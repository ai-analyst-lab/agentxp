"""ydata-profiling deep sidecar (W_pre2.3).

Optional power-user path for the profiler. The default ``openxp profile``
command (W_pre2.4) runs the fast DuckDB SUMMARIZE-based profiler. When the
user passes ``--deep``, the CLI invokes :func:`run_ydata_deep_profile` to
generate a full ydata-profiling HTML (and optional JSON) report with
histograms, correlations, alerts, etc.

ydata-profiling is an optional dependency (``pip install 'openxp[deep-profile]'``);
this module must remain importable even when it is not installed. The
``ydata_profiling`` import is therefore deferred into the function body.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _chmod_600(path: Path) -> None:
    """Best-effort restrict file perms to user-only read/write.

    Matches the rest of the bundle substrate (profile JSON, etc.).
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Non-POSIX filesystems may not support chmod; the report still works.
        pass


def run_ydata_deep_profile(
    source_ref: str,
    *,
    file_path: Optional[Path] = None,
    html_output_path: Path,
    json_output_path: Optional[Path] = None,
    title: Optional[str] = None,
    minimal: bool = False,
) -> Path:
    """Generate a deep profile via ydata-profiling.

    Parameters
    ----------
    source_ref:
        Human-readable identifier for the source (e.g. a warehouse table
        name or a file path). Used in the report title when ``title`` is
        not supplied.
    file_path:
        Local file to profile. Extension dispatches to the pandas reader
        (``.parquet``, ``.csv``, ``.json``, ``.jsonl``). If ``None``, the
        function raises :class:`NotImplementedError` — warehouse table
        deep profiling ships in v0.1.1.
    html_output_path:
        Destination path for the HTML report.
    json_output_path:
        Optional destination for a JSON dump of the same report. ydata
        auto-detects the ``.json`` extension.
    title:
        Optional report title. Defaults to ``f"Deep profile: {source_ref}"``.
    minimal:
        Forwarded to ``ProfileReport(minimal=...)``. Skips the more
        expensive correlations/interactions for very wide tables.

    Returns
    -------
    Path
        The HTML report path that was written.

    Raises
    ------
    ImportError
        If ``ydata-profiling`` is not installed.
    NotImplementedError
        If ``file_path`` is ``None`` (warehouse path not yet implemented).
    """
    try:
        from ydata_profiling import ProfileReport as YProfileReport
    except ImportError as e:
        raise ImportError(
            "ydata-profiling is not installed. Install with:\n"
            "    pip install 'openxp[deep-profile]'\n"
            "Then re-run with --deep."
        ) from e

    if file_path is None:
        raise NotImplementedError(
            "ydata deep profile of warehouse tables ships in v0.1.1"
        )

    import pandas as pd

    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    if suffix == ".parquet":
        df = pd.read_parquet(file_path)
    elif suffix == ".csv":
        df = pd.read_csv(file_path)
    elif suffix == ".json":
        df = pd.read_json(file_path)
    elif suffix == ".jsonl":
        df = pd.read_json(file_path, lines=True)
    else:
        raise ValueError(
            f"Unsupported file extension for deep profile: {suffix!r}. "
            "Supported: .parquet, .csv, .json, .jsonl"
        )

    report = YProfileReport(
        df,
        title=title or f"Deep profile: {source_ref}",
        minimal=minimal,
    )

    html_output_path = Path(html_output_path)
    html_output_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_file(html_output_path)
    _chmod_600(html_output_path)

    if json_output_path is not None:
        json_output_path = Path(json_output_path)
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        report.to_file(json_output_path)  # ydata auto-detects .json extension
        _chmod_600(json_output_path)

    return html_output_path
