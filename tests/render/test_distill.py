"""W1 distill purity + stability tests.

``distill()`` is the keystone of the presentation layer: a PURE projection from
the canonical ``Report`` to a fully-formatted ``ReportVM``. These tests pin the
contract that makes "add a format = add a renderer" safe:

  - Idempotent: ``distill(r) == distill(r)`` and repeated calls never diverge.
  - Non-mutating: ``report`` is byte-for-byte unchanged after distillation.
  - I/O-free + provenance-free: distill never touches disk/clock/network and
    never calls ``build_provenance`` (verification is a separate impure step).
  - Version-tolerant: both the v1 (pre-widening) and v2 (widened) fixtures
    distill to a valid ``ReportVM`` — a sparse VM is fine; a crash is not.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentxp.render.distill import distill
from agentxp.render.viewmodel import ReportVM
from agentxp.schemas.report import Report

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> Report:
    return Report.model_validate(json.loads((FIXTURES / name).read_text()))


@pytest.fixture(params=["report_v1.json", "report_v2.json"])
def report(request) -> Report:
    return _load(request.param)


def test_distill_returns_reportvm(report: Report):
    vm = distill(report)
    assert isinstance(vm, ReportVM)
    assert vm.experiment_id == report.experiment_id


def test_distill_is_idempotent(report: Report):
    """Same input → equal output, every time. No hidden state, no clock."""
    assert distill(report) == distill(report)


def test_distill_does_not_mutate_input(report: Report):
    """The canonical Report is left byte-for-byte unchanged."""
    before = report.model_dump_json()
    distill(report)
    assert report.model_dump_json() == before


def test_distill_never_calls_build_provenance(report: Report, monkeypatch):
    """Verification is a separate impure step; distill must not reach for it.

    We poison ``build_provenance`` so any call from within distill raises.
    """
    import agentxp.render.provenance as prov_mod

    def _boom(*args, **kwargs):  # pragma: no cover - only fires on a contract break
        raise AssertionError("distill() must never call build_provenance()")

    monkeypatch.setattr(prov_mod, "build_provenance", _boom)
    # A fresh import path inside distill would still resolve to the patched name
    # because distill imports the function lazily / by module attribute only if
    # it called it — it doesn't, so this simply must not raise.
    distill(report)


def test_distill_does_no_disk_io(report: Report, monkeypatch):
    """Guard against accidental file reads/writes sneaking into the pure path."""
    real_open = open

    def _no_open(*args, **kwargs):  # pragma: no cover - only fires on a contract break
        raise AssertionError(f"distill() performed disk I/O: open{args!r}")

    monkeypatch.setattr("builtins.open", _no_open)
    try:
        distill(report)
    finally:
        monkeypatch.setattr("builtins.open", real_open)


def test_distill_carries_rationale_verbatim(report: Report):
    """Agent prose passes through untouched — drift there is a bug."""
    vm = distill(report)
    assert vm.rationale_one_line == report.verdict_rationale
    assert vm.uncertainty_notes == [n.detail for n in report.uncertainty_notes]


def test_v1_distills_to_sparse_but_valid_vm():
    """A pre-widening report yields a valid VM with None diagnostics scalars."""
    vm = distill(_load("report_v1.json"))
    assert isinstance(vm, ReportVM)
    assert vm.diagnostics.n_observed is None
    assert vm.diagnostics.sample_pct is None
    assert vm.diagnostics.late_ratio is None


def test_v2_distills_with_full_diagnostics():
    """The widened fixture carries observed/required counts → a sample percent."""
    vm = distill(_load("report_v2.json"))
    assert vm.diagnostics.n_observed is not None
    assert vm.diagnostics.n_required is not None
    assert vm.diagnostics.sample_pct is not None
