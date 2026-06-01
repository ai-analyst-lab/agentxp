"""W6-T4 — cross-format number equality (executable proof of "format once").

The architectural keystone of the presentation layer is that every number a
human sees is formatted EXACTLY ONCE, in the pure ``distill()``, and every
adapter carries that string verbatim — an adapter interpolates, it never does
arithmetic. This test makes that guarantee executable: for one finalized
experiment, the lift / CI / verdict strings the markdown, exec-HTML, social-card
AND cross-experiment index print are byte-identical.

If any adapter ever re-derived or re-formatted a number, its string would drift
from the others and this test would fail — which is exactly the regression the
single-formatter discipline exists to prevent.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentxp.finalize import finalize_report
from agentxp.render.adapters.card import CardAdapter
from agentxp.render.adapters.html import HtmlAdapter
from agentxp.render.adapters.index_html import render_index
from agentxp.render.adapters.markdown import MarkdownAdapter
from agentxp.render.distill import distill
from agentxp.render.provenance import build_provenance
from agentxp.render.viewmodel import ViewBundle
from agentxp.schemas.report import Report

FIXTURE_BUNDLES = Path(__file__).parent / "fixtures" / "bundles_ship"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root with one finalized experiment, exp_001 (verdict SHIP).

    Mirrors the CLI test's fixture, plus a ``state.yaml`` so the index walk (which
    keys on state.yaml presence, exactly like ``agentxp list``) discovers it.
    """
    exp = tmp_path / "experiments" / "exp_001"
    (exp / "bundles").mkdir(parents=True)
    for name in (
        "analyzer.out.yaml",
        "interpreter.out.yaml",
        "monitor.out.yaml",
        "readout.out.yaml",
    ):
        shutil.copy(FIXTURE_BUNDLES / name, exp / "bundles" / name)
    shutil.copy(FIXTURE_BUNDLES / "experiment.yaml", exp / "experiment.yaml")
    (exp / "log.jsonl").write_text(
        json.dumps(
            {"event_name": "stage.committed", "stage": "analyze",
             "timestamp": "2026-06-02T17:55:11Z"}
        )
        + "\n",
        encoding="utf-8",
    )
    (exp / "state.yaml").write_text("experiment_id: exp_001\n", encoding="utf-8")
    finalize_report(exp)
    return tmp_path


def _bundle(exp_dir: Path) -> ViewBundle:
    report = Report.model_validate(json.loads((exp_dir / "report.json").read_text()))
    return ViewBundle(vm=distill(report), provenance=build_provenance(report, exp_dir))


def test_lift_ci_verdict_byte_identical_across_formats(project: Path):
    exp_dir = project / "experiments" / "exp_001"
    bundle = _bundle(exp_dir)
    primary = bundle.vm.metric_table[0]
    lift, ci, verdict = primary.lift_str, primary.ci_95, bundle.vm.verdict

    md = MarkdownAdapter().render(bundle)
    html = HtmlAdapter().render(bundle)
    card = CardAdapter().render(bundle)
    index = render_index(project / "experiments")

    # The strings carry no HTML-special characters, so autoescape leaves them
    # unchanged — the same bytes the single formatter emitted appear in all four.
    for name, out in (("md", md), ("html", html), ("card", card), ("index", index)):
        assert lift in out, f"lift string drifted in {name}"
        assert ci in out, f"ci string drifted in {name}"
        assert verdict in out, f"verdict string drifted in {name}"


def test_index_row_reuses_the_single_format_not_a_reformat(project: Path):
    """The index row's lift/CI come straight off the distilled VM, not a redo."""
    exp_dir = project / "experiments" / "exp_001"
    vm = _bundle(exp_dir).vm
    row = vm.to_index_row(_bundle(exp_dir).provenance.render_status)
    assert row.lift_str == vm.metric_table[0].lift_str
    assert row.ci_95 == vm.metric_table[0].ci_95
    assert row.verdict == vm.verdict
