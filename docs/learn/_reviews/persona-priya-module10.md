# Review — Persona: Priya (PM, data-literate, non-engineer) — Module 10

*Reviewer profile: I've shipped A/B tests, I know guardrails / SRM / null results /
pre-registration cold. I cannot write Python. I can run a terminal command if you
tell me exactly what to type, and I can read code slowly with a lot of squinting.
I evaluated whether Module 10 lets a technical-but-not-engineer truly OWN and DEFEND
the presentation layer — demo it, answer a skeptical exec — or whether it's
engineer-only. This continues the review of Modules 0–8; same lens, same rubric.*

---

## Verdict

**This is the most exec-defensible module in the whole course, and — surprise — it's
also the most PM-runnable. The concepts here are exactly the questions a stakeholder
asks about a polished deliverable, and four of the six labs are real terminal
commands I can actually run. Two labs (10c, F) are engineer-only, but unlike the
middle modules, the brick-wall labs are NOT load-bearing — the axiom they prove is
already proven by labs I *can* run. So the fix here is small: relabel two labs and
hand me one missing demo, and a PM owns this module cold.**

Compare this to my Modules 2/4/5/6 finding. Back there, the *only* way to "prove"
the trust property was to open `bundle.py` or build a `TreeInput` in a REPL — the
code lab WAS the proof, so a non-engineer hit a wall on the single most important
point. Module 10 is the opposite shape. The proof of "polish never outruns proof"
is **Lab 10b** (tamper, watch every format stamp DRAFT, watch every exit code go to
warning), and 10b is a command I run plus one paste-this snippet. Lab 10c ("open
`data.py` and try to make the adapter lie") teaches the *same* axiom from the code
side — but it's a bonus angle, not the only door. That's the difference between an
accessible module and an engineer-only one, and Module 10 got it right.

**The headline win for my persona:** the four concepts in this module —
"`report.json` is the only source of truth," "every output is a pure renderer,"
"polish must never outrun proof," and the three-state verified/draft/unverifiable
badge — are the answers to the *single most common exec question about any analytics
deliverable*: **"can I trust this pretty PDF?"** Every other module defends the
*analysis*. This one defends the *artifact the exec is actually holding*. A PM who
owns this module can stand in front of a screenshot in a deck and say why it can't
be lying. That's gold, and the module mostly delivers it. See "the exec thread" below.

---

## The exec-defense thread (does it exist? mostly yes — and it should be hoisted)

There IS a clean, liftable answer to "can I trust this pretty PDF?" buried in here.
A PM can assemble it from the prose:

> "The PDF is a *photograph* of the HTML one-pager, and the HTML is a pure render of
> one structured record — `report.json`. No output in this system is allowed to do
> arithmetic; the number you see in the headline was formatted exactly once, in one
> place, and every format — markdown, the exec page, the social card, the CSV, the
> PDF — copies that one string. There is no second place a number can come from, so
> there's no second place it can drift. And the proof rides along with the polish:
> if the underlying chain doesn't verify, the page literally stamps DRAFT on itself.
> A clean-looking PDF that *hadn't* verified is not something this system can
> produce."

That's a PM-deliverable paragraph and it's the most valuable thing in the module.
Two problems with how it's currently presented:

1. **It's never assembled in one place for me.** The pieces are scattered across the
   "Why" section, the badge section, and the rasterizer step. The module assembles
   the *engineering* story end-to-end (the two-spine diagram, the `main()` trace) but
   never assembles the *exec* story end-to-end. Module 0 gave me three objections
   with near-verbatim answers. Module 10 should give me the one objection that matters
   here — "can I trust this artifact?" — with the verbatim answer above. It's the
   single highest-leverage addition.

2. **The three-state badge is the most exec-relevant idea and it's framed for
   engineers.** "DRAFT_UNVERIFIED vs UNVERIFIABLE — accusation vs can't-check" is a
   *brilliant* distinction and it's exactly how a careful PM already thinks ("a red
   metric means something broke; a greyed-out metric means we couldn't measure it —
   never confuse those in a dashboard"). But it's introduced as `RenderStatus` enum
   members. Lead with the human version: **green = I checked and it holds; red = I
   checked and it's wrong (an accusation, show this rarely); grey = I couldn't check,
   and I will not pretend I did.** Then mention the enum names. The idea is pure PM;
   the framing makes it look like code.

---

## Lab-by-lab: which doors are open for me, which are walls

| Lab | What it teaches | Can I run it? | Notes |
|---|---|---|---|
| **10a** one number, six formats | the pure-renderer axiom, observable | **YES** | Real `agentxp report` commands. The `grep`/`sed`/`python -c` one-liners are copy-paste-able even if I don't understand them. See snag below. |
| **10b** tamper → every format stamps DRAFT | "polish never outruns proof" — THE axiom | **MOSTLY** | The render commands are mine. The *tamper step* is a 3-line Python snippet I'd paste blindly. This is the most important lab in the module and it's *so close* to fully reachable. Pre-broken fixture fixes it (below). |
| **10c** open `data.py`, try to make it lie | the axiom from the type-system side | **NO — wall** | "Open any adapter and try to improve a number." That's reading and editing Python. But it's a *bonus angle* — 10b already proved the same point behaviorally. |
| **10d** fail fast on missing extra | optional-dep UX, fail-by-name | **YES** | One command, exact expected message. I confirmed the CLI prints exactly this and exits 1 before touching disk. Clean. |
| **10e** break the index, page survives | per-row isolation | **MOSTLY** | Commands are mine; "corrupt one's `report.json` (`{ not valid json`)" is a file edit but a trivial one I can do in any text editor. Reachable. |
| **Lab F** write a `txt` adapter in Python | extend the layer | **NO — wall** | "Create `text.py` with a `TextAdapter` class … `render(self, bundle) -> str`." This is writing Python. Same as the Module-8 finding: *extend* is not a non-engineer verb, and that's fine — as long as it's labeled. |

**The good news in one sentence:** the brick-wall labs (10c, F) are the *extend /
prove-from-code* labs, and the *defend / demo* labs (10a, 10b, 10d, 10e) are
runnable. That's the right split landing by accident — make it land on purpose.

### Snags I hit as a non-engineer, even on the "runnable" labs

- **Lab 10b's tamper is Python, and it doesn't need to be.** The whole point is "now
  render and watch it stamp DRAFT." I don't need to *understand* the tamper, but a
  Python snippet next to four shell commands makes me feel I've left my lane. **Fix:
  ship a pre-broken fixture experiment** (a `report.json` with a zeroed `chain_hash`),
  the way I asked for in the Module-4 review. Then 10b becomes: `agentxp report
  broken_chain --format md` and read the `⚠ DRAFT — UNVERIFIED` banner. Fully
  reachable, and a *better* exec demo too — I can run it live in front of someone.

- **Lab 10a's verification line is unexplained.** The lab gives me four cryptic
  one-liners and says "they match because there is one `lift_str`." I'll trust that,
  but I can't *see* the match unless I run all four and eyeball the outputs. **Add the
  expected output** — "all four print `+0.032 (+18.0%)`" — so I can confirm I did it
  right. (This is the same self-check problem I flagged in Module 3: without an answer
  key, a runnable lab still leaves me unsure I succeeded.)

- **Both labs assume `exp_001` exists.** The setup line says "the `ship_demo.csv`
  fixture from Module 1, or the existing `tests/render/fixtures/bundles_ship/`
  finalized into a dir." *"Finalized into a dir"* is an engineer instruction — I don't
  know how to finalize a fixture into a dir. I need one exact command (or a shipped
  `experiments/exp_001/` I can point at) or every lab in this module is gated on a
  step I can't do. **This is the actual first brick wall, and it's in the setup, not a
  lab.**

---

## The teach-back checkpoint is all-or-nothing again (same Module-8 problem)

Items 1–5 of the teach-back are *defend* items — state the axiom, explain the
pure/impure split, walk the three states, trace one number across six formats,
explain index isolation. **I can do all five from the prose**, and four of them I can
*demo* with the runnable labs. That's a real, complete, valuable outcome: a PM who
can demo and defend the presentation layer.

Item 6 is **"add the `txt` adapter in front of me."** That's writing Python. It gates
the whole checkpoint on a skill I don't have, so as written I "fail" Module 10 even
though I achieved everything a launch actually needs. Same fix as Module 8: **split
the checkpoint into a PM/defend track (items 1–5) and an engineer/extend track (item
6),** and name "passed the defend track" as a legitimate, complete outcome. The
closing line — "When you can state the axiom, defend the pure/impure split, *and
extend the layer*… you own the share-out spine" — bolts the engineer verb onto the
completion bar. Let me own the spine by *defending* it; extending it is a separate,
optional badge.

---

## Confidence block (1 = couldn't do it, 5 = could do it cold)

- **Concepts** — axiom, pure/impure split, three-state badge, "proof welded to
  polish." All squarely in my wheelhouse; the badge distinction is *more* natural to
  me than to an engineer. **Confidence 5. Fully reachable.**
- **The exec answer** ("can I trust this PDF?") — I can assemble it, but the module
  makes me assemble it; it should hand it to me. **Confidence 4, would be 5 if hoisted.**
- **Lab 10a** (six formats match) — runnable, but no answer key and a setup step I
  can't do. **Confidence 3; 5 with a shipped `exp_001` + expected output.**
- **Lab 10b** (tamper → DRAFT) — the proof of the whole module; reachable except the
  Python tamper. **Confidence 3; 5 with a pre-broken fixture.**
- **Lab 10d** (missing extra) — clean, exact, reachable. **Confidence 5.**
- **Lab 10e** (index survives) — reachable. **Confidence 4.**
- **Lab 10c** (make `data.py` lie) — can't. But it's a bonus. **Confidence 1, doesn't matter.**
- **Lab F** (write `txt` adapter) — can't, and shouldn't be expected to. **Confidence
  1; relabel as engineer-track.**

**Overall: Confidence 4.5 on owning-and-defending, gated almost entirely on the
fixture-setup step and two relabels.** This is the best a module has scored for my
persona alongside Modules 0 and 7 — and unlike those, this one has *runnable demos*,
which makes it the strongest module in the course for a PM who has to stand up in
front of an exec.

---

## Voice / pacing notes (carrying over from the Modules 0–8 review)

- **Over-bolding, still.** The "Aha —" blocks are bolded *and* blockquoted *and* often
  have a second bold clause inside. Three of them in the first 60 lines. They're good
  insights; let the blockquote carry the emphasis and drop the inner bolding.
- **The "you" coaching voice** is lighter here than in the middle modules — good. "Lab
  10c makes you go prove it" and "this is the module where you attack the system" are
  the only two; fine to keep one.
- **Pacing is good for me** *until* the walkthrough (steps 1–7), which is ~230 lines of
  code-internals (`_metric_table` line numbers, `_cant_check_reason` precedence, the
  `main()` trace). I don't need it and it's not for me — but unlike Module 5, the
  *insight* isn't buried *behind* it: the "Why" section up top already gave me the
  whole idea before the code starts. **So: add a one-line signpost at the top of the
  walkthrough** — "Steps 1–7 are the engineer's tour of the code; if you're here to
  defend and demo, the Why section above plus the labs are your path." That single
  sentence converts the walkthrough from "a wall I have to climb" into "a section I'm
  told I can skip," which is exactly the PM/engineer routing the whole course needs.

---

## Top fixes (prioritized) — see the return message for the short list

1. Ship a finalized `experiments/exp_001/` (and a pre-broken `broken_chain/`) so the
   labs have a real target without "finalize a fixture into a dir." Unblocks everything.
2. Hoist the exec answer: add a "can I trust this PDF?" objection + verbatim PM answer,
   Module-0 style.
3. Reframe the three-state badge in human terms (green/red/grey, checked-ok /
   checked-wrong / couldn't-check) before the enum names.
4. Relabel 10c and Lab F as engineer-track; split the teach-back into defend (1–5,
   PM-complete) and extend (6, optional).
5. Make Lab 10b's tamper a pre-broken fixture (no Python paste); add expected output to
   Lab 10a so the self-check closes.
6. Add the "steps 1–7 are the engineer's tour, skip to the labs to defend" signpost
   atop the walkthrough.
