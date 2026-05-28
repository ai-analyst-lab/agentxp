"""Tests for the voice-CI checker."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.voice.voice_ci import check


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _gather():
    for rule_dir in sorted(FIXTURES_DIR.iterdir()):
        if not rule_dir.is_dir():
            continue
        rule_num = int(rule_dir.name.split("_")[1])
        for fixture in sorted(rule_dir.glob("*.md")):
            verdict = "bad" if fixture.name.startswith("bad_") else "good"
            yield rule_num, fixture, verdict


@pytest.mark.parametrize(
    ("rule_num", "fixture", "verdict"),
    [(r, f, v) for r, f, v in _gather()],
    ids=[f"rule{r}_{f.name}" for r, f, _ in _gather()],
)
def test_fixture(rule_num: int, fixture: Path, verdict: str):
    text = fixture.read_text()
    violations = check(text)

    rule_violations = [v for v in violations if v.rule_id == rule_num]

    if verdict == "bad":
        assert rule_violations, (
            f"{fixture.name} is a BAD fixture for rule {rule_num} "
            f"but voice_ci.check() returned 0 violations of that rule. "
            f"All violations: {violations}"
        )
    else:
        assert not violations, (
            f"{fixture.name} is a GOOD fixture for rule {rule_num} "
            f"but voice_ci.check() flagged it: {violations}"
        )


def test_check_returns_empty_on_clean_text():
    assert check("Saved.\n\nwrote: bundles/profiler.out.yaml") == []
