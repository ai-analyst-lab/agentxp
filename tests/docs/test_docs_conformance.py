"""Docs ↔ code conformance.

Guards against the failure mode where user-facing docs advertise commands that
do not exist (e.g. ``agentxp /experiment``, ``agentxp brief``, ``agentxp
/analyze`` — all of which once appeared in QUICKSTART but were never real
subcommands). Every ``agentxp <subcommand>`` shown in a fenced code block of a
user-facing doc must resolve to a registered subcommand or a top-level flag.

Scope (the rubric D6 bar): README.md, docs/QUICKSTART.md, docs/snowflake-setup.md.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentxp.cli.__main__ import SUBCOMMANDS

REPO_ROOT = Path(__file__).resolve().parents[2]

USER_FACING_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "QUICKSTART.md",
    REPO_ROOT / "docs" / "snowflake-setup.md",
]

# Top-level flags the dispatcher accepts before any subcommand.
TOPLEVEL_FLAGS = {"-h", "--help", "-V", "--version"}

# Matches `agentxp <token>` where <token> is the next whitespace-delimited word.
# Requires whitespace after `agentxp` so `pip install 'agentxp[snowflake]'`
# (no trailing space) is not matched.
_INVOCATION_RE = re.compile(r"\bagentxp\s+(\S+)")


def _invocations(doc: Path) -> list[tuple[int, str]]:
    """Return (1-based line number, subcommand-token) for each `agentxp <tok>`
    appearing inside a fenced code block of ``doc``."""
    numbered: list[tuple[int, str]] = []
    in_fence = False
    for i, line in enumerate(doc.read_text().splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        for m in _INVOCATION_RE.finditer(line):
            numbered.append((i, m.group(1)))
    return numbered


@pytest.mark.parametrize("doc", USER_FACING_DOCS, ids=lambda p: p.name)
def test_documented_agentxp_commands_exist(doc):
    assert doc.exists(), f"expected user-facing doc missing: {doc}"
    bad: list[str] = []
    for lineno, token in _invocations(doc):
        # Placeholder like <subcommand> / <dialect> / <name>.
        if token.startswith("<") and token.endswith(">"):
            continue
        # Top-level or subcommand flag (e.g. --version, --help).
        if token.startswith("-"):
            if token in TOPLEVEL_FLAGS:
                continue
            # A flag immediately after `agentxp` that isn't top-level is wrong.
            bad.append(f"{doc.name}:{lineno} — `agentxp {token}` (unknown top-level flag)")
            continue
        if token not in SUBCOMMANDS:
            bad.append(f"{doc.name}:{lineno} — `agentxp {token}` is not a registered subcommand")
    assert not bad, "Docs reference non-existent agentxp commands:\n" + "\n".join(bad)
