# AgentXP — User Journeys (Outside-In)

**What this document is.** Every other doc in this repo describes AgentXP from the inside: stages, agents, schemas, the audit chain. This one describes it from the *outside* — from the seat of a person who has opened Claude Code, is sitting in this repo, and is talking to Claude in plain English. The unit of this document is **the sentence the user types**, not the function that runs.

**Why it exists.** AgentXP is meant to be an *agentic* system: you say what you want, Claude infers intent, confirms it, asks back when it's genuinely uncertain, and offers a menu when there's a real fork. You should almost never have to know a stage number, a command flag, or a file path. This document is the yardstick for that claim. If a journey here can't be driven by conversation, that's a finding — and we annotate it inline as a gap rather than hiding it.

**How to read it.**
- Each journey leads with **what the user says** (the real phrasings, not one canonical command).
- Then **the conversation** — turn by turn, the way it should actually read on screen.
- Then the **interaction rule**: when Claude should *infer and proceed*, when it should *ask one question*, and when it should *offer a menu*. This is the heart of the agentic contract.
- Then **boundaries** — what Claude must refuse, halt on, or be honest about not knowing.
- Then **Behind the curtain** — the skill/code that serves the journey, and a candid **Today** note where the intended behavior and the current build diverge.

**The interaction contract, stated once.** Three modes, and choosing the right one is the whole game:
- **Infer & proceed** when the intent is unambiguous and the action is cheap or reversible. State the inference in one clause, do it, show the result. (*"Reading that as a proportion metric — say so if it's a mean."*)
- **Ask one question** when a single missing fact blocks correctness and Claude can't safely default it. Ask exactly one, with a stated fallback. (*"How big a lift makes this worth shipping? If you don't have a number, I'll size for 2pp absolute."*)
- **Offer a menu** when there's a genuine fork with no safe default and the choices are closed. Number them, keep them to 2–4, make the consequence of each explicit. (timestamp coercion, SRM override, resume recovery.)

A halt is not a menu. When randomization is broken or a guardrail is breached, Claude *stops and says so* — it does not offer "ship anyway" as a friendly option. Overriding a halt is always an explicit user action with a recorded reason.

---

## The cast (three lenses, one system)

The same system serves three people who enter it differently. We follow all three.

- **Maya — Product Manager.** Lives in the conversation. Doesn't write SQL, doesn't import Python, never sees a stage number. Wants a defensible verdict she can paste in Slack. The full happy path is hers.
- **Mira — Engineer / builder.** Comfortable in SQL and a warehouse. Wants the stats engine and the audit trail, drives some of it from a notebook, connects AgentXP to her company's Snowflake. Uses the conversation selectively.
- **Lin — Data scientist.** Has her own stats opinions. Wants the *library* (vetted tests) and the *renderer* (consistent readouts), called from a notebook. Treats the conversation as optional scaffolding around code she trusts.

Maya is the spine. Mira and Lin show where the system has to stay a good library and a good integration target, not just a good chatbot.

---

# Part 0 — First contact and setup

### J0.1 — "Claude, clone this repo and set it up"

**What the user says** (any of these):
- "Claude, clone https://github.com/ai-analyst-lab/agentxp.git and set it up."
- "Pull down agentxp from GitHub and get it ready to run."
- "I want to try this experimentation tool — here's the link. Take it from here."

**The conversation:**

```
You: Claude, clone https://github.com/ai-analyst-lab/agentxp.git and set it up.

Claude: Cloning it and installing in editable mode.

  cloned → ./agentxp
  pip install -e .  → agentxp 0.1.0

You're set. AgentXP runs A/B experiments as a guided conversation — you
describe the test in plain English, I walk the analysis, and you get a
verdict with an audit trail anyone can replay.

Two ways in from here:
 - Point me at a data file and we'll start: "test the new checkout button,
   data's at ~/data/checkout.parquet"
 - Or just describe the test and I'll ask where the data lives.

There's also shipped sample data if you want to see it work first —
say "show me a demo run" and I'll use a fixture.
```

**Interaction rule.** *Infer & proceed* on the clone + install — it's exactly what was asked and it's reversible. Then *offer a menu* of next steps, because at first contact the user genuinely has a fork (bring-your-own-data vs. demo) and no basis to know the options. Do **not** dump the 11-stage table or the command list; the agentic promise is that the user never needs it.

**Boundaries.** Claude installs into the environment the user is already in; it does not create or switch virtualenvs without saying so. If `pip install -e .` fails (no Python 3.11+, no write permission), Claude reports the exact failure and the one fix, rather than retrying silently.

**Behind the curtain.** Plain `git clone` + `pip install -e .` via Bash. The "two ways in" menu maps to the `/experiment` skill's entry modes (`from_data`, `full`). **Today:** this works — it's shell plus the `/experiment` skill description. The only gap is cosmetic: there is no `agentxp doctor` that confirms the environment is sound, so a half-broken install surfaces at first use rather than at setup.

---

### J0.2 — "What can this thing do?"

**What the user says:** "What can you actually do with this?" / "What is agentxp?" / "Give me the tour."

**The conversation:**

```
You: what can this actually do?

Claude: AgentXP runs controlled experiments — A/B tests — end to end, as a
conversation. You bring data and a question; I handle the discipline:

 - I profile your data and flag quality problems before they bite.
 - I help you write down the hypothesis and the decision rule *before*
   we look at results, so the verdict can't be reverse-engineered to
   fit what you hoped for.
 - I check that the experiment actually randomized (SRM) and halt if it
   didn't.
 - I run the stats, apply your pre-registered decision rule, and write a
   readout you can hand to a stakeholder.
 - Every choice lands in an audit log a second reviewer can replay.

What I deliberately don't do in this version: causal inference on
observational data, multi-user collaboration, and reading from a cloud
warehouse (that lands in the next version — local files only for now).

Want to run one? Point me at a data file, or say "demo" for a sample.
```

**Interaction rule.** *Infer & proceed* — answer at the level of "what decisions does this help me make," not "here are 13 agents." End with the same low-friction invitation. The honest "don't do" list is part of the answer, not a footnote.

**Boundaries.** The capabilities statement must match the build. The warehouse line is the load-bearing honesty: registering a warehouse credential works; *reading from it* does not yet (Part 1, J1.2).

