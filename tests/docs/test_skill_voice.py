"""W8.3 — banned-vocab lint extended to SKILL.md + agents/*.md.

CLAUDE.md §12 names a banned list (``co-pilot``, ``colleague``,
``powerful``, ``robust``, ``seamless``, ``let me walk you through``,
``before we begin``, ``great question``, ``excellent observation``).
Pre-W8.3 the voice audit fired only on rendered readouts (W6.2 wired
it into ``render_share_tail``). This test extends the same gate to the
skill text and agent prompts so the worldview's voice rules are
enforced everywhere they apply, not just at render time.

The check is intentionally narrow: it fails on the ``banned_phrase``
rule only (rule id 5 — the §12 frozenset). Other voice rules — short
paragraph length, sentence-length variance, etc. — are advisory and do
not block. Skill text is a different register than prose readouts;
rule 5 is the only one that maps cleanly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentxp.render.voice_audit import audit_voice


REPO = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO / ".claude" / "skills"
AGENTS_DIR = REPO / "agents"


_DOCS = [
    *sorted(SKILLS_DIR.glob("**/SKILL.md")),
    *sorted(AGENTS_DIR.glob("*.md")),
]


@pytest.mark.parametrize(
    "doc_path",
    _DOCS,
    ids=lambda p: str(p.relative_to(REPO)),
)
def test_doc_uses_no_banned_vocabulary(doc_path: Path) -> None:
    """Rule 5 (banned phrases per CLAUDE.md §12) must not appear in skill
    text or agent prompts. Other voice rules are advisory and skipped.
    """
    text = doc_path.read_text()
    violations = audit_voice(text, source_label=str(doc_path.relative_to(REPO)))
    banned = [v for v in violations if v.rule_id == 5]
    if banned:
        details = "\n".join(
            f"  - {v.rule_name}: {v.detail}" for v in banned
        )
        pytest.fail(
            f"{doc_path.relative_to(REPO)} contains banned vocabulary "
            f"(CLAUDE.md §12):\n{details}"
        )
