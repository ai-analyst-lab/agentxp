"""Persistence helpers for ``experiments/{exp_id}/queries/{ulid}.yaml`` (§13).

The :class:`agentxp.sql.schema.QueryArtifact` is the audit anchor for every
dispatched SQL attempt — accepted, edited, rejected, blocked, or errored. This
module handles atomic write + chmod-600 enforcement, schema-validated read,
sorted listing, and ULID generation for new filenames.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §13.
"""
from __future__ import annotations

import secrets
from pathlib import Path

import yaml

from agentxp.audit.storage import _atomic_write_bytes
from agentxp.sql.schema import QueryArtifact


# ──────────────────────────────────────────────────────────────────────────
# ULID generation (Crockford base32, 26 chars).
#
# We use the standard Crockford alphabet so the IDs sort lexicographically
# in the same order as their creation timestamp (when generated with a
# timestamp-prefixed ULID). v0.1 uses a random-only 26-char id which is
# sufficient for uniqueness within an experiment; timestamp prefix can be
# added later without changing the file layout.
# ──────────────────────────────────────────────────────────────────────────


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # 32 chars; no I,L,O,U


def _new_query_ulid() -> str:
    """Return a fresh 26-character Crockford-base32 query id.

    Not a true timestamp-ULID in v0.1 — purely random over the 26-char
    alphabet. The filename only needs to be unique within
    ``experiments/{exp_id}/queries/``; lexicographic ordering by timestamp
    is provided by ``QueryArtifact.proposed_at`` inside the YAML.
    """
    return "".join(secrets.choice(_CROCKFORD) for _ in range(26))


# ──────────────────────────────────────────────────────────────────────────
# Read / write / list
# ──────────────────────────────────────────────────────────────────────────


def write_query_artifact(artifact: QueryArtifact, exp_dir: Path) -> Path:
    """Atomically write ``artifact`` to ``exp_dir/queries/{query_id}.yaml``.

    Auto-creates the ``queries/`` subdirectory. The file is chmod 600 on
    creation (per :func:`agentxp.audit.storage._atomic_write_bytes`). Returns
    the absolute path written.
    """
    queries_dir = exp_dir / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)

    target = queries_dir / f"{artifact.query_id}.yaml"

    # Round-trip through pydantic JSON mode so datetimes / enums serialise
    # cleanly, then dump as YAML for the on-disk format.
    payload = artifact.model_dump(mode="json")
    data = yaml.safe_dump(payload, sort_keys=False).encode("utf-8")

    _atomic_write_bytes(target, data, mode=0o600)
    return target


def read_query_artifact(path: Path) -> QueryArtifact:
    """Load + validate a QueryArtifact YAML from disk."""
    with open(path, "rb") as f:
        raw = yaml.safe_load(f)
    return QueryArtifact.model_validate(raw)


def list_query_artifacts(exp_dir: Path) -> list[Path]:
    """Return a lexicographically-sorted list of ``queries/*.yaml`` paths.

    Returns an empty list if the ``queries/`` subdirectory does not exist
    yet — fresh experiments have no artifacts until the first dispatch.
    """
    queries_dir = exp_dir / "queries"
    if not queries_dir.is_dir():
        return []
    return sorted(queries_dir.glob("*.yaml"))


__all__ = [
    "write_query_artifact",
    "read_query_artifact",
    "list_query_artifacts",
    "_new_query_ulid",
]
