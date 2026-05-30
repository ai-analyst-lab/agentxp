# Wave 1 Independent Code Review

**Reviewer:** independent pass (no code changes)
**Commit:** `15eef82` — "wave 1: v0.5/v1.0 feature rollout"
**Scope:** `agentxp/data/`, `agentxp/stats/{cuped,sequential,bayesian}.py`, `agentxp/storage/`, `agentxp/metrics/`, skill orchestrator, 183 new tests
**Test suite:** `238 passed in 4.90s` on a clean run; Bayesian + sequential subset passed 3/3 consecutive runs with identical output (fully deterministic — seeds propagate correctly).

---

## 1. TL;DR

- **Verdict: SHIP WITH FIXES.** The Python modules are solid — math is correct under default parameters, every test case I spot-checked is asserting real behavior, state machine matches PRD Appendix B, atomic writes are genuinely atomic and covered by an interrupt test. The code reads like an extension of `ab_tests.py`, not a parallel dialect.
- **Blocker before Wave 2: the `/experiment` orchestrator skill references ~7 functions and 1 module that do not exist** (`power_ratio`, `extension_estimate`, `fishers_exact_test`, `guardrail_test`, `denominator_srm`, `cohens_h`, `agentxp.stats.prep.prepare_experiment_data`). It also advertises a `computation_trace` dict field that no Wave 1 function returns. This will break every mode except `power` and `status` the moment it runs.
- **One real math concern (non-blocking, document or fix):** `normal_normal_test` applies per-draw precision-weighted shrinkage to likelihood draws, which under-estimates posterior variance when `prior_sd` is small. Harmless at the default `prior_sd=1e6`, silently wrong for strong priors — and one test (`test_strong_prior_pulls_posterior`) is effectively locking in the buggy behavior.

---

## 2. Critical Issues (would break things)

### C1. skill.md references hallucinated functions — `.claude/skills/experiment/skill.md:154-158` and `MODES.md:102-106, 151, 164-167, 173, 233, 286, 288`
The "Stats Function Quick Reference" table and per-mode step specs name these functions that do not exist in `agentxp.stats`:

| Claimed in skill/MODES | Actually exists? |
|---|---|
| `agentxp.stats.power.power_ratio` | No |
| `agentxp.stats.power.extension_estimate` | No |
| `agentxp.stats.ab_tests.fishers_exact_test` | No |
| `agentxp.stats.ab_tests.guardrail_test` | No |
| `agentxp.stats.srm.denominator_srm` | No |
| `agentxp.stats.effect_size.cohens_h` | No |
| `agentxp.stats.prep.prepare_experiment_data` (whole module) | No |

Verified by direct import probe. These are referenced in the `analyze`, `interpret`, `monitor`, and `design` mode specs. If an agent follows MODES.md literally it will ImportError on step 2 of `analyze` and step 4 of `design`. This is the single biggest risk for Wave 2.

### C2. `computation_trace` contract is advertised but unimplemented — `skill.md:149` ("every function returns a dict with `interpretation` and `computation_trace` fields") and `MODES.md:196` ("`working/analyzer-trace.md` (per-call computation traces, D.9)")
No Wave 1 function (or pre-Wave 1 function) returns a `computation_trace` key — I grepped `agentxp/stats/` for it and got zero matches. MODES.md §`interpret` step 2 says "D.9 validation" on `computation_trace` entries, and §`analyze` step 10 says to write traces. If the orchestrator enforces this contract, the skill will reject every analysis it runs.

### C3. `agentxp/__init__.py` advertises an API it doesn't expose — `agentxp/__init__.py:11-32`
The top-level docstring shows `from agentxp.stats import welch_test, proportion_test, ...`, but `__all__` is only `["load_data", "discover_schema"]` and the root package does not re-export `stats`, `storage`, or `metrics` as attributes. `import agentxp; agentxp.stats.welch_test` fails (you have to `import agentxp.stats` explicitly). Not a blocker — the doc example still works verbatim — but a linter or `help(agentxp)` user will be confused. Also: Wave 1's new Bayesian, CUPED, and sequential APIs are not mentioned in the top-level docstring usage examples at all.

---

## 3. Math / Correctness Issues (would give wrong answers)

