"""Connect helpers — called by .claude/skills/connect-data/SKILL.md.

Wires a warehouse profile to ``~/.agentxp/credentials/<dialect>/<profile>.yaml``.
The wizard is interactive by default; tests pass ``interactive=False`` and
supply an overrides dict.

Public surface:
  - run_wizard(dialect, *, interactive=True, overrides=None) -> Path
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Optional

import yaml


SupportedDialect = Literal["duckdb", "snowflake", "bigquery", "databricks"]


_PROMPT_SPECS: dict[str, list[tuple[str, str, Optional[str]]]] = {
    "duckdb": [
        ("profile_name", "Profile name (e.g. demo)", "demo"),
        ("db_path", "Path to the .duckdb file", None),
    ],
    "snowflake": [
        ("profile_name", "Profile name (e.g. prod)", "prod"),
        ("account", "Account identifier", None),
        ("user", "User", None),
        ("warehouse", "Warehouse name", None),
        ("database", "Database name", None),
        ("schema", "Schema name", "PUBLIC"),
    ],
    "bigquery": [
        ("profile_name", "Profile name (e.g. prod)", "prod"),
        ("project_id", "GCP project id", None),
        ("dataset", "Default dataset", None),
        ("location", "Location (default: US)", "US"),
    ],
    "databricks": [
        ("profile_name", "Profile name (e.g. prod)", "prod"),
        ("host", "Workspace host (https://...)", None),
        ("http_path", "HTTP path", None),
        ("catalog", "Catalog name", None),
        ("schema", "Schema name", "default"),
    ],
}


def _credentials_root() -> Path:
    """Where credential files land. Respects ``$AGENTXP_HOME`` override."""
    base = os.environ.get("AGENTXP_HOME")
    if base:
        return Path(base) / "credentials"
    return Path.home() / ".agentxp" / "credentials"


def _interactive_prompts(dialect: str) -> dict[str, str]:
    """Walk the dialect's prompt list, accepting input() for each field."""
    spec = _PROMPT_SPECS[dialect]
    answers: dict[str, str] = {}
    for key, prompt, default in spec:
        if default is not None:
            raw = input(f"{prompt} [{default}]: ").strip()
            answers[key] = raw or default
        else:
            while True:
                raw = input(f"{prompt}: ").strip()
                if raw:
                    answers[key] = raw
                    break
    return answers


def run_wizard(
    dialect: str,
    *,
    interactive: bool = True,
    overrides: Optional[dict[str, Any]] = None,
) -> Path:
    """Interactive (or scripted) wizard for wiring a warehouse profile.

    With ``interactive=True``, walks ``_PROMPT_SPECS[dialect]`` with
    ``input()`` calls. With ``interactive=False``, requires ``overrides``
    to supply every field the dialect needs.

    Writes ``~/.agentxp/credentials/<dialect>/<profile>.yaml`` and returns
    the path. Existing files are overwritten without prompt (caller's
    responsibility to confirm).

    Raises:
      - :class:`KeyError` for unknown dialects
      - :class:`ValueError` for non-interactive runs with missing fields
    """
    if dialect not in _PROMPT_SPECS:
        raise KeyError(
            f"unknown dialect {dialect!r}; expected one of "
            f"{sorted(_PROMPT_SPECS)}"
        )

    if interactive:
        answers = _interactive_prompts(dialect)
    else:
        if overrides is None:
            raise ValueError(
                "non-interactive runs require overrides dict"
            )
        # Validate all required fields are present
        spec = _PROMPT_SPECS[dialect]
        missing = [k for k, _, default in spec
                   if default is None and k not in overrides]
        if missing:
            raise ValueError(
                f"non-interactive run missing required fields: {missing}"
            )
        answers = {}
        for key, _, default in spec:
            answers[key] = str(overrides.get(key, default or ""))

    profile_name = answers.pop("profile_name")
    out_dir = _credentials_root() / dialect
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{profile_name}.yaml"

    payload = {
        "schema_version": 1,
        "dialect": dialect,
        "profile_name": profile_name,
        **answers,
    }
    out_path.write_text(yaml.safe_dump(payload, sort_keys=False))
    # chmod 600 — credential files contain secrets
    os.chmod(out_path, 0o600)

    return out_path


__all__ = ["run_wizard", "SupportedDialect"]
