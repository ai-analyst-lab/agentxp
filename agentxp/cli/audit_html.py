"""HTML renderer for ``agentxp audit <exp_id> --html`` (§15).

Single-file self-contained HTML report:
  - one row per event with collapsible payload (<details>)
  - per-stage section with the matching decisions/*.yaml in <pre>
  - bundle hashes table at the top
  - inline <style>, no external CDN, no JS that wouldn't work offline
  - every user-controlled string passed through html.escape() (M81 fix)

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §15.
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

from agentxp.render import brand

__all__ = ["render_html_report", "write_html_report"]


# Component rules for the audit page. NO hex literal lives here — every colour,
# font, and the chain-ok/chain-fail states resolve through a --xp-* var defined
# by brand.json (W4-T7: the off-brand dump becomes on-brand). The :root block
# and @font-face are prepended by _style_block() so the page stays a single,
# offline, self-contained file.
_AUDIT_RULES = """
body { font-family: var(--xp-font-sans);
       background: var(--xp-paper); color: var(--xp-ink);
       max-width: 1100px; margin: 2em auto; padding: 0 1em; }
h1 { font-family: var(--xp-font-serif); font-size: 1.6em; margin-bottom: 0.2em; }
h2 { font-family: var(--xp-font-serif); font-size: 1.2em; margin-top: 2em;
     border-bottom: 1px solid var(--xp-rule); padding-bottom: 0.25em; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.9em; }
th, td { border-bottom: 1px solid var(--xp-rule); padding: 6px 10px;
         text-align: left; vertical-align: top; }
th { background: var(--xp-paper-raised); }
tr.event-row td { font-family: var(--xp-font-mono); font-size: 0.85em; }
details { margin: 0.4em 0; }
summary { cursor: pointer; color: var(--xp-ink-soft); }
pre { background: var(--xp-paper-raised); font-family: var(--xp-font-mono);
      padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 0.85em;
      white-space: pre-wrap; word-break: break-word; }
.event-name { font-weight: 600; }
.actor { color: var(--xp-ink-soft); }
.ts { color: var(--xp-muted); }
.chain-ok { color: var(--xp-pass); }
.chain-fail { color: var(--xp-fail); }
.muted { color: var(--xp-muted); font-size: 0.9em; }
"""


def _style_block() -> str:
    """Compose the full inlined stylesheet: brand vars + @font-face + rules.

    Keeps the audit report self-contained (no external assets, offline-safe):
    the fonts are base64-embedded and every value resolves through brand.json.
    """
    return "\n".join([brand.css_vars(), brand.font_face_css(), _AUDIT_RULES])


def _esc(value) -> str:
    """html.escape with str() coercion. None → empty string."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _short_metadata_html(event: dict) -> str:
    """Render the per-event short metadata as already-escaped HTML."""
    name = event.get("event_name", "")
    parts: list[str] = []
    if event.get("stage"):
        parts.append(f"stage={_esc(event['stage'])}")
    if event.get("kind"):
        parts.append(f"kind={_esc(event['kind'])}")
    if name in ("agent.dispatched", "agent.completed"):
        if event.get("agent_name"):
            parts.append(f"agent={_esc(event['agent_name'])}")
        if event.get("bundle_hash"):
            parts.append(f"bundle={_esc(str(event['bundle_hash'])[:12])}")
        if name == "agent.completed" and event.get("classification"):
            parts.append(f"status={_esc(event['classification'])}")
    if name.startswith("query.") and event.get("query_id"):
        parts.append(f"query={_esc(event['query_id'])}")
    if name == "gate.blocked" and event.get("reason"):
        parts.append(f"reason={_esc(event['reason'])}")
    if name == "gate.resolved" and event.get("choice"):
        parts.append(f"choice={_esc(event['choice'])}")
    return " ".join(parts)