**Behind the curtain.** Sourced from `README.md` + `KNOWN_LIMITATIONS.md`. **Today:** accurate as written, provided Claude reads the limitations rather than overselling. This is a place the system can drift — an over-eager description that promises warehouse reads would be a regression against this journey.

---

# Part 1 — Connecting to data

### J1.1 — "My data's right here" (local file / DuckDB)

**What the user says:**
- "Test whether the new checkout button improves completion. Data's at ~/data/checkout_test.parquet."
- "Here's a CSV: ~/exports/ab_run.csv. Did the banner work?"
- "Analyze sample-data/clean_ab.csv."

**The conversation:**

```
You: Test whether the new checkout button lifts completion.
     Data's at ~/data/checkout_test.parquet.

Claude: Saving everything to ./experiments/exp_001/. No semantic model on
file for this dataset yet, so I'll look at it before we design the test —
should be a question or two.

  read: ~/data/checkout_test.parquet
  rows: 91,204   cols: 11   date range: 2026-05-19 → 2026-05-26

Looks clean: no mixed types, identifier null rate 0.0%, assignment column
"variant" with two values (control, treatment). I'll treat "variant" as the
assignment and "completed" as the outcome — tell me if either is wrong.

Now: what counts as success? I'm reading this as completion rate
(a proportion). What's the smallest lift that would make you ship it?
```

**Interaction rule.** *Infer & proceed* on the file read, the experiment directory, and the obvious column roles — each stated in one clause and correctable. *Ask one question* only for the thing Claude genuinely can't default: the minimum detectable effect (and even there, offer the 2pp fallback if the user shrugs). Local files are zero-friction by design: no `connect` step, no credentials, DuckDB reads the file inline.

**Boundaries.** If the file doesn't exist or isn't readable, Claude says so and stops — it does not fabricate a profile. If the assignment column is ambiguous (three values, or none obviously binary), that becomes a menu, not a silent guess.

**Behind the curtain.** `/experiment --data <path>` → Stage 0 profiler (DuckDB `SUMMARIZE` + data-quality heuristics). **Today:** the profiler and its heuristics are built and complete; the conversational front-door is the `/experiment` skill with Claude playing the profiler agent. This is the most-load-bearing working path.

---

### J1.2 — "It's in our warehouse" (Snowflake / BigQuery / Databricks)

**What the user says:**
- "The data's in Snowflake — analytics.prod.checkout_events. Can you pull it?"
- "Connect to our BigQuery and run the test on the rollout table."

**The conversation (intended):**

```
You: The cohort data's in Snowflake, analytics.prod.checkout_events.
     Pull it and run the test.

Claude: I can register a Snowflake connection now — I'll collect the account,
user, warehouse, and role, and store them as a credential profile with no
secret written to disk in the clear. Want me to set that up?

  [collects credentials securely, never echoed]
  wrote: ~/.agentxp/profiles/snowflake_prod  (chmod 600)

Connection registered.

Honest boundary: in this version I can *register* the warehouse but I can't
yet *read* from it — warehouse-backed profiling lands in v0.1.1. For right
now, either export the cohort to a parquet/CSV and point me at the file, or
I can walk you through the query to run in Snowflake and export.
```

**Interaction rule.** *Infer & proceed* to offer the credential wizard (registration is real and safe). Then **state the boundary honestly before the user hits it** — this is the single most important honesty beat in the whole document. The agentic temptation is to pretend the read works; the correct behavior is to name the gap and offer the export workaround.

**Boundaries.** Credentials are collected with no-echo input, routed through the redactor before any log/terminal output, stored chmod 600, and referenced as `env:VAR` where possible rather than written raw. No secret ever appears in an exception message or the audit log.

**Behind the curtain.** `agentxp connect <dialect> <name>` registers a profile; the three warehouse adapters (`sql/adapters/`) are code-complete. **Today (gap, by design):** `connect` registration works, but `profile --adapter snowflake` returns a "ships in v0.1.1" message — the adapters are *live-unverified* because there are no test credentials. The conversational layer must surface this as the workaround above, not as a failure. This is the one place where "agentic" currently means "agentically tells you the truth about what it can't do yet."

---

### J1.3 — "Just show me it works" (demo on a fixture)

**What the user says:** "Show me a demo." / "Run it on sample data so I can see the shape." / "Do the one with the broken randomization."

**The conversation:**

```
You: show me a demo — ideally one where something goes wrong

Claude: Good one to see. I'll run sample-data/srm_violation.csv — the
randomization is deliberately broken, so you'll see the system *halt* instead
of handing you a verdict from contaminated data. Starting now.

  [profiles, designs a one-line brief with you, reaches the SRM check]

  HALT — sample-ratio mismatch.
  observed control=5,600  treatment=4,400   expected 5,000 / 5,000
  chi-squared = 144.0, p < 0.001

I'm stopping here. The split is too far from 50/50 to trust — whatever the
lift looks like, it's confounded by who landed in which arm. For a real test
you'd fix the assignment system and rerun. Want me to override it just so you
can see the rest of the flow? (I'll record the override and the reason.)
```

**Interaction rule.** *Infer & proceed* to pick a fixture matching the user's ask ("something goes wrong" → the SRM fixture). The halt is a *halt*, not a menu — but offering to override **for demo purposes, with the override recorded** is legitimate because the user explicitly asked to see the flow.

**Boundaries.** Even in demo mode, an override is an explicit, logged decision with a reason. The system never silently continues past a broken-randomization halt.

**Behind the curtain.** Maps to the QUICKSTART hand-walk. **Today:** the fixtures exist (`sample-data/`), the SRM stats are built; the halt-and-override beat is real. The gap is that there is no `experiments/` directory in the repo yet — the system has not been run end-to-end on a fixture, so this journey is *intended-and-plausible* but not yet *demonstrated*. (This is exactly the end-to-end smoke run the follow-up plan will verify.)

---

# Part 2 — The core experiment as a conversation

This is Maya's spine. One continuous conversation from "I want to test X" to a verdict she can paste in Slack. The stage machinery is entirely behind the curtain.

### J2.1 — The full happy path

**What the user says** to start: "I want to test whether a free-shipping banner at checkout lifts completion without hurting average order value. Data's at ~/data/checkout.parquet."

**The conversation (compressed to the beats that matter):**

