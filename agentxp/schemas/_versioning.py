"""Schema-version registry + load-refusal helpers for AgentXP v0.1.

Single source of truth for which ``schema_version`` of each persisted YAML/JSON
file is supported by this AgentXP version. Loading a file with
``schema_version > MAX_SUPPORTED[file_pattern]`` raises ``SchemaVersionTooNew``;
``schema_version < MIN_SUPPORTED[file_pattern]`` raises ``SchemaVersionTooOld``;
a missing or non-integer ``schema_version`` raises ``SchemaVersionMissing``.

Source spec:
  - experimentation-platform/OPENXP_V01_PLAN.md §1.7.6 (canonical schema_version policy)
  - experimentation-platform/OPENXP_V01_PLAN.md §1.8.6 (canonical per-file constants)
  - experimentation-platform/OPENXP_V01_PLAN.md §6.5   (longer-form evolution policy)
  - experimentation-platform/OPENXP_V01_PLAN.md §10.5  (failure-mode wiring;
                                                       load-refusal raises a
                                                       named error)

Closure invariant: the entries in ``MAX_SUPPORTED`` match the per-file
pydantic ``schema_version: Literal[N] = N`` defaults across the schema modules.
Drift is caught by ``tests/schemas/test_versioning.py::
test_max_supported_table_matches_per_file_models``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────────────────
# Canonical MAX_SUPPORTED table per §1.7.6 / §1.8.6 — locked at v0.1 release.
#
# Update this dict in lockstep with the §1.7.6 table. The 16 entries below
# match the 16 rows of the §1.7.6 table row-for-row (the §1.8.6 short form
# folds `conversation.jsonl` and `log.jsonl` into one row and folds
# `bundles/*.ctx.yaml` + `bundles/*.out.yaml` into one row; §1.7.6 is the
# authoritative consolidated reference and is what this registry encodes).
# ──────────────────────────────────────────────────────────────────────────


MAX_SUPPORTED: dict[str, int] = {
    "state.yaml": 3,
    "experiment.yaml": 2,
    "data_plan.yaml": 2,
    "metrics/*.yaml": 2,
    "semantic_models/*.yaml": 1,
    "fact_sources/*.yaml": 1,
    "assignments/*.yaml": 1,
    "decisions/*.yaml": 1,
    "analyses/*.json": 1,
    "interpretation.json": 1,
    "report.json": 1,
    "bundles/{agent}.ctx.yaml": 1,
    "bundles/{agent}.out.yaml": 1,
    "queries/{ulid}.yaml": 1,
    "conversation.jsonl": 1,  # per-line schema_version
    "log.jsonl": 1,  # per-line schema_version
}
"""Max ``schema_version`` this AgentXP can load for each persisted file pattern.

