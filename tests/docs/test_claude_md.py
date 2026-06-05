"""V41 — Linkcheck + R1-R11 closure + voice + length tests for CLAUDE.md.

Four invariants:
  1. Length: ≤ 200 lines.
  2. Linkcheck: every file path cited in CLAUDE.md exists on disk.
  3. R-rule closure: every R<N> referenced elsewhere in the codebase
     appears in CLAUDE.md §4.
  4. Voice audit: banned phrases do not appear in CLAUDE.md outside the
     "Voice" section that documents the ban itself.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"

# Match Markdown inline code spans that look like file refs:
#   `agentxp/render/voice_audit.py`
#   `agents/critic.md`
_FILE_REF_RE = re.compile(
    r"`([a-zA-Z][a-zA-Z0-9_./-]+\.(?:py|md|yaml|json|jsonl))`"
)

# Match R<N> references like "R1", "R11", "(R7)"
_R_RULE_RE = re.compile(r"\bR(1[0-1]|[1-9])\b")


def _claude_text() -> str:
    return _CLAUDE_MD.read_text()


def test_claude_md_under_200_lines():
    lines = _claude_text().splitlines()
    assert len(lines) <= 200, (
        f"CLAUDE.md has {len(lines)} lines; the v3 ceiling is 200 (see V3_DESIGN.md §12)"
    )


def test_claude_md_linkcheck():
    """Every backtick-quoted file path in CLAUDE.md exists.

    Skips path-pattern citations (anything containing ``*``, ``<``,
    ``>``, ``[``) since those are templates, not real paths. Also skips
    per-experiment artifact names that land under ``experiments/<id>/``
    at runtime (brief.yaml, brief.sealed.yaml, log.md, report.md,
    report.json, analyses/*.json, queries/*.yaml, catalog.jsonl).
    """
    text = _claude_text()
    refs = set(_FILE_REF_RE.findall(text))
    # Per-experiment artifact filenames — never exist at the repo root.
    runtime_artifacts = {
        "brief.yaml", "brief.sealed.yaml", "log.md", "report.md",
        "report.json", "catalog.jsonl", "intent.yaml", "hypothesis.yaml",
        "data_plan.yaml", "analysis.json", "interpretation.json",
    }
    missing: list[str] = []
    for ref in sorted(refs):
        if any(c in ref for c in ("*", "<", ">", "[")):
            continue
        if ref in runtime_artifacts:
            continue
        path = _REPO_ROOT / ref
        if not path.exists():
            missing.append(ref)
    assert not missing, (
        f"CLAUDE.md references files that do not exist: {missing}"
    )


def test_claude_md_r_rule_closure():
    """Every R<N> cited in agents/ or .claude/skills/ appears in CLAUDE.md §4."""
    text = _claude_text()
    declared_rules = set(_R_RULE_RE.findall(text))
    # Convert to ints for sane comparison; declared_rules has the digit part.
    declared = {f"R{n}" for n in declared_rules}

    cited_rules: set[str] = set()
    for md_root in (_REPO_ROOT / "agents", _REPO_ROOT / ".claude" / "skills"):
        for md in md_root.rglob("*.md"):
            content = md.read_text()
            for n in _R_RULE_RE.findall(content):
                cited_rules.add(f"R{n}")

    missing = cited_rules - declared
    assert not missing, (
        f"Rules cited in agents/ or .claude/skills/ but not declared in CLAUDE.md §4: {missing}"
    )


def test_claude_md_no_banned_phrases():
    """Voice audit on CLAUDE.md itself. Banned phrases must not appear
    OUTSIDE the section that documents the ban."""
    text = _claude_text()

    # Strip the line(s) that list banned phrases (documentation, not violation).
    # The banned list is in §12; we strip any line that contains "Banned phrases"
    # or "banned phrases enforced" markers.
    lines = []
    for line in text.splitlines():
        low = line.lower()
        if "banned phrases" in low or "banned-phrase" in low:
            continue
        lines.append(line)
    scanned = "\n".join(lines)

    # Subset of voice_audit phrases that should never appear in worldview docs.
    banned = [
        "co-pilot",
        "colleague",
        "powerful",
        "robust",
        "seamless",
        "let me walk you through",
        "before we begin",
        "great question",
        "excellent observation",
    ]
    hits = [b for b in banned if re.search(rf"\b{re.escape(b)}\b", scanned, re.IGNORECASE)]
    assert not hits, (
        f"CLAUDE.md contains banned phrases outside the documentation: {hits}"
    )
