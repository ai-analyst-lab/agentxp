# Experiment exp_001 — exp_001

> ## Verdict
>
> **SHIP** — Completion +3.2pp [+1.4, +5.0] at 95% CI; latency guardrail clear at +0.8% (under the 5% halt threshold); late-window 0.87x early — no novelty risk.
>
> Confidence: highly likely positive

## Headline metrics

| Metric | Direction | Lift | 95% CI | 90% CI | Status |
|--------|-----------|------|--------|--------|--------|
| checkout_completion_rate | higher_is_better | +0.032 (+18.0%) | [+0.014, +0.05] | [+0.017, +0.047] | SHIP |
| time_to_checkout_p95 | lower_is_better | +0.008 (+0.8%) | [-0.012, +0.028] | [-0.009, +0.025] | clear |

## Diagnostics

| Check | Result |
|-------|--------|
| Sample-ratio mismatch | PASS |
| Sample adequacy | 91204 of 18000 required (507%) |
| Late-window effect ratio | 0.87 |
| Guardrails violated | 0 |


## What I'm not sure about

- Late-window effect is 0.87x early-window — clear of the 0.7 novelty threshold, but only by 0.17, so the no-novelty call is closer than the verdict implies.
- Two pre-registered segments (web, new users) showed effects under half the pooled lift; the SHIP verdict is driven by mobile and returning users.

## Audit trail

| Stage | Committed at | Action ID |
|-------|--------------|-----------|
| analyzer.out.yaml | 2026-06-02T17:55:11+00:00 | `bundles/anal...` |
| interpreter.out.yaml | 2026-06-02T17:55:11+00:00 | `bundles/inte...` |
| monitor.out.yaml | 2026-06-02T17:55:11+00:00 | `bundles/moni...` |
| readout.out.yaml | 2026-06-02T17:55:11+00:00 | `bundles/read...` |

---

*Generated from `report.json` by AgentXP. To replay: `agentxp audit exp_001`.*
