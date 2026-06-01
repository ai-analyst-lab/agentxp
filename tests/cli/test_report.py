"""W2 `agentxp report` CLI tests.

Exercises the verb end-to-end against a real finalized experiment dir built from
the ship bundle fixtures: load report.json → validate → distill → ViewBundle →
adapter → stdout/file. Pins the resolution order, the exit-code contract, and
the honest receipt (a tampered chain_hash → MISMATCH → DRAFT → EXIT_WARNING).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentxp.cli import report as report_cli
from agentxp.cli.exit_codes import EXIT_FATAL, EXIT_OK, EXIT_USER_ERROR, EXIT_WARNING
from agentxp.finalize import finalize_report

FIXTURE_BUNDLES = Path(__file__).parent.parent / "render" / "fixtures" / "bundles_ship"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root with one finalized experiment, exp_001 (verdict SHIP)."""
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
    # A log so canonical_chain_hash binds real content and the gate passes.
    (exp / "log.jsonl").write_text(
        json.dumps(
            {"event_name": "stage.committed", "stage": "analyze",
             "timestamp": "2026-06-02T17:55:11Z"}
        )
        + "\n",
        encoding="utf-8",
    )
    finalize_report(exp)
    return tmp_path


def _run(args, capsys):
    code = report_cli.main(args)
    out, err = capsys.readouterr()
    return code, out, err


def test_md_renders_and_exits_ok(project, capsys):
    code, out, err = _run(["exp_001", "--format", "md", "--project", str(project)], capsys)
    assert code == EXIT_OK
    assert "SHIP" in out
    assert "## Provenance" in out
    # W3: the fixture has a valid log, a matching chain hash, and a verdict that
    # reproduces from the recorded scalars → the full flow resolves VERIFIED.
    assert "Chain: OK" in out
    assert "**verified**" in out


def test_glance_default_when_piped(project, capsys, monkeypatch):
    # capsys makes stdout non-tty → default resolves to glance only when isatty.
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    code, out, err = _run(["exp_001", "--project", str(project)], capsys)
    assert code == EXIT_OK
    # piped default is md, not glance
    assert "## Provenance" in out


def test_glance_format_two_lines(project, capsys):
    code, out, err = _run(
        ["exp_001", "--format", "glance", "--project", str(project)], capsys
    )
    assert code == EXIT_OK
    assert "agentxp audit exp_001  ·  chain OK" in out


def test_audience_skeptic_points_at_audit(project, capsys):
    code, out, err = _run(
        ["exp_001", "--audience", "skeptic", "--project", str(project)], capsys
    )
    assert code == EXIT_OK
    assert "agentxp audit exp_001 --html" in err


def test_format_and_audience_mutually_exclusive(project, capsys):
    code, out, err = _run(
        ["exp_001", "--format", "md", "--audience", "exec", "--project", str(project)],
        capsys,
    )
    assert code == EXIT_USER_ERROR
    assert "mutually exclusive" in err


def test_out_with_glance_is_user_error(project, tmp_path, capsys):
    code, out, err = _run(
        ["exp_001", "--format", "glance", "--out", str(tmp_path / "x.txt"),
         "--project", str(project)],
        capsys,
    )
    assert code == EXIT_USER_ERROR
    assert "--out is not supported" in err


def test_deferred_format_fails_fast(project, capsys):
    code, out, err = _run(
        ["exp_001", "--format", "card", "--project", str(project)], capsys
    )
    assert code == EXIT_USER_ERROR
    assert "Wave 5" in err


def test_html_renders_self_contained_page(project, capsys):
    code, out, err = _run(
        ["exp_001", "--format", "html", "--project", str(project)], capsys
    )
    assert code == EXIT_OK
    assert out.startswith("<!doctype html>")
    assert "SHIP" in out
    # self-contained: inlined style, embedded font, inline chart svg, no CDN.
    assert "<style>" in out
    assert "@font-face" in out
    assert "<svg" in out
    assert "http://www.w3.org/2000/svg" in out
    assert "<script" not in out
    # receipts footer is mandatory.
    assert "xp-receipts-footer" in out
    # exec audience hides the audit trail.
    assert "Audit trail" not in out


def test_html_skeptic_shows_audit_trail(project, capsys):
    code, out, err = _run(
        ["exp_001", "--format", "html", "--audience", "skeptic",
         "--project", str(project)],
        capsys,
    )
    assert code == EXIT_OK
    assert "Audit trail" in out


def test_html_dark_theme_carries_dark_paper(project, capsys):
    code, out, err = _run(
        ["exp_001", "--format", "html", "--theme", "editorial-dark",
         "--project", str(project)],
        capsys,
    )
    assert code == EXIT_OK
    assert "--xp-paper: #14120d;" in out


def test_unknown_format_lists_available(project, capsys):
    code, out, err = _run(
        ["exp_001", "--format", "pdf", "--project", str(project)], capsys
    )
    assert code == EXIT_USER_ERROR
    assert "unknown format" in err


def test_unknown_experiment(project, capsys):
    code, out, err = _run(
        ["nope", "--format", "md", "--project", str(project)], capsys
    )
    assert code == EXIT_USER_ERROR
    assert "unknown experiment" in err


def test_missing_report_json(tmp_path, capsys):
    (tmp_path / "experiments" / "exp_x").mkdir(parents=True)
    code, out, err = _run(
        ["exp_x", "--format", "md", "--project", str(tmp_path)], capsys
    )
    assert code == EXIT_USER_ERROR
    assert "no report.json" in err


def test_out_writes_file(project, tmp_path, capsys):
    dest = tmp_path / "out.md"
    code, out, err = _run(
        ["exp_001", "--format", "md", "--out", str(dest), "--project", str(project)],
        capsys,
    )
    assert code == EXIT_OK
    assert dest.exists()
    assert "SHIP" in dest.read_text()


def test_tampered_chain_hash_is_mismatch_warning(project, capsys):
    """A doctored report.json sidecar → MISMATCH → DRAFT_UNVERIFIED → EXIT_WARNING."""
    report_path = project / "experiments" / "exp_001" / "report.json"
    data = json.loads(report_path.read_text())
    data["chain_hash"] = "0" * 64  # does not match the recomputed log hash
    report_path.write_text(json.dumps(data, indent=2))

    code, out, err = _run(
        ["exp_001", "--format", "md", "--project", str(project)], capsys
    )
    assert code == EXIT_WARNING
    assert "Chain: MISMATCH" in out
    assert "draft_unverified" in out


def test_corrupt_report_json_is_fatal(project, capsys):
    report_path = project / "experiments" / "exp_001" / "report.json"
    report_path.write_text("{ not valid json ")
    code, out, err = _run(
        ["exp_001", "--format", "md", "--project", str(project)], capsys
    )
    assert code == EXIT_FATAL
    assert "not valid JSON" in err
