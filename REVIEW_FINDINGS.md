# AgentXP — Quality Review Findings (v1, one-off trial)

Five read-only review agents graded the codebase against `REVIEW_RUBRIC.md`.
Every grade cites `file:line` evidence. This document synthesizes their findings,
leads with ship-blockers, and ranks improvement hypotheses. Verification used
`.venv/bin/python` (3.13). Baseline: `1277 passed, 63 skipped` on default run.

## Scorecard

| Dim | Owner | Grade | One-line |
|-----|-------|-------|----------|
| D1 | Statistics | **Adequate** | Methods sound, but 2 HIGH edge-case bugs in `ab_tests.py` |
| D2 | Architecture | **Adequate** | Clean overall; one dead 212-line subsystem + adapter duplication |
| D3 | Security | **Weak** | SHIP-BLOCKER: `snowflake_loader.py` leaks secrets to DEBUG log |
| D4 | CLI / UX | **Weak** | `ImportError` swallowed w/o install hint; exit-code 2 collision |
| D5 | Protocol / Tests | **Adequate** | Real coverage, but one mock-asserts-mock + shallow conformance gate |
| D6 | Docs ↔ Code | **Failing** | QUICKSTART advertises commands that do not exist |

Two **Failing/Weak** dimensions (D3, D6) and one **Weak** (D4) are
release-blockers for an open-source v0.1 by the rubric's own bar.

> This is the **as-found** scorecard. After the fixes in this doc, a gate re-run
> moved D3 Weak→Strong, D6 Failing→Strong, D4 Weak→Adequate, D1 Adequate→Strong
> (no regressions). See **Post-fix re-grade** near the bottom.

---

## Ship-blockers (fix before any public release)

### SB-1 — Secret leak in the Snowflake data loader  (D3, security)
**`agentxp/data/snowflake_loader.py:56`** defines its OWN local secret set:
```python
_SECRET_KEYS = {"password", "private_key", "token", "oauth_token"}
```
`_safe_params_for_log` (`:127-132`) masks only those keys, then the masked dict
is emitted at `logger.debug(...)` (`:156-159`). It does **not** mask
`private_key_file_pwd`, `client_secret`, or `passcode` — all of which the
Snowflake connector accepts. A user who enables DEBUG logging and authenticates
with a key-pair passphrase or OAuth client secret will write that secret to the
log in cleartext.

This **contradicts** the prior remediation claim that "all local secret-key sets
were consolidated into the canonical `_SENSITIVE_KEYS`." This module was missed.

- **Failure mode:** PM/analyst turns on `--verbose`/DEBUG to debug a connection,
  pastes the log into a ticket or Slack, leaks `private_key_file_pwd`.
- **Hypothesis (H1):** Delete the local set; route this dict through the canonical
  `_redact_creds_for_log` / `_SENSITIVE_KEYS` in `agentxp/sql/adapter.py`.
  **Expected effect:** all connector-accepted secret keys masked everywhere.
  **How we'd know:** add a test asserting a connection dict containing
  `private_key_file_pwd` + `client_secret` + `passcode` produces a log line with
  no cleartext secret. Grep proves ONE canonical set remains (rubric D3 bar).

### SB-2 — Zero-variance Welch returns a false significant result  (D1, stats)
**`agentxp/stats/ab_tests.py:44-78`.** When both arms have zero sample variance
(e.g. every unit converted, or a constant metric), the pooled SE is 0, the
t-statistic is `±inf`, and the function reports `p ≈ 0` / "significant" instead
of "undefined / cannot test." A non-statistician sees a confident win on
degenerate data.

- **Failure mode:** early test with tiny n where one arm is all-1s / all-0s →
  the tool declares a winner from noise-free-but-information-free data.
- **Hypothesis (H2):** guard `pooled_se == 0` (and `n<2` per arm) → return a
  result flagged `undefined` with a human message, not a p-value.
  **How we'd know:** unit test with two constant arms asserts `undefined`, not
  `significant`; cross-check a normal case still matches `scipy.stats.ttest_ind`
  with `equal_var=False`.

