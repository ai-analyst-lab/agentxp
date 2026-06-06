"""W5.2 — Claude Code Agent bridge tests.

Two-phase dispatch:
  open_dispatch       — Python builds the bundle, serializes it, returns descriptor
  (harness Agent call — out of scope for Python tests)
  complete_dispatch   — validates response against output schema, retries on
                        ValidationError per CLAUDE.md §10
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agentxp.orchestrator.bridge import (
    DispatchDescriptor,
    complete_dispatch,
    open_dispatch,
)
from agentxp.orchestrator.errors import (
    BundleAssemblyError,
    MalformedSpecialistOutput,
)


# A minimal valid set of sources for the critic, which is the role whose
# output schema is wired (_JudgmentPlaceholder).
def _critic_sources() -> dict:
    return dict(
        artifact={"path": "experiments/exp_test/hypothesis.yaml",
                  "sha256": "0" * 64, "kind": "brief"},
        artifact_payload={"hypothesis": "stub"},
        claimed_scope={"claim": "test claim", "cites": []},
        cited_inputs=[],
        judging_mode="brief_consistency",
    )


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """A minimal project tree with the critic agent prompt."""
    root = tmp_path / "agentxp"
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "critic.md").write_text("# Critic\n")
    return root


def test_open_dispatch_returns_descriptor(project_root: Path) -> None:
    desc = open_dispatch(
        role="critic",
        sources=_critic_sources(),
        project_root=project_root,
    )
    assert isinstance(desc, DispatchDescriptor)
    assert desc.role == "critic"
    assert desc.system_prompt_path.exists()
    assert desc.bundle_json_path.exists()
    assert len(desc.bundle_sha256) == 64
    # Critic has a canonical output schema.
    assert desc.output_schema_ref is not None
    assert "_JudgmentPlaceholder" in desc.output_schema_ref


def test_bundle_json_round_trips_through_disk(project_root: Path) -> None:
    desc = open_dispatch(
        role="critic", sources=_critic_sources(), project_root=project_root,
    )
    payload = desc.bundle_json_path.read_text()
    # The sha pins the version the descriptor was assembled against.
    assert hashlib.sha256(payload.encode()).hexdigest() == desc.bundle_sha256
    parsed = json.loads(payload)
    assert parsed["judging_mode"] == "brief_consistency"


def test_complete_dispatch_with_valid_response(project_root: Path) -> None:
    desc = open_dispatch(
        role="critic", sources=_critic_sources(), project_root=project_root,
    )
    # The critic's _JudgmentPlaceholder accepts {passed, reasons[], severity}.
    raw = {"passed": True, "reasons": [], "severity": "warn"}
    validated = complete_dispatch(
        dispatch_id=desc.dispatch_id,
        raw_response=raw,
        project_root=project_root,
    )
    assert validated["passed"] is True
    assert validated["severity"] == "warn"


def test_complete_dispatch_raises_on_malformed_output(project_root: Path) -> None:
    desc = open_dispatch(
        role="critic", sources=_critic_sources(), project_root=project_root,
    )
    raw = {"passed": "not a bool", "severity": "block"}  # type error
    with pytest.raises(MalformedSpecialistOutput) as exc_info:
        complete_dispatch(
            dispatch_id=desc.dispatch_id,
            raw_response=raw,
            project_root=project_root,
        )
    assert exc_info.value.first_errors, "first_errors must carry the validation errors"


def test_complete_dispatch_consumes_descriptor(project_root: Path) -> None:
    """A descriptor is one-shot — using its id twice raises."""
    desc = open_dispatch(
        role="critic", sources=_critic_sources(), project_root=project_root,
    )
    complete_dispatch(
        dispatch_id=desc.dispatch_id,
        raw_response={"passed": True, "reasons": [], "severity": "warn"},
        project_root=project_root,
    )
    with pytest.raises(KeyError):
        complete_dispatch(
            dispatch_id=desc.dispatch_id,
            raw_response={"passed": True, "reasons": [], "severity": "warn"},
            project_root=project_root,
        )


def test_open_dispatch_raises_bundle_assembly_error_on_bad_sources(
    project_root: Path,
) -> None:
    with pytest.raises(BundleAssemblyError):
        open_dispatch(
            role="critic",
            sources={"this_is_not_a_critic_field": "nope"},
            project_root=project_root,
        )


def test_unknown_role_raises(project_root: Path) -> None:
    with pytest.raises((FileNotFoundError, BundleAssemblyError)):
        open_dispatch(
            role="not_a_real_role",
            sources={},
            project_root=project_root,
        )
