"""Voice audit (D5 / NDS-3 / M67).

Single-pass voice CI that runs at render time. Per D5/NDS-3, voice CI is
advisory-only in v0.1: violations surface as stderr warnings but do NOT
block rendering. The orchestrator may inspect the returned list and set
EXIT_WARNING (exit_codes.py = 2) when violations are non-empty.

Wraps the existing tests/voice/voice_ci.check() function (W_pre3.3 owns
the 60 fixtures + 6 rules). The import is deferred + guarded so this
module gracefully degrades if the test tree is unavailable in production.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.voice.voice_ci import VoiceViolation


def _load_check():
    """Deferred import of the voice CI checker.

    Returns the `check` callable from tests/voice/voice_ci. If the test
    tree isn't importable (e.g., installed wheel without tests/), returns
    a no-op stub so production never breaks.
    """
    try:
        from tests.voice.voice_ci import check
        return check
    except ImportError:
        return lambda _text: []


def audit_voice(text: str, source_label: str = "<rendered>") -> list:
    """Run the voice CI on rendered text.

    Prints every violation to stderr with a uniform format and returns
    the violation list for programmatic inspection. ALWAYS returns
    (never raises) — per D5, voice CI is advisory-only.

    Format on stderr:
      [voice_audit] {source_label}: rule {N} ({rule_name}) — {detail}
    """
    check = _load_check()
    try:
        violations = check(text)
    except Exception as exc:  # defensive: voice CI must never crash render
        print(
            f"[voice_audit] {source_label}: checker raised {type(exc).__name__} — {exc}",
            file=sys.stderr,
        )
        return []

    for v in violations:
        print(
            f"[voice_audit] {source_label}: rule {v.rule_id} ({v.rule_name}) — {v.detail}",
            file=sys.stderr,
        )
    return violations


def audit_voice_file(path: Path) -> list:
    """Read file at `path` and audit its content.

    Convenience wrapper around audit_voice. Uses str(path) as the
    source_label so stderr lines point at the offending file.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return audit_voice(text, source_label=str(path))
