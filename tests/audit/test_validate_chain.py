"""Tests for ``openxp.audit.chain.validate_chain`` (§10.7).

One test per Violation case enumerated in §10.7.2, plus the perf-budget
boundary cases (§10.7.3) and the happy path. The closure test in
``tests/coherence/test_canonical_names.py`` parametrizes over the 5 invariant
IDs and asserts each has a matching test name here.

Test naming follows §10.7.6 exactly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from openxp.audit.chain import PerfBudgetExceeded, validate_chain


# ──────────────────────────────────────────────────────────────────────────
# Fixture builders — a minimal valid on-disk experiment, plus mutators per test.
# ──────────────────────────────────────────────────────────────────────────


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _write_yaml(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def _build_healthy_experiment(tmp_path: Path, exp_id: str = "exp-001") -> Path:
    """Construct a minimal end-of-Stage-8-like experiment directory.

    Returns the experiments-root path (parent of the experiment dir).
    """
    root = tmp_path / "experiments_root"
    exp_dir = root / exp_id
    exp_dir.mkdir(parents=True)

    # log.jsonl — root + stage entered/committed + an open/resolve gate pair
    log_rows = [
        {
            "event_name": "stage.entered",
            "action_id": "A1",
            "parent_action_id": None,
            "stage": "0",
        },
        {
            "event_name": "gate.opened",
            "action_id": "A2",
            "parent_action_id": "A1",
            "stage": "0",
            "kind": "confirm_semantic_model",
        },
        {
            "event_name": "gate.resolved",
            "action_id": "A3",
            "parent_action_id": "A2",
            "stage": "0",
            "kind": "confirm_semantic_model",
        },
        {
            "event_name": "stage.committed",
            "action_id": "A4",
            "parent_action_id": "A3",
            "stage": "0",
        },
    ]
    _write_jsonl(exp_dir / "log.jsonl", log_rows)

    # conversation.jsonl — one turn that the bundle will reference
    _write_jsonl(
        exp_dir / "conversation.jsonl",
        [{"turn_id": "T1", "actor": "user", "text": "hi"}],
    )

    # bundles/{agent}.ctx.yaml referencing T1
    _write_yaml(
        exp_dir / "bundles" / "designer.elicitor.ctx.yaml",
        {
            "schema_version": 1,
            "conversation_ref": {
                "schema_version": 1,
                "file": "conversation.jsonl",
                "through_turn_id": "T1",
            },
        },
    )

    # bundles/{agent}.out.yaml referencing query Q1
    _write_yaml(
        exp_dir / "bundles" / "sql_query_writer.out.yaml",
        {"schema_version": 1, "queries": [{"query_id": "Q1"}]},
    )

    # queries/Q1.yaml — the artifact that the bundle references
    _write_yaml(
        exp_dir / "queries" / "Q1.yaml",
        {"schema_version": 1, "query_id": "Q1", "sql": "select 1"},
    )

    # decisions/d1.yaml referencing the bundle with the correct hash
    bundle_path = exp_dir / "bundles" / "designer.elicitor.ctx.yaml"
    bundle_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    _write_yaml(
        exp_dir / "decisions" / "d1.yaml",
        {
            "schema_version": 1,
            "provenance": {
                "bundle_path": "bundles/designer.elicitor.ctx.yaml",
                "bundle_hash": bundle_hash,
            },
        },
    )

    return root


# ──────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────


def test_all_invariants_ok_on_healthy_chain(tmp_path: Path) -> None:
    """§10.7.6 — happy path; no violations, ok=True, ms within soft cap."""
    root = _build_healthy_experiment(tmp_path)
    result = validate_chain("exp-001", _root=root)
    assert result.ok is True, f"unexpected violations: {result.violations}"
    assert result.violations == []
    assert result.invariants_checked == [1, 2, 3, 4, 5]
    assert result.ms >= 0.0
    assert result.perf_warning is False


# ──────────────────────────────────────────────────────────────────────────
# Invariant 1 — parent_action chain integrity
# ──────────────────────────────────────────────────────────────────────────


def test_invariant_1_parent_action_dangling(tmp_path: Path) -> None:
    """A log row references a parent_action_id that never appears."""
    root = _build_healthy_experiment(tmp_path)
    log_path = root / "exp-001" / "log.jsonl"
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    rows.append(
        {
            "event_name": "agent.dispatched",
            "action_id": "A99",
            "parent_action_id": "GHOST",
            "stage": "0",
        }
    )
    _write_jsonl(log_path, rows)

    result = validate_chain("exp-001", _root=root)
    assert result.ok is False
    inv1 = [v for v in result.violations if v.invariant_id == 1]
    assert len(inv1) == 1
    assert "GHOST" in inv1[0].description
    assert inv1[0].offending_action_id == "A99"


def test_invariant_1_parent_action_root_not_null(tmp_path: Path) -> None:
    """A non-root event carries parent_action_id=null."""
    root = _build_healthy_experiment(tmp_path)
    log_path = root / "exp-001" / "log.jsonl"
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    rows.append(
        {
            "event_name": "agent.dispatched",
            "action_id": "A99",
            "parent_action_id": None,
            "stage": "0",
        }
    )
    _write_jsonl(log_path, rows)

    result = validate_chain("exp-001", _root=root)
    assert result.ok is False
    inv1 = [v for v in result.violations if v.invariant_id == 1]
    assert any("parent_action_id=null" in v.description for v in inv1)


def test_invariant_1_duplicate_action_id(tmp_path: Path) -> None:
    """Two events share an action_id."""
    root = _build_healthy_experiment(tmp_path)
    log_path = root / "exp-001" / "log.jsonl"
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    # Duplicate "A1" — same id as the root event.
    rows.append(
        {
            "event_name": "agent.dispatched",
            "action_id": "A1",
            "parent_action_id": "A4",
            "stage": "0",
        }
    )
    _write_jsonl(log_path, rows)

    result = validate_chain("exp-001", _root=root)
    assert result.ok is False
    inv1 = [v for v in result.violations if v.invariant_id == 1]
    assert any("duplicate action_id=A1" in v.description for v in inv1)


# ──────────────────────────────────────────────────────────────────────────
# Invariant 2 — conversation_ref integrity
# ──────────────────────────────────────────────────────────────────────────


def test_invariant_2_conv_ref_dangling(tmp_path: Path) -> None:
    """Bundle's conversation_ref.through_turn_id is not in conversation.jsonl."""
    root = _build_healthy_experiment(tmp_path)
    bundle_path = root / "exp-001" / "bundles" / "designer.elicitor.ctx.yaml"
    bundle = yaml.safe_load(bundle_path.read_text())
    bundle["conversation_ref"]["through_turn_id"] = "T_GHOST"
    _write_yaml(bundle_path, bundle)

    result = validate_chain("exp-001", _root=root)
    assert result.ok is False
    inv2 = [v for v in result.violations if v.invariant_id == 2]
    assert len(inv2) == 1
    assert "T_GHOST" in inv2[0].description
    assert inv2[0].offending_path is not None
    assert "designer.elicitor.ctx.yaml" in inv2[0].offending_path


