"""Track C — 5-layer SQL safety: cross-adapter rejection smoke tests.

Per §11 Layer 3a, a query that references more than one warehouse adapter
(``snowflake.X join bigquery.Y``) MUST raise :class:`CrossAdapterViolation`
*before* any adapter dispatch. We exercise the rejection across all three
v0.1 adapter dialects.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §11 (Layer 3a).
"""
from __future__ import annotations

import pytest

from agentxp.sql.parser import parse_sql
from agentxp.sql.safety import (
    CrossAdapterViolation,
    layer_3a_assert_single_adapter,
)


# A dummy config to switch Layer 3a from "no-op" into enforcement mode.
_ENFORCE = {"enforce_cross_adapter": True}


@pytest.mark.parametrize("dialect", ["duckdb", "snowflake", "bigquery"])
def test_layer_3a_rejects_cross_adapter_join(dialect: str) -> None:
    """SELECT joining snowflake.* + bigquery.* must raise CrossAdapterViolation."""
    sql = (
        "SELECT a.id, b.id FROM snowflake.db.schema.events a "
        "JOIN bigquery.proj.ds.events b ON a.id = b.id"
    )
    tree = parse_sql(sql, dialect=dialect)
    with pytest.raises(CrossAdapterViolation):
        layer_3a_assert_single_adapter(tree, config=_ENFORCE, target_profile=None)


@pytest.mark.parametrize("dialect", ["duckdb", "snowflake", "bigquery"])
def test_layer_3a_allows_single_adapter(dialect: str) -> None:
    """A SELECT entirely under one adapter prefix must not raise."""
    sql = (
        "SELECT id FROM snowflake.db.schema.events"
    )
    tree = parse_sql(sql, dialect=dialect)
    # Should not raise.
    layer_3a_assert_single_adapter(tree, config=_ENFORCE, target_profile=None)


def test_layer_3a_no_config_is_noop() -> None:
    """v0.1 simplification: passing ``config=None`` makes Layer 3a a no-op.

    This is the FRESH/ad-hoc path — the orchestrator only enforces when a
    multi-adapter config is supplied.
    """
    sql = (
        "SELECT a.id FROM snowflake.db.s.t a JOIN bigquery.p.d.t b ON a.id=b.id"
    )
    tree = parse_sql(sql, dialect="duckdb")
    # No raise when config is None — see §11 / safety.py docstring.
    layer_3a_assert_single_adapter(tree, config=None, target_profile=None)
