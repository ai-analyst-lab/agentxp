# Review — Persona: Priya (Product Manager, data-literate, non-engineer)

*Reviewer profile: I've shipped A/B tests, I know guardrails / SRM / null results /
pre-registration cold. I cannot write Python. I can run a terminal command if you
tell me exactly what to type, and I can read code slowly with a lot of squinting.
I evaluated whether this curriculum lets a technical-but-not-engineer truly OWN and
DEFEND AgentXP — demo it, answer a skeptical exec — or whether it's engineer-only.*

---

## Verdict

**A data-literate PM can own and defend the *thesis* and the *behavior* of this
product after the curriculum, but NOT the *implementation* — and the curriculum
doesn't currently separate those two things, so it reads as engineer-only when
about half of it doesn't need to be.**

The good news first: the *ideas* in here are squarely in my wheelhouse and are
taught beautifully. Pre-registration enforced not suggested, the blind interpreter,
"the rule beats the number," a deterministic verdict tree, "replay me not trust me,"
SRM-halts-first, green-but-broken. I finished Module 0, 1, 3 (the concepts), 7, and
8 feeling like I could hold my own in front of a skeptical exec. Those are the
modules a PM most needs and they largely stand alone.

The bad news: Modules 2, 4, 5, 6 are written for someone who reads
`bundle.py`, `tree.py`, `store.py`, and `dispatch.py` as the *primary* artifact, and
treats the runnable/inspectable output as secondary or optional. The labs are
overwhelmingly "open this `.py` file and trace the function" — and when they're not,
they're "drop into a Python REPL and construct a `TreeInput` dataclass." For me both
of those are a brick wall. The frustrating part is that **most of those same insights
have a code-free path that already exists in the repo** (`agentxp audit <exp_id>`,
the `--diff` and `--html` flags, the sample-data outcomes table, the system-audit
prose) — the curriculum just doesn't route me to it as the main path.

**Engineer-only as currently written:** Module 2 (Lab 2b reads `bundle.py`), Module
3 (Lab 3a is a Python REPL with a dataclass), Module 5 (every lab is a Python
`run_pipeline(...)` call), Module 6 (hand-editing `state.yaml` / `log.jsonl` and
reasoning about commit ordering). Module 4 is *partly* reachable because `agentxp
audit` does the heavy lifting — but its teach-back still demands I distinguish
"parent-action chain vs replay hash vs locked-rule wall" at a precision that lives in
the code.

**Can I demo it?** Yes — Module 1 Lab 1a and Module 8 Part 1 are pure
`/experiment` conversation + `agentxp audit`, both reachable. **Can I defend it under
hostile questioning?** Mostly yes on the *why*, shakily on the *how* (see drill
below). **Could I extend it (add an adapter / verdict step)?** No, and the README
promises I'll be able to ("add an adapter, add a verdict step") — that promise is
not honest for a non-engineer and should be scoped.

---

## The skeptic-drill test