```
Claude: [profiles silently if clean] 91k sessions, clean, "variant" splits
~50/50. Reading your goal as:
  primary:   checkout completion rate (proportion)
  guardrail: average order value (must not drop > 2%)
  direction: completion up, AOV held
That right? And what's the smallest completion lift worth shipping?

You: yes. 2 points.

Claude: Got it. Here's the brief I'll hold us to — note the decision rule is
fixed *now*, before we look at results:

  Ship if: completion lift ≥ +2pp AND 95% CI excludes zero
           AND AOV does not drop more than 2%.
  Otherwise: no-ship or iterate.

Locking that. [writes brief]  Checking randomization next… SRM passes
(4,991 / 5,009 vs 5,000 / 5,000, p = 0.78). Running the analysis.

  primary:   completion 16.4% → 18.7%   +2.3pp  95% CI [+1.1, +3.5]
  guardrail: AOV $67.42 → $64.91        −3.7%   95% CI [−5.1, −2.3]

## Verdict: NO-SHIP (guardrail breach)
Completion lifted a real +2.3pp — that clears your bar. But AOV dropped 3.7%,
and the decision rule you set says AOV can't drop more than 2%. The rule
decides this, not me: no-ship on the current variant.

Stakeholder paragraph (paste-ready):
> The free-shipping banner lifted checkout completion +2.3pp (95% CI
> [+1.1, +3.5]) — a real gain. But average order value fell 3.7%, breaching
> the 2% guardrail we set before the test. Net revenue per session is up, so
> there's a case to ship for top-line and own the AOV story — but by the rule
> we pre-registered, this is a no-ship. Recommend iterating the threshold.

Wrote report.md and report.json. Want the audit trail, or to compare against
another run?
```

**Interaction rule.** The whole path is *infer & proceed* punctuated by exactly the confirmations that carry judgment: the metric reading, the MDE, the brief lock. Claude does **not** ask the user to approve each stage transition — those are invisible. The brief lock is the one ceremonial pause, because pre-registration is the product's whole point.

**Boundaries.** The verdict is bound to the pre-registered rule, stated explicitly ("the rule decides this, not me"). The interpreter never sees the original hopeful framing; the readout never revisits the verdict. If results are inconclusive, Claude says "inconclusive" rather than narrating a story that rescues the result.

**Behind the curtain.** Stages 0→8: profiler → (semantic/metric bootstrap) → elicitor/drafter/editor/consistency_judge → monitor → analyzer → interpreter → readout. Claude is the orchestrator, playing each agent and committing each stage via the real `_commit_stage`. **Today (two real defects to fix before this is trustworthy):**
1. **Verdict vocabulary is split.** The interpreter emits one set of verdict labels (`tree.py`: `SHIP / NO-SHIP-GUARDRAIL / INCONCLUSIVE / …`) while the report schema expects a *different, incompatible* set (`report.py`: `NO_SHIP_PRIMARY / ITERATE_WEAK / …`). Stage 7→8 can hand off a verdict the readout schema rejects. This must be reconciled to one closed set.
2. **End-to-end has not been run.** No `experiments/` directory exists; the path above is designed and individually-built but not yet demonstrated start to finish. The follow-up plan's first task is a Stage 0→8 smoke run on a fixture.

---

### J2.2 — "I already have a brief" (analyze-only)

**What the user says:** "The hypothesis and decision rule are already written — I just need the analysis. Data's here, brief's here."

**The conversation:**

```
You: PM already wrote the brief, it's in this Notion page / I'll paste it.
     Just run the analysis on ~/data/rollout.parquet.

Claude: Reading your brief as:
  primary: revenue per session, ship if +1.5% with CI excluding zero
  guardrail: refund rate, must not rise
I'll skip design and go straight to the randomization check and analysis.
Confirm the brief and I'll lock it as the decision rule — once locked, I
apply it cold to whatever the data says.
```

**Interaction rule.** *Infer & proceed* into analyze-only mode the moment the user signals "brief exists." *Ask one question*: confirm-and-lock the brief, because the lock is the integrity boundary. Then run silently to the verdict.

**Boundaries.** A brief supplied after data has been seen is a pre-registration risk; Claude locks it *before* reading results and timestamps the lock in the audit log, so a reviewer can see the order of operations.

**Behind the curtain.** `from_brief` plan → Stages 5–8. **Today:** the plan exists in the skill; same two defects as J2.1 apply at the Stage 7→8 boundary.

---

### J2.3 — "Just profile it, don't design anything yet"

**What the user says:** "Don't run a test — just tell me what's in this dataset." / "Profile ~/data/raw.csv."

**The conversation:**

```
You: just profile ~/data/raw.csv, I'm not ready to design a test

Claude: Profiling only — no test, no brief.

  rows: 88,401  cols: 12
  ⚠ session_started has two timestamp formats mixed (64% ISO, 36% epoch)
  ⚠ user_id null rate 4.2% — above the 1% I'd want for an assignment key
  variant: control / treatment, ~50/50
  refund_amount: 71% null (likely "no refund"), range $0–$840

That's the shape. The timestamp mix and the user_id nulls would both need a
decision before a real test. Want me to stop here, or address those now?
```

**Interaction rule.** *Infer & proceed* — profile and stop, exactly as asked. Surface the quality flags but do **not** force a fix; the user said "not ready." Offer the next step as an option, not a demand.

**Boundaries.** Profiling is read-only and side-effect-light; it doesn't create a full experiment scaffold the user didn't ask for.

**Behind the curtain.** `profile_only` plan → Stage 0 only; also reachable as `agentxp profile <path>` from the shell. **Today:** fully built and the most independently-verified surface.

---

# Part 2.5 — When it isn't a clean A/B

Maya's spine assumed two arms and a proportion metric. Real data isn't always that shape. Each entry: what the user brings, how Claude should read it, and whether v0.1 actually handles it.

### J2.5.1 — Three or more variants

**User says:** "It's a 3-way test — control, variant A, variant B." / "We ran four banner versions."

**Intended:** Claude reads the arm count off the assignment column, explains that comparisons now multiply (each variant vs. control is its own test, so multiplicity correction applies), runs pairwise with Holm correction, and surfaces a per-arm verdict rather than one global yes/no.

**Interaction rule.** *Infer* the arm count from distinct assignment values; *ask one question* only if it's unclear which arm is the baseline.

