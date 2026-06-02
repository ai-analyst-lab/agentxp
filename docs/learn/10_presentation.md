# Module 10 — The presentation layer (share-out without losing the proof)

> **Goal:** Understand the *second spine* — the one that turns a finalized
> `report.json` into something a stakeholder, a skeptic, or future-you can read.
> By the end you can state the pure-renderer axiom and say why it is the whole
> design, trace a single number from `report.json` to six output formats without
> it being re-computed once, explain the three-state `RenderStatus` and why polish
> can never outrun the proof, and add a new output format yourself — predicting,
> before you run anything, which guardrail catches you if you cheat.

---

## Why (the design reasoning)

Every module before this one taught the *analysis* spine: how a CSV becomes a
verdict you can replay (Modules 1–3) and trust (Module 4). That spine ends at
Stage 8, which commits one artifact: `report.json`, the canonical structured
record of the run. Everything in *this* module happens strictly *after* that — it
never analyzes anything. It answers a different question: **once the answer
exists, how do you show it to a human without quietly corrupting it?**

That sounds like a cosmetic problem. It is not. The moment you let a renderer be
"helpful" — round a number for the headline, recompute a percentage because the
stored one looked off, drop the chain-hash receipt because it's ugly in a social
card — you have built a *second* place where the truth lives, and the two places
will drift. The day they drift is the day the product's headline promise ("two
reviewers replay the log and reach the same answer") becomes a lie that *looks*
fine, because the polished output is the one everybody reads.

So the presentation layer is built on a single axiom, and the whole module is
just consequences of it:

> **Aha — `report.json` is the only source of truth, and every output is a *pure
> renderer* over it. Adding a format means adding a renderer, never re-deriving a
> number.** A renderer that does arithmetic is a second source of truth in
> disguise. The discipline isn't "be careful with numbers" — it's structural:
> there is exactly one function allowed to turn a number into a string, and
> adapters physically cannot reach the raw numbers to reformat them.

Two consequences fall straight out of that axiom, and they are the two halves of
the layer:

1. **Numbers are formatted exactly once.** A pure function, `distill()`, projects
   the canonical `Report` into a flat, fully-formatted `ReportVM` — every lift,
   CI, and percentage is already a *string* by the time any adapter sees it. The
   adapters interpolate strings; they never see a `float`.
2. **Proof travels with polish, inseparably.** The verification receipts (chain
   hash, chain-validation result, verdict reproduction) are recomputed by a
   *separate, impure* function, `build_provenance()`, and the two are welded
   together into a `ViewBundle` before any adapter runs. An adapter cannot emit
   the verdict while dropping the receipt, because **both arrive in the same
   object.**

> **Aha — the split between `distill()` (pure) and `build_provenance()` (impure)
> is the load-bearing design decision of the whole layer.** Formatting must be
> pure so it's deterministic, offline, and trivially testable; verification must
> be impure because it has to touch disk and recompute hashes. Conflating them
> would make every renderer touch the filesystem and make "the same report always
> renders the same string" impossible to guarantee. Keeping them apart — and then
> *bundling their outputs* — is what lets polish and proof both be true at once.

The honest framing the rest of the course uses applies here too: this is the
*share-out* spine, distinct from the *analysis* spine. Conflating them is the
Module-10 version of the "two surfaces" confusion in the README. Analysis decides
*what's true*; presentation decides *how it's shown* — and its only job is to not
lie in the translation.

---

## The two-spine map (read this before the walkthrough)

```
ANALYSIS SPINE  (Modules 1–4)         SHARE-OUT SPINE  (this module)
─────────────────────────────         ─────────────────────────────────────────
CSV → 11 stages → verdict tree         report.json ─ distill() [PURE] ─→ ReportVM
        → integrity chain                         │                         │
        → Stage 8 commits ─────────────→ report.json                        │
                                                  │                         ▼
                                       build_provenance() [IMPURE] ─→ Provenance
                                                  │                         │
                                                  └──── CLI assembles ───────┘
                                                              ▼
                                            ViewBundle(vm, provenance)
                                                              ▼
                                  one of N adapters .render(bundle) → str | bytes
                                  (md · glance · html · card · json · csv · png · pdf · index)
```

