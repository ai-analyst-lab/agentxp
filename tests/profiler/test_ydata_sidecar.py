"""Tests for agentxp.profiler.ydata_sidecar (W_pre2.3)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def test_module_loads_without_ydata():
    """The sidecar module must be importable even if ydata is not installed."""
    # Force a fresh import so we don't rely on cached state.
    mod_name = "agentxp.profiler.ydata_sidecar"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    mod = importlib.import_module(mod_name)
    assert hasattr(mod, "run_ydata_deep_profile")


def test_import_error_message_when_ydata_missing(monkeypatch, tmp_path):
    """When ydata_profiling cannot be imported, raise ImportError with the install hint."""
    from agentxp.profiler import ydata_sidecar

    # Force the deferred import inside run_ydata_deep_profile to fail by
    # blocking ydata_profiling in sys.modules.
    monkeypatch.setitem(sys.modules, "ydata_profiling", None)

    # Make a dummy file path so we get past arg validation; the import
    # failure must trigger before file IO.
    dummy_file = tmp_path / "dummy.parquet"
    dummy_file.write_bytes(b"")

    with pytest.raises(ImportError) as excinfo:
        ydata_sidecar.run_ydata_deep_profile(
            "dummy",
            file_path=dummy_file,
            html_output_path=tmp_path / "out.html",
        )
    assert "pip install 'agentxp[deep-profile]'" in str(excinfo.value)


def test_warehouse_path_not_implemented(tmp_path):
    """file_path=None should raise NotImplementedError with the v0.1.1 message.

    This must surface only when ydata IS importable — if ydata is missing,
    the ImportError fires first (as designed). We skip in that case.
    """
    pytest.importorskip("ydata_profiling")
    from agentxp.profiler import ydata_sidecar

    with pytest.raises(NotImplementedError) as excinfo:
        ydata_sidecar.run_ydata_deep_profile(
            "warehouse.schema.table",
            file_path=None,
            html_output_path=tmp_path / "out.html",
        )
    assert "v0.1.1" in str(excinfo.value)


def test_run_ydata_deep_profile_parquet_smoke(tmp_path):
    """Smoke test: 100-row parquet → HTML report > 1KB."""
    pytest.importorskip("ydata_profiling")
    import pandas as pd

    from agentxp.profiler import ydata_sidecar

    df = pd.DataFrame(
        {
            "a": list(range(100)),
            "b": [i * 0.5 for i in range(100)],
            "c": ["x", "y"] * 50,
        }
    )
    src = tmp_path / "data.parquet"
    df.to_parquet(src)

    html_out = tmp_path / "report.html"
    result = ydata_sidecar.run_ydata_deep_profile(
        "smoke",
        file_path=src,
        html_output_path=html_out,
        minimal=True,
    )

    assert result == html_out
    assert html_out.exists()
    assert html_out.stat().st_size > 1024