### SB-3 — Welch t-statistic sign is inverted vs. the reported difference  (D1, stats)
**`agentxp/stats/ab_tests.py:44`.** The `t_stat` sign does not agree with the sign
of the reported `(treatment − control)` difference. The p-value (two-sided) is
unaffected, but any consumer reading the t-stat direction — or a future one-sided
test — gets the lift direction backwards.

- **Hypothesis (H3):** fix the numerator ordering so `t_stat` and `diff` share a
  sign. **How we'd know:** property test: `sign(t_stat) == sign(mean_t − mean_c)`
  across randomized inputs.

### SB-4 — QUICKSTART documents commands that do not exist  (D6, docs)
**`docs/QUICKSTART.md:20,29,34,75,83,100,101,113,160`** shows, as runnable bash,
slash-style invocations the CLI does not expose:
`agentxp /experiment`, `agentxp brief`, `agentxp /analyze`, `--override-srm`,
`agentxp /readout`. A first-run user copy-pastes line 20 and gets an
argparse error on their first command.

- **Hypothesis (H4):** regenerate QUICKSTART from the actual `SUBCOMMANDS` table;
  add a docs-conformance test that greps every fenced `agentxp …` line against
  the registered subcommands and fails CI on drift.
  **How we'd know:** the test passes only when every documented command parses.

---

## Weak / worth-fixing (not blockers, but bite real users)

### W-1 — `ImportError` for optional adapters becomes a dead-end message  (D4)
**`agentxp/cli/connect_common.py:231-234`.** The live-probe path catches the
optional-dep `ImportError` and collapses it to `"probe failed: ImportError"`,
with no `pip install agentxp[snowflake]` hint. The rubric's D4 bar is explicit:
optional-dependency absence must yield an install hint, not a traceback/opaque
error.
- **H5:** map the ImportError to the same install-hint string the adapters use
  elsewhere. Test: probe with the extra uninstalled asserts the hint text.

### W-2 — `EXIT_WARNING = 2` collides with argparse's exit code  (D4)
**`agentxp/cli/exit_codes.py:16`.** argparse exits `2` on usage errors. A script
that treats exit 2 as "ran with warnings" cannot distinguish that from "bad
flags." Exit codes should be unambiguous.
- **H6:** move `EXIT_WARNING` off 2 (e.g. 3) and document the table. Test the
  mapping; grep callers for hardcoded `2`.

### W-3 — `--verbose` raw-exception interpolation in preview  (D4/D3 minor)
**`agentxp/sql/preview.py:37`** interpolates `{e}` raw into output. Low risk
today (driver text), but it's the class of line that leaks detail; route through
the redactor for consistency.

### W-4 — Snowflake `bytes_scanned` reads a private attr; its test is circular  (D5)
**`agentxp/sql/snowflake_adapter.py:129-151`** reads `cursor._stats` (private,
undocumented; brittle across connector versions). **`tests/sql/test_snowflake_adapter.py:268`**
asserts `4096` only because the fake cursor sets `_stats` — the test proves the
mock, not the adapter (mock-asserts-mock, a rubric D5 anti-pattern).
- **H7:** prefer the public `SnowflakeCursor.query_result` / result metadata for
  bytes; if `_stats` must stay, add a real (Tier-B, credential-gated) assertion
  and downgrade the Tier-A test to "does not crash."

### W-5 — Shallow cross-adapter conformance gate  (D5)
**`tests/sql/_adapter_contract.py:56-77`** checks only `isinstance` +
`get_dialect()`. It does not assert `AdapterResult`/`PreviewResult` *shape parity*
or consistent error-mapping across adapters — the actual D5 goal.
- **H8:** extend the contract to assert identical result fields and that each
  adapter maps auth/timeout/over-scan to the same exception types. The new
  `tests/integration/test_adapter_matrix.py` already proves data parity; this
  closes the structural/error half. (Strong: keep that matrix file.)

