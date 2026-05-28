"""Tests for openxp.orchestrator.dispatch — W_pre3.6 single-agent dispatcher.

Covers:
  - §1.8.8 canonical agent-name gating
  - System-prompt loading from default path
  - `agent.dispatched` + `agent.completed` audit events
  - `conversation.jsonl` append on success
  - RetryPolicy: 5xx retries (§10.5.1), auth-expired no-retry, malformed-YAML
    retry (§10.5.4), terminal `failed_after_retries`
  - parent_action_id chaining
  - Backoff sleep schedule

Source spec: OPENXP_V01_PLAN.md §10.5.1, §1.8.5, §1.8.8, §9.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from openxp.orchestrator import dispatch as dispatch_mod
from openxp.orchestrator.dispatch import (
    CANONICAL_AGENT_NAMES,
    AuthExpiredError,
    DispatchRequest,
    DispatchResult,
    FailedAfterRetriesError,
    RetryPolicy,
    TransientServerError,
    dispatch_agent,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers + fixtures
# ──────────────────────────────────────────────────────────────────────────


class _Out(BaseModel):
    """Minimal pydantic schema for tests."""

    answer: str
    confidence: float = 0.5


def _good_response() -> str:
    return json.dumps({"answer": "ok", "confidence": 0.9})


def _read_log(experiment_dir: Path) -> list[dict[str, Any]]:
    log_path = experiment_dir / "log.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


def _read_conversation(experiment_dir: Path) -> list[dict[str, Any]]:
    conv_path = experiment_dir / "conversation.jsonl"
    if not conv_path.exists():
        return []
    return [json.loads(line) for line in conv_path.read_text().splitlines() if line.strip()]


@pytest.fixture
def stub_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a small system prompt at the default lookup path and patch the resolver."""
    prompt_path = tmp_path / "agents" / "profiler.system.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("# stub profiler system prompt\n")
    # Redirect default-path resolution into tmp_path so we don't depend on
    # the real openxp/agents/ on the filesystem.
    monkeypatch.setattr(
        dispatch_mod,
        "_default_system_prompt_path",
        lambda project_root, agent_name: tmp_path / "agents" / f"{agent_name}.system.md",
    )
    return prompt_path


def _make_req(
    tmp_path: Path,
    *,
    agent_name: str = "profiler",
    parent_action_id: str | None = None,
    retry_policy: RetryPolicy | None = None,
) -> DispatchRequest:
    return DispatchRequest(
        agent_name=agent_name,
        experiment_id="exp_test_001",
        project_root=tmp_path,
        ctx_bundle={"k": "v"},
        out_schema=_Out,
        retry_policy=retry_policy or RetryPolicy(backoff_seconds=(0.0, 0.0, 0.0)),
        parent_action_id=parent_action_id,
    )


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


def test_dispatch_rejects_unknown_agent_name(tmp_path: Path) -> None:
    """agent_name must be in §1.8.8 canonical set; anything else is a ValueError."""
    req = _make_req(tmp_path, agent_name="frobnicator")
    with pytest.raises(ValueError, match=r"§1\.8\.8 canonical set"):
        dispatch_agent(req)


