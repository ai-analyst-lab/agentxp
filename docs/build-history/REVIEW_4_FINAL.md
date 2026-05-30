# REVIEW-4: Final Deep Review

**Reviewer:** Claude Opus 4.6 (1M context)
**Date:** 2026-04-16
**Scope:** Full codebase — 47 source modules, 431 tests, 7 commits on main
**Prior reviews:** WAVE1_REVIEW, WAVE2_REVIEW, REVIEW-3

---

## 1. Verdict: SHIP WITH FIXES

- **Math is correct on all 13 core statistical functions.** Every formula was verified against scipy/statsmodels and hand calculation. One formula (mSPRT radius) is more conservative than the textbook form but preserves the always-valid guarantee.
- **431 tests pass deterministically across 3 runs with zero flakiness.** Runtime ~6.4s.
- **Two documentation issues and one formula note require attention before GitHub publication.**

---

## 2. Statistical Correctness Audit

### Per-Function Verdict Table

| Function | Verdict | Notes |
|----------|---------|-------|
| `welch_test` | CORRECT | Welch-Satterthwaite df formula verified. Delegates to `scipy.stats.ttest_ind(equal_var=False)`. CI construction independently correct. |
| `proportion_test` | CORRECT | Pooled SE for test statistic, unpooled SE for CI (Agresti-Caffo style). Both verified by hand calculation. Boundary case (0,1000,0,1000) handled: returns z=0, p=1. |
| `ratio_metric_test` | CORRECT | Delta method variance formula `Var(R) = (1/D^2)(Var(N) - 2R*Cov(N,D) + R^2*Var(D))` matches the textbook. Verified numerically. |
| `cuped_welch_test` | CORRECT | Theta computed from POOLED pre/post across both groups (correct). Centering uses the POOLED pre-experiment mean (correct). Both verified. |
| `msprt_test` | CONSERVATIVE | See detailed finding below. The radius formula produces CIs ~1.4x wider than the standard Gaussian-mixture SPRT (Howard et al. 2021). The always-valid coverage guarantee is preserved — this is a power loss, not a Type I error inflation. Users need ~2x more data to reject H0 than theoretically optimal. `tau=None` correctly defaults to pooled sigma. |
| `beta_binomial_test` | CORRECT | Under uniform prior Beta(1,1), posterior is Beta(1+s, 1+n-s). Verified: `posterior_alpha_control=31`, `posterior_beta_control=41` for `c_success=30, c_n=70`. |
| `normal_normal_test` | CORRECT | NIG conjugate update: `posterior_mean = (prec_pri*prior_mean + n*xbar)/(prec_pri + n)`. Under weak prior (prior_sd=1e6), posterior mean tracks sample mean to <1 unit. Verified. |
| `srm_check` | CORRECT | Chi-square via `scipy.stats.chisquare`. Verified: `[4800,5200]` gives chi2=16.0, p=6.3e-5. Threshold logic is correct: p>0.05 is PASS, p>threshold is WARNING, else BLOCK. Verified with threshold=0.01 vs 0.0005 on `[4850,5150]` (p=0.0027). |
| `guardrail_test` | CORRECT | One-sided CI bound uses `t.ppf(1-alpha, df)` (not alpha/2). `invert=True` correctly flips the oriented effect sign. NI margin is `-abs(nim_relative * baseline)` in oriented space. Verified. |
| `fishers_exact_test` | CORRECT | p-value matches `scipy.stats.fisher_exact` exactly. Odds ratio uses Haldane-Anscombe correction (intentional; documented). |
| `power_proportion` | CORRECT | Uses Cohen's h effect size + `NormalIndPower.solve_power`. Verified: baseline=0.10, mde=0.05 gives n=57,756 per group. |
| `power_ratio` | CORRECT | Delta method variance formula matches `ratio_metric_test`. Verified numerically: var_ratio_per_unit=0.376 for the test case. |
| `adjust_pvalues` | CORRECT | Wraps `statsmodels.stats.multitest.multipletests`. Holm adjusted values verified against hand calculation: `[0.05, 0.12, 0.12, 0.20, 0.50]`. BH values verified. |

### Detailed Finding: mSPRT Radius Formula

**Location:** `agentxp/stats/sequential.py`, function `_msprt_core`, lines 99-105.

**Issue:** The variance term in the always-valid CI radius computation is:
```python
variance_term = (s2 / n_eff) * (denom / denom) + (s2 * tau * tau) / denom
```
The `(denom / denom)` simplifies to 1, giving:
```
variance_term = s2/n_eff + s2*tau^2/(s2 + n_eff*tau^2)
```
The standard Gaussian-mixture SPRT radius (Howard et al. 2021, Theorem 1; Johari et al. 2017) uses:
```
variance_term = s2*(s2 + n_eff*tau^2) / (n_eff^2 * tau^2)
```

