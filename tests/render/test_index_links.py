"""W7 — index identity, link resolution, and the display-name field.

Three regressions the remediation wave pins:

1. **Identity = discovery directory name, not the embedded experiment_id.**
   Every CLI verb (``agentxp report/audit <id>``) resolves an experiment by its
   DIRECTORY name. The index must build row identity (and therefore its
   out-links) from that same key — never from the report's embedded
   ``experiment_id``, which can differ and would produce dead links.

2. **Render-on-index writes the companion artifacts.** ``--index`` renders each
   row's ``report.html`` + ``audit.html`` into the experiment dir, so every link
   the navigator emits actually resolves on disk.

3. **The display name (schema v2 ``name``) flows through.** finalize populates
   it from ``experiment.yaml``; distill surfaces it as ``experiment_name``,
   falling back to the id when absent.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentxp.cli import report as report_cli
from agentxp.cli.exit_codes import EXIT_OK
from agentxp.finalize import finalize_report
from agentxp.render.adapters.index_html import render_index
from agentxp.render.distill import distill
from agentxp.schemas.report import Report

FIXTURE_BUNDLES = Path(__file__).parent / "fixtures" / "bundles_ship"


def _finalize_into(parent: Path, dir_name: str) -> Path:
    """Finalize one ship experiment into ``parent/experiments/{dir_name}``.

    The embedded experiment_id is always ``exp_001`` (the bundles carry it), so
    passing a ``dir_name`` other than ``exp_001`` is what makes the
    identity-from-directory-name behaviour observable.
    """
    exp = parent / "experiments" / dir_name
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
    return exp


def test_row_identity_and_hrefs_use_directory_name_not_embedded_id(tmp_path):
    """A dir named differently from the embedded id links via the DIR name."""
    exp = _finalize_into(tmp_path, "renamed_dir")
    # Sanity: the report really does embed a different id than its directory.
    embedded = json.loads((exp / "report.json").read_text())["experiment_id"]
    assert embedded == "exp_001"
    assert exp.name == "renamed_dir"

    html = render_index(tmp_path / "experiments")

    # Links resolve against the discovery directory name…
    assert "renamed_dir/report.html" in html
    assert "renamed_dir/audit.html" in html
    # …never against the embedded experiment_id.
    assert "exp_001/report.html" not in html
    assert "exp_001/audit.html" not in html


def test_render_on_index_writes_every_linked_artifact(tmp_path, capsys):
    """After --index, every report.html / audit.html the page links to exists."""
    _finalize_into(tmp_path, "exp_alpha")
    _finalize_into(tmp_path, "exp_beta")

    code = report_cli.main(["--index", "--project", str(tmp_path)])
    capsys.readouterr()
    assert code == EXIT_OK

    experiments = tmp_path / "experiments"
    for dir_name in ("exp_alpha", "exp_beta"):
        report_html = experiments / dir_name / "report.html"
        audit_html = experiments / dir_name / "audit.html"
        assert report_html.exists(), f"{dir_name}/report.html not rendered"
        assert audit_html.exists(), f"{dir_name}/audit.html not rendered"
        # Each is a real self-contained page, not an empty touch.
        assert report_html.read_text().startswith("<!doctype html>")
        assert "<html" in audit_html.read_text().lower()

    # And the links the index emits all point at files that now exist.
    index_html = (experiments / "index.html").read_text()
    for dir_name in ("exp_alpha", "exp_beta"):
        assert f"{dir_name}/report.html" in index_html
        assert (experiments / dir_name / "report.html").exists()


def test_display_name_flows_from_brief_through_distill(tmp_path):
    """schema v2 `name` (experiment.yaml) becomes the VM's experiment_name."""
    exp = _finalize_into(tmp_path, "exp_001")
    report = Report.model_validate(json.loads((exp / "report.json").read_text()))
    assert report.name == "Checkout button redesign"

    vm = distill(report)
    assert vm.experiment_name == "Checkout button redesign"
    # The id is still the embedded id, distinct from the display name.
    assert vm.experiment_id == "exp_001"


def test_distill_falls_back_to_id_when_name_absent(tmp_path):
    """A report with no `name` (v1-style) shows the id as the display name."""
    exp = _finalize_into(tmp_path, "exp_001")
    data = json.loads((exp / "report.json").read_text())
    data["name"] = None
    (exp / "report.json").write_text(json.dumps(data, indent=2))

    report = Report.model_validate(json.loads((exp / "report.json").read_text()))
    vm = distill(report)
    assert vm.experiment_name == "exp_001"
