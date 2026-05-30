# Module 3 — The deterministic core

> **Goal:** Own the part of AgentXP that an LLM is *not allowed to touch*: the
> statistics and the verdict tree. By the end you can name what's in the stats
> whitelist, walk the 8-step decision tree cold on a novel analyzer output, and
> predict the verdict (and the exact step that fires) for any of the eight
> fixtures before you run it.

---

## Why (the design reasoning)

The thesis says deterministic Python owns the statistics and the LLM owns the
judgment. This module is the "deterministic Python" half, and the reason it
exists is simple: **the things a wrong answer would corrupt must be code, not
prose.** A confidence interval computed by a language model is a confidence
interval you can't replay and can't trust. A verdict reached by free-form
reasoning is a verdict that can be argued into anything. So both are pulled out of
the LLM's hands entirely:

- The **stats** are a fixed whitelist of pure functions in `agentxp/stats/`. The
  analyzer agent (Stage 6) doesn't *compute* — it *calls*. It picks which function
  applies and reports the number the function returns.
- The **verdict** is a pure function `walk_tree(TreeInput) -> TreeResult` in
  `agentxp/interpret/tree.py`. The interpreter agent (Stage 7) doesn't decide the
  label by reasoning — it supplies the tree's inputs and the tree decides. Same
  inputs, same verdict, every time, forever.

This is why the verdict is *replayable* (Module 0's third subsystem): given the
locked rule and the logged numbers, anyone can re-run the tree and get the same
label. The claim is never "trust the model's judgment." It's "here are the inputs;
run the function yourself."

The deep point for a reviewer: **the LLM's judgment is real and valuable, but it
is confined to the places where being wrong is recoverable** — eliciting a
hypothesis, choosing which test applies, explaining a verdict. The places where
being wrong is *unrecoverable* (the arithmetic, the decision) are deterministic.
The line between them is the line between `agents/` and `agentxp/`.

---

## Walkthrough — the two pieces

### Piece 1: the stats whitelist (`agentxp/stats/`)

Open `agentxp/stats/__init__.py`. The `__all__` list is the whitelist — about 30
exported symbols, and that list *is the contract*: if a statistical operation
isn't here, the analyzer can't invoke it. Nothing computes statistics off-list.

The load-bearing functions to know by signature:

- `welch_test(...)` — two-sample Welch's t-test for continuous metrics (unequal
  variance, the safe default).
- `proportion_test(...)` — two-proportion test for conversion-style metrics.
- `ratio_metric_test(...)` — for ratio metrics (e.g. revenue-per-user) where the
  denominator varies; delta-method variance.
- `srm_check(...)` — sample-ratio-mismatch χ²: did randomization actually split
  the traffic as designed? A failed SRM *halts* (INVALID-SRM), it doesn't get
  papered over.
- `power_proportion(...)` — power / MDE / required-n for the design stage.
- `adjust_pvalues(...)` — multiple-comparison correction when there's more than
  one metric.
- `msprt_test(...)` — mixture-SPRT for sequential looks (the peeking-safe test;
  wired behind the sequential path).

The point isn't to memorize signatures — it's to internalize that **the analyzer
chooses among a fixed menu of correct functions; it never improvises math.**

#### The five terms the tree runs on

You don't need a statistics course to read the tree, but five terms carry all the
weight. Get these and Step 3-7 stop being symbols:

- **MDE (minimum detectable effect).** The smallest effect the experiment was
  *designed* to catch, set at the brief. `mde_pct` is relative (2.0 = 2% of
  baseline); `_mde_absolute` converts it to metric units. The tree compares the
  observed effect against this, not against zero.
- **Power / required-n.** Power is the probability of detecting a real effect of
  MDE size; you pick a target (usually 80%) and it implies `n_required`. When
  `n_observed < n_required`, you under-collected — that's what Step 3 keys on.
- **Confidence interval (90% / 95%).** The plausible range for the true effect.
  "Excludes 0" means the whole range is on one side of zero (a real direction);
  "straddles 0" means it spans zero (could be nothing). The tree reads two widths
  because Step 5 uses the gap between them.
- **CI half-width vs MDE.** Half the 95% interval's span. If it's wider than `2 ×
  mde_absolute` on a null, the study couldn't resolve an MDE-sized effect → NO-LIFT
  (Step 4). This is the precision check.
