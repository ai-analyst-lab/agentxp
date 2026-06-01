# agentxp Presentation / Shareable-Output Layer — Master Plan

**Status:** Approved synthesis (Round 2 → final)
**Date:** 2026-05-31
**Synthesized from:** `working/plans/debate-summary.md` + five Round 2 persona plans (Render Architect, Brand & Editorial Designer, Integrity/Trust Engineer, Integrations & Destinations, Operator/DX Advocate)
**Architectural frame (non-negotiable):** `report.json` is the single source of truth. Every output is a PURE renderer over it (add a format = add a renderer, never re-derive a number). No renderer touches a warehouse, the audit log, an LLM, `experiment.yaml`, or numpy. Numbers are formatted exactly once, in `distill()`. Local-first ships before any API destination; a publish failure never blocks or corrupts a local run.

---

## 1. Executive Summary

We are building a **shareable-output layer** for agentxp so that the deterministic verdict in `report.json` can be read, shared, and trusted in more than one shape — without ever re-deriving a number or letting an LLM near the result.

**The one-verb thesis.** One new CLI verb, `agentxp report <id> --format glance|md|html|card`, mirrors the existing `agentxp audit` exactly (same flags, exit codes, atomic chmod-600 write). Default resolution: interactive terminal → `glance` (one-screen verdict-first read); pipe/redirect → `md` (the existing machine/diff format). `--audience operator|exec|skeptic|public` is sugar over `--format`. A `--index` flag on the same verb emits a static multi-experiment `index.html`. Sharing is always a skippable TAIL, never a gate — the verdict is the product.

**The spine.** `report.json` → `distill()` → `ReportVM` → adapters. `distill(Report) -> ReportVM` is a PURE, deterministic, no-I/O function that flattens and formats every number exactly once into a flat view model. Provenance is a SEPARATE impure call: `build_provenance(report, exp_dir) -> Provenance` recomputes the chain hash, runs `validate_chain`, and runs tree-reproduction. The CLI assembles `ViewBundle(distill(report), build_provenance(report, exp_dir))`; `distill()` NEVER calls `build_provenance()`. Each renderer is a thin adapter over that bundle and nothing else.

**Who writes `report.json` (the authenticity anchor).** Today no Python writes `report.json` — the LLM readout agent hand-authors it. That is the single biggest frame risk: the verifiable fields (chain hash, locked-brief hash, the verdict-tree scalars) would be authored by the very component they are meant to police. This plan fixes it at the root: a **deterministic core finalizer**, `finalize_report(exp_dir)`, computes every verifiable field itself (`chain_hash = canonical_chain_hash(exp_dir)`, `locked_brief_hash = sha256(experiment.yaml)`, `agentxp_version`, and the tree-reproduction scalars taken from the committed interpreter/analyzer outputs — never from agent prose), merges in the agent's prose (verdict rationale, uncertainty notes, stakeholder summary) read from the committed readout bundle, and writes canonical `report.json`. The readout agent stops writing `report.json` entirely; it emits only its prose bundle. Numbers police the agent, not the other way around. Receipts (live-recomputed chain hash, replay command, verdict-tree reproduction, locked-brief hash) travel inseparably in the bundle and are always present, never croppable; their prominence is tiered (one line on glance, compact footer on card/exec, full panel in dossier). The render status is wired to live re-validation across three states — VERIFIED / DRAFT_UNVERIFIED / UNVERIFIABLE.

**Brand.** agentxp adopts the editorial-economist identity as its OWN product brand. Named brand values (colors, fonts, spacing) are vendored in-repo in `agentxp/assets/design/brand.json`, loaded by `agentxp/render/brand.py`; the light/dark CSS themes consume those values. No hex literal lives in any renderer — every color/font resolves through `brand.json`.

