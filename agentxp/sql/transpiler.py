"""Cross-dialect SQL transpiler for AgentXP v0.1.

Thin wrapper around :func:`sqlglot.transpile` that constrains source and
target dialects to the AgentXP v0.1 supported set and surfaces parser
failures as :class:`TranspileError` rather than the assortment of internal
sqlglot exception types.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 (adapters table).
v0.1 dialects: duckdb, snowflake, bigquery.
v0.1.1 adds: mysql, postgres, redshift (not yet wired here).
"""
from __future__ import annotations

import sqlglot

SUPPORTED_DIALECTS: frozenset[str] = frozenset({"duckdb", "snowflake", "bigquery"})


class TranspileError(Exception):
    """Raised when sqlglot cannot parse or render the SQL across dialects."""


def transpile(sql: str, source_dialect: str, target_dialect: str) -> str:
    """Translate ``sql`` from ``source_dialect`` to ``target_dialect``.

    Both dialects must appear in :data:`SUPPORTED_DIALECTS`; any other
    value (including dialects sqlglot itself supports, like ``mysql``)
    raises :class:`ValueError`. Parser / generator failures inside sqlglot
    are re-raised as :class:`TranspileError` with the original message
    preserved so callers don't have to import sqlglot's internals.
    """
    if source_dialect not in SUPPORTED_DIALECTS:
        raise ValueError(
            f"unsupported source dialect {source_dialect!r}; "
            f"supported: {sorted(SUPPORTED_DIALECTS)}"
        )
    if target_dialect not in SUPPORTED_DIALECTS:
        raise ValueError(
            f"unsupported target dialect {target_dialect!r}; "
            f"supported: {sorted(SUPPORTED_DIALECTS)}"
        )

    try:
        rendered = sqlglot.transpile(sql, read=source_dialect, write=target_dialect)
    except sqlglot.errors.SqlglotError as exc:
        raise TranspileError(
            f"failed to transpile {source_dialect} -> {target_dialect}: {exc}"
        ) from exc
    except Exception as exc:  # defensive: sqlglot occasionally raises plain ValueError
        raise TranspileError(
            f"failed to transpile {source_dialect} -> {target_dialect}: {exc}"
        ) from exc

    if not rendered:
        raise TranspileError(
            f"sqlglot returned no statements for {source_dialect} -> {target_dialect}"
        )
    return rendered[0]
