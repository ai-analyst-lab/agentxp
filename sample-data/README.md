# Sample Data

Optional practice datasets for learning AgentXP. **Nothing in the codebase depends on these files.** You can delete this entire directory without breaking anything.

## Datasets

| File | Scenario | What to Learn | Expected Outcome |
|------|----------|--------------|------------------|
| `clean_ab.csv` | Standard A/B test with positive result | Basic analysis workflow | **SHIP** — positive lift on both conversion and revenue, SRM clean |
| `checkout_redesign.csv` | Positive primary, clean guardrails, multiple segments | Full 8-question framework | **SHIP** — checkout_completed significant positive (+10.9%, p=0.039), revenue directionally positive but not significant; no guardrail violations. Interesting because the primary (proportion) clears significance while the revenue (continuous) does not, showing how metric type affects power. |
| `no_effect.csv` | Null result, adequately powered | Interpreting non-significant results | **LEARN (powered)** — neither conversion nor revenue significant, n=5000/group is adequate power |
| `underpowered.csv` | Null result, insufficient sample | Power and MDE concepts | **LEARN (underpowered)** — positive directional lifts but n=500/group is too small to detect moderate effects |
| `srm_violation.csv` | Broken randomization (52/48 split) | SRM detection and diagnosis | **INVALID** — SRM BLOCK (p<0.001), analysis results untrustworthy |
| `guardrail_violation.csv` | Primary metric flat, guardrail degraded | Trade-off analysis, INVESTIGATE path | **INVESTIGATE** — conversion and revenue not significant, but page_load_ms increased +16% (p~0), guardrail_test BLOCK |
| `mixed_results.csv` | Segment-level reversals (Simpson's paradox) | Segment analysis, why averages lie | **INVESTIGATE** — sessions and revenue significantly positive, but 30-day retention significantly negative (-4.8%); segment-level retention reversals on iOS and Android |

## Usage

```
/experiment analyze sample-data/clean_ab.csv
```

## Data Structure

All files share a common structure:
- `user_id` — unique user identifier
- `variant` — `control` or `treatment`
- One or more outcome columns (metric-specific)
- Segment columns (platform, device type, etc.)

The exact column names vary by dataset — AgentXP auto-detects them at runtime.