### M1. `normal_normal_test` per-draw shrinkage is mathematically wrong for strong priors — `agentxp/stats/bayesian.py:378-389`
```python
t_draws = rng.standard_t(df, size=n_samples)
mu_lik = xbar + se * t_draws
prec_lik = 1.0 / (se ** 2)
prec_pri = 1.0 / (prior_sd ** 2)
prec_post = prec_lik + prec_pri
shrunk = (prec_lik * mu_lik + prec_pri * prior_mean) / prec_post
return shrunk
```
`mu_lik` is already a sample from the likelihood-only posterior `t_df(xbar, se^2)`. Applying an affine transform with constant `prec_lik/prec_post` scales the draw variance by `(prec_lik/prec_post)^2`, which is NOT the correct conjugate update for Normal-Normal with unknown variance — the true posterior variance should be approximately `1/prec_post` (known-variance case) or wider (unknown-variance case with a Student-t). The implementation **under-estimates posterior variance** when `prior_sd` is small, producing CrIs that are too narrow.

At the default `prior_sd=1e6` this is harmless (`prec_pri ≈ 0`, so `shrunk ≈ mu_lik`). But the `test_strong_prior_pulls_posterior` test (`tests/test_bayesian.py:196-204`) exercises `prior_sd=0.5` and passes — locking in a subtly wrong answer.

**Suggested fix:** either (a) implement the proper Normal-Inverse-Gamma conjugate update (sample sigma^2 ~ InvGamma, then mu ~ N(precision-weighted mean, sigma^2/prec_post)), or (b) restrict this API to weak priors only and raise if `prior_sd < 10 * se`, or (c) document prominently that strong priors use a known-variance approximation and widen the CrI accordingly.

### M2. `_msprt_core` contains a dead algebraic remnant — `agentxp/stats/sequential.py:104`
```python
variance_term = (s2 / n_eff) * (denom / denom) + (s2 * tau * tau) / denom
```
`denom / denom == 1` identically. This simplifies to `variance_term = s2/n_eff + s2*tau^2/denom`. Almost certainly a half-finished factoring of `(sigma^2/n + tau^2) - (tau^4 * n_eff)/(sigma^2 + n_eff*tau^2)` from Howard et al. The Type I simulation (`tests/test_sequential.py:18-45`) passes, so this form is close enough to empirically hold the always-valid guarantee, but the code is confusing and the docstring formula above it (lines 85-96) doesn't match what's actually computed. Clean up the algebra and re-derive the closed form from Howard §3.2, or add a comment showing the simplification path.

### M3. CUPED math is correct, including the pooled-theta requirement — `agentxp/stats/cuped.py:300`
Positive verification: `cuped_welch_test` pools `control_pre + treatment_pre` before computing `theta`, matches PRD instruction. Variance reduction reported two ways (expected rho^2 and realized within-group), which is the right thing to do for teaching contexts. No issues found.

### M4. O'Brien-Fleming and Pocock boundaries are correct but approximate — `agentxp/stats/sequential.py:340-346`
The docstring honestly flags that this uses incremental spending converted to nominal z, "ignores correlation across looks", and is "a simplification". The test `test_obrien_fleming_monotone_decreasing` asserts monotonicity, `test_obrien_fleming_conservative_early` asserts z>3 at first look, `test_pocock_roughly_constant` asserts spread <0.5. These are the right assertions for the approximation used. Not a bug — just make sure any downstream decisions using these boundaries acknowledge they're approximate group-sequential, not exact Lan-DeMets.

### M5. Data discovery does NOT hardcode column names anywhere outside the hints tuple — verified
`discovery.py:20-38` defines `TREATMENT_COLUMN_HINTS`, `CONTROL_VALUE_HINTS`, `ID_COLUMN_PATTERNS`, `TIMESTAMP_NAME_PATTERNS` as module-level tuples and uses them exclusively via iteration. Grep across `agentxp/data/` for literal `'variant'`, `'conversion'`, `'revenue'` returns only the hints tuple and test fixtures. Clean.

### M6. State machine matches PRD Appendix B — verified
`lifecycle.py` enumerates all 11 states and all forward/backward transitions from PRD lines 3913-3984. One minor deviation: PRD doesn't explicitly enumerate which states can transition TO `BLOCKED`; `lifecycle.py:49-59` allows `DESIGNING`, `POWERED`, `COLLECTING` → `BLOCKED` and `BLOCKED` → back to those plus `ABANDONED`. This is a reasonable PRD extension but not explicit. Document in a comment referencing the PRD line range.

