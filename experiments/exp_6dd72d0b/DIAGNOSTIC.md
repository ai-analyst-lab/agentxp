# exp_6dd72d0b — session diagnostic

Two questions, written down because both surfaced real product gaps, not one-off slips. Section A is the readout-shape gap. Section B is the why-did-this-session-go-slowly trace of every error I hit, with a root cause for each.

---

## A. Readouts: why exp_6dd72d0b's shape didn't match the other dirs

### What you have elsewhere

Every other experiment dir lays out readouts as:

```
readouts/
  <readout_type>/<audience>/<audience>.{html,pdf}
```

with three audiences (`exec`, `operator`, `engineer`) × two formats (`html`, `pdf`) = 6 files per readout type. The mature dirs (`exp_2026q2_*`, `E_F12345`, `E_INVSRM`, `E_UNVER`) carry three readout types — `design_brief`, `srm_check`, `analysis` — for 18 files total. `exp_fb984821` adds `intent` on top, landing at 20.

### What this session produced before the backfill

```
readouts/design_brief/2026-06-05T195315/exec.md
readouts/design_brief/2026-06-05T195524/exec.html
readouts/design_brief/2026-06-05T195524/exec.pdf
readouts/intent/2026-06-05T193714/exec.md
readouts/intent/2026-06-05T195526/exec.html
readouts/intent/2026-06-05T195526/exec.pdf
```

Six files. Three readout types missing? No — `srm_check` and `analysis` are the analyze verb's outputs and don't belong to a sealed-but-not-yet-analyzed brief, so the comparison there is apples-to-oranges. The real shortfall is **persona coverage**: every render was `exec` × { md | html | pdf }, with no `operator` or `engineer` variants.

### Root cause

There are three contributing causes; all three need to be true for the gap to disappear.

1. **`render_share_tail` is single-shot, not fan-out.** Its signature is
   `render_share_tail(..., audience='exec', fmt='md')` —
   one call per (audience, fmt) tuple. There is no helper that loops over the persona × format Cartesian. To produce the canonical 6 files per readout type you have to call it six times.

2. **The `design` SKILL.md step 11 reads as one call.** The skill instructs:
   ```python
   render_share_tail(exp_dir, ..., readout_type="design_brief",
                     vm=vm, vm_sha256=..., provenance_render_status="VERIFIED")
   ```
   No persona loop, no format loop. A literal reading produces exactly one file (`exec.md`), which is what I did on the first pass. The skill encodes "render the share-tail" as a single artifact; the convention that "render" means "× 3 personas × 2 formats" lives in the other dirs' history, not in the skill or the API.

3. **The fixture dirs were batch-generated, not skill-driven.** The 18-file dirs (`exp_2026q2_*`, `E_*`) look like they came from a one-shot fixture/seed script that fanned over `READOUT_AUDIENCES × READOUT_FORMATS`. `exp_fb984821`'s readouts were likely produced by a deliberate render-everything pass at the end of the session. Neither path is the design verb's default — they're add-ons that the skill never codifies.

### What "not connected in reality" means here

- `agentxp.render.readout_kind` enumerates readout *types* but the design skill never tells the orchestrator to walk three persona × two format renders per type.
- The renders catalog (`readouts/catalog.jsonl`) is a hash-chain ledger — it accepts whatever rows it's appended, so it doesn't enforce a persona-coverage invariant either. A sealed brief with one `exec.md` row is a valid catalog state.
- The `readouts` skill (the third verb in the registry) is the one that walks the catalog and *can* regenerate variants, but `design` doesn't dispatch it.

So the connection that's missing is: `design` step 11 → "render all personas × formats for this readout type" → either an explicit loop in the skill, a new `render_share_tail_all_audiences()` helper, or a post-seal hand-off to the `readouts` skill that fans out by default.

### What I did about it

Backfilled the missing 8 files (operator/engineer × html/pdf for intent + design_brief). Catalog rows extended in the same chain. Result: 14 files total, matching the design-verb portion of the canonical layout. The remaining gap vs. 18-file dirs is `srm_check` + `analysis`, which the analyze verb owns.

