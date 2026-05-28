"""validate_chain — internal function called at every ``_commit_stage`` to
enforce audit-chain integrity (the 5 invariants of §10.7).

W_pre1.6 shipped the signature + stub. W_pre1.9 (this file) fills in the body:
all five invariants, the two-pass walk (log.jsonl pass + on-disk artifacts pass),
and the §10.7.3 two-cap perf budget (soft warning at ``perf_budget_ms``, hard
``PerfBudgetExceeded`` at ``2 × perf_budget_ms``).

Per §10.7: this is an internal function in v0.1 (NOT a user-configurable hook —
external hooks defer to v0.2). Called from ``_commit_stage`` after on-disk
artifacts are written and before ``stage.committed`` fires. Returns a
``ChainValidation``; never raises on a normal integrity violation. Raises
``PerfBudgetExceeded`` only when the hard 2× perf ceiling is breached.

Invariants (per §10.7.2):

  1. parent_action chain integrity — every non-root event in log.jsonl
     references a previously-seen action_id; no duplicates; cycle-free.
  2. conversation_ref integrity — every bundles/{agent}.ctx.yaml with a
     conversation_ref block points at a turn_id that exists in
     conversation.jsonl.
  3. artifact SHA256 match — every query_id referenced from
     bundles/*.out.yaml resolves to queries/{ulid}.yaml on disk, and every
     decisions/*.yaml provenance.bundle_hash matches the on-disk bundle.
  4. no stage.committed while a gate is OPEN — for each stage, the gate
     state machine must be CLOSED (or NEVER_OPENED) at commit time.
  5. no gate.resolved/blocked without a preceding gate.opened — every
     terminal gate event traces back to a matching opener for the same
     (stage, kind).

Disk layout (relative to ``experiments/{experiment_id}/``):

  - ``log.jsonl``           — append-only audit log (Invariants 1, 4, 5)
  - ``conversation.jsonl``  — user/agent dialog turns (Invariant 2)
  - ``bundles/*.ctx.yaml``  — agent input bundles (Invariant 2)
  - ``bundles/*.out.yaml``  — agent output bundles (Invariant 3)
  - ``queries/*.yaml``      — SQL query artifacts (Invariant 3)
  - ``decisions/*.yaml``    — recorded decisions with provenance (Invariant 3)
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

import yaml

from agentxp.schemas.report import ChainValidation, Violation


# ──────────────────────────────────────────────────────────────────────────
# Module-level config — override via the private ``_root`` keyword in
# ``validate_chain`` for tests. The default points at the v0.1 disk layout
# (``./experiments/{experiment_id}/``).
# ──────────────────────────────────────────────────────────────────────────

_DEFAULT_EXPERIMENTS_ROOT = Path("experiments")


# ──────────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────────


class PerfBudgetExceeded(Exception):
    """Raised by ``validate_chain`` when runtime exceeds ``2 × perf_budget_ms``.

    Default hard cap: 400 ms (§10.7.3). The orchestrator catches this in
    ``_commit_stage``, rolls back the stage commit, and emits
    ``gate.blocked(reason="chain_validation_failed", metadata.subtype="chain_validation_perf")``.
    """


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────


def validate_chain(
    experiment_id: str,
    *,
    from_event: int = 0,
    to_event: int | None = None,
    perf_budget_ms: int = 200,
    _root: Path | None = None,
) -> ChainValidation:
    """Walk the on-disk audit trail and enforce the 5 invariants of §10.7.2.

    Args:
        experiment_id: the experiment whose audit chain to validate.
        from_event: inclusive log.jsonl row index to start from (default 0).
            Used by ``agentxp audit --diff`` to validate a slice.
        to_event: exclusive row index to stop at (default end-of-log).
        perf_budget_ms: soft cap; ``2 × perf_budget_ms`` is the hard cap.
            Default 200 ms.
        _root: private — override the experiments root directory (tests only).

    Returns:
        ``ChainValidation`` with ``ok``, ``invariants_checked=[1, 2, 3, 4, 5]``,
        ``violations``, ``ms`` (total runtime), ``perf_warning`` (True when
        ms > soft cap).

    Raises:
        PerfBudgetExceeded: when ``ms > 2 × perf_budget_ms`` (the hard cap).
    """
    root = _root if _root is not None else _DEFAULT_EXPERIMENTS_ROOT
    exp_dir = root / experiment_id

    start = time.perf_counter()
    violations: list[Violation] = []

    # Pass 1 — log.jsonl walk (covers Invariants 1, 4, 5 in one fused scan).
    log_events = _load_log_events(exp_dir, from_event=from_event, to_event=to_event)
    violations.extend(_check_invariant_1_parent_action_chain(log_events))
    gate_violations_4, gate_violations_5 = _check_gate_pairing(log_events)
    violations.extend(gate_violations_4)
    violations.extend(gate_violations_5)

    # Pass 2 — on-disk artifacts (covers Invariants 2 and 3).
    violations.extend(_check_invariant_2_conversation_refs(exp_dir))
    violations.extend(_check_invariant_3_artifact_hashes(exp_dir))

    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # §10.7.3 — hard cap check first; raising preempts the normal return.
    if elapsed_ms > 2 * perf_budget_ms:
        raise PerfBudgetExceeded(
            f"validate_chain took {elapsed_ms:.1f}ms, exceeding hard cap "
            f"{2 * perf_budget_ms}ms (2 × perf_budget_ms={perf_budget_ms})"
        )

    return ChainValidation(
        ok=len(violations) == 0,
        invariants_checked=[1, 2, 3, 4, 5],
        violations=violations,
        ms=elapsed_ms,
        perf_warning=elapsed_ms > perf_budget_ms,
    )


# ──────────────────────────────────────────────────────────────────────────
# Pass 1 helpers — log.jsonl ingestion + Invariants 1, 4, 5
# ──────────────────────────────────────────────────────────────────────────


def _load_log_events(
    exp_dir: Path,
    *,
    from_event: int,
    to_event: int | None,
) -> list[dict]:
    """Read log.jsonl (if present) and slice to [from_event, to_event).

    Returns ``[]`` when log.jsonl is missing — that's vacuously consistent
    (an experiment that has not yet been written cannot violate the chain).
    Malformed JSON rows are skipped silently here; that's a separate failure
    mode (``gate.blocked(reason="malformed_yaml")``, §10.5.4) and not the
    job of ``validate_chain``.
    """
    log_path = exp_dir / "log.jsonl"
    if not log_path.exists():
        return []

    events: list[dict] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # Malformed row — not validate_chain's job to detect.
                continue

    end = to_event if to_event is not None else len(events)
    return events[from_event:end]


def _check_invariant_1_parent_action_chain(events: list[dict]) -> list[Violation]:
    """Invariant 1 — parent_action chain integrity (§10.7.2).

    One pass over events. For each event:
      - assert action_id has not been seen before (duplicate-id check)
      - if parent_action_id is None: must be the FIRST event we see
      - else: parent_action_id must already be in the seen set

    Algorithm: O(L). Cycle detection falls out of the seen-set check (a
    forward reference would fail the existence test).
    """
    violations: list[Violation] = []
    seen: set[str] = set()
    saw_root = False

    for event in events:
        action_id = event.get("action_id")
        parent_id = event.get("parent_action_id")

        if action_id is None:
            # No action_id on the row — can't reason about chain integrity.
            continue

        if action_id in seen:
            violations.append(
                Violation(
                    invariant_id=1,
                    description=(
                        f"duplicate action_id={action_id} in log.jsonl"
                    ),
                    offending_action_id=action_id,
                )
            )
            continue

        if parent_id is None:
            # Root event — only valid as the very first action in the chain.
            if saw_root:
                violations.append(
                    Violation(
                        invariant_id=1,
                        description=(
                            f"non-root event has parent_action_id=null "
                            f"(action_id={action_id})"
                        ),
                        offending_action_id=action_id,
                    )
                )
            saw_root = True
        else:
            if parent_id not in seen:
                violations.append(
                    Violation(
                        invariant_id=1,
                        description=(
                            f"parent_action_id={parent_id} not found before "
                            f"action_id={action_id}"
                        ),
                        offending_action_id=action_id,
                    )
                )

        seen.add(action_id)

    return violations


def _check_gate_pairing(
    events: list[dict],
) -> tuple[list[Violation], list[Violation]]:
    """Invariants 4 + 5 — fused gate-pairing scan (§10.7.2).

    Invariant 4: ``stage.committed(stage=S)`` MUST NOT fire while
    ``(S, *)`` has any OPEN gate.

    Invariant 5: every ``gate.resolved`` / ``gate.blocked`` event must
    trace back to an earlier ``gate.opened`` for the same ``(stage, kind)``.

    Algorithm: single pass, dict ``stage -> set[kind]`` tracks currently-open
    gates per stage. On ``stage.entered(stage=S)`` we reset ``open_kinds[S]``
    (per §10.6 resume semantics).

    Returns:
        (invariant_4_violations, invariant_5_violations)
    """
    v4: list[Violation] = []
    v5: list[Violation] = []
    open_gates: dict[str, set[str]] = {}

    for event in events:
        name = event.get("event_name")
        stage = event.get("stage")
        kind = event.get("kind")
        action_id = event.get("action_id")

        if name == "stage.entered" and stage is not None:
            # Re-entry per §10.6 resets that stage's gate-state machine.
            open_gates[stage] = set()

        elif name == "gate.opened" and stage is not None and kind is not None:
            open_gates.setdefault(stage, set()).add(kind)

        elif name in ("gate.resolved", "gate.blocked"):
            matched = False
            if stage is not None and kind is not None:
                kinds = open_gates.get(stage, set())
                if kind in kinds:
                    kinds.discard(kind)
                    matched = True
            if not matched:
                terminal = name.split(".", 1)[1]  # "resolved" or "blocked"
                v5.append(
                    Violation(
                        invariant_id=5,
                        description=(
                            f"gate.{terminal}(stage={stage}, kind={kind}, "
                            f"action_id={action_id}) without preceding gate.opened"
                        ),
                        offending_action_id=action_id,
                    )
                )

        elif name == "stage.committed" and stage is not None:
            kinds = open_gates.get(stage, set())
            if kinds:
                # Surface ALL still-open gates so the user sees the full picture.
                for open_kind in sorted(kinds):
                    v4.append(
                        Violation(
                            invariant_id=4,
                            description=(
                                f"stage.committed(stage={stage}, "
                                f"action_id={action_id}) emitted while gate "
                                f"kind={open_kind} is OPEN"
                            ),
                            offending_action_id=action_id,
                        )
                    )

    return v4, v5


# ──────────────────────────────────────────────────────────────────────────
# Pass 2 helpers — on-disk artifacts (Invariants 2, 3)
# ──────────────────────────────────────────────────────────────────────────


def _check_invariant_2_conversation_refs(exp_dir: Path) -> list[Violation]:
    """Invariant 2 — conversation_ref integrity (§10.7.2).

    For every ``bundles/{agent}.ctx.yaml`` carrying a ``conversation_ref``
    block, ``through_turn_id`` must resolve to a turn in ``conversation.jsonl``.
    The reverse direction (orphan turns) is NOT checked.

    Algorithm: O(N + B). One pass over conversation.jsonl to build the
    ``turn_id`` set, then O(B) checks against it.
    """
    violations: list[Violation] = []
    bundles_dir = exp_dir / "bundles"
    conv_path = exp_dir / "conversation.jsonl"

    if not bundles_dir.exists():
        return violations  # vacuously satisfied

    turn_ids: set[str] = set()
    if conv_path.exists():
        with conv_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tid = row.get("turn_id") if isinstance(row, dict) else None
                if isinstance(tid, str):
                    turn_ids.add(tid)

    for bundle_path in sorted(bundles_dir.glob("*.ctx.yaml")):
        try:
            bundle = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            # Malformed bundle is a separate failure mode — not Invariant 2.
            continue
        if not isinstance(bundle, dict):
            continue
        conv_ref = bundle.get("conversation_ref")
        if not isinstance(conv_ref, dict):
            continue
        ref_turn_id = conv_ref.get("through_turn_id")
        if not isinstance(ref_turn_id, str):
            continue
        if ref_turn_id not in turn_ids:
            violations.append(
                Violation(
                    invariant_id=2,
                    description=(
                        f"bundle {bundle_path.name}: conversation_ref."
                        f"through_turn_id={ref_turn_id} not in conversation.jsonl"
                    ),
                    offending_path=str(bundle_path),
                )
            )

    return violations


def _check_invariant_3_artifact_hashes(exp_dir: Path) -> list[Violation]:
    """Invariant 3 — artifact SHA256 match (§10.7.2).

    Two sub-checks:
      (a) every ``query_id`` referenced from a ``bundles/*.out.yaml`` resolves
          to a ``queries/{query_id}.yaml`` on disk.
      (b) every ``decisions/*.yaml`` with a ``provenance.bundle_hash`` field
          has that hash equal to ``sha256(bundle_file_bytes)``.

    Orphan queries (a ``queries/{ulid}.yaml`` not referenced by any bundle)
    are NOT a violation in v0.1 (§10.7.2 "Counts as broken when").
    """
    violations: list[Violation] = []
    bundles_dir = exp_dir / "bundles"
    queries_dir = exp_dir / "queries"
    decisions_dir = exp_dir / "decisions"

    # (a) every referenced query_id has a corresponding queries/{ulid}.yaml.
    if bundles_dir.exists():
        for out_path in sorted(bundles_dir.glob("*.out.yaml")):
            try:
                out_doc = yaml.safe_load(out_path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if not isinstance(out_doc, dict):
                continue
            for q in out_doc.get("queries", []) or []:
                if not isinstance(q, dict):
                    continue
                qid = q.get("query_id")
                if not isinstance(qid, str):
                    continue
                expected = queries_dir / f"{qid}.yaml"
                if not expected.exists():
                    violations.append(
                        Violation(
                            invariant_id=3,
                            description=(
                                f"missing query artifact: queries/{qid}.yaml"
                            ),
                            offending_path=str(expected),
                        )
                    )

    # (b) every decision's recorded bundle_hash matches the on-disk file.
    if decisions_dir.exists() and bundles_dir.exists():
        for dec_path in sorted(decisions_dir.glob("*.yaml")):
            try:
                dec_doc = yaml.safe_load(dec_path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if not isinstance(dec_doc, dict):
                continue
            prov = dec_doc.get("provenance")
            if not isinstance(prov, dict):
                continue
            recorded = prov.get("bundle_hash")
            bundle_ref = prov.get("bundle_path") or prov.get("bundle")
            if not isinstance(recorded, str) or not isinstance(bundle_ref, str):
                continue
            # bundle_ref is "bundles/{agent}.ctx.yaml" relative to exp_dir,
            # or just "{agent}.ctx.yaml".
            candidate = (
                exp_dir / bundle_ref
                if "/" in bundle_ref
                else bundles_dir / bundle_ref
            )
            if not candidate.exists():
                violations.append(
                    Violation(
                        invariant_id=3,
                        description=(
                            f"bundle_hash mismatch for {bundle_ref}: "
                            f"expected={recorded[:8]}, actual=<missing file>"
                        ),
                        offending_path=str(candidate),
                    )
                )
                continue
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if actual != recorded:
                violations.append(
                    Violation(
                        invariant_id=3,
                        description=(
                            f"bundle_hash mismatch for {bundle_ref}: "
                            f"expected={recorded[:8]}, actual={actual[:8]}"
                        ),
                        offending_path=str(candidate),
                    )
                )

    return violations


__all__ = [
    "validate_chain",
    "PerfBudgetExceeded",
    "ChainValidation",
    "Violation",
]
