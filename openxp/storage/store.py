"""
ExperimentStore — local JSON/YAML-backed storage for experiment history.

File layout under `root`:

    {root}/{experiment_id}/experiment.yaml
    {root}/{experiment_id}/analyses/{timestamp}.json
    {root}/{experiment_id}/interpretation.json
    {root}/{experiment_id}/report.md
    {root}/{experiment_id}/log.jsonl

The experiment.yaml file is the source of truth for ONE experiment. The store
aggregates experiments plus analysis outputs, decisions, and the append-only
event log.

Design notes:
- stdlib + PyYAML only (no SQLite). SQLite can swap in later behind the same
  interface.
- All writes are atomic: write to a sibling tmp file then os.replace().
- All methods raise ValueError/FileNotFoundError/RuntimeError with actionable
  hints — no silent failures.
- The state machine (lifecycle.py) is enforced on every save_experiment() call
  that changes the status field.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .lifecycle import (
    ALL_STATES,
    is_backward,
    validate_transition,
)

DEFAULT_ROOT = "~/.openxp/experiments"
_TIMESTAMP_FMT = "%Y%m%dT%H%M%S%fZ"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp_str() -> str:
    return _utcnow().strftime(_TIMESTAMP_FMT)


def _iso_now() -> str:
    return _utcnow().isoformat().replace("+00:00", "Z")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` atomically via tmp file + os.replace.

    The tmp file lives in the same directory to guarantee same-filesystem
    rename (os.replace is atomic on POSIX when src and dst are on the same FS).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _append_jsonl(path: Path, record: dict) -> None:
    """Append a single JSON record + newline to a .jsonl log file.

    Appends are (nearly) atomic for small records on POSIX when using a single
    write() syscall. We open in 'a' mode, write, fsync, close.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, default=str) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _extract_status(experiment_yaml: dict) -> str:
    """Pull status from either top-level or nested-under-'experiment' shape."""
    if "experiment" in experiment_yaml and isinstance(
        experiment_yaml["experiment"], dict
    ):
        inner = experiment_yaml["experiment"]
    else:
        inner = experiment_yaml
    status = inner.get("status", "DESIGNING")
    if status is None:
        status = "DESIGNING"
    return str(status)


def _extract_name(experiment_yaml: dict) -> str:
    if "experiment" in experiment_yaml and isinstance(
        experiment_yaml["experiment"], dict
    ):
        inner = experiment_yaml["experiment"]
    else:
        inner = experiment_yaml
    return str(inner.get("name", "") or "")


