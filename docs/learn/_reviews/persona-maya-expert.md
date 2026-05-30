# Review — "Maya," the senior engineer who already built this

Reviewed: README + Modules 0–8. Standard: O'Reilly technical book — clear,
economical, example-first, no purple prose, no over-bolding for drama.

## Verdict

This would make a new expert — the architecture is genuinely covered, the
labs are real (run the tree as a pure function, hand-break `log.jsonl`, trip
each SQL layer), and the teach-back checkpoints are well-targeted. The bones
are excellent. But it is not yet economical enough to be worth *my* time as
someone who built it: the thesis sentence, the "deterministic Python owns X /
LLM owns Y" line, the isolation axiom, the `_commit_stage` 8-step ordering, and
the G14 two-store boundary are each restated three to five times in nearly
identical prose across modules. That's the difference between a course that
respects an expert's time and one that re-teaches its own first chapter. It
also over-bolds for drama and tells-not-shows in a handful of load-bearing
spots ("You just proved tampering is detected," "The bias had nowhere to
land," "Sit with that"). Cut the cross-module restatement to a one-line
back-reference and the voice tics, and this goes from a strong B+ to the
O'Reilly bar. Net: ship it, but edit the redundancy out first — it's the single
biggest lever.

## Cross-module redundancy register

The curriculum re-explains the same five concepts repeatedly. A back-reference
("see Module N") would do; instead the full explanation recurs. Exhaustive list:

### R1 — The thesis sentence ("deterministic Python owns stats / LLM owns judgment / sealed off")
Stated in full, or in near-identical paraphrase, in **six** places:
- README L77 (module map row 0) — "Why does this exist?"
- `00_thesis.md` L29–33 — the canonical blockquote ("memorize this sentence").
- `01_shape.md` L17–18 — "the physical expression of the thesis from Module 0."
- `02_agents.md` L14–16 — "Module 0 drew the line: `agentxp/` (Python) owns
  anything a wrong answer would corrupt; `agents/` (markdown) owns judgment."
  This is a verbatim re-statement of the thesis, not a reference.
- `03_deterministic_core.md` L13 — "The thesis says deterministic Python owns
  the statistics and the LLM owns the judgment."
- `05_data_plumbing.md` L23–24 — "This is the same thesis line as everywhere
  else — the LLM does the judgment … and Python owns the part where a wrong
  answer is catastrophic." (At least this one *names* that it's repeating.)

### R2 — The "two surfaces" / "Claude is the orchestrator" / Phase 5 stub
Explained in full **three** times:
- README L53–69 — the dedicated "two surfaces" section.
- `01_shape.md` L36–49 — "Where the stages actually run" re-explains shell CLI
  vs pipeline, "Claude is the orchestrator," and the Phase-5 stub *again*, in
  full, immediately after the README said it.
- Re-touched in `00_thesis.md` L58–65 ("Claude Code is a runtime") and `06`/`07`
  (`_invoke_llm` stub). The Phase-5-stub-is-honest-not-a-bug framing alone
  appears at README L65, `00` L70, `01` L43–44, `06` L44–47, `07` L159–161,
  `08` L163–166 — six times.

### R3 — The isolation axiom ("the judge never sees your hypothesis/hopes")
Stated in full **five** times:
- `00_thesis.md` L44–47 — "The interpreter is blind … It *cannot* motivated-reason
  because the motivation isn't in its context."
- `02_agents.md` L19–32 — the canonical statement + blockquote (correct home).
- `02_agents.md` L93 (roster table) — "blind to: hypothesis prose, hopes,
  state.yaml" — fine as a table cell.
- `03_deterministic_core.md` L141–142 — "Anything not in `TreeInput` (your
  hopes, the hypothesis prose) provably cannot change the verdict. That's the
  isolation axiom (Module 2) expressed as a type." (Good framing, but re-derives.)
- `08_capstone.md` L42–44 + Q5 L83–84 — restated again.
The phrase "never sees the hypothesis prose / never sees what you said you
wanted / never sees the conversation" appears nearly verbatim at `00` L45–46
**and** `02` L29–31.

