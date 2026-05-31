# Module 2 — Agents as programs

> **Goal:** Understand the judgment layer as *software*. The markdown prompts in
> `agents/` are not documentation and not vibes — they are programs with inputs,
> outputs, refusal conditions, and a deliberately restricted field of view. By
> the end you can explain why the interpreter never sees your hypothesis, trace
> exactly which inputs each agent is allowed, and read a `*.system.md` file the
> way you'd read a function signature.

---

## Why (the design reasoning)

Module 0 drew the line: `agentxp/` (Python) owns anything a wrong answer would
corrupt; `agents/` (markdown) owns judgment. This module is about the second half
of that sentence, and the single idea that makes it trustworthy.

### The isolation axiom

> **A judgment agent is denied every input that would let it reverse-engineer the
> answer it's supposed to reach independently.**

This is the load-bearing design choice of the whole system, and it sounds
backwards until you see it. Normally you'd give a model *more* context to make it
smarter. Here we deliberately give the judgment agents *less*, because the failure
mode we're defending against isn't ignorance — it's motivated reasoning. An agent
that can see "the human hoped this would ship" and also "here's the borderline
result" will, like a human, find a path to ship. So we cut the wire. The
interpreter that renders the verdict **never sees the hypothesis prose, never sees
what you said you wanted, never sees the conversation.** It gets the locked rule
and the numbers, walks a fixed tree (Module 3), and emits a label. It *cannot*
motivated-reason because the motivation is not in its context.

> **Aha — you make the judge more trustworthy by giving it *less* context, not
> more.** Every instinct says a better decision needs more information. The
> isolation axiom inverts that: the interpreter is reliable *because* it can't see
> what you hoped for. Withheld context is the feature.

You can read this axiom directly in the prompts — it's stated, not implied:

- **`monitor.system.md`** — the monitor runs the sample-ratio-mismatch (SRM) check
  against the design and is scoped to exactly that; it does not get the narrative of
  why the feature matters. (Guardrails are *measured* by the analyzer at Stage 6 and
  *enforced* by the tree at Stage 7 — see Module 1.)
- **`interpreter.system.md` §2 / §9** — explicitly: *"you do not have access to
  state.yaml"*. The interpreter is handed the analyzer's numbers and the locked
  decision rule, nothing else. No hypothesis, no hopes, no history.
- **`readout.system.md` §6** — a readout that argues the verdict should have been
  different is *"wrong by construction"*: by the time the readout runs, the
  verdict is decided and the readout's only job is to explain it honestly.
- **`consistency_judge` §2** — same shape: judges consistency on a restricted
  view so it can't be swayed by the thing it's supposed to check independently.

The discipline is uniform: **the agent that makes a call is structurally prevented
from seeing the thing that would bias the call.**

### Agents as programs, concretely

Every `*.system.md` file has the same anatomy, and once you see it you'll read
them fast:

- **A role + scope statement** — what this agent decides, and (just as important)
  what it explicitly does NOT do. Most files have a literal "you do NOT do …"
  section. That's the agent's refusal contract.
- **A banned-vocabulary core** — a shared ~12-token list of words the agent may
  not use (hype/salesy/overclaiming language), so the output voice stays flat and
  honest. This is enforced by a voice audit step.
- **One-shot examples (A / B / C)** — concrete input→output pairs that pin the
  format and the tone. These are the agent's "type signature" made executable.
- **Inputs, delivered as a bundle** — never the raw conversation, but a curated,
  hashed snapshot (next section).

Think of each agent as a pure-ish function: `bundle in → artifact out`, with a
declared refusal set. The Python around it makes the inputs deterministic and the
output auditable.

---

## Walkthrough (the agent roster + how inputs get to them)

### The roster

Open `agents/` and map each file to its stage from Module 1:

```bash
$ ls agents/
$ ls agents/designer/
```