- **SRM (sample-ratio mismatch).** A χ² test asking whether the traffic split
  matched the design (e.g. a planned 50/50 that came in 52/48). A failed SRM means
  randomization is broken, so Step 1 halts before any lift is read.

`late_ratio` (Step 7) and the delta method (`ratio_metric_test`'s variance) are the
two you can treat as black boxes for now; `late_ratio` is defined fully under the
tree below.

### Piece 2: the 8-step decision tree (`agentxp/interpret/tree.py`)

This is the heart of the module. `walk_tree(TreeInput) -> TreeResult` is a pure
function that walks **8 ordered steps**; the **first step whose condition fires
terminates** and returns that verdict. Order is everything — a later, gentler
verdict can't override an earlier, stricter one because the earlier one already
returned.

Two things to get straight before the steps. First, the closed `Verdict` set has
**eight labels**, defined in `tree.py` (lines 29-38):

```python
INVALID-SRM, NO-SHIP-GUARDRAIL, INCONCLUSIVE, NO-LIFT,
DIRECTIONAL-ONLY, LIFT-WITH-CAVEAT, SHIP, LEARN
```

Second, **steps and verdicts are not one-to-one.** There are eight *steps* and
eight *verdicts*, but Step 7 can emit either SHIP or LIFT-WITH-CAVEAT, Step 8 is
the LEARN terminal, and Steps 4-7 all read the same primary-metric CIs from
different angles. Here is what each step checks and the verdict it can emit:

1. **Step 1 — SRM gate.** `srm_pass` is false and no override was resolved →
   **INVALID-SRM**, terminate. Randomization is broken, so nothing downstream is
   interpretable. It is step 1 because a bad split poisons every later number. (A
   resolved `srm_override` lets the walk continue.)
2. **Step 2 — guardrails.** Any guardrail's 90% CI excludes 0 on its *harm* side →
   **NO-SHIP-GUARDRAIL**. The rule beats the number: even a positive primary can't
   buy back a breached guardrail.
3. **Step 3 — sample adequacy.** `n_observed < n_required` *and* the primary 95% CI
   straddles 0 → **INCONCLUSIVE**. You under-collected and the result is a wash —
   you can't tell anything yet.
4. **Step 4 — well-powered wide null.** 95% CI straddles 0, `n_observed >=
   n_required`, *and* the CI half-width is wider than `2 * mde_absolute` →
   **NO-LIFT**. You had the sample size you planned for and still got a CI too wide
   to be useful — the effect, if any, is smaller than you powered for.
5. **Step 5 — directional-only.** 95% CI straddles 0 but the 90% CI excludes 0 →
   **DIRECTIONAL-ONLY**. There's a lean, but not at the bar you pre-registered.
6. **Step 6 — magnitude vs MDE.** The 95% CI excludes 0 on the benefit side but the
   absolute lift is smaller than `0.5 * mde_absolute` → **LIFT-WITH-CAVEAT** (reason:
   `small_lift`). Statistically real, practically tiny.
7. **Step 7 — novelty / late-window.** The 95% CI excludes 0 on the benefit side and
   the lift is at least `0.5 * mde_absolute`. Now `late_ratio` decides: `None` or
   `>= 0.7` → **SHIP**; `< 0.7` → **LIFT-WITH-CAVEAT** (reason: `novelty`) because the
   effect is decaying and may be a launch bump, not a durable win.
8. **Step 8 — LEARN (terminal).** Nothing above fired. A real null you can act on:
   the diagnostics record the subcase — `well_powered_null`, `underpowered`, or
   `analysis_incomplete`.

Note what is *not* a tree verdict: segment reversal / Simpson's paradox. The tree
walks the **primary** metric; conflicting segments are surfaced by the analyzer and
become a `CONTRADICTORY_SEGMENTS` reason code at readout sign-off (Stage 8), not a
ninth verdict. So `mixed_results.csv` walks the tree on its primary like any other
fixture; the "investigate" framing lives in the human readout, not in `walk_tree`.

The constants that tune the boundaries (all in `tree.py`, all named so you can
find them):

- `NOLIFT_CI_WIDTH_MULTIPLIER = 2.0` (Step 4) — how wide the 95% CI half-width must
  be, relative to `mde_absolute`, before a straddling null reads as NO-LIFT.
- `MDE_HALF_FRACTION = 0.5` (Steps 6 and 7) — the half-MDE bar an exclusion has to
  clear to count as a meaningful lift rather than LIFT-WITH-CAVEAT (small).
- `NOVELTY_LATE_RATIO_FLOOR = 0.7` (Step 7) — the novelty guard. `compute_late_ratio`
  (tree.py:186) is `late_window_effect / early_window_effect` (the exposure window
  split into thirds: early = first third, late = last third). Below 0.7 the effect
  is decaying, so the verdict flags novelty instead of crowning a SHIP that's really
  a launch bump. `None` (early effect 0, or non-finite) is treated as "unavailable"
  and does *not* block a SHIP.

### The confidence label (`agentxp/interpret/confidence.py`)

Separate from the verdict, `map_confidence(...)` assigns one of **7
`ConfidenceLabel` values** describing how *strongly* the inputs support the
verdict (tight CI, clean power, no novelty → high; wide CI or novelty flags →
lower). The verdict says *what*; the confidence label says *how sure*. Don't
conflate them — a SHIP can be low-confidence and that nuance is exactly what an
honest readout (Stage 8) surfaces.

---

## Lab / break-it (walk the tree by hand)

**Lab 3a — run the tree in Python.** The tree is a pure function, so you can drive
it directly without the whole pipeline:

```bash
$ .venv/bin/python
```
```python
from agentxp.interpret.tree import walk_tree, TreeInput
# Build a TreeInput that mimics a clean positive result:
#   primary lift positive, CI excludes 0, SRM ok, guardrails ok, well powered.
# Inspect the fields TreeInput expects, then construct one and call:
result = walk_tree(my_input)
print(result.verdict, result.step_fired)   # predict before you print
```

Read the `TreeInput` dataclass first so you know every field the tree consumes —
those fields are the *complete* set of things the verdict depends on. Anything not
in `TreeInput` (your hopes, the hypothesis prose) provably cannot change the
verdict. That's the isolation axiom (Module 2) expressed as a type.

> **Not a Python person?** You don't need to run `walk_tree` to do this module. Open
> `agentxp/interpret/tree.py` and *read* `walk_tree` top to bottom — it's eight
> `if` blocks in order. Then drive the fixtures with `/experiment` (Lab 3b) and read
> the verdict + step from the readout. The point is the ordering, not the syntax.

**Lab 3b — predict all 8 fixtures cold.** For each fixture, write down the verdict
*and the step number you think fires*, then run `/experiment` on it and check:

| Fixture | Your predicted verdict | Predicted step |
|---------|------------------------|----------------|
| `clean_ab.csv` | ? | ? |
| `ship_demo.csv` | ? | ? |
| `checkout_redesign.csv` | ? | ? |
| `no_effect.csv` | ? | ? |
| `underpowered.csv` | ? | ? |
| `srm_violation.csv` | ? | ? |
| `guardrail_violation.csv` | ? | ? |
| `mixed_results.csv` | ? | ? |

(The README cheat-sheet has the answers — but predict *first*, including the step,
then check. Getting the step right is harder than the verdict and proves you
understand the ordering.)

**Lab 3c — break the ordering intuition.** Take `guardrail_violation.csv` (primary
flat-to-positive, latency +16%). Confirm it lands NO-SHIP-GUARDRAIL at **step 2**,
*before* the SHIP path at step 7 could ever fire. Then ask yourself: what if the
guardrail check ran *after* the SHIP path? A positive primary would crown a SHIP
and the breached guardrail would never block it. Articulate why "guardrail before
ship" is not arbitrary — it's the encoded version of "the rule beats the number."

---

## Teach-back checkpoint

You pass Module 3 when you can, without notes:

1. **Explain why stats and the verdict are deterministic Python, not LLM
   reasoning** — in terms of recoverable vs unrecoverable error.
2. **Name the stats whitelist's role** and four of its functions, including which
   one *halts* the pipeline and why.
3. **Walk the 8-step tree cold** on an analyzer output I give you: name the
   verdict and the exact step that fires, and explain why an earlier step can
   pre-empt a later one.
4. **Distinguish the verdict from the confidence label** and explain what each
   answers.
5. **Defend the constant.** Pick `NOVELTY_LATE_RATIO_FLOOR = 0.7` (or another) and
   explain what failure mode it's guarding against.

I'll hand you a novel `TreeInput` and ask for the verdict, the step, and the
confidence band. When you can do all three from the fields alone, check the box
and we go to Module 4.
