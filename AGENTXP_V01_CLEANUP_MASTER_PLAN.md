# AgentXP v0.1 Cleanup — Master Plan

**Document date:** 2026-06-04
**Status:** Execution-ready. All Phase 1–2b conflicts resolved through five Round 2 persona plans, two moderator summaries, the REAL_WALK_AUDIT, and Shane's six binding decisions.
**Reading order for executors:** §1 → §2 wave table → §3 (your wave) → §4 dependency graph → §5 files changed → §6 open questions (expected to be empty).

---

## §1 Executive Summary

### 1.1 What we're building

One coherent cleanup that closes four product gaps and 20 audit findings without disturbing Module 0 (the thesis), Module 4 (the integrity spine), or Module 10 (presentation — just shipped). The four gaps:

1. **CSV → warehouse fixture.** The eight sample-data CSVs are clean-deleted and replaced with a single seeded DuckDB warehouse (`sample-data/agentxp_demo.duckdb`) holding eight pre-seeded experiments across the verdict-path teaching cheat-sheet.
2. **`/experiment` → two sub-verbs.** `/experiment design` (Stages 0–4) and `/experiment analyze --brief <path>` (Stages 5–8), bridged by a sealed brief at `briefs/<exp_id>.yaml` carrying a three-part integrity lock.
3. **dispatch_sql wired through the SQL chokepoint.** The 5-layer worker (`agentxp/sql/dispatch.py`) already ships; what is missing is the store-level wrapper, the DuckDB adapter, content-faithful `result_hash`, and parquet result emission.
4. **Inline-mode `dispatch_agent`.** v0.1's primary dispatch path runs inside the slash command (no API key). API mode persists as a Phase 5 path; inline mode emits the same `agent.dispatched` / `agent.completed` pair with `metadata.subtype="inline"`.

The 20 audit findings (B1, B3–B7, B10, G1–G5, S1–S3, S5, S7, I1–I6) fold into the same waves. The whole cleanup ships as **6 waves and one atomic surface-flip PR** (§2).

### 1.2 The thesis being preserved

> **Deterministic Python owns the statistics; an LLM owns the judgment; and the judgment is structurally sealed off from the result.**

Three modules carry this thesis and are non-negotiable:

- **Module 0 — the thesis.** Story unchanged. Three CSV path references update; framing untouched.
- **Module 4 — the integrity spine.** The locked-rule wall, chain invariants, and `_commit_stage` as sole writer all survive. The wall *grows* one invariant (Invariant 6 — paired-events-required-per-bundle) and one teaching beat (`metadata.subtype` absorbs new dispatch semantics so EventName stays closed at 13).
- **Module 10 — the presentation layer.** Body unchanged. Numeric pins on `exp_001` test bundles (`+0.032 (+18.0%)`) are reproduced from synthetic data, independent of the warehouse fixture. Module 3 gains a one-sentence back-reference to Module 10's `RenderStatus` symmetry.

The verdict tree, the chain, `_commit_stage`, the closed-enum walls — all stand.

### 1.3 Shane's 6 binding decisions (constraints the plan respects)

1. **Wave 4 ships as one atomic PR.** The user-facing surface flip. Waves 0–3 land internally behind `SURFACE_V01_ENABLED=False`; Wave 4 flips the flag, deletes CSVs, lands docs, regenerates test bundles, all in one atomic merge.
2. **Warehouse seed reproduces `E_F12345` byte-for-byte.** 314 control conversions, 384 treatment conversions, n=3000/arm, +0.0233 absolute, +22.3% relative, conv_rate_c=10.47%, conv_rate_t=12.80%. trace.md and Module 10 are not touched.
3. **State migration is an explicit `agentxp migrate-state` verb.** No auto-mutation at read time. v3 loaded by v4 code raises a clear error pointing the user at the verb.
4. **Sample-data CSVs clean-deleted** in Wave 4. No DEPRECATED banner. Muscle-memory refusal message ships in place of the CSV. The CSV *adapter* as a product feature persists (taught via a 3-row synthetic CSV in `walkthroughs/data-connectors.md`).
5. **Power-feasibility threshold: strict 1.0×.** Brief-commit refuses when `n_required > available_assignment_surface_per_arm`. No headroom multiplier. No `--force` flag. Allocation-aware: `available_per_arm = available * min(allocation_ratio)`.
6. **`commit-stage` ships as `python3 -m agentxp.recovery commit-stage`.** Not a top-level `agentxp` verb. Not in `/help`. Every emitted event carries `metadata.subtype="recovery_inline"`. Keeps the no-provenance commit door (audit B1) closed.

### 1.4 The atomic-Wave-4 mechanism

A single feature flag at `agentxp/_flags.py`:

```python
# agentxp/_flags.py — Wave 0
import os
SURFACE_V01_ENABLED: bool = os.environ.get("AGENTXP_SURFACE_V01", "0") == "1"
```

Waves 0–3 land all schema changes, dispatch_sql wiring, warehouse fixture, and inline-mode `dispatch_agent` behind the flag. Internal tests set `AGENTXP_SURFACE_V01=1` to exercise the new path. Until Wave 4, a fresh-clone user sees the v0.0 surface unchanged.

Wave 4 — one atomic PR — flips `SURFACE_V01_ENABLED` to default-True (and removes the read-from-env conditional), deletes CSVs, rewrites SKILL.md / STAGES_DESIGN.md / STAGES_ANALYZE.md / CLAUDE.md §1 / QUICKSTART / USER_JOURNEYS / per-module curriculum, lands new walkthroughs, regenerates test bundles, and lands the EXPERIMENTS.md table.

Wave 5 (post-W4 polish, 1-week gap) lands gauntlet rewrites, trace.md re-walk, and SYSTEM_AUDIT.md §11 final entries.

### 1.5 What success looks like

A fresh-clone user, after `pip install agentxp`, runs:

```
$ /experiment analyze --brief briefs/E_F12345.yaml --experiment-id E_F12345
```

…and receives a SHIP verdict with `+22.3%` relative lift, a content-anchored chain, and an audit-replay-clean log.jsonl. **No API key. No CSVs. No `NotImplementedError` on live paths. No `<pending>` literals. No silent test substitution. No null-input passes. No underpowered briefs.**

Or, designing a fresh experiment:

```
$ /experiment design
🆕 Starting design for experiment exp_005.
   Scaffolded directory at experiments/exp_005/ (bundles/, decisions/, ...)
Reading the assignment surface in sample-data/agentxp_demo.duckdb...
   users    47,213 rows ...
No variant column in any table. Good — this is design mode.
ℹ️  Tip: I called this experiment `exp_005`. To rename, say "call it <name>".
What do you want to test?
```

…walks 0→4, seals a brief, refuses an underpowered design with a literal math-rich refusal string, and lands a `briefs/<id>.yaml` whose `design_chain_hash` + `metric_snapshot` + `expected_shape` will be verified at analyze-entry.

---

## §2 Wave Structure

| # | Name | Tasks | Depends on | Ships | Lands as |
|---|------|-------|------------|-------|----------|
| 0 | Schema + hygiene foundations | 17 | — | dark | merge train |
| 1 | SQL chokepoint wiring + result_hash | 6 | W0 | dark | merge train |
| 2 | Warehouse fixture + semantic models + metrics | 8 | W0, W1 | dark | merge train |
| 3 | Inline-mode dispatch + bootstrap + brief integrity | 5 | W0, W1 | dark | merge train |
| 4 | Atomic surface flip + docs + CSV delete | 10 | W0–W3 | **SURFACE FLIP** | one atomic PR |
| 5 | Gauntlet rewrites + trace.md audit | 4 | W4 | docs only | 1-week post-W4 |

**Wave 0 — Schema + hygiene foundations.** Lands every schema change, type alias, closed-enum extension, feature flag, CLI verb scaffold, and orchestrator-store method that downstream waves depend on. Zero user-visible behavior change. Closure tests stay green throughout. Unlocks: every subsequent wave.

**Wave 1 — SQL chokepoint wiring + result_hash content-faithfulness.** Wires the existing `agentxp/sql/dispatch.py` worker through `OrchestratorStore.dispatch_sql()`, ships the DuckDB adapter, fixes the silent `result_hash` content-faithfulness bug, adds parquet emission, and lands the analyzer's `SupportedTestType` registry. Unlocks: warehouse queries from any agent path; Wave 2 fixture generator can validate against the dispatched SQL.

**Wave 2 — Warehouse fixture.** Generates `sample-data/agentxp_demo.duckdb` with eight experiments, six tables, and the E_F12345 seed contract pinned by integration test. Lands `semantic_models/*.yaml`, `metrics/*.yaml` (v2 schema), `fact_sources/*.yaml`, `connections/agentxp_demo.yaml`, `fixture.lock.yaml`, and the `assignments/README.md` convention doc. Regenerates Module 10 test bundles from the new warehouse so `+0.032 (+18.0%)` remains pinned (via `exp_001` synthetic anchor, independent of warehouse). Unlocks: Wave 3 brief-commit power check has real numbers to refuse against; Wave 4 docs have real query results to cite.

**Wave 3 — Inline-mode dispatch + bootstrap_experiment + brief integrity.** Lands `dispatch_agent`'s inline branch (atomic dispatched/completed pair, raw-text persistence, schema validation, no retry), `OrchestratorStore.bootstrap_experiment`, the three-part brief integrity lock, the design-time power-feasibility refusal, and the two-state-lifecycle implementation. Unlocks: Wave 4 sub-verb routing has a working backend.

**Wave 4 — Atomic surface flip + docs + CSV delete (THE atomic PR).** Flips `SURFACE_V01_ENABLED`, deletes the 8 sample-data CSVs, rewrites `.claude/commands/experiment.md` with sub-verbs, rewrites `.claude/skills/experiment/SKILL.md` + STAGES_DESIGN.md + STAGES_ANALYZE.md, rewrites root `CLAUDE.md` §1+§2+§4, rewrites `docs/QUICKSTART.md` + `docs/USER_JOURNEYS.md`, rewrites walkthroughs (your-first-experiment → meta; pre-registration → design; monitoring → analyze; data-connectors → synthetic-CSV swap), and lands per-module curriculum updates (Modules 0–10 per the change matrix). Single atomic merge.

**Wave 5 — Gauntlet rewrites + trace.md audit (polish).** Lands Module 8 gauntlet rewrite (18 → 21 questions), trace.md numeric re-verification against the shipped warehouse, README aha-index + module-map + fixture cheat-sheet updates, and SYSTEM_AUDIT.md §11 final entries (G17 resolved, G6 half-struck, G18 added, G19 added). Ships within 1 week of Wave 4.

---

## §3 Detailed Waves

### §3.0 Wave 0 — Schema + hygiene foundations

**Goal:** Land every schema change, type alias, closed-enum extension, feature flag, and orchestrator-store method that downstream waves depend on, with zero user-visible behavior change.

**Ships dark.** No surface flip; `SURFACE_V01_ENABLED=False` everywhere.

**Parallelism notes:** W0.1 (Sha256Hex) blocks W0.3, W0.7, W0.11–W0.13. W0.2 (feature flag) is standalone. W0.3 (subtype Literal) blocks W0.4 (Invariant 6). W0.5 (StateYaml v4 + migrate-state) blocks W0.7 (LastActionMetadata) and W0.14 (bootstrap). W0.6 (exp_id sweep) is independent — can land any time. Rough sequencing: [W0.1, W0.2, W0.6, W0.8, W0.9, W0.10] in parallel → [W0.3, W0.5, W0.7, W0.11–W0.13] → [W0.4, W0.14, W0.15, W0.16, W0.17].

**Tasks:**

#### Task W0.1 — Sha256Hex type alias + repo-wide hash-field refactor (audit B3)

- **File paths:** `agentxp/schemas/_types.py` (NEW), `agentxp/schemas/data_plan.py`, `agentxp/schemas/semantic_model.py`, `agentxp/schemas/brief.py` (NEW — created in W0.13), `agentxp/schemas/state.py`, `agentxp/audit/events.py`, `agentxp/audit/chain.py`, `tests/schemas/test_sha256_hex_validation.py` (NEW), `tests/schemas/test_hash_field_closure.py` (NEW).
- **What it does:** Introduces a constrained pydantic type:

```python
# agentxp/schemas/_types.py
from typing import Annotated
from pydantic import Field
Sha256Hex = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64)]
```

Refactors every field whose name ends in `_hash` or `_sha256` to use `Sha256Hex`. Specific fields: `DataFingerprint.sha256`, `FactSourceBinding.fingerprint_sha256`, `SemanticModel.fingerprint_sha256`, `Brief.design_chain_hash`, every value in `Brief.metric_snapshot: dict[str, Sha256Hex]`, `DesignRef.brief_chain_hash`, all `bundle_hash` / `result_hash` / `raw_hash` / `ast_hash` / `chain_hash` on events. For `metric_snapshot` (dict[str, Sha256Hex]), use a `@field_validator` to validate each value matches the pattern.

- **Owner persona:** Orchestrator-engineer §2.2; Thesis-keeper §2.2.
- **Inputs:** None — first Wave 0 task.
- **Outputs:** A reusable type alias and a closure test (`test_hash_field_closure.py`) that asserts every field whose name ends in `_hash` or `_sha256` in any schema in `agentxp/schemas/*.py` and `agentxp/audit/events.py` is annotated with `Sha256Hex` (or has a pattern validator). Adding a new hash-shaped field without using `Sha256Hex` fails the closure test.
- **Acceptance criteria:**
  - Literal `<pending>`, empty string, 63-char hex, 65-char hex, uppercase-hex, non-hex chars all raise `ValidationError` at every model that uses `Sha256Hex`.
  - `test_hash_field_closure.py` passes.
  - All existing valid sha256 hashes in fixture files continue to validate.
- **Depends on:** None.

#### Task W0.2 — `SURFACE_V01_ENABLED` feature flag

- **File paths:** `agentxp/_flags.py` (NEW).
- **What it does:** Defines the boolean flag (literal block from §1.4 above). Read at module-import time; controlled via `AGENTXP_SURFACE_V01` env var until Wave 4.
- **Owner persona:** Orchestrator-engineer §1.1.
- **Inputs:** None.
- **Outputs:** Importable boolean; CLI entry points and the `/experiment` sub-verb router gate behavior on this flag through Wave 3.
- **Acceptance criteria:** `from agentxp._flags import SURFACE_V01_ENABLED` works; defaults to False when env var unset; flips True when set to `"1"`.
- **Depends on:** None.