# ──────────────────────────────────────────────────────────────────────────
# Invariant 3 — artifact SHA256 match
# ──────────────────────────────────────────────────────────────────────────


def test_invariant_3_missing_query_artifact(tmp_path: Path) -> None:
    """A bundle.out.yaml references queries/{ulid}.yaml that doesn't exist."""
    root = _build_healthy_experiment(tmp_path)
    # Delete the referenced query artifact.
    (root / "exp-001" / "queries" / "Q1.yaml").unlink()

    result = validate_chain("exp-001", _root=root)
    assert result.ok is False
    inv3 = [v for v in result.violations if v.invariant_id == 3]
    assert any("missing query artifact" in v.description for v in inv3)
    assert any("Q1.yaml" in v.description for v in inv3)


def test_invariant_3_bundle_hash_mismatch(tmp_path: Path) -> None:
    """Decision-recorded bundle_hash does not match on-disk content."""
    root = _build_healthy_experiment(tmp_path)
    # Mutate the bundle file so its sha256 no longer matches the decision record.
    bundle_path = root / "exp-001" / "bundles" / "designer.elicitor.ctx.yaml"
    doc = yaml.safe_load(bundle_path.read_text())
    doc["new_field"] = "tampered"
    _write_yaml(bundle_path, doc)

    result = validate_chain("exp-001", _root=root)
    assert result.ok is False
    inv3 = [v for v in result.violations if v.invariant_id == 3]
    assert any("bundle_hash mismatch" in v.description for v in inv3)


# ──────────────────────────────────────────────────────────────────────────
# Invariant 4 — no stage.committed while gate is OPEN
# ──────────────────────────────────────────────────────────────────────────


def test_invariant_4_commit_with_open_gate(tmp_path: Path) -> None:
    """stage.committed fires while a gate.opened is unmatched on that stage."""
    root = _build_healthy_experiment(tmp_path)
    log_path = root / "exp-001" / "log.jsonl"
    # Replace the gate.resolved row with a no-op so the gate stays OPEN.
    rows = [
        {
            "event_name": "stage.entered",
            "action_id": "A1",
            "parent_action_id": None,
            "stage": "0",
        },
        {
            "event_name": "gate.opened",
            "action_id": "A2",
            "parent_action_id": "A1",
            "stage": "0",
            "kind": "confirm_semantic_model",
        },
        # NOTE: no gate.resolved — gate stays OPEN.
        {
            "event_name": "stage.committed",
            "action_id": "A4",
            "parent_action_id": "A2",
            "stage": "0",
        },
    ]
    _write_jsonl(log_path, rows)

    result = validate_chain("exp-001", _root=root)
    assert result.ok is False
    inv4 = [v for v in result.violations if v.invariant_id == 4]
    assert len(inv4) == 1
    assert "confirm_semantic_model" in inv4[0].description
    assert "OPEN" in inv4[0].description


