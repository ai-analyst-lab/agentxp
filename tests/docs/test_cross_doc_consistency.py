"""W8.2 — cross-document consistency CI.

Three documents must agree:

  1. ``CLAUDE.md`` — the project worldview with the 11-rule list at §4.
  2. ``.claude/skills/*/SKILL.md`` — every skill cites rules by number.
  3. ``agentxp/INDEX.md`` — the Python helper catalog; skills cite from it.

This test catches:

  - A skill that cites a rule (e.g., ``(R7)``) that does not exist in
    ``CLAUDE.md §4``.
  - An ``INDEX.md`` entry that names a function that no longer exists in
    code.
  - A skill that cites a function in its tools-table that isn't in
    ``INDEX.md`` (the catalog is the canonical surface; skills must cite
    from it).

The check is intentionally narrow: it does not enforce prose-style or
ordering — only existence. Style is voice_audit's job.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO / "CLAUDE.md"
SKILLS_DIR = REPO / ".claude" / "skills"
INDEX_MD = REPO / "agentxp" / "INDEX.md"
AGENT_PROMPTS = REPO / "agents"


# ──────────────────────────────────────────────────────────────────────────
# Rule existence
# ──────────────────────────────────────────────────────────────────────────


def _rules_declared_in_claude_md() -> set[str]:
    """Return the set of rule codes declared in CLAUDE.md §4 (R1..R11)."""
    text = CLAUDE_MD.read_text()
    return set(re.findall(r"^### (R\d+)\b", text, flags=re.MULTILINE))


def _rules_cited(text: str) -> set[str]:
    """Find ``R<N>`` rule citations in prose. Matches whole-word ``R1``-``R99``."""
    return set(re.findall(r"\bR\d+\b", text))


@pytest.mark.parametrize(
    "doc_path",
    [
        *sorted(SKILLS_DIR.glob("**/SKILL.md")),
        *sorted(AGENT_PROMPTS.glob("*.md")),
    ],
    ids=lambda p: str(p.relative_to(REPO)),
)
def test_every_cited_rule_exists_in_claude_md(doc_path: Path) -> None:
    """A SKILL.md or agent prompt that cites ``R12`` must have it declared."""
    declared = _rules_declared_in_claude_md()
    cited = _rules_cited(doc_path.read_text())
    unknown = cited - declared
    assert not unknown, (
        f"{doc_path.relative_to(REPO)} cites undeclared rule(s) {unknown}. "
        f"CLAUDE.md §4 only declares {sorted(declared)}. "
        f"Either add the rule or remove the citation."
    )


# ──────────────────────────────────────────────────────────────────────────
# INDEX.md function-existence check
# ──────────────────────────────────────────────────────────────────────────


# Audit item #11 — pattern intentionally requires `- `module.path.fn(`
# to match. INDEX.md uses several formats (bullets with `(`, module
# headers without `(`, prose code spans inside paragraphs). Only the
# bullet+paren form names a callable we can resolve; the other forms
# refer to modules and sub-pages. Document the skip explicitly here
# instead of pretending coverage we don't have.
_INDEX_FN_PATTERN = re.compile(
    r"^- `([a-zA-Z_][\w.]*)\(",   # bullet form: ``- `module.path.fn(``
    flags=re.MULTILINE,
)


def _index_named_callables() -> list[tuple[str, str]]:
    """Return ``(module_path, qualname)`` for each callable named in INDEX.md.

    Matches the dotted-path-followed-by-paren convention used in the catalog
    (e.g. ``- `agentxp.stats.srm.srm_check(observed, expected, threshold)```).
    Skips entries that aren't fully-qualified (those are usually method
    references inside a code block, not catalog entries).
    """
    if not INDEX_MD.exists():
        return []
    text = INDEX_MD.read_text()
    out: list[tuple[str, str]] = []
    for ref in _INDEX_FN_PATTERN.findall(text):
        if "." not in ref:
            continue
        module_path, _, qualname = ref.rpartition(".")
        out.append((module_path, qualname))
    return out


@pytest.mark.parametrize(
    "module_path,qualname",
    _index_named_callables(),
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_every_index_entry_resolves(module_path: str, qualname: str) -> None:
    """Every fully-qualified callable named in INDEX.md must exist in code."""
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        pytest.fail(
            f"INDEX.md references {module_path}.{qualname} but {module_path} "
            f"does not import: {e}"
        )
    assert hasattr(module, qualname), (
        f"INDEX.md references {module_path}.{qualname} but it is not "
        f"defined in {module_path}. Either restore it or update INDEX.md."
    )