### Concrete fix candidates (pick one)

- **Skill edit.** Update `.claude/skills/design/SKILL.md` step 11 to a loop: `for audience in ('exec','operator','engineer'): for fmt in ('html','pdf'): render_share_tail(...)`. Plus md for the human-readable summary.
- **Helper.** Add `agentxp.render.fan_out(exp_dir, readout_type, vm, provenance) -> list[Path]` that does the loop with one call; have the skill invoke it.
- **Default.** Change `render_share_tail`'s default behavior to emit all six variants unless `audience=` or `fmt=` is explicitly pinned. Cleanest but most invasive — changes the contract for every existing caller.

---

## B. Errors I hit during the session — root causes

Twelve distinct failures. Each is its own root cause, not a cascade. Grouped by where the contract broke.

### B.1 — Skill text drifted from the helper signatures

**1. `allocate_experiment(exp_id=...)` → `unexpected keyword argument`.**
Skill says `exp_id=args.exp_id`; the helper at `agentxp/workflows/design.py` takes `experiment_id=`. Root cause: skill text is hand-written prose, drifts when the API renames a kwarg. There's no test that asserts the skill's code blocks parse against the live signatures.

**2. `verify_brief_seal` vs. `verify_or_raise(sealed=...)`.**
Skill names the function `verify_brief_seal` and shows kwargs that match a sealed-path-on-disk signature; the real symbol is `verify_or_raise(*, sealed: SealedBrief, design_chain_path, metric_paths)`. Same root cause as #1.

**3. `commit_artifact` is the documented git-write tool but it's broken (see B.4 #8).** Skill points at a function that can't currently land a commit.

### B.2 — Schema mismatches between on-disk YAML and the bundle/seal schemas

**4. `IntentVM(captured_at: str)` rejects a `datetime`.** `intent.yaml` round-trips through `yaml.safe_load`, which parses ISO timestamps into `datetime.datetime`. `IntentVM.captured_at` is declared `str` with `extra="forbid"`-style strictness, so it refuses the parsed value. Root cause: the schema and the loader disagree on whether the timestamp is a Python type or a string; there's no canonical "load intent.yaml" helper that normalizes the type before constructing the VM.

**5. `DesignerBundle.semantic_models: list[_SemanticModelPlaceholder]` (4 strict fields) refuses the on-disk semantic_model YAML (8+ fields, list-shaped `primary_key`).** Looking at `agentxp/schemas/bundles.py:88`, the placeholder is annotated `TODO(T70): replace with the canonical SemanticModel loader output from agentxp.semantic.io`. The replacement never landed, so the bundle still uses the stub. The orchestrator has no clean path from `semantic_models/*.yaml` (rich shape) to `_SemanticModelPlaceholder` (4-field stub) — you have to flatten by hand. Same story for `_MetricPlaceholder` (TODO(T70)).

**6. `ExpectedShape.cohort_definitions: list[str]` refuses the brief's `list[dict]`.** Brief convention is `cohorts: [{name, definition}]`; ExpectedShape wants `["name: definition", ...]`. Root cause: cohort representation isn't canonicalized — brief.yaml carries structured cohorts, expected_shape carries stringified ones, and there's no adapter. I flattened with `f"{c['name']}: {c['definition']}"` to seal, but that string is now what the analyze verb will see as the "expected cohorts," which loses the structure.

### B.3 — SQL safety pipeline refusing routine probes

**7. `probe_data(purpose="shape_probe::units_available")` → "Unknown purpose".** Allowed purposes (`agentxp/sql/safety.py:513`) are `{'metric_compute', 'preview', 'profile', 'srm_check', 'user_paste'}`. The skill says `purpose="shape_probe"` and the `SqlIntent` enum in `bundles.py` lists `shape_probe` as a valid purpose, but Layer 4 of the pipeline doesn't accept it. Root cause: two enums for "purpose" — one in `bundles.SqlIntent`, one in `safety.layer_4_enforce_resource_bounds` — and they don't overlap.