---

## Architecture (D2) — clean, with two specifics

### A-1 — Dead schema-versioning subsystem  (212 lines, zero non-test callers)
**`agentxp/schemas/_versioning.py`** is a full migration framework with no
runtime caller. **`agentxp/cli/migrate_state.py`** is a no-op stub and `migrate`
is not in `SUBCOMMANDS`. This is exactly the "TODO landmine / half-finished
implementation" the rubric flags.
- **H9:** either wire it up (register `migrate`, give it a real job) or delete it
  + the stub. Deleting is the lower-risk default for v0.1.
  **How we'd know:** grep confirms no callers before deletion; suite stays green.
  **Decision (2026-05-28):** kept as an intentional v0.5+ reservation — see A-1
  resolution at the bottom of this doc.

### A-2 — Adapter duplication that could be shared
The four adapters repeat connection/error-mapping scaffolding. Not urgent, but a
named candidate for a shared base helper once a 5th adapter appears. Do NOT
abstract preemptively (rubric: no premature generality).

---

## What's strong — do NOT churn these
- **Stats core** (`agentxp/stats/*`): Welch/proportions/ratio/Fisher/CUPED/
  sequential/Bayesian/SRM verified against scipy/statsmodels on normal inputs;
  the bugs above are edge-case guards, not method errors. Keep the methods.
- **Canonical redactor** (`agentxp/sql/adapter.py` `_redact_creds_for_log` +
  `_SENSITIVE_KEYS`): the right design — SB-1 is a module that bypasses it, not a
  flaw in it. Fix by routing TO it.
- **Two-tier test discipline** + the new `tests/integration/test_adapter_matrix.py`
  always-on DuckDB leg: real cross-adapter data parity without live creds.
- **Packaging** (post-fix `pyproject.toml` / `requirements.txt`): clean-room
  core-only install + all-subcommand smoke + adapter degradation all pass.

---

## Ranked hypothesis backlog (the deliverable)

| Rank | ID | Change | Risk | Signal it worked |
|------|----|--------|------|------------------|
| 1 | H1 | Route `snowflake_loader` through canonical redactor | Low | new secret-leak test passes; one `_SENSITIVE_KEYS` |
| 2 | H2 | Guard zero-variance / n<2 Welch → `undefined` | Low | constant-arm test returns undefined; scipy parity holds |
| 3 | H4 | Regenerate QUICKSTART + docs-conformance CI test | Low | every documented `agentxp …` line parses |
| 4 | H3 | Fix Welch t-stat sign | Low | `sign(t)==sign(diff)` property test |
| 5 | H5 | Install-hint on optional-adapter ImportError | Low | probe-without-extra asserts hint |
| 6 | H8 | Deepen conformance gate (shape + error parity) | Med | contract asserts identical fields + error types |
| 7 | H9 | Delete (or wire) `_versioning.py` + migrate stub | Low | no callers; suite green |
| 8 | H6 | Move `EXIT_WARNING` off 2 | Low | exit-code table test |
| 9 | H7 | Public bytes_scanned source; de-circular the test | Med | Tier-B real assertion |
| 10 | W-3 | Redact `preview.py:37` interpolation | Low | redactor covers it |

---

## Resolution log (this session)

The four ship-blockers were fixed and verified; suite went 1277 → 1280 passed
(3 new regression tests), 63 skipped, 0 fail.

- **SB-1** — `snowflake_loader.py` local `_SECRET_KEYS` deleted; `_safe_params_for_log`
  now delegates to the canonical `_redact_creds_for_log`. Added `passcode` +
  `oauth_token` to `_SENSITIVE_KEYS` (adapter.py). New test
  `test_safe_params_masks_all_connector_secrets` asserts password / private_key /
  private_key_file_pwd / client_secret / passcode / oauth_token / token all mask.
- **SB-2** — zero pooled-SE Welch now returns `error: "Zero variance in both
  groups; t-test is undefined."` with `significant=False` and no p-value. Test
  `test_zero_variance_both_groups_is_undefined`.
