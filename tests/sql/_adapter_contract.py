"""Shared contract-conformance harness for AgentXP warehouse adapters.

W0 scaffolding the three v0.1.1 adapter builders reuse to assert that all four
adapters conform identically to :class:`agentxp.sql.adapter.BaseAdapter`. Not a
test module itself (the leading underscore keeps pytest from collecting it);
import the helpers / parametrize markers from per-adapter test files.

Usage in a per-adapter test::

    from tests.sql._adapter_contract import (
        assert_conforms_to_base_adapter,
        make_adapter,
    )

    def test_my_adapter_conforms():
        assert_conforms_to_base_adapter(make_adapter("duckdb"), "duckdb")

Or drive all four at once with the parametrize marker::

    @ALL_DIALECTS
    def test_every_adapter_conforms(dialect):
        assert_conforms_to_base_adapter(make_adapter(dialect), dialect)

All constructors here are credential-free: the stub adapters store ``**conn_params``
without connecting, and DuckDB connects lazily (no I/O at construction). Nothing
in this harness touches a live warehouse.
"""
from __future__ import annotations

from typing import Any

import pytest

from agentxp.sql.adapter import BaseAdapter
from agentxp.sql.adapters import ADAPTER_REGISTRY

#: The four dialects every v0.1 adapter (reference + 3 stubs) registers under.
DIALECTS: tuple[str, ...] = ("duckdb", "snowflake", "bigquery", "databricks")

#: Reusable parametrize marker over all four dialects. Apply to a test taking a
#: ``dialect`` argument: ``@ALL_DIALECTS`` then ``def test_x(dialect): ...``.
ALL_DIALECTS = pytest.mark.parametrize("dialect", DIALECTS)


def make_adapter(dialect: str) -> Any:
    """Construct the registered adapter for ``dialect`` without credentials.

    DuckDB gets an in-memory connection (no file, lazy connect). The stub
    adapters accept arbitrary ``**conn_params`` and never connect, so an empty
    construction is safe and credential-free for all four.
    """
    cls = ADAPTER_REGISTRY[dialect]
    return cls()


def assert_conforms_to_base_adapter(adapter: Any, expected_dialect: str) -> None:
    """Assert ``adapter`` satisfies the BaseAdapter contract.

    Checks, in order:

    (a) ``isinstance(adapter, BaseAdapter)`` — relies on the
        ``@runtime_checkable`` Protocol, so this confirms the five required
        methods are present.
    (b) ``adapter.get_dialect()`` returns ``expected_dialect``.
    (c) all five Protocol methods exist and are callable.
    """
    assert isinstance(adapter, BaseAdapter), (
        f"{type(adapter).__name__} does not satisfy the BaseAdapter Protocol"
    )
    assert adapter.get_dialect() == expected_dialect, (
        f"{type(adapter).__name__}.get_dialect() returned "
        f"{adapter.get_dialect()!r}, expected {expected_dialect!r}"
    )
    for method in ("execute", "explain", "dry_run", "get_dialect", "close"):
        assert callable(getattr(adapter, method, None)), (
            f"{type(adapter).__name__} is missing callable .{method}()"
        )


__all__ = [
    "ALL_DIALECTS",
    "DIALECTS",
    "assert_conforms_to_base_adapter",
    "make_adapter",
]