The CLI verb that drives all of this is `agentxp report` (`agentxp/cli/report.py`)
— the presentation counterpart to `agentxp audit`. It performs **no analysis**: it
loads `report.json`, validates it, calls `distill()`, calls `build_provenance()`,
assembles the `ViewBundle`, and hands it to exactly one adapter. The verb never
grows a per-format branch beyond output plumbing — that's the axiom enforced as a
code-shape rule.

Source-of-truth doc for everything below: `PRESENTATION_LAYER_MASTER_PLAN.md`
(the multi-persona master plan), and the build log in
`BUILD_STATUS_PRESENTATION.yaml` (Waves 0–8).

---

## Walkthrough — the layer in code

### 1. `distill()` — the one place numbers become strings (`agentxp/render/distill.py`)

Open it and read the module docstring first; it states the contract as four
promises: **pure** (no I/O, no clock, no network, no numpy — same `Report` in,
equal `ReportVM` out, input never mutated); **sole formatter** (every number a
human sees is formatted here, once); **sole version-skew handler** (it branches on
`report.schema_version` so no downstream code has to — a v1 report distills to a
valid, sparser VM); and **carries agent prose verbatim** (`verdict_rationale` and
each `UncertaintyNote.detail` pass through untouched — drift there is a bug).

The formatting primitives are the *entire* numeric vocabulary of the product, and
there are only four of them (lines 40–59):

- `_fmt_signed(x)` → `f"{x:+.4g}"` — the signed compact float, e.g. `+0.032`.
- `_fmt_lift(absolute, relative)` → `"+0.032 (+18.0%)"` — the headline lift.
- `_fmt_ci(lower, upper)` → `"[+0.014, +0.05]"` — a CI interval.
- `_sample_pct(observed, required)` → a rounded percent, or `None` when either is
  absent (it *never fabricates* a denominator).

Every other file in the layer is forbidden from formatting a number. If you find
an `f"{x:.1f}"` in an adapter, you have found a bug — that's the rule, and Lab 10c
makes you go prove it.

Two design notes worth pausing on:

- **Status without re-derivation** (`_metric_table`, lines 82–101). The primary
  row carries the *committed* verdict; guardrail and negative-control rows are
  tagged `"clear"`; segment rows are tagged `"segment"`. A real guardrail
  *violation* is surfaced **separately**, via `_guardrails_violated()` reading the
  committed `edge_case_flags` — `distill()` never re-decides whether a guardrail
  was breached. It reads the decision the analysis spine already committed.
- **Charts plot stored numbers, never inferred ones** (`_chart_data`, lines
  133–150). The `ChartData` carrier copies the primary metric's stored values
  through *verbatim* so `charts.py` can draw an inline SVG without touching the
  canonical `Report`. Per-arm counts are `Optional`: absent → the SRM-split chart
  **omits** rather than inventing a split. (Same discipline as `_sample_pct`.)

The public entry point is `distill(report) -> ReportVM` (line 168). There's a
second pure entry, `distill_index(rows) -> IndexVM` (line 205) — but read its
docstring carefully, because it teaches a subtlety: the index can't resolve a
render status purely (that needs the impure `build_provenance`), so the *index
adapter* builds the rows at the I/O boundary and `distill_index` only **counts**
the already-resolved statuses. It re-derives nothing. We come back to it in step 5.

### 2. The view-models — flat, preformatted, `extra="forbid"` (`agentxp/render/viewmodel.py`)

This is the data contract every adapter renders against. Read the module docstring
(lines 1–16): it draws the same layering diagram as above and states the
one-directional import rule — `viewmodel.py` imports the provenance contract, but
`provenance.py` *never* imports this module.

