# Hostile accuracy review — Module 10 (`10_presentation.md`) vs. AgentXP source

Reviewer stance: adversarial fact-check. Every claim traced to source `file:line`.
Date: 2026-06-01. Source tree: `/Users/shanebutler/projects/agentxp/`.
Scope: `docs/learn/10_presentation.md` + the Module-10 references in
`docs/learn/README.md` (module-map row 10, aha-index rows 8 & 9, progress tracker).

## Verdict

**Overall grade: A− (the deepest, most accurate module in the course — the axiom,
the pure/impure split, the three-state machine, the line citations, and the labs
are almost all verbatim-correct; let down by one wrong sentence about glance and a
couple of fabricated mechanisms).**

Nearly every line-number citation in this module lands on the cited content
exactly (`distill` 168, `distill_index` 205, `ProvenanceCache` 264, `_cant_check_reason`
99–118, `build_provenance` 121–257, ReportVM 192 / `to_index_row` 215 / ViewBundle
238 / `render_status` 252, base.py "36 lines", index `_discover` 80 / `_build_row` 96,
report.py `--index` xor 215–228 / ViewBundle 341 / EXIT_WARNING 373–374). The
pure-renderer axiom, the `str`-typed `MetricRow`, the strict-precedence steps 0–5,
the can't-check gate, the Wave-7 identity fix, the missing-extra string, and the
sorted "available now" list all check out against the code. The labs would behave
essentially as written.

The one outright wrong claim is that glance emits "ANSI via `brand.ansi()`" — the
shipped glance adapter is plain text by contract and calls no such thing. Two lab
asides invent enforcement mechanisms the code does not have (a `@runtime_checkable`
isinstance check; a `test_cross_format_equality.py` that pins json/csv).

**Count: 1 WRONG, 5 IMPRECISE.**

---

## WRONG claims

### W1. glance does NOT emit ANSI / use `brand.ansi()` — it is plain text by contract
- **Curriculum** (`10_presentation.md:258-259`, step 4 adapter list): "`glance.py` —
  the 3-line terminal default (**plain text + ANSI via `brand.ansi()`**)."
- **Ground truth** (`agentxp/render/adapters/glance.py:10-13`): the module docstring
  states the opposite, verbatim — *"Glance is PLAIN TEXT by contract: **no brand
  colours**, so it pastes cleanly into a PR comment or a Slack message."* The
  `GlanceAdapter.render` body (`glance.py:41-64`) builds `line1`/`line2` from plain
  VM strings + `replay_line(...)`; it never imports `brand` and never calls
  `brand.ansi()`. (`brand.ansi()` does exist at `agentxp/render/brand.py:149`, and
  brand.py's own docstring at `:13` mis-advertises it as "for glance" — but the
  shipped glance adapter does not use it. The operative truth for the adapter the
  module is describing is: no ANSI.)
- **Fix:** "`glance.py` — the verdict-first terminal default, **plain text, no ANSI**
  (so it pastes cleanly into a PR comment or Slack)."

---

## IMPRECISE / misleading claims

### I1. glance is "3-line" — it is 2 always-on lines + an optional CLI hint line
- **Curriculum** (`10_presentation.md:258`): "the **3-line** terminal default."
- **Ground truth** (`glance.py:4-9, 41-64`): the adapter renders **two** lines that
  always print (verdict line + receipt line); the third "hint" line is CLI chrome
  appended by `report.py:366-369` **only** on an interactive, non-quiet stdout —
  `glance.py:8` calls line 3 "(CLI chrome)". The pinned test is named
  `test_glance_format_**two**_lines` (`tests/cli/test_report.py:78`). On a piped/quiet
  stream the output is two lines. ("3-line" matches glance.py's own header line 1,
  so it is defensible, but for an expert audience say "2 lines + an optional hint.")
- **Fix:** "the 2-line (+ optional hint) verdict-first terminal default."

### I2. Lab F's "`@runtime_checkable` isinstance check" is a mechanism the code never runs
- **Curriculum** (`10_presentation.md:444-446`): "a registered class that's missing
  `default_filename` **fails the `@runtime_checkable` `isinstance` check**, not at
  import."
