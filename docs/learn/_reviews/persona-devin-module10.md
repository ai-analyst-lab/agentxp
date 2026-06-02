# Review — persona: "Devin" (senior backend/distributed-systems engineer, stats-weak) — Module 10

Reviewer profile: strong on Python, state machines, file I/O, Protocols, registries,
optional-dependency boundaries, exit codes. Weak on experimentation statistics (power,
MDE, SRM, CI vs MDE). Standard: an O'Reilly book teaches the unfamiliar parts
concretely, with enough scaffolding to re-derive the design from the text.

## Verdict

This is the best module in the curriculum for a reader like me, and it isn't close.
Module 10 is squarely in my strength zone — a pure/impure split, a `Protocol`, a
registry, an optional-dependency boundary, an exit-code contract — and it teaches all
of it precisely enough that **I could re-implement the pure/impure split and add an
adapter from the text alone, and I could predict Lab F's blast radius before running
the suite.** I verified the load-bearing claims against `distill.py`, `viewmodel.py`,
`provenance.py`, `adapters/base.py`, `adapters/__init__.py`, and `cli/report.py`, and
the systems teaching holds up almost everywhere. The line counts cited in the
walkthrough (`_metric_table` 82–101, `_chart_data` 133–150, `distill` 168,
`distill_index` 205; `ReportVM` 192, `ViewBundle` 238; `build_provenance` precedence
121–257; CLI fail-fast 254–266, exit-warning 373–374) all land on the right code.

It is shippable. But there are **three real defects** and a handful of imprecisions
that, left unfixed, will either confuse a careful reader or let them "pass" the
teach-back while believing something the code contradicts. None is a blocker on its
own; together they're an afternoon's edit. Ranked findings below.

This module also vindicates the fix I asked for in the Module 0–9 review: the
stats-adjacent terms here (lift, CI, verdict, guardrail) are used as *forward-references
to Modules 1–4*, not re-taught — and that is the right call, **provided** the reader
actually got them in Module 3. (They didn't, per my prior review. See finding 5.)

---

## Findings (numbered, by priority)

### 1. The "W1 stub vs. fully-live" contradiction between the prose and the docstrings it tells me to read. (Correctness — the one that would actually trip me.)

The module repeatedly describes `build_provenance` as a **live, fully-implemented**
5-step flow — "runs in strict precedence (lines 121–257)," "Reproduce the verdict,"
"VERIFIED iff hash matches *and* `cv.ok` *and* the verdict reproduces." The function
body backs that up: steps 0–5 are all present and call `canonical_chain_hash`,
`validate_chain`, and `receipts._reproduce_verdict` for real.

But the module *also* tells me, three times, to "read the module docstring first." When
I do, the docstring says the opposite: VERIFIED is "**Achievable only once the full
live flow lands in W3**," and `build_provenance`'s own docstring says "**Wave 1
behavior**: populate the recorded receipts, run the can't-check gate, and resolve
UNVERIFIABLE either for a gate trip or for the not-yet-run live flow. W2 adds… W3
adds…". So the prose says "this is live," the docstring says "this is a W1 stub that
always returns UNVERIFIABLE," and the *code* says "actually it's fully live." Two of the
three disagree with the artifact a reader is told to trust.

This directly poisons **Lab 10b** and teach-back item 4. Lab 10b tampers `chain_hash`
and asserts the render degrades to `DRAFT_UNVERIFIED` with a "stale or edited" reason
and `EXIT_WARNING`. That's correct *for the live code* — but a reader who just read the
docstring believes provenance can only ever emit `UNVERIFIABLE`, so the lab's expected
output looks impossible. Either the docstrings are stale (most likely — the body is
clearly past W3) and should be corrected in the source, or the module should add one
sentence: "the docstrings narrate the wave-by-wave build; the shipped body runs the
full flow — read the body, not just the header." I'd prefer the former. Flag it.

### 2. The Lab 10c "wall" is leakier than the module claims — `ChartData` puts raw floats on the VM.

Lab 10c's whole lesson is "the type system is the guardrail: you *can't* re-derive a
number in an adapter because the `MetricRow` only carries `lift_str`/`ci_95`/`ci_90` as
strings — the raw floats aren't handed to the adapter." The first half is true
(`MetricRow` has no float fields — verified). The second half is **false**:
`bundle.vm.charts` is a `ChartData`, and `ChartData` carries `lift_absolute`,
`ci_95_lower/upper`, `ci_90_lower/upper` as raw `float`s (viewmodel lines 94–98). An
adapter *is* handed those floats — that's how `charts.py` draws the SVG without
touching the `Report`. So a reader who follows Lab 10c's "try to make it lie" exercise
and is feeling adversarial will find `bundle.vm.charts.lift_absolute` and re-derive the
headline lift from it — exactly the move the lab claims is structurally impossible.

The honest framing is: the *table* path is float-free by type, but the *chart* path
deliberately carries raw numbers (for plotting, not formatting), and the discipline
there is enforced by **convention + the cross-format equality test**, not by the type
system. That's still a good lesson — it's the "belt-and-suspenders" point from Module 5
— but the module currently overclaims "the type system is the guardrail" full stop. Add
one sentence acknowledging `ChartData`'s floats and that the equality test (not the
type) is what guards the chart path. Otherwise the sharpest reader catches the doc in
exactly the kind of overclaim this product is supposed to be about *not* making.

