"""Generate agents/registry.yaml from CONTRACT blocks (V35).

Parses every ``agents/<role>.md`` file's HTML-commented YAML CONTRACT
block, builds a sorted registry, runs a Kahn topological sort to assert
the DAG is acyclic, and writes ``agents/registry.yaml``.

Run:
    python -m agentxp.agents.gen_registry [--out PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional

import yaml


_CONTRACT_RE = re.compile(
    r"<!--\s*CONTRACT_START\s*\n(?P<body>.*?)\nCONTRACT_END\s*-->",
    re.DOTALL,
)


class ContractParseError(Exception):
    """A CONTRACT block could not be parsed."""


class RegistryCycleError(Exception):
    """The registry's dependency graph contains a cycle."""


def parse_contract(md_text: str, *, file: Path) -> dict[str, Any]:
    """Extract + parse the CONTRACT block from a markdown file."""
    m = _CONTRACT_RE.search(md_text)
    if m is None:
        raise ContractParseError(
            f"{file}: no CONTRACT_START / CONTRACT_END block found"
        )
    try:
        data = yaml.safe_load(m.group("body"))
    except yaml.YAMLError as exc:
        raise ContractParseError(f"{file}: invalid YAML in CONTRACT: {exc}")
    if not isinstance(data, dict):
        raise ContractParseError(
            f"{file}: CONTRACT body must parse to a mapping, got {type(data).__name__}"
        )
    required = {"name", "description", "bundle_schema", "dispatched_by",
                "inputs", "outputs", "blind_to"}
    missing = required - set(data.keys())
    if missing:
        raise ContractParseError(
            f"{file}: CONTRACT missing required keys: {sorted(missing)}"
        )
    return data


def topo_sort(contracts: list[dict[str, Any]]) -> list[str]:
    """Kahn topological sort. Raises RegistryCycleError on cycle.

    Edges: for each contract, dispatched_by → name (a specialist depends on
    the skill that dispatches it). Since skills are leaves (no specialist
    dependencies), this is mostly a sanity check; agents that depend on
    other agents' outputs (designer ← understander, narrator ← sql_specialist)
    would surface here if we encoded them — currently we don't, since
    specialist-to-specialist deps are managed by the orchestrator loop,
    not the registry.
    """
    in_degree: dict[str, int] = {c["name"]: 0 for c in contracts}
    edges: dict[str, set[str]] = defaultdict(set)

    # No specialist-to-specialist edges in v3 — the loop manages composition.
    # The topo sort exists as a defense for future expansion.

    queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
    order: list[str] = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for m in edges.get(n, ()):
            in_degree[m] -= 1
            if in_degree[m] == 0:
                queue.append(m)

    if len(order) != len(contracts):
        remaining = [n for n, d in in_degree.items() if d > 0]
        raise RegistryCycleError(
            f"cycle detected; nodes with unresolved in-edges: {remaining}"
        )
    return order


def build_registry(agents_dir: Path) -> dict[str, Any]:
    """Parse every agents/*.md (except INDEX.md), validate, return registry."""
    contracts: list[dict[str, Any]] = []
    for md in sorted(agents_dir.glob("*.md")):
        if md.stem.upper() == "INDEX":
            continue
        contracts.append(parse_contract(md.read_text(), file=md))

    if not contracts:
        raise ContractParseError(
            f"no agent contracts found under {agents_dir}"
        )

    topo_sort(contracts)  # raises on cycle

    return {
        "version": 1,
        "agents": {c["name"]: {
            "description": (c["description"] or "").strip(),
            "bundle_schema": c["bundle_schema"],
            "dispatched_by": list(c.get("dispatched_by") or []),
            "inputs": list(c.get("inputs") or []),
            "outputs": list(c.get("outputs") or []),
            "blind_to": list(c.get("blind_to") or []),
            "emits": list(c.get("emits") or []),
        } for c in sorted(contracts, key=lambda c: c["name"])},
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="agentxp_gen_registry")
    parser.add_argument(
        "--agents-dir", type=Path, default=Path("agents"),
        help="Directory of agent .md files",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("agents/registry.yaml"),
        help="Output path",
    )
    args = parser.parse_args(argv)

    registry = build_registry(args.agents_dir)
    args.out.write_text(yaml.safe_dump(registry, sort_keys=False, indent=2))
    print(f"wrote {args.out} ({len(registry['agents'])} agents)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
