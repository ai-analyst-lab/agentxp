"""W6.2 + W6.3 + W6.4 tests."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentxp.render import FORMATS, PERSONAS, fan_out
from agentxp.render.distill import distill_intent
from agentxp.render.voice_audit import BannedVocabularyError


def _init_repo(root: Path) -> None:
    (root / "experiments").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "ci@agentxp.test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=root, check=True)


def test_fan_out_produces_six_paths(tmp_path: Path) -> None:
    """W6.4 acceptance — six (audience, fmt) variants in one call."""
    _init_repo(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_test"
    exp_dir.mkdir(parents=True)

    vm = distill_intent(
        experiment_id="exp_test",
        intent_text="A test intent.",
        captured_at=datetime(2026, 6, 6, 4, 0, 0, tzinfo=timezone.utc),
        captured_by="test@example.com",
    )

    paths = fan_out(
        exp_dir=exp_dir,
        experiment_id="exp_test",
        readout_type="intent",
        vm=vm,
        vm_sha256="0" * 64,
    )
    assert len(paths) == 6


def test_fan_out_deterministic_order(tmp_path: Path) -> None:
    """W6.4 — order is exec → operator → engineer, html → pdf, per fixed Cartesian."""
    _init_repo(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_test"
    exp_dir.mkdir(parents=True)
    vm = distill_intent(
        experiment_id="exp_test",
        intent_text="test",
        captured_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
        captured_by="t@e.com",
    )
    paths = fan_out(
        exp_dir=exp_dir,
        experiment_id="exp_test",
        readout_type="intent",
        vm=vm,
        vm_sha256="0" * 64,
    )
    # PERSONAS × FORMATS Cartesian, in declared order.
    expected_suffixes = [
        f"{audience}.{fmt}"
        for audience in PERSONAS
        for fmt in FORMATS
    ]
    actual_suffixes = [p.name for p in paths]
    assert actual_suffixes == expected_suffixes


def test_fan_out_catalog_has_six_rows_with_shared_base(tmp_path: Path) -> None:
    """W6.3 — six rows in catalog, all sharing the same entry_id_base prefix."""
    _init_repo(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_test"
    exp_dir.mkdir(parents=True)
    vm = distill_intent(
        experiment_id="exp_test", intent_text="t",
        captured_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
        captured_by="t@e.com",
    )
    fan_out(
        exp_dir=exp_dir, experiment_id="exp_test", readout_type="intent",
        vm=vm, vm_sha256="0" * 64,
        entry_id_base="fan-deterministic",
    )
    catalog = (exp_dir / "readouts" / "catalog.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in catalog]
    assert len(rows) == 6
    for row in rows:
        assert row["entry_id"].startswith("fan-deterministic-")
    # 6 distinct entry_ids despite shared base.
    assert len({r["entry_id"] for r in rows}) == 6


def test_new_entry_id_collision_resistant() -> None:
    """W6.3 — six successive calls within one tick produce distinct ids."""
    from agentxp.orchestrator.tools import _new_entry_id

    ids = {_new_entry_id() for _ in range(50)}
    assert len(ids) == 50, "uuid4-derived entry ids must not collide under tight succession"


def test_fan_out_carries_computed_render_status(tmp_path: Path) -> None:
    """W4.2 acceptance via fan-out — intent renders are DRAFT_UNVERIFIED across all rows."""
    _init_repo(tmp_path)
    exp_dir = tmp_path / "experiments" / "exp_test"
    exp_dir.mkdir(parents=True)
    vm = distill_intent(
        experiment_id="exp_test", intent_text="t",
        captured_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
        captured_by="t@e.com",
    )
    fan_out(
        exp_dir=exp_dir, experiment_id="exp_test", readout_type="intent",
        vm=vm, vm_sha256="0" * 64,
    )
    catalog = (exp_dir / "readouts" / "catalog.jsonl").read_text().splitlines()
    for line in catalog:
        row = json.loads(line)
        assert row["payload"]["provenance_render_status"] == "DRAFT_UNVERIFIED"
