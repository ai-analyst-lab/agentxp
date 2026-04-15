# OpenXP

**Statsig gives you a dashboard. OpenXP gives you a colleague who knows statistics.**

OpenXP is an open-source, agentic experimentation platform that runs inside [Claude Code](https://claude.ai/code). Instead of a web dashboard, you get a conversational partner that designs experiments, runs power calculations, analyzes results, and writes stakeholder reports — all backed by production-grade statistical code, not LLM improvisation.

## What OpenXP Does

- **Design experiments** with proper statistical rigor — hypothesis, metrics, guardrails, pre-registered decision rules
- **Power calculations** — sample size, duration estimates, sensitivity tables
- **Analyze A/B tests** — SRM validation, treatment effects, segment analysis, business impact
- **Interpret results** — Ship / Investigate / Abort / Learn / Invalid classification
- **Monitor running experiments** — SRM trending, guardrail health, sample accumulation
- **Generate reports** — stakeholder-ready readouts adapted to your audience

## What OpenXP Does NOT Do

- Feature flags or experiment assignment infrastructure
- Deployment or CI/CD
- Causal inference (DiD, PSM — that's a separate project)
- Replace your judgment — OpenXP gives you the analysis, you make the decision

## Quick Start

```bash
# Clone and install
git clone https://github.com/ai-analyst-lab/openxp.git
cd openxp
pip install -e .

# Open in Claude Code and try it
/experiment analyze sample-data/clean_ab.csv
```

## Usage

| Command | What It Does |
|---------|-------------|
| `/experiment design` | Interactive experiment design → experiment.yaml |
| `/experiment power` | Power analysis + duration + sensitivity table |
| `/experiment analyze data.csv` | Full statistical analysis of A/B test data |
| `/experiment interpret` | Ship/Investigate/Abort/Learn/Invalid classification |
| `/experiment monitor data.csv` | Health check on a running experiment |
| `/experiment report` | Stakeholder-ready report |
| `/experiment full data.csv` | End-to-end: design → analyze → interpret → report |

## How It Compares

| | OpenXP | GrowthBook | Statsig | Eppo |
|---|--------|------------|---------|------|
| **Price** | Free (MIT) | Free tier + paid | $$$ | $$$ |
| **Interface** | CLI (Claude Code) | Web dashboard | Web dashboard | Web dashboard |
| **Self-host** | Yes (it's local) | Yes | No | No |
| **CUPED** | v1.0 | Enterprise only | Yes | Yes |
| **Sequential testing** | v1.0 | Yes | Yes | Yes |
| **Bayesian** | v1.0 | Yes | No | No |
| **Code auditable** | Every function | Open source | Proprietary | Proprietary |
| **Report generation** | Built-in | No | No | No |
| **Experiment design** | Built-in | No | No | No |
| **Pre-registration** | experiment.yaml | No | No | No |

## The Stats Engine

Every statistical function is auditable Python. No LLM improvisation — the code runs deterministically.

```python
from openxp.stats import (
    # A/B testing
    welch_test, proportion_test, ratio_metric_test,
    # Power analysis
    power_proportion, power_mean, duration_estimate,
    # SRM detection
    srm_check, srm_diagnose,
    # Effect sizes
    cohens_d, relative_lift,
    # Multiple comparisons
    adjust_pvalues,
)

# Check for SRM before analyzing
srm = srm_check([4800, 5200], expected_ratios=[0.5, 0.5])
print(srm["verdict"])  # "BLOCK" — randomization is broken

# Run a proportion test
result = proportion_test(c_success=350, c_n=1000, t_success=385, t_n=1000)
print(result["interpretation"])
# "Treatment rate (0.3850) is significantly higher than control (0.3500)..."

# Power calculation
power = power_proportion(baseline_rate=0.08, mde_relative=0.10)
print(power["interpretation"])
# "Need 24,572 users per group (49,144 total) to detect a 10.0% relative lift..."
```

## Sample Data

Practice datasets in `sample-data/` (nothing depends on these — delete them freely):

| File | Scenario | Expected Outcome |
|------|----------|-----------------|
| `clean_ab.csv` | Standard A/B test | SHIP |
| `no_effect.csv` | Null result, well-powered | LEARN |
| `srm_violation.csv` | Broken randomization | INVALID |
| `guardrail_violation.csv` | Primary up, guardrail down | INVESTIGATE |
| `underpowered.csv` | Null, insufficient power | LEARN (extend) |
| `mixed_results.csv` | Segment-level reversals | INVESTIGATE |

## Documentation

| Guide | Topic |
|-------|-------|
| [Your First Experiment](walkthroughs/your-first-experiment.md) | End-to-end walkthrough |
| [Power Calculation](walkthroughs/power-calculation.md) | Sample size, duration, sensitivity |
| [Reading Results](walkthroughs/reading-results.md) | p-values, CIs, effect sizes |
| [Pre-Registration](walkthroughs/pre-registration.md) | Why and how to write experiment.yaml |
| [Stats Cheat Sheet](templates/stats-cheat-sheet.md) | Quick reference |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# 55 tests covering A/B tests, power analysis, SRM detection, effect sizes
```

## Roadmap

### v0.1 (current) — Working MVP
- A/B test analysis (welch, proportion, ratio, delta method)
- Power calculations + duration estimation
- SRM detection and diagnosis
- Effect sizes and multiple comparison correction
- 5 agent prompts + skill orchestrator
- experiment.yaml lifecycle

### v0.5 — Full Pipeline + Monitoring
- End-to-end `/experiment full` orchestration
- Running experiment monitoring
- DuckDB connector

### v1.0 — Production Release
- CUPED variance reduction
- Sequential testing (always-valid CIs)
- Bayesian A/B testing
- Snowflake MCP connector

## License

MIT. Use it however you want.

---

Built by [AI Analyst Lab](https://aianalystlab.ai).