### M7. Atomic writes are actually atomic — `agentxp/storage/store.py:59-82`
`_atomic_write_bytes` uses `tempfile.mkstemp` in the same parent directory, `fsync` before rename, `os.replace` for the POSIX-atomic rename, and unlinks the tmp file on any exception. The `test_atomic_write_survives_interrupt` test patches `os.replace` to raise and verifies the original file is intact AND no `.tmp` leftover exists. This is the single best-covered piece of Wave 1.

---

## 4. Style / Convention Violations

### S1. `bayesian.py` uses `pytest`-like blank lines between top-level items inconsistently compared to `ab_tests.py` — `agentxp/stats/bayesian.py` throughout
Minor. `ab_tests.py` uses `# ---...---` block separators sparingly; `bayesian.py` uses them heavily. Not wrong, just a slightly different idiom from the exemplar.

### S2. `sequential.py` uses mixed error-return shapes — `agentxp/stats/sequential.py:145-153, 239-245`
Under insufficient data, some functions return `{"error": True, "error_type": "insufficient_data", "message": ..., "significant": False, "decision": "CONTINUE", "interpretation": ...}` and some use `{"error": "Need at least 2 observations per group"}`. `ab_tests.py` uses the second shape (`"error"` is a string). Normalize to match the exemplar, or at minimum use one shape throughout `sequential.py`.

### S3. `cuped.py:331` string-truthy check on `raw_var` — `agentxp/stats/cuped.py:331`
```python
if raw_var and not math.isnan(raw_var) and raw_var > 0:
```
`raw_var` is a float; the leading `if raw_var` short-circuits on exactly 0.0 but is redundant with `raw_var > 0`. Not wrong, just reads oddly.

### S4. `snowflake_loader.py` `where` parameter is a raw-SQL injection vector — `agentxp/data/snowflake_loader.py:270-272, 289`
Docstring honestly says "**Not validated.** Only pass trusted, static values here." That's a conscious choice, but given that the rest of the module goes to pains to validate identifiers, an agent reading MODES.md and forwarding user input to `where=...` is a realistic footgun. Consider either dropping the parameter, requiring a dict-form `filters={col: val}` that parameterizes, or raising on any single quote / semicolon.

### S5. Normal-Normal `test_null_effect` assertion is weaker than it looks — `tests/test_bayesian.py:155-159`
```python
assert 0.01 < result["prob_treatment_better"] < 0.99
assert result["lift_ci_lower"] < result["lift_ci_upper"]
```
This will pass for almost any non-pathological output. It is a "not catastrophically broken" smoke test, not a null-effect behavior test. Either tighten to `0.2 < p < 0.8` or remove the assertion about lift CI ordering (which is trivially true by construction).

### S6. `agentxp/stats/__init__.py` does not export `_decide` or `_relative_lift_samples` — **this is correct**; style positive.

---

## 5. Test Quality Issues

### T1. `test_type_i_rate_under_peeking` tolerance is borderline but defensible — `tests/test_sequential.py:18-45`
500 reps at alpha=0.05 expects ~25 rejections; test allows up to `0.05 + 0.02 = 0.07` = 35 rejections. With mSPRT's anytime-valid guarantee the true rate should be well under 0.05, so the 2% Monte Carlo slack is fine. However: the peek schedule starts at n=100 per group with 50-step peeks — if a future reviewer lowers that to n=20, the test will become flaky because the plug-in variance estimate is noisy at small n. Add a comment locking in the rationale for the peek schedule.

### T2. `test_strong_prior_pulls_posterior` locks in the M1 bug — `tests/test_bayesian.py:196-204`
This test passes because of the under-estimated posterior variance described in M1. Once the Normal-Normal math is fixed, this test may need to change to assert proper shrinkage behavior against an analytic reference. Flag it as "will need updating when M1 is fixed."

### T3. Snowflake test's `test_import_error_points_to_extras` has a latent brittleness — `tests/test_snowflake_loader.py:192-211`
Uses `__builtins__["__import__"]` dict-indexing fallback. This works in pytest's module context but can break under `python -m unittest` or direct script execution. Low-priority, but consider the cleaner `monkeypatch.setattr(builtins, "__import__", fake_import)`.

