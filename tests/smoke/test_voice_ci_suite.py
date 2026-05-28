"""Track E — voice-CI banned-vocab sweep over every agent system prompt.

For each of the 13 agent prompts under ``agents/`` we strip the ``## Banned
vocabulary`` section (where the prompt MUST quote the banned tokens to
instruct the agent to avoid them) and assert that no banned phrase from
:data:`tests.voice.voice_ci.BANNED_PHRASES` appears in the remaining text.

We do NOT run the full voice-CI ruleset against system prompts — most of
those rules govern agent *output* shape (paragraph count, default-or-one
question, read/wrote receipts) and would false-positive on instruction
text. Banned vocab is the rule that meaningfully applies: if a prompt
*demonstrates* a banned phrase outside the explicit banned-list section,
the agent is likely to echo it.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md voice samples /
W_pre0 voice-CI suite.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.voice.voice_ci import BANNED_PHRASES


_AGENTS_ROOT = Path(__file__).resolve().parents[2] / "agents"


def _collect_agent_prompts() -> list[Path]:
    """Walk ``agents/*.system.md`` + ``agents/designer/*.system.md``."""
    prompts: list[Path] = []
    prompts.extend(sorted(_AGENTS_ROOT.glob("*.system.md")))
    prompts.extend(sorted(_AGENTS_ROOT.glob("*/*.system.md")))
    return prompts


_BANNED_HEADING = re.compile(
    r"^##\s+(?:\d+\.\s+)?Banned vocabulary\b", re.IGNORECASE | re.MULTILINE
)
_NEXT_HEADING = re.compile(r"^##\s+", re.MULTILINE)


def _strip_banned_section(text: str) -> str:
    """Remove the ``## Banned vocabulary`` section and any fenced code blocks.

    Fenced code blocks frequently contain *examples* of bad output that
    intentionally show banned phrases — keep them out of the scan, the same
    way ``voice_ci.check`` itself does for live output.
    """
    m = _BANNED_HEADING.search(text)
    if m is not None:
        start = m.start()
        next_m = _NEXT_HEADING.search(text, m.end())
        end = next_m.start() if next_m is not None else len(text)
        text = text[:start] + text[end:]
    # Drop fenced code blocks (bad-example snippets often quote banned phrases).
    text = re.sub(r"```[\s\S]*?```", "", text)
    return text


def test_voice_ci_collects_thirteen_agent_prompts() -> None:
    """Defensive sanity: the suite is wired to all 13 prompts."""
    prompts = _collect_agent_prompts()
    assert len(prompts) == 13, (
        f"expected 13 agent system prompts; found {len(prompts)}: "
        f"{[p.name for p in prompts]}"
    )


@pytest.mark.parametrize(
    "prompt_path",
    _collect_agent_prompts(),
    ids=lambda p: p.relative_to(_AGENTS_ROOT).as_posix(),
)
def test_agent_prompt_has_no_banned_vocab_outside_banned_section(
    prompt_path: Path,
) -> None:
    """No banned phrase from BANNED_PHRASES outside the banned-list section."""
    text = prompt_path.read_text(encoding="utf-8")
    stripped = _strip_banned_section(text)

    failures: list[str] = []
    for rule_id, pattern in BANNED_PHRASES:
        if re.search(pattern, stripped, flags=re.IGNORECASE):
            failures.append(f"{rule_id} /{pattern}/")
    assert not failures, (
        f"{prompt_path.name}: banned phrases found outside §Banned vocabulary: "
        f"{failures}"
    )
