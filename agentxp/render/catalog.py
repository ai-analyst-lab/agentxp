"""Renders catalog — append-only hash chain for share-tail renders (T50/T51).

Every readout produced by the presentation spine appends one entry to
``experiments/<id>/readouts/catalog.jsonl``. Each entry carries
``prev_catalog_entry_hash`` (sha256 of the previous entry's canonical JSON);
the chain is independently walkable. Tampering with any entry breaks the
chain at the offending position.

The catalog is the only hash chain that survives in v2 — ``validate_chain``
on the experiment-state side is gone (single user, git is the spec). But
renders have a real supersession history (a brief edits after a mid-run
readout was rendered; the mid-run readout's status cascades to DRAFT) that
git alone does not express, so the catalog earns its keep.

Events (closed Literal set):
  - RenderCompleted        a new readout landed
  - RenderSuperseded       a re-render replaced a prior render of the same kind
  - RenderBriefDriftFlagged a render was found to point at a now-edited brief
  - PruneCompleted         old renders were garbage-collected

``build_index(project_root)`` walks every experiment's catalog and composes
a static HTML navigator at ``readouts/index.html`` — the cross-experiment
audit surface comes for free from the catalog.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentxp.schemas._types import Sha256Hex


# ─────────────────────────────────────────────────────────────────────────────
# Event payloads
# ─────────────────────────────────────────────────────────────────────────────


class _BaseEvent(BaseModel):
    """Common base for catalog event payloads."""

    model_config = ConfigDict(extra="forbid")
    event: str  # set by each subclass via Literal


class RenderCompletedEvent(_BaseEvent):
    event: Literal["RenderCompleted"] = "RenderCompleted"
    readout_type: Literal["intent", "design_brief", "monitor_check", "verdict", "audit"]
    audience: Literal["exec", "operator", "engineer"]
    format: Literal["html", "md", "png", "json", "pdf"]
    path: str  # relative to experiments/<id>/
    vm_sha256: Sha256Hex  # hash of the rendered VM contents
    provenance_render_status: Literal["VERIFIED", "DRAFT_UNVERIFIED", "UNVERIFIABLE"]


class RenderSupersededEvent(_BaseEvent):
    event: Literal["RenderSuperseded"] = "RenderSuperseded"
    superseded_path: str
    new_path: str
    reason: str


class RenderBriefDriftFlaggedEvent(_BaseEvent):
    event: Literal["RenderBriefDriftFlagged"] = "RenderBriefDriftFlagged"
    render_path: str
    brief_path: str
    sealed_design_chain_hash: Sha256Hex
    current_design_chain_hash: Sha256Hex


class PruneCompletedEvent(_BaseEvent):
    event: Literal["PruneCompleted"] = "PruneCompleted"
    pruned_paths: list[str]
    bytes_freed: int
    policy: str  # which retention policy fired


# ─────────────────────────────────────────────────────────────────────────────
# CatalogEntry — the on-disk row shape
# ─────────────────────────────────────────────────────────────────────────────


class CatalogEntry(BaseModel):
    """One row in ``experiments/<id>/readouts/catalog.jsonl``.

    The catalog is one entry per line, JSON-encoded. ``prev_catalog_entry_hash``
    points at the sha256 of the prior entry's canonical-JSON bytes (or
    ``"genesis"`` for the very first entry).
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1

    entry_id: str  # ULID
    experiment_id: str
    timestamp: datetime
    prev_catalog_entry_hash: str  # Sha256Hex OR the literal "genesis"
    payload: (
        RenderCompletedEvent
        | RenderSupersededEvent
        | RenderBriefDriftFlaggedEvent
        | PruneCompletedEvent
    ) = Field(discriminator="event")

    @field_validator("timestamp")
    @classmethod
    def _utc_only(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware UTC")
        return v.astimezone(timezone.utc)

    @field_validator("prev_catalog_entry_hash")
    @classmethod
    def _hash_or_genesis(cls, v: str) -> str:
        if v == "genesis":
            return v
        if len(v) != 64 or not all(c in "0123456789abcdef" for c in v):
            raise ValueError(
                "prev_catalog_entry_hash must be 'genesis' or a 64-char "
                "lowercase hex sha256"
            )
        return v


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _canonical_bytes(entry: CatalogEntry) -> bytes:
    """Canonical JSON bytes for an entry (sorted keys; ISO timestamps)."""
    dump = json.loads(entry.model_dump_json())
    return json.dumps(dump, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_entries(catalog_path: Path) -> list[CatalogEntry]:
    """Parse all entries from a catalog file. Returns empty list if absent."""
    if not catalog_path.exists():
        return []
    entries: list[CatalogEntry] = []
    with catalog_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(CatalogEntry.model_validate_json(line))
    return entries


# ─────────────────────────────────────────────────────────────────────────────
# Public API — append / validate
# ─────────────────────────────────────────────────────────────────────────────


def catalog_append(
    *,
    catalog_path: Path,
    experiment_id: str,
    entry_id: str,
    payload: RenderCompletedEvent
    | RenderSupersededEvent
    | RenderBriefDriftFlaggedEvent
    | PruneCompletedEvent,
    timestamp: Optional[datetime] = None,
) -> CatalogEntry:
    """Append a new entry to a catalog file. Returns the constructed entry.

    Computes ``prev_catalog_entry_hash`` by reading the existing tail of
    the catalog (or ``"genesis"`` if empty), then atomically appends the
    new line. Atomicity at the file level uses open-append: a single
    fwrite of a complete JSON line under O_APPEND is atomic enough for a
    single-user CLI; we do not need fsync gymnastics.
    """
    catalog_path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_entries(catalog_path)
    if existing:
        prev_hash = _sha256_hex(_canonical_bytes(existing[-1]))
    else:
        prev_hash = "genesis"

    entry = CatalogEntry(
        entry_id=entry_id,
        experiment_id=experiment_id,
        timestamp=timestamp or datetime.now(timezone.utc),
        prev_catalog_entry_hash=prev_hash,
        payload=payload,
    )

    with catalog_path.open("a") as f:
        f.write(entry.model_dump_json() + "\n")

    return entry


class CatalogChainBreak(Exception):
    """validate_catalog found a break in the prev_catalog_entry_hash chain.

    Carries the index of the first broken entry, the expected hash, and
    the entry's claimed prev_hash. Used to surface tampering or partial
    writes.
    """

    def __init__(self, *, index: int, expected: str, claimed: str):
        self.index = index
        self.expected = expected
        self.claimed = claimed
        super().__init__(
            f"catalog chain break at entry {index}: expected prev_hash="
            f"{expected[:12]}…, got {claimed[:12]}…"
        )


def validate_catalog(catalog_path: Path) -> None:
    """Walk the catalog chain; raise CatalogChainBreak on first break.

    Returns None on success. The chain is valid iff every entry's
    ``prev_catalog_entry_hash`` equals the sha256 of the prior entry's
    canonical bytes (with ``"genesis"`` for the first entry).
    """
    entries = _read_entries(catalog_path)
    expected = "genesis"
    for i, entry in enumerate(entries):
        if entry.prev_catalog_entry_hash != expected:
            raise CatalogChainBreak(
                index=i,
                expected=expected,
                claimed=entry.prev_catalog_entry_hash,
            )
        expected = _sha256_hex(_canonical_bytes(entry))


# ─────────────────────────────────────────────────────────────────────────────
# Cross-experiment index navigator
# ─────────────────────────────────────────────────────────────────────────────


class CatalogIndexRow(BaseModel):
    """One row in the cross-experiment index — the worst-case status across
    an experiment's renders, plus the verdict if known."""

    model_config = ConfigDict(extra="forbid")
    experiment_id: str
    n_renders: int
    worst_status: Literal["VERIFIED", "DRAFT_UNVERIFIED", "UNVERIFIABLE"]
    latest_render_type: Optional[str] = None
    latest_render_at: Optional[str] = None  # ISO-8601


_STATUS_RANK = {"VERIFIED": 0, "DRAFT_UNVERIFIED": 1, "UNVERIFIABLE": 2}


def _summarize_catalog(catalog_path: Path, experiment_id: str) -> CatalogIndexRow:
    entries = _read_entries(catalog_path)
    completed = [
        e for e in entries
        if isinstance(e.payload, RenderCompletedEvent)
    ]
    if not completed:
        return CatalogIndexRow(
            experiment_id=experiment_id,
            n_renders=0,
            worst_status="UNVERIFIABLE",
        )

    statuses = [e.payload.provenance_render_status for e in completed]
    worst = max(statuses, key=lambda s: _STATUS_RANK[s])
    latest = completed[-1]
    return CatalogIndexRow(
        experiment_id=experiment_id,
        n_renders=len(completed),
        worst_status=worst,
        latest_render_type=latest.payload.readout_type,
        latest_render_at=latest.timestamp.isoformat(),
    )


def build_index(project_root: Path) -> list[CatalogIndexRow]:
    """Walk every experiment's catalog and return summary rows.

    Used by ``agentxp readouts --index`` to regenerate the static HTML
    navigator at ``readouts/index.html``. Pure projection — no rendering
    happens here; an HTML adapter consumes the rows.
    """
    exp_root = project_root / "experiments"
    if not exp_root.exists():
        return []

    rows: list[CatalogIndexRow] = []
    for exp_dir in sorted(exp_root.iterdir()):
        if not exp_dir.is_dir():
            continue
        catalog_path = exp_dir / "readouts" / "catalog.jsonl"
        rows.append(_summarize_catalog(catalog_path, exp_dir.name))
    return rows


__all__ = [
    # Event payloads
    "RenderCompletedEvent",
    "RenderSupersededEvent",
    "RenderBriefDriftFlaggedEvent",
    "PruneCompletedEvent",
    # Entry + errors
    "CatalogEntry",
    "CatalogChainBreak",
    # Public API
    "catalog_append",
    "validate_catalog",
    # Index
    "CatalogIndexRow",
    "build_index",
]
