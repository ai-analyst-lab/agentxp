"""Glance adapter — the 3-line, verdict-first terminal readout.

The highest-frequency surface: "I just ran it — did it pass?" Answered in two
lines that always print, plus an optional third hint line the CLI suppresses
under ``--quiet`` or a non-TTY stream.

  line 1  verdict + lift + CI + guardrail + confidence — all VERBATIM off the VM
  line 2  the mandatory receipt: ``agentxp audit <id>  ·  chain OK|MISMATCH|unverifiable``
  line 3  (CLI chrome) a hint pointing at the fuller readout — see GLANCE_HINT

Glance is PLAIN TEXT by contract: no brand colours, so it pastes cleanly into a
PR comment or a Slack message. The receipt is never "verified" off a stored hash
— ``chain_token`` reads the live minimal hash check (W2-T9).
"""
from __future__ import annotations

from agentxp.render.receipts import replay_line
from agentxp.render.viewmodel import ViewBundle

#: The optional third line. Lives here so glance owns its own text; the CLI
#: appends it only on an interactive, non-quiet stdout.
GLANCE_HINT = "tip: `agentxp report <id> --format md` for the full readout"


def _guardrail_phrase(bundle: ViewBundle) -> str:
    violated = bundle.vm.diagnostics.guardrails_violated
    if not violated:
        return "guardrails clear"
    n = len(violated)
    return f"{n} guardrail violation{'s' if n != 1 else ''}"


class GlanceAdapter:
    """Render a ViewBundle to a 2-line (+optional hint) verdict-first glance."""

    format_id = "glance"
    binary = False
    requires_node = False

    def render(self, bundle: ViewBundle) -> str:
        vm = bundle.vm
        primary = vm.metric_table[0] if vm.metric_table else None
        lift = primary.lift_str if primary else "n/a"
        ci = primary.ci_95 if primary else "n/a"
        line1 = "  ·  ".join(
            [
                vm.verdict,
                lift,
                f"95% CI {ci}",
                _guardrail_phrase(bundle),
                vm.confidence_label,
            ]
        )
        line2 = replay_line(bundle.provenance)
        return f"{line1}\n{line2}"

    def default_filename(self, bundle: ViewBundle) -> str:
        return f"{bundle.vm.experiment_id}.glance.txt"


__all__ = ["GlanceAdapter", "GLANCE_HINT"]