### R4 — The `_commit_stage` 8-step ordering (validate → append → advance)
The full 8-step list appears **twice, nearly identically**:
- `01_shape.md` L89–112 — "The one function under all eleven: `_commit_stage`"
  with all 8 steps spelled out.
- `06_state_stores_resume.md` L49–68 — "The chokepoint: `_commit_stage`" with
  the *same* 8 steps spelled out again. Module 6 is the right home (it's the
  resume module); Module 1 should give the shape in 2–3 lines and forward-ref,
  not pre-print the whole list. The "validate→append→advance, memorize 6→7→8"
  instruction appears at `01` L111, `06` L51/L65, `08` L54–56 (three times).
- The G11 crash-window explanation ("log ahead of state is recoverable, behind
  is a lie") is in `01` L106–108, `06` L70–76, `07` L54 (G11 row), `08` L102–104.

### R5 — The two-store split / G14 boundary ("not unified in v0.1")
Explained in full **three to four** times:
- `04_integrity_spine.md` L140–144 — the amendments/G14 boundary.
- `06_state_stores_resume.md` L29–47 — "The two store layers (and why they're
  not unified)" re-explains `OrchestratorStore` vs `ExperimentStore` and *why
  naive chaining breaks Invariant 1* — which `04` L143–144 already said.
- `07_build_history.md` L57 (G14 row) + L163–169 (judgment lesson).
- `08_capstone.md` L167–169 (roadmap).

### R6 — The locked-rule wall ("existence on disk is the lock")
- `00_thesis.md` L40–41 (subsystem 1).
- `01_shape.md` L73–75 ("Stage 2 is the integrity hinge").
- `02_agents.md` L154–158 (Lab 2d, the prompt-side).
- `04_integrity_spine.md` L34–41 + L107–124 (the canonical home).
- `08_capstone.md` L42–43.
"Locking isn't a flag; existence on disk is the lock" appears at `04` L39 and
L121 (twice within the same module).

### R7 — "Naming the boundaries is half of looking like an expert"
This exact motivational beat recurs:
- `00_thesis.md` L72–73 — "amateurs oversell, experts name the edges."
- `05_data_plumbing.md` L34 — "Naming that boundary is part of looking like an
  expert."
- Echoed in `01` L44, `07` throughout, `08` Q16/Q18.

### R8 — "the rule beats the number" / "guardrail before ship"
- `01_shape.md` L83 — "the rule beats the number."
- `03_deterministic_core.md` L84 (step 2) + L166 — "the encoded version of 'the
  rule beats the number.'"
- `08_capstone.md` Q9 (SRM halt rationale).

### R9 — The skeptic-drill questions (verbatim duplication)
The three Module 0 market objections (`00` L137–141) are reproduced **word-for-
word** as `08_capstone.md` Q1–Q3 (L72–77). Likewise `00`'s "name three
non-features" reappears as `08` Q16. This is intentional (capstone = gauntlet),
but the capstone could *reference* them rather than re-paste, or at least not
also restate their expected answers inline.

### R10 — `live_unverified` adapters (DuckDB verified, 3 ship unverified)
- README L48 (skips are credential-gated).
- `00_thesis.md` L71–72.
- `05_data_plumbing.md` L33–34 + L107–109.
- `07_build_history.md` L133–140.
- `08_capstone.md` Q18 + checklist + roadmap.

## Per-module notes

### Module 0 — Thesis & market
**Goal met?** Yes. The thesis sentence, three subsystems, why-now, scope-NOT,
and skeptic drill are all here and the FAQ exercise is the right test.

**Pacing.** The problem framing (L14–27) is two paragraphs where one would do;
"None of this is dishonesty — it's how brains work when a number you care about
is on the screen" is a nice line but the surrounding setup belabors a point the
target reader concedes in one sentence. The three-subsystems list (L40–51) is
good but each item pre-explains a whole later module — keep the one-liner, drop
the parenthetical mini-lecture.