class ExperimentStore:
    """JSON+YAML backed experiment history store."""

    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(os.path.expanduser(str(root)))
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths

    def _exp_dir(self, experiment_id: str) -> Path:
        if not experiment_id or "/" in experiment_id or experiment_id.startswith("."):
            raise ValueError(
                f"Invalid experiment_id {experiment_id!r}. "
                "Must be a non-empty slug without '/' or leading '.'."
            )
        return self.root / experiment_id

    def _yaml_path(self, experiment_id: str) -> Path:
        return self._exp_dir(experiment_id) / "experiment.yaml"

    def _analyses_dir(self, experiment_id: str) -> Path:
        return self._exp_dir(experiment_id) / "analyses"

    def _interpretation_path(self, experiment_id: str) -> Path:
        return self._exp_dir(experiment_id) / "interpretation.json"

    def _report_path(self, experiment_id: str) -> Path:
        return self._exp_dir(experiment_id) / "report.md"

    def _log_path(self, experiment_id: str) -> Path:
        return self._exp_dir(experiment_id) / "log.jsonl"

    # ------------------------------------------------------------- experiment

    def save_experiment(
        self,
        experiment_id: str,
        experiment_yaml: dict,
        amendment_reason: str | None = None,
    ) -> Path:
        """Write or overwrite an experiment.yaml, enforcing state transitions.

        If the file already exists, the old status is read and compared against
        the new status. Illegal transitions raise ValueError. Retreats (e.g.
        POWERED -> DESIGNING) require `amendment_reason`.
        """
        if not isinstance(experiment_yaml, dict):
            raise TypeError(
                f"experiment_yaml must be a dict, got {type(experiment_yaml).__name__}. "
                "Hint: yaml.safe_load(yaml_text) before passing in."
            )

        yaml_path = self._yaml_path(experiment_id)
        new_status = _extract_status(experiment_yaml)
        if new_status not in ALL_STATES:
            raise ValueError(
                f"Invalid status {new_status!r} in experiment_yaml. "
                f"Valid states: {sorted(ALL_STATES)}"
            )

        old_status: str | None = None
        if yaml_path.exists():
            try:
                existing = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                raise RuntimeError(
                    f"Existing experiment.yaml at {yaml_path} is corrupt: {e}. "
                    "Hint: fix or remove the file before re-saving."
                ) from e
            old_status = _extract_status(existing)

            ok, err = validate_transition(old_status, new_status)
            if not ok:
                raise ValueError(
                    f"[{experiment_id}] {err}"
                )
            if is_backward(old_status, new_status) and not amendment_reason:
                raise ValueError(
                    f"[{experiment_id}] Backward transition {old_status} -> "
                    f"{new_status} requires an amendment_reason. "
                    "Hint: pass amendment_reason='why you are retreating'."
                )

        serialized = yaml.safe_dump(
            experiment_yaml, sort_keys=False, default_flow_style=False
        )
        _atomic_write_text(yaml_path, serialized)

        event: dict[str, Any] = {
            "ts": _iso_now(),
            "event": "experiment_saved",
            "from_status": old_status,
            "to_status": new_status,
            "name": _extract_name(experiment_yaml),
        }
        if amendment_reason:
            event["amendment_reason"] = amendment_reason
        if old_status is not None and old_status != new_status:
            event["event"] = "status_change"
        _append_jsonl(self._log_path(experiment_id), event)

        return yaml_path

    def load_experiment(self, experiment_id: str) -> dict:
        yaml_path = self._yaml_path(experiment_id)
        if not yaml_path.exists():
            raise FileNotFoundError(
                f"No experiment.yaml for {experiment_id!r} at {yaml_path}. "
                "Hint: call save_experiment() first or check the id."
            )
        try:
            return yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise RuntimeError(
                f"experiment.yaml for {experiment_id!r} is corrupt: {e}"
            ) from e

    def list_experiments(self, status_filter: str | None = None) -> list[dict]:
        """Return a summary list: [{id, name, status, created, updated}, ...].

        Sorted by updated desc. `created` and `updated` are filesystem mtimes
        on the experiment dir and experiment.yaml respectively, ISO-formatted.
        """
        if status_filter is not None and status_filter not in ALL_STATES:
            raise ValueError(
                f"Invalid status_filter {status_filter!r}. "
                f"Valid states: {sorted(ALL_STATES)}"
            )

        rows: list[dict] = []
        if not self.root.exists():
            return rows

        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            yaml_path = child / "experiment.yaml"
            if not yaml_path.exists():
                continue
            try:
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            status = _extract_status(data)
            if status_filter and status != status_filter:
                continue
            created_ts = datetime.fromtimestamp(
                child.stat().st_ctime, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
            updated_ts = datetime.fromtimestamp(
                yaml_path.stat().st_mtime, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
            rows.append(
                {
                    "id": child.name,
                    "name": _extract_name(data),
                    "status": status,
                    "created": created_ts,
                    "updated": updated_ts,
                }
            )

        rows.sort(key=lambda r: r["updated"], reverse=True)
        return rows

    # ----------------------------------------------------------------- analyses

    def save_analysis(
        self, experiment_id: str, analysis_result: dict
    ) -> Path:
        """Append a timestamped analysis JSON file under analyses/."""
        if not isinstance(analysis_result, dict):
            raise TypeError(
                f"analysis_result must be a dict, got {type(analysis_result).__name__}."
            )
        if not self._yaml_path(experiment_id).exists():
            raise FileNotFoundError(
                f"Cannot save analysis for unknown experiment {experiment_id!r}. "
                "Hint: save_experiment() first."
            )

        analyses_dir = self._analyses_dir(experiment_id)
        ts = _timestamp_str()
        out_path = analyses_dir / f"{ts}.json"
        # In the (extremely unlikely) event of a same-microsecond collision,
        # append a disambiguating counter.
        counter = 0
        while out_path.exists():
            counter += 1
            out_path = analyses_dir / f"{ts}-{counter}.json"

        payload = dict(analysis_result)
        payload.setdefault("analyzed_at", _iso_now())
        payload.setdefault("experiment_id", experiment_id)

        _atomic_write_text(
            out_path, json.dumps(payload, indent=2, sort_keys=True, default=str)
        )
        _append_jsonl(
            self._log_path(experiment_id),
            {
                "ts": _iso_now(),
                "event": "analysis_saved",
                "path": str(out_path.relative_to(self.root)),
            },
        )
        return out_path

    def load_latest_analysis(self, experiment_id: str) -> dict | None:
        analyses_dir = self._analyses_dir(experiment_id)
        if not analyses_dir.exists():
            return None
        files = sorted(
            [p for p in analyses_dir.iterdir() if p.suffix == ".json"],
            key=lambda p: p.name,
        )
        if not files:
            return None
        latest = files[-1]
        try:
            return json.loads(latest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Latest analysis file {latest} is corrupt: {e}"
            ) from e

    # ------------------------------------------------------------- interpretation

    def save_interpretation(
        self, experiment_id: str, interpretation: dict
    ) -> Path:
        """Store the Ship/Investigate/Abort/Learn/Invalid decision."""
        if not isinstance(interpretation, dict):
            raise TypeError(
                f"interpretation must be a dict, got {type(interpretation).__name__}."
            )
        if not self._yaml_path(experiment_id).exists():
            raise FileNotFoundError(
                f"Cannot save interpretation for unknown experiment {experiment_id!r}. "
                "Hint: save_experiment() first."
            )
        valid = {"SHIP", "INVESTIGATE", "ABORT", "LEARN", "INVALID"}
        classification = interpretation.get("classification")
        if classification is not None and classification not in valid:
            raise ValueError(
                f"Invalid interpretation.classification {classification!r}. "
                f"Must be one of {sorted(valid)}."
            )

        payload = dict(interpretation)
        payload.setdefault("decided_at", _iso_now())
        payload.setdefault("experiment_id", experiment_id)

        path = self._interpretation_path(experiment_id)
        _atomic_write_text(
            path, json.dumps(payload, indent=2, sort_keys=True, default=str)
        )
        _append_jsonl(
            self._log_path(experiment_id),
            {
                "ts": _iso_now(),
                "event": "interpretation_saved",
                "classification": classification,
            },
        )
        return path

    # -------------------------------------------------------------------- report

    def save_report(self, experiment_id: str, report_md: str) -> Path:
        if not isinstance(report_md, str):
            raise TypeError(
                f"report_md must be a str, got {type(report_md).__name__}."
            )
        if not self._yaml_path(experiment_id).exists():
            raise FileNotFoundError(
                f"Cannot save report for unknown experiment {experiment_id!r}. "
                "Hint: save_experiment() first."
            )
        path = self._report_path(experiment_id)
        _atomic_write_text(path, report_md)
        _append_jsonl(
            self._log_path(experiment_id),
            {"ts": _iso_now(), "event": "report_saved"},
        )
        return path

    # --------------------------------------------------------------------- log

    def history(self, experiment_id: str) -> list[dict]:
        """Return the full append-only event log for an experiment."""
        log_path = self._log_path(experiment_id)
        if not log_path.exists():
            if not self._exp_dir(experiment_id).exists():
                raise FileNotFoundError(
                    f"No experiment directory for {experiment_id!r}. "
                    "Hint: save_experiment() first."
                )
            return []
        events: list[dict] = []
        with open(log_path, "r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError as e:
                    raise RuntimeError(
                        f"log.jsonl for {experiment_id!r} corrupt on line {lineno}: {e}"
                    ) from e
        return events

    # ------------------------------------------------------------------ delete

    def delete_experiment(
        self, experiment_id: str, confirm: bool = False
    ) -> None:
        if not confirm:
            raise ValueError(
                f"Refusing to delete experiment {experiment_id!r} without confirm=True. "
                "Hint: delete_experiment(id, confirm=True)."
            )
        exp_dir = self._exp_dir(experiment_id)
        if not exp_dir.exists():
            raise FileNotFoundError(
                f"No experiment directory for {experiment_id!r} at {exp_dir}."
            )
        # Recursive rmdir — stdlib.
        import shutil

        shutil.rmtree(exp_dir)


def store_from_env() -> ExperimentStore:
    """Construct an ExperimentStore using OPENXP_STORE env var or default root."""
    root = os.environ.get("OPENXP_STORE", DEFAULT_ROOT)
    return ExperimentStore(root=root)