- **SB-3** — Welch arg order swapped to `ttest_ind(treatment, control)` so
  `t_stat` shares the sign of `diff`; two-sided p-value unchanged (verified equal
  to scipy). Test `test_t_stat_sign_matches_diff`.
- **SB-4** — QUICKSTART rewritten to the true v0.1 model: shell CLI (`$`) vs.
  in-Claude-Code slash commands (`>`); removed non-existent `agentxp /experiment`,
  `agentxp brief`, `agentxp /analyze`, `agentxp /readout`, `--override-srm`,
  `--justification`. `experiment.py` argparse `prog` fixed `/experiment` →
  `experiment`. README verified clean (no command lines).

Second pass (this session, after the blockers):

- **W-1** — `live_probe` (`connect_common.py`) now catches `ImportError` on both
  the construct and probe paths and surfaces the adapter's curated, credential-
  free install hint (`pip install 'agentxp[snowflake]'`) instead of collapsing
  it to "probe failed: ImportError". Two new tests (probe path + construct path).
- **W-2** — exit-code-2 ambiguity resolved at the dispatcher, not by renumbering
  the spec constant: argparse raises `SystemExit(2)` on usage errors while real
  warnings are *returned* as `EXIT_WARNING`. The dispatcher normalizes the
  raised 2 to `EXIT_USER_ERROR`; returned 2 passes through. Documented in
  `exit_codes.py`; two new dispatcher tests. (Kept `EXIT_WARNING = 2` per §1.8.)
- **H4 (second half)** — added `tests/docs/test_docs_conformance.py`: parses
  fenced code blocks in README / QUICKSTART / snowflake-setup and asserts every
  `agentxp <subcommand>` resolves to a registered subcommand or top-level flag.
  Proven non-tautological (flags the old `/experiment`, `brief`, `/analyze`).

Suite: 1287 passed, 63 skipped, 0 fail.

Third pass (this session):

- **W-3** — `preview.py` now routes the caught dry_run exception through
  `redact_message(e)` instead of raw `{e}` interpolation, so the review-screen
  warning can't echo creds/SQL embedded in a driver message.
- **W-4** — kept `cursor._stats` as the pragmatic bytes source (the documented
  alternative, a `QUERY_HISTORY` round-trip, doubles request cost), but replaced
  the single mock-echo assertion with direct branch tests of
  `_extract_bytes_scanned`: all three key spellings → value; non-int / missing
  key / non-dict / no attribute → honest `None`. Plus a behavioral test that the
  adapter reports `None` (not 0) when the connector omits stats. The live Tier-B
  real-bytes assertion still needs credentials and is deferred.
- **W-5** — deepened `_adapter_contract.py` beyond isinstance + get_dialect:
  `assert_protocol_signature_parity()` compares `inspect.signature` of all five
  Protocol methods across all four adapters (catches the interchangeability gap
  `@runtime_checkable` misses — verified all four are currently identical), and
  `assert_result_models_canonical()` pins the `AdapterResult`/`PreviewResult`
  field sets. Cross-adapter *error-mapping* parity (auth/timeout/over-scan)
  still needs live drivers and is deferred to the integration matrix.

Suite: 1298 passed, 63 skipped, 0 fail.

Resolved by product decision:

- **A-1** — `agentxp/schemas/_versioning.py` (212 lines) + `cli/migrate_state.py`
  (no-op stub, not in `SUBCOMMANDS`, so unreachable) are dead at runtime. Decision
  (2026-05-28): **keep both** — they are explicitly reserved for the v0.5+ schema
  bump and `_versioning.py` carries tests. This is an accepted, intentional forward
  reservation, not unaccounted-for dead code; the review correctly flagged it and
  the owner consciously chose to retain it. No code change.

## Post-fix re-grade (gate re-run, 2026-05-28)

Re-graded each dimension against `REVIEW_RUBRIC.md` after the fixes, with fresh
evidence (not the resolution log). Suite green at `1298 passed, 63 skipped`.