**Voice.** Mostly clean. "They're calculators." (L25) is a good short line that
earns itself. Over-bolding starts here: **bold** on "before" (L42), "blind"
(L44), "replayable" (L48) is fine once, but the pattern compounds across modules.

**Telling vs showing.** L73 "Knowing the boundaries *cold* is half of looking
like an expert — amateurs oversell, experts name the edges" is sermonizing. The
reader is an expert; don't tell them what experts do.

**Confidence calibration.**
- (a) Should be able to: state the thesis in one sentence; name the 3
  subsystems; answer the 3 market objections; name 3 non-features + why.
- (b) Target: **4/5** (defend the thesis under push-back).
- (c) Gets there. The skeptic drill with you playing skeptic is exactly the
  right mechanism. Slight over-claim only in that it asserts the answers are
  strong rather than letting the reader discover them under pressure first.

### Module 1 — The shape: 11 stages
**Goal met?** Yes, strongly. The stage table is the best artifact in the course
— owner/artifact/gate columns are exactly the three questions an expert needs.

**Pacing.** Too slow at the top: L12–18 ("a pipeline with a conscience") is a
metaphor stretched across a paragraph. The bigger problem is the full
`_commit_stage` 8-step dump (L89–112) — see R4. In the *shape* module, that's a
premature deep-dive that Module 6 then repeats verbatim. Give the 3-line shape
here, forward-ref Module 6.

**Voice.** "An experiment platform is really a **pipeline with a conscience**"
(L12) — borderline cute; an O'Reilly editor would cut "with a conscience" or
make it a one-time aside, not a bolded thesis. "the whole pipeline stops looking
like eleven things and starts looking like one thing that runs eleven times"
(L32–33) is a good line — keep that one.

**Telling vs showing.** Largely shows (the table, the audit-timeline lab). Good.

**Confidence calibration.**
- (a) List 11 stages + owner/artifact/gate; explain why Stage 2 precedes Stage
  5; name `_commit_stage` + ordering; identify the two blind judges.
- (b) Target: **5/5** (this is the spine; everything references it).
- (c) Gets there *if* the learner does Lab 1a/1b. The "narrate it to me against
  the audit timeline" check is excellent and well-calibrated.

### Module 2 — Agents as programs
**Goal met?** Yes. "Read a `*.system.md` as a function signature" is the right
mental model and the bundle/dispatch chain-of-custody is traced concretely.

**Pacing.** Good, mostly. L23–32 re-explains the isolation axiom at length right
after stating it as a blockquote — tighten: the blockquote + one sentence of
"why backwards" is enough; the "cut the wire" paragraph restates it a third time
within the same module.

**Voice.** L151 "*The bias had nowhere to land.*" — italicized dramatic
one-liner. This is the single worst voice offense in the course: it's a
screenwriter's button, not engineering prose, and it's *telling* (see below).
"are not documentation and not vibes" (L4) — "vibes" is chatty in a way O'Reilly
wouldn't print in a goal statement.