### 3. Lab 10b's tamper target is `report.json`'s `chain_hash`, and the precedence makes the *reason string* non-obvious — the lab should say which check fires.

The lab edits `report.json`'s `chain_hash` to `"0"*64`. Walking the live code: the
stored hash is now zeros; `live_hash` recomputed from the untouched `log.jsonl` won't
match → `hash_matches=False`. But `validate_chain` runs against the *log*, which wasn't
touched, so `cv_ok` is almost certainly `True`. Precedence is chain → hash → tree, so
the verdict is `DRAFT_UNVERIFIED` with the **hash-mismatch** reason ("the sidecar is
stale or has been edited"). The lab asserts the right verdict and the right footer, so
it works — but it doesn't tell the reader *why* the hash branch fires rather than the
chain branch, and a reader who tampered the *log* instead (a natural variation) would
get the chain-validation reason and a different message. One sentence — "you edited the
sidecar, not the log, so the chain still validates and the *hash* check is the
first-failing one; precedence is chain → hash → tree" — turns a "it worked" into an "I
understand the precedence." This is the kind of thing the module does well elsewhere
(the index identity aha), so it's a consistency gap, not a new burden.

### 4. `distill_index` "counts, doesn't derive" is taught well — but the *who builds the rows* split deserves the diagram, not just prose.

Step 1 and step 5 both gesture at the subtlety that `distill_index` is pure and only
*counts* statuses, while the **index adapter** builds the rows at the I/O boundary
because resolving a render status needs the impure `build_provenance`. This is correct
(verified against `distill_index` and `IndexRowVM.error_row` / `to_index_row`) and it's
the single most interesting design point in the module — it's where the pure/impure
line gets drawn *inside* one feature. But it's delivered as two scattered paragraphs
("We come back to it in step 5") and the two-spine diagram at the top doesn't show the
index path at all. For a reader whose strength is exactly this kind of boundary, a
three-box mini-diagram (`adapter loops dirs → per-dir distill()+build_provenance() →
IndexRowVM` ... `distill_index(rows) → counts only`) would land it in one look. Minor,
but it's leaving the best systems lesson slightly under-staged.

### 5. The stats-adjacent terms are correctly *forward-referenced*, not re-taught — which is right, but it inherits Module 3's debt.

Judged from my persona: the module never stops to define "lift," "CI," "MDE," "SRM
split chart," or "verdict." It uses them as already-known and points back implicitly to
Modules 1–4. **That is the correct editorial choice for Module 10** — re-teaching MDE
here would be the over-explaining I'd skim past, and a presentation-layer module should
assume the analysis spine. The one place it's load-bearing is `_guardrails_violated`
and the "a real guardrail *violation* is surfaced **separately**" note (distill lines
104–110): the module explains the *mechanism* (it reads committed `edge_case_flags`,
never re-decides) crisply and correctly, which is all this module owes. So no new stats
primer is needed *here*.

BUT: my Module 0–9 review found Module 3 never actually defines MDE/power/CI/SRM in
computable terms. Module 10's forward-references are only honest if that debt gets paid
in Module 3. As written, a stats-weak reader hits "every lift, CI, and percentage" and
"the SRM-split chart omits rather than inventing a split" with no grounded model of what
an SRM split *is* or why a missing per-arm count matters. The fix is in Module 3 (per my
prior review), not here — but this module should add **one** forward-reference line near
the first use of "lift/CI/verdict": "these terms are defined in Module 3 §0 (the stats
primer); here we only *format* them, never compute them." That one line keeps the
stats-weak reader from feeling stranded a second time, and it reinforces the axiom
(formatting, not computing) at the same moment.

### 6. Minor fidelity / precision nits.

