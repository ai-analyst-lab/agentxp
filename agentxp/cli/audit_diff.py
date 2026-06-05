"""Pairwise audit-trail diff helper for ``agentxp audit <a> --diff <b>`` (§15).

Surfaces three classes of differences:
  - events present in A but missing in B (and vice-versa)
  - bundle hashes that differ for the same agent_name
  - a unified-diff-style text rendering with optional ANSI color

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §15.
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = ["render_diff"]


# ANSI color escapes — only emitted when use_color=True (TTY heuristic).
_RED = "\033[31m"
_GREEN = "\033[32m"
_RESET = "\033[0m"


def _load_log_events(exp_dir: Path) -> list[dict]:
    log_path = exp_dir / "log.jsonl"
    if not log_path.exists():
        return []
    events: list[dict] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _event_key(event: dict) -> tuple:
    """Coarse identity key for diffing.

    Two events are considered "the same event" if they share event_name +
    the major identifier(s). We deliberately exclude timestamp and action_id
    so that two runs of the same experiment compare cleanly. Bundle hash is
    NOT part of the key so that a "same event, different bundle hash" diff
    is surfaced as a hash difference rather than a missing event.
    """
    name = event.get("event_name", "")
    parts: list = [name]
    for field in ("stage", "kind", "agent_name", "query_id"):
        if event.get(field):
            parts.append(f"{field}={event[field]}")
    return tuple(parts)


def _format_event_line(event: dict) -> str:
    """One-line summary of an event for diff output."""
    ts = event.get("timestamp", "")
    name = event.get("event_name", "-")
    extras: list[str] = []
    for field in ("stage", "kind", "agent_name", "query_id"):
        if event.get(field):
            extras.append(f"{field}={event[field]}")
    extras_str = " ".join(extras)
    return f"{ts} {name} {extras_str}".rstrip()


def render_diff(
    exp_a_id: str,
    exp_a_dir: Path,
    exp_b_id: str,
    exp_b_dir: Path,
    *,
    use_color: bool = False,
) -> str:
    """Return the text rendering of the A-vs-B diff."""
    events_a = _load_log_events(exp_a_dir)
    events_b = _load_log_events(exp_b_dir)

    keys_a = {_event_key(e): e for e in events_a}
    keys_b = {_event_key(e): e for e in events_b}

    only_in_a = [keys_a[k] for k in keys_a.keys() - keys_b.keys()]
    only_in_b = [keys_b[k] for k in keys_b.keys() - keys_a.keys()]

    # Bundle-hash differences: same agent_name appears in both A and B with
    # different bundle_hash values. Compare on (agent_name, event_name) so
    # dispatched vs completed don't cross-pollinate.
    def _agent_hashes(events: list[dict]) -> dict[tuple[str, str], str]:
        out: dict[tuple[str, str], str] = {}
        for ev in events:
            if ev.get("event_name") not in (
                "agent.dispatched",
                "agent.completed",
            ):
                continue
            agent = ev.get("agent_name")
            bh = ev.get("bundle_hash")
            if not agent or not bh:
                continue
            out.setdefault((agent, ev["event_name"]), bh)
        return out

    hashes_a = _agent_hashes(events_a)
    hashes_b = _agent_hashes(events_b)
    hash_diffs: list[tuple[str, str, str, str]] = []
    for key, hash_a in hashes_a.items():
        hash_b = hashes_b.get(key)
        if hash_b is not None and hash_b != hash_a:
            agent, event_name = key
            hash_diffs.append((agent, event_name, hash_a, hash_b))

    lines: list[str] = []
    lines.append(f"--- {exp_a_id}/log.jsonl")
    lines.append(f"+++ {exp_b_id}/log.jsonl")

    if not only_in_a and not only_in_b and not hash_diffs:
        lines.append("no differences")
        return "\n".join(lines) + "\n"

    def _minus(text: str) -> str:
        line = f"- {text}"
        return f"{_RED}{line}{_RESET}" if use_color else line

    def _plus(text: str) -> str:
        line = f"+ {text}"
        return f"{_GREEN}{line}{_RESET}" if use_color else line

    if only_in_a:
        lines.append("")
        lines.append(f"events only in {exp_a_id}:")
        for ev in only_in_a:
            lines.append(_minus(_format_event_line(ev)))

    if only_in_b:
        lines.append("")
        lines.append(f"events only in {exp_b_id}:")
        for ev in only_in_b:
            lines.append(_plus(_format_event_line(ev)))

    if hash_diffs:
        lines.append("")
        lines.append("bundle hashes that differ:")
        for agent, event_name, hash_a, hash_b in hash_diffs:
            lines.append(f"  {agent} ({event_name}):")
            lines.append(_minus(f"  {hash_a[:12]}..."))
            lines.append(_plus(f"  {hash_b[:12]}..."))

    return "\n".join(lines) + "\n"