**Explicitly deferred (design the seam, don't build):** PNG/PDF via an optional Python Playwright `[png]` extra; Notion/Google Doc/Slack destinations (monorepo MCP skill first, then optional `agentxp[destinations]` extra, idempotent upsert keyed on `experiment_id`); the multi-page dossier (≈ `report.md` + `audit --html` today); the slide deck.

---

## 2. Wave Structure

| Wave | Name | Goal | Depends on | Key deliverable |
|------|------|------|-----------|-----------------|
| **W0** | Schema widening + core finalizer | Make `report.json` self-describing & tree-reproducible so receipts and the design card have data; add `terminal_step` to the tree core; move `report.json` authorship from the LLM agent to a deterministic core finalizer | — | Additive optional fields on `schemas/report.py::Report` (incl. the 7 tree-reproduction scalars + per-guardrail direction); `terminal_step: int` on `TreeResult`; `schema_version` 1→2; **`finalize_report()` (core) computes the verifiable fields & writes `report.json`; agent demoted to prose-only** |
| **W1** | Keystone (distill + VM + registry + provenance) | One deterministic pure flatten path; separate `build_provenance()`; `report.md` becomes a `distill()` adapter output (agent already prose-only from W0); land 3-state RenderStatus contract | W0 | `render/distill.py` (pure), `render/viewmodel.py`, `render/adapters/`, `render/provenance.py`, `render/receipts.py`; golden-file parity test |
| **W2** | `report` verb + glance + surface md | First user-visible value; prove the registry + replay path end-to-end on the safe formats with an honest minimal live hash receipt | W1 | `cli/report.py`, `glance` adapter, `md` adapter, `__main__.py` registration |
| **W3** | Provenance hardening (full validate_chain + tree-reproduction + DRAFT stamping) | Make the verified badge real (can turn red), full chain invariants + tree-reproduction in scope, DRAFT stamp per format | W0, W1, W2 | Live `build_provenance()` verification flow + `_reproduce_verdict()` + per-format DRAFT stamping + red-path test |
| **W4** | Exec HTML readout + brand.json + audit_html refactor + fonts | Branded one-pager; vendor brand values & fonts; refactor audit_html onto the brand layer as first proof | W1, W3 | `brand.json`, `brand.py`, `components.css`, themes, woff2 fonts, `adapters/html.py`, `templates/...exec.html.j2`, refactored `audit_html.py` |
| **W5** | Social card (HTML) | Productize the editorial prototype cards as generated HTML | W4 | `adapters/card.py`, `templates/...card.html.j2` |
| **W6** | Static index navigator | Cross-experiment browsable roll-up, pure renderer, links out | W1, W4 | `adapters/index_html.py`, `distill_index()`, `templates/...index.html.j2`, `--index` wiring |
| **Deferred** | PNG/PDF · destinations · dossier · deck | Designed-for seams only, not built | per-item | Protocol flags, `Destination` interface note, MCP skill path |

> **Sequence note.** W3 (provenance hardening) is split out from W1 in this final plan. W1 lands the provenance *sub-model, the 3-state `RenderStatus` contract, and the `build_provenance()` signature* (so the bundle shape is fixed and W2's glance can show the one-line receipt). W2 runs a MINIMAL live hash recompute+compare so its receipt is honest from day one. W3 lands the *full `validate_chain` invariants, tree-reproduction assertion, and DRAFT stamping across formats* — the load-bearing trust work — once the verb exists to exercise it and immediately before the first branded visual tier (W4) that the Integrity Engineer set as a release gate. W3 is BLOCKED until W0 lands the tree-reproduction scalars and `terminal_step`. The original debate numbering (W3 = exec HTML) is preserved as W4 here.

---

## 3. Detailed Waves

### Wave 0 — Schema widening + core finalizer

**Goal.** If a number or provenance fact is rendered anywhere, it MUST exist in canonical `report.json` — and the verifiable fields MUST be written by deterministic code, not the LLM agent. Reading `experiment.yaml` from a renderer is FORBIDDEN. Widen the schema additively so receipts and the design card have data, add the tree-reproduction scalars and the `terminal_step` core field, move `report.json` authorship into a core `finalize_report()`, and demote the agent to prose-only — without breaking the chain or existing replays. **W3 (tree-reproduction) is BLOCKED until W0 lands the scalar set, `terminal_step`, and the finalizer.**

| ID | Task | Files | Deps | Acceptance |
|----|------|-------|------|------------|
| W0-T1 | Add provenance fields to `Report` | `agentxp/schemas/report.py` | — | `chain_hash: str \| None`, `locked_brief_hash: str \| None` (sha256 of `experiment.yaml`), `agentxp_version: str \| None` added, all optional w/ defaults |
| W0-T2 | Add design-card fields | `agentxp/schemas/report.py` | — | `hypothesis: str \| None`, `mde: float \| None`, `power: float \| None`, `ci_level: float = 0.95`; widen `MetricResult` (not `Report`) for per-arm `n_arm_control/treatment`, `mean_arm_*`, and confirm `ci_lower_95/upper_95/lower_90/upper_90` present |
| W0-T3 | Add the 7 missing tree-reproduction scalars + per-guardrail `direction` | `agentxp/schemas/report.py` | W0-T1/T2 | Add `srm_override_resolved`, `n_observed`, `n_required`, `primary_direction`, `mde_pct`, `baseline`, `late_ratio` (all Optional), plus per-guardrail `direction` on the guardrail sub-model. These 7 (+ direction) are entirely absent from `report.json` today: `n_observed`/`n_required`/`baseline` currently live only in `schemas/results.py`; hypothesis/MDE/power only in `experiment.yaml`. **Completeness check:** `TreeInput`'s full input set = these 7 scalars + the 5 CI scalars (W0-T4, already present, transposed names) + per-guardrail `direction`. W0-T7's finalizer populates them from the committed interpreter/analyzer outputs. **Load-bearing for W3 tree-reproduction.** |
| W0-T4 | Confirm the 5 CI scalars map (no rename) | `agentxp/schemas/report.py` (read), `agentxp/render/distill.py` (W1, note) | W0-T3 | The 5 CI scalars already exist under transposed names (`ci_95_lower` in schema vs `primary_ci_lower_95` in `TreeInput`). `distill()` (W1) maps them. **Do NOT rename existing schema fields.** |
| W0-T5 | Add `terminal_step` to `TreeResult` (core prerequisite) | `agentxp/interpret/tree.py` | — | Add `terminal_step: int` to `TreeResult`, set at each of the 8 return sites. Purely additive — does NOT touch verdict logic. Tree-reproduction (W3) compares `(verdict, terminal_step)` as enum+int; NO string parsing of the unstable `"{N}: ..."` format anywhere. Pin with one fixture test |
| W0-T6 | Bump `schema_version` | `agentxp/schemas/report.py` | W0-T1..T4 | `schema_version: Literal[1] → Literal[1, 2]`, default `2`; old v1 `report.json` still validates (pydantic fills defaults) |
| W0-T7 | **Deterministic `finalize_report()` writes `report.json` (core, not agent)** | `agentxp/finalize.py` (new — Stage-8 orchestration, deliberately OUTSIDE `render/` so it is not bound by the renderer purity rule), `.claude/skills/experiment/STAGES.md` | W0-T1..T6 | New core function `finalize_report(exp_dir) -> Path`, called at Stage 8 by the orchestrator AFTER the agent emits prose and BEFORE anything reads `report.json`. Computes the verifiable fields ITSELF: `chain_hash = canonical_chain_hash(exp_dir)` (this function takes the dir directly — note the asymmetry with `validate_chain`), `locked_brief_hash = sha256(experiment.yaml)`, `agentxp_version = agentxp.__version__`; pulls the 7 tree scalars + per-guardrail `direction` + per-arm/CI from the committed interpreter/analyzer stage bundles (NOT agent prose); reads agent prose (`verdict_rationale`, uncertainty notes, stakeholder summary) from the committed readout prose bundle; assembles the `Report` model; writes `report.json` atomically (reuse `audit.storage._atomic_write_bytes`). The verifiable numbers are core-authored so they police the agent. **Pre-build SPIKE (blocks implementation):** confirm the on-disk artifacts `finalize_report` reads — the interpreter `TreeResult`/`TreeInput` bundle, the analyzer output bundle, and the agent prose bundle (name + path + keys). See W0-T8 for the prose-bundle contract. |
| W0-T8 | Demote readout agent to prose-only (+ define the prose-bundle contract) | `agents/readout.system.md`, `.claude/skills/experiment/STAGES.md` | W0-T7 | Agent STOPS writing `report.json`. It writes only a **prose bundle** — define this artifact explicitly: a file (e.g. `<exp_dir>/bundles/readout.out.yaml`, confirm against today's agent) whose keys are exactly the prose `finalize_report` consumes (`verdict_rationale`, the 1–5 uncertainty notes, the stakeholder summary). The verifiable fields (`chain_hash`, `locked_brief_hash`, `agentxp_version`, the 7 scalars + `direction`, per-arm/CI) are REMOVED from the agent's responsibility — `finalize_report()` computes them. Update STAGES.md Stage-8 contract: agent emits prose bundle → core runs `finalize_report()` → `report.json` committed |
| W0-T9 | Schema-safety + fixtures | `tests/render/test_schema_widening.py` (new), `tests/render/fixtures/report_v1.json` (new), `tests/render/fixtures/report_v2.json` (new) | W0-T6, W0-T7 | Author the canonical **`report_v2.json`** fixture (carries all new fields — the file every downstream golden/red-path test depends on) AND a pre-widening **`report_v1.json`**. Tests: v1 fixture validates against widened model; `schema_version` round-trips; a widened report's `chain_hash` still validates (chain is over `log.jsonl`, sidecar-widen is chain-safe); `terminal_step` fixture pins the 8 return sites; a `schema_version: 2` fixture with required scalars MISSING is asserted to resolve to `UNVERIFIABLE` (not `DRAFT_UNVERIFIED`) — the half-migration case |

**Discipline (the migration mechanics).** Additive + optional + defaulted fields only. `schema_version` increments. The audit chain is over `log.jsonl`, NOT `report.json`, so widening the sidecar does NOT invalidate `chain_hash`. `distill()` (W1) is the SOLE place that reads `schema_version` and normalizes; adapters never branch on version. Golden replays (W1) guard the bump.

**`locked_brief_hash` semantics.** `locked_brief_hash: str | None` is the sha256 of `experiment.yaml` (the write-once lock), computed by the deterministic `finalize_report()` (W0-T7) at Stage 8 — renderers never read `experiment.yaml`. The audit log does NOT currently record a brief hash, so `build_provenance` cannot cross-check it against the chain; it is therefore surfaced as a **"recorded" receipt (core-written), explicitly NOT part of the VERIFIED gate** (which rests only on the live-verified chain hash, `validate_chain`, and tree-reproduction). Optional; absent → renders "brief lock not recorded" (non-blocking by design). A chain-recorded brief-lock event that would make it independently verifiable stays a future item.

---

### Wave 1 — Keystone: pure `distill()` + `ReportVM` + adapter registry + provenance sub-model

**Goal.** Extract the flat view model into one module, build the single deterministic PURE `distill()`, stand up the adapter registry, land the shared provenance sub-model and the 3-state `RenderStatus` contract (with `build_provenance()` as a separate impure call), and migrate the readout agent off hand-building the VM. This is the enabling refactor that makes every present and deferred format a thin renderer.

| ID | Task | Files | Deps | Acceptance |
|----|------|-------|------|------------|
| W1-T1 | Promote flat models into `viewmodel.py` | `agentxp/render/viewmodel.py` (new) | W0 | `ReportVM` + `MetricRow`, `GuardrailViolation`, `Diagnostics`, `AuditRow`, `DesignCard`, `IndexRowVM` defined; the CLI-assembled `ViewBundle` carries `(distill_output, provenance, render_status)` |
| W1-T2 | Build pure `distill()` | `agentxp/render/distill.py` (new) | W1-T1 | `distill(Report) -> ReportVM` is PURE, side-effect-free, idempotent, NO I/O; owns ALL formatting (lift_str, ci_str, sample_pct, badge class, flattening primary/guardrails/negative_controls/segments → `MetricRow[]`, `None`→"unavailable", maps the 5 transposed CI scalars per W0-T4); carries agent prose VERBATIM (`verdict_rationale`, `UncertaintyNote.detail`, stakeholder summary); SOLE version-skew handler. **NEVER calls `build_provenance()`.** |
| W1-T3 | Build the provenance sub-model + 3-state RenderStatus contract | `agentxp/render/provenance.py` (new), `agentxp/render/receipts.py` (new) | W1-T1 | `Provenance` (frozen, tier-tagged fields), `build_provenance(report, exp_dir) -> Provenance` signature (separate impure call; live verification behavior is W3). **Call-shape note:** `validate_chain` takes `(experiment_id, *, _root=...)`, not an `exp_dir` — so `build_provenance` splits `exp_dir` into `experiment_id = exp_dir.name` + `root = exp_dir.parent` and calls `validate_chain(experiment_id, _root=root)` (promoting the currently test-only `_root` kwarg to a supported production call). Also `ProvenanceCache`, and the three-state `RenderStatus` enum: **VERIFIED** (green — requires ALL of: `log.jsonl` present + stored `chain_hash` present + recomputed==stored + `validate_chain` ok + tree reproduces; one-directional: any "can't check" → never VERIFIED), **DRAFT_UNVERIFIED** (red — active failure: hash mismatch or tree-reproduction failure), **UNVERIFIABLE** (neutral gray — `schema_version==1`, or `chain_hash`/`log.jsonl` absent, or required scalars missing; NOT an accusation). The CLI assembles `ViewBundle(distill(report), build_provenance(report, exp_dir))` |
| W1-T4 | Adapter Protocol + registry | `agentxp/render/adapters/base.py` (new), `agentxp/render/adapters/__init__.py` (new) | W1-T1 | `FormatAdapter` Protocol (`format_id`, `binary`, `requires_node`, `render(bundle)->bytes\|str`, `default_filename`); `ADAPTERS` dict mirrors `SUBCOMMANDS`; flags exist day one so CLI can fail fast on deferred formats |
| W1-T5 | Markdown reference adapter | `agentxp/render/adapters/markdown.py` (new), `agentxp/render/report.py` (modified), `agentxp/render/__init__.py` (modified — re-export `distill`/`render_report` for back-compat), `templates/experiment-report.md` (unchanged) | W1-T2, W1-T4 | Thin wrapper over today's `render/report.py` renderer, consuming the bundle; markdown Jinja env stays `autoescape=False`; `report.md` is now generated from `distill(report.json)` rather than hand-built by the agent |
| W1-T6 | Confirm readout agent is prose-only | `agents/readout.system.md` (read — already demoted in W0-T8) | W1-T2, W0-T8 | The agent no longer hand-builds the flat model OR writes `report.json` (done in W0-T8); this task just confirms the contract holds end-to-end once `distill()` + `finalize_report()` exist — `report.json` is core-finalized, `report.md` is a `distill()` adapter output, the agent emits only its prose bundle. No new agent work; pretty-printing is fully out of the prompt |
| W1-T7 | Golden-file parity test (the keystone guard) | `tests/render/test_distill_parity.py` (new) | W1-T2, W1-T5, W1-T6 | NOT byte-identity vs an LLM sample. A **hand-blessed** canonical `report.md` is captured; normalization rule: agent prose carried verbatim (`verdict_rationale`, uncertainty notes) must match EXACTLY — drift there is a bug; numeric formatting / whitespace / key-order are owned by `distill()`, so on a formatting difference the golden is UPDATED to `distill()`'s output. Test asserts NORMALIZED equality, not bytes |
| W1-T8 | `distill()` purity/stability + version-skew tests | `tests/render/test_distill.py` (new) | W1-T2 | `distill(r) == distill(r)`, no I/O, no mutation of `r`, never calls `build_provenance()`; v1-fixture and v2-fixture both distill to a valid `ReportVM` |

**Layering rule (enforced in review).** `schemas/report.py → distill.py → viewmodel.py → adapters/* → cli/report.py`. Adapters import `viewmodel` + `brand` only — never `schemas`, `distill`, `provenance`, a warehouse, the audit log, or numpy. `provenance.py`/`receipts.py` are assembled alongside `distill()` output by the CLI into the `ViewBundle`; `distill()` never depends on them. Any backward arrow is a bug. **Scope of the FORBIDDEN-imports rule:** it binds the *renderer path* (`render/distill.py` + `render/adapters/*`), which must never touch the audit log, a warehouse, an LLM, `experiment.yaml`, or numpy. It does NOT bind `agentxp/finalize.py` (W0-T7) — the finalizer is Stage-8 orchestration that lives OUTSIDE `render/` precisely so it can legitimately call `canonical_chain_hash`, read `experiment.yaml`, and read the stage bundles. `build_provenance()` (impure, in `render/provenance.py`) is the one sanctioned exception inside `render/`: it reads `log.jsonl` for live verification but is never imported by an adapter.

---

### Wave 2 — `report` verb + glance renderer + surface md

**Goal.** First user-visible deliverable. Prove the registry + replay path end-to-end on the two safe (Python-only) formats, with an honest minimal live hash receipt. Highest-frequency daily value: "I just ran it — did it pass?"

| ID | Task | Files | Deps | Acceptance |
|----|------|-------|------|------------|
| W2-T1 | `report` CLI module | `agentxp/cli/report.py` (new) | W1 | Modeled exactly on `cli/audit.py`: same `argparse` shape, `_resolve_exp_dir`, `EXIT_*` from `exit_codes.py`, atomic chmod-600 write via `audit.storage._atomic_write_bytes`; loads `report.json` → validate → `distill()` → assemble `ViewBundle` with `build_provenance()` → adapter → write; NO LLM/warehouse/agent loop |
| W2-T2 | Register the verb | `agentxp/cli/__main__.py` (modified) | W2-T1 | `"report": ("agentxp.cli.report", "main")` added to `SUBCOMMANDS` |
| W2-T3 | Default-resolution logic | `agentxp/cli/report.py` | W2-T1 | `--format` > `--audience` (mutually exclusive, fail loud w/ named reason) > `sys.stdout.isatty()` True→glance / False→md |
| W2-T4 | `glance` adapter (Operator owns end-to-end) | `agentxp/render/adapters/glance.py` (new), `agentxp/render/brand.py` (new, ANSI mirror) | W1-T4 | 3-line max, verdict-first; line 1 = verdict word + lift + CI + guardrail + confidence (verbatim from VM); line 2 = mandatory one-line receipt (`agentxp audit <id>` + chain OK/MISMATCH/unverifiable token from the W2-T9 minimal live check); line 3 = hint (suppressed by `--quiet`/pipe). Glance stays plain text (no Brand colors). `--out` with `--format glance` → `EXIT_USER_ERROR` |
| W2-T5 | `--audience` sugar table | `agentxp/cli/report.py` | W2-T3 | operator→glance/md, exec→html, skeptic→md (+ points at `audit --html`, NOT a new renderer), public→card |
| W2-T6 | Exit-code semantics + schema-validation guard | `agentxp/cli/report.py`, `agentxp/cli/exit_codes.py` (read) | W2-T1 | `EXIT_OK` (rendered, VERIFIED/UNVERIFIABLE); `EXIT_USER_ERROR` (unknown id / flag conflict / `--out` w/ glance / missing report.json); `EXIT_WARNING` (rendered but DRAFT_UNVERIFIED, mirrors audit's failed-chain return); `EXIT_FATAL` (disk error, or `Report.model_validate(data)` wrapped in `try/except ValidationError → EXIT_FATAL` with "report.json failed schema validation (version mismatch or corruption)"). Keep `extra="forbid"`; supported skew = OLD v1 read by NEW v2 (works, additions Optional). Do NOT silently ignore unknown fields |
| W2-T7 | Stage-8 skippable tail scaffold (non-TTY guarded) | `.claude/skills/experiment/SKILL.md`, `.claude/skills/experiment/STAGES.md` §11 (modified) | W2-T1 | Soft prompt at `confirm_readout`→`confirm`: enter-to-skip terminates the run normally; never blocks. The "enter to skip" tail GUARDS on `sys.stdin.isatty()` — non-interactive runs (CI, pipe) skip silently, never block on stdin. In W2 it offers only `(enter to skip)`; share options added in W4/W5 |
| W2-T8 | `/share-experiment <id>` on-demand re-render | `.claude/skills/experiment/SKILL.md` (command def) | W2-T1 | Re-enters only the render step against committed `report.json` via `distill()` + `build_provenance()` + adapter; no pipeline re-run |
| W2-T9 | Minimal live hash recompute (honest receipt) | `agentxp/render/provenance.py`, `agentxp/render/adapters/glance.py`, `markdown.py` | W1-T3, W2-T1 | glance/md run a MINIMAL live check — recompute `canonical_chain_hash` and compare to stored (the function already exists). Receipt is honest from W2: `OK` / `MISMATCH` / `unverifiable`. **W2 never prints "verified" off a stored hash alone.** Full `validate_chain` invariants + tree-reproduction + richer DRAFT stamping are ADDED in W3 |

---

### Wave 3 — Provenance hardening: full validate_chain + tree-reproduction + DRAFT stamping

**Goal.** Make the verified badge real — wired to live re-validation that CAN turn red — and add the full `validate_chain` invariants plus the tree-reproduction assertion that defends against a doctored sidecar. This is the load-bearing v1 trust defense and the explicit release gate for W4+. **Blocked on W0's tree-reproduction scalars (W0-T3), `terminal_step` (W0-T5), and the core finalizer (W0-T7) — tree-reproduction can only verify fields the finalizer authored.**

| ID | Task | Files | Deps | Acceptance |
|----|------|-------|------|------------|
| W3-T1 | Full live verification flow in `build_provenance()` | `agentxp/render/provenance.py` | W1-T3, W2, W0-T3, W0-T5, W0-T7 | Status resolution runs in strict precedence. **(0) "Can't-check" gate FIRST, before any reproduction is attempted:** if `schema_version==1`, OR `chain_hash`/`log.jsonl` absent, OR any required tree-reproduction scalar is missing (the half-migrated `schema_version==2`-but-incomplete case) → `UNVERIFIABLE` and STOP — do NOT attempt tree-reproduction (a missing scalar must never surface as a `DRAFT_UNVERIFIED` accusation). Otherwise: (1) `live_hash = canonical_chain_hash(exp_dir)` recomputed, never trust stored; (2) `hash_matches_report = live_hash == report.chain_hash`; (3) split `exp_dir` → `experiment_id = exp_dir.name`, `root = exp_dir.parent`; `cv = validate_chain(experiment_id, _root=root)` wrapped in `try/except PerfBudgetExceeded` → degrade to `UNVERIFIABLE`, never crash; (4) tree-reproduction (W3-T2); (5) `render_status = VERIFIED iff log.jsonl present AND stored chain_hash present AND hash_matches_report AND cv.ok AND tree_reproduces`; an active failure (hash mismatch or tree-reproduction failure) → `DRAFT_UNVERIFIED` w/ first-failing-check reason (precedence chain→hash→tree). One-directional: any "can't check" → never VERIFIED. `locked_brief_hash` is NOT in the gate (surfaced as a "recorded" receipt only — see W0 `locked_brief_hash` semantics) |
| W3-T2 | Tree-reproduction assertion | `agentxp/render/receipts.py` | W0-T3, W0-T5, W3-T1 | `_reproduce_verdict(report)` rebuilds `TreeInput` from report scalars (incl. the 7 W0-T3 scalars + per-guardrail `direction`), re-runs `walk_tree`, asserts `result.verdict == report.verdict` AND `result.terminal_step == report.terminal_step`; comparison is `(verdict, terminal_step)` as enum+int — NO string parsing. `Report.verdict` is the TREE verdict; a human NO-SHIP sign-off lives in `override_justification` and never overwrites `Report.verdict`, so the re-run tree verdict matches. The SRM-override path reproduces only if `srm_override_resolved` is persisted (W0) |
| W3-T3 | `ProvenanceCache` (perf) | `agentxp/render/provenance.py` | W3-T1 | `(live_hash, cv)` cached keyed on `exp_dir` per render session; recompute once, reuse across all formats/index rows of one run |
| W3-T4 | Per-status DRAFT / UNVERIFIABLE stamping | `agentxp/render/adapters/glance.py`, `markdown.py` (+ html/card/index as they land) | W3-T1 | DRAFT_UNVERIFIED — glance: leading `⚠ DRAFT — UNVERIFIED: {reason}` before verdict line; md: top admonition + footer `chain integrity: FAILED — {detail}`. UNVERIFIABLE — calm neutral-gray treatment, never an accusation. A legitimate override renders as a distinct, legitimate layer — never DRAFT. Verdict never hidden, always stamped |
| W3-T5 | Display-short / embed-full everywhere | `agentxp/render/receipts.py` | W3-T1 | 12-char `chain_hash_short` displayed; full 64-char `chain_hash` embedded (md footer literal, later HTML `<meta>`/`data-`); short hash NEVER the sole anchor |
| W3-T6 | Red-path + override test (release gate) | `tests/render/test_provenance_redpath.py` (new) | W3-T1..T4 | Tampered fixture (hash mismatch / tree-reproduction failure) → every tier renders DRAFT_UNVERIFIED + reason; an override-fixture (human NO-SHIP via `override_justification` over a tree SHIP verdict) renders as a legitimate override layer and STILL reproduces (tree verdict matches `Report.verdict`), never DRAFT; receipts block present & un-croppable; the `(verdict, terminal_step)` comparison is pinned by fixture so a `tree.py` change fails loudly |

---

### Wave 4 — Exec HTML readout + brand values + audit_html refactor + fonts

**Goal.** The branded one-pager. Vendor the editorial-economist brand values & self-hosted fonts, build the brand layer (no hex literals), refactor `audit_html.py` onto it as the first visible proof, and ship the exec HTML adapter with a mandatory receipts footer wired to live `render_status`.

| ID | Task | Files | Deps | Acceptance |
|----|------|-------|------|------------|
| W4-T1 | Vendor brand values | `agentxp/assets/design/brand.json` (new) | — | Editorial palette (cream/blue/serif) encoded as named brand values; `editorial-light` (default) + `editorial-dark` named themes; greens/reds reconcile to the ACTUAL `audit_html` values `#146c2e` / `#b3261e` (NOT `#2D8659` / `#C8102E`); `_derived_from` note for monorepo semantic green/red (copied, never a runtime dep) |
| W4-T2 | Brand layer (Python loader) | `agentxp/render/brand.py` (new/extend) | W4-T1 | Loads `brand.json` once; `css_vars()` emits inlined `:root{--xp-…}`; `ansi()` map for glance; `svg_palette` for charts; base64 `@font-face` block builder (deterministic). The "no hex literal in any renderer" enforcement point — every color/font resolves through `brand.json` |
| W4-T3 | Self-host license-clear fonts | `agentxp/assets/design/fonts/*.woff2`, `OFL.txt` | — | **Source Serif 4 (OFL)** headline serif + **Inter (OFL)** body + **JetBrains Mono (OFL)** labels. Charter is DROPPED (no legal diligence). Base64-embedded, Latin subset, ≤2 weights/family, target <300 KB/file; system fallback stack retained; NO CDN. **Blocker before any visual tier ships.** |
| W4-T4 | Component CSS + themes | `agentxp/assets/design/components.css`, `themes/editorial-light.css`, `themes/editorial-dark.css` (new) | W4-T1 | `.xp-verdict-badge` (always carries the word, not color alone), `.xp-eyebrow/.xp-headline`, `.xp-metric-row`, `.xp-callout-strip/.xp-stat`, `.xp-badge--pass/--warn` (reuse chain green/red), `.xp-chart`, `.xp-receipts-footer` (required, un-renderable without it); every value a `var(--xp-…)` resolving through `brand.json` |
| W4-T5 | Deterministic inline-SVG charts (pure) | `agentxp/render/charts.py` (new) | W4-T2 | `lift_bar`, `ci_interval`, `srm_split`, `power_curve`; brand-colored; plot ONLY stored numbers in `report.json` (no stats in presentation). The power curve is a statistic (n_required across MDE) not stored today → render it ONLY if the engine emits curve points, else OMIT. `sample_pct = n_observed/n_required` is allowed display arithmetic over two stored ints. Byte-identical from same `report.json`; no JS charting lib |
| W4-T6 | Exec HTML adapter | `agentxp/render/adapters/html.py` (new), `templates/experiment-report.html.j2` (new) | W4-T2..T5, W3 | `autoescape=True`; reuses audit_html `_esc` self-containment discipline; verdict-first; mandatory compact `.receipts-footer` from live `render_status`; `--audience exec` hides full audit trail, `skeptic` shows it; single self-contained file, offline-safe |
| W4-T7 | Refactor `audit_html.py` onto brand layer (first proof) | `agentxp/cli/audit_html.py` (modified) | W4-T2..T4 | Off-brand dump becomes on-brand; `.chain-ok`/`.chain-fail` resolve through `brand.json`; preserves single-file / inline-CSS / `html.escape()` / chmod-600 / offline contract |
| W4-T8 | Per-status golden tests (visual-QA gate) | `tests/render/test_html_golden.py` (new) | W4-T6 | Fixtures for ship / don't-ship / inconclusive / guardrail-violated / underpowered + DRAFT_UNVERIFIED + UNVERIFIABLE, light+dark; snapshot; contrast audit (`#8A8580` muted reserved for ≥14px labels) |

---

### Wave 5 — Social card (HTML)

**Goal.** Productize the editorial prototype cards as one generated HTML, fed by the same bundle. Card-as-HTML ships; card-as-PNG is deferred.

| ID | Task | Files | Deps | Acceptance |
|----|------|-------|------|------------|
| W5-T1 | Social card adapter | `agentxp/render/adapters/card.py` (new), `templates/social-card.html.j2` (new) | W4 | Pixel-locked 1200×1500 portrait; masthead + verdict badge + one hero chart + callout strip + compact receipts footer; DRAFT treatment is a diagonal ribbon ACROSS the verdict-badge hero (NOT a croppable footer note — the footer is the croppable part of a LinkedIn screenshot); HTML only; reuses W4 components |
| W5-T2 | Stage-8 tail `(p) public card` option | `.claude/skills/experiment/SKILL.md`, `.claude/skills/experiment/STAGES.md` | W5-T1, W2-T7 | Share prompt offers public card; still enter-to-skip; non-TTY guarded |
| W5-T3 | Card golden tests | `tests/render/test_card_golden.py` (new) | W5-T1 | Five verdict states + DRAFT ribbon render clean; cross-format equality with html/md/index |

---

### Wave 6 — Static index navigator

**Goal.** The cross-experiment browsable roll-up — "what have we tested, what won." Pure renderer over many `report.json` via the same `distill()`; static single file; links out, never iframes.

| ID | Task | Files | Deps | Acceptance |
|----|------|-------|------|------------|
| W6-T1 | `distill_index()` + IndexVM | `agentxp/render/distill.py`, `agentxp/render/viewmodel.py` | W1 | `distill_index(list[Report]) -> IndexVM`; projection only, never re-derivation |
| W6-T2 | Index adapter | `agentxp/render/adapters/index_html.py` (new), `templates/experiment-index.html.j2` (new) | W4, W6-T1 | Discovers via the canonical root `{cwd}/experiments/` walked the way `cli/list.py` does (via `state.yaml` presence), reusing `list.py`'s resolver — NOT `ExperimentStore.list_experiments()` (which reads global `~/.agentxp`). Per id `distill(report.json)` + `build_provenance()`; one self-contained file; table at Tier 1 (Name · Verdict badge · Confidence · lift · CI · Status · Updated · [report][audit]); verdict carries word + VERIFIED/DRAFT/UNVERIFIABLE marker. **Per-row isolation:** an experiment that fails `distill()`/validation renders a status-only row with an error marker; a row whose `build_provenance` raises `PerfBudgetExceeded` (the 400ms hard cap is per-experiment, so N experiments = N independent budgets) renders `UNVERIFIABLE`; one bad experiment NEVER aborts the whole index. Links OUT (no iframe); inline vanilla JS filter/sort, degrades without JS; `html.escape()` everything; brand values only |
| W6-T3 | `--index` wiring | `agentxp/cli/report.py` | W2-T1, W6-T2 | `--index` flag, `exp_id` optional when present; both omitted or both given → `EXIT_USER_ERROR` w/ named reason; `--out` default `{cwd}/experiments/index.html`; reuses `list.py` resolve + filters |
| W6-T4 | Cross-format equality test | `tests/render/test_cross_format_equality.py` (new) | W6-T2 | lift / CI / verdict strings byte-identical across md / html / card / index for one fixture (executable proof numbers are formatted exactly once) |

**Index perf.** Live-validate every row with a per-session `ProvenanceCache`; accept O(N) at realistic scale (tens). Above ~50 experiments, fall back to stored-status rows with a "re-verify" affordance. Don't pre-optimize.

---

### Deferred / Future Waves (design the seam, do not build)

| Deferred item | Seam it plugs into | Notes |
|---------------|--------------------|-------|
| **PNG / PDF rasterization** | New `adapters/png.py` / `pdf.py` registry rows; `binary=True`, `requires_node=False` flags already on the `FormatAdapter` Protocol (W1-T4) | **Engine decision: Python `playwright` as an optional lazily-detected `agentxp[png]` extra — NOT a Node puppeteer harness.** Rationale: one language for contributors, simpler/free CI, reproducible pinned Chromium (`playwright install chromium`), offline after install. Core wheel ships `numpy/pandas/scipy/jinja2` only. `png.py`/`pdf.py` lazy-import + availability check; if absent → `EXIT_USER_ERROR`: "PNG/PDF needs `pip install agentxp[png] && playwright install chromium`. HTML is at `<path>` — print it yourself." PNG is HTML-in-a-fixed-box rasterized; bundle web fonts, `print-color-adjust:exact`. QR (full hash) is a pure additive step here. |
| **Notion DB / Google Doc / Slack** | `Destination` Protocol (design note only): `emit(view_bundle, config) -> EmitResult`; input is the identical `ViewBundle(distill_output, provenance, render_status)` | Two tiers, both outside core: (1) monorepo MCP skill `.claude/skills/agentxp-publish/` reusing already-authed `mcp__claude_ai_Notion__*`/`mcp__google-docs__*`/`mcp__slack__*` (zero new secrets, fast path for Shane); (2) optional `agentxp[destinations]` Python extra, env-var auth only. Idempotent upsert keyed on `experiment_id`; skip-if-unchanged via `sha256(report.json)`; per-experiment `publish.json` manifest; publish failure non-fatal, never blocks local run. No `notion-client`/`slack_sdk`/`google-api-python-client` in core. |
| **Multi-page dossier** | The DOSSIER prominence tier already specified in `Provenance` (full panel) | Don't build a distinct artifact — dossier ≈ `report.md` + `audit --html` today. `--audience skeptic` surfaces both. Component vocabulary (W4) extends to it later. |
| **Slide deck** | Adapter registry row | Future; not designed beyond "it's another adapter over the bundle." |

---

## 4. Dependency Graph

```
W0 schema widening + core finalizer
   (chain_hash, locked_brief_hash, agentxp_version, design-card fields,
    + 7 tree-reproduction scalars [srm_override_resolved, n_observed, n_required,
      primary_direction, mde_pct, baseline, late_ratio] + per-guardrail direction,
    + terminal_step: int on TreeResult @ 8 return sites)
        │  finalize_report(exp_dir) [CORE, not agent] computes the verifiable fields
        │     (chain hash, locked-brief hash, version, tree scalars from interpreter/
        │      analyzer outputs) + merges agent prose bundle → writes report.json;
        │     readout agent DEMOTED to prose-only. Numbers police the agent.
        │  (schema_version 1→2; additive/optional; distill() is sole skew handler;
        │   chain over log.jsonl stays valid; the 5 CI scalars are mapped, never renamed)
        │  ── W3 (tree-reproduction) is BLOCKED until these + finalizer land ──┐
        ▼                                                          │
W1 KEYSTONE ── distill(Report)->ReportVM (PURE, no I/O, never calls build_provenance)
   │            │
   │            └──► viewmodel.py (ViewBundle = distill_output + provenance + render_status)
   │            └──► provenance.py / receipts.py
   │                  (build_provenance(report, exp_dir) SEPARATE impure call;
   │                   3-state RenderStatus contract: VERIFIED / DRAFT_UNVERIFIED / UNVERIFIABLE)
   │            └──► adapters/base.py + registry (FormatAdapter Protocol; binary/requires_node day-one)
   │            └──► adapters/markdown.py (reference) + readout-agent migration
   │            └──► GOLDEN-FILE PARITY TEST (hand-blessed canonical, normalized equality)
   ▼
W2 cli/report.py verb ──► glance adapter (+ brand.py ANSI) ──► surface md
   │   (TTY→glance, pipe→md; --audience sugar; mirrors audit.py;
   │    MINIMAL live hash recompute+compare → honest receipt OK/MISMATCH/unverifiable;
   │    never prints "verified" off a stored hash; schema-validate guard → EXIT_FATAL;
   │    Stage-8 skippable tail scaffold guarded on sys.stdin.isatty())
   ▼                                                              │
W3 PROVENANCE HARDENING ◄──────────── (blocked on W0 scalars + terminal_step)
   │   build_provenance() FULL live re-validation (recompute hash + validate_chain
   │   + _reproduce_verdict via walk_tree comparing (verdict, terminal_step), no string parse)
   │   ──► 3-state RenderStatus ──► per-status DRAFT/UNVERIFIABLE stamping
   │   ──► ProvenanceCache (perf) ──► override-fixture + RED-PATH TEST (release gate for W4+)
   ▼
W4 BRAND.JSON + FONTS (vendored, no CDN, no hex literals; greens/reds #146c2e/#b3261e)
   │   ──► brand.py/components.css/themes
   │   ──► charts.py (deterministic SVG, plots only stored numbers, power curve only if emitted)
   │   ──► adapters/html.py (exec one-pager, mandatory receipts footer)
   │   ──► REFACTOR audit_html.py onto brand layer (first proof) ──► visual-QA gate (states + DRAFT + UNVERIFIABLE)
   │       Fonts: Source Serif 4 (OFL) + Inter (OFL) + JetBrains Mono (OFL); Charter dropped
   ▼
W5 adapters/card.py (social card HTML, 1200×1500, DRAFT diagonal ribbon over verdict-badge hero)
   ▼
W6 distill_index() ──► adapters/index_html.py (discovers {cwd}/experiments/ via list.py resolver;
        per-row isolation; live-validate per session-cache, O(N) at tens, stored-status fallback >50)
        ──► --index wiring ──► CROSS-FORMAT EQUALITY TEST
        (depends on W1 for distill, W4 for brand/links-out to exec HTML)

DEFERRED (seams only): png/pdf [playwright extra] · Destination Protocol [MCP skill → [destinations] extra] · dossier (= existing artifacts) · deck

Cross-cutting invariants (every wave):
  • report.json is the only legal renderer input; distill() formats numbers exactly once and is PURE.
  • report.json's verifiable fields are core-authored by finalize_report(), NEVER by the LLM agent.
  • Provenance is a separate impure build_provenance() call; the CLI assembles ViewBundle(distill(report), build_provenance(report, exp_dir)).
  • Receipts ALWAYS present, never croppable; prominence tiered (glance line / footer / panel).
  • RenderStatus is three-state; VERIFIED is one-directional (any "can't check" → never VERIFIED).
  • No hex literal in any renderer (W4+); brand values vendored in brand.json.
  • Adapters import viewmodel + brand only; one-way dependency arrows.
```

---

## 5. Files Changed Summary

### Wave 0
| File | Change | Purpose |
|------|--------|---------|
| `agentxp/schemas/report.py` | modify | Add `chain_hash`/`locked_brief_hash`/`agentxp_version` + hypothesis/MDE/power/per-arm (+ MetricResult CI/per-arm) + the 7 tree-reproduction scalars + per-guardrail `direction`; bump `schema_version` 1→2 |
| `agentxp/interpret/tree.py` | modify | Add `terminal_step: int` to `TreeResult`, set at each of the 8 return sites (additive) |
| `agentxp/finalize.py` | new | Deterministic core `finalize_report(exp_dir)` (OUTSIDE `render/` — Stage-8 orchestration, not a renderer) — computes the verifiable fields (chain hash, locked-brief hash, version, tree scalars from interpreter/analyzer outputs), merges agent prose bundle, writes canonical `report.json` atomically |
| `agents/readout.system.md` | modify | **Demote to prose-only:** agent no longer writes `report.json` or the verifiable fields — emits only its prose bundle |
| `.claude/skills/experiment/STAGES.md` (+ `SKILL.md`) | modify | Stage-8 contract: agent prose bundle → core `finalize_report()` → `report.json` committed |
| `tests/render/fixtures/report_v1.json`, `report_v2.json` | new | Canonical pre-widening (v1) + fully-widened (v2) fixtures — the files every downstream golden/red-path test depends on |
| `tests/render/test_schema_widening.py` | new | v1 fixture validates against widened model; chain stays valid; `terminal_step` fixture pins 8 return sites; `schema_version:2`+missing-scalars → `UNVERIFIABLE` |

### Wave 1
| File | Change | Purpose |
|------|--------|---------|
| `agentxp/render/viewmodel.py` | new | `ReportVM` + `ViewBundle` (distill_output + provenance + render_status) + row sub-models |
| `agentxp/render/distill.py` | new | Pure, no-I/O, deterministic flatten/format; maps the 5 transposed CI scalars; sole version-skew handler; never calls `build_provenance()` |
| `agentxp/render/provenance.py` | new | `Provenance` model, 3-state `RenderStatus`, `build_provenance(report, exp_dir)` signature (separate impure call), `ProvenanceCache` |
| `agentxp/render/receipts.py` | new | `_reproduce_verdict()` + per-format receipt serialization/stamping |
| `agentxp/render/adapters/base.py` | new | `FormatAdapter` Protocol + registry helpers |
| `agentxp/render/adapters/__init__.py` | new | `ADAPTERS` registry |
| `agentxp/render/adapters/markdown.py` | new | Reference adapter over the bundle |
| `agentxp/render/report.py` | modify | Becomes/feeds the markdown adapter; imports VM from `viewmodel` |
| `agentxp/render/__init__.py` | modify | Re-export `distill`, `render_report` (back-compat) — wired in W1-T5 |
| `agents/readout.system.md` | read | Confirm prose-only contract holds end-to-end (the demotion itself lands in W0-T8) |
| `tests/render/test_distill_parity.py` | new | Golden-file parity (hand-blessed canonical, normalized equality) |
| `tests/render/test_distill.py` | new | Purity/idempotency (no I/O, no `build_provenance` call) + version-skew |

### Wave 2
| File | Change | Purpose |
|------|--------|---------|
| `agentxp/cli/report.py` | new | `report` verb, mirrors `audit.py`; default resolution; exit codes; schema-validate guard → EXIT_FATAL; assembles `ViewBundle` |
| `agentxp/cli/__main__.py` | modify | Register `"report"` in `SUBCOMMANDS` |
| `agentxp/render/adapters/glance.py` | new | Terminal one-screen verdict-first renderer (Operator owns); honest OK/MISMATCH/unverifiable receipt |
| `agentxp/render/brand.py` | new | `brand.json` loader → Python mirror (ANSI in W2; CSS-var/SVG extended in W4) |
| `agentxp/render/provenance.py` | modify | Minimal live `canonical_chain_hash` recompute+compare (honest W2 receipt) |
| `agentxp/render/adapters/markdown.py` | modify | Surface the W2-T9 honest OK/MISMATCH/unverifiable receipt in the md footer |
| `.claude/skills/experiment/SKILL.md`, `STAGES.md` | modify | Stage-8 skippable share tail scaffold (guarded on `sys.stdin.isatty()`); `/share-experiment` |

### Wave 3
| File | Change | Purpose |
|------|--------|---------|
| `agentxp/render/provenance.py` | modify | Full live re-validation flow (validate_chain + tree-reproduction) + 3-state `RenderStatus` + `ProvenanceCache` behavior |
| `agentxp/render/receipts.py` | modify | Tree-reproduction assertion (compares `(verdict, terminal_step)`); display-short/embed-full; DRAFT stamping |
| `agentxp/render/adapters/glance.py`, `markdown.py` | modify | DRAFT_UNVERIFIED / UNVERIFIABLE / override stamping per format |
| `tests/render/test_provenance_redpath.py` | new | Red-path / tamper + override-fixture test (release gate for W4+) |

### Wave 4
| File | Change | Purpose |
|------|--------|---------|
| `agentxp/assets/design/brand.json` | new | Vendored editorial brand values; light+dark themes; greens/reds `#146c2e`/`#b3261e` |
| `agentxp/assets/design/components.css` | new | Named component atoms |
| `agentxp/assets/design/themes/editorial-light.css`, `editorial-dark.css` | new | Theme overrides (var-driven, resolve through `brand.json`) |
| `agentxp/assets/design/fonts/*.woff2` (+ `OFL.txt`) | new | Self-hosted Source Serif 4 + Inter + JetBrains Mono (all OFL); Charter dropped |
| `agentxp/render/brand.py` | modify | Extend loader to CSS-var + SVG palette + base64 @font-face block |
| `agentxp/render/charts.py` | new | Deterministic inline-SVG builders; plot only stored numbers; power curve only if emitted |
| `agentxp/render/adapters/html.py` | new | Exec one-pager adapter |
| `templates/experiment-report.html.j2` | new | Exec one-pager template (requires receipts block) |
| `agentxp/cli/audit_html.py` | modify | Refactor onto brand layer (first proof) |
| `tests/render/test_html_golden.py` | new | Per-status (incl. DRAFT_UNVERIFIED + UNVERIFIABLE) visual-QA gate |

### Wave 5
| File | Change | Purpose |
|------|--------|---------|
| `agentxp/render/adapters/card.py` | new | Social card HTML adapter; DRAFT diagonal ribbon over verdict-badge hero |
| `templates/social-card.html.j2` | new | Social card template (requires receipts block) |
| `.claude/skills/experiment/SKILL.md`, `STAGES.md` | modify | `(p) public card` share option (non-TTY guarded) |
| `tests/render/test_card_golden.py` | new | Card golden states |

### Wave 6
| File | Change | Purpose |
|------|--------|---------|
| `agentxp/render/distill.py`, `viewmodel.py` | modify | `distill_index()` + `IndexVM` |
| `agentxp/render/adapters/index_html.py` | new | Static navigator adapter; discovers `{cwd}/experiments/` via `list.py` resolver; per-row isolation |
| `templates/experiment-index.html.j2` | new | Navigator template (links out, no iframe) |
| `agentxp/cli/report.py` | modify | `--index` wiring |
| `tests/render/test_cross_format_equality.py` | new | Byte-identical numbers across formats |

> **Note on path conventions.** This master plan adopts the **flat `agentxp/render/` layout** (matches the existing `render/report.py`, `render/voice_audit.py`); the Brand `present/` sub-package is folded into it. Brand values live in `agentxp/assets/design/brand.json`, loaded by `agentxp/render/brand.py`. The readout agent is at the repo root (`agents/readout.system.md`); the orchestrator spec is `.claude/skills/experiment/STAGES.md` + `.claude/skills/experiment/SKILL.md`.

---

## 6. Resolved Decisions

The following items were debated during synthesis and are now settled; they are reflected directly in the waves above.

- **Brand-values filename.** `agentxp/assets/design/brand.json`, loaded by `agentxp/render/brand.py`. The word "token" is dropped — these are named brand values. (W4-T1/T2.)
- **`step_fired` int-vs-list.** Resolved by an additive core field: `TreeResult.terminal_step: int` set at the 8 return sites. Tree-reproduction compares `(verdict, terminal_step)` as enum+int — no string parsing of the unstable `"{N}: ..."` format. (W0-T5, W3-T2.)
- **`report.json` authorship.** A deterministic core `finalize_report(exp_dir)` computes the verifiable fields (chain hash, locked-brief hash, version, tree scalars from the interpreter/analyzer outputs) and writes `report.json`; the LLM readout agent is demoted to prose-only. Today the agent hand-authors the file — that would let the component being policed write its own verdict-tree receipts. The finalizer closes that hole at the root. (W0-T7, W0-T8.)
- **`locked_brief_hash`.** `locked_brief_hash: str | None` = sha256 of `experiment.yaml` (the write-once lock), computed by the core `finalize_report()` at Stage 8; renderers never read `experiment.yaml`. The audit log records no brief hash today, so it is surfaced as a "recorded" receipt (core-written), NOT part of the VERIFIED gate. Optional; absent → "brief lock not recorded". (W0-T1, W0-T7.)
- **`build_provenance` ↔ `validate_chain` call shape.** `validate_chain(experiment_id, *, _root=...)` takes an id + root, not an `exp_dir`; `build_provenance` splits `exp_dir` into `experiment_id = exp_dir.name` + `root = exp_dir.parent` and promotes the test-only `_root` kwarg to a supported production call. (W1-T3, W3-T1.)
- **Half-migration status precedence.** A `schema_version==2` report with required scalars missing resolves to `UNVERIFIABLE` (not `DRAFT_UNVERIFIED`): the "can't-check" gate runs BEFORE tree-reproduction is attempted, so a missing scalar is never an accusation. Pinned by a W0-T9 fixture. (W3-T1.)
- **Canonical fixtures.** `report_v1.json` + `report_v2.json` are authored in W0-T9 as explicit deliverables — every downstream golden / red-path / cross-format test depends on the v2 fixture, so it cannot be left implicit. (W0-T9.)
- **Index perf / O(N).** Live-validate every row with a per-session cache; accept O(N) at realistic scale (tens). Above ~50 experiments, fall back to stored-status rows with a "re-verify" affordance. A row that trips the per-experiment 400ms `PerfBudgetExceeded` cap renders `UNVERIFIABLE`. Don't pre-optimize. (W6.)
- **Headline font.** Source Serif 4 (OFL) headline + Inter (OFL) body + JetBrains Mono (OFL) labels. Charter dropped — no legal diligence. (W4-T3.)

**Genuinely open:** none remaining.

---

*End of master plan.*