- **Ground truth:** there is **no** `isinstance(..., FormatAdapter)` call anywhere in
  the runtime (grep of `agentxp/` is empty). `ADAPTERS` is a plain dict
  (`adapters/__init__.py:22-29`) and `get_adapter` is just `ADAPTERS[format_id]`
  (`:32-34`); the CLI calls `adapter.render(bundle)` and only touches
  `default_filename` when `--out` plumbing needs it. A class missing
  `default_filename` would raise `AttributeError` **at call time** (and only on an
  `--out` path), not fail an isinstance check. `@runtime_checkable` (`base.py:16`)
  *enables* such a check but nothing performs one.
- **Fix:** "a registered class missing `default_filename` fails at *call time* with
  an `AttributeError` (the Protocol is structural — nothing isinstance-checks it at
  registration)."

### I3. Lab 10a cites `test_cross_format_equality.py` for a json/csv equality it doesn't cover
- **Curriculum** (`10_presentation.md:362-370`): Lab 10a renders **md/json/csv/html**
  and claims "(The repo pins it as a test: `tests/render/test_cross_format_equality.py`.)"
- **Ground truth:** `tests/render/test_cross_format_equality.py:70-86`
  (`test_lift_ci_verdict_byte_identical_across_formats`) asserts byte-identity across
  **md / html / card / index** — **not** json or csv. The json/csv byte-identity
  claim is actually pinned in `tests/render/test_data_adapters.py:114`
  (`test_numbers_byte_identical_across_md_json_csv`). The lab's own json/csv lines are
  pinned by a *different* test file than the one cited.
- **Fix:** cite both: "`test_cross_format_equality.py` (md/html/card/index) and
  `test_data_adapters.py::test_numbers_byte_identical_across_md_json_csv` (md/json/csv)."

### I4. Lab 10b implies the tampered-chain test covers all formats; it asserts only `md`
- **Curriculum** (`10_presentation.md:381-386`): lists md admonition + footer, card
  ribbon, json `render_status == "draft_unverified"`, and "**every** format returns
  `EXIT_WARNING`," then: "(Pinned: `test_report.py::test_tampered_chain_hash_is_mismatch_warning`.)"
- **Ground truth** (`tests/cli/test_report.py:228-240`): the test tampers
  `chain_hash`, renders **`--format md` only**, and asserts `EXIT_WARNING` +
  `"Chain: MISMATCH"` + `"draft_unverified"` in the md output. The *behavioural*
  claim that any format returns `EXIT_WARNING` is sound (the code keys the exit code
  off `bundle.render_status` independent of format — `report.py:373-374`), but the
  cited test does not exercise card/json/"every format." The card-ribbon and json
  claims are true from the code (`card.py:87`, `data.py:36`) but not from *that*
  test. Tighten: "the md path is pinned by `test_tampered_chain_hash_is_mismatch_warning`;
  the all-format EXIT_WARNING follows structurally from `report.py:373-374`."

### I5. "six output formats" vs the diagram's nine — count is right but the wording invites confusion
- **Curriculum** (`10_presentation.md:6-7` goal, `:357` Lab 10a "every text format,"
  `:493` teach-back): "trace a single number ... to **six** output formats." The
  two-spine diagram (`:86`) lists **nine** ids (`md · glance · html · card · json ·
  csv · png · pdf · index`).
- **Ground truth:** the six *text/registered single-report* formats are md, glance,
  html, card, json, csv (`adapters/__init__.py:22-29` — exactly six entries); png/pdf
  are the deferred extra and index is the cross-experiment navigator. The "six" is
  correct for the registered formats, but the module never reconciles it with the
  nine-item diagram, and Lab 10a actually shows only four commands (md/json/csv/html,
  `:362-365`). No factual error; flag for clarity — say "six registered formats
  (png/pdf are the optional extra; index is the navigator)."

---

## Labs soundness

- **Lab 10a (one number, six formats)** — SOUND. `--format md|json|csv|html` are all
  real flags (`report.py:86`, `adapters/__init__.py`); `--out` works for html
  (`report.py:351-361`). The json path `['vm']['metric_table'][0]['lift_str']` matches
  `data.py:34-37` (dumps `{"vm": ..., "provenance": ...}`) and `viewmodel.py:53`
  (`lift_str`). csv row 1 = primary metric matches `data.py:76-89` (header row, then
  one row per metric, primary first). Citation nit in I3.
