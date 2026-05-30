# Module 0 — Thesis & market

> **Goal:** State, in one sentence, what AgentXP is *for* and why it has a right
> to exist — and defend that sentence against the three objections a skeptic
> will throw at you on launch day. Plus get oriented in the repo so the later
> modules have a map.

---

## Why (the design reasoning)

### The problem AgentXP exists to solve

Most product teams run A/B tests badly, and not for lack of tools. They run them
badly because **the human reading the result is the same human who wanted a
particular result.** You ship a feature you believe in, you watch the dashboard,
and the moment a number looks good you start building the story for why it's
good. You move the threshold to where the result landed. You peek early and stop
when it's winning. You explain away the guardrail that broke. None of this is
dishonesty — it's how brains work when a number you care about is on the screen.

The existing platforms — Eppo, StatSig, GrowthBook — compute the statistics
correctly. That was never the hard part. They hand you a clean lift and a clean
CI and then **leave the judgment entirely to you**, at exactly the moment your
judgment is most compromised. They're calculators. A calculator can't stop you
from asking it the wrong question, or from re-asking until you get the answer
you wanted.

### The thesis (memorize this sentence)

> **Deterministic Python owns the statistics; an LLM owns the judgment; and the
> judgment is structurally sealed off from the result so the verdict cannot be
> reverse-engineered to fit what you hoped to find.**

Everything in the codebase is downstream of that one sentence. When you wonder
"why is it built this way?", the answer is almost always "so the verdict stays
honest." Three concrete expressions of the thesis, each a whole subsystem you'll
study later:

1. **Pre-registration is enforced, not suggested.** You write the decision rule —
   the metric, the direction, the MDE, the guardrails — *before* you see the
   data, and it gets locked. (Module 4: the integrity wall.)
2. **The interpreter is blind.** The agent that renders the verdict never sees
   your hypothesis prose, never sees what you said you wanted, never sees the
   conversation. It gets the locked rule and the numbers, walks a fixed decision
   tree, and emits a label. It *cannot* motivated-reason because the motivation
   isn't in its context. (Module 2 + 3.)
3. **Every number is replayable.** A tamper-evident audit chain links every event
   to its parent by hash; anyone can `agentxp audit <exp_id>` and re-derive the
   verdict from logged queries and deterministic functions. The claim isn't
   "trust me" — it's "replay me." (Module 4.)

### Why now, and why in Claude Code

Two things make this buildable in 2026 that weren't before. First, LLMs got good
enough to hold a genuine analytical conversation — to elicit a hypothesis from
messy prose, to explain *why* a guardrail blocks a ship, to decline a request
that isn't actually an experiment. Second, **Claude Code is a runtime**: a place
where an agent can read files, run Python, execute SQL, and converse, all in one
loop. AgentXP isn't a SaaS dashboard you log into; it's a skill that runs where
the builder already works. That's the wedge — "experimentation that runs in your
terminal, owned by you, open-source" — against incumbents that are hosted,
priced per-seat, and own your data.

### What it is NOT (scope honesty)

You will be asked this, so be clear: AgentXP v0.1 does **randomized A/B
experiments only**. It is not a causal-inference toolkit (no diff-in-diff, no
matching, no synthetic control — those decline cleanly, which is itself a
feature; Module 2). It does not run a long-lived headless loop yet (Phase 5;
Module 6). Three warehouse adapters ship code-complete but unverified against
live credentials (Module 5). Knowing these boundaries cold is part of defending
the system: a reviewer trusts the claims you make more when you're the one naming
what the tool doesn't do.

---

## Walkthrough (get oriented)

Spend 15 minutes with the map before any code:

```bash
$ cd ~/projects/agentxp
$ ls                       # top-level: agentxp/ (code), agents/ (prompts),
                           #   tests/, docs/, sample-data/, .claude/skills/
$ ls agentxp/              # the Python: stats/ interpret/ audit/ sql/
                           #   orchestrator/ storage/ schemas/ cli/ amendments/
$ ls agents/               # the LLM prompts: profiler, analyzer, monitor,
                           #   interpreter, readout, designer/*, ...
```

The single most important structural fact: **the `agentxp/` Python directory and
the `agents/` prompt directory are two different kinds of program.** Python is
deterministic and owns anything a wrong answer would corrupt (stats, the chain,
SQL safety). The markdown prompts are the judgment layer. The line between them
*is* the thesis. Hold that distinction and the architecture stops looking
arbitrary.

Then read these three, in this order — they hold the "why" you just learned:

1. `docs/USER_JOURNEYS.md` — skim the intro and the §"Hold the discipline" block
   (J3.5.6–J3.5.9). This is the product's soul in script form.
2. `SYSTEM_AUDIT.md` — read §11 (the gap register). This is the honest list of
   what was wrong before release.
3. `OVER_ENGINEERING_REVIEW.md` — skim it. This is the discipline of *not*
   building, which is rarer and more telling than what got built.

---

## Lab 0 (orienting hands-on)

```bash
$ source .venv/bin/activate
$ agentxp --version                   # agentxp 0.1.0
$ .venv/bin/python -m pytest -q       # ~1240 passed, ~63 skipped
$ agentxp list                        # experiments you've run (likely empty)
$ ls sample-data/                     # your 8 practice fixtures
```

Then, just to feel the shape (we go deep in Module 1): open Claude Code in the
repo and run `/experiment --data sample-data/clean_ab.csv`. Don't worry about
mastering it — watch how it *talks*. Notice it reads your intent back as
structured fields and commits one default at a time with a reason. That
conversational elicitation is the LLM-judgment layer doing its job.

---

## Teach-back checkpoint

You pass Module 0 when you can do this without notes:

1. **State the thesis in one sentence** and name the three subsystems that
   express it.
2. **Survive the skeptic drill** — answer these three the way you'd answer them
   on launch day:
   - *"This is just a wrapper around statsmodels with a chatbot on top. Why
     would I use it over Eppo, which is battle-tested and hosted?"*
   - *"If an LLM is making the call, how is that more trustworthy than me making
     the call? You've just added a black box."*
   - *"Pre-registration and audit logs are process theater. Disciplined teams
     already do this; undisciplined teams will just override everything. What
     does the tool actually change?"*
3. **Name three things AgentXP deliberately does NOT do**, and why each
   non-feature is a strength.

Write your answers, or say them to me and I'll play the skeptic and push back
where a real reviewer would. When your three answers hold under pressure, check
the box in the README and we move to Module 1.
