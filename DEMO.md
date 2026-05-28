# AgentXP Hero Demo Script

Recording script for the opening GIF on the README and the project homepage.

**Target runtime:** ~70 seconds
**Recording tools:** asciinema (preferred for terminal authenticity) or terminalizer (preferred for GIF polish and typing animation control)
**Aspect:** 16:9 terminal, dark background, large monospace font (16pt+)
**Voice-over:** optional; the demo is designed to read cleanly without narration

---

## Scene Setup (do this before recording)

1. Terminal: iTerm2 or Ghostty, full screen, dark theme, font size 16pt.
2. Working directory: `~/openxp` with `sample-data/` present.
3. Claude Code is already open in the terminal — the `>` prompt is visible and idle.
4. Clear the scrollback so the recording starts clean.
5. Window title: `openxp — claude`
6. Verify: `ls sample-data/srm_violation.csv sample-data/clean_ab.csv` — both exist.

The recording starts with Claude Code's idle prompt visible.

---

## Scene 1 — SRM Gate Blocks (0:00 – 0:20)

**Purpose:** show AgentXP catching a randomization failure before wasting an analysis.

### Beat 1 (0:00 – 0:03)

Type at the Claude Code prompt, slowly enough to read:

```
/experiment analyze sample-data/srm_violation.csv
```

Hit Enter. The command renders; Claude Code begins responding.

### Beat 2 (0:03 – 0:12)

Claude Code output (highlight on screen):

```
Loading sample-data/srm_violation.csv… 10,000 rows × 5 columns.
Discovered: treatment column 'variant' (control vs treatment),
metric column 'converted', 'revenue', segment column 'platform'.

Step 1 / 8 — SRM check (chi-square on allocation)
  control:   6,012  (expected 5,000)
  treatment: 3,988  (expected 5,000)
  chi-square p = 1.4e-28
  verdict: BLOCK
```

### Beat 3 (0:12 – 0:20)

The BLOCK line glows red. Claude Code prints the dramatic save:

```
STOP — Sample Ratio Mismatch detected.
Allocation deviates from the 50/50 split by 10.1 percentage points.
This is almost certainly a randomization bug, not a real effect.
Do NOT trust downstream results.

Recommended next step: /experiment investigate
```

**Highlight:** the BLOCK verdict and the "Do NOT trust" line.

**Voice-over idea:** *"AgentXP's SRM gate catches broken randomization before you waste a week analyzing bad data."*

---

## Scene 2 — Full Pipeline, SHIP Verdict (0:20 – 0:50)

**Purpose:** show the one-command end-to-end run on a clean experiment.

### Beat 1 (0:20 – 0:23)

Type:

```
/experiment full sample-data/clean_ab.csv
```

Hit Enter.

### Beat 2 (0:23 – 0:32)

Claude Code prints a compact pipeline progress indicator. Each step appears and ticks green as it completes:

```
[1/6] Designing experiment from data…           done
[2/6] Power analysis (n=4,823/group, d=9 days)  VIABLE
[3/6] SRM check                                  PASS
[4/6] Treatment effects                          running…
```

### Beat 3 (0:32 – 0:42)

The results table appears:

```
Primary — conversion rate:
  control    8.2%     treatment  8.9%     lift +8.5%   p=0.018   SIG
Secondary — revenue/user:
  control    $4.12    treatment  $4.28    lift +3.9%   p=0.134
Guardrail — page load p95:
  control    2.10s    treatment  2.11s    +0.5%        PASS
```

### Beat 4 (0:42 – 0:50)

The interpretation block lands. Highlight the verdict line:

```
[5/6] Interpretation                              SHIP
[6/6] Report                                       generated -> reports/2026q2-ab.md

Verdict: SHIP
  Primary metric significant positive, guardrails clean.
  Projected business impact: $180K–$500K/year (CI bounds).
```

**Highlight:** the green `SHIP` and the projected business impact line.

**Voice-over idea:** *"One command: design, power, analyze, interpret, report. SHIP verdict in under a minute."*

---

## Scene 3 — Interpret Against the Analysis (0:50 – 1:10)

**Purpose:** show the Result Interpretation Tree walkthrough for an analysis that already exists.

### Beat 1 (0:50 – 0:53)

Type:

```
/experiment interpret
```

