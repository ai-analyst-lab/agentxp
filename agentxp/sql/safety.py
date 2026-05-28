"""5-layer SQL safety pipeline for AgentXP v0.1 (§11).

Walks user / agent SQL through five gates before dispatch:

  1. parse           — sqlglot tree (delegated to :mod:`agentxp.sql.parser`)
  2. read_only       — reject DELETE / DROP / UPDATE / INSERT / TRUNCATE / MERGE / CREATE / ALTER
  3a. cross_adapter  — reject queries spanning multiple warehouse adapters
  3b. semantic       — assert every FROM table is a declared fact_source
  3c. deny_list      — block §11 DENY_FUNCTIONS + non-ALLOWED_AST_NODES
  4. resource        — inject / cap LIMIT per the §11 resource-bounds matrix

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §11.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from sqlglot import exp

from agentxp.sql.parser import (
    ALLOWED_AST_NODES,
    DENY_FUNCTIONS,
    parse_sql,
    walk_ast,
)


# ──────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────


class SafetyViolation(Exception):
    """Base class for any layer-2/3/4 safety rejection (§11)."""


class ReadOnlyViolation(SafetyViolation):
    """Layer 2: AST contains a write / DDL operation."""


class CrossAdapterViolation(SafetyViolation):
    """Layer 3a: query references tables on more than one adapter."""


class SemanticModelViolation(SafetyViolation):
    """Layer 3b: a FROM table is not declared as any fact_source."""


class DenyListViolation(SafetyViolation):
    """Layer 3c: AST contains a DENY_FUNCTIONS call or a non-ALLOWED node."""


class ResourceBoundsViolation(SafetyViolation):
    """Layer 4: query cannot be safely capped (e.g. unknown purpose)."""


class UnparseableSQL(SafetyViolation):
    """Layer 1: sqlglot returned None / raised ParseError."""


# ──────────────────────────────────────────────────────────────────────────
# Resource-bounds matrix (§11)
#
# Per-purpose row-count caps. The full ResourceBounds row (timeout_s,
# bytes_scanned_cap, require_explain) lives in agentxp.sql.schema; the
# safety pipeline only needs the row_limit_default value at Layer 4.
# ──────────────────────────────────────────────────────────────────────────


_ROW_LIMIT_BY_PURPOSE: dict[str, int] = {
    "profile":         100_000,
    "preview":           1_000,
    "srm_check":     1_000_000,
    "metric_compute": 10_000_000,
    "user_paste":        1_000,
}


# ──────────────────────────────────────────────────────────────────────────
# Implicit structural nodes
#
# These are sqlglot wrapper / structural nodes that fall out of any valid
# SELECT but aren't part of the §11 security-relevant allowlist. Allowing
# them at Layer 3c keeps the deny-list check focused on what matters
# (functions + statement shape) without forcing every CTE/alias query
# through a false-positive.
# ──────────────────────────────────────────────────────────────────────────


_STRUCTURAL_ALLOWED: frozenset[type[exp.Expression]] = frozenset({
    exp.TableAlias,
    exp.ColumnDef,
    exp.Schema,
    exp.DataType,
    exp.Tuple,
    exp.Ordered,
})


# ──────────────────────────────────────────────────────────────────────────
# Result
# ──────────────────────────────────────────────────────────────────────────


class SafetyResult(BaseModel):
    """Outcome of a successful 5-layer pass (§11).

    On any layer rejection the caller sees a :class:`SafetyViolation` subclass
    raised instead; this struct exists only for the happy path so the
    orchestrator can persist the post-Layer-4 SQL and the AST it cleared.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    sql_validated: str
    tree: Any  # sqlglot AST (kept opaque outside agentxp.sql)
    layers_passed: list[int]
    warnings: list[str] = []


# ──────────────────────────────────────────────────────────────────────────
# Layer 2 — read-only assertion
# ──────────────────────────────────────────────────────────────────────────


