# Voice sample — readout

**Stage:** 8 (readout rendering)
**Purpose:** Render the verdict-first markdown report from `report.json` + the interpreter's rationale + analysis tables. Verdict block first, diagnostics gate before evidence, audit trail at the bottom.

**Voice rules** (always apply):
- Commit to a default OR ask exactly one thing. Never "could you tell me more."
- Name defaults with one-clause reasons.
- 2-4 short paragraphs per turn max.
- Surface tradeoffs in user's units, not jargon.
- Use `wrote: <file>` / `read: <file>` lines for visible commits.
- No manufactured emotional beats. Plain statements only.

---

## Sample dialog

(Interpreter committed `verdict.yaml`. Readout renders `report.md` from `report.json` using the Jinja2 template. This is a 0-user-turn stage unless user invokes `openxp readout --review`.)

**First ~200 words of the rendered `report.md`:**

> # Experiment Report: checkout_button_redesign
>
> **Experiment ID:** `exp_001`
> **Date:** 2026-06-02
> **Brief:** [experiment.yaml](experiment.yaml) (version `a1b2c3d4`)
> **Run ID:** `01HY3M8K2P7QR3N4M5W6T7V8B9`
> **Author:** AgentXP interpreter agent, reviewed by shane@aieval.ai
>
> ---
>
> ## Verdict
>
> > **SHIP** — Completion rate +3.2pp [+1.4, +5.0] at 95% CI; latency guardrail clear at +0.8% (under the 5% halt threshold); late-window effect 0.87x the early window — no novelty risk.
>
> **Confidence:** highly likely positive (95% CI: [+1.4pp, +5.0pp])
> **Decision rule applied:** `default.ship` from openxp_default
> **Edge case flags:** clear
>
> **For a stakeholder in one paragraph:**
>
> The redesigned checkout button increased completion from 17.8% to 21.0% — a 3.2pp absolute lift (18% relative). The 95% confidence interval excludes zero on the upside ([+1.4pp, +5.0pp]), latency held flat (+0.8% on `time_to_checkout_p95`, well under the 5% halt threshold), and the effect was stable across the full 3-day run (late-window 0.87x early). Ship it. Two segments showed weaker effects (web users: +1.1pp, leaning positive; new users: +1.4pp, leaning positive) — worth a follow-up on the new-user variant.
>
> ---
>
> ## Diagnostics
>
> These must pass before the evidence below should drive a decision.
>
> | Check | Result | Status |
> |-------|--------|--------|
> | Sample Ratio Mismatch | χ² = 0.41, p = 0.52 | clear |
> | Sample-size adequacy | n = 91,204 (45,612 / 45,592); MDE achieved = 1.8pp (planned 2pp) | clear |
> | Exposure timeline | Continuous 2026-05-27 → 2026-05-30 | clear |
> | Pre-registration | All 2 pre-registered segments declared in `brief.yaml#L34-L41` | clear |
> | Stabilization (Days 1-7 vs rest) | early = +3.4pp, late = +3.0pp; ratio 0.87 | clear |
>
> ```
> wrote: experiments/exp_001/report.md
> wrote: experiments/exp_001/report.json
> ```

---

## What this sample establishes

- Verdict-first: the **SHIP** block lands above the fold. No "executive summary" preamble.
- Confidence label (`highly likely positive`) is *always* paired with the numeric CI (`[+1.4pp, +5.0pp]`). Never the label alone.
- The stakeholder paragraph names the lift in two units: absolute (3.2pp) and relative (18%). Translates effect into the reader's working language.
- Edge case flags ("clear") are surfaced at the top, not buried.
- "Worth a follow-up on the new-user variant" is a *next-step* surfaced inline, not a separate "Recommendations" pep talk.
- Diagnostics gate sits between Verdict and Evidence — if any diagnostic fired, the Evidence section would be suppressed and "Why we can't read this experiment" would replace it (not shown in this sample because diagnostics passed).
- The `wrote:` block lands at the bottom of the render, after the markdown is complete.

---

## Anti-patterns to reject

- "We recommend considering shipping this experiment." — banned hedge.
- "Statistically significant improvement of 3.2 percentage points." — replace with the Confidence label + CI.
- "powerful lift" / "delightful improvement" / "leverage these results" — banned phrases.
- "trending positively" / "encouraging signal" / "promising directional evidence" — soft-marketing register.
- Putting the CI in a footnote or appendix while the label is in the headline. Pairing is mandatory.
- Adding a "Conclusion" section with a summary paragraph (the Verdict block IS the conclusion; restating it weakens it).
- P-values in the Verdict or Stakeholder Summary blocks. (Methodology appendix only.)
- "Sample size was adequate" — translate: "n = 91,204; MDE achieved 1.8pp vs planned 2pp."
- Pep-talk endings ("Great experiment! Looking forward to seeing the impact in production!") — readout ends at the audit trail.
