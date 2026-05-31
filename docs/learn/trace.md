# Appendix — the one-number trace

> **Goal:** Follow a *single number* from a raw CSV cell all the way to the chain
> hash, through every stage that touches it. Modules 1–9 teach the system one
> subsystem at a time. This appendix does the opposite: it picks one value and
> refuses to let go of it, so you can see how the eleven stages, the deterministic
> core, the readout, and the audit chain are all the *same* number wearing
> different clothes. When you can narrate this trace cold, you understand the
> pipeline end to end — not as a diagram, but as a thing that happens to one
> datum.

We trace `ship_demo.csv`, the E2E anchor fixture (Module 1). Our number is the
**treatment group's conversion count: 384**. Everything below is the real value
the code produces — verify each one yourself with the commands at the end.

---

## The number at a glance

| Stage | What our number *is* here | Value | Where to see it |
|-------|---------------------------|-------|-----------------|
| 0 | one `converted` cell for one user — a single `1` | `1` | `sample-data/ship_demo.csv` |
| 0.75 | the metric that *counts* those cells gets defined | `conversion = mean(converted)` | metric_drafter artifact (Stage 0.75) |
| 3 | the brief pre-registers it as the **primary** + the MDE bar | primary = conversion | locked `brief.yaml` (Module 4) |
| 5 | the split that makes the count trustworthy (SRM) | 3000 / 3000, `srm_pass=True` | monitor artifact (Module 1) |
| 6 | SQL `SUM(converted)` over the treatment rows | `384` (of 3000 → `0.1280`) | `query.executed` event + analyzer output |
| 6 | differenced against control `0.1047` | abs `+0.0233`, rel `+22.3%` | `proportion_test` (`stats/ab_tests.py:156`) |
| 7 | flattened to one `TreeInput` field | `primary_lift_magnitude` + the 4 CI bounds | `TreeInput` (`interpret/tree.py:83`) |
| 7 | walked through the 8-step tree | verdict **SHIP** | `TreeResult.verdict` (`tree.py:108`) |
| 8 | rendered as a human sentence | "+22.3% conversion …" | readout artifact |
| all | folded into the append-only audit trail | a `query.executed` / `agent.completed` row | `log.jsonl` |
| all | hashed into the chain digest | one input to `canonical_chain_hash` | `audit/storage.py:134` |

---

## The trace, hop by hop

**Stage 0 — the cell exists.** Open `ship_demo.csv`. Somewhere in the treatment
rows is a user with `converted = 1`. That single cell is our number's birth. The
profiler (Stage 0) reads the file and reports its shape; it does *not* yet know
that `converted` is a metric. At this point our `1` is just one of 6,000 cells in
a column.

**Stage 0.75 — the metric that will count it.** The metric_drafter proposes a
metric definition: conversion = `mean(converted)` per variant. *Now* our cell has
a job — it's one of the things that metric will average. Nothing has been computed
yet; the definition is a promise about how the count will be taken.

**Stage 3 — the brief locks the bar.** The drafter writes the brief and it gets
**locked** (Module 4): conversion is the **primary** metric, with a registered MDE
and direction (`higher_is_better`). This is the moment that matters for honesty —
the bar our `+22.3%` will later be judged against is fixed *before* anyone has
seen the 384. Existence of the locked `brief.yaml` on disk is the lock; you cannot
quietly move the bar after you see the lift.

**Stage 5 — the count is made trustworthy.** Before anyone trusts the conversion
*rate*, the monitor runs the sample-ratio-mismatch check: 3000 control vs 3000
treatment, `srm_pass = True`. This is why the count is interpretable at all — a
broken split (Module 3, `srm_violation.csv`) would halt here and our 384 would
never be read as a real result. Trust precedes measurement.

**Stage 6 — the count happens, and becomes a lift.** The sql_query_writer emits a
query that `SUM`s `converted` over the treatment rows and divides by the count.
The warehouse runs it (a `query.executed` event lands in the log). The result:
**384 / 3000 = 0.1280**. Control is **314 / 3000 = 0.1047**. The analyzer feeds
both into `proportion_test` (`stats/ab_tests.py:156`), which returns the absolute
difference `+0.0233`, the relative lift `+22.3%`, and the 95% / 90% confidence
intervals. Our `1`-cell is now one 3000th of a *lift*.