Hit Enter. (No argument — it finds the most recent analysis from Scene 2.)

### Beat 2 (0:53 – 1:04)

Claude Code walks the interpretation tree, each question appearing as it's answered:

```
Walking the Result Interpretation Tree against latest analysis…

  Q1. Is the SRM gate clean?                         YES  →  continue
  Q2. Is the primary metric significant?              YES  →  continue
  Q3. Is the effect in the hypothesized direction?    YES  →  continue
  Q4. Are all guardrails within threshold?            YES  →  continue
  Q5. Is the experiment adequately powered?           YES  →  continue
  Q6. Do segments confirm the aggregate?              YES  →  continue
  Q7. Is practical significance met?                  YES  →  SHIP
```

### Beat 3 (1:04 – 1:10)

Final block:

```
Classification: SHIP
Rationale:
  • Clean SRM, adequately powered, primary +8.5% (p=0.018)
  • Guardrails pass; no segment reversals detected
  • Projected $340K/year best estimate

Next step: /experiment report --audience executive
```

**Highlight:** the tree, cascading YES answers, and the final SHIP classification.

**Voice-over idea:** *"The interpretation tree is transparent. Every decision has a reason you can show your stakeholders."*

---

## Beat Sheet (for the editor)

| Time | Scene | Action | What's on screen | Highlight |
|------|-------|--------|-----------------|-----------|
| 0:00 | 1 | Type `/experiment analyze sample-data/srm_violation.csv` | Command renders | — |
| 0:03 | 1 | Schema discovery + SRM running | Row count, columns, chi-square | — |
| 0:12 | 1 | BLOCK verdict | Red BLOCK, "Do NOT trust" | BLOCK line |
| 0:20 | 2 | Type `/experiment full sample-data/clean_ab.csv` | Command renders | — |
| 0:23 | 2 | Pipeline steps ticking | 6-step progress | Each green tick |
| 0:32 | 2 | Results table | Primary, secondary, guardrail rows | Primary lift row |
| 0:42 | 2 | SHIP + business impact | Verdict block | SHIP, $180K-$500K |
| 0:50 | 3 | Type `/experiment interpret` | Command renders | — |
| 0:53 | 3 | Interpretation tree walking | 7 cascading Qs | Each YES |
| 1:04 | 3 | Final classification | SHIP + rationale | SHIP verdict |
| 1:10 | — | Fade to README link | `github.com/ai-analyst-lab/openxp` | URL |

**Total runtime: ~70 seconds.**

---

## Recording Commands

### asciinema (authentic terminal cast)

```bash
# Install
brew install asciinema

# Record
asciinema rec openxp-demo.cast -t "AgentXP — experiment analysis in Claude Code"

# Convert to GIF for embedding
brew install agg
agg --theme monokai --font-size 20 openxp-demo.cast openxp-demo.gif
```

### terminalizer (more polish, controllable typing speed)

```bash
# Install
npm install -g terminalizer

# Init config
terminalizer init openxp-demo

# Edit config/openxp-demo.yml:
#   cols: 120
#   rows: 30
#   frameDelay: auto
#   theme: monokai
#   fontFamily: "JetBrains Mono"
#   fontSize: 16

# Record
terminalizer record openxp-demo

# Render
terminalizer render openxp-demo
```

---

## Post-Production Notes

- Trim any startup lag before Scene 1 — the recording should begin with the Claude Code prompt already idle.
- If a real run is too slow for Scene 2's 30-second budget, pre-record and stitch; the demo's purpose is to communicate the product, not prove wall-clock speed.
- Loop the GIF. The last frame should match the first frame closely enough that the loop isn't jarring.
- For the README embed, target 800px wide max. The asciinema cast should be embedded as a live player; the GIF is the fallback.
- Keep total file size under 3MB for the GIF.

## Voice-Over Script (optional, ~30 seconds total)

> "This is AgentXP — an experiment analysis partner that runs inside Claude Code.
> Scene one: it catches broken randomization before you waste a week on bad data.
> Scene two: one command runs the full pipeline — design, power, analyze, interpret, report — and gives you a SHIP verdict.
> Scene three: every decision is explained by a transparent interpretation tree you can show your stakeholders.
> Statsig gives you a dashboard. AgentXP gives you a colleague who knows statistics."