The sub-models (`MetricRow`, `Diagnostics`, `ChartData`, `AuditRow`, `DesignCard`)
all carry the comment that matters: *"all strings are PREFORMATTED by distill()."*
`MetricRow.lift_str` is a `str`, not a `float`. That's not laziness — it's the
axiom encoded in the *type*. An adapter literally cannot reformat a lift, because
by the time it has the lift, it's already a string.

Note which fields are `Optional` and why: `Diagnostics.n_observed/n_required/
sample_pct` are optional because a pre-widening (schema v1) report doesn't carry
them, and `distill()` maps a missing value to `None` rather than fabricating one.
The view-model's optionality *is* the version-skew handling, made visible.

Then the two assembled types at the bottom:

- **`ReportVM`** (line 192) — the full flat projection one adapter renders. Field
  names match `templates/experiment-report.md` so the markdown template renders
  against it unchanged. It has a `to_index_row(render_status)` method (line 215)
  that *reuses* the already-formatted primary `lift_str`/`ci_95` rather than
  reformatting — the index borrows strings, never numbers.
- **`ViewBundle`** (line 238) — the thing every adapter actually receives:
  `vm: ReportVM` **+** `provenance: Provenance`. Read its docstring; it states the
  inseparability guarantee in one sentence: *"Bundling the receipts WITH the
  numbers is the structural guarantee that polish never travels without proof."*
  Its `render_status` property (line 252) just forwards `provenance.render_status`.

### 3. `build_provenance()` — the impure receipts (`agentxp/render/provenance.py`)

This is the verification half, and it's the bridge back to Module 4 — it's the
*reader* of the integrity spine you learned to break there. Read the module
docstring (lines 1–31): it defines the **three-state, one-directional**
`RenderStatus`:

- **VERIFIED** (green) — requires *all* of: `log.jsonl` present, stored
  `chain_hash` present, recomputed hash == stored, `validate_chain` ok, *and* the
  verdict tree reproduces.
- **DRAFT_UNVERIFIED** (red) — an *active* failure: a hash mismatch or a
  tree-reproduction failure. This is an **accusation**, reserved for real
  contradictions.
- **UNVERIFIABLE** (neutral gray) — "can't check": schema v1, or a missing
  `chain_hash`/`log.jsonl`, or a half-migrated v2 missing a reproduction scalar.
  **Not** an accusation.

> **Aha — the status machine is one-directional: any "can't check" demotes, and
> nothing ever promotes a doubt into a green checkmark.** This is the same honesty
> principle as Module 4's "never claim verified off a stored hash." A renderer
> that *couldn't* verify must say so in neutral gray, not paper over it. The three
> states exist precisely so "I checked and it's wrong" (red) is never confused
> with "I couldn't check" (gray) — collapsing those two is how trust dashboards
> lie.

`build_provenance(report, exp_dir)` runs in strict precedence (lines 121–257),
and you should trace each step against what you broke in Module 4:

0. **The can't-check gate** (`_cant_check_reason`, lines 99–118) runs *first* —
   schema v1 / no `chain_hash` / no `log.jsonl` / a missing tree-repro scalar all
   resolve UNVERIFIABLE before any reproduction is attempted.