I went through Module 0's three objections and Module 8's 18-question gauntlet and
marked each PASS (could answer cold from the reading), PARTIAL (got the gist, would
wobble on specifics), or FAIL (needed code I can't read).

### Module 0 — the three launch-day objections

> **"This is just a wrapper around statsmodels with a chatbot on top. Why use it
> over Eppo, which is hosted and battle-tested?"**
**PASS.** I can answer this in my sleep: Eppo computes the stats correctly — that was
never the hard part — and then hands the judgment back to me at the exact moment my
judgment is most compromised. AgentXP seals the judgment off from the result. Plus
the wedge: runs in my terminal, I own the data, open-source, no per-seat pricing.
Module 0 hands me this almost verbatim and it's a *PM's* argument, not an engineer's.

> **"If an LLM makes the call, how is that more trustworthy than me making it?
> You've added a black box."**
**PASS.** The interpreter is blind — it never sees my hypothesis, my hopes, or the
conversation; it gets the locked rule + the numbers and walks a fixed tree. It
*can't* motivated-reason because the motivation isn't in its context. And the verdict
itself isn't even the LLM — it's a pure function, so "run it yourself." Strong answer,
fully reachable from prose.

> **"Pre-registration and audit logs are process theater. Disciplined teams already
> do this; undisciplined teams override everything. What does the tool change?"**
**PARTIAL.** I can give the conceptual answer (the lock is enforced by the structure,
not by discipline — you physically can't loosen the rule after seeing the result).
But when the skeptic pushes — *"enforced how, exactly?"* — the real answer is
"existence-on-disk is the lock, `_write_artifact` raises `ArtifactLocked`." I can SAY
that sentence but I can't *show* it the way Lab 4b wants (a Python REPL). I'd want a
`/experiment` moment where I try to change a locked brief and the system refuses *in
the conversation*, so I can demo the refusal without code.

### Module 8 — the 18-question gauntlet

| # | Question (abbrev.) | Result | Note |
|---|---|---|---|
| 1 | Why not Eppo? | **PASS** | PM-native argument |
| 2 | LLM = black box? | **PASS** | isolation axiom, from prose |
| 3 | Pre-reg is theater? | **PARTIAL** | can say the *why*, can't show the lock without code |
| 4 | Walk `/experiment` → verdict; where Claude stops, Python starts | **PASS** | the two-surfaces framing + 11-stage table is genuinely clear |
| 5 | Prove the interpreter can't be talked into a verdict — *show it in `bundle.py`* | **FAIL** | I can state *that* it can't; I cannot open `bundle.py` and point at the seam. The question literally requires reading code. |
| 6 | Why three design agents? | **PASS** | three judgments, three failure modes — a PM gets this |
| 7 | Why a hard-coded tree, not model reasoning? | **PASS** | recoverable vs unrecoverable error, replayability — well taught |
| 8 | Novel analyzer output → verdict + step, walk the tree cold | **PARTIAL** | I can do verdict + step from the *plain-English* 8-step list in Module 3. But Lab 3a wants me to construct a `TreeInput` to *verify*, which I can't. So I can reason it, not prove it. |
| 9 | SRM halts everything — brittle? | **PASS** | "a broken split poisons every downstream number, that's why it's step 1" — clean |
| 10 | Show me tamper-evidence; break Invariant 1 live | **PARTIAL** | `agentxp audit` showing `chain integrity: FAILED` is reachable; but Lab 4a's setup (hand-edit a `parent_action_id` in `log.jsonl`) is an engineer move. I'd need someone to pre-break a fixture for me. |
| 11 | Is it a blockchain? | **PASS** | No — ID-linkage via `parent_action_id`, not parent-content hashing; replay hash is separate. Module 4 states this crisply and even tells me to *correct the misconception*, which is exactly what a skeptic fishes for. |
| 12 | Crash mid-run — lose it or get a wrong answer? | **PARTIAL** | I get the *story* (append-then-advance, log-ahead-of-state is recoverable, the lying state can't arise from a crash). But "recite steps 6→7→8 of `_commit_stage`" is asking me to memorize a code function's internal ordering. I can defend the *property*, not the *function*. |
| 13 | "Green-but-broken" — why believe it's fixed now? | **PASS** | The monkeypatch was deleted, tests now hit real emitters, the E2E runs `validate_chain` ON. This is Module 7 and it's the single most *credible-making* answer in the whole gauntlet — and it's pure prose. A PM can wield this. |
| 14 | LLM writing SQL on my warehouse — talk me down | **PARTIAL** | "agent proposes, Python disposes, fail-closed layers, any layer can reject before a byte hits the warehouse" — I can say that. Naming "every layer" (parse → dialect-hazard → read-only → 3a/3b/3c → resource-bounds) and the exact exception each raises is a code-level recall task. PARTIAL. |
| 15 | Prove you won't print my Snowflake password | **PARTIAL** | I believe the answer (two redaction layers + a single chokepoint) but the demo is a Python REPL call to `_redact_creds_for_log`. The *one* place I'd most want a code-free demo (a CLI that shows a redacted error) and there isn't an obvious one. |
| 16 | What doesn't it do, why is each non-feature a strength? | **PASS** | randomized A/B only, no causal inference (declines cleanly), headless loop stubbed, three adapters `live_unverified`. "Amateurs oversell, experts name the edges" — I love this and can deliver it. |
| 17 | You kept `amendments/` — dead code you were scared to delete | **PASS** | reachability-from-a-near-need, `amendments_decision: KEEP` overruled task #68 as the G9 re-confirm vehicle. Pure judgment argument, no code. Module 7 nails it. |
| 18 | How do you know the adapters work if never run on live creds? | **PASS** | the `live_unverified` honesty — mock-tested, named as a boundary not hidden. PM-deliverable. |

**Tally: 9 PASS, 7 PARTIAL, 1 FAIL (Q5), Module-0 = 2 PASS + 1 PARTIAL.**

So a prepared PM could survive maybe two-thirds of the gauntlet convincingly, get
through another quarter on conceptual fumes, and faceplant on exactly one — Q5,
"show it in `bundle.py`." The PARTIALs cluster on a clear pattern: **I can defend
every *property* of the system; I wobble whenever the question demands I name a
*function, field, exception, or constant* by its code identity.** That's the whole
accessibility story in one sentence.

---

## Accessibility map

Per module: **fully-reachable** (a non-engineer can do everything), **mostly-reachable**
(core idea + most labs work; one or two code labs are skippable), **engineer-only**
(the labs and teach-back genuinely require reading/writing code), + what would unlock it.

| Module | Reachability | Why | What would unlock it |
|---|---|---|---|
| **0 Thesis & market** | **fully-reachable** | All prose; labs are `agentxp --version`, `agentxp list`, `/experiment`. The skeptic drill is a PM exercise. | Nothing. This is the model for the others. |
| **1 The shape** | **mostly-reachable** | The 11-stage table + two-surfaces framing is the clearest thing in the course; Lab 1a is `/experiment` + `agentxp audit`. Only `less STAGES.md` / reading the test file are code-adjacent and skippable. | Mark Lab 1b (pytest the E2E test file) as "optional / for engineers"; the audit timeline already proves the spine for me. |
| **2 Agents as programs** | **engineer-only** (as written) | Lab 2b ("read `bundle.py`, locate `assemble`, confirm the prose isn't assembled") is a hard gate. Lab 2a (read a `.system.md` as a function signature) is *almost* reachable — a `.md` prompt file is readable English, ironically. | Lead with Lab 2c (the *behavioral* proof: tell Claude "I really need this to ship," run to verdict, `agentxp audit`, confirm the plea never entered the judge's bundle — "the bias had nowhere to land"). That single lab proves the isolation axiom with zero `.py` reading and it's already here, just buried third. Demote 2b to optional. |
| **3 Deterministic core** | **engineer-only for the lab, mostly-reachable for the idea** | The 8-step tree is taught in plain English and Lab 3b (predict-then-check on 8 fixtures) is *fully* a PM exercise. But Lab 3a (REPL, build a `TreeInput` dataclass) is the "prove it" step and I can't do it. | Make Lab 3b the spine of the module (it already works for me). Replace 3a's "construct a TreeInput" with "read the verdict + step out of the `agentxp audit` / `verdict.yaml` output and compare to your prediction." Same lesson, no dataclass. |
| **4 Integrity spine** | **mostly-reachable, via the CLI** | This is the pleasant surprise: `agentxp audit` (+`--diff`, `--html`) is the inspection surface and Labs 4a/4c *show their expected CLI output*. But the *setup* for those labs (hand-edit `log.jsonl`) is engineer work, and the teach-back's three-mechanism distinction is code-precise. | Ship **pre-broken fixture experiments** (a tampered-chain dir, a gate-pairing-violation dir) so I can run `agentxp audit` on them and *see* the refusal without doing the surgery. That converts 4a/4c from engineer-only to fully-reachable. |
| **5 Data plumbing** | **engineer-only** | Every lab is a Python `run_pipeline(...)` / `parse_sql(...)` call. The teach-back wants me to name layers and their exceptions. | A CLI like `agentxp check-sql "SELECT 1; DROP TABLE users"` that prints "rejected at Layer 2: write not permitted" would make the whole module reachable and would *also* be a better live demo for Q14/Q15. As-is, the SQL-safety story is the least PM-legible in the course despite being the one execs worry about most ("an LLM is writing SQL on my warehouse"). |
| **6 State, stores & resume** | **engineer-only** | Labs hand-edit `state.yaml`/`log.jsonl` and reason about `_commit_stage` step ordering. The *one* reachable lab is 6a (interrupt a `/experiment`, `agentxp resume`). | Lead with 6a (it's a great PM-reachable "kill it and bring it back" demo). The two-stores / commit-ordering teach-back should be flagged "defend the *property* (no lying state); engineers also learn the function." I can defend "the log is the source of truth, state is a derived cache" without reciting eight numbered steps. |
| **7 Build history** | **fully-reachable** | The whole module is reading four `.md`/`.yaml` docs and making *judgment* arguments. "Green-but-broken," the necessity criterion, the keep-vs-cut calls — all PM-legible, all from prose. Lab is "write the argument," not "trace the code." | Nothing. Alongside Module 0, the strongest module for my persona. |
| **8 Capstone** | **mostly-reachable** | Part 1 demo is `/experiment` + `agentxp audit` (reachable). The gauntlet is mostly defensible (see drill). But the checklist literally requires "show it in the bundle code" (Q5) and REPL demos (redaction, TreeInput). | Split the checklist into a **PM track** (demo + defend the properties + the judgment/scope answers) and an **engineer track** (the code-level "show me in the file" items). A PM passing the PM track should be a legitimate, named outcome — right now the checklist is all-or-nothing and gated on code. |

---

## Per-module notes (pacing, voice, redundancy, confidence)

**Voice, overall.** Strong. It mostly reads like a good O'Reilly book: economical,
declarative, "problem → constraint → choice." It is *not* preachy and it earns its
opinions. Two voice problems recur:

1. **Over-bolding.** Nearly every paragraph has a bolded clause, and several have
   the whole load-bearing sentence in bold. When everything is bold, nothing is.
   Offenders: Module 1's "**every stage ends at the same chokepoint**" *and*
   "**Eleven stages, one commit path**" *and* "**`_commit_stage`**" all bold within
   three sentences; Module 4 bolds five mechanism names plus five invariant headers
   plus inline phrases. Cut bolding to ~one emphasis per section.

2. **"a reviewer will test you on them" / "amateurs oversell, experts name the
   edges" / "this is the module where you attack the system."** This second-person
   coaching voice is motivating once, grating by the fourth module. It's the one
   place the writing tips from "clear technical prose" toward pep-talk. Module 0's
   "Knowing the boundaries *cold* is half of looking like an expert" is the
   archetype — true, but it appears in spirit in almost every teach-back.

**Redundancy.** The `_commit_stage` 8-step ordering is printed nearly verbatim
**three times** (Module 1 lines 96-109, Module 6 lines 51-68, and re-narrated in
Module 8). The two-surfaces (shell CLI vs `/experiment`) framing appears in the
README, Module 0, and Module 1. The `live_unverified` adapter caveat appears in
Modules 0, 5, 7, and 8. The G14 two-store boundary appears in Modules 2, 4, 6, 7.
Some of this is deliberate spiral-teaching and fine; the `_commit_stage` verbatim
triple-print is genuinely too much — print it once (Module 6, where it belongs),
reference it elsewhere.

**Pacing.** Modules 0, 1, 7 are paced right for me. Module 4 is dense but the
density is earned (it's the trust module). Modules 3, 5, 6 front-load code
mechanics that lose me before they reach the insight — e.g., Module 5 spends ~80
lines on layer-by-layer code internals before the teach-back, when the *idea* ("any
layer can reject before a byte hits the warehouse; agent proposes, Python disposes")
is one sentence I'd have grasped immediately and the layers are detail.

**Confidence blocks** (1 = couldn't do it, 5 = could do it cold):

- **M0** — Could state the thesis, name the 3 subsystems, survive 2 of 3 objections
  cleanly. **Confidence 5. Reachable.**
- **M1** — Could name all 11 stages, owner, artifact, gate; could narrate a
  `ship_demo` run. Could NOT recite the `_commit_stage` internals. **Confidence 4.
  Mostly reachable.**
- **M2** — Could state the isolation axiom and *why* it's trustworthy; could run the
  behavioral proof (2c). Could NOT do the `bundle.py` trace (2b). **Confidence 3.
  Engineer-only as written, 4+ if reframed around 2c.**
- **M3** — Could walk the 8-step tree in English and predict all 8 fixtures. Could
  NOT build a `TreeInput`. **Confidence 4 on the idea, 2 on the lab. Mostly
  reachable if 3b leads.**
- **M4** — Could explain the three mechanisms conceptually and run `agentxp audit`.
  Could NOT hand-break `log.jsonl` myself. **Confidence 3. Mostly reachable with
  pre-broken fixtures.**
- **M5** — Got the one-sentence thesis; lost in the layer internals; can't run any
  lab. **Confidence 2. Engineer-only.**
- **M6** — Could run interrupt/resume (6a) and defend "log is source of truth, state
  is derived." Could NOT recite commit ordering or hand-edit state. **Confidence 3.
  Mostly reachable if 6a leads.**
- **M7** — Could defend every keep-vs-cut call and explain green-but-broken. **Confidence
  5. Fully reachable.**
- **M8** — Could do the demo and ~two-thirds of the gauntlet. **Confidence 3.5.
  Mostly reachable; fails the code-show items.**

---

## A real bug I hit as a PM (label mismatch)

Module 3 Lab 3b and the README cheat-sheet tell me to **predict the verdict, then
run `/experiment` and check myself against the answer**. But the answer key
disagrees with itself:

- README / curriculum cheat-sheet: `guardrail_violation.csv` → **NO-SHIP-GUARDRAIL**;
  `mixed_results.csv` → **caveat / investigate**; `srm_violation.csv` → **INVALID-SRM**.
- `sample-data/README.md` (the file I'd actually open next to the fixture): the same
  three are labeled **INVESTIGATE**, **INVESTIGATE**, and **INVALID** (no `-SRM`).

For an engineer this is a shrug. For *me*, the self-check loop is the entire learning
mechanism in Module 3, and a mismatched answer key makes me think I got it wrong when
I got it right — or worse, teaches me the wrong label. The two verdict vocabularies
need to be reconciled (the curriculum's 8-label set is presumably canonical;
`sample-data/README.md` should match it exactly).

---

## Top 10 highest-value fixes

1. **Add a "PM / defend track" vs "engineer / extend track" split at the top.** The
   README promises both "defend" and "extend (add an adapter, add a verdict step)."
   Defend is reachable for me; extend is not. Say so. Let a PM legitimately *complete*
   the defend track without the code labs. Right now the all-or-nothing capstone
   checklist makes a PM feel they failed when they actually achieved the goal that
   matters for a launch.

2. **Reframe each code lab with a code-free primary path where one exists.** The
   pattern is almost always "read `foo.py`" → could be "read the `agentxp audit`
   output / the `.yaml` artifact / the CLI rejection." The repo already has the
   inspection surface; the curriculum just doesn't route me to it first.

3. **Ship pre-broken fixture experiments** (tampered chain, gate-pairing violation,
   lying state). Then Labs 4a/4c/6c become "run `agentxp audit` on `broken_chain/`
   and read the refusal" — fully reachable — instead of "hand-edit `log.jsonl`."

4. **Make Module 2's behavioral proof (Lab 2c) the lead, demote the `bundle.py`
   trace (2b) to optional.** 2c proves the isolation axiom with zero Python reading
   and is more convincing anyway ("the bias had nowhere to land"). This single move
   converts the most important conceptual module from engineer-only to reachable.

5. **Fix the verdict-label mismatch** between the curriculum cheat-sheet and
   `sample-data/README.md` (NO-SHIP-GUARDRAIL vs INVESTIGATE, INVALID-SRM vs INVALID).
   It breaks the self-check loop that is Module 3's whole pedagogy.

6. **Add two small inspection CLIs** so the two most exec-relevant claims have
   code-free demos: `agentxp check-sql "<query>"` (prints which safety layer rejects
   it) and a way to surface a redacted error in the terminal. These directly serve
   gauntlet Q14/Q15, the questions an exec is *most* likely to ask, and which are
   currently REPL-only.

7. **Print the `_commit_stage` 8-step ordering once** (in Module 6), and reference it
   from Modules 1 and 8 instead of re-printing it. Frees space and stops it reading
   like filler.

8. **Cut bolding by ~70%.** One emphasis per section. The writing is strong enough to
   carry weight without typographic shouting (Modules 1 and 4 are the worst
   offenders).

9. **Dial back the "look like an expert / a reviewer will test you" coaching voice.**
   Keep it in Module 0 and the capstone where it fits the frame; strip it from the
   middle modules so they read like reference, not a pep rally.

10. **In Module 3, make Lab 3b (predict-then-check on 8 fixtures) the spine and
    replace Lab 3a's "construct a TreeInput" with "read verdict + step from the audit
    output."** The 8-step tree taught in English is genuinely PM-learnable; the only
    thing gating it is the dataclass, and the dataclass isn't the lesson.
