# Experiment {{ report.experiment_id }} — {{ report.experiment_name }}

> ## Verdict
>
> **{{ report.verdict }}** — {{ report.rationale_one_line }}
>
> Confidence: {{ report.confidence_label }}

## Headline metrics

| Metric | Direction | Lift | 95% CI | 90% CI | Status |
|--------|-----------|------|--------|--------|--------|
{% for m in report.metric_table -%}
| {{ m.name }} | {{ m.direction }} | {{ m.lift_str }} | {{ m.ci_95 }} | {{ m.ci_90 }} | {{ m.status }} |
{% endfor %}

## Diagnostics

| Check | Result |
|-------|--------|
| Sample-ratio mismatch | {% if report.diagnostics.srm_pass %}PASS{% else %}FAIL{% endif %} |
| Sample adequacy | {{ report.diagnostics.n_observed }} of {{ report.diagnostics.n_required }} required ({{ report.diagnostics.sample_pct }}%) |
| Late-window effect ratio | {% if report.diagnostics.late_ratio is not none %}{{ "%.2f" | format(report.diagnostics.late_ratio) }}{% else %}unavailable{% endif %} |
| Guardrails violated | {{ report.diagnostics.guardrails_violated | length }} |

{% if report.diagnostics.guardrails_violated -%}
### Guardrail violations
{% for g in report.diagnostics.guardrails_violated %}
- **{{ g.metric }}** — {{ g.detail }}
{%- endfor %}
{%- endif %}

## What I'm not sure about

{% for caveat in report.uncertainty_notes -%}
- {{ caveat }}
{% endfor %}

## Audit trail

| Stage | Committed at | Action ID |
|-------|--------------|-----------|
{% for row in report.audit_trail -%}
| {{ row.stage }} | {{ row.committed_at }} | `{{ row.action_id[:12] }}...` |
{% endfor %}

---

*Generated from `report.json` by AgentXP. To replay: `agentxp audit {{ report.experiment_id }}`.*