1. Recompute `canonical_chain_hash(exp_dir)` — *never trust the stored value*
   (this is Module 4's replay hash).
2. Compare recomputed vs stored → `hash_matches`.
3. Run `validate_chain` (Module 4's five invariants). A `PerfBudgetExceeded`
   blow-out degrades to UNVERIFIABLE — a slow check is a "can't check," never an
   accusation.
4. Reproduce the verdict from the recorded inputs (`receipts._reproduce_verdict`).
   A `None` (incomplete inputs) → UNVERIFIABLE, not a contradiction.
5. **VERIFIED iff** hash matches *and* `cv.ok` *and* the verdict reproduces.
   Otherwise → DRAFT_UNVERIFIED with the *first-failing* reason (precedence:
   chain → hash → tree).

The whole `except Exception … never crash a render over verification` pattern
(e.g. lines 161, 188) is deliberate: a verification that errors out demotes the
status; it never takes down the render. Polish degrades gracefully to "unproven,"
it never crashes.

`ProvenanceCache` (line 264) memoizes by resolved `exp_dir` so rendering six
formats of one experiment in one CLI run hashes the log *once*.

### 4. The adapter Protocol and registry (`adapters/base.py`, `adapters/__init__.py`)

The contract is tiny (`base.py`, 36 lines). `FormatAdapter` is a
`@runtime_checkable` Protocol with three class attributes — `format_id` (stable
short id), `binary` (True ⇒ `render` returns `bytes`, e.g. PNG/PDF), `requires_node`
(True ⇒ needs an external engine like a browser) — and two methods: `render(bundle)
-> str | bytes` (pure, no disk writes) and `default_filename(bundle) -> str`.

Read the docstring's one-line statement of the whole layer: *"Adding an output
format = adding one adapter that consumes the bundle. An adapter NEVER re-derives a
number … and NEVER decides verification status."* The `binary`/`requires_node`
flags existed from day one so the CLI can fail fast on a heavy/absent dependency
*without importing it*.

The registry (`adapters/__init__.py`) is one dict, `ADAPTERS: dict[str,
FormatAdapter]`, mapping `format_id → instance`: `md`, `glance`, `html`, `card`,
`json`, `csv`. (The `html`/`card` entries are editorial-light defaults; the CLI
builds a configured instance when `--theme`/`--audience` are passed.) `png`/`pdf`
are deliberately **not** here — they live behind the optional extra (step 6).

The shipped adapters, by tier:

- **`markdown.py`** — the reference renderer. Wraps the existing §21 markdown
  renderer and appends `footer_block(prov)`. Read lines 28–39: a DRAFT_UNVERIFIED
  status stamps a **top admonition** (`> ⚠ DRAFT — UNVERIFIED`) so a reader can't
  miss it above the verdict, plus a blunt `chain integrity: FAILED` footer line.
  UNVERIFIABLE stays calm. This is the DRAFT-stamping pattern every visual adapter
  mirrors.
- **`glance.py`** — the 3-line terminal default (plain text + ANSI via
  `brand.ansi()`).
- **`html.py`** — the self-contained exec one-pager (inlined CSS, base64 fonts,
  inline SVG charts, no CDN, no `<script>`). `--audience exec|skeptic` flips the
  audit-trail section.
- **`card.py`** — the pixel-locked 1200×1500 social card. DRAFT strikes a diagonal
  ribbon across the verdict hero (never the footer — the footer is the croppable
  part of a screenshot).
- **`data.py`** — `json` (the faithful `{vm, provenance}` dump) and `csv` (one row
  per headline metric). Step 7.

### 5. The index — the only adapter that walks a directory (`adapters/index_html.py`)

Every other adapter renders one bundle; `render_index` renders the
cross-experiment navigator. Read the docstring (lines 1–22). It discovers
experiments the way `cli/list.py` does — `_discover()` (line 80): a child dir is an
experiment iff it holds a `state.yaml`, sorted for byte-stability — projects each
through the same `distill()`, resolves each row's status with `build_provenance()`,
and aggregates with `distill_index()`.

> **Aha — per-row isolation is the load-bearing invariant of the index.** One
> unreadable or unvalidatable experiment renders a status-only ERROR row
> (UNVERIFIABLE) and *never aborts the page* (`_build_row`, line 96). The 400ms
> `PerfBudgetExceeded` cap is *per experiment*, so N experiments are N independent
> budgets — a single slow row degrades to gray, it doesn't sink the navigator.
> This is the same "surface the problem as data, don't crash" stance as Module 4's
> `validate_chain` returning violations instead of raising.

The page is self-contained like html/card; the one departure is a small block of
inline vanilla JS for client-side filter/sort that **degrades gracefully** — every
row is server-rendered, so the table is complete with JS off. Links go *out* to
each experiment's `report.html` + `audit.html` (no iframe).

> **Aha — identity is the directory name, not the embedded `experiment_id`.** A row's
> identity (and therefore its out-links) is `exp_dir.name`, because that's what
> every CLI verb (`agentxp report/audit <id>`) resolves against. A directory
> renamed from the id its `report.json` was minted under would otherwise emit dead
> links. (This was a real defect — Wave 7 in the build log; the fix stamps
> `experiment_id = exp_dir.name` while keeping the embedded name as the
> human-readable display string.) The lesson: *display* name and *resolve* name are
> two different things, and links must use the one the CLI can resolve.

### 6. Binary formats behind an optional extra (`adapters/raster.py`)

Read this adapter's docstring (lines 1–14). The key insight: **the rasterizers
render nothing new.** `PngAdapter` screenshots the existing `card` page;
`PdfAdapter` prints the existing exec `html` page. Because those pages are already
fully self-contained (inlined CSS, base64 fonts, inline SVG, no CDN), the
rasterizer hands headless Chromium a *single string* with `wait_until="networkidle"`
and never touches the network. No new numbers enter the system at the PNG stage —
a PNG is a photograph of an HTML page that was itself a pure render of the VM.

The optional-dependency discipline is the other half:

- `playwright` is imported **lazily**, inside `_rasterize` (line 46) — the module
  imports fine *without* the extra installed, so the CLI can probe
  `is_available()` (line 26, tries `import playwright.sync_api`) and fail fast.
- Both adapters set `binary = True` (CLI requires `--out`) and `requires_node =
  True` (external engine).
- `pyproject.toml` declares the extra: `png = ["playwright>=1.40"]`, and the
  install hint names the *second* step (`playwright install chromium`) because the
  pip install alone doesn't fetch the browser binary.

> **Aha — a heavy/optional format fails fast by *name*, never by ImportError.**
> The CLI (`report.py`, lines 254–266) checks `raster.is_available()` *before
> touching disk* and, when absent, prints exactly which extra ships png/pdf and
> the two install steps — `pip install 'agentxp[png]' then: playwright install
> chromium`. An opaque `ModuleNotFoundError: playwright` would be a worse version
> of the same information. Optional dependencies are a UX problem, and the
> `binary`/`requires_node` flags + `is_available()` probe are the UX solution.

### 7. The CLI verb ties it together (`agentxp/cli/report.py`)

Trace `main()` once, top to bottom, and you've seen the whole layer drive:

1. `--index` xor a positional `exp_id` (lines 215–228) — exactly one names what to
   render; both/neither is a named usage error.
2. Format resolution order (`_resolve_format`, line 121): `--format` > `--audience`
   sugar (`operator`→isatty default, `exec`→html, `skeptic`→md, `public`→card) >
   isatty default (`glance` on a TTY, `md` when piped).
3. Fail-fast on a deferred/unknown format **before touching disk** (lines 251–273):
   png/pdf route through `raster` (fail fast naming the extra, else build); an
   unrecognized id lists the available formats.
4. Usage walls: `glance` + `--out` is an error (terminal surface); a `binary`
   adapter with no `--out` is an error (bytes can't go to a TTY).
5. Load → validate (`extra="forbid"`; a `ValidationError` is `EXIT_FATAL`) → build
   the bundle: `ViewBundle(vm=distill(report), provenance=build_provenance(report,
   exp_dir))` (line 341) → `adapter.render(bundle)`.
6. The exit-code contract that mirrors `audit`: a `DRAFT_UNVERIFIED` render still
   *emits* but returns `EXIT_WARNING` (lines 373–374). The render succeeds; the
   warning travels in the exit code.

---

## Lab / break-it (prove the axiom holds — or watch it fail)

Set up a finalized experiment first (the `ship_demo.csv` fixture from Module 1, or
the existing `tests/render/fixtures/bundles_ship/` finalized into a dir).

**Lab 10a — one number, six formats, zero re-derivations.** Render the same
experiment to every text format and confirm the headline lift string is
*byte-identical* across all of them:

```bash
$ agentxp report exp_001 --format md     | grep -o '+[0-9.]* (+[0-9.]*%)' | head -1
$ agentxp report exp_001 --format json   | python -c "import json,sys; print(json.load(sys.stdin)['vm']['metric_table'][0]['lift_str'])"
$ agentxp report exp_001 --format csv     | sed -n '2p'   # row 1 = primary metric
$ agentxp report exp_001 --format html  --out /tmp/r.html && grep -o '+[0-9.]* (+[0-9.]*%)' /tmp/r.html | head -1
```

They match because there is *one* `lift_str`, formatted once in `distill()`, that
every adapter interpolates. This is the axiom, observable. (The repo pins it as a
test: `tests/render/test_cross_format_equality.py`.)

**Lab 10b — tamper the chain, watch every format degrade to DRAFT.** This is the
presentation-layer echo of Module 4's Lab 4a. Doctor the sidecar:

```python
import json, pathlib
p = pathlib.Path("experiments/exp_001/report.json")
d = json.loads(p.read_text()); d["chain_hash"] = "0" * 64; p.write_text(json.dumps(d, indent=2))
```

Now render. Expected: `md` gains the top `⚠ DRAFT — UNVERIFIED` admonition *and*
a `chain integrity: FAILED` footer; the `card` strikes a diagonal ribbon across
the hero; `json` carries `provenance.render_status == "draft_unverified"`; and
**every** format returns `EXIT_WARNING` (exit code 2). You just proved the proof
is welded to the polish — there is no format that shows the verdict while hiding
the broken receipt. (Pinned: `test_report.py::test_tampered_chain_hash_is_mismatch_warning`.)

**Lab 10c — try to make an adapter lie (the axiom as a wall).** Open any adapter
and try to "improve" a number — e.g. in `data.py`'s `CsvAdapter`, replace
`m.lift_str` with something that recomputes from a raw float. You'll find you
*can't*, cleanly: the `MetricRow` doesn't carry the raw floats — only `lift_str`,
`ci_95`, `ci_90` as strings. To re-derive, you'd have to reach past the VM back
into the `Report`, which the adapter isn't handed. The type system is the
guardrail. (If you force it — pass the `Report` in — the cross-format equality test
goes red the moment your rounding differs from `distill()`'s by one digit.)

**Lab 10d — fail fast on the missing extra.** In an environment *without*
`agentxp[png]`, run `agentxp report exp_001 --format png`. Expected:
`format 'png' ships in the optional agentxp[png] extra (pip install 'agentxp[png]'
then: playwright install chromium); available now: card, csv, glance, html, json,
md` and exit code 1 — **before** any disk read. Then `--format png` *with* the
extra but *without* `--out` → `format 'png' is binary; --out is required`.

**Lab 10e — break the index without breaking the page.** Build two experiments,
then corrupt one's `report.json` (`{ not valid json`). Run `agentxp report
--index`. Expected: the page still writes (exit 0); the bad experiment is a
status-only ERROR row badged UNVERIFIABLE; the good one renders normally. One bad
experiment never aborts the navigator — per-row isolation, observable.

(For each lab, the matching tests under `tests/render/` and `tests/cli/test_report.py`
show the same behavior as green assertions — read them alongside your hand-breaking.)

---

## Lab F — add a new output format (the build-to-break exercise)

This is the Module-9 move applied to the presentation layer: **add an adapter, and
predict the blast radius before you run the suite.**

**The target.** A `txt` adapter — a plain-text, no-ANSI, no-markdown digest for
pasting into an email or a ticket. Plain text, so `binary = False`,
`requires_node = False`.

**Build it.**

1. Create `agentxp/render/adapters/text.py` with a `TextAdapter` class:
   `format_id = "txt"`, both flags `False`, a `render(self, bundle) -> str` that
   interpolates **only preformatted strings off `bundle.vm`** (verdict,
   `rationale_one_line`, each `MetricRow.name` + `lift_str` + `ci_95`), and a
   `default_filename`. **Do no arithmetic** — if you're tempted to compute a
   percentage, that's the axiom telling you to stop; the string you want is
   already on the VM.
2. Stamp the DRAFT case the way `markdown.py` does: when
   `bundle.provenance.render_status is RenderStatus.DRAFT_UNVERIFIED`, prepend a
   blunt `!! DRAFT — UNVERIFIED: {status_reason}` line. Proof travels with polish,
   even in plain text.
3. Register it: add `TextAdapter.format_id: TextAdapter()` to `ADAPTERS` in
   `adapters/__init__.py` and export the class.

**Predict the blast radius first** (write it down before running):

- If you forget to register it, what fails — an import error or a CLI message?
  (The CLI's `fmt not in ADAPTERS` branch prints `unknown format 'txt'; choose
  from: …` and exits 1. The Protocol is structural, so a registered class that's
  missing `default_filename` fails the `@runtime_checkable` `isinstance` check, not
  at import.)
- If your `render` re-derives a number and rounds it differently from `distill()`,
  which test catches you? (Add a `txt` case to
  `tests/render/test_cross_format_equality.py` and it goes red on the first digit
  that differs — that test is the axiom's enforcement.)
- Does adding `txt` touch verification at all? (No. An adapter never decides
  status; it *reads* `bundle.provenance`. If you find yourself importing
  `build_provenance` inside the adapter, you've crossed the pure/impure line — back
  out.)

**Run it.**

```bash
$ .venv/bin/python -m pytest tests/render/ tests/cli/test_report.py -q
$ agentxp report exp_001 --format txt
```

**The lesson.** Adding a *text* format is the easiest extension in the system —
one class, three flags, one dict entry — precisely because the contract is narrow
and the VM hands you only strings. Compare to a *binary* format (png/pdf), which
additionally needs `binary=True`, an external engine, lazy imports, an
`is_available()` probe, a `pyproject` extra, and CLI fail-fast wiring. **The
breadth of the work matches the breadth of the dependency** — exactly the
proportion Module 9 taught for adapters and stages. A pure-text renderer is cheap
because it borrows everything (numbers from `distill()`, proof from
`build_provenance()`) and owns nothing but layout.

---

## Teach-back checkpoint

You pass Module 10 when you can, without notes:

1. **State the axiom and why it's structural** — `report.json` is the only source
   of truth; every output is a pure renderer; adding a format = adding a renderer,
   never re-deriving a number. Explain why a renderer that does arithmetic is a
   second source of truth in disguise, and how the `str`-typed VM fields enforce
   the rule rather than merely requesting it.
2. **Explain the pure/impure split** — what `distill()` may and may not do, what
   `build_provenance()` must do (touch disk, recompute), why they're separate, and
   why the CLI *bundles* their outputs into a `ViewBundle` so polish never travels
   without proof.
3. **Walk the three-state `RenderStatus`** — name all three, explain that it's
   one-directional ("can't check" demotes, never promotes), and why conflating
   "I checked and it's wrong" (DRAFT, red) with "I couldn't check" (UNVERIFIABLE,
   gray) is the failure mode the three states exist to prevent. Tie it back to
   Module 4 (this is the *reader* of the integrity spine).
4. **Trace one number, six formats** — show that the headline lift is byte-identical
   across md/json/csv/html/card because it's formatted once. Then tamper a chain
   hash and predict, for each format, exactly how it stamps DRAFT and that all
   return `EXIT_WARNING`.
5. **Explain index per-row isolation and the identity rule** — why one bad
   experiment can't abort the navigator, and why a row's links must use the
   *directory name*, not the embedded `experiment_id`.
6. **Add the `txt` adapter in front of me** and route each possible mistake to the
   guardrail that catches it: an unregistered format (CLI message), a re-derived
   number (cross-format equality test), a crossed pure/impure line (importing
   `build_provenance` in an adapter). Then explain why a binary format is more work
   than a text one, and why that's the right proportion.

When you can state the axiom, defend the pure/impure split, and extend the layer
without re-deriving a single number or dropping a single receipt, you own the
share-out spine. Check the box — that completes the v0.1 curriculum end to end:
the analysis spine (0–9) *and* the presentation spine (10).