> **Aha — this is the exact handoff the isolation axiom protects.** The analyzer
> computes the lift but is blind to the *hypothesis intent* (Module 2). It hands
> the interpreter numbers, not hopes. Our 384 crosses from "data" to "judgment"
> here, and the wire that would let the hope leak across is deliberately cut.

**Stage 7 — the lift becomes a single decision-relevant scalar, then a verdict.**
The interpreter flattens the analyzer bundle into a `TreeInput` (`tree.py:83`).
Our number is now `primary_lift_magnitude` plus four CI bounds
(`primary_ci_lower_95`, `..._upper_95`, `..._lower_90`, `..._upper_90`). `walk_tree`
walks the eight steps in order (Module 3): SRM passes (Step 1), no guardrail breach
(Step 2), well-powered (Step 3), the 95% CI excludes 0 on the benefit side and the
magnitude clears the MDE bar — so the walk falls through to **SHIP**. The verdict
is a pure function of those scalars; the same inputs always produce the same label.

**Stage 8 — the verdict becomes a sentence.** The readout renders the verdict into
human prose — a line on the order of *"Ship: +22.3% conversion (95% CI excludes
0), guardrails clean, well-powered."* The readout's only job is to explain the
decided verdict honestly; a readout that argued for a *different* verdict would be
"wrong by construction" (Module 2). Our 384 is now a recommendation a human reads.

**Every stage — the number is recorded, then hashed.** Each step above appended
events to `log.jsonl`: a `query.executed` carrying the SQL that counted our cell,
an `agent.completed` carrying the analyzer's output, a `stage.committed` advancing
the pipeline (Module 6's append-then-advance). Finally `canonical_chain_hash`
(`audit/storage.py:134`) folds the whole ordered event list into one digest. Our
number is now part of a tamper-evident chain: change the 384 anywhere and the hash
no longer matches (Module 4). The datum that started as a single `1` in a CSV ends
as one contributor to a cryptographic commitment that the analysis happened the
way the log says it did.

---

## Verify it yourself

The conversion counts and lift are real — reproduce them directly:

```bash
$ .venv/bin/python - <<'PY'
import csv
from collections import defaultdict
n = defaultdict(int); c = defaultdict(int)
with open("sample-data/ship_demo.csv") as f:
    for row in csv.DictReader(f):
        v = row["variant"]; n[v] += 1; c[v] += int(row["converted"])
ctrl, trt = c["control"]/n["control"], c["treatment"]/n["treatment"]
print(f"control:   {c['control']}/{n['control']} = {ctrl:.4f}")
print(f"treatment: {c['treatment']}/{n['treatment']} = {trt:.4f}")
print(f"absolute lift = {trt-ctrl:+.4f}   relative = {(trt-ctrl)/ctrl*100:+.1f}%")
PY
control:   314/3000 = 0.1047
treatment: 384/3000 = 0.1280
absolute lift = +0.0233   relative = +22.3%
```

Then trace the schema hops by reading, in order:
`agentxp/stats/ab_tests.py:156` (the lift + CI), `agentxp/interpret/tree.py:83`
(the `TreeInput` our number flattens into), the `walk_tree` steps just below it
(the SHIP path), and `agentxp/audit/storage.py:134` (the hash that closes the
loop). To watch the *whole* pipeline produce these for real, drive `ship_demo.csv`
Stage 0→8 in Claude Code (Module 1) and `agentxp audit <exp_id>` the result.

> **Where this lands you.** The modules teach the subsystems; this trace proves
> they're one system. If you can retell the 384 story — cell → metric → locked
> bar → trustworthy split → lift → scalar → verdict → sentence → event → hash —
> without notes, you can stand in front of any reviewer and show that AgentXP
> isn't a pile of parts. It's one honest path a number walks, with a guardrail at
> every join. That's the capstone claim (Module 8), made concrete.