**Behind the curtain / Today (gap, verify).** The SRM check generalizes to k arms (chi-squared on k expected proportions), and Holm correction exists. But the two-sample tests, the brief, and the interpreter are built around a control-vs-treatment binary. The guided conversational flow **likely assumes two arms**; 3+ may only be reachable as pairwise library calls (Lin's path), not the guided flow. → **G12.**

### J2.5.2 — A continuous or ratio metric, not a rate

**User says:** "The metric is revenue per session, not a conversion rate." / "average session length."

**Intended:** Claude reads it as a mean or a ratio and picks Welch (mean) or the ratio test (per-user ratio with delta-method SE) instead of a proportion test — stating the reading so it's correctable.

**Interaction rule.** *Infer* the metric type from the column shape (binary 0/1 → proportion; numeric → mean; numerator/denominator pair → ratio). State it in one clause.

**Behind the curtain / Today.** `welch_test` and `ratio_metric_test` are built. **Works** — the type inference is Claude's judgment in the elicitor.

### J2.5.3 — No guardrail at all

**User says:** "I just care about completion. No guardrail."

**Intended:** Claude proceeds but names the risk once — "no guardrail means a primary win could hide a downstream cost; want me to suggest a standard one like AOV or refund rate?" — without forcing one.

**Interaction rule.** *Infer & proceed*; *offer* (not require) a guardrail.

**Behind the curtain / Today.** The brief supports optional guardrails. **Works.**

### J2.5.4 — Underpowered / tiny sample

**User says:** small-n data, hopeful framing.

**Intended:** The analysis runs, the verdict comes back inconclusive/underpowered, and Claude says honestly "you'd need ~N more per arm to detect your 2pp." It does **not** stretch a non-result into a directional story.

**Behind the curtain / Today.** There's an underpowered/inconclusive verdict, and `power` / `detectable_effect` functions compute the "you'd need N more." **Works** — modulo the verdict-enum split (G2).

### J2.5.5 — Huge sample, everything "significant"

**User says:** millions of rows, p < 0.001 on everything.

**Intended:** Claude separates statistical from practical significance — a +0.05pp lift with a tiny p-value still fails a 2pp ship bar. The pre-registered effect-size threshold is exactly what saves the user from significance-by-scale; Claude reports effect size first, p-value second.

**Behind the curtain / Today.** The brief's MDE is the mechanism; works *if* the elicitor captured an MDE (it asks — see J2.1). This is the clearest reason the MDE question is load-bearing.

### J2.5.6 — No clean assignment column

**User says:** data with no obvious control/treatment split, or a "before/after" timestamp.

**Intended:** Claude can't infer randomization, so it asks which column is the assignment. If there genuinely is none — a pre/post comparison — it **declines**: that's a quasi-experiment, not a randomized A/B, and out of scope for v0.1.

**Interaction rule.** *Ask one question* (which column); if none, *decline cleanly* and name why.

**Behind the curtain / Today (gap, verify).** The clean decline is the correct behavior; whether the elicitor actually catches "this is pre/post, not an A/B" rather than proceeding as if it were one is a prompt-quality question. → **G11.**

### J2.5.7 — "I already looked at the results"

**User says:** "I peeked yesterday, it looked good — can you confirm?"

**Intended:** Claude flags the peeking problem honestly — fixed-horizon stats assume you didn't look; repeated peeks inflate false positives. It can still run the analysis, but must caveat that the pre-registration guarantee is weakened, and note that always-valid/sequential methods exist but aren't wired into the guided flow here.

**Interaction rule.** *Hold the discipline + explain* (this is also an axis-B "why" moment).

**Behind the curtain / Today (gap).** Sequential / always-valid tests (`msprt_test`, `always_valid_ci`) exist in the library but are **not** wired to the workflow — so the guided flow is fixed-horizon only and can caveat peeking, not correct for it. → **G13.**

---

# Part 3 — Mid-flight, in the user's words

Things go sideways. The agentic test is whether the user can keep talking in plain English and get unstuck.

### J3.1 — "Wait, why did it stop?" (SRM halt)

Covered in J1.3's demo, but in a real run: the user sees a halt mid-conversation and asks "why'd it stop?" Claude re-explains the SRM in one paragraph, states that it will not produce a verdict from this data, and offers the override-with-reason as the only way forward — framed as "you're overriding a safety check," never as "ship anyway."

**Interaction rule.** Halt → explain → *offer a menu only of legitimate next actions*: (1) fix upstream and rerun, (2) override with a recorded reason code, (3) abandon. Overriding requires the user to pick a reason from a closed set; Claude does not write the reason for them.

**Behind the curtain.** `monitor` agent + SRM stats + `gate.blocked` / `gate.resolved` events. **Today (defect):** the SRM halt and override are built, but the **audit-chain validator can't actually verify gate pairing** — invariants 4 and 5 read a `stage` field that gate events don't carry, so they silently never fire. The override is recorded, but the integrity checker that's supposed to prove "every gate that opened was resolved" is currently a no-op. Fix before this journey's audit guarantee is real.

---

### J3.2 — "That's not what I meant" (ambiguous / contradictory brief)

**What the user says** mid-design: "No — I care about *revenue*, not completion." / Claude's consistency check finds the stated guardrail contradicts the primary.

**The conversation:**

```
Claude: Before I lock this — your primary is "maximize completion" but your
guardrail is "don't increase orders below $20." Those can pull against each
other: a completion win often comes from more small orders. Three ways to
resolve:

  1  keep both, accept the tension (I'll flag it in the readout)
  2  change the guardrail to AOV instead of order-count
  3  re-state the primary

Which?
```

**Interaction rule.** *Offer a menu* — a genuine contradiction with no safe default is exactly the menu case. Claude names the tension concretely (not "these seem inconsistent") and gives closed options.

**Behind the curtain.** `consistency_judge` agent → `brief_contradiction` gate. **Today:** built; the resolve flow is real. The verdict-enum split (J2.1) is downstream of this and still applies.

---

### J3.3 — "Pick it back up" (resume after interruption)

**What the user says:** "We got cut off — where were we on the checkout test?" / "Resume exp_001." / closes laptop mid-run, comes back tomorrow.

**The conversation:**

```
You: where were we on the checkout experiment?

Claude: exp_001 stopped after the analysis committed but before the readout —
looks like the session was interrupted, not a halt. The state and audit log
are intact. I can render the readout now from what's already computed; nothing
needs re-running. Go ahead?
```

**Interaction rule.** *Infer & proceed* to detect the recovery case and state it plainly, then *ask one question* (resume vs. inspect). The user should never have to know which of the recovery cases they're in — Claude diagnoses it.

**Boundaries.** Resume reads the on-disk state and audit log as the source of truth; it never silently re-runs a committed stage or overwrites a result.

**Behind the curtain.** `agentxp resume <exp_id>` detects the recovery case from `state.yaml` + `log.jsonl`. **Today:** the resume detector is built; conversational framing is the `/experiment` skill. Same end-to-end caveat as J2.1 — not yet demonstrated against a real interrupted run.

---

### J3.4 — "The warehouse login expired"

If a registered warehouse credential expires mid-flow (a v0.1.1 path, since reads aren't wired yet), the intended behavior is: Claude detects the auth failure, says so without leaking any secret, and offers to re-collect the credential — it does not crash with a raw driver exception. **Today:** this is a v0.1.1 journey; the re-auth dialog is specified but unreachable until warehouse reads land. Annotated here so it isn't forgotten.

---

# Part 3.5 — Off the rails

This is the real test of whether AgentXP is *agentic* or just a chatbot wrapped around a stats library. The user doesn't follow the script — they change their mind, push back, try to bend the rules, or ask "why." An agentic system is defined by how it holds (or fails to hold) under that pressure. Grouped by the interaction rule each one tests.

## Refuse — the integrity wall

### J3.5.1 — "Loosen the guardrail so it passes"

**User says** (after a no-ship): "Can you bump the AOV guardrail to 5% so this ships?"

```
Claude: I won't rewrite the rule after seeing the result — that's the exact
move this system exists to prevent. You set "AOV can't drop more than 2%"
before we looked at anything; changing it to 5% now, because the result
landed at 3.7%, turns the rule into a story that fits the data.

What I *can* do: record that you're overriding the no-ship with a written
reason. That goes in the audit log with your name on it, and your director
sees both the original rule and your override. Want to do that instead?
```

**Interaction rule.** *Refuse* the rewrite. *Offer* the recorded-override as the legitimate way to disagree.

**Boundaries.** The pre-registered brief is immutable after results. An override is explicit, logged, and attributed — never a silent edit.

**Behind the curtain / Today (top-priority gap).** This is the single most important integrity behavior in the product — **and it is currently unenforced in code.** Claude is the orchestrator; nothing in the build stops a sufficiently insistent user from getting Claude to rewrite `brief.yaml`. Whether it refuses depends entirely on the instructions in `SKILL.md` and the editor agent prompt. → **G9.**

### J3.5.2 — "Just make it ship, I need it for my review"

**User says:** "I need a ship verdict for my review tomorrow. Make it work."

```
Claude: I can't change what the data says — but I can give you the strongest
*honest* version. The completion win is real (+2.3pp, CI clear of zero). The
block is the AOV drop against the rule you set. Here's how I'd present that
to your reviewer: lead with the real lift, name the guardrail breach plainly,
and bring the iterate-at-$75 recommendation. That's a defensible story.
A fabricated ship verdict isn't — and it's in the audit log forever.
```

**Interaction rule.** *Refuse* the fabrication; *redirect* the pressure into honest-framing help.

**Behind the curtain / Today.** Same root as J3.5.1 — relies on prompt discipline, not enforcement. → **G9.**

### J3.5.3 — "Skip the brief, just give me the p-value"

**User says:** "I don't need all this brief stuff — run a t-test and tell me if it's significant."

```
Claude: Sure — [runs it] completion p = 0.003, AOV p = 0.001.

One thing so you're not surprised later: without a decision rule fixed up
front, that's a p-value, not a ship decision, and there's no audit trail
tying it to a hypothesis. Totally fine if you just want the number. Want to
stop here, or wrap the disciplined version around it (takes two questions)?
```

**Interaction rule.** *Honor* the escape hatch — don't gatekeep — but *name what's lost*. This is Lin's library path (J5.3) surfaced inside the conversation.

**Behind the curtain / Today.** The stats are callable; Claude can run a bare test. **Works** as an escape hatch; the "here's what you give up" framing is prompt-dependent.

## Re-confirm / re-enter — the user changes their mind

### J3.5.4 — "Scrap that, I care about retention now" (pre-lock)

**User says** mid-design: "Actually forget completion — what I really care about is 7-day retention."

```
Claude: Switching the primary to 7-day retention. Quick check first —
your data ends 2026-05-26 and the test started 2026-05-19, so the latest
cohorts only have ~5 days of follow-up, not 7. I can use a 5-day retention
window, or restrict to cohorts with a full 7. Which?
```

**Interaction rule.** *Re-enter* the elicitation cleanly; *validate* the new metric against the data before re-locking.

**Behind the curtain / Today.** Re-entry before the brief is locked is supported (nothing is committed yet). The data-validity check is profiler/elicitor judgment. **Works.**

### J3.5.5 — Changes the metric *after* the brief is locked

**User says** post-lock: "Wait, can we make it retention instead?"

```
Claude: The brief's locked, so I can't quietly swap the primary — that's the
same problem as changing a rule after seeing data. This becomes a new
experiment (exp_002), sharing the same dataset. I'll carry over what still
applies and re-elicit the retention specifics. Start it?
```

**Interaction rule.** *Distinguish* pre-lock (free re-entry, J3.5.4) from post-lock (new experiment / logged amendment). *Refuse* the silent edit.

**Behind the curtain / Today (gap).** The "free edit vs. needs-a-new-experiment" boundary is exactly what the `amendments/` package was built to handle — and it's **dead code** (G8). So today there's no amendment-log affordance; the only honest path is "start a new experiment." → **G14.**

## Hold the discipline + explain — the "why" interrogations (axis B)

### J3.5.6 — "Why no-ship? completion went up."

```
Claude: Completion did go up, and that part's real and worth keeping. But you
set a rule before we looked: AOV can't drop more than 2%. It dropped 3.7%.
The verdict follows the rule you wrote, not the completion number on its own.
If you think a 3.7% AOV drop is actually acceptable, that's a legitimate call
— but it's you overriding your own rule, and I'll log it as exactly that, so
the next person sees the rule, the breach, and your decision to ship anyway.
```

**Interaction rule.** *Explain* the rule's authority; *offer* the override as the honest way to disagree.

**Behind the curtain / Today.** The interpreter is bound to the rule by design. Verify the interpreter prose actually *explains* rather than merely asserting. → **G10.**

### J3.5.7 — "Why do I have to set the threshold before I see the data?"

This is *the* question — the whole product thesis.

```
Claude: Because if you set it after, you'll set it wherever the result landed
— everyone does, it's not dishonesty, it's how brains work. A +1.3pp result
makes "1pp" feel like the obvious bar. A +0.4pp result makes 0.4pp feel
"directionally promising." Fixing the number first is the one thing that stops
the result from quietly rewriting the question you were asking. It's the
difference between a finding and a story you told yourself afterward.
```

**Interaction rule.** *Hold + teach.* This is the moment that proves the system understands its own purpose, not just its rules.

**Behind the curtain / Today (gap).** Pure pedagogy — and whether Claude can deliver it depends on the agent prompts carrying the *why*, not just the *rule*. Worth auditing directly. → **G10.**

### J3.5.8 — "Why halt instead of just flagging the SRM?"

```
Claude: Because a flag invites you to look past it — and once you've seen a
2.3pp lift, you won't want to. The halt keeps the result from existing before
the randomization is trusted: you can't be tempted by a number you haven't
seen. You can still override, but you have to do it *before* the lift is on
screen, and on the record. A flag would let you see the prize first and
rationalize second.
```

**Interaction rule.** *Hold + teach* — pre-registration logic applied to SRM.

**Behind the curtain / Today.** The halt-before-results ordering is real in the monitor stage. Verify the prompt carries this reasoning. → **G10.**

### J3.5.9 — "How do I know your numbers are right? What's the catch?"

```
Claude: Don't trust me — replay me. Every number traces to a logged query and
a deterministic Python function; run `agentxp audit exp_001` and you'll see
the exact computation, not my summary of it. And the stats engine is the same
library your data team can call from a notebook and check against statsmodels.

The real catch, honestly: I can verify the *counts* are balanced, but I can't
verify your assignment system was truly random upstream of this data. If the
randomization was broken before the data reached me, the SRM check is your
only signal — and it passed here.
```

**Interaction rule.** *Redirect* trust from authority to replayability; *name* the real limitation.

**Behind the curtain / Today.** Audit replay is built; "check against statsmodels" is Lin's actual path (J5.3). A strong, honest answer.

## Decline cleanly — out of scope

### J3.5.10 — "Run a causal analysis on this observational log"

**User says:** "I don't have a randomized test, but can you tell me if the feature *caused* the lift from this usage data?"

```
Claude: That's causal inference on observational data — you'd be controlling
for confounders, not comparing randomized arms. AgentXP only does randomized
A/B in this version. If I ran it as an A/B anyway, I'd hand you a number that
*looks* like a treatment effect but isn't, and you'd make a decision on it.
That's a different tool and a separate project. I'd rather tell you that than
give you a confident wrong answer.
```

**Interaction rule.** *Decline*; name the boundary; do **not** hallucinate a method.

**Behind the curtain / Today (gap, verify).** The clean decline is correct; whether the elicitor catches this vs. proceeding as if it were an A/B is prompt-quality. A faked causal analysis would be a serious correctness failure. → **G11.**

### J3.5.11 — Vague or junk input

**User says:** "idk just do whatever's normal." / pastes a screenshot of a table. / a malformed CSV.

**Intended:** For vagueness, Claude asks the *one* question that unblocks ("what are you trying to decide?") rather than guessing a whole experiment. For junk data, it reports what it could and couldn't read instead of fabricating a profile. A screenshot isn't a data source — Claude says so and asks for a file.

**Interaction rule.** *Degrade gracefully* — one clarifying question for vagueness; honest partial-read for junk; decline the screenshot.

**Behind the curtain / Today.** The profiler reports read failures honestly. Screenshot→data (OCR) is out of scope. **Works** as a decline.

---

# Part 4 — After the fact

The experiment is done. Now the audit trail earns its keep.

### J4.1 — "Why did exp_007 halt at stage 5?"

**What the user says:** "Why did exp_007 stop?" / "Walk me through what happened on the checkout test." / "What was the decision trail?"

**The conversation:**

```
You: why did exp_007 halt?

Claude: It halted at the randomization check. Here's the trail:

  brief locked       2026-05-28 09:14   ship-rule: +2pp, CI excludes 0
  SRM check          2026-05-28 09:17   HALT — 5,600/4,400, p<0.001
  (no analysis ran — the halt stopped it before any results)

The split was too far from 50/50 to trust. No verdict was produced, by
design. Want the full event-by-event log, or an HTML report to share?
```

**Interaction rule.** *Infer & proceed* — answer the natural-language question directly, in narrative, then offer the formal artifact. "Why did exp_007 halt?" and `agentxp audit exp_007` should produce the same answer; the plain-English version is primary.

**Behind the curtain.** `agentxp audit <exp_id>` (text / `--diff` / `--html` / `--json`). **Today:** the audit CLI is built and is a strong surface. **Caveat:** the chain *validator* has the invariant-4/5 gap (J3.1) — the replay narrative is accurate, but the formal "chain is internally consistent" guarantee is currently weaker than advertised until that's fixed.

---

### J4.2 — "Show me everything I've run" / "compare two runs"

**What the user says:** "What experiments are in here?" / "List my runs." / "How did exp_007 differ from exp_004?"

**The conversation:**

```
You: list my runs, and what changed between the last two?

Claude:
  exp_004  REPORTED  free_shipping_banner    2026-05-26  NO-SHIP-GUARDRAIL
  exp_007  HALTED    free_shipping_v2        2026-05-28  (SRM)

Between them: same primary and guardrail, but exp_007 added a $75 order
threshold to the banner copy and pulled a fresh week of data — which is the
run that tripped the SRM. Want the side-by-side audit diff?
```

**Interaction rule.** *Infer & proceed* on the list; *infer & proceed* on the diff since the user asked for both. The diff is narrated ("what changed and why it matters"), with the formal `--diff` artifact offered.

**Behind the curtain.** `agentxp list` + `agentxp audit <a> --diff <b>`. **Today:** built.

---

### J4.3 — "That doesn't look right"

**User says:** "The AOV number seems off — our average order is like $90, not $65."

```
Claude: Good catch to question it. The $64.91 is AOV *among completers in this
cohort*, not your store-wide average — and it's computed on orders inside the
test window only. Two things could explain the gap from $90: (1) your $90 is
all-orders including non-test traffic, or (2) a currency/units mismatch. Let
me show the computation: [traces the query + the filter]. Which $90 are you
comparing to — store-wide all-time, or this segment?
```

**Interaction rule.** *Investigate* the doubt — re-check the computation path, show the work, reconcile (conditional vs. unconditional is a real, common gap). Don't get defensive; don't just re-assert the number.

**Behind the curtain / Today.** The analysis is traceable via the audit/computation trace, and conditional-vs-unconditional is already a documented case in the happy-path readout. **Works** if Claude digs rather than re-asserts.

### J4.4 — "Just give me the raw numbers, skip the narrative"

**User says:** "I don't need the paragraph — just the table and the CIs."

**Interaction rule.** *Honor* the format request. The stakeholder paragraph is a default, not a requirement.

**Behind the curtain / Today.** The report ships in both structured (JSON sidecar) and narrative (markdown) forms; the JSON is exactly this. **Works.**

### J4.5 — "I can't find my experiment" / something crashed

**User says:** "I had a run going yesterday — it's gone." / a mid-run crash.

**Intended:** Claude lists what's actually on disk (`agentxp list`); if a run is half-committed, the resume detector (J3.3) diagnoses the recovery case and states the safe next step. If nothing was written, Claude says so plainly rather than inventing a lost run.

**Interaction rule.** *Inspect disk truthfully*; resume if recoverable; honest "nothing here" if not.

**Behind the curtain / Today.** `list` + `resume` are built and the crash-recovery cases are specified; same not-yet-demonstrated caveat as G1.

---

# Part 5 — Other ways I connect it to things

Three integrations are in scope. Each is a place AgentXP stops being a closed conversation and becomes a piece of someone's larger workflow.

### J5.1 — Warehouse data sources (Mira's lens)

Mira's cohort lives in Snowflake. The *intended* journey: "Connect our Snowflake and pull `analytics.prod.checkout_events` for the test." The *current* journey: registration works, reads don't (J1.2). Mira's real workaround today is to query Snowflake with her own connector, land two pandas frames, and either (a) feed the stats library directly (J5.3) or (b) export to parquet and point the conversation at the file (J1.1).

**Interaction rule.** When the user names a warehouse, Claude offers registration, states the read boundary, and offers the export-to-file path — it never pretends to read. **Today (gap, by design):** warehouse reads ship in v0.1.1; the adapters are code-complete but live-unverified. The honest fallback (export → local file) keeps Mira unblocked.

### J5.2 — Export readouts outward (Maya's lens)

Maya's deliverable doesn't live in the repo — it lives in Slack, Linear, and a finance thread. The journey: verdict → copy the paste-ready stakeholder paragraph into Slack → generate a self-contained HTML audit report (`agentxp audit exp_001 --html`) → drop it in the Linear ticket → forward to finance. The HTML is single-file, no external assets, with every user-controlled string HTML-escaped.

**Interaction rule.** After a verdict, Claude proactively offers the two export shapes Maya actually uses — the Slack paragraph (already in the readout) and the shareable HTML — without being asked. **Today:** the markdown/JSON readout and the HTML audit export are built. The "paste-ready paragraph" is part of the readout contract. This is a strong, working integration surface.

### J5.3 — Stats library in a notebook (Lin's lens)

Lin never opens the conversation. She does `from agentxp.stats.ab_tests import welch_test, proportion_test` in Jupyter, runs her own analysis, and calls `render_report(...)` to get a readout that matches every other readout her org ships. She also runs `srm_check` as a cheap kill-switch and occasionally `validate_chain(exp_dir)` to sanity-check someone else's experiment.

**Interaction rule.** None — this is the *no-conversation* path, and it must stay first-class. The library has to behave like a well-typed library, not like the inside of an agent. **Today (works, with rough edges):** every `agentxp.stats.*` function returns a deterministic dict with an `interpretation` string; `render_report` takes a hand-built `Report` view model; `validate_chain` runs read-only. Known friction Lin will hit: no `Report.from_dataframes(...)` helper (she hand-builds the view model), the renderer requires a verdict (no "inconclusive, no label" mode), and the per-result dicts aren't exported as typed dataclasses. None of these block her; all are v0.2 ergonomics. **Honesty note for scope:** several stats modules Lin *could* import (`bayesian`, `sequential`, `cuped`, `power`) are correct and tested but are not used by the conversational workflow — they're library surface for power users like Lin, not part of Maya's path.

---

# Part 6 — The three lenses, side by side

The same system, entered three ways. This is the compatibility matrix the design has to honor.

| | **Maya (PM)** | **Mira (Engineer)** | **Lin (Data scientist)** |
|---|---|---|---|
| **Enters via** | Conversation only | Conversation + notebook + warehouse | Notebook only |
| **Wants** | A defensible verdict to paste | Stats engine + audit trail, reproducible | Vetted tests + consistent renderer |
| **Touches stages?** | Never sees them | Selectively (audit, resume) | Never |
| **Data source** | Local file | Snowflake (own connector today) | In-memory pandas |
| **Key integration** | Export readout outward (J5.2) | Warehouse (J5.1, gated) | Library (J5.3) |
| **Biggest current gap for them** | Verdict-enum split breaks Stage 7→8 | Warehouse reads not wired; no headless Python orchestrator | No `from_dataframes` helper; dicts not typed |

**What all three share, and what must not break:**
- The stats are deterministic and the same numbers come out regardless of entry path.
- The audit log is the credibility claim — and it's only as good as the chain validator, which currently has a no-op gap (J3.1, J4.1).
- Nobody should have to know a stage number, a flag, or a file path to get the value — except where they *choose* to drop to the library (Lin) or the warehouse (Mira).

---

### Part 6 extension — More entry attitudes

Not new mechanics — new *attitudes* the same system has to absorb.

- **The first-timer** ("I've never run an A/B test — what do I do?"). Claude teaches as it goes: defines each term in one clause the first time it appears, defaults aggressively, asks fewer questions. The MDE question becomes "how big a change would actually matter to you?" instead of jargon. **Today:** depends entirely on whether the elicitor prompt can drop register and teach — verify it can.
- **The skeptic** ("I don't trust AI to do my stats"). Claude agrees with the instinct and redirects to verifiability (J3.5.9): the AI does *judgment* (framing, interpretation), deterministic Python does the *math*, and both replay. The skeptic's correct move is to check the library against statsmodels — which is Lin's path. **Today:** the judgment-vs-math split is real and is the honest answer.
- **The auditor / compliance reviewer** (non-technical, verifying after the fact). Runs nothing — reads `agentxp audit <id> --html` and checks a fixed list: was the rule pre-registered? was SRM honored? was any guardrail bypassed, by whom, and why? **Today (gap):** this persona depends entirely on the chain validator working — and invariants 4/5 (gate pairing: "was every halt resolved, and by whom") currently never fire (G3). The auditor is the persona most directly harmed by that defect.
- **The forker** (wants a custom agent — e.g., a regulatory check at brief sign-off). **Today (gap):** no documented extension point; `CANONICAL_AGENT_NAMES` is a hardcoded set, there's no `register_agent` API, no `docs/extending.md`. A v0.2 ask.

---

# Appendix — The honest gap register (as of 2026-05-29)

Pulled from the journeys above, in one place, so the follow-up plan has a single source. These are the points where the *intended* agentic system and the *current* build diverge.

| # | Gap | Surfaces in | Disposition |
|---|---|---|---|
| G1 | **No experiment has been run end-to-end.** No `experiments/` dir exists; Stage 0→8 is built piecewise but never demonstrated. | J1.3, J2.1, J3.3 | **Verify first** — Stage 0→8 smoke run on a fixture. |
| G2 | **Verdict vocabulary is split** between `interpret/tree.py` and `schemas/report.py` — incompatible sets at the Stage 7→8 handoff. | J2.1, J2.2, J3.2 | **Fix** — reconcile to one closed set. Needs a call on which set is canonical. |
| G3 | **Audit-chain invariants 4 & 5 never fire** — they read a `stage` field gate events don't carry. The "every gate resolved" guarantee is currently a no-op. | J3.1, J4.1 | **Fix or remove** — a checker that can't fire is worse than none. |
| G4 | **Invariant 3(b) hashes `decisions/*.yaml` that are never written** (the decisions writer is dead code). Vacuously passes. | J4.1 | **Fix or remove** alongside G3; delete the dead writer. |
| G5 | **Warehouse reads not wired** — `connect` registers credentials, but `profile --adapter <wh>` returns "ships in v0.1.1." Adapters code-complete, live-unverified. | J1.2, J3.4, J5.1 | **By design (v0.1.1).** Conversational layer must surface the export workaround, not fail. |
| G6 | **No headless Python orchestrator** — `_invoke_llm` / `advance()` / `dispatch_sql` are stubs; the interactive Claude-as-orchestrator path is the only live one. | J5.3 (Mira's "make it reproducible") | **By design (Phase 5 excluded).** Document the boundary; don't pretend a `.py` can drive the 11 stages. |
| G7 | **Library ergonomics** — no `Report.from_dataframes`, renderer requires a verdict, stats return dicts not typed models. | J5.3 | **v0.2 polish.** Non-blocking for Lin. |
| G8 | **Dead/parallel code** — `amendments/`, `_versioning`, `sql/cache`, `sql/preview`, the orphaned `agents/experiment-*.md` prompt set, the second Snowflake loader. | (not a journey; surfaces as false "this is wired" signals) | **Delete** — pure subtraction, shrinks the readable surface. |
| G9 | **The integrity refusals are unenforced** — nothing in code stops the orchestrator from rewriting a locked brief, loosening a guardrail post-hoc, or manufacturing a ship verdict under user pressure. It rests entirely on agent-prompt discipline. | J3.5.1, J3.5.2, J3.5.5 | **Verify + harden** — audit `SKILL.md` and the editor prompt; this is the product's core claim. **Highest priority among the new findings.** |
| G10 | **Unclear whether the prompts *teach* the discipline or merely *assert* it** — the "why pre-register / why halt" answers are the product thesis; if the prompts only state the rule, Claude can't defend it when pushed. | J3.5.6–J3.5.8, J2.5.7, first-timer | **Audit the prompts** for the *why*, not just the rule. |
| G11 | **Out-of-scope decline may not be clean** — whether the elicitor catches "this is observational / pre-post, not a randomized A/B" and declines, vs. proceeding as if it were an A/B, is unverified. | J2.5.6, J3.5.10 | **Verify** the decline; a faked causal analysis would be a serious correctness failure. |
| G12 | **3+ variants likely unsupported in the guided flow** — SRM generalizes to k arms, but the brief/analyzer/interpreter and two-sample tests assume a control-vs-treatment binary. | J2.5.1 | **Verify**; if unsupported, say so (multi-arm is library-only via pairwise calls). |
| G13 | **Peeking can't be corrected, only caveated** — always-valid/sequential methods exist in the library but aren't wired into the guided flow, which is fixed-horizon only. | J2.5.7 | **By design (v0.1)** — document the caveat. Ties to the speculative-stats note in the over-engineering review. |
| G14 | **No amendment mechanism** — the post-lock "change the primary" path has no logged-amendment affordance; the `amendments/` package built for it is dead code. Today's only honest answer is "start a new experiment." | J3.5.5 | **Decide**: revive a minimal amendment log, or make "new experiment" the official path and delete `amendments/` (ties to G8). |

**Reading of the register.** Two tiers now.

*Build-state gaps (G1–G8)* — the periphery-before-spine findings: G1–G4 are the integrity spine of Maya's journey and the first thing to make real; G5–G6 are honest, deliberate v0.1 boundaries the conversation must narrate truthfully; G7 is polish; G8 is cleanup that makes everything else easier to see.

*Behavioral gaps (G9–G14), surfaced by the off-the-rails journeys* — these are the more interesting set, because they're about whether the system **holds its judgment under pressure**, not whether a function is wired. **G9 is the headline:** the product's entire credibility claim ("the verdict can't be reverse-engineered to fit the result") currently rests on prompt discipline, with no code enforcement — and the off-script journeys (J3.5.1, J3.5.2, J3.5.5) are precisely the user behaviors that would test it. G10–G11 are adjacent: can the system *explain* its discipline and *decline* cleanly, or does it only recite rules and risk faking out-of-scope work? These can't be closed by deleting code or wiring a stub — they need a prompt audit and probably some hard guardrails in `SKILL.md`.

This document defines *what good looks like* from the user's seat. The follow-up implementation plan sequences the build-state gaps; the behavioral gaps (especially G9) deserve their own line item, because an agentic system that can be argued out of its own integrity rule isn't the thing we set out to build.
