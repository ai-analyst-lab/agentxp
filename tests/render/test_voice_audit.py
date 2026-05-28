"""Tests for openxp.render.voice_audit (D5 / NDS-3 / M67)."""
from __future__ import annotations

from pathlib import Path

from openxp.render.voice_audit import audit_voice, audit_voice_file


# Text that satisfies every rule: has a `wrote:` commit line + one question,
# short paragraphs, no banned phrases, no path leaks.
CLEAN_TEXT = """wrote: bundles/profiler.out.yaml

Profile is in the bundle. Skim the column table and tell me which ones look off.
"""


def test_audit_voice_clean_text(capsys):
    violations = audit_voice(CLEAN_TEXT)
    assert violations == []
    captured = capsys.readouterr()
    assert captured.err == ""


def test_audit_voice_banned_word_flagged(capsys):
    # "powerful" is a rule-5 banned phrase; CLEAN_TEXT base keeps rules 1/3/6 clean.
    text = "wrote: bundles/profiler.out.yaml\n\nThis is a powerful result. What now?\n"
    violations = audit_voice(text)
    assert len(violations) >= 1
    assert any(v.rule_id == 5 for v in violations)
    err = capsys.readouterr().err
    assert "[voice_audit]" in err
    assert "rule 5" in err


def test_audit_voice_returns_list():
    result = audit_voice(CLEAN_TEXT)
    assert isinstance(result, list)


def test_audit_voice_never_raises():
    # Pass odd inputs; must not raise.
    for bad in ["", "\x00\x01", "no questions and no commit line at all"]:
        result = audit_voice(bad)
        assert isinstance(result, list)


def test_audit_voice_file_reads_file(tmp_path: Path, capsys):
    p = tmp_path / "doc.md"
    p.write_text(
        "wrote: bundles/profiler.out.yaml\n\nThis is a powerful result. What now?\n",
        encoding="utf-8",
    )
    violations = audit_voice_file(p)
    assert len(violations) >= 1
    err = capsys.readouterr().err
    assert str(p) in err


def test_audit_voice_source_label_in_stderr(capsys):
    text = "wrote: bundles/profiler.out.yaml\n\nThis is a powerful result. What now?\n"
    audit_voice(text, source_label="my_doc")
    err = capsys.readouterr().err
    assert "my_doc" in err
