"""W1 golden-file parity test for the distill → markdown spine.

The golden (``report_v2.golden.md``) is the hand-blessed rendering of the
widened v2 fixture. The contract this test pins:

  - Numeric formatting, whitespace, column order, and section ordering are
    OWNED by distill() + the markdown template. If you intentionally change any
    of those, regenerate the golden (see ``_regenerate`` below) and re-bless it.
  - Agent prose (the verdict rationale and every uncertainty note) must appear
    VERBATIM in the rendered output. That half of the assertion is not a
    formatting concern — drift there means distill mangled prose and is a bug,
    so it is checked independently of the golden.

Equality is asserted on NORMALIZED text (trailing whitespace stripped per line,
trailing blank lines dropped) so an editor re-save of the golden can't break the
test over invisible whitespace.
"""
from __future__ import annotations

import json
from pathlib import Path

from agentxp.render.distill import distill
from agentxp.render.report import render_report
from agentxp.schemas.report import Report

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "report_v2.golden.md"


def _normalize(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _render() -> str:
    report = Report.model_validate(json.loads((FIXTURES / "report_v2.json").read_text()))
    return render_report(distill(report))


def _regenerate() -> None:
    """Re-bless the golden. Run manually after an intentional formatting change:

        python -c "from tests.render.test_distill_parity import _regenerate; _regenerate()"
    """
    GOLDEN.write_text(_render())


def test_markdown_matches_golden():
    assert _normalize(_render()) == _normalize(GOLDEN.read_text())


def test_agent_prose_is_verbatim():
    """The rationale and every uncertainty note survive rendering unchanged."""
    report = Report.model_validate(json.loads((FIXTURES / "report_v2.json").read_text()))
    out = _render()
    assert report.verdict_rationale in out
    for note in report.uncertainty_notes:
        assert note.detail in out
