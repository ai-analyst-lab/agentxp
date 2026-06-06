"""W5.5 — bridge-aware BLINDNESS_MANIFEST closure.

The serialized bundle the bridge writes to disk is what the sub-agent
actually reads. The closure tests at ``tests/orchestrator/test_bundle_assembler.py``
and ``tests/schemas/test_blindness_closure.py`` (W1.9) prove the bundle
schemas don't *declare* forbidden fields; this test proves the bridge's
serialization doesn't *introduce* them through some layer-violating path
(e.g. an enriched assembler that adds metadata, a future debug-dump
helper).

If any forbidden field name appears in the serialized JSON the sub-agent
will read, the test fails — even if the schema-level closure tests pass.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentxp.orchestrator.bridge import open_dispatch
from agentxp.schemas.bundles import BLINDNESS_MANIFEST


def _critic_sources() -> dict:
    return dict(
        artifact={"path": "experiments/exp_test/hypothesis.yaml",
                  "sha256": "0" * 64, "kind": "brief"},
        artifact_payload={"hypothesis": "stub"},
        claimed_scope={"claim": "test", "cites": []},
        cited_inputs=[],
        judging_mode="brief_consistency",
    )


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "agentxp"
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "critic.md").write_text("# Critic\n")
    return root


def test_serialized_critic_bundle_has_no_forbidden_fields(project_root: Path) -> None:
    """Every forbidden field for the critic must NOT appear in the bundle JSON."""
    desc = open_dispatch(
        role="critic", sources=_critic_sources(), project_root=project_root,
    )
    payload = json.loads(desc.bundle_json_path.read_text())
    forbidden = BLINDNESS_MANIFEST["critic"]
    # Walk the payload recursively and assert no forbidden key appears.
    keys_seen: set[str] = set()

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                keys_seen.add(k)
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(payload)
    violations = set(forbidden) & keys_seen
    assert not violations, (
        f"Serialized critic bundle exposes forbidden field(s): {violations}. "
        f"Bridge serialization violates R5/R6 — check open_dispatch's "
        f"bundle.bundle.model_dump_json() chain."
    )
