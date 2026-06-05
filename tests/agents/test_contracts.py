"""V36 — Closure tests for agent CONTRACT blocks + registry.yaml.

For each specialist prompt under ``agents/``:
  1. CONTRACT block parses cleanly.
  2. Named ``bundle_schema`` exists in ``BUNDLE_SCHEMAS``.
  3. ``blind_to`` field names are a subset of ``BLINDNESS_MANIFEST[role]``.
  4. Every ``dispatched_by`` entry resolves to a real
     ``.claude/skills/<name>/SKILL.md`` file.
  5. ``agents/registry.yaml`` generates + topo-sorts without cycle.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentxp.agents.gen_registry import (
    build_registry,
    parse_contract,
    topo_sort,
)
from agentxp.schemas.bundles import BLINDNESS_MANIFEST, BUNDLE_SCHEMAS


_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENTS_DIR = _REPO_ROOT / "agents"
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"


def _specialist_md_files() -> list[Path]:
    return [p for p in sorted(_AGENTS_DIR.glob("*.md"))
            if p.stem.upper() != "INDEX"]


def _contracts() -> list[dict]:
    return [parse_contract(p.read_text(), file=p) for p in _specialist_md_files()]


@pytest.mark.parametrize("md_file", _specialist_md_files(),
                         ids=lambda p: p.stem)
def test_contract_parses(md_file):
    """CONTRACT_START / CONTRACT_END block parses without raising."""
    parse_contract(md_file.read_text(), file=md_file)


@pytest.mark.parametrize("contract", _contracts(),
                         ids=lambda c: c["name"])
def test_bundle_schema_exists(contract):
    """The named bundle_schema is registered in BUNDLE_SCHEMAS."""
    schema_name = contract["bundle_schema"]
    role = contract["name"]
    assert role in BUNDLE_SCHEMAS, (
        f"role {role!r} not in BUNDLE_SCHEMAS; "
        f"registered: {sorted(BUNDLE_SCHEMAS)}"
    )
    cls = BUNDLE_SCHEMAS[role]
    assert cls.__name__ == schema_name, (
        f"role {role!r}: contract names {schema_name!r}, "
        f"BUNDLE_SCHEMAS gives {cls.__name__!r}"
    )


@pytest.mark.parametrize("contract", _contracts(),
                         ids=lambda c: c["name"])
def test_blind_to_subset_of_manifest(contract):
    """Every blind_to field appears in BLINDNESS_MANIFEST for the role."""
    role = contract["name"]
    declared = set(contract["blind_to"])
    manifest_entries = set(BLINDNESS_MANIFEST.get(role, []))
    extras = declared - manifest_entries
    assert not extras, (
        f"{role}: contract names blind_to fields not in BLINDNESS_MANIFEST: {extras}"
    )


@pytest.mark.parametrize("contract", _contracts(),
                         ids=lambda c: c["name"])
def test_dispatched_by_resolves_to_real_skills(contract):
    """Every dispatched_by entry is a directory under .claude/skills/."""
    role = contract["name"]
    for skill in contract.get("dispatched_by", []):
        skill_path = _SKILLS_DIR / skill / "SKILL.md"
        assert skill_path.exists(), (
            f"{role}: dispatched_by={skill!r} does not exist at {skill_path}"
        )


def test_registry_generates_without_cycle():
    """build_registry() succeeds and includes all 5 specialists."""
    registry = build_registry(_AGENTS_DIR)
    assert registry["version"] == 1
    names = set(registry["agents"].keys())
    assert names == {"understander", "designer", "critic",
                     "sql_specialist", "analyst_narrator"}


def test_topo_sort_no_cycle():
    """The current contracts topologically sort."""
    contracts = _contracts()
    order = topo_sort(contracts)
    assert len(order) == len(contracts)