# Top-level statement classes that mutate the warehouse. The §11 contract
# rejects each of these outright — even when wrapped in a CTE or subquery,
# sqlglot would still surface one of these node types via .walk().
_WRITE_NODES: tuple[type[exp.Expression], ...] = (
    exp.Delete,
    exp.Drop,
    exp.Update,
    exp.Insert,
    exp.TruncateTable,
    exp.Merge,
    exp.Create,
    exp.Alter,
)


def layer_2_assert_read_only(tree: exp.Expression) -> None:
    """Raise :class:`ReadOnlyViolation` if ``tree`` contains a write / DDL op.

    Forbidden top-level or nested statement types: DELETE, DROP, UPDATE,
    INSERT, TRUNCATE, MERGE, CREATE, ALTER. EXPLAIN is permitted (sqlglot
    parses it as ``exp.Command(this="EXPLAIN", ...)`` which is not a write).
    """
    for node in walk_ast(tree):
        if isinstance(node, _WRITE_NODES):
            raise ReadOnlyViolation(
                f"Write / DDL operation not permitted: {type(node).__name__}"
            )


# ──────────────────────────────────────────────────────────────────────────
# Layer 3a — single-adapter assertion
# ──────────────────────────────────────────────────────────────────────────


# Known adapter prefixes that may appear as the leading qualifier of a
# fully-qualified table reference (snowflake.db.schema.table, etc.).
_ADAPTER_PREFIXES: frozenset[str] = frozenset({
    "snowflake",
    "bigquery",
    "duckdb",
})


def layer_3a_assert_single_adapter(
    tree: exp.Expression,
    config: Optional[dict] = None,
    target_profile: Optional[str] = None,
) -> None:
    """Raise :class:`CrossAdapterViolation` on cross-adapter table references.

    v0.1 simplification per §11: when ``config`` is ``None`` the check is a
    no-op (ad-hoc queries against a single connection). Otherwise we scan
    every :class:`exp.Table` node for a leading-identifier adapter prefix
    and reject if two distinct prefixes appear in the same query.
    """
    if config is None:
        return

    found: set[str] = set()
    for node in walk_ast(tree):
        if not isinstance(node, exp.Table):
            continue
        # Walk the catalog / db / name chain looking for an adapter prefix
        # in the leading position.
        catalog = node.args.get("catalog")
        if catalog is None:
            continue
        name = getattr(catalog, "name", None) or str(catalog)
        if name and name.lower() in _ADAPTER_PREFIXES:
            found.add(name.lower())

    if len(found) > 1:
        raise CrossAdapterViolation(
            f"Query references multiple adapters: {sorted(found)}"
        )


# ──────────────────────────────────────────────────────────────────────────
# Layer 3b — semantic model check
# ──────────────────────────────────────────────────────────────────────────


def layer_3b_semantic_model_check(
    tree: exp.Expression,
    semantic_models: Optional[list] = None,
    strict: bool = True,
) -> None:
    """Raise :class:`SemanticModelViolation` on unknown fact sources.

    Walks every :class:`exp.Table` reference and asserts the un-qualified
    table name (or the rightmost identifier of a dotted path) is declared
    as a ``fact_source`` of one of ``semantic_models``. When
    ``semantic_models`` is ``None`` this is a no-op — the safety pipeline
    is allowed to run without semantic context for ad-hoc dispatches.
    """
    if semantic_models is None:
        return

    declared: set[str] = set()
    for model in semantic_models:
        sources = getattr(model, "fact_sources", None)
        if sources is None and isinstance(model, dict):
            sources = model.get("fact_sources", [])
        for src in (sources or []):
            name = getattr(src, "name", None) or (
                src.get("name") if isinstance(src, dict) else None
            )
            if name:
                declared.add(name.lower())

    for node in walk_ast(tree):
        if not isinstance(node, exp.Table):
            continue
        tbl_name = node.name
        if not tbl_name:
            continue
        if tbl_name.lower() not in declared:
            if strict:
                raise SemanticModelViolation(
                    f"Table {tbl_name!r} is not declared as a fact_source"
                )