- **Lab 10b (tamper → DRAFT everywhere)** — SOUND. Setting `chain_hash="0"*64`
  produces `hash_matches=False` → DRAFT_UNVERIFIED (`provenance.py:169,239-243`); md
  stamps the `⚠ DRAFT — UNVERIFIED` admonition + `chain integrity: FAILED` footer
  (`markdown.py:31-38`); card strikes the ribbon (`card.py:87`, `is_draft`); json
  carries `provenance.render_status` (`data.py:36`); CLI returns `EXIT_WARNING`
  regardless of format (`report.py:373-374`). The doctored field is `chain_hash`,
  which is correct (the can't-check gate only trips when it is *absent* —
  `provenance.py:108`; a present-but-wrong hash flows to the mismatch path). Citation
  nit in I4.
- **Lab 10c (try to make an adapter lie)** — SOUND. `MetricRow` carries only
  `lift_str`/`ci_95`/`ci_90`/`name`/`direction`/`status` as **str** (no floats) —
  `viewmodel.py:47-56`. The adapter is handed a `ViewBundle`, never the `Report`
  (`base.py:27`, `viewmodel.py:248-250`). The "force it and cross-format equality goes
  red" claim is sound given `test_cross_format_equality.py:70`.
- **Lab 10d (fail fast on missing extra)** — SOUND and verbatim-accurate. Without the
  extra, `report.py:259-264` prints exactly:
  `format 'png' ships in the optional agentxp[png] extra (pip install 'agentxp[png]'
  then: playwright install chromium); available now: card, csv, glance, html, json, md`
  — `_DEFERRED_FORMATS["png"]` = "the optional agentxp[png] extra" (`:41`); the list is
  `', '.join(sorted(ADAPTERS))` → the six registered ids in sorted order (matches the
  module's "available now: card, csv, glance, html, json, md"). Return is
  `EXIT_USER_ERROR` = **1** (`cli/exit_codes.py`), matching "exit code 1." Pinned:
  `tests/cli/test_report.py:113` (`test_png_when_extra_absent_fails_fast`). The
  follow-on "`--format png` *with* the extra but *without* `--out` →
  `format 'png' is binary; --out is required`" matches `report.py:298-300` and
  `tests/render/test_raster.py:103` (`test_cli_png_requires_out`).
- **Lab 10e (break the index without breaking the page)** — SOUND. Corrupting one
  `report.json` to `{ not valid json` yields `JSONDecodeError` →
  `IndexRowVM.error_row(exp_id, "report.json is not valid JSON")` (`index_html.py:113-114`),
  status UNVERIFIABLE (`viewmodel.py:151-167`); the good experiment renders; the page
  still writes and `_render_index` returns `EXIT_OK` (`report.py:198-205`). Per-row
  isolation is real (`index_html.py:96-139`).
- **Lab F (add a `txt` adapter)** — SOUND as a build exercise. The DRAFT stamp pattern
  (`!! DRAFT — UNVERIFIED: {status_reason}` on `RenderStatus.DRAFT_UNVERIFIED`) mirrors
  `markdown.py:31-35` / `glance.py:61-62`. Registering via `ADAPTERS` is correct
  (`adapters/__init__.py:22-29`). The unknown-format message `unknown format 'txt';
  choose from: …` matches `report.py:268-272`. Two asides need fixing: the
  isinstance-check mechanism (I2) and the cross-format-equality test scope (it does
  not currently include json/csv — adding a `txt` case is fine, but see I3).

---

## Confirmed-correct highlights (do NOT "fix" these)

- **The pure-renderer axiom / sole-formatter claim** — `distill.py:1-15` docstring
  states PURE / SOLE formatter / SOLE version-skew / verbatim prose verbatim. The four
  formatting primitives are exactly `_fmt_signed`/`_fmt_lift`/`_fmt_ci`/`_sample_pct`
  at `distill.py:40-59` (module's "lines 40–59" — exact). `MetricRow` strings-only is
  the axiom in the type (`viewmodel.py:47-56`).
- **`_metric_table` / `_chart_data` cites** — `distill.py:82-101` and `:133-150`
  (exact). "Status without re-derivation" via `_guardrails_violated` reading
  `edge_case_flags` — `distill.py:104-110` (the module's claim is precise). Per-arm
  counts Optional → srm_split omits — `distill.py:148-150`, `viewmodel.py:100-101`.
- **distill / distill_index / "index only counts statuses"** — `distill.py:168` and
  `:205-228`; `distill_index` re-derives nothing and only tallies statuses (exact).
- **viewmodel cites** — docstring 1–16 (one-directional import rule, exact); ReportVM
  192, `to_index_row` 215 (reuses `lift_str`/`ci_95`, no reformat), ViewBundle 238
  (the inseparability docstring sentence is verbatim, `:243-245`), `render_status`
  property 252 — all exact.
- **Three-state RenderStatus + strict precedence 0–5** — `provenance.py:10-30, 57-61`
  (VERIFIED/DRAFT_UNVERIFIED/UNVERIFIABLE, one-directional). `_cant_check_reason`
  99–118 (exact; schema v1 / no chain_hash / no log.jsonl / missing tree scalar).
  `build_provenance` 121–257: step 1 recompute `canonical_chain_hash` (`:160`), step 2
  `hash_matches` (`:169`), step 3 `validate_chain` with `PerfBudgetExceeded` → UNVERIFIABLE
  (`:177-183`), step 4 `receipts._reproduce_verdict` None → UNVERIFIABLE (`:204-216`),
  step 5 VERIFIED iff all three (`:219`), else DRAFT with first-failing reason in
  precedence **chain → hash → tree** (`:236-248` — exact order). `except Exception …
  never crash a render` at `:161,188` (module cites 161/188 — exact). `ProvenanceCache`
  264 (exact). `_reproduce_verdict` exists at `receipts.py:70`.
- **Adapter Protocol + registry** — `base.py` is 36 lines; `FormatAdapter` is a
  `@runtime_checkable` Protocol with `format_id`/`binary`/`requires_node` + `render`
  + `default_filename` (`base.py:16-33`). Docstring "Adding an output format = adding
  one adapter … NEVER re-derives a number … NEVER decides verification status"
  verbatim (`base.py:3-6`). `ADAPTERS: dict[str, FormatAdapter]` maps md/glance/html/
  card/json/csv (`__init__.py:22-29`); png/pdf are NOT in it (live in raster behind the
  extra). html/card defaults are editorial-light, CLI rebuilds configured instances
  (`__init__.py:18-21`, `report.py:280-290`).
- **markdown / card / html behaviour** — md DRAFT top admonition + `chain integrity:
  FAILED` footer (`markdown.py:31-38`); card diagonal ribbon on the hero, never the
  footer (`card.py:15-17, 87`); html self-contained, no `<script>`, `--audience
  exec|skeptic` flips audit trail via `show_audit` (`html.py:8-21, 147-159`,
  `report.py:280-284`).
- **Index per-row isolation + Wave-7 identity fix** — `_discover` requires `state.yaml`,
  sorted (`index_html.py:80-93`); `_build_row` isolates every failure, 400ms cap
  per-experiment (`index_html.py:96-139`, `:13-15`); inline vanilla JS degrades
  gracefully, links go out, no iframe (`:17-21`). Identity = `exp_dir.name` via
  `model_copy(update={"experiment_id": exp_dir.name})` (`index_html.py:139`),
  display name kept as `experiment_name` — the module's Wave-7 claim is exact, and
  `BUILD_STATUS_PRESENTATION.yaml:553-563` confirms it was a real W7 defect/fix.
- **raster + pyproject extra** — rasterizers render nothing new (PNG screenshots the
  card, PDF prints exec html), `wait_until="networkidle"`, lazy playwright import
  inside `_rasterize` at `raster.py:46`, `is_available()` at `:26-36`, both `binary=
  True`/`requires_node=True` (`:64-65, 86-87`). `pyproject.toml:59-64`:
  `png = ["playwright>=1.40"]` with the two-step install note — exact.
- **report.py drive** — `--index` xor exp_id 215–228; `_resolve_format` order
  `--format > --audience sugar > isatty default` at 121-130 (operator→isatty,
  exec→html, skeptic→md, public→card — `:47-52`); deferred fail-fast before disk at
  254–265; usage walls (glance+`--out` `:293-295`, binary-no-`--out` `:298-300`);
  load→validate (`extra="forbid"`, ValidationError → EXIT_FATAL `:328-335`) → bundle
  `ViewBundle(vm=distill(report), provenance=build_provenance(report, exp_dir))` at
  **341** → DRAFT → EXIT_WARNING at **373-374**. All exact.
- **README Module-10 references** — module-map row 10 (`README.md:89`) and progress
  tracker (`:157`) accurate; aha-index rows 8 & 9 (`:108-109`) map to Module 10 and
  the header "nine load-bearing insights" (`:93`) matches the 9 rows. "Trace one
  number to six formats" is consistent with the six registered formats (see I5).
