"""W8 — the pure json + csv data adapters.

These are dependency-free machine exports over the same ViewBundle every other
adapter renders. The contract under test:

- they are pure text adapters (no disk writes, ``binary``/``requires_node`` off);
- they carry the receipts inseparably (json embeds provenance; csv leads every
  row with verdict + render status);
- they carry the SAME already-formatted lift / CI / verdict strings the markdown
  and html adapters emit — an adapter never re-derives a number, so the export
  numbers are byte-identical to the rendered ones.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
from pathlib import Path

import pytest

from agentxp.cli import report as report_cli
from agentxp.cli.exit_codes import EXIT_OK
from agentxp.finalize import finalize_report
from agentxp.render.adapters.data import CsvAdapter, JsonAdapter
from agentxp.render.adapters.markdown import MarkdownAdapter
from agentxp.render.distill import distill
from agentxp.render.provenance import build_provenance
from agentxp.render.viewmodel import ViewBundle
from agentxp.schemas.report import Report

FIXTURE_BUNDLES = Path(__file__).parent / "fixtures" / "bundles_ship"


@pytest.fixture
def bundle(tmp_path: Path) -> ViewBundle:
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
    report = Report.model_validate(json.loads((exp / "report.json").read_text()))
    return ViewBundle(vm=distill(report), provenance=build_provenance(report, exp))


@pytest.fixture
def project(tmp_path: Path, bundle) -> Path:
    # The bundle fixture already built tmp_path/experiments/exp_001 + report.json.
    return tmp_path


def test_adapters_are_pure_text():
    for adapter in (JsonAdapter(), CsvAdapter()):
        assert adapter.binary is False
        assert adapter.requires_node is False


def test_json_is_valid_and_embeds_vm_plus_provenance(bundle):
    out = JsonAdapter().render(bundle)
    data = json.loads(out)  # must be valid JSON
    assert set(data) == {"vm", "provenance"}
    assert data["vm"]["verdict"] == bundle.vm.verdict
    assert data["vm"]["experiment_name"] == bundle.vm.experiment_name
    # receipts travel inseparably in the same document.
    assert data["provenance"]["render_status"] == bundle.provenance.render_status.value
    assert "experiment_id" in data["provenance"]


def test_json_carries_the_single_formatted_numbers_verbatim(bundle):
    """The json export reuses distill()'s strings — never a reformat."""
    primary = bundle.vm.metric_table[0]
    data = json.loads(JsonAdapter().render(bundle))
    row = data["vm"]["metric_table"][0]
    assert row["lift_str"] == primary.lift_str
    assert row["ci_95"] == primary.ci_95


def test_csv_parses_header_and_one_row_per_metric(bundle):
    out = CsvAdapter().render(bundle)
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == CsvAdapter._HEADER
    assert len(rows) - 1 == len(bundle.vm.metric_table)


def test_csv_rows_lead_with_identity_verdict_and_status(bundle):
    out = CsvAdapter().render(bundle)
    reader = csv.DictReader(io.StringIO(out))
    first = next(reader)
    assert first["experiment_id"] == bundle.vm.experiment_id
    assert first["verdict"] == bundle.vm.verdict
    assert first["render_status"] == bundle.provenance.render_status.value
    # numeric columns carry the already-formatted strings verbatim.
    primary = bundle.vm.metric_table[0]
    assert first["lift"] == primary.lift_str
    assert first["ci_95"] == primary.ci_95


def test_numbers_byte_identical_across_md_json_csv(bundle):
    """The keystone guarantee extends to the data exports too."""
    primary = bundle.vm.metric_table[0]
    lift, ci, verdict = primary.lift_str, primary.ci_95, bundle.vm.verdict

    md = MarkdownAdapter().render(bundle)
    js = JsonAdapter().render(bundle)
    cv = CsvAdapter().render(bundle)
    for name, out in (("md", md), ("json", js), ("csv", cv)):
        assert lift in out, f"lift drifted in {name}"
        assert ci in out, f"ci drifted in {name}"
        assert verdict in out, f"verdict drifted in {name}"


def test_cli_json_to_stdout(project, capsys):
    code = report_cli.main(["exp_001", "--format", "json", "--project", str(project)])
    out, _ = capsys.readouterr()
    assert code == EXIT_OK
    data = json.loads(out)
    assert data["vm"]["verdict"] == "SHIP"


def test_cli_csv_to_file(project, tmp_path, capsys):
    dest = tmp_path / "out.csv"
    code = report_cli.main(
        ["exp_001", "--format", "csv", "--out", str(dest), "--project", str(project)]
    )
    capsys.readouterr()
    assert code == EXIT_OK
    assert dest.exists()
    rows = list(csv.reader(io.StringIO(dest.read_text())))
    assert rows[0] == CsvAdapter._HEADER