def _bundle_hashes_section(events: list[dict]) -> str:
    """Build the bundle-hashes table — one row per (agent, hash, status)."""
    rows: list[str] = []
    seen: set[tuple[str, str]] = set()
    for ev in events:
        name = ev.get("event_name")
        if name not in ("agent.dispatched", "agent.completed"):
            continue
        agent = ev.get("agent_name") or "-"
        bh = ev.get("bundle_hash") or ""
        if not bh:
            continue
        key = (agent, bh)
        if key in seen:
            continue
        seen.add(key)
        status = ev.get("classification") or (
            "dispatched" if name == "agent.dispatched" else "completed"
        )
        rows.append(
            "<tr><td>{a}</td><td><code>{h}</code></td><td>{s}</td></tr>".format(
                a=_esc(agent), h=_esc(bh), s=_esc(status)
            )
        )
    if not rows:
        return "<p class='muted'>no agent bundles recorded</p>"
    return (
        "<table><thead><tr><th>agent</th><th>bundle hash</th>"
        "<th>status</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _event_rows_section(events: list[dict]) -> str:
    """Build the event-timeline table. Payload collapsible per row."""
    if not events:
        return "<p class='muted'>no events recorded yet</p>"
    rows: list[str] = []
    for ev in events:
        ts = _esc(ev.get("timestamp", ""))
        actor = _esc(ev.get("actor_name") or ev.get("actor_kind") or "-")
        name = _esc(ev.get("event_name", "-"))
        tail = _short_metadata_html(ev)
        payload_json = _esc(json.dumps(ev, indent=2, default=str))
        rows.append(
            "<tr class='event-row'>"
            f"<td class='ts'>{ts}</td>"
            f"<td class='actor'>{actor}</td>"
            f"<td class='event-name'>{name}</td>"
            f"<td>{tail}"
            "<details><summary>payload</summary>"
            f"<pre>{payload_json}</pre></details>"
            "</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>timestamp</th><th>actor</th>"
        "<th>event</th><th>detail</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _decisions_section(decisions: list[tuple[str, str]]) -> str:
    """Render per-stage decisions as <pre> blocks (one per file)."""
    if not decisions:
        return "<p class='muted'>no decision records found</p>"
    blocks: list[str] = []
    for fname, body in decisions:
        blocks.append(
            f"<details open><summary>{_esc(fname)}</summary>"
            f"<pre>{_esc(body)}</pre></details>"
        )
    return "".join(blocks)


def render_html_report(
    exp_id: str,
    events: list[dict],
    decisions: list[tuple[str, str]],
) -> str:
    """Return the full HTML document as a string."""
    gates_opened = sum(1 for e in events if e.get("event_name") == "gate.opened")
    gates_resolved = sum(
        1 for e in events if e.get("event_name") == "gate.resolved"
    )
    summary_line = (
        f"total events: {len(events)} | "
        f"gates opened: {gates_opened} | "
        f"gates resolved: {gates_resolved}"
    )

    title = f"Audit trail for {exp_id}"
    return (
        "<!doctype html>\n"
        "<html lang='en'><head>"
        "<meta charset='utf-8'>"
        f"<title>{_esc(title)}</title>"
        f"<style>{_style_block()}</style>"
        "</head><body>"
        f"<h1>{_esc(title)}</h1>"
        f"<p class='muted'>{_esc(summary_line)}</p>"
        "<h2>Bundle hashes</h2>"
        f"{_bundle_hashes_section(events)}"
        "<h2>Events</h2>"
        f"{_event_rows_section(events)}"
        "<h2>Decisions</h2>"
        f"{_decisions_section(decisions)}"
        "</body></html>\n"
    )


def write_html_report(out_path: Path, html_text: str) -> None:
    """Write the HTML to disk with chmod 600 (per §1.7.3 user-data hygiene)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the start so there's no world-readable window.
    if out_path.exists():
        out_path.unlink()
    fd = os.open(
        str(out_path),
        os.O_CREAT | os.O_WRONLY | os.O_EXCL,
        0o600,
    )
    try:
        os.write(fd, html_text.encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass  # tolerate on restricted filesystems