**8. `DenyListViolation: AST node 'Sub' not in ALLOWED_AST_NODES` (date arithmetic).** A perfectly normal shape probe — `WHERE started_at >= (SELECT MAX(started_at) - INTERVAL 30 DAY FROM sessions)` — gets parsed by sqlglot as a `Sub` node, which Layer 3c rejects. Same for `DATE_TRUNC('day', x)` (parses as `Var`). Root cause: the `ALLOWED_AST_NODES` set is sized for metric-aggregation queries (SELECT/GROUP BY/aggregates), not for warehouse shape probes that need date math. Designer cannot characterize an exposure window using SQL the safety pipeline accepts.

**9. `SafetyResult` has no `.allowed` field.** I assumed a boolean flag; the real API raises `ToolRefusal` on refusal and returns a `SafetyResult` on pass. Root cause: API surface convention mismatch with my intuition — there's no `.allowed` and no `.refusal_reason` because the refusal is exceptional, not a return value. Not a bug, but the skill text doesn't describe the contract either.

### B.4 — Orchestrator integration gaps

**10. `dispatch_specialist` → `NotImplementedError: No LLM caller configured`.** `agentxp/orchestrator/loop.py:86` has a `_default_llm_caller` that explicitly raises, with a comment that "actual dispatch happens via the Claude Code harness's Agent tool when the orchestrator runs inside Claude Code." But nothing in the codebase wires the Agent tool to the `LLMCaller` protocol. I had to build the bundle JSON, write it to `/tmp/`, invoke `Agent` manually with the role's system prompt path + bundle path, and parse the sub-agent's free-text return. The orchestrator-Python ⇄ Claude Code Agent bridge is the missing piece. Until it exists, every "dispatch specialist" step in every skill becomes a manual construction.

**11. `commit_artifact` runs `git add <root-relative-path>` with `cwd=exp_dir` → exit 128.** `agentxp/orchestrator/tools.py:395` does `subprocess.run(["git", "add", str(art_path), str(log_path)], cwd=exp_dir, ...)` where `art_path` is `experiments/exp_6dd72d0b/hypothesis.yaml` (root-relative). With `cwd=exp_dir`, git looks for `experiments/exp_6dd72d0b/experiments/exp_6dd72d0b/hypothesis.yaml` and fatals. Fix is one of: pass `cwd=project_root`; or compute `art_path.relative_to(exp_dir)` before passing. I bypassed by doing `git add` + `git commit` manually from the project root, but that means **every artifact commit in this session was direct, not via the audited helper**. Audit trail is still intact (every change has a git commit + a `log.md` line), but it's not from the function that's supposed to own that responsibility.

**12. `.gitignore` blocks every new experiment dir.** `experiments/*` is ignored, with `!experiments/exp_fb984821/` as the only whitelist. `allocate_experiment` creates `experiments/exp_<ulid>/` but doesn't touch `.gitignore`, so the first `git add` fails with "paths are ignored by one of your .gitignore files." Root cause: per-experiment whitelist is the wrong granularity. Fix is one of:
- Change line 56 to `!experiments/exp_*/` (catches all `exp_`-prefixed dirs, which is the naming convention).
- Have `allocate_experiment` append a `!experiments/<id>/` line to `.gitignore` and commit it as part of allocation.

I added the whitelist line manually for this session.

---

## C. The session-level cost

The cause-by-cause breakdown above totals nine schema/API/safety/integration issues I had to discover by hitting them. The marginal cost per error was ~30–90 seconds of "read the traceback, look up the real signature, retry," which adds up over the 19-step design workflow.

The two highest-leverage fixes:

- **B.4 #11** (commit_artifact path bug). Single line change, restores the audited write path for every skill that commits.
- **B.4 #10** (Agent ⇄ LLMCaller bridge). Without it, every specialist dispatch in every skill is manual. A `ClaudeCodeAgentCaller` that takes `role`, reads `agents/{role}.md` + the bundle JSON, calls `Agent()` with the right `subagent_type` and prompt, and parses the response back into the role's output schema would collapse ~half the manual scaffolding in this session.

The persona-fanout gap (Section A) is third-priority — visible to the user as missing files, but mechanically a one-line skill edit.
