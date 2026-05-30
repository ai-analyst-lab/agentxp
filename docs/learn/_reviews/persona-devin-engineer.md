# Review — persona: "Devin" (senior backend/distributed-systems engineer, stats-weak)

Reviewer profile: strong on Python, state machines, file I/O, concurrency, logs.
Weak on experimentation statistics (power, MDE, SRM, CI vs MDE, sequential, delta
method). Standard: an O'Reilly book teaches the unfamiliar parts concretely.

## Verdict

The systems half of this curriculum is excellent — among the best internal docs
I've read. Modules 1, 4, and 6 are precise enough that I could re-derive
`_commit_stage`'s validate→append→advance ordering, name the crash window, and
predict the chain refusals before running the labs. I verified those against
`store.py`, `chain.py`, and `resume.py` and they hold up.

But the curriculum **fails its own depth target for a stats-weak engineer**, and
it fails it exactly where it matters most: Module 3, the deterministic core. Two
problems compound:

1. **Module 3's verdict list does not match the code.** This is not a nuance — it
   is wrong. The curriculum teaches 8 verdicts as `SHIP / NO-SHIP / LEARN
   (powered) / LEARN (underpowered) / caveat-investigate / INVALID-SRM /
   NO-SHIP-GUARDRAIL / fallback`. The actual `Verdict` literal in
   `agentxp/interpret/tree.py:29` is `INVALID-SRM, NO-SHIP-GUARDRAIL,
   INCONCLUSIVE, NO-LIFT, DIRECTIONAL-ONLY, LIFT-WITH-CAVEAT, SHIP, LEARN`. There
   is no `NO-SHIP` verdict, no `LEARN (powered)`/`LEARN (underpowered)` split (it's
   one `LEARN` with a `learn_subcase` diagnostic), and `DIRECTIONAL-ONLY` /
   `INCONCLUSIVE` / `NO-LIFT` are never mentioned. A reader who memorizes Module 3
   and then opens the code will think the file is from a different version. The
   teach-back asks me to "walk the tree cold" and "predict the step that fires" —
   I cannot, because the labels I was taught aren't the labels in the tree, and
   the step→verdict mapping in the module is fabricated.

2. **Every stats term that gates a verdict is named but never taught.** MDE, power,
   CI half-width vs MDE, SRM χ², 90% vs 95% CI, late_ratio, delta method, ratio
   metric — each appears as a load-bearing input to a decision, and none gets the
   one or two concrete sentences a stats-weak engineer needs. I can read the Python
   control flow in `tree.py` fine; what I cannot do is say *why* `ci_half_width_95 >
   2 * mde_absolute` means "underpowered wide null," because nobody told me what an
   MDE is in units I can compute, or why a wide CI relative to it means the study
   couldn't see the effect. The mechanism is teachable; the stats it gates was
   assumed.

Net: ship the systems modules nearly as-is. Do **not** ship Module 3 until (a) the
verdict labels are corrected to the code and (b) a "stats you need" primer is added.
Module 1's table also lists the wrong verdict vocabulary (it says the interpreter
emits "one of 8 labels" and the README cheat-sheet uses the fabricated names too).

---

## Teach-back results

### Module 0 — Thesis & market
- Q1 state thesis + 3 subsystems → **PASS**. One sentence is memorable; the three
  subsystems (pre-reg lock, blind interpreter, replayable chain) are clearly tied.
- Q2 survive skeptic drill (3 objections) → **PASS**. The "calculators leave the
  judgment to you at the moment your judgment is compromised" framing is a genuinely
  good answer to all three. I could deliver these cold.
- Q3 name 3 non-features + why each is a strength → **PASS**. Randomized-A/B-only,
  no headless loop, three unverified adapters — all stated plainly.

### Module 1 — The shape: 11 stages
- Q1 list 11 stages, owner, artifact, gate → **PASS**. The table is clean; I can
  recite 0–8 + 3b with owners and artifacts.