**Telling vs showing.** L151 asserts the outcome ("The bias had nowhere to
land") instead of letting the `agentxp audit` output show that the interpreter's
bundle contains only the locked rule + numbers. The lab *does* show it (L146–151);
then the dramatic line tells it anyway. Cut the line; the artifact already made
the point.

**Confidence calibration.**
- (a) State the isolation axiom + the specific denied inputs; trace an input via
  `BundleStore.assemble`; read a system.md as a program; defend the designer trio.
- (b) Target: **4/5**.
- (c) Gets there. Lab 2c (try to bias the judge, watch it fail) is the strongest
  break-it in the course. Earns its claim.

### Module 3 — The deterministic core
**Goal met?** Yes, and this is the best-paced module. The tree-as-pure-function
lab (drive `walk_tree` directly) is exactly right for an expert.

**Pacing.** Tight. The 8 verdicts are enumerated once, cleanly. Good restraint.

**Voice.** Clean. "it picks which function applies and reports the number the
function returns" (L23) — economical, shows the analyzer's actual job. "Same
inputs, same verdict, every time, forever." (L27) — the "forever" is a small
flourish but tolerable. The "deep point for a reviewer" header (L34) is slightly
self-important but the content under it is real.

**Telling vs showing.** Good — Lab 3b (predict all 8 fixtures cold, *including
the step*) makes the reader demonstrate the claim instead of being told.

**Confidence calibration.**
- (a) Explain why stats+verdict are deterministic (recoverable vs unrecoverable
  error); name the whitelist's role + 4 functions incl. the halting one; walk
  the 8-step tree cold; distinguish verdict from confidence label; defend a
  constant.
- (b) Target: **5/5** (this is the part you most have to defend live).
- (c) Gets there cleanly. The "defend the constant" checkpoint (L183–184) is a
  standout — it forces understanding, not recall.

### Module 4 — The integrity spine
**Goal met?** Yes. Five invariants, the two-mechanism distinction, the lock,
amendments, and five break-it labs. The most technically dense module and it
earns the density.

**Pacing.** Mostly right, but the "two distinct integrity mechanisms" framing
(L20–41) + the "it is NOT a blockchain" correction is then re-paged in the
checkpoint (L206–207) and again as `08` Q11 — the *correction* is worth one
strong statement, not three.

**Voice.** Generally good, engineering-dense prose. Over-bolding creeps:
**ArtifactLocked**, **existence on disk is the lock** (L39 and again L121),
**It is not a blockchain** (L29). Pick one bold per idea.

**Telling vs showing.** **The worst telling-not-showing line in the course is
here:** Lab 4a L164 — "You just proved tampering is detected on every read — no
hash needed." The lab just had the reader run `agentxp audit` and read a
`FAILED — …` footer. The footer *is* the proof; the sentence telling the reader
they proved it is redundant and slightly condescending. Let the output stand.

**Confidence calibration.**
- (a) Distinguish the 3 mechanisms (+ correct the blockchain myth); name 5
  invariants + what each rejects + why validate returns rather than raises;
  explain the lock precisely; explain the G14 boundary; break one invariant live.
- (b) Target: **5/5**.
- (c) Gets there — arguably the highest-confidence module because the labs are
  adversarial (hand-edit the log, watch it fail). This is showing at its best;
  just delete the "you just proved" narration.

### Module 5 — Data plumbing
**Goal met?** Yes. The honest "5 layers is spec framing; code has 4 with 3a/b/c"
correction (L29–34) is exactly the kind of precision an expert respects.

**Pacing.** Good. Dense but every line carries a real fact (exception names,
deny-list functions, row caps). The redactor section (L111–139) is the right
depth for "the worst-case failure."

**Voice.** Cleanest module after Module 3. "The agent proposes; deterministic
Python disposes" (L21) is a good, earned line. Minor: "(the important one)" /
"(the important part)" appears twice (L138, L198) — pick one emphasis cue.

**Telling vs showing.** Strong. Lab 5d makes the reader `grep -r hunter2` and
find nothing — the *absence in the grep* is the proof. Then L209 tells them
"You've proven the leak path is closed at the key level, the regex level, and
the disk level" — same pattern as 4a, the grep already proved it; trim the
recap to "Three layers, three demonstrations" or cut.

**Confidence calibration.**
- (a) Trace a query through every layer + exception each raises; explain why AST
  allowlist AND function deny-list; explain the redaction guarantee + the drift
  incident; name what the audit trail can't hold; state adapter-verification honesty.
- (b) Target: **5/5** (this is the question that scares enterprise reviewers).
- (c) Gets there. The "I'll hand you an arbitrary SQL string, which layer kills
  it" checkpoint (L234) is well-calibrated.

### Module 6 — State, stores & resume
**Goal met?** Yes. Two stores, the chokepoint, reconstruct-from-log, the 8
resume cases, and a kill-it-and-resume lab.

**Pacing.** The single biggest redundancy victim. L49–68 re-prints the entire
`_commit_stage` 8-step list that Module 1 L89–112 already printed. This is the
*correct home* for it — so the fix is to thin Module 1, not Module 6. As written,
the expert reads the same numbered list twice and learns nothing new the second
time. The two-store explanation (L29–47) also overlaps `04` L140–144.

**Voice.** Good. "the question isn't whether it crashes; it's whether a crash
can leave the experiment in a **lying state**" (L14–16) is a strong, concrete
framing — keep it. "Equal-or-ahead is recoverable; behind is a lie." (L76) is a
good economical button.

**Telling vs showing.** Good — Lab 6c (manufacture the lying state, watch resume
win) shows it.

**Confidence calibration.**
- (a) Name the two stores + roots + which is chained + why not unified; recite
  the commit ordering + the crash window; explain reconstruct-from-log; explain
  resume as (log,state) divergence.
- (b) Target: **4/5**.
- (c) Gets there. Note the lab depends on a real `agentxp resume` working on a
  hand-corrupted dir; if resume's 8-case detection is brittle the lab may
  frustrate — worth a "expected output" block like the other labs have.

### Module 7 — Build history & judgment
**Goal met?** Yes, and this is the most *distinctive* module — judgment about
what not to build is genuinely rare to teach. The gap register, the four-wave
plan, and the three keep-vs-cut lessons are strong.

**Pacing.** Slightly slow in places because it leans on long block-quotes from
the source docs (L24, L104, L108, L122, L127). Quoting the audit verdict once is
right; quoting five separate passages turns the module into a reader's-digest of
`SYSTEM_AUDIT.md` rather than a synthesis. Trim to the 2–3 load-bearing quotes
and paraphrase the rest.

**Voice.** **L27 "Sit with 'green-but-broken.'"** — this is the sermonizing
imperative the brief flagged. An expert does not need to be told to sit with
something. State the lesson, don't instruct the reader's emotional posture.
"the most self-aware passage in the whole repo" (L123) and "Judgment under
revision, shown working" (L129) lean toward admiring the docs rather than
teaching from them.

**Telling vs showing.** The argument-based labs (A/B/C) are good for this
module's content (judgment can't be unit-tested). But Exercise framing tells the
"win condition" up front, which removes the reader's chance to construct it —
consider hiding the win condition until after they attempt.