- **`ProvenanceCache` is taught but the CLI doesn't use it.** The module says
  `ProvenanceCache` "memoizes by resolved `exp_dir` so rendering six formats of one
  experiment in one CLI run hashes the log *once*." The class exists and does that. But
  `cli/report.py`'s `main()` renders **one** format per invocation and calls
  `build_provenance` directly (line 341) — it does *not* use `ProvenanceCache`. So the
  "six formats, one hash" benefit isn't realized by the shipped `report` verb (it'd
  matter for an in-process caller rendering many formats, or the index path). Not wrong,
  but the module implies the CLI exploits it and it doesn't. Either name the actual
  caller or soften to "so a caller rendering several formats hashes once."
- **"one of N adapters" / registry count.** The module's diagram lists
  `md · glance · html · card · json · csv · png · pdf · index`, and the prose correctly
  notes png/pdf are *not* in `ADAPTERS` and index is a separate entry point. Good — but
  the registry is exactly six (`md, glance, html, card, json, csv`), and saying so
  explicitly ("`ADAPTERS` has six entries; png/pdf and index are deliberately outside
  it") would pre-empt a reader miscounting against the diagram.
- **Lab 10a csv comment.** `--format csv | sed -n '2p'  # row 1 = primary metric` —
  fine, but `data.py`'s `CsvAdapter` is "one row per headline metric," and row 1 of the
  file is the header, so "row 2 = primary metric" (which `2p` correctly selects). The
  inline comment says "row 1 = primary metric," which is off-by-one against what the
  `sed` actually grabs. Trivial, but a copy-paste reader will trust the comment.
- **Lab F is excellent and concrete — ship it as-is.** The `txt` adapter exercise is
  the most actionable build-to-break in the curriculum for me: three flags, one
  `render`, one registry line, and a written-down blast-radius prediction whose three
  branches (unregistered → CLI message; re-derived number → cross-format equality test;
  crossed pure/impure line → importing `build_provenance`) each map to a real guardrail I
  verified. The "breadth of work matches breadth of dependency" closing is the right
  lesson and it's *shown*, not asserted. The only thing I'd add: tell the reader the
  `extra="forbid"` on `MetricRow`/`ReportVM` means a typo'd field name fails at VM
  *construction*, not in their adapter — another guardrail, free.

---

## What works (don't touch these)

- **The axiom is stated once, structurally, and every consequence is derived from it.**
  "A renderer that does arithmetic is a second source of truth in disguise" is the best
  one-line statement of a design constraint in the whole curriculum, and the `str`-typed
  VM field (`lift_str` is a `str`, not a `float`) as "the axiom encoded in the type" is
  exactly the *show-don't-tell* the earlier modules sometimes missed. I could re-derive
  the pure/impure split from this section alone.
- **The three-state `RenderStatus` is taught with the right emphasis:** the
  one-directional rule ("can't-check demotes, never promotes") and the
  red-vs-gray distinction ("I checked and it's wrong" vs "I couldn't check") are precise,
  correct against the code, and tied back to Module 4 cleanly. The `PerfBudgetExceeded →
  UNVERIFIABLE, never an accusation` detail is the kind of edge a careful engineer wants
  and it's accurate (provenance lines 177–187).
- **The optional-dependency boundary (step 6) is textbook.** Lazy import inside
  `_rasterize`, `is_available()` probe, `binary`/`requires_node` flags letting the CLI
  fail fast *by name* before importing, the `pyproject` extra naming the *second*
  install step (`playwright install chromium`) — all correct, all the right lessons, and
  the "optional dependencies are a UX problem" framing is the right altitude.
- **The index identity aha** ("identity is the directory name, not the embedded
  `experiment_id`") is a genuinely earned war-story (Wave 7 fix) and it teaches a real
  distributed-systems lesson — *display name vs. resolve name* — without sermonizing. Best
  aha in the module.
- **Pacing is right for my profile.** Nothing is over-explained for an engineer; the
  density is appropriate; the labs are runnable and teach what they claim. The
  over-bolding tic from earlier modules is *much* reduced here — bold is mostly reserved
  for the ahas, which is the correct use.

## Confidence (my standard)

- (a) Could I re-implement the pure/impure split and add an adapter from the text alone?
  **Yes.** (b) Could I predict Lab F's blast radius before running it? **Yes** — all
  three branches. (c) Earned for the systems content. The only things standing between
  this and a clean pass are findings 1 (the stub/live contradiction) and 2 (the leaky
  Lab 10c wall) — both correctness, both small.