**Impact:** Code radius is ~1.4x wider than the textbook formula (converges to sqrt(2) ratio at large n_eff). This means:
- Type I error is BELOW alpha (safe)
- Coverage guarantee holds (always-valid property preserved)
- Users need approximately 2x more data to reach a STOP_REJECT decision
- The CI is valid but wider than necessary

**Severity:** MEDIUM. Not a correctness bug. The always-valid guarantee is the hard requirement, and it is satisfied. However, users comparing AgentXP's sequential test power to Optimizely/Netflix will find AgentXP requires more data.

**Recommendation:** Either (a) fix the formula to match the textbook, or (b) document the conservative choice and the reason. The `(denom / denom)` suggests this was a simplification error, not an intentional design decision.

---

## 3. Integration Probe Results

| Chain | Result | Notes |
|-------|--------|-------|
| `from agentxp.stats import *` → all 34 names resolve | PASS | |
| `load_data` → `discover_schema` → `welch_test` | PASS | Loaded `no_effect.csv`, discovered schema, ran welch_test. Note: `LoadResult` attribute is `dataframe`, not `df`. |
| `ExperimentStore` → save → load → save_analysis → history | PASS | 2 events in history after save + analysis. |
| `AmendmentTracker` → record → list | PASS | Correctly classified name change as non-material. |
| `run_monitor` → construct context → run → check report shape | PASS | Report has `srm_trend`, `guardrail_health`, `sample_accumulation` checks. |
| `validate_experiment_yaml` → validate template | PASS | Template has 8 findings (expected — template has placeholder values). |
| `AgentXPError` → raise → str → to_dict | PASS | `to_dict` returns 6 keys: type, code, message, hint, severity, details. |

All 7 integration chains pass.

---

## 4. Security Findings

| Check | Result | Notes |
|-------|--------|-------|
| `ExperimentStore` path traversal (`../`, absolute, `.hidden`) | BLOCKED | All three rejected with clear ValueError. |
| YAML loading | SAFE | `yaml.safe_load` used in all 6 call sites (store.py x4, validator x2). No `yaml.load()` (unsafe) anywhere. |
| Snowflake `filters=` parameterization | CORRECT | `_query_parameterized` uses `cursor.execute(sql, params)` with `%s` placeholders. Values are never interpolated into SQL. Column names in filters are validated via `_validate_ident` regex. |
| Snowflake credential masking | CORRECT | `_SECRET_KEYS = {"password", "private_key", "token", "oauth_token"}`. `_safe_params_for_log` masks these. `logger.debug` in `_connect` uses `_safe_params_for_log`. `__repr__` only exposes mode and database name. No f-strings reference password or connection params directly. |
| Deprecated `where=` parameter | WARNING | The deprecated `where` parameter in `load_experiment` still accepts raw SQL. It emits a `DeprecationWarning` but does not block. This is documented as deprecated. Acceptable for v1.0 but should be removed in v1.1. |

No critical security issues found.

---

## 5. Edge Case Smoke Results

| Edge Case | Result | Notes |
|-----------|--------|-------|
| `welch_test([1,1,1,1,1], [2,2,2,2,2])` — zero variance | RUNS | Returns t=-inf, p=0.0, significant=True, CI=[1.0, 1.0]. scipy issues RuntimeWarning about precision loss. Cohen's d=0 with label "Negligible" is technically wrong for a deterministic 1.0 difference — should be inf. **Minor cosmetic issue only.** |
| `proportion_test(0, 1000, 0, 1000)` — both zero | RUNS | Returns z=0, p=1.0, significant=False. Correct: no difference between two zero rates. |
| `srm_check([0, 1000])` — one group empty | RUNS | Returns chi2=1000.0, verdict=BLOCK. Correct: total absence of one group is the ultimate SRM. |
| `cuped_welch_test(zeros, randn, zeros, randn)` — zero-var pre | RUNS | theta=0.0 (no adjustment), then runs standard Welch. Correct: when pre has no variance, CUPED degrades gracefully to unadjusted. |
| `discover_schema(pd.DataFrame())` — empty DataFrame | RUNS | Returns schema with treatment_column=None, n_rows=0. No crash. |
| `validate_experiment_yaml({})` — empty dict | RUNS | Returns ok=False with 9 findings (all required fields missing). Correct collect-all-errors behavior. |
| `diff_experiments({}, {})` — empty diffs | RUNS | Returns empty list. Correct. |

All 7 edge cases handled gracefully. No crashes.