def test_dispatch_accepts_all_canonical_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every name in CANONICAL_AGENT_NAMES is accepted by dispatch_agent."""
    # Stub every canonical prompt file.
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    for name in CANONICAL_AGENT_NAMES:
        (agents_dir / f"{name}.system.md").write_text(f"# {name}\n")
    monkeypatch.setattr(
        dispatch_mod,
        "_default_system_prompt_path",
        lambda project_root, agent_name: agents_dir / f"{agent_name}.system.md",
    )
    monkeypatch.setattr(dispatch_mod, "_invoke_llm", lambda sp, b: _good_response())

    for name in CANONICAL_AGENT_NAMES:
        req = _make_req(tmp_path, agent_name=name)
        result = dispatch_agent(req)
        assert isinstance(result, DispatchResult)
        assert result.attempts == 1


def test_dispatch_loads_system_prompt_from_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """_invoke_llm receives the exact text of the resolved system prompt file."""
    seen: dict[str, Any] = {}

    def fake_invoke(system_prompt: str, ctx_bundle: dict[str, Any]) -> str:
        seen["system_prompt"] = system_prompt
        seen["ctx_bundle"] = ctx_bundle
        return _good_response()

    monkeypatch.setattr(dispatch_mod, "_invoke_llm", fake_invoke)
    dispatch_agent(_make_req(tmp_path))

    assert seen["system_prompt"] == stub_prompt.read_text()
    assert seen["ctx_bundle"] == {"k": "v"}


def test_dispatch_appends_agent_dispatched_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """log.jsonl gets an `agent.dispatched` row as the chain root."""
    monkeypatch.setattr(dispatch_mod, "_invoke_llm", lambda sp, b: _good_response())
    dispatch_agent(_make_req(tmp_path))

    events = _read_log(tmp_path)
    dispatched = [e for e in events if e["event_name"] == "agent.dispatched"]
    assert len(dispatched) == 1
    assert dispatched[0]["agent_name"] == "profiler"
    assert dispatched[0]["experiment_id"] == "exp_test_001"
    assert dispatched[0]["actor_kind"] == "orchestrator"


def test_dispatch_appends_agent_completed_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """Happy path: one agent.completed with classification=success."""
    monkeypatch.setattr(dispatch_mod, "_invoke_llm", lambda sp, b: _good_response())
    dispatch_agent(_make_req(tmp_path))

    events = _read_log(tmp_path)
    completed = [e for e in events if e["event_name"] == "agent.completed"]
    assert len(completed) == 1
    assert completed[0]["classification"] == "success"
    assert completed[0]["agent_name"] == "profiler"
    # First-attempt success carries no `subtype` (only retry-resolved successes do).
    assert completed[0]["metadata"].get("subtype") is None


def test_dispatch_appends_conversation_turn_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """conversation.jsonl gets a turn with system + user + assistant on success."""
    raw = _good_response()
    monkeypatch.setattr(dispatch_mod, "_invoke_llm", lambda sp, b: raw)
    dispatch_agent(_make_req(tmp_path))

    turns = _read_conversation(tmp_path)
    assert len(turns) == 1
    t = turns[0]
    assert t["agent_name"] == "profiler"
    assert t["system"] == stub_prompt.read_text()
    assert json.loads(t["user"]) == {"k": "v"}
    assert t["assistant"] == raw


def test_dispatch_retries_on_transient_5xx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """503 twice → success → attempts=3; two retry completions + one success completion."""
    calls = {"n": 0}
    responses = [
        ("err", 503),
        ("err", 503),
        ("ok", _good_response()),
    ]

    def fake_invoke(sp: str, b: dict[str, Any]) -> str:
        idx = calls["n"]
        calls["n"] += 1
        kind, payload = responses[idx]
        if kind == "err":
            raise TransientServerError(payload)
        return payload

    monkeypatch.setattr(dispatch_mod, "_invoke_llm", fake_invoke)
    # Silence the backoff sleeps.
    monkeypatch.setattr(dispatch_mod.time, "sleep", lambda *_: None)

    result = dispatch_agent(_make_req(tmp_path))
    assert result.attempts == 3

    events = _read_log(tmp_path)
    completed = [e for e in events if e["event_name"] == "agent.completed"]
    assert len(completed) == 3
    # First two are retries with transient_5xx subtype, third is success with retry subtype.
    assert completed[0]["classification"] == "retry"
    assert completed[0]["metadata"]["subtype"] == "transient_5xx"
    assert completed[1]["classification"] == "retry"
    assert completed[1]["metadata"]["subtype"] == "transient_5xx"
    assert completed[2]["classification"] == "success"
    assert completed[2]["metadata"]["subtype"] == "retry"


def test_dispatch_raises_failed_after_retries_when_budget_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """All max_attempts raise 5xx → FailedAfterRetriesError + terminal completion."""

    def always_5xx(sp: str, b: dict[str, Any]) -> str:
        raise TransientServerError(502)

    monkeypatch.setattr(dispatch_mod, "_invoke_llm", always_5xx)
    monkeypatch.setattr(dispatch_mod.time, "sleep", lambda *_: None)

    with pytest.raises(FailedAfterRetriesError):
        dispatch_agent(_make_req(tmp_path))

    events = _read_log(tmp_path)
    completed = [e for e in events if e["event_name"] == "agent.completed"]
    # 3 retries (one per attempt) + 1 terminal failure summary = 4
    assert len(completed) == 4
    assert completed[-1]["classification"] == "failed"
    assert completed[-1]["metadata"]["subtype"] == "failed_after_retries"


def test_dispatch_raises_auth_expired_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """AuthExpiredError surfaces immediately; no retries; subtype=auth_expired."""

    def auth_dead(sp: str, b: dict[str, Any]) -> str:
        raise AuthExpiredError("token expired")

    monkeypatch.setattr(dispatch_mod, "_invoke_llm", auth_dead)
    sleep_calls: list[float] = []
    monkeypatch.setattr(dispatch_mod.time, "sleep", lambda s: sleep_calls.append(s))

    with pytest.raises(AuthExpiredError):
        dispatch_agent(_make_req(tmp_path))

    events = _read_log(tmp_path)
    completed = [e for e in events if e["event_name"] == "agent.completed"]
    assert len(completed) == 1
    assert completed[0]["classification"] == "failed"
    assert completed[0]["metadata"]["subtype"] == "auth_expired"
    assert completed[0]["metadata"]["attempt"] == 1
    # No backoff sleeps on auth-expired path.
    assert sleep_calls == []


def test_dispatch_validates_out_against_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """Malformed responses 3x → FailedAfterRetriesError; eventual valid → success."""
    # 3 malformed in a row.
    monkeypatch.setattr(dispatch_mod, "_invoke_llm", lambda sp, b: "not even json {{{")
    monkeypatch.setattr(dispatch_mod.time, "sleep", lambda *_: None)
    with pytest.raises(FailedAfterRetriesError):
        dispatch_agent(_make_req(tmp_path))

    # Eventual valid after 2 malformed.
    calls = {"n": 0}

    def flaky(sp: str, b: dict[str, Any]) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            return "garbage }}}}"
        return _good_response()

    # Fresh tmp_path subdir to isolate the log.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    monkeypatch.setattr(dispatch_mod, "_invoke_llm", flaky)
    req = DispatchRequest(
        agent_name="profiler",
        experiment_id="exp_test_001",
        project_root=fresh,
        ctx_bundle={"k": "v"},
        out_schema=_Out,
        retry_policy=RetryPolicy(backoff_seconds=(0.0, 0.0, 0.0)),
    )
    result = dispatch_agent(req)
    assert result.attempts == 3
    assert result.out.answer == "ok"


def test_dispatch_chains_audit_via_parent_action_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """parent_action_id propagates to dispatched; completed events point to dispatched.action_id."""
    monkeypatch.setattr(dispatch_mod, "_invoke_llm", lambda sp, b: _good_response())

    req = _make_req(tmp_path, parent_action_id="PARENT_ABC")
    result = dispatch_agent(req)

    events = _read_log(tmp_path)
    dispatched = next(e for e in events if e["event_name"] == "agent.dispatched")
    completed = [e for e in events if e["event_name"] == "agent.completed"]

    assert dispatched["parent_action_id"] == "PARENT_ABC"
    assert dispatched["action_id"] == result.action_id
    for c in completed:
        assert c["parent_action_id"] == dispatched["action_id"]


def test_backoff_sleeps_between_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_prompt: Path
) -> None:
    """time.sleep is called with policy.backoff_seconds[attempt-1] between retries."""
    calls = {"n": 0}

    def two_then_ok(sp: str, b: dict[str, Any]) -> str:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise TransientServerError(503)
        return _good_response()

    sleep_calls: list[float] = []
    monkeypatch.setattr(dispatch_mod, "_invoke_llm", two_then_ok)
    monkeypatch.setattr(dispatch_mod.time, "sleep", lambda s: sleep_calls.append(s))

    policy = RetryPolicy(backoff_seconds=(1.0, 2.5, 6.0))
    req = _make_req(tmp_path, retry_policy=policy)
    result = dispatch_agent(req)

    assert result.attempts == 3
    # Backoff fires after attempts 1 and 2 (not after the successful 3rd).
    assert sleep_calls == [1.0, 2.5]
