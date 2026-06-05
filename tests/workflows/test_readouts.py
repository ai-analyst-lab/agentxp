"""Tests for agentxp.workflows.readouts (V13)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from agentxp.render.catalog import (
    RenderCompletedEvent,
    catalog_append,
)
from agentxp.workflows.readouts import build_index, list_catalog


def test_list_catalog_returns_empty_when_missing():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp) / "exp_001"
        exp.mkdir()
        assert list_catalog(exp) == []


def test_list_catalog_parses_appended_entries():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp) / "exp_001"
        catalog_path = exp / "readouts" / "catalog.jsonl"
        catalog_append(
            catalog_path=catalog_path,
            experiment_id="exp_001",
            entry_id="01_1",
            payload=RenderCompletedEvent(
                readout_type="verdict",
                audience="exec",
                format="md",
                path="readouts/verdict/2026-06-04/exec.md",
                vm_sha256="a" * 64,
                provenance_render_status="VERIFIED",
            ),
        )
        rows = list_catalog(exp)
        assert len(rows) == 1
        assert rows[0].payload.readout_type == "verdict"


def test_build_index_re_export_works():
    """build_index is re-exported from agentxp.render.catalog."""
    with tempfile.TemporaryDirectory() as tmp:
        rows = build_index(Path(tmp))
        assert rows == []
