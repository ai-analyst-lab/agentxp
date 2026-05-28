"""Voice-CI: deterministic regex-based checks for the 6 voice rules.

This is NOT an LLM judge. It runs in CI on every agent-prompt commit and
catches the most common voice violations. The fixtures in tests/voice/fixtures/
are the ground truth - if a fixture is mis-classified, fix the rule, not the
fixture.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class VoiceViolation:
    rule_id: int
    rule_name: str
    detail: str


BANNED_PHRASES = [
    # Rule 5: no throat-clearing
    ("rule_5", r"\bgreat question\b"),
    ("rule_5", r"\bexcellent (observation|question|point)\b"),
    ("rule_5", r"\bwe('| a)re excited\b"),
    ("rule_5", r"\blet me walk you through\b"),
    ("rule_5", r"\bbefore we begin\b"),
    ("rule_5", r"\b(I've )?successfully (loaded|completed|finished)"),
    # Rule 2: no manufactured beats
    ("rule_2", r"\bthat messed with me\b"),
    ("rule_2", r"\bin a strange way\b"),
    ("rule_2", r"\bwhat struck me\b"),
    ("rule_2", r"\bI couldn't believe\b"),
    ("rule_2", r"\bI was excited\b"),
    # Generic AI-marketing banned (cross-rule, attributed to rule_5)
    ("rule_5", r"\bleverage\b"),
    ("rule_5", r"\bpowerful\b"),
    ("rule_5", r"\bdelightful\b"),
    ("rule_5", r"\brobust\b"),
    ("rule_5", r"\bseamless\b"),
    ("rule_5", r"\bcutting[- ]edge\b"),
]


def check(text: str) -> list[VoiceViolation]:
    """Run all rules. Return list of violations (empty if clean)."""
    violations: list[VoiceViolation] = []

    plain = _strip_code_blocks(text)

    # Rule 1: default-or-one-question.
    q_count = plain.count("?")
    has_commit = re.search(r"^\s*(wrote|read):\s+\S", plain, re.MULTILINE) is not None
    if q_count > 1:
        violations.append(VoiceViolation(1, "default_or_one_question", f"{q_count} questions"))
    elif q_count == 0 and not has_commit:
        violations.append(VoiceViolation(1, "default_or_one_question", "no commit + no question"))

    # Rule 3: short paragraphs.
    paragraphs = [p.strip() for p in plain.split("\n\n") if p.strip()]
    if len(paragraphs) > 5:
        violations.append(VoiceViolation(3, "short_paragraphs", f"{len(paragraphs)} paragraphs"))
    for i, p in enumerate(paragraphs):
        if len(p.split()) > 120:
            violations.append(
                VoiceViolation(3, "short_paragraphs", f"paragraph {i} has {len(p.split())} words")
            )

    # Rule 4: named defaults with reasons.
    commit_patterns = [
        r"I'm reading\b",
        r"I'll (treat|use|go with|pick|default)\b",
        r"going with\b",
        r"default(ing)? to\b",
    ]
    for pat in commit_patterns:
        for m in re.finditer(pat, plain, re.IGNORECASE):
            window = plain[m.start():m.start() + 200]
            if not re.search(r"\bbecause\b|—|–| \(", window):
                violations.append(
                    VoiceViolation(
                        4,
                        "named_defaults_with_reasons",
                        f"commit at pos {m.start()} lacks reason",
                    )
                )

    # Rule 6: read/wrote receipts.
    if re.search(r"\b(Saved|Wrote) (it|that|the) to ", plain) and not has_commit:
        violations.append(
            VoiceViolation(6, "read_wrote_receipts", "commit-in-prose without `wrote:` line")
        )
    if re.search(r"(/Users/|/home/)\w+/", plain):
        violations.append(VoiceViolation(6, "read_wrote_receipts", "full home path leaked"))

    # Banned phrases (handles rule_2 + rule_5 entries)
    for rule_id, pat in BANNED_PHRASES:
        if re.search(pat, plain, re.IGNORECASE):
            rule_num = int(rule_id.split("_")[1])
            violations.append(
                VoiceViolation(rule_num, "banned_phrase", f"matched /{pat}/")
            )

    return violations


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks so banned-phrase checks don't false-positive on banned-lists."""
    return re.sub(r"```[\s\S]*?```", "", text)