# ──────────────────────────────────────────────────────────────────────────
# Layer 3c — deny-list + AST allowlist
# ──────────────────────────────────────────────────────────────────────────


_DENY_FUNCTIONS_UPPER: frozenset[str] = frozenset(n.upper() for n in DENY_FUNCTIONS)


def _function_names(node: exp.Expression) -> list[str]:
    """Return the candidate uppercase names for a function-call node."""
    out: list[str] = []
    if isinstance(node, exp.Anonymous):
        # `Anonymous.this` is the raw function name string.
        name = node.name or (
            node.this if isinstance(node.this, str) else None
        )
        if name:
            out.append(name.upper())
    elif isinstance(node, exp.Func):
        try:
            sn = node.sql_name()
            if sn:
                out.append(sn.upper())
        except Exception:
            pass
        name = getattr(node, "name", None)
        if name:
            out.append(str(name).upper())
    # Dotted call form (e.g. `BQ.JOBS.CANCEL(...)`): sqlglot may surface
    # the path through `exp.Dot` chains.
    if isinstance(node, exp.Dot):
        parts: list[str] = []
        cur: Any = node
        while isinstance(cur, exp.Dot):
            tail = cur.expression
            tail_name = getattr(tail, "name", None) or (
                str(tail) if tail is not None else ""
            )
            parts.append(tail_name)
            cur = cur.this
        head_name = getattr(cur, "name", None) or (str(cur) if cur is not None else "")
        parts.append(head_name)
        path = ".".join(reversed(parts)).upper()
        if path:
            out.append(path)
    return out


def _is_allowed_node(node: exp.Expression) -> bool:
    cls = type(node)
    for allowed in ALLOWED_AST_NODES:
        if cls is allowed or issubclass(cls, allowed):
            return True
    for allowed in _STRUCTURAL_ALLOWED:
        if cls is allowed or issubclass(cls, allowed):
            return True
    return False


def layer_3c_deny_list_check(tree: exp.Expression) -> None:
    """Raise :class:`DenyListViolation` on banned functions or AST shapes.

    Two complementary checks (§11):

    * **Function deny-list:** every :class:`exp.Anonymous` / :class:`exp.Func`
      / dotted-call node is matched case-insensitively against
      :data:`agentxp.sql.parser.DENY_FUNCTIONS`.
    * **AST allowlist:** every visited node's ``type()`` must be in (or be a
      subclass of) :data:`agentxp.sql.parser.ALLOWED_AST_NODES` or the
      module-local ``_STRUCTURAL_ALLOWED`` set.

    EXPLAIN is the one exception: sqlglot parses ``EXPLAIN <stmt>`` as an
    :class:`exp.Command` wrapping the inner statement text as a literal, so
    we permit the wrapper without re-parsing the inner literal here. (The
    adapter is responsible for refusing EXPLAIN against a write statement;
    Layer 2 has already verified the top-level wrapper is not a write.)
    """
    # Special-case: EXPLAIN at the root parses as Command("EXPLAIN", <Literal>).
    if isinstance(tree, exp.Command):
        kind = tree.args.get("this")
        kind_str = (
            kind if isinstance(kind, str) else getattr(kind, "name", "") or ""
        )
        if kind_str.upper() == "EXPLAIN":
            return
        raise DenyListViolation(
            f"Command {kind_str!r} is not permitted by Layer 3c"
        )

    for node in walk_ast(tree):
        # Function deny-list.
        for name in _function_names(node):
            if name in _DENY_FUNCTIONS_UPPER:
                raise DenyListViolation(
                    f"Function {name!r} is on the §11 deny-list"
                )
            # Also catch dotted-path hits like BQ.JOBS.CANCEL where only
            # the suffix appears in DENY_FUNCTIONS (none in v0.1, but the
            # path form is the canonical one in the spec).
        # AST allowlist.
        if not _is_allowed_node(node):
            raise DenyListViolation(
                f"AST node {type(node).__name__!r} is not in ALLOWED_AST_NODES"
            )


