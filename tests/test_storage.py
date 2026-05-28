"""
Tests for agentxp.storage — ExperimentStore and lifecycle state machine.

All tests use pytest's `tmp_path` fixture so no real ~/.agentxp/ is ever touched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agentxp.storage import ExperimentStore, store_from_env
from agentxp.storage.lifecycle import (
    VALID_TRANSITIONS,
    is_backward,
    validate_transition,
)


# --------------------------------------------------------------------- helpers


def _basic_yaml(
    exp_id: str = "checkout-redesign-2026q1",
    status: str = "DESIGNING",
    name: str = "Checkout Redesign",
) -> dict:
    return {
        "experiment": {
            "id": exp_id,
            "name": name,
            "status": status,
            "hypothesis": {
                "action": "Redesign the checkout button",
                "metric": "checkout_completion_rate",
                "direction": "increase",
                "magnitude": "5% relative lift",
                "mechanism": "Reduced friction",
            },
        }
    }


def _basic_analysis(version: int = 1) -> dict:
    return {
        "schema_version": 1,
        "analysis_version": version,
        "primary_metric": {
            "name": "checkout_completion_rate",
            "relative_lift": 0.105,
            "p_value": 0.018,
            "significant": True,
        },
        "srm": {"verdict": "PASS", "p_value": 0.73},
    }


@pytest.fixture
def store(tmp_path: Path) -> ExperimentStore:
    return ExperimentStore(root=tmp_path / "experiments")


# -------------------------------------------------------------------- basic I/O


def test_init_creates_root(tmp_path: Path):
    root = tmp_path / "nested" / "experiments"
    assert not root.exists()
    s = ExperimentStore(root=root)
    assert root.exists()
    assert s.root == root


def test_save_and_load_round_trip(store: ExperimentStore):
    exp_id = "checkout-redesign-2026q1"
    payload = _basic_yaml(exp_id=exp_id)
    path = store.save_experiment(exp_id, payload)

    assert path.exists()
    assert path.name == "experiment.yaml"

    loaded = store.load_experiment(exp_id)
    assert loaded["experiment"]["id"] == exp_id
    assert loaded["experiment"]["status"] == "DESIGNING"
    assert loaded["experiment"]["hypothesis"]["direction"] == "increase"


def test_load_missing_experiment_raises(store: ExperimentStore):
    with pytest.raises(FileNotFoundError, match="No experiment.yaml"):
        store.load_experiment("does-not-exist")


def test_invalid_experiment_id_rejected(store: ExperimentStore):
    with pytest.raises(ValueError, match="Invalid experiment_id"):
        store.save_experiment("bad/id", _basic_yaml())
    with pytest.raises(ValueError, match="Invalid experiment_id"):
        store.save_experiment("", _basic_yaml())
    with pytest.raises(ValueError, match="Invalid experiment_id"):
        store.save_experiment(".hidden", _basic_yaml())


# --------------------------------------------------------------------- analyses


def test_save_analysis_appends_multiple(store: ExperimentStore):
    exp_id = "exp-1"
    store.save_experiment(exp_id, _basic_yaml(exp_id=exp_id))

    p1 = store.save_analysis(exp_id, _basic_analysis(version=1))
    p2 = store.save_analysis(exp_id, _basic_analysis(version=2))
    p3 = store.save_analysis(exp_id, _basic_analysis(version=3))

    analyses_dir = store.root / exp_id / "analyses"
    files = sorted(analyses_dir.glob("*.json"))
    assert len(files) == 3
    assert p1 != p2 != p3

    latest = store.load_latest_analysis(exp_id)
    assert latest is not None
    assert latest["analysis_version"] == 3
    assert latest["experiment_id"] == exp_id


def test_load_latest_analysis_none_when_empty(store: ExperimentStore):
    exp_id = "exp-2"
    store.save_experiment(exp_id, _basic_yaml(exp_id=exp_id))
    assert store.load_latest_analysis(exp_id) is None


def test_save_analysis_rejects_unknown_experiment(store: ExperimentStore):
    with pytest.raises(FileNotFoundError, match="unknown experiment"):
        store.save_analysis("ghost", _basic_analysis())


# ------------------------------------------------------------------- list/filter


def test_list_experiments_filters_by_status(store: ExperimentStore):
    store.save_experiment("a", _basic_yaml("a", status="DESIGNING", name="A"))
    store.save_experiment("b", _basic_yaml("b", status="DESIGNING", name="B"))
    store.save_experiment("c", _basic_yaml("c", status="DESIGNING", name="C"))
    # Advance b to POWERED (legal forward transition)
    b_yaml = _basic_yaml("b", status="POWERED", name="B")
    store.save_experiment("b", b_yaml)

    all_rows = store.list_experiments()
    assert {r["id"] for r in all_rows} == {"a", "b", "c"}
    assert all(set(r.keys()) >= {"id", "name", "status", "created", "updated"}
               for r in all_rows)

    designing = store.list_experiments(status_filter="DESIGNING")
    assert {r["id"] for r in designing} == {"a", "c"}

    powered = store.list_experiments(status_filter="POWERED")
    assert {r["id"] for r in powered} == {"b"}
    assert powered[0]["name"] == "B"


def test_list_experiments_invalid_filter(store: ExperimentStore):
    with pytest.raises(ValueError, match="Invalid status_filter"):
        store.list_experiments(status_filter="NONSENSE")


# -------------------------------------------------------- state machine (unit)


def test_state_machine_forward_transitions_legal():
    assert validate_transition("DESIGNING", "POWERED") == (True, None)
    assert validate_transition("POWERED", "COLLECTING") == (True, None)
    assert validate_transition("COLLECTING", "ANALYZING") == (True, None)
    assert validate_transition("ANALYZING", "INTERPRETED") == (True, None)
    assert validate_transition("INTERPRETED", "REPORTED") == (True, None)
    assert validate_transition("REPORTED", "SHIPPED") == (True, None)
    assert validate_transition("SHIPPED", "COMPLETED") == (True, None)


def test_state_machine_skipping_is_illegal():
    ok, err = validate_transition("DESIGNING", "COLLECTING")
    assert ok is False
    assert "Illegal transition" in err
    assert "POWERED" in err  # hint mentions the missing stop

    ok, err = validate_transition("COLLECTING", "REPORTED")
    assert ok is False
    assert "Illegal transition" in err


def test_state_machine_backward_transitions_recognized():
    # POWERED -> DESIGNING is a retreat
    ok, err = validate_transition("POWERED", "DESIGNING")
    assert ok is True
    assert is_backward("POWERED", "DESIGNING") is True
    assert is_backward("DESIGNING", "POWERED") is False

    # ANALYZING -> COLLECTING is a retreat (SRM fix)
    assert validate_transition("ANALYZING", "COLLECTING") == (True, None)
    assert is_backward("ANALYZING", "COLLECTING") is True


def test_state_machine_terminal_states():
    ok, err = validate_transition("COMPLETED", "DESIGNING")
    assert ok is False
    assert "terminal" in err or "Illegal" in err

    ok, err = validate_transition("ABANDONED", "DESIGNING")
    assert ok is False


def test_state_machine_unknown_state():
    ok, err = validate_transition("BOGUS", "DESIGNING")
    assert ok is False
    assert "Unknown current state" in err

    ok, err = validate_transition("DESIGNING", "BOGUS")
    assert ok is False
    assert "Unknown target state" in err


def test_state_machine_noop_allowed():
    assert validate_transition("COLLECTING", "COLLECTING") == (True, None)


def test_valid_transitions_dict_covers_all_states():
    from agentxp.storage.lifecycle import ALL_STATES
    assert set(VALID_TRANSITIONS.keys()) == ALL_STATES


# ---------------------------------------------------- state machine (via store)


def test_store_legal_forward_progression(store: ExperimentStore):
    exp_id = "progress"
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="DESIGNING"))
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="POWERED"))
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="COLLECTING"))
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="ANALYZING"))
    loaded = store.load_experiment(exp_id)
    assert loaded["experiment"]["status"] == "ANALYZING"


def test_store_illegal_transition_raises(store: ExperimentStore):
    exp_id = "skipper"
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="DESIGNING"))
    with pytest.raises(ValueError, match="Illegal transition"):
        store.save_experiment(exp_id, _basic_yaml(exp_id, status="COLLECTING"))


def test_store_backward_requires_amendment(store: ExperimentStore):
    exp_id = "retreat"
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="DESIGNING"))
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="POWERED"))

    # Retreat without reason — rejected
    with pytest.raises(ValueError, match="amendment_reason"):
        store.save_experiment(exp_id, _basic_yaml(exp_id, status="DESIGNING"))

    # Retreat with reason — accepted
    path = store.save_experiment(
        exp_id,
        _basic_yaml(exp_id, status="DESIGNING"),
        amendment_reason="Power analysis returned NOT_VIABLE; reducing MDE.",
    )
    assert path.exists()
    assert store.load_experiment(exp_id)["experiment"]["status"] == "DESIGNING"


def test_store_invalid_status_in_yaml(store: ExperimentStore):
    bad = _basic_yaml("bad", status="DESIGNING")
    bad["experiment"]["status"] = "WAT"
    with pytest.raises(ValueError, match="Invalid status"):
        store.save_experiment("bad", bad)


# -------------------------------------------------------- interpretation/report


def test_save_interpretation_and_report(store: ExperimentStore):
    exp_id = "ship-it"
    store.save_experiment(exp_id, _basic_yaml(exp_id))

    interp_path = store.save_interpretation(
        exp_id,
        {
            "classification": "SHIP",
            "reasoning": "Primary up +10.5%, guardrails clean.",
        },
    )
    assert interp_path.exists()
    data = json.loads(interp_path.read_text())
    assert data["classification"] == "SHIP"
    assert data["experiment_id"] == exp_id
    assert "decided_at" in data

    report_path = store.save_report(exp_id, "# Report\n\nShip it.\n")
    assert report_path.exists()
    assert report_path.read_text().startswith("# Report")


def test_save_interpretation_invalid_classification(store: ExperimentStore):
    exp_id = "e"
    store.save_experiment(exp_id, _basic_yaml(exp_id))
    with pytest.raises(ValueError, match="Invalid interpretation.classification"):
        store.save_interpretation(exp_id, {"classification": "MAYBE"})


# ----------------------------------------------------------------- event log


def test_log_jsonl_captures_all_events(store: ExperimentStore):
    exp_id = "logged"
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="DESIGNING"))
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="POWERED"))
    store.save_analysis(exp_id, _basic_analysis())
    store.save_interpretation(exp_id, {"classification": "LEARN"})
    store.save_report(exp_id, "# r")

    events = store.history(exp_id)
    event_types = [e["event"] for e in events]
    assert "experiment_saved" in event_types  # initial save
    assert "status_change" in event_types  # DESIGNING -> POWERED
    assert "analysis_saved" in event_types
    assert "interpretation_saved" in event_types
    assert "report_saved" in event_types

    # Status change event has from/to
    sc = next(e for e in events if e["event"] == "status_change")
    assert sc["from_status"] == "DESIGNING"
    assert sc["to_status"] == "POWERED"

    # Every event is timestamped
    assert all("ts" in e for e in events)


def test_history_records_amendment_reason(store: ExperimentStore):
    exp_id = "amend"
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="DESIGNING"))
    store.save_experiment(exp_id, _basic_yaml(exp_id, status="POWERED"))
    store.save_experiment(
        exp_id,
        _basic_yaml(exp_id, status="DESIGNING"),
        amendment_reason="Power not viable",
    )
    events = store.history(exp_id)
    retreat = [
        e for e in events
        if e.get("from_status") == "POWERED" and e.get("to_status") == "DESIGNING"
    ]
    assert len(retreat) == 1
    assert retreat[0]["amendment_reason"] == "Power not viable"


def test_history_missing_experiment_raises(store: ExperimentStore):
    with pytest.raises(FileNotFoundError):
        store.history("never-existed")


# --------------------------------------------------------------------- delete


def test_delete_without_confirm_raises(store: ExperimentStore):
    exp_id = "doomed"
    store.save_experiment(exp_id, _basic_yaml(exp_id))
    with pytest.raises(ValueError, match="confirm=True"):
        store.delete_experiment(exp_id)
    # File must still exist
    assert (store.root / exp_id / "experiment.yaml").exists()


def test_delete_with_confirm_removes_dir(store: ExperimentStore):
    exp_id = "doomed2"
    store.save_experiment(exp_id, _basic_yaml(exp_id))
    store.save_analysis(exp_id, _basic_analysis())
    store.delete_experiment(exp_id, confirm=True)
    assert not (store.root / exp_id).exists()


def test_delete_missing_experiment_raises(store: ExperimentStore):
    with pytest.raises(FileNotFoundError):
        store.delete_experiment("nope", confirm=True)


def test_delete_removes_log_jsonl_too(store: ExperimentStore):
    """delete_experiment should take the entire dir with it, log.jsonl included."""
    exp_id = "doomed3"
    store.save_experiment(exp_id, _basic_yaml(exp_id))
    store.save_analysis(exp_id, _basic_analysis())

    log_path = store.root / exp_id / "log.jsonl"
    assert log_path.exists()

    store.delete_experiment(exp_id, confirm=True)

    # Entire directory (log included) is gone.
    assert not log_path.exists()
    assert not (store.root / exp_id).exists()


# --------------------------------------------------------------- corrupt yaml


def test_load_experiment_corrupt_yaml_raises(store: ExperimentStore):
    """Garbage bytes in an experiment.yaml should produce a clear RuntimeError."""
    exp_id = "corrupt-1"
    exp_dir = store.root / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = exp_dir / "experiment.yaml"
    # `{:\n[` is malformed YAML.
    yaml_path.write_text("{:\n[\n")

    with pytest.raises(RuntimeError, match="corrupt"):
        store.load_experiment(exp_id)


def test_save_experiment_corrupt_existing_yaml_raises(store: ExperimentStore):
    """save_experiment reads the existing file to validate transitions; if
    that file is corrupt it should raise a clear RuntimeError rather than
    silently clobber."""
    exp_id = "corrupt-2"
    exp_dir = store.root / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / "experiment.yaml").write_text("{:\n[\n")

    with pytest.raises(RuntimeError, match="corrupt"):
        store.save_experiment(exp_id, _basic_yaml(exp_id))


# ------------------------------------------------------------- atomic writes


def test_atomic_write_leaves_no_tmp_on_success(store: ExperimentStore):
    exp_id = "atomic"
    store.save_experiment(exp_id, _basic_yaml(exp_id))
    exp_dir = store.root / exp_id
    # No leftover tmp files
    leftovers = [p for p in exp_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_atomic_write_survives_interrupt(tmp_path: Path):
    """Simulate an interrupt (exception) during a write and confirm the old
    file is still intact and no partial replacement happened."""
    store = ExperimentStore(root=tmp_path / "e")
    exp_id = "interrupt"
    # First save writes a good file
    store.save_experiment(exp_id, _basic_yaml(exp_id, name="GOOD"))
    good_contents = store._yaml_path(exp_id).read_text()

    # Now patch os.replace to blow up mid-write
    import agentxp.storage.store as store_mod

    def boom(src, dst):
        raise RuntimeError("simulated crash before rename")

    with patch.object(store_mod.os, "replace", side_effect=boom):
        with pytest.raises(RuntimeError, match="simulated crash"):
            store.save_experiment(exp_id, _basic_yaml(exp_id, name="BAD"))

    # Original file untouched
    assert store._yaml_path(exp_id).read_text() == good_contents
    assert store.load_experiment(exp_id)["experiment"]["name"] == "GOOD"

    # No .tmp leftovers from the aborted write
    exp_dir = store.root / exp_id
    leftovers = [p for p in exp_dir.iterdir() if ".tmp" in p.name]
    assert leftovers == []


# ------------------------------------------------------------- factory / env


def test_store_from_env_uses_env_var(tmp_path: Path, monkeypatch):
    target = tmp_path / "envroot"
    monkeypatch.setenv("AGENTXP_STORE", str(target))
    s = store_from_env()
    assert s.root == target
    assert target.exists()


def test_store_from_env_default_not_touched(monkeypatch):
    """If AGENTXP_STORE isn't set, the factory still returns a store object
    rooted at the default — but we don't create/mutate ~/.agentxp here; we just
    verify the path resolution logic without calling the constructor's mkdir.
    """
    monkeypatch.delenv("AGENTXP_STORE", raising=False)
    # We don't actually build it (would mkdir ~/.agentxp). Just verify the
    # default constant is what we expect.
    from agentxp.storage.store import DEFAULT_ROOT
    assert DEFAULT_ROOT == "~/.agentxp/experiments"
