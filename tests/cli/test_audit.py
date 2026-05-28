"""Tests for openxp.cli.audit — §15 (audit CLI, 3 subcommands per D4)."""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from openxp.cli.audit import main
from openxp.cli.exit_codes import (
    EXIT_FATAL,
    EXIT_OK,
    EXIT_USER_ERROR,
    EXIT_WARNING,
)


# ──────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────


def _ts(offset: int = 0) -> str:
    """Deterministic UTC ISO timestamp."""
    return datetime(2026, 5, 27, 12, offset, 0, tzinfo=timezone.utc).isoformat()


def _write_log(exp_dir: Path, events: list[dict]) -> None:
    exp_dir.mkdir(parents=True, exist_ok=True)
    log_path = exp_dir / "log.jsonl"
    with log_path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    # log.jsonl must be chmod 600 per §1.7.3 — set it so validate_chain
    # doesn't trip on permission drift during the test.
    os.chmod(log_path, 0o600)


def _valid_chain_events(exp_id: str = "exp_001") -> list[dict]:
    """Three events forming a valid parent-action chain.

    stage.entered → stage.committed (paired); no gate events, no agent
    dispatches, so Invariants 2 and 3 are vacuously satisfied.
    """
    return [
        {
            "schema_version": 1,
            "timestamp": _ts(0),
            "action_id": "01HXXX0000000000000000000A",
            "parent_action_id": None,
            "actor_kind": "system",
            "actor_name": "orchestrator",
            "experiment_id": exp_id,
            "event_name": "stage.entered",
            "stage": "data_loaded",
            "metadata": {},
        },
        {
            "schema_version": 1,
            "timestamp": _ts(1),
            "action_id": "01HXXX0000000000000000000B",
            "parent_action_id": "01HXXX0000000000000000000A",
            "actor_kind": "system",
            "actor_name": "orchestrator",
            "experiment_id": exp_id,
            "event_name": "stage.committed",
            "stage": "data_loaded",
            "bundle_hash": "deadbeefcafe1234deadbeefcafe1234",
            "metadata": {},
        },
        {
            "schema_version": 1,
            "timestamp": _ts(2),
            "action_id": "01HXXX0000000000000000000C",
            "parent_action_id": "01HXXX0000000000000000000B",
            "actor_kind": "agent",
            "actor_name": "profiler",
            "experiment_id": exp_id,
            "event_name": "agent.dispatched",
            "agent_name": "profiler",
            "bundle_hash": "abc123def4567890abc123def4567890",
            "metadata": {},
        },
    ]


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


def test_audit_unknown_exp_id_returns_user_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = main(["does_not_exist"])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "unknown experiment" in captured.err


def test_audit_empty_log_returns_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_001"
    exp_dir.mkdir(parents=True)
    # log.jsonl is intentionally absent — empty timeline.

    rc = main(["exp_001"])
    captured = capsys.readouterr()
    assert rc == EXIT_WARNING
    assert "no events" in captured.out


def test_audit_text_renders_event_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_001"
    _write_log(exp_dir, _valid_chain_events())

    rc = main(["exp_001"])
    captured = capsys.readouterr()
    # The 3 event names should all appear on stdout.
    assert "stage.entered" in captured.out
    assert "stage.committed" in captured.out
    assert "agent.dispatched" in captured.out
    # Three events, one root, no gates — chain should validate clean.
    assert rc == EXIT_OK


