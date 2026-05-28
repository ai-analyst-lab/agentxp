"""Track G — security sweep: chmod 600 on every sensitive file, PII redaction,
and concurrent writer serialisation.

Per §1.7.3 every file OpenXP writes that may carry user data must be chmod
600 at creation. Per §10.9 the project- and state-level locks must
serialise concurrent writers from independent processes. Per §1.7.1 the
PII redactor must catch the common credential patterns before they cross
the audit-log boundary.

Source spec: OPENXP_V01_PLAN.md §1.7.1, §1.7.3, §10.9, §10.5.6.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from openxp.audit.redactor import redact, redact_message
from openxp.audit.storage import (
    _atomic_write_bytes,
    append_conversation_turn,
    append_event,
)
from openxp.orchestrator.bundle import BundleStore
from openxp.orchestrator.store import StateStore
from openxp.schemas.state import Stage, StateYaml


# ──────────────────────────────────────────────────────────────────────────
# chmod 600 sweep — one test per sensitive file shape
# ──────────────────────────────────────────────────────────────────────────


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_chmod_600_on_state_yaml(fake_exp_dir: Path) -> None:
    """StateStore.write lands state.yaml at chmod 600."""
    store = StateStore(fake_exp_dir / "state.yaml")
    store.write(
        StateYaml(
            experiment_id=fake_exp_dir.name,
            current_stage=Stage.DATA_LOADED,
        )
    )
    assert store.path.exists()
    assert _mode(store.path) == 0o600, (
        f"state.yaml must be chmod 600; got {oct(_mode(store.path))}"
    )


def test_chmod_600_on_log_jsonl(fake_exp_dir: Path) -> None:
    """append_event creates log.jsonl chmod 600."""
    append_event(
        fake_exp_dir,
        {
            "event_name": "stage.entered",
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": "data_loaded",
        },
    )
    log = fake_exp_dir / "log.jsonl"
    assert log.exists()
    assert _mode(log) == 0o600


def test_chmod_600_on_conversation_jsonl(fake_exp_dir: Path) -> None:
    """append_conversation_turn creates conversation.jsonl chmod 600."""
    append_conversation_turn(fake_exp_dir, {"role": "user", "content": "hi"})
    conv = fake_exp_dir / "conversation.jsonl"
    assert conv.exists()
    assert _mode(conv) == 0o600


def test_chmod_600_on_bundle_ctx_yaml(
    fake_project_root: Path, fake_exp_dir: Path
) -> None:
    """BundleStore.assemble lands bundles/{agent}.ctx.yaml at chmod 600."""
    bundles_dir = fake_exp_dir / "bundles"
    store = BundleStore(bundles_dir, fake_project_root)
    store.assemble(
        agent_name="profiler",
        ctx_inputs={"smoke": True},
        depends_on_project_yamls=None,
    )
    ctx_path = bundles_dir / "profiler.ctx.yaml"
    assert ctx_path.exists()
    assert _mode(ctx_path) == 0o600


def test_chmod_600_on_atomic_write_bytes(tmp_path: Path) -> None:
    """The shared ``_atomic_write_bytes`` helper enforces 0o600 by default."""
    target = tmp_path / "secret.yaml"
    _atomic_write_bytes(target, b"payload: ok\n")
    assert _mode(target) == 0o600


# ──────────────────────────────────────────────────────────────────────────
# PII redactor — catches AWS keys, passwords, AKIA pattern, kv pairs
# ──────────────────────────────────────────────────────────────────────────


def test_pii_redactor_scrubs_aws_access_key() -> None:
    """AKIA + 16 base32 chars must be replaced with [REDACTED_AWS_ACCESS_KEY]."""
    text = "Error: missing creds; tried AKIAIOSFODNN7EXAMPLE on profile prod."
    out = redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED_AWS_ACCESS_KEY]" in out


def test_pii_redactor_scrubs_password_kv() -> None:
    """``password=secret123`` must be reduced to ``password=[REDACTED]``."""
    text = "conn-string: account=acme;password=hunter2;user=admin"
    out = redact(text)
    assert "hunter2" not in out
    assert "[REDACTED]" in out


def test_pii_redactor_scrubs_bearer_token() -> None:
    """``Bearer <jwt-ish>`` must be reduced to ``Bearer [REDACTED_TOKEN]``."""
    text = "Authorization: Bearer abcdef0123456789ABCDEF0123456789"
    out = redact(text)
    assert "abcdef0123456789ABCDEF0123456789" not in out
    assert "[REDACTED_TOKEN]" in out


def test_pii_redactor_scrubs_email() -> None:
    """Email addresses are replaced with a stable placeholder."""
    text = "Owner: shane@aieval.ai"
    out = redact(text)
    assert "shane@aieval.ai" not in out
    assert "[REDACTED_EMAIL]" in out


def test_pii_redactor_is_idempotent() -> None:
    """redact(redact(x)) == redact(x) — placeholders never re-match."""
    text = "AKIAIOSFODNN7EXAMPLE password=hunter2 user@example.com"
    once = redact(text)
    twice = redact(once)
    assert once == twice


def test_redact_message_wraps_exception_str() -> None:
    """redact_message catches PII embedded in an exception's str."""
    err = RuntimeError("dispatch failed: AKIAIOSFODNN7EXAMPLE rejected")
    out = redact_message(err)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED_AWS_ACCESS_KEY]" in out


