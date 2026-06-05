"""Tests for agentxp.workflows.audit (V12)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from agentxp.workflows.audit import diff_logs, walk_log


def test_walk_log_yields_parsed_entries():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp) / "exp_001"
        exp.mkdir()
        (exp / "log.md").write_text(
            "# log\n"
            "\n"
            "- `2026-06-04T12:00:00+00:00` — design verb opened\n"
            "- `2026-06-04T12:05:00+00:00` — intent captured by shane\n"
            "some prose that should be ignored\n"
            "- `2026-06-04T12:10:00+00:00` — brief drafted\n"
        )
        entries = list(walk_log(exp))
        assert len(entries) == 3
        assert entries[0].message == "design verb opened"
        assert entries[1].message == "intent captured by shane"
        assert entries[2].line_no > entries[1].line_no


def test_walk_log_empty_dir_yields_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        assert list(walk_log(Path(tmp))) == []


def test_walk_log_missing_log_yields_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp) / "exp_001"
        exp.mkdir()
        assert list(walk_log(exp)) == []


def test_diff_logs_picks_up_changes_and_extras():
    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp) / "a"
        b = Path(tmp) / "b"
        a.mkdir()
        b.mkdir()
        (a / "log.md").write_text(
            "- `2026-06-04T12:00:00+00:00` — entry one\n"
            "- `2026-06-04T12:05:00+00:00` — entry two\n"
        )
        (b / "log.md").write_text(
            "- `2026-06-04T12:00:00+00:00` — entry one\n"
            "- `2026-06-04T12:05:00+00:00` — entry two CHANGED\n"
            "- `2026-06-04T12:10:00+00:00` — entry three\n"
        )
        diffs = list(diff_logs(a, b))
        assert len(diffs) == 2
        assert diffs[0].kind == "changed"
        assert diffs[1].kind == "only_in_b"
