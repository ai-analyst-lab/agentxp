"""T50/T51 — renders catalog hash chain + index tests."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentxp.render.catalog import (
    CatalogChainBreak,
    CatalogEntry,
    PruneCompletedEvent,
    RenderBriefDriftFlaggedEvent,
    RenderCompletedEvent,
    RenderSupersededEvent,
    build_index,
    catalog_append,
    validate_catalog,
)


def _render_completed(**kw) -> RenderCompletedEvent:
    defaults = dict(
        readout_type="verdict",
        audience="exec",
        format="html",
        path="readouts/verdict/2026-06-04/exec.html",
        vm_sha256="a" * 64,
        provenance_render_status="VERIFIED",
    )
    defaults.update(kw)
    return RenderCompletedEvent(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Append + chain validation
# ─────────────────────────────────────────────────────────────────────────────


def test_first_entry_has_genesis_prev_hash():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "catalog.jsonl"
        entry = catalog_append(
            catalog_path=path,
            experiment_id="exp_001",
            entry_id="01HZX...",
            payload=_render_completed(),
        )
        assert entry.prev_catalog_entry_hash == "genesis"


def test_subsequent_entries_chain_to_prior():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "catalog.jsonl"
        e1 = catalog_append(
            catalog_path=path, experiment_id="exp_001",
            entry_id="01ULID1", payload=_render_completed(),
        )
        e2 = catalog_append(
            catalog_path=path, experiment_id="exp_001",
            entry_id="01ULID2",
            payload=_render_completed(readout_type="verdict", audience="operator"),
        )
        # e2.prev should be sha256 of e1's canonical bytes
        assert e2.prev_catalog_entry_hash != "genesis"
        assert len(e2.prev_catalog_entry_hash) == 64
        # Chain validates
        validate_catalog(path)


def test_validate_catalog_passes_clean_chain():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "catalog.jsonl"
        for i in range(5):
            catalog_append(
                catalog_path=path, experiment_id="exp_001",
                entry_id=f"01ULID{i}",
                payload=_render_completed(),
            )
        validate_catalog(path)  # no raise


def test_validate_catalog_raises_on_tamper():
    """If someone edits an entry on disk, the next entry's prev_hash no
    longer matches and validate_catalog raises at the break point."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "catalog.jsonl"
        catalog_append(
            catalog_path=path, experiment_id="exp_001",
            entry_id="01ULID1", payload=_render_completed(),
        )
        catalog_append(
            catalog_path=path, experiment_id="exp_001",
            entry_id="01ULID2", payload=_render_completed(audience="operator"),
        )

        # Tamper: rewrite the first entry's audience field
        lines = path.read_text().splitlines()
        lines[0] = lines[0].replace('"exec"', '"engineer"')
        path.write_text("\n".join(lines) + "\n")

        with pytest.raises(CatalogChainBreak) as excinfo:
            validate_catalog(path)
        assert excinfo.value.index == 1


def test_validate_empty_catalog_passes():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "catalog.jsonl"
        # Don't create the file at all
        validate_catalog(path)


# ─────────────────────────────────────────────────────────────────────────────
# Event payload variety — discriminator works
# ─────────────────────────────────────────────────────────────────────────────


def test_all_four_event_types_can_be_appended():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "catalog.jsonl"
        catalog_append(
            catalog_path=path, experiment_id="exp_001",
            entry_id="01_1", payload=_render_completed(),
        )
        catalog_append(
            catalog_path=path, experiment_id="exp_001",
            entry_id="01_2",
            payload=RenderSupersededEvent(
                superseded_path="readouts/verdict/2026-06-04/exec.html",
                new_path="readouts/verdict/2026-06-05/exec.html",
                reason="brief edited",
            ),
        )
        catalog_append(
            catalog_path=path, experiment_id="exp_001",
            entry_id="01_3",
            payload=RenderBriefDriftFlaggedEvent(
                render_path="readouts/verdict/exec.html",
                brief_path="brief.yaml",
                sealed_design_chain_hash="a" * 64,
                current_design_chain_hash="b" * 64,
            ),
        )
        catalog_append(
            catalog_path=path, experiment_id="exp_001",
            entry_id="01_4",
            payload=PruneCompletedEvent(
                pruned_paths=["readouts/old.html"],
                bytes_freed=1024,
                policy="age>90d",
            ),
        )
        validate_catalog(path)


# ─────────────────────────────────────────────────────────────────────────────
# build_index — worst-status cascade
# ─────────────────────────────────────────────────────────────────────────────


def test_build_index_on_empty_project_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        rows = build_index(Path(tmp))
        assert rows == []


def test_build_index_summarizes_per_experiment_worst_status():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        exp_dir = root / "experiments" / "exp_001"
        catalog = exp_dir / "readouts" / "catalog.jsonl"

        catalog_append(
            catalog_path=catalog, experiment_id="exp_001",
            entry_id="01_1",
            payload=_render_completed(provenance_render_status="VERIFIED"),
        )
        catalog_append(
            catalog_path=catalog, experiment_id="exp_001",
            entry_id="01_2",
            payload=_render_completed(provenance_render_status="DRAFT_UNVERIFIED"),
        )
        # worst should be DRAFT_UNVERIFIED

        rows = build_index(root)
        assert len(rows) == 1
        assert rows[0].experiment_id == "exp_001"
        assert rows[0].n_renders == 2
        assert rows[0].worst_status == "DRAFT_UNVERIFIED"


def test_build_index_unverifiable_dominates():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        exp_dir = root / "experiments" / "exp_002"
        catalog = exp_dir / "readouts" / "catalog.jsonl"
        catalog_append(
            catalog_path=catalog, experiment_id="exp_002",
            entry_id="01_1",
            payload=_render_completed(provenance_render_status="VERIFIED"),
        )
        catalog_append(
            catalog_path=catalog, experiment_id="exp_002",
            entry_id="01_2",
            payload=_render_completed(provenance_render_status="UNVERIFIABLE"),
        )
        catalog_append(
            catalog_path=catalog, experiment_id="exp_002",
            entry_id="01_3",
            payload=_render_completed(provenance_render_status="DRAFT_UNVERIFIED"),
        )

        rows = build_index(root)
        assert rows[0].worst_status == "UNVERIFIABLE"


def test_build_index_across_multiple_experiments():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for exp_id in ("exp_a", "exp_b", "exp_c"):
            catalog = root / "experiments" / exp_id / "readouts" / "catalog.jsonl"
            catalog_append(
                catalog_path=catalog, experiment_id=exp_id,
                entry_id=f"01_{exp_id}",
                payload=_render_completed(),
            )

        rows = build_index(root)
        assert len(rows) == 3
        assert {r.experiment_id for r in rows} == {"exp_a", "exp_b", "exp_c"}