# ──────────────────────────────────────────────────────────────────────────
# Concurrent writers — state.yaml + log.jsonl serialise across processes
# ──────────────────────────────────────────────────────────────────────────
#
# Worker functions MUST be module-level for picklability under "spawn" on
# macOS (the default start method in CPython 3.8+).


def _state_writer_worker(
    project_root: str, exp_id: str, stage_value: str, hold_seconds: float
) -> int:
    """Acquire .state.lock via OrchestratorStore._file_lock and write state.yaml."""
    from openxp.orchestrator.store import OrchestratorStore
    from openxp.schemas.state import Stage, StateYaml

    store = OrchestratorStore(Path(project_root), exp_id)
    with store._file_lock(timeout_s=15.0):
        store.state.write(
            StateYaml(
                experiment_id=exp_id,
                current_stage=Stage(stage_value),
            )
        )
        time.sleep(hold_seconds)
    return 0


def _log_writer_worker(exp_dir: str, n: int) -> int:
    """Append ``n`` log.jsonl events from a child process."""
    from openxp.audit.storage import append_event

    for i in range(n):
        append_event(
            Path(exp_dir),
            {
                "event_name": "stage.entered",
                "ts": datetime.now(timezone.utc).isoformat(),
                "stage": "data_loaded",
                "pid": os.getpid(),
                "i": i,
            },
        )
    return 0


def test_concurrent_state_writers_serialize(
    fake_project_root: Path, fake_exp_dir: Path
) -> None:
    """Two processes write state.yaml; the second must wait for the first.

    The test asserts (a) both processes exit cleanly, (b) the final
    state.yaml is a single complete document, not a half-write, and (c)
    state.yaml ends up chmod 600.
    """
    ctx = multiprocessing.get_context("spawn")
    p1 = ctx.Process(
        target=_state_writer_worker,
        args=(str(fake_project_root), fake_exp_dir.name, "data_loaded", 0.5),
    )
    p2 = ctx.Process(
        target=_state_writer_worker,
        args=(str(fake_project_root), fake_exp_dir.name, "brief_drafted", 0.0),
    )
    p1.start()
    # Give p1 a head start so it grabs the lock first.
    time.sleep(0.1)
    p2.start()
    p1.join(timeout=30)
    p2.join(timeout=30)
    assert p1.exitcode == 0 and p2.exitcode == 0, (
        f"workers must exit 0; got {p1.exitcode!r} / {p2.exitcode!r}"
    )
    state_yaml = fake_exp_dir / "state.yaml"
    assert state_yaml.exists()
    # File is a complete YAML document (one of the two states won).
    import yaml as _yaml

    data = _yaml.safe_load(state_yaml.read_text())
    assert isinstance(data, dict)
    assert data["current_stage"] in {"data_loaded", "brief_drafted"}
    assert _mode(state_yaml) == 0o600


def test_concurrent_log_appenders_produce_clean_lines(
    fake_exp_dir: Path,
) -> None:
    """Two processes append to log.jsonl concurrently; no torn lines."""
    ctx = multiprocessing.get_context("spawn")
    p1 = ctx.Process(target=_log_writer_worker, args=(str(fake_exp_dir), 5))
    p2 = ctx.Process(target=_log_writer_worker, args=(str(fake_exp_dir), 5))
    p1.start()
    p2.start()
    p1.join(timeout=30)
    p2.join(timeout=30)
    assert p1.exitcode == 0 and p2.exitcode == 0
    log = fake_exp_dir / "log.jsonl"
    assert log.exists()
    # Every line parses as JSON — no interleaving / partial writes.
    for ln in log.read_text().splitlines():
        if not ln.strip():
            continue
        json.loads(ln)
    # Sweep didn't drift chmod.
    assert _mode(log) == 0o600