| Dim | Before | After | Evidence the bar is now cleared |
|-----|--------|-------|---------------------------------|
| D1 | Adequate | **Strong** | `ab_tests.py:57` zero-SE guard → `undefined`; `:77` t-stat sign matches `diff`; `:36` n<2 already guarded. Two HIGH bugs closed; methods unchanged. |
| D2 | Adequate | **Adequate** | A-1 reclassified as an intentional v0.5+ reservation (owner decision); A-2 correctly NOT abstracted. No new dead code. |
| D3 | Weak | **Strong** | `grep` confirms ONE `_SENSITIVE_KEYS` literal (`adapter.py:96`); the four SB-1 keys (`client_secret`/`private_key_file_pwd`/`passcode`/`oauth_token`) all present; `snowflake_loader` delegates to canonical. No surviving local set. |
| D4 | Weak | **Adequate** | `connect_common` surfaces the curated install hint on `ImportError`; dispatcher disambiguates argparse-2 from `EXIT_WARNING`. Happy path now matches the rewritten QUICKSTART. |
| D5 | Adequate | **Adequate** | W-4 de-circularized (`_extract_bytes_scanned` branch tests + None-when-omitted); W-5 added signature + result-model parity locks. Named open gap: cross-adapter *error-mapping* parity still needs live drivers. |
| D6 | Failing | **Strong** | `tests/docs/test_docs_conformance.py` ratchets every `agentxp <cmd>` in the docs against `SUBCOMMANDS`; QUICKSTART rewritten; proven non-tautological. |

Two Weak/Failing release-blockers (D3, D6) cleared to Strong; D4 cleared to
Adequate. No dimension regressed. Per the rubric (ratchet, not maximize), this
clears the v0.1 bar.

Residual (tracked, not blockers):
- **D5 error-mapping parity** — auth/timeout/over-scan exception parity across
  the three live adapters; needs credentials (Tier-B). Deferred to the
  integration matrix.
- **W-4 real-bytes** — Tier-B assertion that Snowflake `bytes_scanned` reflects
  a real scan; needs credentials.
- **Minor (new, this re-grade):** `tests/test_snowflake_loader.py:183` emits a
  `DeprecationWarning` — `load_experiment(where=...)` uses a deprecated param;
  migrate the internal call to `filters=`. Cosmetic; not graded.

## Pass-2 — independent blind re-run of the loop (2026-05-28)

Five fresh review agents graded the post-fix codebase against the rubric, **not
given this document** (no anchoring on prior findings or my re-grade). They
independently confirmed every pass-1 fix held — AND corrected my own optimistic
post-fix re-grade on three dimensions. This is the loop catching the orchestrator.

| Dim | Pass-1 as-found | My re-grade | Pass-2 blind | What blind review caught that I missed |
|-----|-----------------|-------------|--------------|----------------------------------------|
| D1 | Adequate | Strong | **Adequate** | mSPRT over-conservative, Pocock shape, Bayesian prior, mislabeled CI — I only re-checked basic Welch |
| D2 | Adequate | Adequate | **Adequate** | `agentxp migrate` recommended but unregistered (stranding); circular import |
| D3 | Weak | Strong | **Weak** | reproduced password leak via `snowflake_loader` *exception* path — SB-1 only fixed the *log* path |
| D4 | Weak | Adequate | **Strong** | (better than I credited) |
| D5 | Adequate | Adequate | **Adequate** | no cross-adapter error-mapping *parity* test; 2 near-tautological truncation tests |
| D6 | Failing | Strong | **Adequate** | `/unlock` doc example missing required arg; warehouse-status framing self-contradicts |

**Lesson:** my re-grade graded "did I fix the named findings," not "is the
dimension clean." Grading against the closed tickets is Goodhart; the blind
re-run against the rubric is the real ratchet. D3/D6/D1 were not actually Strong.

### New findings, verified by me before recording

