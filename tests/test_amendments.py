"""
Tests for openxp.amendments — diff, classify, and the AmendmentTracker.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from openxp.amendments import (
    Amendment,
    AmendmentTracker,
    classify_change,
    diff_experiments,
    require_amendment_for_transition,
)
from openxp.storage.store import ExperimentStore


# ------------------------------------------------------------------ fixtures


def _base_yaml(status: str = "COLLECTING") -> dict:
    return {
        "experiment": {
            "id": "checkout-redesign-2026q1",
            "name": "Checkout redesign",
            "status": status,
            "hypothesis": {
                "action": "Single-page checkout",
                "metric": "conversion_rate",
                "direction": "increase",
                "magnitude": "5% relative",
                "mechanism": "Less friction",
            },
            "metrics": {
                "primary": {
                    "name": "conversion_rate",
                    "type": "proportion",
                    "definition": "orders / sessions",
                    "mde": 0.05,
                    "baseline": 0.12,
                },
                "secondary": [
                    {"name": "aov", "type": "continuous", "definition": "avg order value"},
                    {"name": "items_per_order", "type": "continuous", "definition": "items/order"},
                ],
                "guardrail": [
                    {
                        "name": "support_tickets",
                        "type": "continuous",
                        "threshold": 0.02,
                        "direction": "do_not_increase",
                        "definition": "tickets per user",
                    }
                ],
            },
            "power": {
                "alpha": 0.05,
                "power": 0.80,
                "duration_days": 14,
                "sample_size_per_group": 10000,
            },
            "description": "Initial rollout plan",
            "tags": ["checkout", "growth"],
            "timeline": {"created": "2026-03-01"},
            "results": {"srm_verdict": None},
        }
    }


@pytest.fixture
def store(tmp_path: Path) -> ExperimentStore:
    return ExperimentStore(root=tmp_path / "exps")


@pytest.fixture
def tracker(store: ExperimentStore) -> AmendmentTracker:
    return AmendmentTracker(store)


@pytest.fixture
def saved_experiment(store: ExperimentStore) -> str:
    exp_id = "checkout-redesign-2026q1"
    store.save_experiment(exp_id, _base_yaml("COLLECTING"))
    return exp_id


# ------------------------------------------------------------------ diff tests


def test_diff_detects_scalar_change():
    before = {"a": {"b": 1}}
    after = {"a": {"b": 2}}
    diff = diff_experiments(before, after)
    assert diff == [{"path": "a.b", "op": "changed", "before": 1, "after": 2}]


def test_diff_detects_added_and_removed_nested():
    before = {"a": {"b": 1}, "c": 3}
    after = {"a": {"b": 1, "d": 4}}
    diff = diff_experiments(before, after)
    paths = {(c["path"], c["op"]) for c in diff}
    assert ("a.d", "added") in paths
    assert ("c", "removed") in paths
    # c removed record carries before value.
    removed = next(c for c in diff if c["path"] == "c")
    assert removed["before"] == 3 and removed["after"] is None


def test_diff_deep_list_fields():
    before = _base_yaml()
    after = copy.deepcopy(before)
    # Rename second secondary metric.
    after["experiment"]["metrics"]["secondary"][1]["name"] = "line_items_per_order"
    diff = diff_experiments(before, after)
    assert any(
        c["path"] == "experiment.metrics.secondary[1].name"
        and c["op"] == "changed"
        and c["before"] == "items_per_order"
        and c["after"] == "line_items_per_order"
        for c in diff
    ), diff


def test_diff_list_length_delta_reports_added_index():
    before = _base_yaml()
    after = copy.deepcopy(before)
    after["experiment"]["metrics"]["secondary"].append(
        {"name": "refund_rate", "type": "proportion", "definition": "refunds/orders"}
    )
    diff = diff_experiments(before, after)
    added = [c for c in diff if c["op"] == "added"]
    assert any(c["path"] == "experiment.metrics.secondary[2]" for c in added), added


def test_diff_empty_when_equal():
    y = _base_yaml()
    assert diff_experiments(y, copy.deepcopy(y)) == []


def test_diff_rejects_non_dict():
    with pytest.raises(TypeError):
        diff_experiments([], {})  # type: ignore[arg-type]


# ------------------------------------------------------------ classify tests


def test_classify_metric_rename_is_material():
    change = {
        "path": "experiment.metrics.primary.name",
        "op": "changed",
        "before": "conversion_rate",
        "after": "checkout_conversion",
    }
    assert classify_change(change) == "material"


def test_classify_power_change_is_material():
    change = {
        "path": "experiment.power.duration_days",
        "op": "changed",
        "before": 14,
        "after": 21,
    }
    assert classify_change(change) == "material"


def test_classify_description_edit_is_administrative():
    change = {
        "path": "experiment.description",
        "op": "changed",
        "before": "v1",
        "after": "v2",
    }
    assert classify_change(change) == "administrative"


def test_classify_tags_and_timeline_administrative():
    assert (
        classify_change(
            {"path": "experiment.tags[0]", "op": "changed", "before": "a", "after": "b"}
        )
        == "administrative"
    )
    assert (
        classify_change(
            {"path": "experiment.timeline.created", "op": "changed", "before": "x", "after": "y"}
        )
        == "administrative"
    )


def test_classify_experiment_name_is_administrative():
    # Human-readable name under an otherwise-material tree is admin.
    assert (
        classify_change(
            {"path": "experiment.name", "op": "changed", "before": "A", "after": "B"}
        )
        == "administrative"
    )


# ----------------------------------------------------- transition rule tests


def test_require_amendment_for_retreats():
    assert require_amendment_for_transition("POWERED", "DESIGNING") is True
    assert require_amendment_for_transition("ANALYZING", "COLLECTING") is True
    assert require_amendment_for_transition("INTERPRETED", "COLLECTING") is True
    assert require_amendment_for_transition("INVALID", "DESIGNING") is True


def test_require_amendment_false_for_forward():
    assert require_amendment_for_transition("DESIGNING", "POWERED") is False
    assert require_amendment_for_transition("COLLECTING", "ANALYZING") is False
    assert require_amendment_for_transition("INTERPRETED", "REPORTED") is False


# ------------------------------------------------------------- tracker tests


def test_record_first_amendment_round_trip(tracker, saved_experiment):
    new = copy.deepcopy(_base_yaml("COLLECTING"))
    new["experiment"]["power"]["duration_days"] = 21

    amendment = tracker.record_amendment(
        saved_experiment,
        new,
        reason="Traffic lower than expected, extending duration to reach power.",
    )

    assert isinstance(amendment, Amendment)
    assert amendment.material is True
    assert amendment.from_state == "COLLECTING"
    assert amendment.to_state == "COLLECTING"
    # Change path present.
    paths = [c["path"] for c in amendment.changes]
    assert "experiment.power.duration_days" in paths

    # list_amendments round-trips and returns the same record.
    listed = tracker.list_amendments(saved_experiment)
    assert len(listed) == 1
    assert listed[0].id == amendment.id
    assert listed[0].reason == amendment.reason


def test_record_multiple_amendments_in_order(tracker, saved_experiment):
    y1 = copy.deepcopy(_base_yaml("COLLECTING"))
    y1["experiment"]["power"]["duration_days"] = 21
    a1 = tracker.record_amendment(
        saved_experiment, y1, reason="Need more runway to hit power."
    )

    # Second amendment diffs against the CURRENT store state (still original),
    # because record_amendment does not persist the yaml.
    y2 = copy.deepcopy(_base_yaml("COLLECTING"))
    y2["experiment"]["description"] = "Revised rollout notes"
    a2 = tracker.record_amendment(
        saved_experiment, y2, reason="Clarifying the rollout plan doc."
    )

    listed = tracker.list_amendments(saved_experiment)
    assert [a.id for a in listed] == [a1.id, a2.id]
    assert listed[0].material is True
    assert listed[1].material is False


def test_reason_too_short_raises(tracker, saved_experiment):
    new = copy.deepcopy(_base_yaml("COLLECTING"))
    new["experiment"]["power"]["duration_days"] = 21
    with pytest.raises(ValueError, match="reason"):
        tracker.record_amendment(saved_experiment, new, reason="short")


def test_material_amendments_filters(tracker, saved_experiment):
    # One material, one administrative.
    y_material = copy.deepcopy(_base_yaml("COLLECTING"))
    y_material["experiment"]["metrics"]["primary"]["name"] = "cvr"
    tracker.record_amendment(
        saved_experiment, y_material, reason="Renaming primary metric for clarity."
    )

    y_admin = copy.deepcopy(_base_yaml("COLLECTING"))
    y_admin["experiment"]["description"] = "Updated description for readers."
    tracker.record_amendment(
        saved_experiment, y_admin, reason="Doc cleanup for stakeholder readout."
    )

    mat = tracker.material_amendments(saved_experiment)
    assert len(mat) == 1
    assert mat[0].material is True


def test_amendments_file_location_and_get(tracker, saved_experiment, store):
    new = copy.deepcopy(_base_yaml("COLLECTING"))
    new["experiment"]["power"]["sample_size_per_group"] = 15000
    a = tracker.record_amendment(
        saved_experiment, new, reason="Sample size bumped after baseline refresh."
    )

    expected = store.root / saved_experiment / "amendments.jsonl"
    assert expected.exists(), f"expected {expected} to exist"
    lines = expected.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["id"] == a.id
    assert record["material"] is True

    got = tracker.get_amendment(saved_experiment, a.id)
    assert got.id == a.id

    with pytest.raises(KeyError):
        tracker.get_amendment(saved_experiment, "no-such-id")


def test_amendment_breadcrumb_in_store_history(tracker, saved_experiment, store):
    new = copy.deepcopy(_base_yaml("COLLECTING"))
    new["experiment"]["power"]["duration_days"] = 28
    a = tracker.record_amendment(
        saved_experiment, new, reason="Extending for holiday traffic calibration."
    )

    events = store.history(saved_experiment)
    amendment_events = [e for e in events if e.get("event") == "amendment_recorded"]
    assert len(amendment_events) == 1
    assert amendment_events[0]["amendment_id"] == a.id
    assert amendment_events[0]["material"] is True


def test_list_amendments_empty_for_fresh_experiment(tracker, saved_experiment):
    assert tracker.list_amendments(saved_experiment) == []


def test_existing_storage_tests_untouched_hook_check():
    # Sanity: the ExperimentStore public surface we rely on still exists.
    store = ExperimentStore
    assert hasattr(store, "save_experiment")
    assert hasattr(store, "load_experiment")
    assert hasattr(store, "history")
