"""Tests for agentxp migrate metrics (v1 → v2)."""
from __future__ import annotations

import yaml

from agentxp.cli.migrate_metrics import migrate_metric_v1_to_v2, migrate_one_file


def test_v1_to_v2_adds_schema_version():
    v1 = {"name": "x", "numerator": "count", "denominator": "users"}
    new, changes = migrate_metric_v1_to_v2(v1)
    assert new["schema_version"] == 2
    assert any("schema_version" in c for c in changes)


def test_already_v2_no_changes():
    v2 = {"schema_version": 2, "name": "x", "fact_source": "events"}
    new, changes = migrate_metric_v1_to_v2(v2)
    assert changes == []
    assert new == v2


def test_v1_adds_fact_source_placeholder():
    v1 = {"name": "x", "numerator": "count"}
    new, _ = migrate_metric_v1_to_v2(v1)
    assert "fact_source" in new


def test_migrate_one_file_writes_bak(tmp_path):
    yaml_path = tmp_path / "test.yaml"
    yaml_path.write_text("name: x\nnumerator: count\n")

    was_migrated, _ = migrate_one_file(yaml_path, dry_run=False)
    assert was_migrated

    bak = tmp_path / "test.yaml.bak"
    assert bak.exists()
    assert "name: x" in bak.read_text()

    new = yaml.safe_load(yaml_path.read_text())
    assert new["schema_version"] == 2


def test_migrate_one_file_dry_run_no_write(tmp_path):
    yaml_path = tmp_path / "test.yaml"
    original_text = "name: x\nnumerator: count\n"
    yaml_path.write_text(original_text)

    was_migrated, _ = migrate_one_file(yaml_path, dry_run=True)
    assert was_migrated

    assert yaml_path.read_text() == original_text  # untouched
    assert not (tmp_path / "test.yaml.bak").exists()


def test_idempotent(tmp_path):
    yaml_path = tmp_path / "test.yaml"
    yaml_path.write_text("name: x\nnumerator: count\n")

    migrate_one_file(yaml_path, dry_run=False)
    was_migrated_2nd, _ = migrate_one_file(yaml_path, dry_run=False)
    assert not was_migrated_2nd