#### Task W0.3 — `EventMetadataSubtype` Literal extension

- **File paths:** `agentxp/audit/events.py` (~line 65 — the existing subtype Literal location), `tests/audit/test_event_subtype_completeness.py` (NEW).
- **What it does:** Extends the existing forward-compatible `EventMetadataSubtype` Literal to include the full canonical Wave-0 set:

```python
EventMetadataSubtype = Literal[
    "inline",
    "api",
    "inline_validation_failed",
    "dispatch_runtime_error",
    "connection_established",
    "brief_hash_mismatch",
    "metric_snapshot_mismatch",
    "assignments_snapshot_mismatch",
    "state_migrated_v3_v4",
    "recovery_inline",
    "experiment_bootstrapped",
    "stale_lock_broken",
    "unsupported_test_type",
    "power_infeasible",
]
```

`EventMetadataSubtype` is forward-compatible (not closure-tested by count — only EventName at 13 and Verdict at 9 are closure-tested). Documentation explicitly states this.

- **Owner persona:** Orchestrator-engineer §0 + §2.1; Audit-supplement §1 recommendation 15.
- **Inputs:** None (the Literal is a pure type-level extension).
- **Outputs:** Forward-compat Literal usable from any chain-event payload.
- **Acceptance criteria:** EventName closure test (`tests/audit/test_event_enum_closure.py`) still asserts `len(EventName) == 13`. New subtype values pass through `_emit` without rejection. Test asserts no two values are duplicates and the type covers every documented subtype reference in the codebase.
- **Depends on:** W0.1 (some payload fields use `Sha256Hex`).

#### Task W0.4 — Chain Invariants 5 → 6 (Invariant 3b / Invariant 6)

- **File paths:** `agentxp/audit/chain.py::validate_chain`, `agentxp/audit/chain.py` (the `ChainValidation` model), `tests/audit/test_invariant_3b_bundle_anchoring.py` (NEW), `tests/audit/test_validate_chain_closure.py` (closure test extended).
- **What it does:** Extends `validate_chain` with Invariant 6 (also referred to as Invariant 3b in some persona plans — synthesis lands it as **Invariant 6**, the sixth invariant after the existing five):

```
For every file matching experiments/<exp_id>/bundles/*.out.yaml:
  let agent_name = basename without .out.yaml
  REQUIRE: at least one paired (agent.dispatched, agent.completed) in log.jsonl
    where both events' payload.agent_name == agent_name AND share a parent_action_id linkage
  REQUIRE: agent.dispatched.payload.bundle_hash equals sha256(canonical-JSON of bundle source_hashes dict)
  REQUIRE: agent.dispatched.metadata.subtype in {"inline", "api", "recovery_inline"}
  REQUIRE: when subtype == "inline", bundles/<agent>.inline.txt exists AND
           agent.completed.metadata.inline_raw_sha256 equals sha256(inline.txt content)
  FAIL_MODE: Violation(kind="bundle_unanchored", path=..., msg="out.yaml with no dispatched/completed pair")
            OR Violation(kind="bundle_hash_mismatch", ...)
            OR Violation(kind="inline_raw_missing", ...)
            OR Violation(kind="inline_raw_hash_mismatch", ...)
```

Also extends `ChainValidation` with a third state (`unverifiable_count: int`, `unverifiable_paths: list[str]`) for legacy logs lacking the pairs. Legacy logs become **UNVERIFIABLE**, not invalid — a third state alongside valid/invalid. `agentxp audit --allow-unverifiable <exp_id>` is the explicit override for legacy.

- **Owner persona:** Thesis-keeper §2.1; Curriculum-maintainer §3 (B1 reinforcement).
- **Inputs:** W0.3 (subtype Literal includes "inline", "api", "recovery_inline"), W0.1 (Sha256Hex for bundle_hash).
- **Outputs:** Strengthened `validate_chain` that catches the audit's B1 finding.
- **Acceptance criteria:**
  - Synthetic test fixture with `bundles/foo.out.yaml` and no paired events → `Violation(kind="bundle_unanchored")`.
  - Synthetic fixture with mismatched bundle_hash payload → `Violation(kind="bundle_hash_mismatch")`.
  - Synthetic inline-mode fixture missing `inline.txt` → `Violation(kind="inline_raw_missing")`.
  - Inline-mode fixture with tampered `inline.txt` → `Violation(kind="inline_raw_hash_mismatch")`.
  - Legacy fixture with unanchored bundles → `ChainValidation(unverifiable_count=N, unverifiable_paths=[...])`.
  - `agentxp audit` output distinguishes UNVERIFIABLE from VALID/INVALID.
- **Depends on:** W0.3.

#### Task W0.5 — StateYaml v3 → v4 migration + `agentxp migrate-state` verb (Shane decision 3)

- **File paths:** `agentxp/schemas/state.py` (StateYaml class ~line 397; new `terminal: bool`, `design_ref: Optional[DesignRef]` fields; `schema_version: Literal[4]`), `agentxp/cli/migrate_state.py` (NEW), `agentxp/orchestrator/migrate.py` (NEW — the migration logic), `tests/cli/test_migrate_state_v3_v4.py` (NEW).
- **What it does:** Bumps StateYaml to v4 with two new fields: `terminal: bool` (false by default; set true at final-stage commit per lifecycle) and `design_ref: Optional[DesignRef]` (populated only on analyze-side experiments).

Ships `agentxp migrate-state` CLI verb per Shane decision 3 — explicit, no auto-mutation at read time. CLI shape:

```bash
agentxp migrate-state <experiment_id> [--dry-run] [--force]
agentxp migrate-state --all [--dry-run]
```

Behavior:
- `--dry-run`: report what would change, exit 0, no writes.
- Default: acquire `.state.lock`, read v3, validate, write v4 with new defaults (`terminal=False`, `design_ref=None`), preserve prior file at `state.yaml.v3.bak`, emit `stage.committed` event with `metadata.subtype="state_migrated_v3_v4"`, `metadata.from_schema_version=3`, `metadata.to_schema_version=4`. Release lock.
- `--all`: iterate every dir under `experiments/`.
- v4-already → no-op, exit 0 with "already at v4".
- v2-or-older → refuse with "version too old; this migrator handles v3 → v4 only", exit non-zero.

v4 code reading a v3 file raises a clear error: "experiments/exp_003/state.yaml is at schema_version: 3. Run `agentxp migrate-state --exp-id exp_003`."

- **Owner persona:** Orchestrator-engineer §1.3; Product-UX §6 (refusal/success/failure copy).
- **Inputs:** W0.1 (Sha256Hex), W0.3 (state_migrated_v3_v4 subtype).
- **Outputs:** v4 schema; CLI verb; migration chain event.
- **Acceptance criteria (test plan):**
  - `test_v3_round_trip`: write v3, migrate, assert v4 loads with `terminal=False`, `design_ref=None`.
  - `test_idempotent_on_v4`: migrate v4 file → no-op, exit 0.
  - `test_refuses_v2`: v2 file → error code, no write, no chain event.
  - `test_emits_chain_event`: assert `stage.committed` with `subtype=state_migrated_v3_v4` lands in log.jsonl; chain still validates after migration.
  - `test_resume_path_hint`: load v3 with v4 reader → expect "run agentxp migrate-state" exit message.
  - `test_dry_run_no_write`: assert no file modified, no chain event.
  - `test_all_flag`: three experiments (v3, v4, v2) → migrates v3, skips v4, refuses v2; v3 succeeds even though v2 fails.
  - Product-UX refusal/success/failure messages (literal strings in §6.1–6.4 of product-ux Round 2) ship verbatim.
- **Depends on:** W0.1, W0.3.

#### Task W0.6 — Repo-wide `exp_id` → `experiment_id` sweep + AST CI lint (audit G3)

- **File paths:** `agentxp/finalize.py:253–254` and all other call sites under `agentxp/`, `tests/lint/test_no_exp_id_kwarg.py` (NEW).
- **What it does:** Sweeps function signatures and pydantic field names to use `experiment_id` consistently. CLI argument names like `--exp-id` remain user-facing for ergonomics; the kwarg name inside Python is `experiment_id`. Local variables (e.g., `exp_id = exp_dir.name` at `agentxp/render/adapters/index_html.py:104`) are out of scope.

Adds an AST-based lint at `tests/lint/test_no_exp_id_kwarg.py`:

```python
import ast, pathlib
def test_no_exp_id_in_function_signatures():
    forbidden = []
    for py in pathlib.Path("agentxp").rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args + node.args.kwonlyargs:
                    if arg.arg == "exp_id":
                        forbidden.append(f"{py}:{node.lineno} def {node.name}({arg.arg}...)")
    assert not forbidden, "\n".join(forbidden)
```

- **Owner persona:** Orchestrator-engineer §2.6.
- **Inputs:** None.
- **Outputs:** Consistent kwarg naming; lint that catches regression.
- **Acceptance criteria:** Lint passes on the cleaned repo; lint fails on a synthetic `def foo(exp_id: str)` injection.
- **Depends on:** None.

#### Task W0.7 — `SessionMetadata.last_action_metadata` → `LastActionMetadata` explicit submodel (audit G4)

- **File paths:** `agentxp/schemas/state.py` (above the `SessionMetadata` class definition).
- **What it does:** Replaces the dict-typed `last_action_metadata` with an explicit submodel keeping `extra="forbid"`:

```python
class LastActionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: Optional[Literal["from_data", "from_brief", "resume"]] = None
    source_path: Optional[str] = None
    brief_path: Optional[str] = None
    parent_experiment_id: Optional[str] = None
    notes: Optional[str] = None

class SessionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # existing fields...
    last_action_metadata: Optional[LastActionMetadata] = None
```

- **Owner persona:** Orchestrator-engineer §2.7.
- **Inputs:** W0.5 (StateYaml v4).
- **Outputs:** A typed metadata block that accepts the documented `plan` and `source_path` fields the audit's G4 surfaced as missing.
- **Acceptance criteria:** `{"plan": "from_data", "source_path": "..."}` validates. Unknown key raises. Null is allowed.
- **Depends on:** W0.5.

#### Task W0.8 — Add `python-ulid>=2.2,<3.0` dependency (audit G2)

- **File paths:** `pyproject.toml`.
- **What it does:** Adds `python-ulid>=2.2,<3.0` to `[project] dependencies`. Pinned to python-ulid (not ulid-py) because (a) python-ulid is the actively-maintained successor, (b) it ships type stubs, (c) ulid-py is deprecated upstream.
- **Owner persona:** Orchestrator-engineer §2.5.
- **Inputs:** None.
- **Outputs:** Installable dep; `from ulid import ULID` works at `agentxp/orchestrator/store.py:484`.
- **Acceptance criteria:** `tests/test_dependencies.py::test_ulid_importable` — `import ulid; ulid.ULID()` succeeds in a clean environment.
- **Depends on:** None.

#### Task W0.9 — Drop orphan v1 metric YAMLs at project root (audit S2)

- **File paths:** Delete `metrics/bounce_rate.yaml`, `metrics/checkout_completion_rate.yaml`, `metrics/d7_retention.yaml`, `metrics/revenue_per_session.yaml`, `metrics/session_revenue.yaml`, plus any `.bak` siblings. List deletions in `CHANGELOG.md` v0.1.0.
- **What it does:** Clean-deletes the five orphan v1 metric YAMLs that bind to nothing in the new warehouse. No `agentxp migrate-metrics` verb for v0.1 — that's deferred to v0.1→v0.2 future.
- **Owner persona:** Warehouse-engineer §2.3.
- **Inputs:** None.
- **Outputs:** Cleaner `metrics/` directory; explicit CHANGELOG entry.
- **Acceptance criteria:** Filesystem assertion; CHANGELOG lists each deletion.
- **Depends on:** None.

#### Task W0.10 — `VoiceRule.enforcement: Literal["halt", "warn"]` schema field (audit B10)

- **File paths:** `agentxp/schemas/voice_rule.py` (extends current), `agentxp/voice/audit.py` (the driver), `tests/voice/test_enforcement_tiers.py` (NEW).
- **What it does:** Per audit-supplement §2.J resolution: **2-tier**, not 3-tier. Each `VoiceRule` declares `enforcement: Literal["halt", "warn"]` with no `advise` tier. Display labels render as "enforced" (❌) for halt and "advisory" (ℹ️) for warn.

```python
class VoiceRule(BaseModel):
    rule_id: int
    description: str
    enforcement: Literal["halt", "warn"]
    pattern: str | None = None
```

Driver:

```python
def run_voice_audit(text: str, rules: list[VoiceRule]) -> VoiceAuditResult:
    violations = [v for rule in rules for v in rule.check(text)]
    halt_violations = [v for v in violations if v.rule.enforcement == "halt"]
    warn_violations = [v for v in violations if v.rule.enforcement == "warn"]
    return VoiceAuditResult(
        passed=not halt_violations,
        halt_violations=halt_violations,
        warn_violations=warn_violations,
    )
```

Migration: existing rules without explicit `enforcement` default to `"warn"`. The audit's three observed-overridden rules migrate to `"warn"` (Shane can promote to `"halt"` later individually).

**No commit-driver override.** `_commit_stage` only sees the tiered result; halt-tier violations cannot be bypassed by a second script.

- **Owner persona:** Thesis-keeper §2.7 (revised per audit-supplement §2.J — `advise` dropped); Orchestrator-engineer §2.4; Product-UX §4.8.
- **Inputs:** None.
- **Outputs:** Single-source-of-truth tier per rule; renderer reads from the schema.
- **Acceptance criteria:** `test_voice_audit_halt_only_blocks_commit` — synthetic text triggering rule 1 (warn) and rule 2 (halt) → commit blocked; remove halt trigger → commit succeeds with warn-tier caveats logged to artifact. Renderer shows ❌ (enforced) and ℹ️ (advisory) blocks per Product-UX §4.8 literal mockups.
- **Depends on:** None.

#### Task W0.11 — `VerdictKind` 8 → 9 (add `UNVERIFIABLE`) (audit B5, audit-supplement §2.D)

- **File paths:** `agentxp/schemas/verdict.py` (or wherever VerdictKind lives), `agentxp/verdict/walk_tree.py` (the tree itself — refactored to refuse null inputs), `tests/verdict/test_verdict_enum_closure.py` (updated to `== 9`), `tests/verdict/test_walk_tree_null_input_refuses.py` (NEW).
- **What it does:** Adds `UNVERIFIABLE` as the 9th VerdictKind value. Refactors `walk_tree` to refuse null inputs at any step rather than auto-passing:

```python
class StepOutcome(Enum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIABLE = "unverifiable"  # NEW

def walk_tree(inputs: VerdictInputs) -> Verdict:
    for step in TREE_STEPS:
        outcome = step.evaluate(inputs)
        if outcome == StepOutcome.FAIL:
            return Verdict(step_id=step.id, kind=step.fail_verdict)
        if outcome == StepOutcome.UNVERIFIABLE:
            return Verdict(
                step_id=step.id,
                kind=VerdictKind.UNVERIFIABLE,
                reason=step.unverifiable_reason(inputs)
            )
    return Verdict(step_id=TREE_STEPS[-1].id, kind=VerdictKind.SHIP)

class Step:
    id: str
    required_inputs: list[str]
    fail_verdict: VerdictKind
    def evaluate(self, inputs: VerdictInputs) -> StepOutcome:
        for inp in self.required_inputs:
            if getattr(inputs, inp) is None:
                return StepOutcome.UNVERIFIABLE
        return self._evaluate_impl(inputs)
```

Step 7 (late-ramp/novelty) declares `required_inputs = ["late_ratio", "novelty_decay_curve"]`; null `late_ratio` → walk halts at UNVERIFIABLE, never SHIP.

- **Owner persona:** Thesis-keeper §2.4 (spec); Orchestrator-engineer (implementation, per audit-supplement §3.1).
- **Inputs:** None.
- **Outputs:** Honest verdict tree; closure test asserts `len(VerdictKind) == 9`.
- **Acceptance criteria:** Null `late_ratio` → `VerdictKind.UNVERIFIABLE` with reason "late_ratio is null — fact source is snapshot-mode". Closure test passes at 9. Existing 8-value verdicts continue to fire correctly.
- **Depends on:** None.

#### Task W0.12 — `FactSource` discriminated subclass split + `kind: fact|dimension` on semantic_model (audit B4)

- **File paths:** `agentxp/schemas/fact_source.py`, `agentxp/schemas/semantic_model.py`, `tests/schemas/test_fact_source_discriminator.py` (NEW).
- **What it does:** Splits `FactSource` into two discriminated subclasses:

```python
class FactSource(BaseModel):
    type: Literal["event_time"] = "event_time"
    time_column: str = Field(min_length=1)
    # ... other fields

class SnapshotFactSource(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    snapshot_at: datetime
    entity_column: str = Field(min_length=1)
    # no time_column field

FactSourceUnion = Annotated[Union[FactSource, SnapshotFactSource], Field(discriminator="type")]
```

Adds `kind: Literal["fact", "dimension"]` to `SemanticModel` schema. `users.yaml` and `experiments.yaml` set `kind: dimension`; their bound `fact_sources/*.yaml` legally omit `time_column`.

Adds the warehouse-engineer's three-stack `time_column` validator (`@model_validator(mode="after") _validate_time_column`): field exists, is timestamp-typed, has `role: event_time`.

- **Owner persona:** Thesis-keeper §2.3; Warehouse-engineer §2.1.
- **Inputs:** None.
- **Outputs:** Schema where snapshot mode is structurally distinct from event-time mode; B4 (time_column=user_id lie) impossible.
- **Acceptance criteria:** Synthetic fact_source with `time_column: user_id` against a non-timestamp field raises `ValidationError`. Snapshot-typed FactSource validates without `time_column`. Tests pass.
- **Depends on:** None.

#### Task W0.13 — Schema cleanups (I1, I2, I3, I4, I5, `Brief`, `DesignRef`)

- **File paths:** `agentxp/schemas/metric.py`, `agentxp/schemas/experiment.py` (Hypothesis), `agentxp/schemas/report.py`, `agentxp/schemas/data_plan.py`, `agentxp/schemas/brief.py` (NEW), `agentxp/schemas/design_ref.py` (NEW).
- **What it does:** Lands a cluster of schema cleanups from audit I1–I5 plus the new Brief/DesignRef models:

**I1 — three-slot XOR `mde_default_*`:**
```python
class Metric(BaseModel):
    type: SupportedTestType  # see W1.5
    mde_default_relative_pct: Optional[float] = None
    mde_default_absolute_pp: Optional[float] = None
    mde_default_absolute_units: Optional[float] = None

    @model_validator(mode="after")
    def _exactly_one_mde(self):
        slots = [self.mde_default_relative_pct, self.mde_default_absolute_pp, self.mde_default_absolute_units]
        if sum(1 for s in slots if s is not None) != 1:
            raise ValueError(f"Metric '{self.name}' must declare exactly one mde_default_*.")
        if self.mde_default_absolute_pp is not None and self.type != "proportion":
            raise ValueError("mde_default_absolute_pp only valid for type=proportion.")
        return self
```

**I2 — Hypothesis mirror:** `predicted_magnitude_pct` → 2-slot XOR `predicted_magnitude_relative_pct` / `predicted_magnitude_absolute_pp`. Brief-validation cross-checks unit alignment with the referenced metric.