- Q2 why Stage 2 before Stage 5 → **PASS**. "Stage order is how pre-registration is
  enforced in time" is the exact right answer and it stuck.
- Q3 name the one function + validate→append→advance + crash → **PASS**. The 8-step
  shape of `_commit_stage` is correct in spirit; I verified `store.py:655` and the
  ordering matches (the real code numbers validate as its own step before the log
  emit and adds a rollback path, but the module's 6→7→8 mental model is sound).
- Q4 two blind agents + what each is blind to → **PASS**. Monitor (blind to
  narrative) and interpreter (blind to hypothesis/hopes/state.yaml).

  *Caveat: the module says the interpreter commits "verdict.yaml (one of 8 labels)"
  but never lists the 8 labels here, deferring to Module 3 — where they're wrong.*

### Module 2 — Agents as programs
- Q1 isolation axiom + denied inputs + why → **PASS**. Cleanly stated; the
  `interpreter(locked_rule, analyzer_numbers) -> verdict_label` signature framing is
  the best teaching device in the whole curriculum.
- Q2 trace input conversation→agent (bundle, assemble, SHA256, chain tie) → **PASS**.
  The chain-of-custody paragraph is precise and I could redraw it.
- Q3 read a *.system.md as a program → **PASS** (conceptually; I'd need the file open,
  which the lab provides).
- Q4 defend designer trio split → **PASS**. Three judgments, three failure modes;
  editor carries the locked-rule refusal.

### Module 3 — The deterministic core  ← the failure
- Q1 why stats+verdict are deterministic, recoverable vs unrecoverable → **PASS**.
  This conceptual point is well made and I believe it.
- Q2 name the whitelist's role + 4 functions incl. the one that halts → **PARTIAL**.
  I can say `srm_check` halts and name `welch_test`, `proportion_test`,
  `power_proportion`. But I cannot say *what `welch_test` is for vs `proportion_test`
  vs `ratio_metric_test`* beyond echoing the one-line gloss — "continuous,"
  "conversion-style," "ratio metric, delta-method variance" are labels I can't
  unpack. The module told me delta method exists; it never told me what problem it
  solves (variance of a ratio when the denominator is itself random). I'm parroting.
- Q3 walk the 8-step tree cold, name verdict + exact step → **FAIL**. The labels in
  the module don't match the code. I'd answer "NO-SHIP" or "LEARN (underpowered)" —
  neither exists. The real tree fires `INCONCLUSIVE` (Step 3), `NO-LIFT` (Step 4),
  `DIRECTIONAL-ONLY` (Step 5), `LIFT-WITH-CAVEAT` (Step 6 small-lift / Step 7
  novelty), `SHIP` (Step 7), `LEARN` (Step 8). The module's step→verdict table is a
  different design than the shipped one. A learner cannot pass this checkpoint using
  only the module.
- Q4 verdict vs confidence label → **PARTIAL**. The *distinction* (what vs how-sure)
  lands. But the module says `map_confidence` returns "7 ConfidenceLabel values" and
  I have no way to verify what drives them beyond "tight CI / clean power → high" —
  and "clean power" is again a term I can't operationalize.
- Q5 defend a constant (NOVELTY_LATE_RATIO_FLOOR=0.7) → **PARTIAL**. I can recite
  "effect decaying below the floor flags novelty." But the module never defines
  late_ratio precisely — it's `late_window_effect / early_window_effect` over
  exposure-window thirds (`tree.py:186`), and that definition only exists in the
  code, not the module. I had to read the source to actually answer. The module also
  doesn't mention the asymmetry (ratio > 1.3 is still SHIP), so my defense is
  incomplete.

### Module 4 — The integrity spine
- Q1 three mechanisms + correct "not a blockchain" → **PASS**. The parent-action
  chain vs replay hash vs locked-rule wall separation is crisp and correct; I
  verified `validate_chain` returns violations (doesn't raise) against `chain.py`.
- Q2 five invariants + why return-not-raise + the one exception → **PASS**. All five
  match the code; `PerfBudgetExceeded` as the sole raise is correct.
- Q3 explain the lock precisely → **PASS**. "Existence on disk is the lock,"
  `ArtifactLocked`, `amend=True` reserved seam — all accurate.
- Q4 amendments boundary G14 → **PASS**. Two stores, naive wiring breaks Invariant 1.
- Q5 break one invariant + read refusal → **PASS** (labs are runnable and concrete).

  *This is the model module. If Module 3 read like Module 4, there'd be no review.*

### Module 5 — Data plumbing
- Q1 trace query through every layer + correct "5 layers" framing → **PASS**. The
  "code has 4 numbered layers, 3 split a/b/c, plus an unnumbered dialect guard"
  honesty matches `safety.py` exactly. Strong.
- Q2 why AST allowlist *and* function deny-list → **PASS**. Belt-and-suspenders,
  allow-known-good + deny-known-bad. Clear.
- Q3 redaction guarantee, canonical _SENSITIVE_KEYS, drift incident → **PASS**.
- Q4 what the audit trail can't hold + what enforces the row bound → **PASS**. The
  "name what enforces what" precision (schema-forbid vs row caps vs no single
  LLM-gate) is exactly the kind of rigor I want.
- Q5 adapter verification honesty → **PASS**.

  *Only stats-adjacent gap: `srm_check`'s purpose=1M row cap is mentioned but the
  module never connects why SRM needs the full population while metric_compute is
  capped at 10M — a one-liner would close it.*

### Module 6 — State, stores & resume
- Q1 two stores, roots, which chained, why not unified → **PASS**. Verified against
  `store.py` and the §10.6 resume model.
- Q2 recite _commit_stage ordering + crash window + why opposite ordering lies →
  **PASS**. This is the clearest distributed-systems explanation in the doc. The
  "log equal-or-ahead of state is recoverable; behind is a lie" framing is exactly
  right and I could re-derive it.
- Q3 reconstruct_from_log — trusts log, ignores state.yaml → **PASS**. Matches
  `reconstruct_from_log` at `store.py:570`.
- Q4 resume as a function of (log, state) divergence → **PASS**. The "8 cases"
  matches `_detect_case` (§10.6) in `resume.py:103`.

### Module 7 — Build history & judgment
- Q1 explain "green-but-broken" via validate_chain → **PASS**. The monkeypatch story
  is the most memorable lesson in the back half.
- Q2 necessity criterion + 4 buckets + "exported ≠ reachable" → **PASS**.
- Q3 defend two keep-vs-cut calls as one judgment → **PASS**.
- Q4 name current honest boundaries → **PASS**.

### Module 8 — Capstone
- Demo + gauntlet → **PARTIAL**, entirely because of Module 3. Gauntlet Q8 ("hand
  them a novel analyzer output, what's the verdict and which step fires") is
  unanswerable with the fabricated labels. Every other gauntlet question I can field.

---

## The stats-fluency gap (the most important section)

Below is every statistics term the curriculum makes load-bearing — i.e. a verdict,
a function choice, or a constant depends on it — that it **names but never teaches**.
For each: where it bites, and the minimal concrete explanation the curriculum should
add. These are the sentences an O'Reilly book would have included; their absence is
the single biggest defect for a stats-weak reader.

1. **MDE (minimum detectable effect)** — *Module 1 Stage 2/3, Module 3 Steps 4/6.*
   Named ~8 times as the thing you pre-register and the thing CI width is compared
   to, but never defined. The tree converts it: `mde_absolute = (mde_pct/100) *
   baseline` (`tree.py:167`). A reader needs: *"The MDE is the smallest true effect
   you decided in advance is worth detecting. You pick it before the test; power
   analysis then tells you the sample size needed to reliably see an effect that
   big. It's expressed as a percent of baseline (mde_pct=2.0 → 2% relative), and the
   tree converts it to absolute units to compare against the CI."* Without this,
   Steps 4 and 6 are opaque.

2. **Statistical power / "adequately powered" / "underpowered"** — *Module 1 Stage 3,
   Module 3 Steps 3/4/8, the `no_effect` vs `underpowered` fixtures.* The whole
   "a real null vs you-couldn't-tell" distinction rests on power, and power is never
   defined. Add: *"Power is the probability your test detects a true effect of at
   least the MDE, given your sample size. 80% is the usual target. 'Underpowered'
   means n is too small to reliably catch an MDE-sized effect, so a flat result tells
   you nothing — you might have missed a real effect. 'Adequately powered' means a
   flat result is informative: if there were an MDE-sized effect, you'd probably have
   seen it, so its absence is a finding."* This is the literal difference between the
   `LEARN`-well-powered and `INCONCLUSIVE` paths.

3. **Confidence interval, and CI half-width vs MDE** — *Module 3 Step 4
   (`NOLIFT_CI_WIDTH_MULTIPLIER = 2.0`), Step 8.* The single most important
   unexplained mechanic. The code fires NO-LIFT when `ci_half_width_95 > 2 *
   mde_absolute`. A stats-weak reader cannot parse this. Add: *"A 95% CI is the range
   of effect sizes consistent with your data. Its half-width measures precision —
   narrow = precise. If the CI straddles 0 (no significant effect) AND its half-width
   is still wider than ~2× the MDE, your measurement was too imprecise to rule out an
   MDE-sized effect → you couldn't tell (was originally framed as NO-LIFT/underpowered).
   If the CI straddles 0 but is tight relative to the MDE, you've genuinely shown the
   effect isn't there → a real null (LEARN)."* This one paragraph unlocks Steps 3, 4,
   and 8.

4. **90% vs 95% CI (the DIRECTIONAL-ONLY mechanic)** — *not in the curriculum at all,
   but it's a whole verdict in the code (Step 5).* The tree uses BOTH a 95% and a 90%
   CI; when the 95% straddles 0 but the 90% excludes it, it fires `DIRECTIONAL-ONLY`.
   The curriculum never mentions this verdict, the two CI levels, or why you'd use a
   looser interval to capture "suggestive but not conclusive." Must be added — it's a
   load-bearing step the module silently dropped.

5. **SRM and the χ² goodness-of-fit test** — *Module 1 Stage 4, Module 3 Step 1,
   `srm_violation` fixture.* "SRM χ²" is named ~6 times; χ² is never explained. From
   `srm.py`: it's a chi-squared test of observed vs expected per-variant counts;
   p < threshold ⇒ the split deviates from design ⇒ randomization is broken ⇒ HALT.
   Add: *"You designed a 50/50 split; you observed 52/48. The χ² test asks: is that
   gap bigger than random chance would produce at this sample size? If yes (very
   small p — Microsoft uses 0.0005), your randomization is broken, which means
   treatment and control differ for reasons other than your feature, so every
   downstream number is contaminated. That's why SRM is Step 1 and halts rather than
   flags."* The "why halt not flag" answer the gauntlet demands needs this.

6. **late_ratio / novelty** — *Module 3 Step 7, `NOVELTY_LATE_RATIO_FLOOR = 0.7`.*
   The module says "compares late-window effect to overall" — but the code
   (`tree.py:186`) defines it as `late_window_effect / early_window_effect` over
   exposure-window *thirds* (early = first third, late = last third), not vs overall.
   The module's definition is also imprecise *and* misses the >1.3 asymmetry. Fix the
   definition and add: *"A novelty effect is a temporary bump because users react to
   anything new; it decays. Splitting the run into thirds and dividing the late-window
   effect by the early-window effect: ~1.0 = stable (real, SHIP), <0.7 = decaying
   (novelty, downgrade to caveat), >1.3 = slow-burn (still SHIP). It guards against
   crowning a launch bump as a permanent win."*

7. **Ratio metric / delta method** — *Module 3 whitelist (`ratio_metric_test`).*
   Named with the gloss "delta-method variance"; delta method never explained. Add:
   *"For a metric like revenue-per-user, both numerator and denominator vary across
   users, so you can't use a simple two-sample test — the variance of a ratio of two
   random quantities needs a special formula (the delta method, a first-order Taylor
   approximation). `ratio_metric_test` applies it so the CI on the ratio is correct."*
   One sentence; otherwise it's three jargon words.

8. **Welch vs proportion vs the menu** — *Module 3 whitelist.* The module says
   "internalize that the analyzer chooses among a fixed menu" but never gives the
   *selection rule*. Add a 3-line table: continuous metric (revenue, latency) →
   `welch_test` (unequal-variance t-test); binary/conversion metric → `proportion_test`
   (two-proportion z); ratio metric → `ratio_metric_test`. The `checkout_redesign`
   fixture ("how metric *type* affects power") is literally about this and there's no
   scaffolding for it.

9. **p-value & multiple comparisons** — *Module 1 Stage 5, `adjust_pvalues`.* p-values
   appear in the artifact list and the correction function is whitelisted, but the
   reader is never told what a p-value is or why >1 metric inflates false positives.
   One sentence each would suffice; right now `adjust_pvalues` is a black box with a
   name.

**Recommendation:** add a single ~1.5-page "Stats you actually need (for engineers)"
primer as Module 3 §0, before the whitelist walkthrough. Define MDE, power, CI +
half-width-vs-MDE, the two CI levels, SRM/χ², late_ratio, and the test-selection
table — each in the concrete, computable terms above. Then the existing Module 3
prose becomes followable instead of name-dropping. This is the highest-leverage fix
in the whole curriculum.

---

## Per-module notes

### Module 0
- **Pacing:** good. ~15 min of reading, earns it.
- **Mechanism clarity:** n/a (orientation).
- **Voice:** mostly clean, but **over-bolding** starts here: "the human reading the
  result is the same human who wanted a particular result" is bolded, and a half-dozen
  phrases are bolded per page. By Module 3 the bolding is noise — when everything is
  emphasized nothing is. **Sermonizing:** "None of this is dishonesty — it's how
  brains work" is fine once; the curriculum returns to this register repeatedly.
- **Confidence:** (a) I can pitch the product and defend the thesis. (b) 5/5.
  (c) Earned — no stats required.

### Module 1
- **Pacing:** good. The single table carries the module.
- **Mechanism clarity:** high. The `_commit_stage` 8-step shape is enough to act on;
  I verified it against `store.py:655`.
- **Redundancy:** the "two surfaces (shell vs Claude-orchestrator)" explanation is
  repeated near-verbatim from the README and again in Module 6. Once, in the README,
  is enough; cross-reference instead of re-explaining.
- **Voice:** "a pipeline with a conscience" is a nice line but it's used to *tell*
  rather than show; the table shows better than the prose does.
- **Confidence:** (a) name all stages, drive the demo, narrate. (b) 4/5. (c) Earned —
  the only soft spot is "Power" (Stage 3) which forward-refs stats not yet taught.

### Module 2
- **Pacing:** good.
- **Mechanism clarity:** high — best conceptual module. The function-signature framing
  for agents is the strongest teaching device in the doc.
- **Redundancy:** the isolation axiom is stated in Module 0, restated here, and again
  in Modules 3 and 8. Stating it in Module 2 (its home) and referencing elsewhere
  would cut ~30% of the repetition.
- **Voice:** "it sounds backwards until you see it" / "so we cut the wire" — borderline
  dramatic but earns it because the mechanism immediately follows. This is *show*, the
  good kind.
- **Confidence:** (a) explain isolation, trace a bundle, read a system.md as a program.
  (b) 5/5. (c) Earned.

### Module 3
- **Pacing:** too fast on exactly the wrong things. It spends a sentence each on
  ~7 stats functions and zero sentences teaching the stats. "The point isn't to
  memorize signatures" is true, but it's used to wave past the part I most needed.
- **Mechanism clarity:** the *tree-as-ordered-steps, first-fire-wins* mechanic is
  clear and correct. The *verdict labels are wrong* (see Verdict). The *stats inputs*
  are unexplained (see gap section).
- **Redundancy:** restates the recoverable/unrecoverable thesis from Module 0 at
  length.
- **Voice:** "A confidence interval computed by a language model is a confidence
  interval you can't replay and can't trust" — good. But "This is the heart of the
  module" then under-delivers on the heart.
- **Confidence:** (a) I can run `walk_tree` in Python and read the control flow; I
  cannot predict verdicts from the module's labels, nor explain the stats gating each
  step. (b) **2/5.** (c) **Not earned** for a stats-weak reader — and the label
  mismatch would fail even a stats-fluent one.

### Module 4
- **Pacing:** excellent.
- **Mechanism clarity:** highest in the curriculum. Every claim I spot-checked against
  `chain.py` / `store.py` was accurate, including return-not-raise and the lone
  `PerfBudgetExceeded`.
- **Redundancy:** minimal.
- **Voice:** clean. The "it is not a blockchain — do not say each event hashes the
  previous one" is exactly the kind of *correct the misconception explicitly* move an
  O'Reilly book makes.
- **Confidence:** (a) name all five invariants, break four of them, predict refusals.
  (b) 5/5. (c) Earned (no stats).

### Module 5
- **Pacing:** good, dense but justified.
- **Mechanism clarity:** high; the "4 numbered layers, 3 split, 1 unnumbered guard"
  honesty matches `safety.py:1` precisely.
- **Redundancy:** low.
- **Voice:** strong. "The agent proposes; deterministic Python disposes" earns its
  repetition because it's the actual control-flow shape.
- **Confidence:** (a) trace a query, predict the rejecting layer + message, prove the
  redactor. (b) 5/5. (c) Earned — minor SRM-row-cap stats aside.

### Module 6
- **Pacing:** excellent.
- **Mechanism clarity:** highest-value systems content. The crash-window reasoning is
  exactly what a distributed-systems engineer wants and I could re-derive it.
- **Redundancy:** repeats the `_commit_stage` ordering from Module 1 — but here it's
  *justified*, because Module 1 gave the shape and Module 6 gives the why. Keep both.
- **Voice:** clean.
- **Confidence:** (a) explain stores, ordering, reconstruct, resume; answer any
  crash-point question. (b) 5/5. (c) Earned.

### Module 7
- **Pacing:** good; longest module but it's narrative, which carries.
- **Mechanism clarity:** n/a (history/judgment).
- **Redundancy:** the `live_unverified` / Phase-5-stub / G14 boundaries are now stated
  in Modules 0, 5, 6, 7, and 8. That's four too many. Consolidate the "honest
  boundaries" into one canonical list (Module 7 or README) and reference it.
- **Voice:** the "green-but-broken" and monkeypatch story is the best *writing* in the
  doc. A little sermon-y ("Sit with 'green-but-broken'") but earns it.
- **Confidence:** (a) defend keep-vs-cut calls, explain the audit failure. (b) 5/5.
  (c) Earned.

### Module 8
- **Pacing:** appropriate for a capstone (no new material).
- **Mechanism clarity:** n/a.
- **Voice:** fine.
- **Confidence:** (a) field all gauntlet questions *except* the tree-walk (Q8). (b)
  4/5, dragged down solely by the Module 3 dependency. (c) Earned for everything
  except the tree.

---

## Redundancy summary (cross-module)

These are explained 3+ times near-verbatim. Pick one home each, cross-reference the
rest — this would tighten the curriculum by an estimated 10–15%:

1. **Two surfaces (shell CLI vs Claude-orchestrator):** README + Module 1 + Module 6.
2. **The isolation axiom:** Modules 0, 2, 3, 8.
3. **Recoverable vs unrecoverable error / thesis line:** Modules 0, 1, 3, 5.
4. **The honest boundaries (`live_unverified`, Phase-5 stub, G14):** Modules 0, 5, 6,
   7, 8.
5. **`_commit_stage` ordering:** Modules 1 + 6 (this one is *justified* — keep both).

## Voice / O'Reilly-fit offenders

The writing is mostly good, but three tics recur:

- **Over-bolding.** Roughly 1 in 6 sentences has a bolded clause. It started as
  emphasis and became wallpaper. An O'Reilly book bolds *terms on first definition*,
  not arguments. Cut bolding by ~60%, reserve it for the glossary terms (most of which
  aren't even defined — see the gap section).
- **Telling-not-showing in the "Why" sections.** "This is the load-bearing design
  choice of the whole system" (Module 2), "This is the heart of the module" (Module 3),
  "Sit with 'green-but-broken'" (Module 7). The *good* modules (4, 5, 6) earn these by
  immediately showing the mechanism; Module 3 asserts importance then under-delivers.
- **Mild sermonizing about honesty/discipline.** "amateurs oversell, experts name the
  edges" (Module 0), "Knowing the boundaries *cold* is half of looking like an expert."
  Fine in moderation; it appears often enough to read as a motif rather than a point.

---

## Top 10 highest-value fixes

1. **Fix Module 3's verdict labels to match the code.** The module teaches
   `SHIP/NO-SHIP/LEARN(powered)/LEARN(underpowered)/caveat-investigate/...`; the code
   (`tree.py:29`) ships `INVALID-SRM, NO-SHIP-GUARDRAIL, INCONCLUSIVE, NO-LIFT,
   DIRECTIONAL-ONLY, LIFT-WITH-CAVEAT, SHIP, LEARN`. Rewrite the 8-step list and the
   step→verdict mapping to the actual tree. Also fix the README cheat-sheet
   ("LEARN (powered)" etc.) and Module 1's verdict references. **Blocker.**

2. **Add the missing DIRECTIONAL-ONLY / 90%-vs-95%-CI mechanic.** Step 5 of the real
   tree uses two CI levels and emits a verdict the curriculum never mentions. Teach it.

3. **Add a "Stats you actually need (for engineers)" primer as Module 3 §0.** Define —
   in concrete, computable terms — MDE, power, CI + half-width-vs-MDE, SRM/χ²,
   late_ratio (with the correct thirds definition and the >1.3 asymmetry), the
   test-selection table, and p-value/multiple-comparisons. ~1.5 pages. Highest leverage.

4. **Correct and complete the late_ratio definition in Module 3.** It's
   `late_window_effect / early_window_effect` over window *thirds* (`tree.py:186`), not
   "late vs overall," and the module omits the >1.3 slow-burn case.

5. **Give the stats whitelist a selection rule, not just a glossary.** A 3-row table:
   continuous→welch, conversion→proportion, ratio→ratio_metric (delta method, one-line
   why). Tie it to the `checkout_redesign` fixture, which is explicitly about metric
   type affecting power.

6. **Explain why SRM halts rather than flags, in stats terms.** The gauntlet (Q9) and
   teach-back both demand this; the module asserts "a broken split poisons every
   number" without the χ² reasoning that makes it convincing.

7. **Cut over-bolding by ~60%** and reserve bold for first-use term definitions.

8. **Deduplicate the four cross-module repetitions** (two-surfaces, isolation axiom,
   thesis line, honest-boundaries). One canonical home each; cross-reference. Keep the
   `_commit_stage` repeat — it's the one that's justified.

9. **Verify the labs run end-to-end before release.** I could mechanically follow
   Labs 4 and 5 (and verified the asserted behavior against the source). But Lab 3b
   ("predict all 8 fixtures cold... the README cheat-sheet has the answers") points at
   a cheat-sheet whose verdict names don't exist in the code — a learner following the
   lab will get confused, not corrected. Reconcile fixture cheat-sheet ↔ code labels.

10. **Add one explicit forward-reference discipline.** Module 1 Stage 3 ("Power") and
    Module 3 both lean on stats the reader hasn't been given. Either move the stats
    primer (fix #3) earlier, or add a one-line "you'll get the stats in Module 3 §0 —
    for now, treat MDE as 'the smallest effect worth detecting'" so the stats-weak
    reader isn't stranded twice.
