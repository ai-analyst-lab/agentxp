"""Tests for agentxp.agents.templates.render_show_interpretation."""

from __future__ import annotations

from agentxp.agents.templates import render_show_interpretation


def _base_ctx(**overrides):
    """Return a minimal valid context, overridable per-test."""
    ctx = {
        "agent_name": "profiler",
        "stage": "0",
        "source_ref": "~/data/x.parquet",
        "row_count": 100,
        "column_count": 2,
        "date_range": None,
        "columns": [
            {
                "name": "user_id",
                "type": "string",
                "null_pct": "0%",
                "sample": "u_8a3f...",
                "my_read": "unit of randomization",
                "flagged": False,
                "flag_reason": None,
            },
            {
                "name": "bucket",
                "type": "string",
                "null_pct": "0%",
                "sample": "A,B",
                "my_read": "assignment column",
                "flagged": False,
                "flag_reason": None,
            },
        ],
        "things_to_check": [],
        "things_noticed": [],
        "closing_question": None,
    }
    ctx.update(overrides)
    return ctx


def test_minimal_render():
    out = render_show_interpretation(_base_ctx())
    assert "read: ~/data/x.parquet" in out
    assert "rows: 100" in out
    assert "cols: 2" in out
    assert "user_id" in out
    assert "bucket" in out
    assert "unit of randomization" in out
    assert "assignment column" in out
    assert "Looks right? Or fix one thing." in out
    # date_range absent → no "date range:" segment in header
    assert "date range:" not in out


def test_render_with_date_range():
    out = render_show_interpretation(
        _base_ctx(date_range="2026-05-19 → 2026-05-26")
    )
    assert "date range: 2026-05-19 → 2026-05-26" in out
    # Header should keep rows and cols on the same line as date range.
    header_line = next(
        line for line in out.splitlines() if line.startswith("rows:")
    )
    assert "cols: 2" in header_line
    assert "date range: 2026-05-19 → 2026-05-26" in header_line


def test_render_with_one_check():
    out = render_show_interpretation(
        _base_ctx(things_to_check=["Reading bucket A as control. Flip if wrong."])
    )
    assert "One thing I want to check before I save:" in out
    assert "A few things I want to check" not in out
    assert "- Reading bucket A as control. Flip if wrong." in out


def test_render_with_multiple_checks():
    out = render_show_interpretation(
        _base_ctx(
            things_to_check=[
                "Reading bucket A as control.",
                "Treating session_ended nulls as drop-offs.",
            ]
        )
    )
    assert "A few things I want to check before I save:" in out
    assert "One thing I want to check" not in out
    assert "- Reading bucket A as control." in out
    assert "- Treating session_ended nulls as drop-offs." in out


def test_render_with_flag_marker():
    ctx = _base_ctx()
    ctx["columns"][1]["flagged"] = True
    ctx["columns"][1]["flag_reason"] = "ambiguous variant labels"
    out = render_show_interpretation(ctx)
    # The flag marker should appear at the end of the bucket row.
    bucket_lines = [line for line in out.splitlines() if "bucket" in line]
    assert any("⚠" in line for line in bucket_lines), (
        f"expected ⚠ on bucket row, got lines: {bucket_lines}"
    )
    # The unflagged user_id row should NOT carry the marker.
    user_id_lines = [
        line for line in out.splitlines()
        if "user_id" in line and "column" not in line
    ]
    assert all("⚠" not in line for line in user_id_lines)


def test_render_with_custom_closing_question():
    out = render_show_interpretation(
        _base_ctx(closing_question="A=control. Right?")
    )
    assert "A=control. Right?" in out
    # Default closing should NOT also appear.
    assert "Looks right? Or fix one thing." not in out


def test_render_with_no_questions_no_commits():
    out = render_show_interpretation(_base_ctx())
    # Default closing fires.
    assert "Looks right? Or fix one thing." in out
    # No check/notice headers when both lists empty.
    assert "want to check before I save" not in out
    assert "noticed but didn't ask about" not in out


def test_padding_truncates_long_names():
    ctx = _base_ctx()
    long_name = "very_long_column_name_here"  # 26 chars, > 18
    ctx["columns"][0]["name"] = long_name
    out = render_show_interpretation(ctx)
    # Original long name must not appear in full.
    assert long_name not in out
    # The 17-char prefix should appear (we keep 17 + trailing space when truncating).
    assert long_name[:17] in out


def test_render_with_things_noticed_single():
    out = render_show_interpretation(
        _base_ctx(
            things_noticed=["session_ended is 12% null — timed-out sessions."]
        )
    )
    assert "One thing I noticed but didn't ask about:" in out
    assert "Things I noticed but didn't ask about:" not in out
    assert "- session_ended is 12% null — timed-out sessions." in out


def test_render_with_things_noticed_multiple():
    out = render_show_interpretation(
        _base_ctx(
            things_noticed=[
                "session_ended is 12% null.",
                "bucket has 3 distinct values, not 2.",
            ]
        )
    )
    assert "Things I noticed but didn't ask about:" in out
    assert "- session_ended is 12% null." in out
    assert "- bucket has 3 distinct values, not 2." in out
