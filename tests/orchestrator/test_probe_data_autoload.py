"""probe_data auto-loads semantic_models/*.yaml in design mode.

Pre-audit, ``probe_data(..., mode="design")`` with the default
``semantic_models=None`` made Layer 3d a silent no-op — R11 enforcement
depended on the orchestrator remembering to pass the models. Post-fix
the models load from ``<project_root>/semantic_models/`` by default, so
the wall fires without caller memory.
"""
from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

import pytest

from agentxp.orchestrator.tools import ToolRefusal, probe_data
from agentxp.sql.safety import SafetyViolation


_ASSIGNMENT_MODEL = textwrap.dedent("""\
    schema_version: 1
    name: assignment
    primary_key: [user_id, experiment_id]
    source_table: assignments
    dimensions:
      - name: user_id
        type: integer
      - name: experiment_id
        type: string
      - name: arm
        type: string
    outcome_columns: [arm]
""")


def _project_with_models(root: Path) -> Path:
    sm_dir = root / "semantic_models"
    sm_dir.mkdir()
    (sm_dir / "assignment.yaml").write_text(_ASSIGNMENT_MODEL)
    return root


def test_design_mode_autoloads_models_and_refuses_outcome_column():
    with tempfile.TemporaryDirectory() as tmp:
        root = _project_with_models(Path(tmp))
        with pytest.raises(SafetyViolation):
            probe_data(
                "SELECT arm, COUNT(*) FROM assignments GROUP BY arm",
                mode="design", purpose="profile", project_root=root,
            )


def test_design_mode_autoload_skips_template_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = _project_with_models(Path(tmp))
        (root / "semantic_models" / "_TEMPLATE.yaml").write_text("not: [valid")
        # Underscore-prefixed file ignored; the real model still loads.
        with pytest.raises(SafetyViolation):
            probe_data(
                "SELECT arm FROM assignments",
                mode="design", purpose="profile", project_root=root,
            )


def test_design_mode_malformed_model_refuses_rather_than_skips():
    """A model that fails to load must refuse the probe (fail-closed)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _project_with_models(Path(tmp))
        (root / "semantic_models" / "broken.yaml").write_text("name: broken\n")
        with pytest.raises(ToolRefusal, match="broken.yaml"):
            probe_data(
                "SELECT 1",
                mode="design", purpose="profile", project_root=root,
            )


def test_explicit_empty_list_skips_autoload_but_stays_fail_closed():
    """semantic_models=[] skips the auto-load, and Layer 3b then refuses
    every table (nothing is declared as a fact_source) — opting out of the
    auto-load does not open the wall."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _project_with_models(Path(tmp))
        with pytest.raises(SafetyViolation):
            probe_data(
                "SELECT COUNT(*) FROM assignments",
                mode="design", purpose="profile",
                semantic_models=[], project_root=root,
            )


def test_design_mode_autoload_with_no_models_dir_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        probe_data(
            "SELECT 1",
            mode="design", purpose="profile", project_root=Path(tmp),
        )
