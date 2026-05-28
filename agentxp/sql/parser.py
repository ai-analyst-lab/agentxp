"""Layer-1 SQL parsing for the AgentXP safety pipeline (§11).

Wraps :mod:`sqlglot` so the rest of ``agentxp.sql`` can treat the AST as
opaque. Only this module and :mod:`agentxp.sql.transpiler` import sqlglot
directly — every other module accepts the AST as ``Any``.

Exposes:
  - :func:`parse_sql`         : dialect-aware parser with UnparseableSQL on failure
  - :func:`walk_ast`          : depth-first iterator over every node
  - :data:`ALLOWED_AST_NODES` : the §11 AST allowlist (positive list)
  - :data:`DENY_FUNCTIONS`    : the §11 deny-list of warehouse side-effect funcs
"""
from __future__ import annotations

from typing import Iterator

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError


# ──────────────────────────────────────────────────────────────────────────
# AST allowlist (§11)
# ──────────────────────────────────────────────────────────────────────────


ALLOWED_AST_NODES: frozenset[type[exp.Expression]] = frozenset({
    exp.Select,
    exp.From,
    exp.Where,
    exp.Group,
    exp.Order,
    exp.Limit,
    exp.Join,
    exp.Union,
    exp.CTE,
    exp.With,
    exp.Window,
    exp.Case,
    exp.Cast,
    exp.Interval,
    exp.Subquery,
    exp.Filter,
    exp.Qualify,
    exp.Distinct,
    exp.Star,
    exp.Identifier,
    exp.Literal,
    exp.Func,
    exp.Anonymous,
    exp.Column,
    exp.Table,
    exp.Alias,
    exp.Paren,
    exp.And,
    exp.Or,
    exp.Not,
    exp.EQ,
    exp.NEQ,
    exp.LT,
    exp.GT,
    exp.LTE,
    exp.GTE,
})
"""The positive AST allowlist enforced at Layer 3c (§11).

Any node whose ``type()`` is not in this set AND is not a subclass of an
entry in this set is treated as a deny-list violation. The check is
performed by :func:`agentxp.sql.safety.layer_3c_deny_list_check`.
"""


# ──────────────────────────────────────────────────────────────────────────
# DENY_FUNCTIONS — names matched case-insensitively against `exp.Anonymous`
# and `exp.Func` nodes during Layer 3c (§11).
# ──────────────────────────────────────────────────────────────────────────


DENY_FUNCTIONS: frozenset[str] = frozenset({
    # Snowflake system side-effects
    "SYSTEM$WAIT",
    "SYSTEM$CANCEL_QUERY",
    # Postgres side-effects + large-object I/O
    "PG_SLEEP",
    "LO_EXPORT",
    "LO_IMPORT",
    "COPY",
    # BigQuery jobs
    "BQ.JOBS.CANCEL",
    # Generic
    "SLEEP",
    "LOAD_FILE",
    "EXEC",
    "EXECUTE",
    "EVAL",
})
"""Case-insensitive function names blocked at Layer 3c (§11).

Matched against ``exp.Anonymous.name``, ``exp.Func.sql_name()``, and the
identifier path of dotted calls (``BQ.JOBS.CANCEL``). Any hit raises
:class:`agentxp.sql.safety.DenyListViolation`.
"""


# Pre-uppercased copy for fast `in` checks at hot paths.
_DENY_FUNCTIONS_UPPER: frozenset[str] = frozenset(name.upper() for name in DENY_FUNCTIONS)


def parse_sql(sql: str, dialect: str) -> exp.Expression:
    """Parse ``sql`` under ``dialect`` and return the sqlglot AST root.

    Raises :class:`agentxp.sql.safety.UnparseableSQL` when sqlglot cannot
    produce a tree. Empty / whitespace-only input also raises.

    Parameters
    ----------
    sql
        SQL text to parse.
    dialect
        Source dialect (``"duckdb"``, ``"snowflake"``, ``"bigquery"``, or
        ``"sqlglot"`` for the canonical IR form).
    """
    # Import here to avoid a hard cycle with safety module.
    from agentxp.sql.safety import UnparseableSQL

    if sql is None or not sql.strip():
        raise UnparseableSQL("SQL input is empty")
    try:
        tree = parse_one(sql, read=dialect if dialect != "sqlglot" else None)
    except ParseError as exc:
        raise UnparseableSQL(f"sqlglot parse error: {exc}") from exc
    if tree is None:
        raise UnparseableSQL("sqlglot returned None for input")
    return tree


def walk_ast(expr: exp.Expression) -> Iterator[exp.Expression]:
    """Yield every node in ``expr`` depth-first (including the root)."""
    for node in expr.walk():
        # sqlglot >=25 returns the bare expression from `.walk()`; older
        # versions returned (node, parent, key) tuples. Normalize.
        if isinstance(node, tuple):
            yield node[0]
        else:
            yield node


__all__ = [
    "ALLOWED_AST_NODES",
    "DENY_FUNCTIONS",
    "parse_sql",
    "walk_ast",
]
