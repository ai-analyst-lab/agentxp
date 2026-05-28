"""
AmendmentTracker — append-only amendments.jsonl per experiment.

Layout (alongside the existing store files):

    {store.root}/{experiment_id}/amendments.jsonl

Each line is a JSON Amendment record. We also emit an 'amendment_recorded'
event to the existing log.jsonl so amendments are visible from store.history().

Design notes:
- AmendmentTracker takes an ExperimentStore and uses its public accessors
  (root, load_experiment, log_path) to resolve experiment directories
  without reaching into underscored helpers.
- Amendment records are the source of truth for diffs; the log event is a
  lightweight breadcrumb that points back to the amendment id.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..storage.lifecycle import BACKWARD_TARGETS, is_backward
from ..storage.store import ExperimentStore, _extract_status
from .diff import classify_change, diff_experiments

_MIN_REASON_LEN = 10


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_author() -> str:
    return os.getenv("USER", "unknown") or "unknown"


@dataclass
class Amendment:
    """Structured amendment record.

    Fields
    ------
    id: UUID4 string for the amendment
    timestamp: ISO-8601 UTC
    experiment_id: slug the amendment belongs to
    author: USER env var default
    reason: free-text, >= 10 chars (enforced at construction)
    changes: list of change dicts from diff_experiments
    material: True if ANY change is classified material
    from_state: experiment status before the amendment
    to_state: experiment status after the amendment (may equal from_state
              for same-state edits)
    """

    experiment_id: str
    reason: str
    changes: list[dict]
    material: bool
    from_state: str
    to_state: str
    author: str = field(default_factory=_default_author)
    timestamp: str = field(default_factory=_iso_now)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or len(self.reason.strip()) < _MIN_REASON_LEN:
            raise ValueError(
                f"Amendment reason must be >= {_MIN_REASON_LEN} chars. "
                f"Got {len(self.reason.strip()) if isinstance(self.reason, str) else 0}. "
                "Hint: describe WHY the change is needed, not just WHAT changed."
            )
        if not self.experiment_id:
            raise ValueError("Amendment.experiment_id is required.")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Amendment":
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            experiment_id=data["experiment_id"],
            author=data["author"],
            reason=data["reason"],
            changes=list(data.get("changes", [])),
            material=bool(data["material"]),
            from_state=data["from_state"],
            to_state=data["to_state"],
        )


def require_amendment_for_transition(from_state: str, to_state: str) -> bool:
    """True if the lifecycle transition is a retreat that requires an amendment.

    Delegates to ``lifecycle.is_backward`` so the tracker stays in sync with
    the state machine automatically — if Wave 3 adds a new backward edge, the
    tracker picks it up without code changes. The canonical backward map is
    ``lifecycle.BACKWARD_TARGETS``; at time of writing it contains
    ``POWERED -> {DESIGNING}``, ``ANALYZING -> {COLLECTING}``,
    ``INTERPRETED -> {COLLECTING}``, and ``INVALID -> {DESIGNING, ABANDONED}``.
    """
    return is_backward(from_state, to_state)


def backward_transitions_snapshot() -> dict[str, list[str]]:
    """Return the current backward-transition map, derived from lifecycle.

    Useful for agents that want to surface "which retreats require an
    amendment" without hardcoding a list. Always reflects the runtime state
    of ``lifecycle.BACKWARD_TARGETS``.
    """
    return {src: sorted(targets) for src, targets in BACKWARD_TARGETS.items()}


class AmendmentTracker:
    """Read/write amendments for experiments under an ExperimentStore."""

    FILENAME = "amendments.jsonl"

    def __init__(self, store: ExperimentStore):
        self.store = store

    # ------------------------------------------------------------------ paths

    def _amendments_path(self, experiment_id: str) -> Path:
        # Use the store's public log_path accessor to resolve the experiment
        # directory (same directory convention store.py uses for log.jsonl).
        exp_dir = self.store.log_path(experiment_id).parent
        return exp_dir / self.FILENAME

    # ------------------------------------------------------------------- write

    def record_amendment(
        self,
        experiment_id: str,
        new_yaml_dict: dict,
        reason: str,
        author: str | None = None,
    ) -> Amendment:
        """Compute a diff against the currently-saved experiment.yaml and
        append a new Amendment record.

        Does NOT write the new_yaml_dict to disk — call store.save_experiment
        separately. That split keeps the tracker a pure audit layer and leaves
        state-machine enforcement to the store.
        """
        if not isinstance(new_yaml_dict, dict):
            raise TypeError(
                f"new_yaml_dict must be a dict, got {type(new_yaml_dict).__name__}."
            )

        current = self.store.load_experiment(experiment_id)
        from_state = _extract_status(current)
        to_state = _extract_status(new_yaml_dict)

        changes = diff_experiments(current, new_yaml_dict)
        material = any(classify_change(c) == "material" for c in changes)

        amendment = Amendment(
            experiment_id=experiment_id,
            reason=reason,
            changes=changes,
            material=material,
            from_state=from_state,
            to_state=to_state,
            author=author if author is not None else _default_author(),
        )

        path = self._amendments_path(experiment_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(amendment.to_dict(), sort_keys=True, default=str) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

        # Breadcrumb in the existing event log so store.history() shows it.
        log_path = self.store.log_path(experiment_id)
        event: dict[str, Any] = {
            "ts": amendment.timestamp,
            "event": "amendment_recorded",
            "amendment_id": amendment.id,
            "author": amendment.author,
            "reason": amendment.reason,
            "material": amendment.material,
            "from_state": amendment.from_state,
            "to_state": amendment.to_state,
            "n_changes": len(changes),
        }
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())

        return amendment

    # -------------------------------------------------------------------- read

    def list_amendments(self, experiment_id: str) -> list[Amendment]:
        """Return all amendments in insertion order."""
        path = self._amendments_path(experiment_id)
        if not path.exists():
            # Mirror store.history() behavior: if the experiment dir doesn't
            # exist at all, raise; otherwise return [].
            if not path.parent.exists():
                raise FileNotFoundError(
                    f"No experiment directory for {experiment_id!r} at {path.parent}."
                )
            return []
        out: list[Amendment] = []
        with open(path, "r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise RuntimeError(
                        f"amendments.jsonl for {experiment_id!r} corrupt on line {lineno}: {e}"
                    ) from e
                out.append(Amendment.from_dict(data))
        return out

    def get_amendment(self, experiment_id: str, amendment_id: str) -> Amendment:
        for a in self.list_amendments(experiment_id):
            if a.id == amendment_id:
                return a
        raise KeyError(
            f"No amendment {amendment_id!r} for experiment {experiment_id!r}. "
            "Hint: list_amendments() to see available ids."
        )

    def material_amendments(self, experiment_id: str) -> list[Amendment]:
        return [a for a in self.list_amendments(experiment_id) if a.material]