**P2-SB-1 (D3, NEW ship-blocker) — `snowflake_loader` leaks creds via the
exception path.** `agentxp/data/snowflake_loader.py:162` (`connect(**params)`)
and `:208` (`cursor.execute`) run with no credential-scrubbing except handler —
only `finally: cursor.close()`. A driver `OperationalError`/`DatabaseError` can
echo `account`/`user`/`password` and propagates uncaught. This **contradicts the
file's own line-18 docstring** ("Credentials are NEVER ... included in exception
messages") and **violates the standing engagement constraint** (no secret in
exception messages). SB-1 fixed only the `logger.debug` dict in this same file
(`:158-161` uses `_safe_params_for_log`) — it never wrapped connect/execute. The
sibling `SnowflakeAdapter._connect` scrubs correctly; the loader is the
unprotected twin. *Verified: connect/execute paths read, no scrubbing except;
docstring promise read.*
- **Fix:** wrap connect/query/_check_row_count/_query_parameterized to re-raise
  with `type(e).__name__` (mirror `SnowflakeAdapter`), or route the loader
  through `SnowflakeAdapter` so there is one connect path. **How we'd know:** a
  test that raises a creds-bearing driver error and asserts no secret in the
  re-raised `str(e)` / caplog (mirror the BLOCKER-1 adapter leak tests).

**P2-1 (D2) — unreachable `migrate` recovery command.** `migrate` is NOT in
`SUBCOMMANDS` (`cli/__main__.py:22-30`), yet `cli/resume.py:124` and
`schemas/_versioning.py:198` tell users to "Run `agentxp migrate state <exp_id>`"
— which exits 1 `unknown subcommand`. The recovery path the kept v0.5+ versioning
subsystem promises is a dead end *today*. `cli/migrate_metrics.py` is a real,
tested 127-line tool that is also unreachable. *Verified by grep.* Ties to the
A-1 keep decision: the reserved code is not inert — it emits guidance to a
missing command. **Fix options:** (a) register a `migrate` router
(state→`migrate_state.main`, metrics→`migrate_metrics.main`); or (b) soften the
two messages so they don't name an unrunnable command until v0.5.

**P2-2 (D1, all conservative — no false positives):**
- mSPRT severely over-conservative (`stats/sequential.py:99-105`): simulated
  Type I = 0.0, always-valid CI ~2.7× fixed-horizon width at N=5000 → wasted
  traffic, false "no effect". Fix to canonical Howard GAVI radius.
- Pocock boundaries increasing, not constant (`sequential.py:343-345`): FWER
  still controlled (0.034) so safe, but contradicts the labeled method.
- Bayesian `normal_normal` NIG prior isn't the documented Student-t(n-1)
  (`bayesian.py:367-368`): CIs ~4-5% too tight at small n; docstring overclaims.
- CI comment says "Agresti-Caffo" but code is plain Wald (`ab_tests.py:195`).

**P2-3 (D5, creds-free — corrects my deferral):** the cross-adapter
error-mapping parity gap I deferred as "needs live creds" is testable WITH FAKES
— inject a fake raising each driver's auth/timeout error and assert all four map
to the same AgentXP exception type. Plus 2 near-tautological truncation tests
(`test_snowflake_adapter.py:337`, `test_databricks_adapter.py:305`): the fake
holds 1 row so `max_rows=1` proves nothing.

**P2-4 (D6):** `/unlock` README example (`README.md:113`) omits the required
`<exp_id>`; README says "DuckDB only, warehouses in v0.1.1" yet
`agentxp connect snowflake` is live while `profile --adapter snowflake` says
"ships in W_sql" — reconcile the framing; install-hint string drift across 3
sites.

**P2-5 (D3, latent/minor):** `profile.py:243/254/291` raw `{e}` +
`traceback.print_exc()` — dormant (warehouse profiling is NotImplemented) but a
live leak the moment it ships; `connect_bigquery.py:112` echoes a JSON fragment;
`databricks` extra omits `databricks-sdk` so the M2M OAuth path ImportErrors.