| Agent | Stage | Decides | Notably blind to |
|-------|-------|---------|------------------|
| `profiler` | 0 | column types, candidate metrics, "is this an experiment?" | — (it's the eyes) |
| `semantic_modeler` | 0.5 | drafts the semantic model (entities, dimensions) | — |
| `metric_drafter` | 0.75 | drafts the metric catalog (primary / guardrail / control) | — |
| `designer/elicitor` | 1–2 | pulls intent out of the dialogue, then drafts the hypothesis | — |
| `designer/drafter` | 3–4 | writes the brief (`experiment.yaml`) and the data plan | — |
| `designer/editor` | 3b + edits | applies *scoped* edits; refuses post-lock loosening | — |
| `consistency_judge` | 3 / 3b | does the drafted brief contradict the hypothesis? | a restricted view, so it can't be swayed |
| `sql_query_writer` | 5–6 | proposes the SRM and analysis SQL | — |
| `sql_corrector` | 5–6 | re-drafts a query the warehouse rejected | — |
| `monitor` | 5 | the SRM (sample-ratio-mismatch) check | the narrative/why-it-matters |
| `analyzer` | 6 | computes lifts, CIs, p-values, guardrail tests | the hypothesis *intent* |
| `interpreter` | 7 | **the verdict** (8-label tree) | hypothesis prose, hopes, `state.yaml` |
| `readout` | 8 | the human writeup | nothing new — verdict is fixed |

The **designer trio** (elicitor / drafter / editor) is worth dwelling on: design is
split into three narrow agents rather than one, because "pull the intent and shape
the hypothesis," "write the brief and data plan," and "apply a scoped edit" are
three different judgments with different failure modes. The editor in particular
carries the G9/G14 integrity behavior — it applies edits scoped to a single field,
refuses to loosen a locked pre-registration, and routes any legitimate change
through the disclosed-deviation path (Module 4).

### How inputs reach an agent: the bundle

Agents never read the live conversation or the whole repo. The orchestrator
**assembles a bundle** — a curated, content-hashed snapshot of exactly the inputs
that agent is allowed — and hands it over. This is the mechanism that *enforces*
the isolation axiom: an agent can't see what you hoped for because that simply
isn't in its bundle.

- `BundleStore.assemble` in `agentxp/orchestrator/bundle.py` builds two kinds of
  bundle: a **`.ctx` bundle** (the context the agent reads) and an **`.out`
  bundle** (what it produced). Source files are SHA256-snapshotted into a
  `.sources/` directory so the exact inputs are replayable.
- `agentxp/orchestrator/dispatch.py` is where an agent is actually run against its
  bundle. Dispatch is also where every error path is scrubbed through the
  redactor (Module 5) before anything is logged.
- The hashes are the link back to the audit chain (Module 4): the
  `agent.dispatched` / `agent.completed` events carry the `bundle_hash`, so you
  can prove which exact inputs produced which output.

The chain of custody is: *orchestrator decides what the agent may see → bundle
snapshots and hashes it → dispatch runs the agent → output is hashed and
committed.* The agent's field of view is a design decision encoded in what the
bundle contains.

---

## Lab / break-it (prove the blindness)

**Lab 2a — read an agent as a function signature.** Open
`agents/interpreter.system.md`. Find: (1) its scope statement, (2) the explicit
"does not have access to state.yaml" line, (3) the inputs it *is* given, (4) the
output format. Write down the "type signature" in one line:
`interpreter(locked_rule, analyzer_numbers) -> verdict_label`. Notice what's
*absent* from the inputs — that absence is the whole point.

**Lab 2b — find the seam in the bundle.** Read `agentxp/orchestrator/bundle.py`
and locate `assemble`. Trace what goes into an interpreter bundle versus a
profiler bundle. Confirm from the code that the hypothesis prose / "what the user
wanted" is not assembled into the interpreter's `.ctx` bundle. This is the
break-it lesson: *you cannot leak intent to the interpreter through the supported
path, because the supported path doesn't carry it.*

**Lab 2c — try to bias the judge (and watch the structure refuse).** In a
`/experiment` run, deliberately tell Claude something like "I really need this to
ship" during design. Then run through to the verdict and `agentxp audit` the
experiment. Confirm that the interpreter's committed inputs (its bundle) contain
the locked rule and the numbers — not your plea. The plea lives in the
conversation; it never enters the judge's context, so it can't affect the verdict.

**Lab 2d — read the refusal contract.** Open `agents/designer/editor.system.md`
and find the v0.1 behavior block describing what happens when someone tries to
loosen a *locked* brief after results are in. Note that the editor does NOT
silently overwrite — it captures the change as a disclosed deviation, and the
supported way to change a locked pre-registration is a new experiment. (This is
the prompt-side of the Module 4 integrity wall.)

---

## Teach-back checkpoint

You pass Module 2 when you can, without notes:

1. **State the isolation axiom in one sentence**, and name the *specific* inputs
   the interpreter is denied — and explain why denying them makes the verdict more
   trustworthy rather than less.
2. **Trace one input from conversation to agent**: explain what a bundle is, what
   `BundleStore.assemble` does, why the inputs are SHA256-snapshotted, and how that
   ties to the audit chain.
3. **Read a `*.system.md` aloud as a program**: point at its scope, its "does NOT"
   refusal set, its banned-vocabulary/voice constraint, and its one-shot examples,
   and say what each is *for*.
4. **Defend the designer trio split** — why three narrow agents instead of one,
   and which one carries the locked-rule refusal behavior.

Pick any agent file at random; I'll ask you "what is this blind to, and why?" When
your answer holds for the interpreter, the monitor, and the readout, check the box
and we go to Module 3.
