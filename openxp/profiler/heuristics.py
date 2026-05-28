"""HG-D4 per-column heuristics for the Stage-0 profiler (W_pre2.2).

Two rules, both surfaced as soft warnings on ``ColumnProfile``:

* **F.PRACTICE.01 — null-rate-on-identifier:** if a column name *looks* like a
  unit-of-randomization identifier (``user_id``, ``session``, ``*_account``…)
  and its ``null_rate`` clears the threshold, the test won't be analyzable.
* **F.PRACTICE.02 — mixed-timestamp-format:** if a ``string`` column's
  ``sample_values`` parse into two or more distinct date/time format buckets,
  flag the column for the ``mixed_timestamp_formats`` data-quality gate
  (§10.5.5). Heuristic only — never auto-resolves.

Returns plain dicts so the caller can do the final ``ColumnProfile(**d)``
validation without circular imports.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = ["apply_hg_d4_heuristics"]


# ── Identifier-name detection (F.PRACTICE.01) ───────────────────────────────

# Suffixes that strongly imply "this is an identifier column" — `_id`, `_key`,
# `_uuid`, `_uid`, `_guid`.
_ID_SUFFIXES: tuple[str, ...] = ("_id", "_key", "_uuid", "_uid", "_guid")

# Bare identifier nouns. Match exactly (case-insensitive) — these *are* the
# unit of randomization, not just descriptive columns about one.
_ID_BARE_NAMES: frozenset[str] = frozenset(
    {"id", "user", "session", "account", "customer"}
)

# Prefix/suffix wildcards on the four unit-of-randomization nouns.
_ID_NOUN_AFFIXES: tuple[str, ...] = ("user", "session", "account", "customer")


def _is_identifier_shaped(name: str) -> bool:
    n = name.lower()
    if n in _ID_BARE_NAMES:
        return True
    if any(n.endswith(s) for s in _ID_SUFFIXES):
        return True
    # Match `*_user`, `*_session`, `*_account`, `*_customer` — column is *about* a unit.
    if any(n.endswith("_" + noun) for noun in _ID_NOUN_AFFIXES):
        return True
    # Match `user_*`, `session_*`, `account_*`, `customer_*` — column is *of* a unit.
    if any(n.startswith(noun + "_") for noun in _ID_NOUN_AFFIXES):
        return True
    return False


# ── Timestamp-format detection (F.PRACTICE.02) ──────────────────────────────

# Compiled once at module import; cheaper than per-call.

# Full ISO-8601 datetime: 2026-01-01T12:34:56(.frac)?(Z|±hh:mm)?
_RE_ISO8601_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)
# ISO-8601 date only.
_RE_ISO8601_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# US slash date — month/day/year.
_RE_US_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
# European dotted date — day.month.year.
_RE_EU_DATE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")
# Unix epoch in seconds — 9 or 10 digits covers 1973-09 through 2286.
_RE_EPOCH_SECONDS = re.compile(r"^\d{9,10}$")
# Unix epoch in milliseconds — 12 or 13 digits.
_RE_EPOCH_MILLIS = re.compile(r"^\d{12,13}$")
# RFC 2822 day-of-week prefix (covers "Mon, 01 Jan 2026 12:00:00 +0000").
_RE_RFC2822_PREFIX = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun),")
# Last-resort "looks date-ish" — has at least one digit AND a separator we use.
_RE_OTHER_DATEISH = re.compile(r"(?=.*\d)(?=.*[-/:])")

# Priority order matters: more-specific patterns must run first so an
# ``iso8601_date`` value isn't claimed by ``epoch_seconds``.
_FORMAT_PRIORITY: tuple[str, ...] = (
    "iso8601_datetime",
    "iso8601_date",
    "us_date",
    "eu_date",
    "rfc2822",
    "epoch_millis",
    "epoch_seconds",
    "other",
)


def _classify_format(value: str) -> str:
    """Return one of the format-bucket names, or ``"not_a_date"`` for non-date strings."""
    v = value.strip()
    if not v:
        return "not_a_date"
    if _RE_ISO8601_DATETIME.match(v):
        return "iso8601_datetime"
    if _RE_ISO8601_DATE.match(v):
        return "iso8601_date"
    if _RE_US_DATE.match(v):
        return "us_date"
    if _RE_EU_DATE.match(v):
        return "eu_date"
    if _RE_RFC2822_PREFIX.match(v):
        return "rfc2822"
    if _RE_EPOCH_MILLIS.match(v):
        return "epoch_millis"
    if _RE_EPOCH_SECONDS.match(v):
        return "epoch_seconds"
    if _RE_OTHER_DATEISH.search(v):
        return "other"
    return "not_a_date"


def apply_hg_d4_heuristics(
    raw_column: dict[str, Any],
    *,
    row_count: int,
    flag_null_rate_threshold: float = 0.5,
    flag_format_min_distinct_formats: int = 2,
) -> dict[str, Any]:
    """Enrich ``raw_column`` with HG-D4 flag fields; return a new dict.

    The returned dict is suitable for ``ColumnProfile(**d)`` — same keys as
    the input plus ``mixed_format_detected``, ``format_samples``,
    ``flagged_for_review``, ``flag_reason``.
    """
    out: dict[str, Any] = dict(raw_column)

    # Preserve any prior heuristic state on the column (orchestrator may inject).
    flagged = bool(out.get("flagged_for_review", False))
    flag_reasons: list[str] = []
    if out.get("flag_reason"):
        flag_reasons.append(str(out["flag_reason"]))

    name = str(out.get("name", ""))
    dtype = out.get("dtype")
    null_rate = float(out.get("null_rate", 0.0))

    # ── F.PRACTICE.01: null-rate-on-identifier ──────────────────────────────
    if null_rate > flag_null_rate_threshold and _is_identifier_shaped(name):
        flagged = True
        flag_reasons.append(
            f"{name} is {null_rate * 100:.0f}% null. "
            "If this is the unit of randomization, the test won't be analyzable."
        )

    # ── F.PRACTICE.02: mixed-timestamp-format detection ─────────────────────
    mixed_format_detected = bool(out.get("mixed_format_detected", False))
    format_samples: list[str] = list(out.get("format_samples", []))

    if dtype == "string":
        samples = out.get("sample_values") or []
        # Map each sample to its bucket; remember the *first* sample for each bucket
        # so format_samples is reproducible across runs.
        bucket_to_first_sample: dict[str, str] = {}
        for sv in samples:
            if not isinstance(sv, str):
                continue
            bucket = _classify_format(sv)
            if bucket == "not_a_date":
                continue
            bucket_to_first_sample.setdefault(bucket, sv)

        if len(bucket_to_first_sample) >= flag_format_min_distinct_formats:
            mixed_format_detected = True
            # Emit one sample per bucket, in priority order, capped at 5.
            ordered_buckets = [
                b for b in _FORMAT_PRIORITY if b in bucket_to_first_sample
            ]
            ordered_buckets = ordered_buckets[:5]
            format_samples = [bucket_to_first_sample[b] for b in ordered_buckets]
            flagged = True
            bucket_list = ", ".join(ordered_buckets)
            flag_reasons.append(
                f"{name} has multiple timestamp formats: {bucket_list}"
            )

    out["mixed_format_detected"] = mixed_format_detected
    out["format_samples"] = format_samples
    out["flagged_for_review"] = flagged
    out["flag_reason"] = "; ".join(flag_reasons) if flag_reasons else None
    return out