### What pass-2 independently confirmed is strong
Single canonical `_SENSITIVE_KEYS` (grep-verified no drift); the four adapters'
redact-then-`type().__name__` exception discipline; the BLOCKER-1 credential-leak
test suite (plants a secret in the driver exception, asserts it's scrubbed); the
signature + result-model parity harness; Python-computed integration goldens;
the zero-variance/n<2 stats guards; the exit-code design + argparse-2
normalization; the QUICKSTART `$`/`>` convention. All core stats methods
(Welch/proportions/ratio/Fisher/SRM/corrections/power/Bayesian/guardrail)
re-verified against scipy/statsmodels ground truth.

### Pass-2 resolution log (2026-05-28) — all findings fixed

Every pass-2 finding above is now fixed. Grouped commits; full suite green
(1312 passed, 63 credential-gated skips) on `.venv` Python 3.13.

- **P2-SB-1 (D3) — RESOLVED.** `snowflake_loader.py` connect/query/row-count/
  parameterized paths now route through a `_reraise_clean` helper that re-raises
  with `type(e).__name__` only, mirroring `SnowflakeAdapter`. New tests plant a
  creds-bearing driver error and assert no secret in `str(e)`/caplog.
- **P2-1 (D2) — RESOLVED.** Registered a `migrate` router (`cli/migrate.py`,
  wired into `__main__.py` SUBCOMMANDS) dispatching `state`→`migrate_state` and
  `metrics`→`migrate_metrics`, so the guidance strings now resolve. Dispatcher
  tests added.
- **P2-2 (D1) — RESOLVED.** mSPRT radius corrected to the canonical Howard
  normal-mixture form `radius² = 2·σ²·denom/(n_eff²·τ²)·log(√(denom/σ²)/α)` with
  the matching e-value exponent (`n_eff²`); docstring rewritten with the full
  derivation. Verified: Type-I under peeking 0.013 (≤α), power@0.3 = 1.0,
  radius/e-value decisions agree on 3000 sims. Pocock/OBF docstring now honestly
  describes the independent-increment spending approximation (Pocock drifts mildly
  upward, not exactly constant). Bayesian NIG prior comment corrected — it is a
  *proper* InverseGamma(0.5,0.5) weakly-informative prior, NOT Jeffreys.
  `ab_tests.py` CI comment corrected from "Agresti-Caffo" to unpooled Wald, with
  the AC trade-off documented.
- **P2-3 (D5) — RESOLVED.** Added `tests/sql/test_adapter_error_parity.py`:
  creds-free fakes inject each driver's auth/timeout error and assert all
  adapters map to the same `AuthExpiredError`/`QueryTimeoutError`, plus a planted
  secret never leaks. De-tautologized the two truncation tests (seed 10 rows,
  `max_rows=3`, assert `fetchmany` got 3).
- **P2-4 (D6) — RESOLVED.** README `/unlock` example now includes `<exp_id>`;
  warehouse-status framing reconciled (profiles can be registered; reading from a
  warehouse ships in v0.1.1); install-hint string normalized to the quoted
  `pip install 'agentxp[...]'` form across loader + docs.
- **P2-5 (D3) — RESOLVED.** `profile.py` routes all unexpected-error output
  through one `_print_unexpected_error` seam (redactor-scrubbed message + verbose
  traceback); `connect_bigquery.py` invalid-JSON path raises a generic message
  `from None` (no secret fragment); `databricks` extra now ships `databricks-sdk`.

## Verdict on the review process itself
The trial produced what it was meant to: a security ship-blocker the prior
remediation report had wrongly claimed fixed (SB-1), two real statistical
edge-case bugs with reproducing conditions (SB-2/SB-3), a Failing docs grade with
nine exact line cites (SB-4), and a ranked, testable hypothesis backlog. Every
finding carries `file:line` evidence and a "how we'd know it worked" check.
That is strong enough to justify keeping the rubric and re-running it as a gate.