Keys are file patterns (literal names + glob/template placeholders) and match
the §1.7.6 / §1.8.6 row labels verbatim. The 16-row count is closure-tested.
"""


MIN_SUPPORTED: dict[str, int] = {key: 1 for key in MAX_SUPPORTED}
"""Minimum ``schema_version`` this AgentXP accepts. v0.1 has no v0 grace period."""


# ──────────────────────────────────────────────────────────────────────────
# Exception hierarchy. The named-error contract in §1.7.6 / §10.5 requires
# message text that points at the corrective action: upgrade or migrate.
# ──────────────────────────────────────────────────────────────────────────


class SchemaVersionError(Exception):
    """Base class for schema_version-related load refusals."""


class SchemaVersionTooNew(SchemaVersionError):
    """File was written by a newer AgentXP. Upgrade with: ``pip install --upgrade agentxp``."""


class SchemaVersionTooOld(SchemaVersionError):
    """File was written by an older AgentXP. Run: ``agentxp migrate state <exp_id>``."""


class SchemaVersionMissing(SchemaVersionError):
    """File lacks a ``schema_version`` field, or it is non-integer."""


# ──────────────────────────────────────────────────────────────────────────
# Pattern matching for the file-pattern keys.
#
# The keys in MAX_SUPPORTED are a small fixed set, so we match by hand against
# (a) exact filename (e.g. "state.yaml"), (b) glob-style "{dir}/*.{ext}"
# (e.g. "metrics/*.yaml"), and (c) template-style "{dir}/{name}.{ext}"
# (e.g. "bundles/{agent}.ctx.yaml", "queries/{ulid}.yaml").
# ──────────────────────────────────────────────────────────────────────────


def _match_pattern(file_path: Path) -> str | None:
    """Return the MAX_SUPPORTED key matching ``file_path``, or None.

    Matching rules:
      - exact filename match (e.g. ``state.yaml``) wins if the path's
        basename equals the pattern,
      - else for patterns containing ``/``, match against directory + suffix.

    Patterns that look like ``bundles/{agent}.ctx.yaml`` and
    ``bundles/{agent}.out.yaml`` are differentiated by the trailing
    ``.ctx.yaml`` / ``.out.yaml`` substring.
    """
    name = file_path.name
    parts = file_path.parts

    # Pass 1 — exact filename matches (no glob/template metacharacters).
    for pattern in MAX_SUPPORTED:
        if "*" not in pattern and "{" not in pattern and "/" not in pattern:
            if name == pattern:
                return pattern

    # Pass 2 — bundles/{agent}.ctx.yaml and bundles/{agent}.out.yaml.
    # Differentiated by the dotted compound suffix so they never collide.
    if "bundles" in parts:
        if name.endswith(".ctx.yaml"):
            return "bundles/{agent}.ctx.yaml"
        if name.endswith(".out.yaml"):
            return "bundles/{agent}.out.yaml"

    # Pass 3 — queries/{ulid}.yaml — any .yaml under a queries/ directory.
    if "queries" in parts and name.endswith(".yaml"):
        return "queries/{ulid}.yaml"

    # Pass 4 — generic "{dir}/*.{ext}" globs.
    for pattern in MAX_SUPPORTED:
        if "*" in pattern and "/" in pattern:
            base, leaf = pattern.split("/", 1)
            # leaf is "*.{ext}"; pull off the extension after the dot.
            if leaf.startswith("*.") and base in parts and name.endswith(leaf[1:]):
                return pattern

    return None


# ──────────────────────────────────────────────────────────────────────────
# check_schema_version — the single public load-refusal helper.
# ──────────────────────────────────────────────────────────────────────────


def check_schema_version(file_path: Path, raw_data: dict[str, Any]) -> int:
    """Validate ``raw_data['schema_version']`` against the registry for ``file_path``.

    Returns the ``schema_version`` value when valid. Raises:

    - ``SchemaVersionMissing`` if the field is absent or non-integer.
    - ``SchemaVersionTooNew`` if ``schema_version > MAX_SUPPORTED[pattern]``.
    - ``SchemaVersionTooOld`` if ``schema_version < MIN_SUPPORTED[pattern]``.

    For file paths whose pattern is not in the registry, the function is
    permissive: it returns the version unchanged. This is intentional — the
    registry is the source of truth for *known* file types; an unknown path
    is a caller-side bug to flag elsewhere, not a load refusal here.
    """
    if "schema_version" not in raw_data:
        raise SchemaVersionMissing(
            f"File {file_path} lacks a top-level 'schema_version' field. "
            f"This file is unreadable by AgentXP v0.1. If you wrote it by hand, "
            f"add 'schema_version: <N>' at the top per OPENXP_V01_PLAN.md §1.7.6."
        )

    version = raw_data["schema_version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise SchemaVersionMissing(
            f"File {file_path} has non-integer schema_version={version!r}. "
            f"Must be int per OPENXP_V01_PLAN.md §1.7.6."
        )

    pattern = _match_pattern(file_path)
    if pattern is None:
        # Unrecognized file pattern — permissive pass-through.
        return version

    max_supported = MAX_SUPPORTED[pattern]
    min_supported = MIN_SUPPORTED[pattern]

    if version > max_supported:
        raise SchemaVersionTooNew(
            f"File {file_path} has schema_version={version}, but this AgentXP "
            f"supports up to {max_supported} for {pattern!r}. "
            f"This file was written by a newer AgentXP. "
            f"Upgrade with: pip install --upgrade agentxp"
        )

    if version < min_supported:
        raise SchemaVersionTooOld(
            f"File {file_path} has schema_version={version}, but this AgentXP "
            f"requires at least {min_supported} for {pattern!r}. "
            f"This file was written by an older AgentXP. "
            f"Run: agentxp migrate state <exp_id>"
        )

    return version


__all__ = [
    "MAX_SUPPORTED",
    "MIN_SUPPORTED",
    "SchemaVersionError",
    "SchemaVersionTooNew",
    "SchemaVersionTooOld",
    "SchemaVersionMissing",
    "check_schema_version",
]