**Confidence calibration.**
- (a) Explain "green-but-broken" via validate_chain; state the necessity
  criterion + 4 buckets + the "exported ≠ reachable" refinement; defend two
  keep-vs-cut calls as one judgment; name the current honest boundaries.
- (b) Target: **4/5** (you'll be interrogated on "why kept dead code").
- (c) Gets there. The hostile-reviewer prompt at L212–213 is the right test.

### Module 8 — Release readiness (capstone)
**Goal met?** Yes — explicitly "no new material, it's the gauntlet," and it
delivers a demo script + 18-question interrogation + checklist.

**Pacing.** Appropriate for a capstone. The main issue is that it re-pastes
content rather than referencing: Q1–Q3 are verbatim Module 0 (R9), and several
questions inline their "Expected:" answer (Q5, Q7, Q9, Q11, Q12, Q13, Q14, Q15,
Q16, Q17, Q18). If the point is retrieval-under-pressure, printing the expected
answer next to the question undercuts the drill — move expected answers to a
collapsible/after-section, or just cite the module (which it also does).

**Voice.** Clean and purposeful. "A public release is a promise you have to
defend in real time, usually to someone who *wants* to find the hole." (L12) —
good. No major tics.

**Telling vs showing.** This module is *all* showing (you do the demo, you
answer cold) — correct for a capstone.

**Confidence calibration.**
- (a) Drive 0→8 from memory; survive 18 hostile questions; complete the 10-item
  checklist.
- (b) Target: **5/5** (it's the certification).
- (c) Gets there *only if* the expected answers are hidden during the attempt;
  as written, the inline "Expected:" hints let a reader pass by reading, which
  over-claims the certification.

## Top 10 highest-value fixes

1. **Thin Module 1's `_commit_stage` section to 3 lines + forward-ref Module 6
   (R4).** Module 6 is the home; Module 1 only needs "every stage funnels through
   `_commit_stage`, which validates → appends → advances; Module 6 traces it."
   Removes the single largest verbatim duplication.
2. **Replace the in-prose thesis restatements with one-line back-refs (R1).** In
   `02` L14–16, `03` L13, `05` L23–24, swap the full re-explanation for "(the
   thesis from Module 0: Python owns what a wrong answer corrupts)."
3. **Delete the three dramatic one-liners.** `02` L151 "The bias had nowhere to
   land."; `07` L27 "Sit with 'green-but-broken.'"; trim `04` L29's bolded "It is
   not a blockchain" to plain text. These are the brief's exact target.
4. **Cut the "you just proved X" narration in labs (telling-not-showing).** `04`
   L164 and `05` L209 — the `audit` footer and the empty `grep` are the proof;
   let them stand.
5. **State the isolation axiom once in full (Module 2), reference elsewhere
   (R3).** Trim `00` L44–47 to a one-liner pointer, and `03` L141–142 to "the
   `TreeInput` fields are the complete dependency set (Module 2's axiom as a
   type)."
6. **Consolidate the "Phase 5 stub is honest, not a bug" line (R2).** It appears
   six times. State it once (Module 6, its home) and reference it; the README and
   `01` only need "headless loop is a tracked Phase 5 stub — see Module 6."
7. **De-bold for drama, repo-wide.** Reserve bold for true terms-of-art on first
   use (`ArtifactLocked`, `_commit_stage`, invariant names). Strip bold from
   adjectives/emphasis ("**before**", "**blind**", "**lying state**" after first
   use). An O'Reilly copyedit would cut ~60% of the bold.
8. **Move the capstone's inline "Expected:" answers out of view (Module 8).** Put
   them in a separate "answer key" section so the gauntlet actually tests
   retrieval, not reading. Otherwise the cert over-claims.
9. **Collapse the two-store/G14 explanation to one home (R5).** Module 6 owns it;
   `04` L140–144 should reference Module 6 rather than re-derive "naive chaining
   breaks Invariant 1."
10. **Cut the "looking like an expert / amateurs oversell" sermon (R7).** `00`
    L73 and `05` L34. The audience *is* the expert; show the boundary-naming in
    the scope sections and let it speak.

## Voice rewrite samples

### Sample 1 — `02_agents.md` L146–151 (dramatic button + telling)
**Before:**
> Then run through to the verdict and `agentxp audit` the experiment. Confirm
> that the interpreter's committed inputs (its bundle) contain the locked rule
> and the numbers — not your plea. The plea lives in the conversation; it never
> enters the judge's context. *The bias had nowhere to land.*

**After:**
> Then run to the verdict and `agentxp audit` the experiment. Open the
> interpreter's committed bundle: it holds the locked rule and the analyzer
> numbers, and nothing else. Your "I really need this to ship" is in the
> conversation log, not the bundle — so it never reached the judge.

### Sample 2 — `07_build_history.md` L26–29 (sermonizing imperative)
**Before:**
> Sit with "green-but-broken." The tests passed. The thing the tests were
> protecting did not work. That's the single most important lesson in this
> module, and we'll trace exactly how it happened.

**After:**
> "Green-but-broken" means the tests passed while the thing they protected did
> not work. Here it happened because the flagship chain tests monkeypatched
> `validate_chain` and asserted on a hand-fabricated log the real emitters can't
> produce (§4.2). We trace exactly how below.

### Sample 3 — `04_integrity_spine.md` L160–165 (telling-not-showing in a lab)
**Before:**
> Run `agentxp audit <exp_id>`. Expected: footer reads `chain integrity: FAILED
> — parent_action_id=… not found before action_id=…` (or `duplicate action_id=…`).
> You just proved tampering is detected on every read — no hash needed, the
> *reference graph* itself is the tripwire.

**After:**
> Run `agentxp audit <exp_id>`. The footer reads `chain integrity: FAILED —
> parent_action_id=… not found before action_id=…` (or `duplicate action_id=…`).
> No content hash was involved — the reference graph alone caught the edit, and
> it's re-checked on every read.
