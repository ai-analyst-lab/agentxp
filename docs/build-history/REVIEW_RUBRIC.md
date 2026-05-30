# AgentXP — Quality Review Rubric (v1, one-off trial)

A shared standard for grading the agentxp codebase. Five review agents each
grade the dimensions they own against the bars below. The rubric is a
**ratchet, not an objective to maximize**: the goal is to clear the bar and
never regress, and to surface honest error analysis + ranked improvement
hypotheses — not to chase a number.

## What agentxp is meant to be

An open-source, Claude-Code-native system for designing and analyzing
controlled experiments. Deterministic Python does the statistics; agentic
stages handle judgment. Target users: PMs / analysts / engineers who are NOT
statisticians, running real A/B tests against real warehouses. So the bar is:
**statistically trustworthy, safe with credentials, honest when it can't do
something, and legible to a non-expert.**

## Grading scale (per dimension)

- **Strong** — clears the bar; no action needed beyond polish.
- **Adequate** — clears the bar but has named weaknesses worth a hypothesis.
- **Weak** — partially clears; at least one issue that would bite a real user.
- **Failing** — does not clear; a ship-blocker for an open-source release.

Every grade MUST cite `file:line` evidence. A grade with no evidence is invalid.

## Required output from every agent

1. **Per-dimension grade** (Strong/Adequate/Weak/Failing) with cited evidence.
2. **Error analysis** — for each weakness, the failure mode: what breaks, for
   whom, under what conditions. Not "this could be better" — "a user doing X
   hits Y because of Z at file:line."
3. **Improvement hypotheses** — ranked. Each: the change, the expected effect,
   and how we'd know it worked (the metric/check that would move). This is the
   part the review is judged on.
4. **What's strong** — name what should NOT be touched, so we don't churn it.

Agents are **read-only**: do not edit code, do not commit. Findings only.
Use `.venv/bin/python` for any verification. Repo: `/Users/shanebutler/projects/agentxp`.

---

## Dimensions & bars

### D1 — Statistical correctness (owner: stats agent)
Goal: a non-statistician can trust the numbers. Bar:
- Each test (Welch, proportions, ratio, Fisher, CUPED, sequential/mSPRT,
  Bayesian, guardrail non-inferiority, SRM, corrections) implements a method
  that matches its standard definition; assumptions are stated.
- Numerical stability: no naive variance, no catastrophic cancellation, correct
  handling of n=0/1, zero variance, perfect separation, tiny/huge effect sizes.
- Multiple-comparison and sequential-testing math is sound (no peeking-inflation
  unless the always-valid machinery actually controls it).
- Outputs (p-values, CIs, power) are internally consistent and labeled with
  their assumptions. Verify a few against scipy/statsmodels ground truth.

### D2 — Architecture & code quality (owner: architecture agent)
Goal: a contributor can navigate and extend it without a map. Bar:
- Abstractions earn their keep; no premature generality, no copy-paste that
  should be shared, no shared thing that should be copy-paste.
- Coupling is sane; modules have clear responsibilities; no circular-import
  hacks or god-modules.
- No dead code, no half-finished implementations, no TODO landmines.
- Error handling is at boundaries, not scattered defensively; failures are
  specific exception types, not bare `except`/`raise Exception`.

### D3 — Security & credential safety (owner: security agent)
Goal: it is hard to leak a secret even by accident. Bar:
- Every credential routes through the canonical redactor before any
  log/exception/audit/terminal output. No secret in an exception message.
- `_SENSITIVE_KEYS` is complete and there is ONE canonical set (no drift).
- Profile files are written chmod 600; secrets collected no-echo; env:VAR
  references preferred over raw secret writes.
- Packaging: every imported runtime dep is declared at the right tier (core vs
  optional extra); a clean-room `pip install` of any documented path works;
  install hints are correct.

### D4 — CLI / UX & error ergonomics (owner: cli/ux agent)
Goal: a non-expert is never stranded by a traceback. Bar:
- Every subcommand has clear help; required args validated with actionable
  messages; exit codes are meaningful and consistent.
- Optional-dependency absence yields an install hint, not a traceback.
- Error messages tell the user what to DO next, in their language, not the
  driver's.
- The happy path (connect → profile → experiment → audit) is walkable without
  reading source.

### D5 — Protocol conformance & test quality (owner: protocol/test agent)
Goal: the four adapters are interchangeable and the tests actually prove it. Bar:
- All adapters satisfy `BaseAdapter`; `AdapterResult`/`PreviewResult` shapes are
  identical; error-mapping (auth/timeout/over-scan) is consistent across them.
- Tests are meaningful, not tautological (no mock-asserts-the-mock); critical
  paths (stats, redaction, dispatch, transpile) have real coverage.
- Tier-A (mock, always-on) vs Tier-B (credential-gated, skips clean) discipline
  holds; CI is green with zero credentials.
- The integration matrix proves cross-adapter parity to the extent possible
  without live creds.

### D6 — Docs ↔ code accuracy (owner: cli/ux agent, secondary)
Goal: nothing in README/QUICKSTART is a lie. Bar:
- Every command, flag, install path, and code snippet in README.md /
  docs/QUICKSTART.md / docs/snowflake-setup.md actually works as written.
- No references to removed/renamed things; no aspirational features documented
  as if they exist.