# ──────────────────────────────────────────────────────────────────────────
# Layer 4 — resource bounds (LIMIT injection / cap)
# ──────────────────────────────────────────────────────────────────────────


def layer_4_enforce_resource_bounds(
    tree: exp.Expression,
    purpose: str,
) -> exp.Expression:
    """Inject or cap a terminal ``LIMIT`` clause for ``purpose`` (§11).

    Looks up the per-purpose row-count cap from the §11 resource-bounds
    matrix. If the query has no LIMIT, injects ``LIMIT cap``. If the
    existing LIMIT is larger than ``cap``, replaces it. If it is smaller,
    leaves it alone (the user / agent has chosen a tighter bound).

    Returns the (possibly modified) sqlglot expression.
    """
    if purpose not in _ROW_LIMIT_BY_PURPOSE:
        raise ResourceBoundsViolation(
            f"Unknown purpose {purpose!r}; expected one of "
            f"{sorted(_ROW_LIMIT_BY_PURPOSE)}"
        )
    cap = _ROW_LIMIT_BY_PURPOSE[purpose]

    # Only Select-shaped roots take a terminal LIMIT. For non-Select roots
    # (e.g. exp.Command for EXPLAIN) we no-op.
    if not isinstance(tree, exp.Select):
        return tree

    existing = tree.args.get("limit")
    if existing is None:
        return tree.limit(cap)

    # Existing LIMIT — pull the integer value if we can.
    current_val: Optional[int] = None
    limit_expr = existing.expression if hasattr(existing, "expression") else None
    if isinstance(limit_expr, exp.Literal) and not limit_expr.is_string:
        try:
            current_val = int(limit_expr.name)
        except (TypeError, ValueError):
            current_val = None

    if current_val is None or current_val > cap:
        return tree.limit(cap)
    return tree


# ──────────────────────────────────────────────────────────────────────────
# Orchestrating entry point
# ──────────────────────────────────────────────────────────────────────────


def run_pipeline(
    sql: str,
    dialect: str,
    purpose: str,
    config: Optional[dict] = None,
    target_profile: Optional[str] = None,
    semantic_models: Optional[list] = None,
) -> SafetyResult:
    """Run the 5-layer §11 pipeline. Returns :class:`SafetyResult` on success.

    Layer order — fail-closed at every step:

      1. Parse                       (delegated to :func:`parse_sql`)
      2. Layer 2 read-only
      3a. Layer 3a cross-adapter
      3b. Layer 3b semantic model
      3c. Layer 3c deny-list / allowlist
      4. Layer 4 resource bounds      (rewrites the tree)

    The orchestrator catches :class:`SafetyViolation` at its own boundary
    and persists a ``SafetyLayerResult(passed=False, reason=...)`` row.
    """
    tree = parse_sql(sql, dialect)
    layers: list[int] = [1]

    layer_2_assert_read_only(tree)
    layers.append(2)

    layer_3a_assert_single_adapter(tree, config=config, target_profile=target_profile)
    layer_3b_semantic_model_check(tree, semantic_models=semantic_models)
    layer_3c_deny_list_check(tree)
    layers.append(3)

    tree = layer_4_enforce_resource_bounds(tree, purpose=purpose)
    layers.append(4)

    return SafetyResult(
        sql_validated=tree.sql(dialect=dialect if dialect != "sqlglot" else None),
        tree=tree,
        layers_passed=layers,
        warnings=[],
    )


__all__ = [
    # Exceptions
    "SafetyViolation",
    "ReadOnlyViolation",
    "CrossAdapterViolation",
    "SemanticModelViolation",
    "DenyListViolation",
    "ResourceBoundsViolation",
    "UnparseableSQL",
    # Result
    "SafetyResult",
    # Layer entry points
    "layer_2_assert_read_only",
    "layer_3a_assert_single_adapter",
    "layer_3b_semantic_model_check",
    "layer_3c_deny_list_check",
    "layer_4_enforce_resource_bounds",
    # Orchestrator
    "run_pipeline",
]