### T4. No direct test for `probability_to_beat` shape invariant at extreme n — `tests/test_bayesian.py:227-241`
Good coverage otherwise (value check, shape mismatch, empty). Consider one test with `n_samples=2` to ensure edge cases don't crash.

### T5. No test for `cuped_adjust` when all pre-values are identical (theta should go to 0) — `tests/test_cuped.py`
`_compute_theta` has an explicit `if var_pre == 0.0: return 0.0` branch at `cuped.py:67-70`, but no test exercises it. One-liner to add.

### T6. Storage test `test_store_from_env_default_not_touched` explicitly does NOT build the store to avoid mkdir-ing `~/.agentxp` — good, this is exactly the right pattern. Positive.

### T7. No test covers `ExperimentStore.save_experiment` when the existing file is corrupt YAML — `store.py:189-195`
There's an error branch for `yaml.YAMLError` on load but no test exercises it. Add a fixture that writes `{:\n[` to the yaml path and confirms `RuntimeError("corrupt")`.

### T8. Determinism positive check — 3 consecutive runs of `test_bayesian.py` + `test_sequential.py` produced byte-identical output (`54 passed in 3.41s/3.58s/3.52s`). No flakiness observed. Seeds propagate correctly across both modules.

---

## 6. Integration Risks

### I1. Wave 1 adds 3 new modules to `agentxp.stats` that agents/skills must know about, but skill.md's "Stats Function Quick Reference" table is pre-Wave-1 — `skill.md:151-158`
The table has rows for `prep`, `ab_tests`, `power`, `srm`, `effect_size`, `corrections` but **no row for `cuped`, `bayesian`, or `sequential`**. Any Wave 2 agent reading this table as the source of truth will not know these functions exist. The `--sequential` flag is mentioned in `skill.md:48` but no mode spec in MODES.md actually explains how to use it.

### I2. `MetricDefinition.type` values (`proportion`, `mean`, `ratio`) don't cover the Bayesian or CUPED test functions — `agentxp/metrics/schema.py:17-19, 150-163`
`to_test_function` dispatches only to `proportion_test`, `welch_test`, `ratio_metric_test`. No path to `beta_binomial_test`, `cuped_welch_test`, `msprt_test`. Wave 2 may need a `test_family` field on `MetricDefinition` (frequentist / bayesian / sequential / cuped) to compose with the new Wave 1 code.

### I3. `ExperimentStore.save_analysis` uses microsecond timestamps for filenames — `store.py:309-316`
Two analyses saved in the same microsecond get a `-{counter}.json` suffix, but `load_latest_analysis` sorts by filename, which means `20260414T120000000000Z-1.json` sorts AFTER `20260414T120000000001Z.json` (same-microsecond retry vs next-microsecond natural). The "latest" could be wrong by a microsecond. Low-risk in practice; fix by including an incrementing counter in the primary key.

### I4. `agentxp/data/__init__.py` imports `DuckDBLoader` at module top — `agentxp/data/__init__.py:24`
`duckdb_loader.py` itself lazy-imports duckdb, but `from agentxp.data import ...` executes the class body at import time. This is fine — the `_import_duckdb()` call is inside `__init__`, not at module level. Verified clean.

### I5. No name collisions across the five new modules. Verified with `import agentxp; import agentxp.stats, agentxp.storage, agentxp.metrics, agentxp.data` — no shadowing.

### I6. `pyproject.toml:31-41` — `[project.optional-dependencies]` with `snowflake` and `duckdb` extras is syntactically valid. I simulated the wheel build by reading the TOML and confirmed both extras appear under the standard PEP 621 key. Good.

---

## 7. Coverage Gaps

- **`agentxp/data/base.py:39-53` `SchemaDiscovery.to_dict`** has no direct test (only exercised transitively).
- **`agentxp/data/base.py:85-97` `LoadResult.to_dict`** — same.
- **`agentxp/data/csv_loader.py:136-141` `CSVLoader.stream` error paths** — stream is tested for the happy path but not for file-not-found or empty file.
- **`agentxp/stats/cuped.py:114-116` variance-zero fallback** (both pre and post) — no test.
- **`agentxp/stats/sequential.py:82-116` `_msprt_core` with extreme n_eff** (n=2, the minimum allowed) — no direct assertion.
- **`agentxp/stats/bayesian.py:125-143` `_decide`** is covered via the public API tests but has no unit test with edge cases on the thresholds (e.g., loss_ship_t_rel exactly equal to threshold_ship).
- **`agentxp/storage/store.py:85-100` `_append_jsonl` under concurrent writers** — no test. Low priority (single-process assumption is stated).
- **`agentxp/storage/store.py:444-458` `delete_experiment`** is tested, but the test does not confirm that the JSONL log is also removed along with the directory. It is (via `shutil.rmtree`) but an explicit assertion would be nice.
- **`agentxp/metrics/registry.py:19-27` `_default_metrics_dir` fallback to `~/.agentxp/metrics`** — no test (would require monkeypatching HOME).