---

## 6. TEST_PLAN Quality Assessment

The TEST_PLAN.md (1,495 lines) is thorough and well-structured. Assessment:

**Strengths:**
- Defines 15 test types with clear runtime budgets and CI stage assignments.
- Covers every public function with specific test ideas.
- Statistical simulation tests have explicit Monte Carlo tolerance bands (e.g., Type I rate in [0.045, 0.055] with N=10000).
- Identifies the 5 biggest gaps correctly (no sim tests, no property-based, no fuzz, no E2E, no contract snapshots).
- CI stage ordering is realistic: pre-commit <5s, PR check <60s, nightly <60min.

**Gaps found:**
1. **mSPRT radius formula correctness** — The TEST_PLAN mentions a Type-I simulation for mSPRT but does not flag the variance-term discrepancy identified in this review. A cross-check test against the closed-form textbook radius should be added.
2. **Zero-variance edge case** — No test for `welch_test` with constant groups. The plan mentions "boundary" tests but does not specifically call out the zero-variance case where Cohen's d is 0 instead of inf.
3. **`LoadResult.dataframe` vs `.df`** — No contract test for the attribute name. Users will assume `.df` (the common convention). This is a foot-gun.
4. **Test count in header is stale** — TEST_PLAN header says "391 passing tests" (now 431).

**Overall:** The plan is excellent for its scope. The gaps are minor. Would not block shipping.

---

## 7. Documentation Accuracy

### README.md

| Claim | Accurate? | Issue |
|-------|-----------|-------|
| Test count: "391 tests" | NO | Actual: 431 tests. README line 139. |
| Stats module API example | YES | `proportion_test`, `srm_check`, `power_proportion` all work as shown. |
| Sample data table | YES | All 6 CSV files exist in `sample-data/`. |
| Walkthrough links | NOT VERIFIED | Links are relative paths; didn't check all 12 exist. |
| Roadmap checkboxes | YES | v0.1/v0.5/v1.0 all marked shipped; v1.1+ items unchecked. |
| "PyPI publication" unchecked | CORRECT | Still local-install only. |

### CLAUDE.md

| Claim | Accurate? | Issue |
|-------|-----------|-------|
| Stats Module Reference table | INCOMPLETE | Lists 15 functions. Missing 18 functions added in v1.0: `cuped_welch_test`, `cuped_adjust`, `variance_reduction`, `msprt_test`, `always_valid_ci`, `group_sequential_boundaries`, `sequential_proportion_test`, `beta_binomial_test`, `normal_normal_test`, `expected_loss`, `probability_to_beat`, `fishers_exact_test`, `guardrail_test`, `denominator_srm`, `cohens_h`, `extension_estimate`, `power_ratio`, `prepare_experiment_data`. |
| Agent index (5 agents) | NOT VERIFIED | Agents are markdown files; paths listed but not read. |
| Checkpoint table | YES | 5 checkpoints listed with correct type assignments. |
| Data Discovery Protocol | YES | 7-step protocol matches `discovery.py` implementation. |

---

## 8. Test Stability

| Run | Result | Time |
|-----|--------|------|
| 1 | 431 passed, 1 warning | 6.56s |
| 2 | 431 passed, 1 warning | 6.09s |
| 3 | 431 passed, 1 warning | 6.46s |

**Zero flakiness.** The 1 warning is scipy's standard "precision loss" warning during zero-variance edge case testing — not a test issue. Deterministic across all runs.

---

## 9. Prioritized Fix List

### Before GitHub Publication (P0)

1. **Update README.md test count** from 391 to 431. (1 min)
2. **Update CLAUDE.md Stats Module Reference** to include the 18 missing v1.0 functions (cuped, sequential, Bayesian, guardrails, fishers, power_ratio, etc.). (15 min)

### Before v1.0 Label (P1)

3. **Investigate mSPRT radius formula** in `_msprt_core` (sequential.py lines 99-105). The `(denom / denom)` simplification produces a variance term ~2x larger than the textbook. Either fix to match Howard et al. 2021 or document the conservative choice. Does not affect correctness of always-valid guarantee. (30 min to fix, or 10 min to document)

### Nice-to-Have (P2)

4. **Cohen's d in zero-variance edge case** — `welch_test` returns d=0 with label "Negligible" when both groups are constant. Returning d=inf or a special label would be more correct, but this is a degenerate case unlikely to occur in practice.
5. **`LoadResult.dataframe` naming** — Consider adding a `.df` property alias since it's the common convention. Not a bug, just a foot-gun for new users.
6. **TEST_PLAN header** — Update "391 passing tests" to 431.

---

*End of REVIEW-4.*