def test_audit_text_shows_chain_integrity_ok(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_001"
    _write_log(exp_dir, _valid_chain_events())

    rc = main(["exp_001"])
    captured = capsys.readouterr()
    assert "chain integrity: OK" in captured.out
    assert rc == EXIT_OK


def test_audit_text_shows_chain_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_001"
    # Corrupt chain: second event references a parent that was never seen.
    events = _valid_chain_events()
    events[1]["parent_action_id"] = "01HXXX9999999999999999999Z"  # orphan
    _write_log(exp_dir, events)

    rc = main(["exp_001"])
    captured = capsys.readouterr()
    assert "chain integrity: FAILED" in captured.out
    assert rc == EXIT_WARNING


def test_audit_json_flag_outputs_structured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_001"
    _write_log(exp_dir, _valid_chain_events())

    rc = main(["exp_001", "--json"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    parsed = json.loads(captured.out)
    assert isinstance(parsed, list)
    assert len(parsed) == 3
    assert parsed[0]["event_name"] == "stage.entered"


def test_audit_quiet_suppresses_header(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_001"
    _write_log(exp_dir, _valid_chain_events())

    rc = main(["exp_001", "--quiet"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "Audit trail for" not in captured.out
    # Event rows still render.
    assert "stage.entered" in captured.out


def test_audit_html_writes_file_at_default_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_001"
    _write_log(exp_dir, _valid_chain_events())

    rc = main(["exp_001", "--html"])
    assert rc == EXIT_OK
    out_path = exp_dir / "audit.html"
    assert out_path.exists()
    # chmod 600 per §1.7.3 / audit hygiene
    mode = stat.S_IMODE(out_path.stat().st_mode)
    assert mode == 0o600
    body = out_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in body
    assert "Audit trail for exp_001" in body


def test_audit_html_explicit_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_001"
    _write_log(exp_dir, _valid_chain_events())

    explicit = tmp_path / "custom_audit.html"
    rc = main(["exp_001", "--html", "--out", str(explicit)])
    assert rc == EXIT_OK
    assert explicit.exists()
    body = explicit.read_text(encoding="utf-8")
    assert "<!doctype html>" in body


def test_audit_html_escapes_user_prose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_001"
    # Inject an XSS payload into a user-controllable string field. The HTML
    # renderer MUST html.escape() every user-supplied value per M81.
    events = _valid_chain_events()
    events.append(
        {
            "schema_version": 1,
            "timestamp": _ts(3),
            "action_id": "01HXXX0000000000000000000D",
            "parent_action_id": "01HXXX0000000000000000000C",
            "actor_kind": "user",
            "actor_name": "<script>alert('xss')</script>",
            "experiment_id": "exp_001",
            "event_name": "gate.resolved",
            "kind": "confirm_hypothesis",
            "choice": "y",
            "rationale": "<img src=x onerror=alert(1)>",
            "metadata": {},
        }
    )
    _write_log(exp_dir, events)

    rc = main(["exp_001", "--html"])
    assert rc == EXIT_OK
    body = (exp_dir / "audit.html").read_text(encoding="utf-8")
    # Raw <script> tag must not appear; escaped form must.
    assert "<script>alert" not in body
    assert "&lt;script&gt;alert" in body
    # Onerror handler also escaped.
    assert "<img src=x onerror" not in body


def test_audit_diff_identical_returns_no_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_a = tmp_path / "experiments" / "exp_001"
    exp_b = tmp_path / "experiments" / "exp_002"
    _write_log(exp_a, _valid_chain_events("exp_001"))
    _write_log(exp_b, _valid_chain_events("exp_002"))

    rc = main(["exp_001", "--diff", "exp_002"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "no differences" in captured.out


def test_audit_diff_different_bundle_hashes_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_a = tmp_path / "experiments" / "exp_001"
    exp_b = tmp_path / "experiments" / "exp_002"
    events_a = _valid_chain_events("exp_001")
    events_b = _valid_chain_events("exp_002")
    # Same event sequence, but different bundle hash on the agent dispatch.
    events_b[2]["bundle_hash"] = "99999999ffffffff99999999ffffffff"
    _write_log(exp_a, events_a)
    _write_log(exp_b, events_b)

    rc = main(["exp_001", "--diff", "exp_002"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "bundle hashes that differ" in captured.out
    assert "abc123def456" in captured.out
    assert "99999999ffff" in captured.out


def test_audit_diff_missing_events_shows_in_one_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exp_a = tmp_path / "experiments" / "exp_001"
    exp_b = tmp_path / "experiments" / "exp_002"
    events_a = _valid_chain_events("exp_001")
    # B is shorter — drop the agent.dispatched.
    events_b = _valid_chain_events("exp_002")[:2]
    _write_log(exp_a, events_a)
    _write_log(exp_b, events_b)

    rc = main(["exp_001", "--diff", "exp_002"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "only in exp_001" in captured.out
    assert "agent.dispatched" in captured.out


def test_audit_main_handles_arbitrary_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # cwd has no experiments/ subdir at all. Audit should refuse gracefully
    # (EXIT_USER_ERROR), not raise.
    monkeypatch.chdir(tmp_path)
    rc = main(["exp_001"])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "unknown experiment" in captured.err
