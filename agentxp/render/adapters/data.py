"""Data adapters — ``json`` and ``csv`` machine-readable exports of a bundle.

Both are pure, dependency-free renderers (stdlib only) over the same
:class:`ViewBundle` every other adapter consumes. They carry the strings
``distill()`` already formatted — an adapter interpolates, it never re-derives a
number — and they carry the authenticity receipts inseparably (the provenance
travels in the same document), so a machine consumer of the export sees the same
verdict, the same lift, and the same verification status a human reader sees.

``json`` is the faithful structured dump (the VM plus its provenance). ``csv`` is
the flat tabular slice a spreadsheet wants: one row per headline metric, each row
self-describing (experiment identity + verdict + render status lead every row).
Neither mangles a value to defend against spreadsheet formula-injection — the
numbers are the user's own run output and authenticity forbids silently editing
them; the stdlib ``csv`` writer still quotes any field with special characters.
"""
from __future__ import annotations

import csv
import io
import json

from agentxp.render.viewmodel import ViewBundle


class JsonAdapter:
    """Render a ViewBundle to a structured JSON document (VM + receipts)."""

    format_id = "json"
    binary = False
    requires_node = False

    def render(self, bundle: ViewBundle) -> str:
        payload = {
            "vm": bundle.vm.model_dump(mode="json"),
            "provenance": bundle.provenance.model_dump(mode="json"),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def default_filename(self, bundle: ViewBundle) -> str:
        return f"{bundle.vm.experiment_id}.report.json"


class CsvAdapter:
    """Render a ViewBundle to a flat CSV of the headline metric table.

    One row per metric. Each row leads with the experiment identity, verdict and
    render status so a row pasted into a sheet stands on its own. All numeric
    columns carry the already-formatted strings off the VM verbatim.
    """

    format_id = "csv"
    binary = False
    requires_node = False

    _HEADER = [
        "experiment_id",
        "experiment_name",
        "verdict",
        "render_status",
        "metric",
        "direction",
        "lift",
        "ci_95",
        "ci_90",
        "metric_status",
    ]

    def render(self, bundle: ViewBundle) -> str:
        vm = bundle.vm
        status = bundle.provenance.render_status.value
        buf = io.StringIO()
        # \n line terminator (not the csv default \r\n) so the output is
        # byte-stable across platforms, matching the other text adapters.
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(self._HEADER)
        for m in vm.metric_table:
            writer.writerow([
                vm.experiment_id,
                vm.experiment_name,
                vm.verdict,
                status,
                m.name,
                m.direction,
                m.lift_str,
                m.ci_95,
                m.ci_90,
                m.status,
            ])
        return buf.getvalue()

    def default_filename(self, bundle: ViewBundle) -> str:
        return f"{bundle.vm.experiment_id}.report.csv"


__all__ = ["JsonAdapter", "CsvAdapter"]
