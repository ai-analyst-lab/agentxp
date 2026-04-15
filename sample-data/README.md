# Sample Data

Optional practice datasets for learning OpenXP. **Nothing in the codebase depends on these files.** You can delete this entire directory without breaking anything.

## Datasets

| File | Scenario | What to Learn |
|------|----------|--------------|
| `clean_ab.csv` | Standard A/B test with positive result | Basic analysis workflow |
| `checkout_redesign.csv` | Positive primary, clean guardrails, multiple segments | Full 8-question framework |
| `no_effect.csv` | Null result, adequately powered | Interpreting non-significant results |
| `underpowered.csv` | Null result, insufficient sample | Power and MDE concepts |
| `srm_violation.csv` | Broken randomization (52/48 split) | SRM detection and diagnosis |
| `guardrail_violation.csv` | Primary metric up, guardrail degraded | Trade-off analysis, INVESTIGATE path |
| `mixed_results.csv` | Segment-level reversals (Simpson's paradox) | Segment analysis, why averages lie |

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

The exact column names vary by dataset — OpenXP auto-detects them at runtime.
