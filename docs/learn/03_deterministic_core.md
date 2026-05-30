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
  analyzer agent (Stage 5) doesn't *compute* — it *calls*. It picks which function
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

### Piece 2: the 8-step decision tree (`agentxp/interpret/tree.py`)

This is the heart of the module. `walk_tree(TreeInput) -> TreeResult` is a pure
function that walks **8 ordered steps**; the **first step whose condition fires
terminates** and returns that verdict. Order is everything — a later, gentler
verdict can't override an earlier, stricter one because the earlier one already
returned.

The 8 verdicts (the `Verdict` literals) and the gist of the step that produces
each:

1. **INVALID-SRM** — SRM χ² fails. Randomization is broken, so *nothing
   downstream is interpretable*. Halt first, before reading any lift. (This is why
   it's step 1: a broken split poisons every later number.)
2. **NO-SHIP-GUARDRAIL** — a guardrail metric breached its locked threshold. The
   rule beats the number: even if the primary went up, a broken guardrail blocks
   the ship.
3. **SHIP** — primary metric moved in the pre-registered direction, CI excludes
   the null, guardrails intact, adequately powered.
4. **NO-SHIP** — primary moved against you (or the CI sits on the wrong side).
5. **LEARN (powered)** — a real null: adequately powered, CI tight around zero.
   This is a *finding*, not a failure — you learned the effect isn't there.
6. **LEARN (underpowered)** — null but the CI is too wide to conclude anything;
   you didn't have the sample to see an effect this size.
7. **caveat / investigate** — e.g. segment reversal (Simpson's paradox): the
   aggregate and the segments disagree, so the average is lying. Don't ship on a
   number you don't understand.
8. **(terminal/fallback)** — the catch-all when none of the cleaner conditions
   fire.

The constants that tune the boundaries (all in `tree.py`, all named so you can
find them):

- `NOLIFT_CI_WIDTH_MULTIPLIER = 2.0` — how wide the CI must be (relative to MDE)
  before "no lift" reads as *underpowered* rather than a *real null*.
- `MDE_HALF_FRACTION = 0.5` — the half-MDE band used to separate "meaningfully
  flat" from "couldn't tell."
- `NOVELTY_LATE_RATIO_FLOOR = 0.7` — the novelty/late-period guard: `compute_late_ratio`
  (tree.py:186) compares late-window effect to overall; if the effect is decaying
  below this floor, the verdict flags novelty rather than crowning a SHIP that's
  really just a launch bump.

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
*before* any SHIP logic at step 3 could fire. Then ask yourself: what if steps 2
and 3 were swapped? Articulate why "guardrail before ship" is not arbitrary —
it's the encoded version of "the rule beats the number."

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
