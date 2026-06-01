"""W8 — the PNG/PDF raster adapters (the optional agentxp[png] extra).

Every test that drives Chromium is gated on :func:`raster.is_available` so the
core suite stays green without the extra installed. What's pinned: the adapters
declare themselves binary + engine-dependent; PNG produces real PNG bytes off
the social card and PDF produces real PDF bytes off the exec html; and the CLI
routes png/pdf through the extra (binary → --out required) when it is present,
or fails fast naming the extra when it is not.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentxp.cli import report as report_cli
from agentxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR
from agentxp.finalize import finalize_report
from agentxp.render.adapters import raster
from agentxp.render.distill import distill
from agentxp.render.provenance import build_provenance
from agentxp.render.viewmodel import ViewBundle
from agentxp.schemas.report import Report

FIXTURE_BUNDLES = Path(__file__).parent / "fixtures" / "bundles_ship"

needs_extra = pytest.mark.skipif(
    not raster.is_available(), reason="agentxp[png] extra not installed"
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
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


@pytest.fixture
def bundle(project: Path) -> ViewBundle:
    exp = project / "experiments" / "exp_001"
    report = Report.model_validate(json.loads((exp / "report.json").read_text()))
    return ViewBundle(vm=distill(report), provenance=build_provenance(report, exp))


def _run(args, capsys):
    code = report_cli.main(args)
    out, err = capsys.readouterr()
    return code, out, err


def test_raster_adapters_are_binary_and_engine_dependent():
    # These flags are inspectable without Chromium — no skip needed.
    for adapter in (raster.PngAdapter(), raster.PdfAdapter()):
        assert adapter.binary is True
        assert adapter.requires_node is True


def test_build_adapter_maps_ids():
    assert raster.build_adapter("png").format_id == "png"
    assert raster.build_adapter("pdf").format_id == "pdf"
    with pytest.raises(KeyError):
        raster.build_adapter("xlsx")


@needs_extra
def test_png_renders_real_png_bytes(bundle):
    data = raster.PngAdapter().render(bundle)
    assert isinstance(data, bytes)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 1000  # a real raster, not an empty frame


@needs_extra
def test_pdf_renders_real_pdf_bytes(bundle):
    data = raster.PdfAdapter().render(bundle)
    assert isinstance(data, bytes)
    assert data[:5] == b"%PDF-"
    assert len(data) > 1000


@needs_extra
def test_cli_png_requires_out(project, capsys):
    # png is binary — writing to stdout is a usage error even with the extra.
    code, out, err = _run(
        ["exp_001", "--format", "png", "--project", str(project)], capsys
    )
    assert code == EXIT_USER_ERROR
    assert "binary" in err
    assert "--out is required" in err


@needs_extra
def test_cli_png_writes_file(project, tmp_path, capsys):
    dest = tmp_path / "card.png"
    code, out, err = _run(
        ["exp_001", "--format", "png", "--out", str(dest), "--project", str(project)],
        capsys,
    )
    assert code == EXIT_OK
    assert dest.exists()
    assert dest.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@needs_extra
def test_cli_pdf_writes_file(project, tmp_path, capsys):
    dest = tmp_path / "report.pdf"
    code, out, err = _run(
        ["exp_001", "--format", "pdf", "--out", str(dest), "--project", str(project)],
        capsys,
    )
    assert code == EXIT_OK
    assert dest.exists()
    assert dest.read_bytes()[:5] == b"%PDF-"
