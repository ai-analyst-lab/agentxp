"""Agent context-bundle assembly for AgentXP v0.1.

Implements the bundle-snapshot policy from OPENXP_V01_PLAN.md §10.5.9
(H15 / H42) and the per-experiment file layout from §1.8.13. Every agent
invocation gets `bundles/{agent}.ctx.yaml` + `bundles/{agent}.out.yaml`;
project-level YAML dependencies are COPIED (not referenced) into a
`{agent}.ctx.yaml.sources/` sibling directory at assembly time so the
bundle is the source of truth for that invocation. File copies and the
metadata write happen under a shared `project_read_lock` (§10.9) and use
the atomic `_atomic_write_bytes` helper for chmod-600 + tmp-rename.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §1.8.13, §5
(bundle isolation axiom), §10.5.9, §10.9, §1.7.3.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentxp.audit.storage import _atomic_write_bytes
from agentxp.orchestrator.project_lock import project_read_lock


# ─────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────

_BUNDLE_SCHEMA_VERSION = 1
_FILE_MODE = 0o600  # §1.7.3 secrets policy: owner read/write only


# ─────────────────────────────────────────────────────────────────────────
# Public types
# ─────────────────────────────────────────────────────────────────────────


class AgentBundle(BaseModel):
    """In-memory view of a `bundles/{agent}.{ctx,out}.yaml` pair.

    Returned by :meth:`BundleStore.assemble` and :meth:`BundleStore.read_bundle`.
    The pydantic shape is the public contract for downstream agents (W1.1 +
    W1.2 dispatch + agent prompt assembly).
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    agent_name: str
    ctx_path: Path
    out_path: Path  # may not yet exist
    schema_version: int = _BUNDLE_SCHEMA_VERSION
    assembled_at: datetime
    ctx_inputs: dict[str, Any] = Field(default_factory=dict)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    sources_root: Optional[Path] = None

    @field_validator("assembled_at")
    @classmethod
    def _utc_only(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError(
                "assembled_at must be timezone-aware UTC per §1.7.2"
            )
        return v.astimezone(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _sha256_hex(data: bytes) -> str:
    """SHA256 of raw bytes as 64-char lowercase hex (§10.5.9)."""
    return hashlib.sha256(data).hexdigest()


def _relative_to_project(path: Path, project_root: Path) -> Path:
    """Return ``path`` relative to ``project_root`` for `.sources/` layout.

    If ``path`` is not under ``project_root`` (e.g., absolute path outside
    the project), fall back to using just the filename. This keeps the
    `.sources/` tree mirror-shaped without leaking absolute host paths.
    """
    abs_path = path.resolve()
    abs_root = project_root.resolve()
    try:
        return abs_path.relative_to(abs_root)
    except ValueError:
        # Path is outside project_root; flatten to filename so we still
        # capture and hash the dependency without leaking host paths.
        return Path(path.name)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# BundleStore
# ─────────────────────────────────────────────────────────────────────────


class BundleStore:
    """Owner of `experiments/{exp_id}/bundles/` per §1.8.12.

    Single chokepoint for ctx-bundle assembly and out-bundle writes. All
    project-YAML reads are performed under a shared `project_read_lock`
    (§10.9) and copied into the bundle directory (§10.5.9). All writes go
    through `_atomic_write_bytes` (chmod 600, tmp + os.replace).
    """

    def __init__(self, bundles_dir: Path, project_root: Path):
        """Initialize the store.

        Args:
            bundles_dir: ``experiments/{exp_id}/bundles/``. Created on first
                write if it does not exist.
            project_root: The user's experiment project root — the directory
                that holds ``semantic_models/``, ``fact_sources/``,
                ``metrics/``, ``assignments/``, and ``.agentxp/.project.lock``.
        """
        self.bundles_dir = Path(bundles_dir)
        self.project_root = Path(project_root)

    # ── path helpers ────────────────────────────────────────────────────

    def _ctx_path(self, agent_name: str) -> Path:
        return self.bundles_dir / f"{agent_name}.ctx.yaml"

    def _out_path(self, agent_name: str) -> Path:
        return self.bundles_dir / f"{agent_name}.out.yaml"

    def _sources_root(self, agent_name: str) -> Path:
        return self.bundles_dir / f"{agent_name}.ctx.yaml.sources"

    # ── public API ──────────────────────────────────────────────────────

    def assemble(
        self,
        agent_name: str,
        ctx_inputs: dict[str, Any],
        depends_on_project_yamls: Optional[list[Path]] = None,
    ) -> AgentBundle:
        """Assemble `bundles/{agent_name}.ctx.yaml` and return the
        :class:`AgentBundle` view.

        Steps (per §10.5.9):
          1. Acquire shared `project_read_lock(project_root)`.
          2. For each project YAML in ``depends_on_project_yamls``: read raw
             bytes, compute SHA256, atomically write a COPY under
             ``bundles/{agent_name}.ctx.yaml.sources/{relative_path}``.
          3. Atomically write the ctx.yaml carrying schema_version,
             agent_name, assembled_at, ctx_inputs, source_hashes, sources_root.
          4. Every file written is chmod 600.

        The same project YAMLs read twice within the same lock window
        yield identical source_hashes; a file edited between two
        ``assemble()`` calls (with the project_write_lock acquired in
        between) yields different hashes — the audit anchor for §10.6
        row 8 (`referenced_artifact_changed`).
        """
        deps = list(depends_on_project_yamls or [])
        self.bundles_dir.mkdir(parents=True, exist_ok=True)
        sources_root = self._sources_root(agent_name)

        source_hashes: dict[str, str] = {}
        assembled_at = _utcnow()

        with project_read_lock(self.project_root):
            # Step 2: COPY each project YAML into .sources/, recording sha256.
            for dep in deps:
                dep_path = Path(dep)
                raw = dep_path.read_bytes()
                digest = _sha256_hex(raw)
                rel = _relative_to_project(dep_path, self.project_root)
                rel_str = rel.as_posix()
                source_hashes[rel_str] = digest

                dest = sources_root / rel
                _atomic_write_bytes(dest, raw, mode=_FILE_MODE)

            # Step 3: write the ctx.yaml itself.
            ctx_payload: dict[str, Any] = {
                "schema_version": _BUNDLE_SCHEMA_VERSION,
                "agent_name": agent_name,
                "assembled_at": assembled_at.isoformat(),
                "ctx_inputs": ctx_inputs,
                "source_hashes": source_hashes,
                "sources_root": (
                    sources_root.name if deps else None
                ),
            }
            ctx_bytes = yaml.safe_dump(
                ctx_payload, sort_keys=False, default_flow_style=False
            ).encode("utf-8")
            _atomic_write_bytes(self._ctx_path(agent_name), ctx_bytes, mode=_FILE_MODE)

        return AgentBundle(
            agent_name=agent_name,
            ctx_path=self._ctx_path(agent_name),
            out_path=self._out_path(agent_name),
            schema_version=_BUNDLE_SCHEMA_VERSION,
            assembled_at=assembled_at,
            ctx_inputs=dict(ctx_inputs),
            source_hashes=dict(source_hashes),
            sources_root=sources_root if deps else None,
        )

    def read_bundle(
        self,
        agent_name: str,
        kind: Literal["ctx", "out"],
    ) -> AgentBundle:
        """Read back an existing ctx-bundle. ``kind`` selects which path is
        considered authoritative for the metadata fields; ``out`` round-trips
        through the existing ctx.yaml for fields the out.yaml does not carry.

        Raises:
            FileNotFoundError: if the requested artifact does not exist.
        """
        ctx_path = self._ctx_path(agent_name)
        out_path = self._out_path(agent_name)

        if kind == "ctx":
            target = ctx_path
        else:
            target = out_path
        if not target.exists():
            raise FileNotFoundError(f"bundle artifact not found: {target}")

        # Always read ctx.yaml for the metadata (out.yaml carries only the
        # agent's output payload, not the snapshot metadata).
        if not ctx_path.exists():
            raise FileNotFoundError(
                f"bundle ctx.yaml missing for agent {agent_name!r}: {ctx_path}"
            )
        ctx_data = yaml.safe_load(ctx_path.read_bytes()) or {}

        assembled_at_raw = ctx_data.get("assembled_at")
        if isinstance(assembled_at_raw, datetime):
            assembled_at = assembled_at_raw
        elif isinstance(assembled_at_raw, str):
            assembled_at = datetime.fromisoformat(assembled_at_raw)
        else:
            raise ValueError(
                f"ctx.yaml at {ctx_path} missing valid assembled_at"
            )
        if assembled_at.tzinfo is None:
            assembled_at = assembled_at.replace(tzinfo=timezone.utc)

        sources_root_field = ctx_data.get("sources_root")
        if sources_root_field:
            sources_root: Optional[Path] = self._sources_root(agent_name)
        else:
            sources_root = None

        return AgentBundle(
            agent_name=ctx_data.get("agent_name", agent_name),
            ctx_path=ctx_path,
            out_path=out_path,
            schema_version=int(
                ctx_data.get("schema_version", _BUNDLE_SCHEMA_VERSION)
            ),
            assembled_at=assembled_at,
            ctx_inputs=dict(ctx_data.get("ctx_inputs") or {}),
            source_hashes=dict(ctx_data.get("source_hashes") or {}),
            sources_root=sources_root,
        )

    def write_out(self, agent_name: str, payload: BaseModel) -> Path:
        """Atomically write `bundles/{agent_name}.out.yaml` from a pydantic
        model. Returns the path.

        The bundles directory is created on demand so write_out can be
        called even if assemble has not been (e.g., test harness).
        """
        self.bundles_dir.mkdir(parents=True, exist_ok=True)
        data = payload.model_dump(mode="json")
        text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
        out_path = self._out_path(agent_name)
        _atomic_write_bytes(out_path, text.encode("utf-8"), mode=_FILE_MODE)
        return out_path


__all__ = [
    "AgentBundle",
    "BundleStore",
]
