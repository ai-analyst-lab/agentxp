"""Tests for ``agentxp.semantic.io``.

Verifies that:
  - ``write_yaml`` + ``load_yaml`` round-trip preserves the model.
  - ``write_yaml`` lands files with chmod 0o600 (§1.7.3 secrets policy).
  - ``load_yaml`` surfaces YAML parse errors and Pydantic ``ValidationError``.
  - Concurrent multi-process writes serialize correctly under the project
    write lock (no interleaved bytes; no exitcode != 0).
"""
from __future__ import annotations

import multiprocessing
import os
import stat
import sys
import time
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agentxp.semantic.io import load_yaml, write_yaml
from agentxp.semantic.validators import (
    AssignmentYAML,
    SemanticModel,
)


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


def _semantic_model() -> SemanticModel:
    return SemanticModel.model_validate(
        {
            "schema_version": 1,
            "name": "user_events",
            "description": "User-level event facts.",
            "entity": {"primary": "user_id", "related": []},
            "fields": [
                {
                    "name": "user_id",
                    "type": "string",
                    "nullable": False,
                    "role": "identifier",
                },
                {
                    "name": "event_ts",
                    "type": "timestamp",
                    "nullable": False,
                    "role": "event_time",
                },
            ],
        }
    )


# ─────────────────────────────────────────────────────────────────────────
# Round-trip + atomicity tests
# ─────────────────────────────────────────────────────────────────────────


def test_round_trip_semantic_model(tmp_path: Path) -> None:
    sm = _semantic_model()
    target = tmp_path / "semantic_models" / "user_events.yaml"
    write_yaml(target, sm, tmp_path)
    assert target.exists()

    loaded = load_yaml(target, SemanticModel, tmp_path)
    assert loaded.model_dump() == sm.model_dump()


def test_write_yaml_creates_parent_dir(tmp_path: Path) -> None:
    sm = _semantic_model()
    target = tmp_path / "deeply" / "nested" / "semantic_models" / "user_events.yaml"
    assert not target.parent.exists()
    write_yaml(target, sm, tmp_path)
    assert target.exists()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod 600 semantics differ on Windows; §1.7.3 targets POSIX",
)
def test_write_yaml_sets_chmod_600(tmp_path: Path) -> None:
    sm = _semantic_model()
    target = tmp_path / "semantic_models" / "user_events.yaml"
    write_yaml(target, sm, tmp_path)

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, (
        f"Written YAML mode is {oct(mode)}, expected 0o600 (§1.7.3)"
    )


def test_write_yaml_leaves_no_tempfile_on_success(tmp_path: Path) -> None:
    sm = _semantic_model()
    target = tmp_path / "semantic_models" / "user_events.yaml"
    write_yaml(target, sm, tmp_path)

    # No leftover .tmp files in the directory.
    leftovers = [
        p
        for p in target.parent.iterdir()
        if p.name.startswith(f".{target.name}.") and p.name.endswith(".tmp")
    ]
    assert leftovers == [], f"Tempfile leaked: {leftovers}"


def test_load_yaml_raises_on_malformed_yaml(tmp_path: Path) -> None:
    target = tmp_path / "broken.yaml"
    target.write_text(":: this is :: not yaml\n  - [unbalanced\n")
    with pytest.raises(yaml.YAMLError):
        load_yaml(target, SemanticModel, tmp_path)


def test_load_yaml_raises_validation_error_on_schema_violation(tmp_path: Path) -> None:
    target = tmp_path / "bad.yaml"
    # schema_version mismatch (1 expected for SemanticModel; assignment shape too).
    target.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "name": "user_events",
                "description": "x",
                "entity": {"primary": "ghost", "related": []},
                "fields": [
                    {
                        "name": "user_id",
                        "type": "string",
                        "nullable": False,
                        "role": "identifier",
                    }
                ],
            }
        )
    )
    with pytest.raises(ValidationError):
        load_yaml(target, SemanticModel, tmp_path)


def test_load_yaml_raises_on_missing_file(tmp_path: Path) -> None:
    target = tmp_path / "does_not_exist.yaml"
    with pytest.raises(FileNotFoundError):
        load_yaml(target, SemanticModel, tmp_path)


def test_assignment_round_trip(tmp_path: Path) -> None:
    a = AssignmentYAML.model_validate(
        {
            "schema_version": 1,
            "name": "checkout_redesign",
            "description": "Variant assignment.",
            "type": "inline",
            "variant_column": "variant",
            "fact_source": "user_events",
            "randomization_unit": "user_id",
        }
    )
    target = tmp_path / "assignments" / "checkout_redesign.yaml"
    write_yaml(target, a, tmp_path)
    loaded = load_yaml(target, AssignmentYAML, tmp_path)
    assert loaded.model_dump() == a.model_dump()


# ─────────────────────────────────────────────────────────────────────────
# Concurrency: multi-process writers must serialize via project_write_lock
# ─────────────────────────────────────────────────────────────────────────


def _concurrent_writer(project_root: str, marker: str) -> None:
    """Worker invoked by the concurrent-writers test. Must be top-level
    for pickling under macOS spawn-mode multiprocessing.
    """
    root = Path(project_root)
    target = root / "semantic_models" / "user_events.yaml"
    sm = SemanticModel.model_validate(
        {
            "schema_version": 1,
            "name": "user_events",
            "description": marker,
            "entity": {"primary": "user_id", "related": []},
            "fields": [
                {
                    "name": "user_id",
                    "type": "string",
                    "nullable": False,
                    "role": "identifier",
                }
            ],
        }
    )
    write_yaml(target, sm, root)
    # Hold for a beat so siblings collide on the lock.
    time.sleep(0.1)


def test_concurrent_writes_serialize(tmp_path: Path) -> None:
    procs = [
        multiprocessing.Process(
            target=_concurrent_writer, args=(str(tmp_path), f"marker_{i}")
        )
        for i in range(3)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=15)
        assert p.exitcode == 0, f"Worker failed exitcode={p.exitcode}"

    target = tmp_path / "semantic_models" / "user_events.yaml"
    assert target.exists()
    # The file must parse as a single valid SemanticModel — no interleaved bytes.
    loaded = load_yaml(target, SemanticModel, tmp_path)
    assert loaded.description.startswith("marker_")
    # And on POSIX, mode is 0o600.
    if sys.platform != "win32":
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600
        assert os.access(str(target), os.R_OK | os.W_OK)