# ──────────────────────────────────────────────────────────────────────────
# Invariant 5 — no gate.resolved/blocked without preceding gate.opened
# ──────────────────────────────────────────────────────────────────────────


def test_invariant_5_resolve_without_open(tmp_path: Path) -> None:
    """gate.resolved with no preceding gate.opened on the same (stage, kind)."""
    root = _build_healthy_experiment(tmp_path)
    log_path = root / "exp-001" / "log.jsonl"
    rows = [
        {
            "event_name": "stage.entered",
            "action_id": "A1",
            "parent_action_id": None,
            "stage": "0",
        },
        {
            "event_name": "gate.resolved",
            "action_id": "A2",
            "parent_action_id": "A1",
            "stage": "0",
            "kind": "confirm_semantic_model",
        },
    ]
    _write_jsonl(log_path, rows)

    result = validate_chain("exp-001", _root=root)
    assert result.ok is False
    inv5 = [v for v in result.violations if v.invariant_id == 5]
    assert len(inv5) == 1
    assert "gate.resolved" in inv5[0].description
    assert "without preceding gate.opened" in inv5[0].description


def test_invariant_5_block_without_open(tmp_path: Path) -> None:
    """gate.blocked with no preceding gate.opened on the same (stage, kind)."""
    root = _build_healthy_experiment(tmp_path)
    log_path = root / "exp-001" / "log.jsonl"
    rows = [
        {
            "event_name": "stage.entered",
            "action_id": "A1",
            "parent_action_id": None,
            "stage": "0",
        },
        {
            "event_name": "gate.blocked",
            "action_id": "A2",
            "parent_action_id": "A1",
            "stage": "0",
            "kind": "confirm_semantic_model",
            "reason": "disk_full",
        },
    ]
    _write_jsonl(log_path, rows)

    result = validate_chain("exp-001", _root=root)
    assert result.ok is False
    inv5 = [v for v in result.violations if v.invariant_id == 5]
    assert len(inv5) == 1
    assert "gate.blocked" in inv5[0].description


# ──────────────────────────────────────────────────────────────────────────
# Perf budget (§10.7.3)
# ──────────────────────────────────────────────────────────────────────────


def test_perf_warning_at_soft_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ms > soft cap → perf_warning=True, ok=True (still commits, §10.7.3)."""
    root = _build_healthy_experiment(tmp_path)

    # Inject a synthetic delay by monkeypatching time.perf_counter to advance
    # by ~250 ms (above the 200 ms soft cap, below the 400 ms hard cap).
    import openxp.audit.chain as chain_mod

    real_perf_counter = chain_mod.time.perf_counter
    call_count = {"n": 0}

    def fake_perf_counter() -> float:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return 0.0
        return 0.25  # 250 ms elapsed

    monkeypatch.setattr(chain_mod.time, "perf_counter", fake_perf_counter)

    result = validate_chain("exp-001", _root=root)
    # Restore for safety (monkeypatch unwinds on teardown anyway).
    chain_mod.time.perf_counter = real_perf_counter

    assert result.ok is True
    assert result.perf_warning is True
    assert result.ms > 200.0
    assert result.ms < 400.0


def test_perf_budget_exceeded_at_hard_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ms > 2 × soft cap → raises PerfBudgetExceeded (§10.7.3 hard cap)."""
    root = _build_healthy_experiment(tmp_path)

    import openxp.audit.chain as chain_mod

    call_count = {"n": 0}

    def fake_perf_counter() -> float:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return 0.0
        return 0.5  # 500 ms elapsed — beyond the 400 ms hard cap

    monkeypatch.setattr(chain_mod.time, "perf_counter", fake_perf_counter)

    with pytest.raises(PerfBudgetExceeded) as exc_info:
        validate_chain("exp-001", _root=root)
    assert "hard cap" in str(exc_info.value)


# ──────────────────────────────────────────────────────────────────────────
# Partial-range validation (§10.7.6)
# ──────────────────────────────────────────────────────────────────────────


def test_partial_range_validation(tmp_path: Path) -> None:
    """from_event/to_event restrict the log walk.

    By limiting the walk to the first two rows, we exclude the gate.resolved
    + stage.committed pair, leaving the gate OPEN at the slice boundary. That
    is NOT itself a violation (Invariant 4 only fires on a stage.committed
    while-open), so the slice should still validate. But excluding the
    opener and including the resolver should trigger Invariant 5.
    """
    root = _build_healthy_experiment(tmp_path)

    # Slice [0, 2) — only stage.entered + gate.opened. No violations expected.
    result = validate_chain("exp-001", _root=root, from_event=0, to_event=2)
    assert result.ok is True, f"unexpected violations on slice: {result.violations}"

    # Slice [2, 4) — gate.resolved + stage.committed without preceding opener.
    # That's an Invariant 5 violation (resolver with no opener visible).
    result = validate_chain("exp-001", _root=root, from_event=2, to_event=4)
    assert result.ok is False
    assert any(v.invariant_id == 5 for v in result.violations)