---

## 8. Positive Highlights

- **Atomic writes + interrupt test** (`test_atomic_write_survives_interrupt`). Patching `os.replace` to raise and asserting the original file is byte-identical is the textbook way to prove atomicity. Model for other storage tests.
- **State machine separation** (`lifecycle.py`) is a clean adapter. Pure-data validation, no I/O, no yaml — easy to fuzz, easy to reason about.
- **Type I rate simulation under peeking** (`test_type_i_rate_under_peeking`) is an actual Monte Carlo statistical check, not a smoke test. This is what "test the math" looks like.
- **CUPED theta-from-closed-form test** (`test_theta_closed_form_on_tiny_example`) uses a hand-constructed `post = 2*pre + 1` to pin theta exactly. Hard to write, impossible to fake.
- **Credential masking** (`_safe_params_for_log` + `test_password_never_logged_on_connect`) iterates every log record and asserts the raw password never appears. Correct paranoia.
- **Discovery hints are isolated to four tuples at `discovery.py:20-62`**, used exclusively via membership tests. True to the "no hardcoded column names" principle from CLAUDE.md.
- **Normal-Normal test covers the positive, negative, null, seed, sample-size, shipping-decision, and NaN-handling cases** — thorough by the standards of this repo.

---

## 9. Required Fixes List (prioritized)

1. **[BLOCKER]** Fix `skill.md` and `MODES.md` to remove references to non-existent functions: `power_ratio`, `extension_estimate`, `fishers_exact_test`, `guardrail_test`, `denominator_srm`, `cohens_h`, `agentxp.stats.prep.prepare_experiment_data`. Either implement them in Wave 2 or rewrite the affected mode steps to use only what `agentxp.stats` actually exports today.
2. **[BLOCKER]** Remove the `computation_trace` contract from `skill.md:149` and `MODES.md:196, 222, 260`, or implement it in every `agentxp.stats` function. Current state is a silent integration landmine.
3. **[HIGH]** Add CUPED, Bayesian, and sequential rows to the "Stats Function Quick Reference" table in `skill.md:151-158`. Agents built off Wave 1 need to know these exist.
4. **[HIGH]** Fix `normal_normal_test` strong-prior math (`bayesian.py:378-389`) OR restrict `prior_sd` to weak-prior range and raise on misuse. Update `test_strong_prior_pulls_posterior` accordingly.
5. **[MEDIUM]** Clean up `_msprt_core:104` dead algebra (`denom / denom`) and reconcile the code with the docstring derivation.
6. **[MEDIUM]** Normalize error-return shapes across `sequential.py` to match `ab_tests.py` convention (`"error": "<string>"`).
7. **[MEDIUM]** Harden `SnowflakeLoader.load_experiment`'s `where` parameter — either parameterize it or validate out obvious injection shapes.
8. **[MEDIUM]** Update top-level `agentxp/__init__.py` docstring to include Bayesian/CUPED/sequential usage examples OR stop advertising `from agentxp.stats import ...` patterns at the root docstring and let `agentxp.stats.__init__` own that docs surface.
9. **[LOW]** Add coverage for the gaps listed in §7 — especially `cuped` variance-zero fallback, `SchemaDiscovery.to_dict`, and `ExperimentStore` corrupt-YAML path.
10. **[LOW]** Tighten `test_null_effect` assertion window in `test_bayesian.py:155-159`.
11. **[LOW]** Add a `test_family` field to `MetricDefinition` (frequentist / bayesian / sequential / cuped) before Wave 2 tries to route metrics through the new test suites.
12. **[LOW]** Document (in a comment at `lifecycle.py:49-59`) the PRD reference for `BLOCKED` transitions — Appendix B is ambiguous about inbound edges.
