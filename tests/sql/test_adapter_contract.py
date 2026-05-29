"""Conformance tests asserting all four v0.1 adapters share one BaseAdapter shape.

Drives the shared harness in :mod:`tests.sql._adapter_contract` over every
registered dialect. The three v0.1.1 adapter builders extend this by importing
the same helpers in their per-adapter test files.
"""
from __future__ import annotations

from agentxp.sql.adapter import BaseAdapter
from agentxp.sql.adapters import ADAPTER_REGISTRY
from tests.sql._adapter_contract import (
    ALL_DIALECTS,
    DIALECTS,
    assert_conforms_to_base_adapter,
    assert_protocol_signature_parity,
    assert_result_models_canonical,
    make_adapter,
)


@ALL_DIALECTS
def test_adapter_conforms_to_base_adapter(dialect):
    assert_conforms_to_base_adapter(make_adapter(dialect), dialect)


@ALL_DIALECTS
def test_registry_resolves_dialect_to_class(dialect):
    cls = ADAPTER_REGISTRY[dialect]
    assert make_adapter(dialect).get_dialect() == dialect
    assert isinstance(cls(), BaseAdapter)


def test_registry_covers_exactly_the_four_dialects():
    assert set(ADAPTER_REGISTRY) == set(DIALECTS)


def test_all_adapters_share_identical_protocol_signatures():
    # Protocol presence != interchangeability; this catches parameter drift
    # (e.g. one adapter's execute(..., limit=) vs another's max_rows=).
    assert_protocol_signature_parity()


def test_adapter_result_models_are_canonical():
    # Pins the result/preview field sets so a new adapter can't return a
    # near-miss shape that callers would have to special-case.
    assert_result_models_canonical()