**I3 — drop `Hypothesis.predicted_direction`** (the metric YAML's `direction` is canonical); keep distinct `Hypothesis.predicted_lift_sign: Literal[+1, -1]` (information not in the metric YAML — a user predicting a negative lift on a higher-is-better metric).

**I4 — `ConfidenceLabel` closed enum + display map:**
```python
class ConfidenceLabel(str, Enum):
    HIGHLY_LIKELY_POSITIVE = "highly_likely_positive"
    LIKELY_POSITIVE = "likely_positive"
    INCONCLUSIVE = "inconclusive"
    LIKELY_NEGATIVE = "likely_negative"
    HIGHLY_LIKELY_NEGATIVE = "highly_likely_negative"

class InterpreterOutput(BaseModel):
    confidence_label: ConfidenceLabel  # closed enum

CONFIDENCE_DISPLAY = {
    ConfidenceLabel.HIGHLY_LIKELY_POSITIVE: "highly likely positive",
    # ...
}
```
Chain carries the underscore-machine form; renderer reads `CONFIDENCE_DISPLAY[label]` for human strings.

**I5 — status-gated `data_plan.yaml` rewrite:**
```python
class DataPlanV2(BaseModel):
    status: Literal["draft", "confirmed"]

    @model_validator(mode="after")
    def _required_fields_by_status(self):
        if self.status == "confirmed":
            missing = []
            if not self.fact_source_bindings: missing.append("fact_source_bindings")
            if not self.assignment_binding: missing.append("assignment_binding")
            for fsb in (self.fact_source_bindings or []):
                if not fsb.fingerprint_sha256:
                    missing.append(f"fact_source_bindings[{fsb.name}].fingerprint_sha256")
            if missing:
                raise ValueError(f"status=confirmed requires: {missing}")
        return self
```
The `_write_artifact(..., amend=True)` flag permits in-place draft updates; `ArtifactLocked` engages once status flips to `confirmed`.

**`Brief` model (NEW):**
```python
class ExpectedShape(BaseModel):
    n_per_arm: int
    allocation: dict[str, float]
    allocation_tolerance: float = 0.02
    exposure_window: tuple[datetime, datetime]
    assignment_unit: str
    requires_event_time: bool = True

class Brief(BaseModel):
    experiment_id: str
    design_chain_hash: Sha256Hex
    metric_snapshot: dict[str, Sha256Hex]  # metric_id → sha256 of YAML
    expected_shape: ExpectedShape
    hypothesis: Hypothesis
    sealed_at: datetime
```

**`DesignRef` model (NEW):**
```python
class DesignRef(BaseModel):
    brief_path: str  # repo-relative
    brief_chain_hash: Sha256Hex
    source_experiment_id: str
```

- **Owner persona:** Warehouse-engineer §2.4 (I1, three-slot XOR); Orchestrator-engineer §2.12 (I2), §2.13 (I3), §2.14 (I4), §2.15 (I5); Orchestrator-engineer §1.3 (Brief, DesignRef).
- **Inputs:** W0.1, W0.5.
- **Outputs:** A complete schema vocabulary for the brief integrity lock, hypothesis, metrics, and data plan.
- **Acceptance criteria:** Each sub-schema has a test asserting valid examples pass and invalid examples raise. `test_data_plan_status_transitions.py` covers the draft→confirmed lifecycle. `test_hypothesis_no_predicted_direction.py` asserts the field is absent and a legacy brief with it raises a clear "remove predicted_direction" error.
- **Depends on:** W0.1, W0.5.

#### Task W0.14 — `OrchestratorStore.bootstrap_experiment` + `allocate_experiment_id` (audit G5, S7)

- **File paths:** `agentxp/orchestrator/store.py` (new method on `OrchestratorStore`), `agentxp/orchestrator/allocate.py` (NEW).
- **What it does:** Adds `bootstrap_experiment` method:

```python
def bootstrap_experiment(
    self,
    experiment_id: str,
    *,
    journey: Literal["design", "analyze"],
    design_ref: Optional[DesignRef] = None,
    initial_metadata: Optional[LastActionMetadata] = None,
) -> Path:
    """Scaffold a fresh experiment directory.

    Creates experiments/<experiment_id>/{bundles,decisions,analyses,queries/results}/,
    writes initial state.yaml (schema_version=4, current_stage=PROFILE if design or
    MONITOR if analyze, terminal=False, design_ref=design_ref), seeds an empty
    log.jsonl, and emits the first chain event (stage.entered with
    metadata.subtype="experiment_bootstrapped").
    """
```

Implementation per orchestrator-engineer §2.8 (full body in that document). Sub-verb routing calls this on entry. Throws `ExperimentAlreadyExists` if dir exists.

`allocate_experiment_id(project_root)` at `agentxp/orchestrator/allocate.py`:
```python
def allocate_experiment_id(project_root: Path) -> str:
    existing = [d.name for d in (project_root / "experiments").iterdir() if d.is_dir()]
    pattern = re.compile(r"^exp_(\d+)$")
    nums = [int(m.group(1)) for d in existing if (m := pattern.match(d))]
    next_n = (max(nums) + 1) if nums else 1
    return f"exp_{next_n:03d}"
```

Custom IDs allowed as long as `^exp_[a-z0-9_]+$` and not colliding with `archive/`, `tmp_`, `__`. Analyze experiments may adopt the brief's experiment_id (so `briefs/E_F12345.yaml` analyzed produces `experiments/E_F12345/`).

- **Owner persona:** Orchestrator-engineer §2.8 + §2.11.
- **Inputs:** W0.5, W0.7, W0.13 (DesignRef, LastActionMetadata).
- **Outputs:** Scaffolded experiment dirs; ID allocator.
- **Acceptance criteria:** `tests/orchestrator/test_bootstrap_experiment.py` — all subdirs exist; state.yaml validates v4 with correct `terminal=False` and `design_ref`; log.jsonl exists with the bootstrap event; subtype=experiment_bootstrapped. `tests/orchestrator/test_allocate.py` — fresh repo → exp_001; with exp_001 and exp_003 → exp_004 (max+1); collision detection; format validation.
- **Depends on:** W0.5, W0.7, W0.13.

#### Task W0.15 — `agentxp.recovery` namespace (commit-stage) + `agentxp unlock --reason` + `.state.lock` surfacing (Shane decision 6; audit S5)

- **File paths:** `agentxp/recovery/__init__.py` (NEW), `agentxp/recovery/cli.py` (NEW), `agentxp/cli/unlock.py` (NEW), `agentxp/cli/list.py` (lock column added), `agentxp/cli/audit.py` (lock block added), `tests/recovery/test_commit_stage.py` (NEW), `tests/cli/test_unlock.py` (NEW).
- **What it does:** Per Shane decision 6 + audit-supplement §2.B: ships `commit-stage` under `python3 -m agentxp.recovery commit-stage`, NOT as a top-level `agentxp` verb. Not in `agentxp --help` or CLAUDE.md §2. All emitted events carry `metadata.subtype="recovery_inline"`.

CLI shape:
```bash
python3 -m agentxp.recovery commit-stage <experiment_id> <stage> \
  --bundle <agent_name>=<bundle_path> [--bundle ...] \
  [--inline-output <agent_name>=<output_path>] \
  [--reason "<short description>"]
```

Semantics per orchestrator-engineer §2.9 (full spec in that document). For each `--bundle agent=path`, loads the bundle source, calls `dispatch_agent(..., inline_output=...)`. After dispatches succeed, calls `_commit_stage(stage)`.

Adds `agentxp unlock <experiment_id> --reason "<why>"` verb:
- Reads `.state.lock`; if PID alive → refuse with "lock held by live PID X"; if PID dead → delete lock and emit `stage.committed` with `metadata.subtype="stale_lock_broken"`, `metadata.reason=<reason>`, `metadata.stale_pid=<dead_pid>`.
- `--reason` REQUIRED (literal Product-UX §4.4 refusal message ships verbatim).

Adds lock surfacing per Product-UX §4.4:
- `agentxp list` adds `🔒` prefix and a `lock` column showing `PID 4421` for live, `stale_lock` for dead, blank for unlocked.
- `agentxp audit <exp_id>` opens with a literal lock block (Product-UX §4.4 mockup).

- **Owner persona:** Orchestrator-engineer §2.9 + §2.10; Product-UX §4.3 + §4.4.
- **Inputs:** W0.3 (recovery_inline, stale_lock_broken subtypes), W0.14 (bootstrap).
- **Outputs:** Internal recovery surface; unlock verb; lock visibility.
- **Acceptance criteria:** `test_commit_stage` — happy path, bundle-not-found error, inline-output schema violation. `test_unlock` — stale lock broken with audit event; live lock refused; missing lock errors cleanly; `--reason` required.
- **Depends on:** W0.3, W0.14.

#### Task W0.16 — `agentxp prune` verb (audit S1)

- **File paths:** `agentxp/cli/prune.py` (NEW), `audit/project.jsonl` (project-level event log, NEW concept), `tests/cli/test_prune.py` (NEW).
- **What it does:** New verb per Product-UX §4.1. Behavior + refusal conditions:

```
$ agentxp prune
Scanning experiments/ for orphans...

Found N orphan experiments (no state.yaml, no log.jsonl):
  experiments/exp_NNN/    (M files, last modified ...)

Found 0 stale locks (locks older than 1h with no live process).
Found 0 incomplete experiments (have state.yaml, current_stage != terminal).

Prune the N orphans? [y/N/show] y
```

Refusal conditions:
1. Live `.state.lock` → refuse; direct to `agentxp unlock`.
2. `state.yaml` exists AND `current_stage != terminal` AND last-modified < 7 days → refuse by default; require `--all --force`. Hint at `/resume`.
3. Sealed brief referenced from elsewhere → refuse (pruning would orphan an analyze chain).

Flags: `--all`, `--dry-run`, `--force`, positional `exp_id`.

Events recorded in `audit/project.jsonl` (a project-level event log separate from per-experiment `log.jsonl`) as `prune.completed` with `{exp_id, files_removed, reason, ts, by}`. Same file holds `connection.established` and `migrate-state.completed`.

Discoverability: `agentxp list` adds `status` column showing `orphan` for any `experiments/<id>/` without state.yaml; footer "Orphans (run `agentxp prune` to clean up)". `/experiment design` Stage 0 emits one-line hint when orphans exist. `/help` lists `prune`.

- **Owner persona:** Product-UX §4.1.
- **Inputs:** W0.14, W0.15.
- **Outputs:** Garbage collection verb; project-level audit log file.
- **Acceptance criteria:** `test_prune` — dry-run reports orphans without deleting; live-lock refusal works; in-flight refusal works; force-flag bypasses #2/#3 but never #1; `prune.completed` event lands in `audit/project.jsonl`.
- **Depends on:** W0.14, W0.15.

#### Task W0.17 — `agentxp new` verb (audit S7)

- **File paths:** `agentxp/cli/new.py` (NEW), `tests/cli/test_new.py` (NEW).
- **What it does:** Allocates an experiment ID via `allocate_experiment_id`, calls `bootstrap_experiment(new_id, journey="design")`, prints the ID. Useful for "give me a fresh experiment dir to play with" and headless tests.

```bash
agentxp new [--id <custom_id>] [--journey design|analyze] [--brief <path>]
```

If `--id` omitted, allocator picks. If `--journey analyze --brief <path>` supplied, validates brief, then bootstraps with `design_ref` and `LastActionMetadata(plan="from_brief", brief_path=...)`.

- **Owner persona:** Orchestrator-engineer §2.11; Product-UX §4.2 (UX side).
- **Inputs:** W0.14.
- **Outputs:** A clean way to allocate + scaffold without going through the slash command.
- **Acceptance criteria:** `test_new` — fresh repo → exp_001 scaffolded; collision detection; custom ID validation.
- **Depends on:** W0.14.

---

### §3.1 Wave 1 — SQL chokepoint wiring + result_hash content-faithfulness

**Goal:** Wire the existing `agentxp/sql/dispatch.py` worker through `OrchestratorStore.dispatch_sql()`, ship the DuckDB adapter, fix the silent `result_hash` content-faithfulness bug, add parquet emission, and land the analyzer's `SupportedTestType` registry.

**Ships dark.** No surface flip. Internally exercises CSV path via DuckDB until Wave 2 ships the warehouse.

**Parallelism notes:** W1.1, W1.2, W1.5, W1.6 are independent. W1.3, W1.4 depend on W1.1.

**Tasks:**

#### Task W1.1 — `OrchestratorStore.dispatch_sql()` store wrapper

- **File paths:** `agentxp/orchestrator/store.py` (around line 929 — the existing `NotImplementedError` stub).
- **What it does:** Delegates to the existing 5-layer worker at `agentxp/sql/dispatch.py`. Emits `query.proposed`, `query.validated`, `query.executed`/`query.failed` chain events through `self._emit()`. Accepts `parent_action_id` for chain pairing.
- **Owner persona:** Orchestrator-engineer §0 + §1.2.
- **Inputs:** None (worker already exists).
- **Outputs:** Live `dispatch_sql` path; no more NotImplementedError.
- **Acceptance criteria:** End-to-end SQL dispatch against CSVs (Wave 1) and DuckDB (post-Wave 2) returns rows, emits the three-event chain, and `result_hash` flows through W1.2's canonicalizer.
- **Depends on:** None.

#### Task W1.2 — `canonical_result_hash` content-faithful hashing (audit B8 partial, debate §2.9)

- **File paths:** `agentxp/sql/_hashing.py` (NEW), `agentxp/sql/dispatch.py` (`_emit_executed` updated), `tests/sql/test_result_hash_order_invariance.py` (NEW), `tests/sql/test_result_hash_pinned_E_F12345.py` (NEW).
- **What it does:** Replaces the silently-broken `result_hash=_sha256_hex(f"{row_count}|{bytes_scanned}")` with canonical row-content hash:

```python
def canonical_result_hash(rows: list[tuple], column_names: list[str]) -> str:
    canonicalized = [
        json.dumps(dict(zip(column_names, row)), sort_keys=True, default=str)
        for row in rows
    ]
    canonicalized.sort()
    return hashlib.sha256("\n".join(canonicalized).encode("utf-8")).hexdigest()
```

Order-invariance closure test: shuffling rows produces identical hash. E_F12345 pinned-hash test: SHIP-anchor query produces a literal pinned sha256 hex (Wave 2's warehouse seed + this canonicalizer = deterministic anchor).

- **Owner persona:** Orchestrator-engineer §1.2; Thesis-keeper §2 (debate §2.9).
- **Inputs:** None.
- **Outputs:** Replay-deterministic `result_hash` for every query.
- **Acceptance criteria:** Order-invariance test passes. Pinned-hash test passes once warehouse seed lands.
- **Depends on:** None.

#### Task W1.3 — DuckDB adapter for `dispatch_sql`

- **File paths:** `agentxp/sql/adapters/duckdb.py` (NEW).
- **What it does:** Implements the adapter interface (column-name extraction, row materialization as `list[tuple]`, deterministic column order). Reads from `connections/<name>.yaml` for the DuckDB file path. Also supports the CSV-via-DuckDB path (CSV adapter persists as a product feature; see audit-supplement §2.H).
- **Owner persona:** Orchestrator-engineer §1.4.
- **Inputs:** W1.1.
- **Outputs:** Working DuckDB adapter; CSV adapter still ships in `agentxp/sql/adapters/csv.py` (separate file, unchanged).
- **Acceptance criteria:** `dispatch_sql` against a DuckDB connection returns rows with deterministic column order; integration test green.
- **Depends on:** W1.1.

#### Task W1.4 — Parquet emission for query results

- **File paths:** `agentxp/sql/artifact_writer.py` (extends current).
- **What it does:** Writes query results to `experiments/<exp_id>/queries/results/<action_id>.parquet`. Uniform parquet emission (no JSON fallback for small result sets — debate §3.6 resolved to parquet uniformly).
- **Owner persona:** Orchestrator-engineer §1.2.
- **Inputs:** W1.1.
- **Outputs:** Parquet result files chain-anchored via `query.executed.metadata.result_path`.
- **Acceptance criteria:** Result file lands at the expected path; sha256 of the file matches the emitted `result_hash`.
- **Depends on:** W1.1.

#### Task W1.5 — Analyzer `SupportedTestType` Literal + `SUPPORTED_TESTS` registry (audit B6)

- **File paths:** `agentxp/schemas/metric.py` (adds `SupportedTestType` Literal), `agentxp/analyzer/registry.py` (NEW), `tests/analyzer/test_test_registry_literal_mirror.py` (NEW).
- **What it does:** Closed Literal:

```python
SupportedTestType = Literal[
    "proportion",   # two-proportion z-test
    "mean",         # Welch's t
    "p50",          # median bootstrap
    "p95",          # quantile bootstrap
    "p99",          # quantile bootstrap
    "sum",          # mean-on-sum, bootstrap CI
    "ratio",        # delta method
]
```

Registry:
```python
SUPPORTED_TESTS: dict[SupportedTestType, Callable[..., StatTest]] = {
    "proportion": two_proportion_z_test,
    "mean": welch_t_test,
    "p50": quantile_bootstrap_p50,
    "p95": quantile_bootstrap_p95,
    "p99": quantile_bootstrap_p99,
    "sum": sum_bootstrap,
    "ratio": delta_method_ratio,
}

def dispatch_test(metric: Metric, ...) -> StatTest:
    if metric.type not in SUPPORTED_TESTS:
        raise UnsupportedTestType(metric.type)  # raise, never substitute
    return SUPPORTED_TESTS[metric.type](...)
```

Closure test asserts `set(SupportedTestType.__args__) == set(SUPPORTED_TESTS.keys())`. **The p95→mean silent substitution path is DELETED** (grep `agentxp/stats/` for any code mapping unsupported types to a default; remove).

Brief-commit-time check: `validate_brief_for_commit(brief, metrics_dir)` looks up each metric's `type` against the registry and refuses unsupported types with `gate.blocked(kind=referenced_artifact_changed, subtype="unsupported_test_type")`.

- **Owner persona:** Thesis-keeper §2.5; Orchestrator-engineer §2.3.
- **Inputs:** W0.13 (metric schema), W1.1.
- **Outputs:** No silent substitution path possible; brief refuses unsupported types at commit.
- **Acceptance criteria:** Closure test passes. Synthetic brief with `type: tukey_hsd` refused at commit with literal message. Existing p95 metric in `metrics/page_load_p95.yaml` (Wave 2) processes correctly through the p95 quantile bootstrap.
- **Depends on:** W0.13.

#### Task W1.6 — Verdict tree refactor (audit B5 implementation)

- **File paths:** `agentxp/verdict/walk_tree.py`.
- **What it does:** Implements the spec from W0.11 — null-input refusal at every step, `VerdictKind.UNVERIFIABLE` returned when any required input is null. Per-step `required_inputs` declared explicitly.

Step 7 (late-ramp/novelty) declares `required_inputs = ["late_ratio", "novelty_decay_curve"]`. Wave 0 added the enum value; Wave 1 implements the consuming walker.

- **Owner persona:** Thesis-keeper §2.4 (spec); Orchestrator-engineer (implementation, per audit-supplement §3.1).
- **Inputs:** W0.11.
- **Outputs:** Honest verdict tree; B5 closed.
- **Acceptance criteria:** `test_walk_tree_null_input_refuses` — synthetic VerdictInputs with `late_ratio=None` produces `Verdict(kind=UNVERIFIABLE, step_id=7, reason="...")`, never SHIP. All existing E_F12345 happy-path tests continue to return SHIP.
- **Depends on:** W0.11.

---

### §3.2 Wave 2 — Warehouse fixture + semantic models + metrics

**Goal:** Land `sample-data/agentxp_demo.duckdb` with 8 seeded experiments, six tables, and a deterministic E_F12345 reproducing 314/384/+22.3% byte-for-byte.

**Ships dark.** No surface flip. Module 10 test bundles are regenerated from synthetic `exp_001` data (not the warehouse) and continue to pin `+0.032 (+18.0%)`.

**Parallelism notes:** W2.1 must complete before W2.7, W2.8. W2.2–W2.6 can land in any order once W2.1's generator exists.

**Tasks:**

#### Task W2.1 — Generate `sample-data/agentxp_demo.duckdb` via deterministic seeded generator

- **File paths:** `agentxp/fixtures/generate_demo_warehouse.py` (NEW), `sample-data/SEED.yaml` (NEW — pins MASTER_SEED, FIXTURE_VERSION, per-experiment seeds), `sample-data/agentxp_demo.duckdb` (generated artifact), `tests/integration/test_e_f12345_reproduces_canonical_numbers.py` (NEW).
- **What it does:** Generates the warehouse per warehouse-engineer §3 seed contract. Eight experiments:

| experiment_id   | scenario                              | expected verdict       | key numbers |
|-----------------|---------------------------------------|------------------------|-------------|
| E_F12345        | checkout banner, clean lift           | SHIP                   | n=3000/arm, ctrl 314/3000=10.47%, trt 384/3000=12.80%, +22.3% rel |
| E_SRM_001       | broken randomization (52/48 split)    | INVALID-SRM            | n_ctrl=3120, n_trt=2880, χ² halt at SRM step |
| E_GUARD_001     | primary lifts, p95 latency degrades   | NO-SHIP-GUARDRAIL      | primary +1.8pp, page_load_ms p95 +180 (guard breach) |
| E_MIX_001       | aggregate lift, segment reversal      | LIFT-WITH-CAVEAT       | overall +12% rel; iOS −4%, Android +28% (Simpson's) |
| E_NULL_001      | adequately powered null               | NO-LIFT                | n=20000/arm, observed +0.2% rel, CI straddles 0 |
| E_UNDER_001     | underpowered null                     | INCONCLUSIVE           | n=300/arm, observed +6% rel but CI [-12%, +24%] |
| E_NOVELTY_001   | early lift, fades by week 4           | LIFT-WITH-CAVEAT       | weeks 1-2 +15%, week 4 +2%, late_ratio triggers |
| E_CONTAM_001    | cross-arm contamination via referrals | INVALID-CONTAMINATION  | 8% of treated users referred control users; SUTVA gate |

**E_F12345 seed-derivation tree** (literal from warehouse-engineer §3.2):

```python
MASTER_SEED       = 0xA6EE4720
FIXTURE_VERSION   = "v0.1.0"
EXP_SEED_E_F12345 = 12345

ss = numpy.random.SeedSequence([MASTER_SEED, EXP_SEED_E_F12345])
streams = ss.spawn(8)
# Stream slot allocation (FIXED — part of FIXTURE_VERSION contract):
#   [0] control arm: which 314 of 3000 convert
#   [1] treatment arm: which 384 of 3000 convert
#   [2] control: revenue draws (lognormal)
#   [3] treatment: revenue draws
#   [4] control: page_load_ms draws
#   [5] treatment: page_load_ms draws
#   [6] control: first_exposed_at timestamps
#   [7] treatment: first_exposed_at timestamps

# Separate cohort stream (different SeedSequence root) for user selection
cohort_ss = numpy.random.SeedSequence([MASTER_SEED, EXP_SEED_E_F12345, 0xC0]).spawn(1)[0]
cohort_rng = numpy.random.default_rng(cohort_ss)
user_pool = numpy.arange(50_000)
cohort_rng.shuffle(user_pool)
control_user_idx   = user_pool[:3000]
treatment_user_idx = user_pool[3000:6000]
```

**Exact-count conversion vector** (binomial-by-shuffle):

```python
control_conv = numpy.zeros(3000, dtype=numpy.int8)
control_conv[:314] = 1
numpy.random.default_rng(streams[0]).shuffle(control_conv)
# control_conv.sum() == 314, byte-deterministic

treatment_conv = numpy.zeros(3000, dtype=numpy.int8)
treatment_conv[:384] = 1
numpy.random.default_rng(streams[1]).shuffle(treatment_conv)
# treatment_conv.sum() == 384
```

**Auxiliary distributions** (warehouse-engineer §3.5):
- Revenue per user: control lognormal(μ=ln(12.40), σ=0.6) from streams[2]; treatment lognormal(μ=ln(13.02), σ=0.6) from streams[3]. ≈+5% revenue lift.
- Page load p95: control gamma(shape=2.5, scale=200)+250 from streams[4]; treatment same from streams[5]. p95 ≈ 850ms / 855ms.
- Exposure timing: uniform over `[2026-04-01, 2026-04-15]` from streams[6]/[7]. No late-ramp bias.

- **Owner persona:** Warehouse-engineer §3.
- **Inputs:** None.
- **Outputs:** Generated `agentxp_demo.duckdb`; integration test pinning E_F12345 numbers.
- **Acceptance criteria:** `test_e_f12345_reproduces_canonical_numbers` asserts the exact 4-tuple `(control, 3000, 314, 0.10466667)` and `(treatment, 3000, 384, 0.12800000)`. Re-running the generator produces byte-identical DuckDB logical content. Per audit-supplement §2.C, E_UNDER_001 and E_NOVELTY_001 ship with widened MDEs in their metric YAMLs (NOT an `intentionally_underpowered` flag).
- **Depends on:** None.

#### Task W2.2 — Six tables DDL

- **File paths:** `agentxp/fixtures/generate_demo_warehouse.py` (DDL embedded), `docs/learn/05_data_plumbing.md` (will reference in W4).
- **What it does:** Creates six tables: `experiments`, `assignments`, `users`, `sessions`, `orders`, `page_events`. Schema per warehouse-engineer Round 1 §1.1 (canonical reference). Key columns:
  - `experiments.assignment_unit` (the per-experiment denominator for power-feasibility checks)
  - `assignments.experiment_id`, `assignments.user_id`, `assignments.variant`, `assignments.first_exposed_at`, `assignments.assignment_source`, `assignments.assignment_hash` (Sha256Hex)
  - First-exposure attribution at row level; one row per `(user_id, experiment_id)`.
  - `users` is dimensional (`kind: dimension` in semantic model); other five are facts.
- **Owner persona:** Warehouse-engineer (canonical DDL in Round 1).
- **Inputs:** W2.1.
- **Outputs:** Schema-stable tables in the generated warehouse.
- **Acceptance criteria:** SQL `DESCRIBE` against each table produces expected columns; `assignments.assignment_hash` validates against `Sha256Hex`.
- **Depends on:** W2.1.

#### Task W2.3 — `semantic_models/*.yaml` with `kind` and `joins` blocks

- **File paths:** `semantic_models/users.yaml`, `semantic_models/experiments.yaml`, `semantic_models/assignments.yaml`, `semantic_models/sessions.yaml`, `semantic_models/orders.yaml`, `semantic_models/page_events.yaml`.
- **What it does:** Each YAML declares `kind: fact|dimension` (W0.12), fields with `type` and `role`, and `joins:` blocks declaring valid join edges (validated by `dispatch_sql`'s semantic-check layer per warehouse-engineer §1.3). `users.yaml` and `experiments.yaml` set `kind: dimension`. Each carries `fingerprint_sha256` validated as `Sha256Hex`.
- **Owner persona:** Warehouse-engineer §1.3 + §2.1.
- **Inputs:** W0.1, W0.12, W2.2.
- **Outputs:** Semantic catalog the dispatch_sql worker reads.
- **Acceptance criteria:** Each YAML loads and validates under the v2 schema. `fingerprint_sha256` is a real sha256, never `<pending>`.
- **Depends on:** W0.1, W0.12, W2.2.

#### Task W2.4 — `metrics/*.yaml` canonical six (v2 schema, three-slot MDE)

- **File paths:** `metrics/conversion_rate.yaml`, `metrics/revenue_per_user.yaml`, `metrics/total_revenue.yaml`, `metrics/session_count.yaml`, `metrics/page_load_p95.yaml`, `metrics/late_ratio.yaml`.
- **What it does:** Six canonical metrics at v2 schema with three-slot XOR MDE (W0.13). Each metric's `type` is from `SupportedTestType` (W1.5). Example:

```yaml
# metrics/conversion_rate.yaml
name: conversion_rate
type: proportion
direction: higher_is_better
mde_default_relative_pct: 10.0     # 10% relative lift
mde_default_absolute_pp: null
mde_default_absolute_units: null
fingerprint_sha256: <sha256 of canonical YAML form>
```

`metrics/page_load_p95.yaml` declares `type: p95` (now supported via W1.5's registry — no more silent substitution).

Per audit-supplement §2.C: E_UNDER_001 and E_NOVELTY_001 may use widened-MDE variants (`metrics/conversion_rate_widened.yaml` with `mde_default_relative_pct: 25.0` or similar) so their briefs pass the 1.0× power-feasibility check.

- **Owner persona:** Warehouse-engineer §2.4 + §1.6.
- **Inputs:** W0.13, W1.5, W2.2.
- **Outputs:** Six metric YAMLs the brief locks against.
- **Acceptance criteria:** Each YAML validates; XOR validator catches multi-slot or zero-slot briefs; `type` is in the registry.
- **Depends on:** W0.13, W1.5, W2.2.

#### Task W2.5 — `assignments/README.md` underscore-prefix convention doc (audit I6)

- **File paths:** `assignments/README.md` (NEW).
- **What it does:** Documents the convention per warehouse-engineer §2.6:

```
# assignments/

assignments/<name>.yaml         — reusable spec, no underscore prefix, referenced by any experiment.
assignments/_inline_<exp>.yaml  — inline-only, single-use, bound to one experiment_id.
                                   Underscore prefix is structural marker.
                                   Auto-deleted by `agentxp prune` when bound experiment terminates.
```

Stage 4's brief-commit enforces: if `assignment_spec` points to `_inline_*.yaml`, the suffix must match `Brief.experiment_id`. Mismatch → refusal.

- **Owner persona:** Warehouse-engineer §2.6.
- **Inputs:** W0.16 (prune).
- **Outputs:** Documented convention.
- **Acceptance criteria:** README exists; Stage 4 commit refuses on suffix mismatch (covered by W3.5 acceptance).
- **Depends on:** None (the doc is standalone; the enforcement is in W3.5).

#### Task W2.6 — `sample-data/EXPERIMENTS.md` (Product-UX literal table)

- **File paths:** `sample-data/EXPERIMENTS.md` (NEW).
- **What it does:** Lands the literal 8-row table from Product-UX §7 (synthesized with warehouse-engineer's seed contract). Documents how to use each experiment (analyze with sealed brief; design fresh; regenerate). Pins E_F12345 numbers as the load-bearing curriculum anchor.

Front-matter YAML for each experiment per warehouse-engineer §2.2 (n_per_arm, allocation, exposure_window, seeded_effects, feasible_mde).

- **Owner persona:** Product-UX §7; Warehouse-engineer §2.2.
- **Inputs:** W2.1.
- **Outputs:** Discoverable experiment catalog.
- **Acceptance criteria:** Markdown loads cleanly; YAML front-matter parses; each row matches the warehouse contents.
- **Depends on:** W2.1.

#### Task W2.7 — `fixture.lock.yaml` with logical-content hashing

- **File paths:** `sample-data/fixture.lock.yaml` (NEW), `agentxp/fixtures/lock.py` (NEW).
- **What it does:** Per warehouse-engineer §5.1: hashes **logical content** (sorted rows per table, serialized canonically), NOT raw DuckDB bytes. DuckDB's internal page ordering is implementation-defined and not part of the reproducibility contract.

```python
def compute_fixture_content_hash(duckdb_path: Path) -> str:
    conn = duckdb.connect(str(duckdb_path))
    table_hashes = {}
    for tbl in sorted(["experiments", "assignments", "users", "sessions", "orders", "page_events"]):
        rows = conn.execute(f"SELECT * FROM {tbl} ORDER BY ALL").fetchall()
        cols = [d[0] for d in conn.description]
        table_hashes[tbl] = canonical_result_hash(rows, cols)
    return hashlib.sha256(json.dumps(table_hashes, sort_keys=True).encode()).hexdigest()
```

`fixture.lock.yaml` content:
```yaml
fixture_version: v0.1.0
content_hash: <sha256>
table_hashes:
  experiments: <sha256>
  assignments: <sha256>
  # ...
```

CI asserts that re-generating the fixture produces the same content_hash. Drift → CI failure.

- **Owner persona:** Warehouse-engineer §1.2.
- **Inputs:** W1.2 (canonical_result_hash).
- **Outputs:** CI dam against fixture drift.
- **Acceptance criteria:** Re-running W2.1 produces a `fixture.lock.yaml` byte-identical to the checked-in version. CI fails on any divergence.
- **Depends on:** W1.2, W2.1.

#### Task W2.8 — Regenerate `tests/render/fixtures/bundles_ship/*` (Module 10 test bundles)

- **File paths:** `tests/render/fixtures/bundles_ship/*` (regenerated), `scripts/regen_test_bundles.py` (NEW or updated).
- **What it does:** Regenerates Module 10's test bundles from synthetic `exp_001` data (not the warehouse — per audit-supplement §2.I, `exp_001` is a test-bundle-only synthetic anchor independent of the warehouse fixture). Pins `+0.032 (+18.0%)` deterministically.

Two code paths in `regen_test_bundles.py`:
- Synthetic inputs deterministically for `exp_001` → Module 10 anchor.
- Warehouse query results for `E_F12345` → trace.md / Module 1 / Module 8 anchor.

- **Owner persona:** Curriculum-maintainer §6; Orchestrator-engineer (audit-supplement §2.I).
- **Inputs:** W2.1, W1.2.
- **Outputs:** Regenerated test bundles; Module 10 unchanged numerically.
- **Acceptance criteria:** Module 10 rendering tests produce byte-identical `+0.032 (+18.0%)` strings across all six formats. E_F12345 analyze flow produces `+22.3%` against the warehouse.
- **Depends on:** W2.1, W1.2.

---

### §3.3 Wave 3 — Inline-mode dispatch + bootstrap + brief integrity

**Goal:** Land `dispatch_agent`'s inline branch, the three-part brief integrity lock, the design-time power-feasibility refusal, and the two-state-lifecycle implementation. All behind `SURFACE_V01_ENABLED=False`.

**Ships dark.** Internally exercised via `AGENTXP_SURFACE_V01=1` in test env.

**Parallelism notes:** W3.1 + W3.2 together. W3.3 depends on W0.13 (Brief schema). W3.4 depends on W3.3. W3.5 depends on W3.3.

**Tasks:**

#### Task W3.1 — `dispatch_agent` inline-mode signature + atomic dispatched/completed pair (audit B1)

- **File paths:** `agentxp/orchestrator/store.py:881` (existing `dispatch_agent` location); `tests/orchestrator/test_dispatch_agent_inline.py` (NEW).
- **What it does:** Extends `dispatch_agent` signature per orchestrator-engineer §2.1:

```python
def dispatch_agent(
    self,
    agent_name: str,
    bundle: Any,
    *,
    out_schema: type[BaseModel],
    retry_policy: Optional[RetryPolicy] = None,
    parent_action_id: Optional[str] = None,
    inline_output: dict | BaseModel | None = None,
    purpose: Optional[str] = None,
) -> DispatchResult:
```

Body implements the atomic dispatched/completed pair per orchestrator-engineer §2.1 (literal flow in that document). Three guarantees:

1. **BundleStore.assemble() runs first regardless of mode.** Produces `ctx.yaml`, `bundle_hash`, `bundle_source_hashes`.
2. **Atomic pair emission** via try/except/finally: `agent.dispatched` emitted before the try; success-branch or failure-branch `agent.completed` in every exit path. A defensive `finally` block emits `agent.completed(classification="failed", metadata.subtype="dispatch_runtime_error", metadata.exception=<repr(e)>)` if both dispatch and completion-emit fail.
3. **No retry inside `dispatch_agent` for inline mode** (debate §3.5 resolution). Schema violation raises `ValidationError`; skill catches and re-prompts Claude with a new `action_id`.

Inline-mode payloads (matching thesis-keeper §2.1):

```yaml
event_name: agent.dispatched
metadata:
  subtype: inline
  inline_raw_path: bundles/profiler.inline.txt
  bundle_source_hashes: {...}
```

```yaml
event_name: agent.completed
metadata:
  subtype: inline                    # or inline_validation_failed
  inline_raw_sha256: <Sha256Hex>     # per audit-supplement §2.A
  attempt: 1
```

- **Owner persona:** Orchestrator-engineer §2.1; Thesis-keeper §2.1; audit-supplement §2.A (inline_raw_sha256 in event payload, NOT in source_hashes).
- **Inputs:** W0.1, W0.3, W0.14.
- **Outputs:** Working inline dispatch; audit B1 closed.
- **Acceptance criteria:** Full test suite per orchestrator-engineer §2.1 (test plan section): inline happy path, inline validation failure, pair atomicity under unexpected exception, API path unchanged subtype, audit replay distinguishes inline vs api, `validate_chain` Invariant 6 catches missing pair. Closure test: every inline dispatch's `agent.completed.metadata.inline_raw_sha256` matches `sha256(inline.txt)`.
- **Depends on:** W0.1, W0.3, W0.14.

#### Task W3.2 — Inline raw-text persistence at `bundles/<agent>.inline.txt` (debate §4.6; audit-supplement §2.A)

- **File paths:** `agentxp/orchestrator/store.py` (`_write_inline_raw` helper).
- **What it does:** Per audit-supplement §2.A resolution: persist `bundles/<agent>.inline.txt` (the raw Claude turn, verbatim, no parsing), **referenced from** `agent.dispatched.metadata.inline_raw_path` AND chain-anchored via `agent.completed.metadata.inline_raw_sha256` (NOT folded into the bundle's `source_hashes`).

Append-only; may not be overwritten. Not subject to `ArtifactLocked` (it's not a "committed" artifact in the stage-commit sense; it's an audit-trail debug artifact). Invariant 6 requires its existence when `subtype="inline"`.

If raw text exists but `out.yaml` doesn't (schema validation failed), the chain still emits paired events with `classification="failed"`, `subtype="inline_validation_failed"`. Raw file remains as the audit trail of what Claude tried to produce.

- **Owner persona:** Thesis-keeper §3.2 (revised per audit-supplement §2.A); Orchestrator-engineer §4.1.
- **Inputs:** W3.1.
- **Outputs:** Raw-text audit artifact; chain-anchored via event payload.
- **Acceptance criteria:** Inline dispatch writes the file; `inline_raw_sha256` matches; Invariant 6 closure test catches deletion/tampering.
- **Depends on:** W3.1.

#### Task W3.3 — Three-part brief integrity lock (debate §2.4)

- **File paths:** `agentxp/schemas/brief.py` (W0.13 created the model; this task lands the validation logic), `agentxp/orchestrator/brief_validation.py` (NEW), `agentxp/orchestrator/store.py` (`_check_brief_bindings` at analyze-entry).
- **What it does:** Brief artifact embeds: `design_chain_hash` + `metric_snapshot: dict[str, Sha256Hex]` + `expected_shape: ExpectedShape` + `sealed_at`.

At analyze-entry, `_check_brief_bindings(brief_path)` runs:

(a) Compute `sha256(brief_file_bytes)` and verify file hasn't been touched since `sealed_at` (brief is committed via `_write_artifact` and protected by `ArtifactLocked`).
(b) Recompute design experiment's chain hash through Stage 4 commit; compare to `brief.design_chain_hash`. Fail-closed → `gate.blocked(kind=REFERENCED_ARTIFACT_CHANGED, subtype="brief_hash_mismatch")`.
(c) For every metric_id in `brief.metric_snapshot`, recompute `sha256(metrics/<metric_id>.yaml)` and compare. Mismatch → same gate, `subtype="metric_snapshot_mismatch"`.
(d) Compute `actual_assignments_snapshot_hash` from live warehouse rows scoped to `(experiment_id, [started_at, ended_at])`; compare to `brief.expected_shape` constraints (n_per_arm tolerance, allocation tolerance, exposure window match). Mismatch → same gate, `subtype="assignments_snapshot_mismatch"`.

No new `PendingDecisionKind` — all routed through existing `REFERENCED_ARTIFACT_CHANGED`. `BriefDataMismatch` exists internally as a Python exception, mapped to `gate.blocked`.

- **Owner persona:** Thesis-keeper §1.3; Orchestrator-engineer §1.3; Warehouse-engineer §1.2.
- **Inputs:** W0.13, W2.4.
- **Outputs:** Brief refuses analyze-entry on any of three drift modes.
- **Acceptance criteria:**
  - `test_brief_hash_mismatch_routes_to_referenced_artifact_changed` — analyze-entry against a brief whose `design_chain_hash` doesn't match design log → expected gate.
  - `test_metric_snapshot_mismatch_routes_to_referenced_artifact_changed`.
  - `test_assignments_snapshot_mismatch_routes_to_referenced_artifact_changed` — mutated assignments rows fail-closed.
- **Depends on:** W0.13, W2.4.

#### Task W3.4 — Design-time power-feasibility refusal (1.0× strict; Shane decision 5; audit B7)

- **File paths:** `agentxp/orchestrator/brief_validation.py` (extends W3.3), `agentxp/stats/power.py` (NEW or extends current).
- **What it does:** Inside `validate_brief_for_commit`, runs `_check_power_feasibility(brief, profile_result)`:

```python
def _check_power_feasibility(brief: Brief, profile_result: ProfileResult) -> Optional[Violation]:
    available = profile_result.assignment_surface_size
    available_per_arm = available * min(brief.expected_shape.allocation.values())
    required_per_arm = compute_n_required(
        baseline=profile_result.metric_baseline(brief.hypothesis.metric_name),
        mde=brief.hypothesis.predicted_magnitude_relative_pct or brief.hypothesis.predicted_magnitude_absolute_pp,
        power=brief.hypothesis.power,
        alpha=brief.hypothesis.alpha,
    )
    if required_per_arm > available_per_arm:  # STRICT 1.0× — Shane decision 5
        return Violation(
            kind="power_infeasible",
            msg=<Product-UX §4.7 literal refusal message>,
        )
    return None
```

**Strict 1.0× threshold per Shane decision 5 and audit-supplement §2.E.** Allocation-aware: `available_per_arm = available * min(allocation_ratio)`. No `--force` flag. No `intentionally_underpowered` escape hatch (audit-supplement §2.C).

Refusal message: literal Product-UX §4.7 string ships verbatim:

```
❌ This design can't be sealed — your assignment surface is too small.

   Brief math:
     baseline:         checkout_completion_rate = 12.3%
     MDE (relative):   1.0%  (from metrics/checkout_completion_rate.yaml)
     power / alpha:    80% / 0.05
     n_required:       1,196,603 per arm

   Assignment surface (from Stage 0 profile):
     eligible users:   47,213
     n_per_arm @ 50/50: 23,606

   At your current surface size of n=23,606 per arm, the smallest
   relative lift you could detect at 80% power is ~22%. Your brief
   claims to detect a 1.0% relative lift. The experiment would
   ship a NULL result with ~98% probability regardless of whether
   the treatment actually works.

   Two paths:

   1. Widen the MDE in metrics/checkout_completion_rate.yaml
      (set mde_default_pct: 22.0 or larger).
   2. Expand the assignment surface — connect a larger warehouse,
      or change the eligibility filter to include more users.

   The brief is NOT sealed. Edit and re-run /experiment design.
```

- **Owner persona:** Thesis-keeper §2.6 (revised per audit-supplement §2.E); Warehouse-engineer §2.2; Product-UX §4.7 (refusal copy).
- **Inputs:** W3.3, W2.4, W2.6 (EXPERIMENTS.md feasibility table).
- **Outputs:** Brief refuses underpowered commits at 1.0×.
- **Acceptance criteria:**
  - Synthetic brief with `n_required = 1.2M, available = 3K` → refused with literal message.
  - Brief with `n_required = 5,500, available_per_arm = 5,000` → refused (1.0× strict).
  - Brief with `n_required = 5,000, available_per_arm = 5,000` → committed.
  - No `--force` flag exists.
  - E_UNDER_001 and E_NOVELTY_001 ship with widened-MDE briefs that pass the check (per audit-supplement §2.C).
- **Depends on:** W3.3, W2.4, W2.6.

#### Task W3.5 — Two-state-lifecycle implementation (debate §2.3)

- **File paths:** `agentxp/orchestrator/store.py` (`_commit_stage` enforces terminal-per-lifecycle), `agentxp/cli/experiment.py` (sub-verb dispatcher), `tests/orchestrator/test_two_state_lifecycles.py` (NEW).
- **What it does:** Implements the bridge mechanism per thesis-keeper §1.3:

- Design experiment (`experiments/<design_exp_id>/`) → Stage 0–4. Stage 4 commit writes `briefs/<exp_id>.yaml` (W3.3 schema) and flips `state.yaml.terminal=true`.
- Analyze experiment (`experiments/<analyze_exp_id>/`) is a new dir with its own `state.yaml` and `log.jsonl`. First event: `stage.entered(stage=monitor, parent_action_id=None)` — new root.
- Analyze state.yaml has `design_ref: DesignRef` pointing back. First bundle's `source_hashes` includes the brief's content hash (this is the load-bearing link for audit replay).
- Stage 8 commit flips analyze `terminal=true`.

`_commit_stage` enforces: `terminal=true` only set as side-effect of final-stage commit per lifecycle (Stage 4 for design, Stage 8 for analyze); never settable from CLI.

Inline assignment_spec enforcement (audit I6): if `assignment_spec` points to `_inline_*.yaml`, suffix must match `Brief.experiment_id`. Mismatch → refusal.

- **Owner persona:** Orchestrator-engineer §1.3; Thesis-keeper §1.3.
- **Inputs:** W3.3, W0.14, W2.5.
- **Outputs:** Two experiment dirs on disk per logical experiment; chain replay walks both via `DesignRef.brief_chain_hash`.
- **Acceptance criteria:** `test_two_state_lifecycles` — design experiment terminates at Stage 4; analyze experiment opens with `design_ref`; analyze terminates at Stage 8; `validate_chain` is clean on both; cross-chain replay reads brief content hash from `bundles[0].source_hashes`. Inline assignment suffix mismatch refused at brief-commit.
- **Depends on:** W3.3, W0.14, W2.5.

---

### §3.4 Wave 4 — Atomic surface flip + docs + CSV delete (THE ATOMIC PR)

**Goal:** Flip the user-facing surface. One atomic merge. All matching docs in the same PR. CSV fixtures clean-deleted.

**Ships SURFACE FLIP.** Lands as **one atomic PR**.

**Parallelism notes:** All W4 tasks are part of a single PR — work concurrently in branches, merge to a single integration branch, ship as one PR. Internally, W4.1 (flag flip) must be the last commit before merge. W4.6 (CLAUDE.md §1) must land verbatim from Product-UX §3. W4.9 (per-module docs) is the largest line-count piece; can be split across multiple drafters but lands in the same PR.

**Tasks:**

#### Task W4.1 — Flip `SURFACE_V01_ENABLED` to True (default)

- **File paths:** `agentxp/_flags.py`.
- **What it does:** Removes the env-var-read conditional; the flag is now unconditionally True. (Or: keep the env var as an emergency-kill-switch and default to `"1"`. Synthesis recommendation: remove the conditional entirely — feature flags that linger become tech debt.)
- **Owner persona:** Orchestrator-engineer §1.1.
- **Inputs:** All W0–W3 tasks complete and tested.
- **Outputs:** Surface flipped.
- **Acceptance criteria:** Fresh-clone user without any env vars sees the new surface.
- **Depends on:** W0–W3 complete.

#### Task W4.2 — Delete 8 sample-data CSVs (Shane decision 4)

- **File paths:** Delete `sample-data/ship_demo.csv`, `sample-data/clean_ab.csv`, plus the other 6 CSV fixtures listed in the architect brief. Update `sample-data/README.md` to point at `agentxp_demo.duckdb` and `EXPERIMENTS.md`.
- **What it does:** Clean delete. No DEPRECATED banner.

The CSV *adapter* as a product feature persists (audit-supplement §2.H). It's taught via a 3-row synthetic CSV in `walkthroughs/data-connectors.md` (W4.8 below).

- **Owner persona:** Product-UX §4.5; Warehouse-engineer §0.
- **Inputs:** W2.1 (warehouse fixture exists as replacement).
- **Outputs:** Cleaner `sample-data/`.
- **Acceptance criteria:** Filesystem assertion; `sample-data/` contains only `agentxp_demo.duckdb`, `EXPERIMENTS.md`, `SEED.yaml`, `fixture.lock.yaml`, and `seeds/` (generator scripts).
- **Depends on:** W2.1.

#### Task W4.3 — Rewrite `.claude/commands/experiment.md` for sub-verbs

- **File paths:** `.claude/commands/experiment.md`.
- **What it does:** Replaces the single-verb shape with sub-verb routing:

```
- /experiment design                    Design a new experiment (Stages 0-4)
- /experiment analyze --brief <path>    Analyze a populated experiment (Stages 5-8)
- /experiment resume <exp_id>           Resume an interrupted experiment
```

Help text carries the "designing AFTER results is the failure mode this tool exists to prevent" paragraph.

- **Owner persona:** Product-UX §1.
- **Inputs:** W3 complete (backend supports the routing).
- **Outputs:** Sub-verb-capable slash command.
- **Acceptance criteria:** `/experiment design`, `/experiment analyze`, `/experiment resume` all dispatch correctly.
- **Depends on:** W3.

#### Task W4.4 — Rewrite `.claude/skills/experiment/SKILL.md`

- **File paths:** `.claude/skills/experiment/SKILL.md`.
- **What it does:** Per Product-UX + Orchestrator-engineer: inline-mode is v0.1 path; API path is Phase 5 only; sub-verbs design/analyze. Teaches the skill how to play each agent's role inside the slash command. References `dispatch_agent(inline_output=...)` as the canonical invocation.
- **Owner persona:** Product-UX §1 + §4.
- **Inputs:** W3.
- **Outputs:** Skill that knows the new shape.
- **Acceptance criteria:** Following the SKILL.md prose verbatim leads to a working `/experiment design` → seal → `/experiment analyze` flow against E_F12345.
- **Depends on:** W3.

#### Task W4.5 — Rewrite `.claude/skills/experiment/STAGES.md` per-stage prose (debate §4.3)

- **File paths:** `.claude/skills/experiment/STAGES_DESIGN.md` (NEW or rewritten), `.claude/skills/experiment/STAGES_ANALYZE.md` (NEW).
- **What it does:** Per Product-UX §8.1 ownership: Product-UX writes the per-stage harness-instructions prose; Curriculum-maintainer reviews each stage spec against the corresponding module's four-beat (Stage 0 ↔ Module 1; Stage 4 ↔ Module 1+4; Stage 6 ↔ Module 5; Stage 8 ↔ Module 10).

Stage 0 prose includes the literal scaffolding screen from Product-UX §4.2 ("🆕 Starting design for experiment exp_005..."). Stage 4 prose includes the brief integrity lock and power-feasibility refusal flow. Stage 5 prose includes the brief-binding check.

- **Owner persona:** Product-UX (writes); Curriculum-maintainer (reviews).
- **Inputs:** W3, W4.4.
- **Outputs:** Per-stage prose docs.
- **Acceptance criteria:** Four-beat alignment confirmed by Curriculum-maintainer review. Stage 0 screen matches Product-UX §4.2 literal mockup.
- **Depends on:** W3, W4.4.

#### Task W4.6 — Rewrite root `CLAUDE.md` §1 (Product-UX literal three sentences)

- **File paths:** `CLAUDE.md` (project root) §1.
- **What it does:** Replaces §1 with Product-UX §3 literal:

> AgentXP is an open-source agentic experimentation system you run inside Claude Code — no API key, no server, no separate process. There are two commands: `/experiment design` to design a new experiment against your warehouse and seal a brief, and `/experiment analyze --brief <path>` to analyze a populated experiment whose data has landed. Eleven stages, thirteen agents, and a sealed audit chain run *underneath* those two commands — you never need to know a stage number to use the tool, and you should never tell the user a stage number unless they ask.

§2 entry-point block per Product-UX §5:

```
- /experiment design                    Design a new experiment (Stages 0-4)
- /experiment analyze --brief <path>    Analyze a populated experiment (Stages 5-8)
- /experiment resume <exp_id>           Resume an interrupted experiment
- /connect-data <warehouse>             Wire a warehouse connection
- /audit <exp_id>                       Replay the decision chain
- /list                                 Show experiments in this project
- /unlock <exp_id> --reason "<why>"     Force-release a stale state lock
- /prune                                Clean up orphan experiments
```

`agentxp migrate-state` listed in §4 Python CLI section (not slash command).

§G/§S clarifications per audit-supplement §3.2: brief paragraph documenting `LastActionMetadata` fields and `data_plan.yaml` draft→confirmed lifecycle.

- **Owner persona:** Product-UX §3 + §5; partial §G/§S from audit-supplement §3.2.
- **Inputs:** W4.1.
- **Outputs:** Root CLAUDE.md reflects the new surface.
- **Acceptance criteria:** §1, §2, §4 prose matches Product-UX literals.
- **Depends on:** W4.1.

#### Task W4.7 — Rewrite `docs/QUICKSTART.md` + `docs/USER_JOURNEYS.md`

- **File paths:** `docs/QUICKSTART.md` (lines 9, 29, 39, 48, 148–149 per curriculum-maintainer §4 table), `docs/USER_JOURNEYS.md` (lines 118, 119, 127, 146, 194, 214, 305, 462).
- **What it does:** Retargets to design/analyze sub-verb shape. `ls sample-data/` → `ls sample-data/agentxp_demo.duckdb`. No CSV paths surface in QUICKSTART.

USER_JOURNEYS §11 (gap register) updates: G17 resolved (journey conflation), G6 partial-strike (`dispatch_sql` half), G18 added (orphan v1 metric YAMLs → no `migrate-metrics` verb in v0.1).

- **Owner persona:** Curriculum-maintainer §4 (file:line precision); Product-UX (review).
- **Inputs:** W4.1–W4.6.
- **Outputs:** Updated docs.
- **Acceptance criteria:** Per-line diffs match curriculum-maintainer §4 table; no CSV path references remain.
- **Depends on:** W4.1–W4.6.

#### Task W4.8 — Rewrite walkthroughs

- **File paths:**
  - `walkthroughs/your-first-experiment.md` (becomes meta walkthrough, ≤120 lines)
  - `walkthroughs/pre-registration.md` (becomes design walkthrough; adds power-check section with literal Product-UX §4.7 refusal example)
  - `walkthroughs/monitoring.md` → rename to `walkthroughs/analyze.md` (covers Stages 5–8)
  - `walkthroughs/state-machine.md` (light touch — adds state migration verb section referencing `agentxp migrate-state`)
  - `walkthroughs/data-connectors.md` (ships with 3-row synthetic CSV per audit-supplement §2.H)
- **What it does:** Walkthroughs collapse per debate consensus + curriculum-maintainer §4 table. `monitoring.md` rename happens in the same PR (not a Wave-5 follow-up).
- **Owner persona:** Curriculum-maintainer §4.
- **Inputs:** W4.1–W4.7.
- **Outputs:** Five updated walkthroughs.
- **Acceptance criteria:** All five walkthroughs follow the new sub-verb shape; data-connectors has a working 3-row CSV example; pre-registration has a power-check section with the literal refusal example.
- **Depends on:** W4.1–W4.7.

#### Task W4.9 — Per-module curriculum doc updates (Modules 0–10) per change matrix

- **File paths:** `docs/learn/00_thesis.md` (CSV refs at 00:85, 00:117, 00:121), `docs/learn/01_shape.md` (largest single rewrite; Lab 1a → design 0→4 + analyze 5→8 against E_F12345; adds design-time power-check beat at Lab 1a; line 123 drops CSV path → experiment_id), `docs/learn/02_agents.md` (line 02:157 word fix; adds "How agents get called in v0.1" sub-section teaching `agent.dispatched(subtype="inline")` — NOT new EventName), `docs/learn/03_deterministic_core.md` (line 03:226 CSV table → 8 experiment_ids; NEW null-input refusal sub-section per B5; Module 10 RenderStatus back-reference; Lab 3b adds 9th row E_F12345 with null late_ratio → UNVERIFIABLE; NEW analyzer test whitelist sub-section per B6; Lab 3a adds refusal-not-substitution drill), `docs/learn/04_integrity_spine.md` (aha #3 extension; new chain-event sub-section teaching `agent.dispatched(subtype="inline")` — closure-at-13 framing; Walkthrough §1 grows "five → six chain invariants" teaching Invariant 6; Lab 4a third drill — drop dispatch pair, watch Invariant 6 fire; locked-rule wall gains migration paragraph for `agentxp migrate-state`), `docs/learn/05_data_plumbing.md` (dispatch_sql stub → live path; DuckDB adapter demo against agentxp_demo.duckdb; G4/I5 two-paragraph addition on `LastActionMetadata` and draft→confirmed lifecycle per audit-supplement §3.2), `docs/learn/06_state_stores_resume.md` (Lab 6a doubles to design-mode vs analyze-mode crash; NEW `agentxp migrate-state` paragraph), `docs/learn/07_build_history_judgment.md` (07:92 and 07:165 dispatch_sql rewrites; design/analyze split as judgment artifact), `docs/learn/08_capstone.md` (gauntlet rewrites land in W5), `docs/learn/09_extend.md` (journey-split blast-radius as worked example), `docs/learn/10_presentation.md` (NEW RenderStatus sub-section back-references Module 3; numeric pins re-verified post-W4 against synthetic exp_001 — body unchanged).
- **What it does:** Per curriculum-maintainer §4 change matrix (file:line precision).
- **Owner persona:** Curriculum-maintainer §4.
- **Inputs:** W4.1–W4.8.
- **Outputs:** All learner-facing docs aligned with the new surface.
- **Acceptance criteria:** Each module's four-beat (Why / Walkthrough / Lab / Teach-back) preserved. Module 0 thesis untouched in framing. Module 4 carries the new Invariant 6 teaching. Module 10 body unchanged.
- **Depends on:** W4.1–W4.8.

#### Task W4.10 — Muscle-memory refusal for old `--data <csv>` path

- **File paths:** `agentxp/cli/experiment.py` (the sub-verb dispatcher detects the old shape and refuses).
- **What it does:** Per Product-UX §9 literal refusal message:

```
> /experiment design --data sample-data/ship_demo.csv

Refused: /experiment design profiles your warehouse, not a results file.

What you passed (sample-data/ship_demo.csv) looks like results data —
it has a `variant` column. Designing AFTER results are in is the
failure mode this tool exists to prevent: the threshold gets set
wherever the result landed, and the verdict becomes a story you tell
about a number you already saw.

Two paths forward:

  1. You have a locked brief already:
       /experiment analyze --brief briefs/<id>.yaml --experiment-id <id>

  2. You don't:
       /experiment design
     (no --data flag — Stage 0 profiles the connected warehouse and
      walks you to a sealed brief BEFORE results are queried)

For reference: sample-data/ship_demo.csv was removed in v0.1. The
canonical SHIP scenario lives at E_F12345 inside agentxp_demo.duckdb
with a pre-sealed brief at briefs/E_F12345.yaml:

  /experiment analyze --brief briefs/E_F12345.yaml --experiment-id E_F12345
```

Also: `agentxp profile sample-data/...csv` refusal per Product-UX §4.5 literal message.

- **Owner persona:** Product-UX §4.5 + §9.
- **Inputs:** W4.1.
- **Outputs:** Refusal that names *why* design-after-results is the failure mode, in the user's voice.
- **Acceptance criteria:** Synthetic `/experiment design --data <path>` → refusal with literal message. `agentxp profile <csv>` → refusal with literal message.
- **Depends on:** W4.1.

---

### §3.5 Wave 5 — Gauntlet rewrites + trace.md audit (1-week post-W4)

**Goal:** Post-cleanup polish. Module 8 gauntlet rewrite, trace.md re-walk against shipped warehouse, README updates, SYSTEM_AUDIT.md §11 final entries.

**Ships docs only.** Multiple PRs OK. Lands within 1 week of W4.

**Parallelism notes:** All four tasks independent.

**Tasks:**

#### Task W5.1 — Module 8 gauntlet 18 → 21 questions

- **File paths:** `docs/learn/08_capstone.md`.
- **What it does:** Per curriculum-maintainer §3 + §4 table: Q4 split into Q4a/Q4b/Q4c (+2 from 18 → 20); new Q7b on design-time power-check determinism (+1 → 21). Q13 gains B6 example (p95→mean silent sub). Q16 gains "schema migration is a verb, not auto." Q4d (underpowered refusal) folds into Q4c.

Q7b (literal from curriculum-maintainer §3):
> The design-time power check refuses an underpowered brief before commit. Why is *that* check deterministic and refused-at-brief-time rather than monitor-time? A reviewer says, "let the model decide if 3K is enough — sometimes a directionally clear signal is fine." Defend the design-time refusal stance.

- **Owner persona:** Curriculum-maintainer §3 + §4.
- **Inputs:** W4 shipped.
- **Outputs:** 21-question gauntlet.
- **Acceptance criteria:** Question count is 21; each new question has model-answer + hostile-reviewer framing.
- **Depends on:** W4.

#### Task W5.2 — trace.md numeric audit

- **File paths:** `docs/learn/trace.md` (lines 12–13, 22, 26, 27, 30, 52, 53, 57, 59, 65, 67, 72, 85, 88, 95, 104–121, 128, 132).
- **What it does:** Verifies every canonical number reproduces against the shipped warehouse. Specifically: 314 control conv, 384 treatment conv, 0.1047 control rate, 0.1280 treatment rate, +0.0233 absolute, +22.3% relative, n=3000/arm.

Per curriculum-maintainer §6: "**Warehouse seed must reproduce 314/384/n=3000. Acceptable variance: zero.**"

Splits trace.md into design-half (Stages 0–3) and analyze-half (Stages 5–8). Path gains 2 hops (SQL query writer → dispatch_sql → analyzer).

- **Owner persona:** Curriculum-maintainer §6.
- **Inputs:** W4 shipped, W2.1 warehouse.
- **Outputs:** trace.md numerically faithful to shipped warehouse.
- **Acceptance criteria:** Each pinned number verified by running the analyzer's SQL against E_F12345 in the shipped warehouse. Zero drift.
- **Depends on:** W4.

#### Task W5.3 — `docs/learn/README.md` updates

- **File paths:** `docs/learn/README.md` (module map row 1; aha-index note; fixture cheat-sheet — line 128 specifically).
- **What it does:** Fixture cheat-sheet rewrite (8 CSVs → 8 experiment_ids). Aha-index clarifying paragraphs for #2 (priority-ranking AND null-input halt), #3 (existence on disk IS the lock, with closure-at-13 + migration-as-verb extensions), #4 (recoverable direction AND which mode to resume), #5 (analyzer test whitelist + p95 case).
- **Owner persona:** Curriculum-maintainer §4.
- **Inputs:** W4 shipped.
- **Outputs:** Updated README.
- **Acceptance criteria:** Fixture cheat-sheet matches `sample-data/EXPERIMENTS.md`; aha-index reads cleanly with the four extensions.
- **Depends on:** W4.

#### Task W5.4 — `docs/SYSTEM_AUDIT.md` §11 (gap register) update

- **File paths:** `docs/SYSTEM_AUDIT.md` (§11 specifically).
- **What it does:** Per curriculum-maintainer §4 + §5: G17 resolved (journey conflation); G6 half-struck (`dispatch_sql` portion); G18 added (orphan v1 metric YAMLs → no `migrate-metrics` verb in v0.1, deferred to v0.1→v0.2); G19 added ("result_hash content-faithfulness silent break — fixed Wave 0").
- **Owner persona:** Curriculum-maintainer §4.
- **Inputs:** W4 shipped.
- **Outputs:** Final gap register.
- **Acceptance criteria:** §11 reflects all four entries.
- **Depends on:** W4.

---

## §4 Dependency Graph

```
┌─────────────────────────────────────────────────────────────────────┐
│                          SURFACE_V01_ENABLED = False                │
│                          (Waves 0–3 ship dark)                      │
└─────────────────────────────────────────────────────────────────────┘

Wave 0 — Schema + hygiene foundations
═══════════════════════════════════════════
    [W0.1 Sha256Hex]──┬──>[W0.3 EventMetadataSubtype]──>[W0.4 Invariant 6]
                      │                  │
                      ├──>[W0.7 LastActionMetadata]
                      │                  ↑
                      └──>[W0.13 schemas (I1-I5, Brief, DesignRef)]
                                         ↑
    [W0.5 StateYaml v4 + migrate-state]──┘
                      │
                      ├──>[W0.14 bootstrap_experiment + allocate]
                      │                  │
                      │                  ├──>[W0.15 recovery + unlock]
                      │                  │                  │
                      │                  │                  ├──>[W0.16 prune]
                      │                  │
                      │                  └──>[W0.17 agentxp new]
                      │
    [W0.2 _flags.py]──┘   (independent: W0.6 exp_id sweep, W0.8 ulid dep,
                            W0.9 orphan YAML delete, W0.10 VoiceRule tier,
                            W0.11 VerdictKind 9, W0.12 FactSource split)

Wave 1 — SQL chokepoint wiring + result_hash
══════════════════════════════════════════════
    [W1.1 dispatch_sql store wrapper]──┬──>[W1.3 DuckDB adapter]
                                       └──>[W1.4 parquet emission]

    [W1.2 canonical_result_hash]   (independent)
    [W1.5 SupportedTestType + registry] ← depends on W0.13
    [W1.6 walk_tree refactor]           ← depends on W0.11

Wave 2 — Warehouse fixture
════════════════════════════
    [W2.1 generate warehouse]──┬──>[W2.2 six tables]
                               ├──>[W2.6 EXPERIMENTS.md]
                               ├──>[W2.7 fixture.lock.yaml] ← W1.2
                               └──>[W2.8 regen test bundles] ← W1.2

    [W2.3 semantic_models] ← W0.1, W0.12, W2.2
    [W2.4 metrics/*.yaml]  ← W0.13, W1.5, W2.2
    [W2.5 assignments/README.md] (standalone doc; enforcement in W3.5)

Wave 3 — Inline-mode dispatch + brief integrity
═════════════════════════════════════════════════
    [W3.1 dispatch_agent inline]──>[W3.2 inline_raw_sha256]
                  ↑ W0.1, W0.3, W0.14

    [W3.3 brief integrity lock]──>[W3.4 power-feasibility refusal]
                  ↑ W0.13, W2.4              ↑ W2.6 EXPERIMENTS.md

    [W3.5 two-state lifecycles]
                  ↑ W3.3, W0.14, W2.5

┌─────────────────────────────────────────────────────────────────────┐
│  Wave 4 — ATOMIC SURFACE FLIP (one PR, all tasks together)          │
│                                                                      │
│  [W4.1 flip flag] [W4.2 delete CSVs] [W4.3 experiment.md sub-verbs] │
│  [W4.4 SKILL.md] [W4.5 STAGES.md] [W4.6 CLAUDE.md §1-§4]            │
│  [W4.7 QUICKSTART + USER_JOURNEYS] [W4.8 walkthroughs collapse]     │
│  [W4.9 per-module 0-10 curriculum] [W4.10 muscle-memory refusal]    │
│                                                                      │
│  All depend on W0-W3 complete and tested.                            │
└─────────────────────────────────────────────────────────────────────┘

                           SURFACE_V01_ENABLED = True
                           (Wave 4 atomic merge)

Wave 5 — Polish (1-week post-W4, multiple small PRs)
══════════════════════════════════════════════════════
    [W5.1 gauntlet 18→21]  [W5.2 trace.md re-walk]
    [W5.3 README updates]  [W5.4 SYSTEM_AUDIT §11]
```

Critical path through the waves:
W0.1 → W0.13 → W2.4 → W3.3 → W3.4 → W4 (atomic). Plus W2.1 → W2.8 → W4. Plus W0.5 → W0.14 → W0.15 / W0.16 / W0.17 → W4 (via W4.6 CLAUDE.md §2).

---

## §5 Files Changed Summary

| Wave | File | Change | Description |
|---|---|---|---|
| W0 | `agentxp/schemas/_types.py` | created | `Sha256Hex` type alias |
| W0 | `agentxp/_flags.py` | created | `SURFACE_V01_ENABLED` feature flag |
| W0 | `agentxp/audit/events.py` | modified | Extend `EventMetadataSubtype` Literal |
| W0 | `agentxp/audit/chain.py` | modified | Add Invariant 6; `ChainValidation` tertiary state |
| W0 | `agentxp/schemas/state.py` | modified | StateYaml v4 with `terminal`/`design_ref`; `LastActionMetadata` |
| W0 | `agentxp/cli/migrate_state.py` | created | `agentxp migrate-state` verb |
| W0 | `agentxp/orchestrator/migrate.py` | created | Migration logic |
| W0 | `agentxp/schemas/data_plan.py` | modified | `Sha256Hex` on fingerprint fields; status-gated validator |
| W0 | `agentxp/schemas/semantic_model.py` | modified | `Sha256Hex`; `kind: fact|dimension` |
| W0 | `agentxp/schemas/brief.py` | created | `Brief`, `ExpectedShape` |
| W0 | `agentxp/schemas/design_ref.py` | created | `DesignRef` |
| W0 | `agentxp/schemas/fact_source.py` | modified | Discriminated union: `FactSource` vs `SnapshotFactSource` |
| W0 | `agentxp/schemas/metric.py` | modified | Three-slot XOR MDE; `SupportedTestType` |
| W0 | `agentxp/schemas/experiment.py` | modified | Hypothesis: 2-slot XOR magnitude; drop `predicted_direction`; keep `predicted_lift_sign` |
| W0 | `agentxp/schemas/report.py` | modified | `ConfidenceLabel` enum; `CONFIDENCE_DISPLAY` map |
| W0 | `agentxp/schemas/voice_rule.py` | modified | `enforcement: Literal["halt", "warn"]` |
| W0 | `agentxp/voice/audit.py` | modified | Tiered driver; no override |
| W0 | `agentxp/schemas/verdict.py` | modified | `VerdictKind` 8 → 9 (`UNVERIFIABLE`) |
| W0 | `agentxp/finalize.py` | modified | `exp_id` → `experiment_id` sweep |
| W0 | `agentxp/orchestrator/store.py` | modified | `bootstrap_experiment` method |
| W0 | `agentxp/orchestrator/allocate.py` | created | `allocate_experiment_id` |
| W0 | `agentxp/recovery/__init__.py` | created | Recovery namespace |
| W0 | `agentxp/recovery/cli.py` | created | `commit-stage` under `python3 -m agentxp.recovery` |
| W0 | `agentxp/cli/unlock.py` | created | `agentxp unlock --reason` |
| W0 | `agentxp/cli/list.py` | modified | Lock column + `🔒` prefix; orphan status |
| W0 | `agentxp/cli/audit.py` | modified | Lock block when locked |
| W0 | `agentxp/cli/prune.py` | created | `agentxp prune` |
| W0 | `agentxp/cli/new.py` | created | `agentxp new` |
| W0 | `pyproject.toml` | modified | Add `python-ulid>=2.2,<3.0` |
| W0 | `metrics/bounce_rate.yaml` | deleted | Orphan v1 |
| W0 | `metrics/checkout_completion_rate.yaml` | deleted | Orphan v1 |
| W0 | `metrics/d7_retention.yaml` | deleted | Orphan v1 |
| W0 | `metrics/revenue_per_session.yaml` | deleted | Orphan v1 |
| W0 | `metrics/session_revenue.yaml` | deleted | Orphan v1 |
| W0 | `agentxp/verdict/walk_tree.py` | modified | Null-input refusal; UNVERIFIABLE returned |
| W0 | Multiple test files | created | Closure + behavior tests |
| W1 | `agentxp/orchestrator/store.py` | modified | `dispatch_sql` store wrapper at :929 |
| W1 | `agentxp/sql/_hashing.py` | created | `canonical_result_hash` |
| W1 | `agentxp/sql/dispatch.py` | modified | `_emit_executed` uses canonical hash |
| W1 | `agentxp/sql/adapters/duckdb.py` | created | DuckDB adapter |
| W1 | `agentxp/sql/artifact_writer.py` | modified | Parquet emission |
| W1 | `agentxp/analyzer/registry.py` | created | `SUPPORTED_TESTS` registry |
| W1 | Multiple test files | created | Order-invariance, pinned-hash, registry-mirror tests |
| W2 | `agentxp/fixtures/generate_demo_warehouse.py` | created | Deterministic generator |
| W2 | `sample-data/SEED.yaml` | created | Seed contract |
| W2 | `sample-data/agentxp_demo.duckdb` | created | Generated warehouse |
| W2 | `sample-data/EXPERIMENTS.md` | created | 8-row table + how-to-use |
| W2 | `sample-data/fixture.lock.yaml` | created | CI dam |
| W2 | `agentxp/fixtures/lock.py` | created | Content-hash logic |
| W2 | `semantic_models/users.yaml` | created | Dimension |
| W2 | `semantic_models/experiments.yaml` | created | Dimension |
| W2 | `semantic_models/assignments.yaml` | created | Fact |
| W2 | `semantic_models/sessions.yaml` | created | Fact |
| W2 | `semantic_models/orders.yaml` | created | Fact |
| W2 | `semantic_models/page_events.yaml` | created | Fact |
| W2 | `metrics/conversion_rate.yaml` | created | v2 schema, three-slot MDE |
| W2 | `metrics/revenue_per_user.yaml` | created | v2 schema |
| W2 | `metrics/total_revenue.yaml` | created | v2 schema |
| W2 | `metrics/session_count.yaml` | created | v2 schema |
| W2 | `metrics/page_load_p95.yaml` | created | v2 schema, type=p95 |
| W2 | `metrics/late_ratio.yaml` | created | v2 schema |
| W2 | `metrics/conversion_rate_widened.yaml` | created | For E_UNDER_001 / E_NOVELTY_001 briefs |
| W2 | `assignments/README.md` | created | Underscore convention |
| W2 | `connections/agentxp_demo.yaml` | created | DuckDB connection config |
| W2 | `tests/render/fixtures/bundles_ship/*` | regenerated | From synthetic `exp_001` |
| W2 | `scripts/regen_test_bundles.py` | created | Two-path regenerator |
| W3 | `agentxp/orchestrator/store.py` | modified | `dispatch_agent` inline branch; `_commit_stage` terminal-per-lifecycle |
| W3 | `agentxp/orchestrator/brief_validation.py` | created | `_check_brief_bindings`; `_check_power_feasibility` |
| W3 | `agentxp/stats/power.py` | created/modified | `compute_n_required`; allocation-aware denominator |
| W3 | `briefs/E_F12345.yaml` | created | Pre-sealed brief for the SHIP-anchor walkthrough |
| W3 | `briefs/E_*.yaml` | created (8 total) | Pre-sealed briefs for each scenario |
| W3 | Multiple test files | created | Inline-mode, brief-binding, power-feasibility, two-state-lifecycle |
| W4 | `agentxp/_flags.py` | modified | Flag flipped (or removed) |
| W4 | `sample-data/ship_demo.csv` | deleted | CSV cleanup |
| W4 | `sample-data/clean_ab.csv` | deleted | CSV cleanup |
| W4 | `sample-data/*.csv` (6 more) | deleted | CSV cleanup |
| W4 | `sample-data/README.md` | modified | Points at `agentxp_demo.duckdb` |
| W4 | `.claude/commands/experiment.md` | rewritten | Sub-verbs |
| W4 | `.claude/skills/experiment/SKILL.md` | rewritten | Inline-mode v0.1 path; sub-verbs |
| W4 | `.claude/skills/experiment/STAGES_DESIGN.md` | created/rewritten | Per-stage prose for design |
| W4 | `.claude/skills/experiment/STAGES_ANALYZE.md` | created | Per-stage prose for analyze |
| W4 | `CLAUDE.md` | modified | §1, §2, §4 rewritten; §G/§S clarifications |
| W4 | `docs/QUICKSTART.md` | modified | Sub-verb shape; no CSV paths |
| W4 | `docs/USER_JOURNEYS.md` | modified | Per-line per curriculum-maintainer §4 table; §11 G17/G6/G18 |
| W4 | `walkthroughs/your-first-experiment.md` | rewritten | Meta walkthrough, ≤120 lines |
| W4 | `walkthroughs/pre-registration.md` | rewritten | Design walkthrough + power-check |
| W4 | `walkthroughs/monitoring.md` | renamed → `analyze.md` | Analyze flow |
| W4 | `walkthroughs/state-machine.md` | modified | Adds `agentxp migrate-state` paragraph |
| W4 | `walkthroughs/data-connectors.md` | modified | 3-row synthetic CSV |
| W4 | `docs/learn/00_thesis.md` | modified | Three CSV refs at 00:85, 00:117, 00:121 |
| W4 | `docs/learn/01_shape.md` | modified | Lab 1a design+analyze; power-check beat; line 123 |
| W4 | `docs/learn/02_agents.md` | modified | Line 02:157; inline-dispatch teaching |
| W4 | `docs/learn/03_deterministic_core.md` | modified | B5 null-input + B6 whitelist sub-sections; Lab 3a/3b extensions |
| W4 | `docs/learn/04_integrity_spine.md` | modified | Invariant 6; inline-subtype; migration-verb |
| W4 | `docs/learn/05_data_plumbing.md` | modified | dispatch_sql live; G4/I5 paragraphs |
| W4 | `docs/learn/06_state_stores_resume.md` | modified | Lab 6a doubling; migrate-state |
| W4 | `docs/learn/07_build_history_judgment.md` | modified | dispatch_sql passages |
| W4 | `docs/learn/09_extend.md` | modified | Journey-split blast-radius |
| W4 | `docs/learn/10_presentation.md` | modified | RenderStatus back-reference (body unchanged) |
| W4 | `OVER_ENGINEERING_REVIEW.md` | modified | Line 12 dispatch_sql edit |
| W4 | `agentxp/cli/experiment.py` | modified | Sub-verb dispatcher; muscle-memory refusal |
| W5 | `docs/learn/08_capstone.md` | modified | Gauntlet 18 → 21 |
| W5 | `docs/learn/trace.md` | modified | Numeric re-walk; split into design-half + analyze-half |
| W5 | `docs/learn/README.md` | modified | Aha-index, module-map, fixture cheat-sheet |
| W5 | `docs/SYSTEM_AUDIT.md` | modified | §11 G17 resolved, G6 half-struck, G18 + G19 added |

---

## §6 Open Questions

**All conflicts resolved through Phases 1–2b. The plan is execution-ready.**

The five Round 2 persona plans, the original debate summary, the audit supplement, and Shane's six binding decisions together resolve every cross-persona conflict and assign every audit finding an owner. The audit-supplement closed the five real cross-persona calls (inline raw text, commit-stage surface, underpowered flag, Verdict 8→9, power threshold) with reasoning, and confirmed the minor surfaces (naming, wave/walkthrough/anchor coexistence, voice tiers, event placement).

Two items remain *available* for Shane's strategic preference, both already resolved technically:

- **Power-feasibility threshold (1.0× strict vs 1.5× buffered):** Resolved to 1.0× strict per Shane decision 5. If Shane revisits, single-line change in W3.4.
- **`agentxp.recovery commit-stage` (internal namespace vs fully removed):** Resolved to internal namespace per Shane decision 6 + audit-supplement §2.B. If Shane revisits, defer the namespace to v0.2 and rewrite headless integration tests to drive the slash command from a harness.

Neither blocks execution.

---

## Closing — Definition of Done

- All Wave 0 schema changes land with closure tests green (EventName at 13, VerdictKind at 9, Sha256Hex closure, Invariant 6 enforced).
- Wave 1 `dispatch_sql` runs end-to-end against DuckDB with content-faithful `result_hash` and order-invariance test green.
- Wave 2 `agentxp_demo.duckdb` reproduces E_F12345 = 314/384/+22.3% byte-for-byte; `fixture.lock.yaml` content_hash stable across regeneration.
- Wave 3 `dispatch_agent` inline-mode emits the atomic dispatched/completed pair with `inline_raw_sha256`; `validate_brief_for_commit` refuses underpowered briefs at 1.0× strict; two-state lifecycles work end-to-end.
- Wave 4 atomic PR: a fresh-clone user with `pip install agentxp` runs `/experiment analyze --brief briefs/E_F12345.yaml --experiment-id E_F12345` and receives SHIP + 22.3% lift + clean audit chain. No API key. No CSVs. No NotImplementedError. No `<pending>` literals. No silent test substitution. No null-input passes. No underpowered briefs.
- Wave 5 (1-week post-W4): gauntlet at 21 questions; trace.md numerically faithful; SYSTEM_AUDIT §11 final.

The thesis — *deterministic Python owns the statistics; an LLM owns the judgment; and the judgment is structurally sealed off from the result* — survives intact. The audit revealed silent holes in the spine; this cleanup closes them by name.
