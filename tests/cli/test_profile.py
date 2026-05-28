"""Tests for agentxp.cli.profile — W_pre2.4."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from agentxp.cli.exit_codes import (
    EXIT_OK,
    EXIT_USER_ERROR,
    EXIT_WARNING,
)
from agentxp.cli.profile import main


def _write_clean_parquet(path: Path, n_rows: int = 100) -> Path:
    # Build the dataset in DuckDB and write parquet natively — avoids the
    # pyarrow / fastparquet engine that pandas would otherwise need.
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            "CREATE TABLE t AS "
            "SELECT i AS row_pk, "
            "       CAST(i AS DOUBLE) * 1.5 AS amount, "
            "       CASE WHEN i % 2 = 0 THEN 'US' ELSE 'UK' END AS country, "
            "       (i % 2 = 0) AS active "
            f"FROM range(0, {n_rows}) tbl(i)"
        )
        path_str = str(path).replace("'", "''")
        con.execute(f"COPY t TO '{path_str}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def _write_flagged_parquet(path: Path, n_rows: int = 100) -> Path:
    # user_id is identifier-shaped and 60% null → trips HG-D4 F.PRACTICE.01.
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            "CREATE TABLE t AS "
            "SELECT CASE WHEN i < CAST(? AS BIGINT) * 6 / 10 THEN NULL "
            "            ELSE i END AS user_id, "
            "       CAST(i AS DOUBLE) AS amount "
            f"FROM range(0, {n_rows}) tbl(i)",
            [n_rows],
        )
        path_str = str(path).replace("'", "''")
        con.execute(f"COPY t TO '{path_str}' (FORMAT PARQUET)")
    finally:
        con.close()
    return path


def test_main_returns_exit_ok_for_clean_parquet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    rc = main([str(parquet_path)])

    assert rc == EXIT_OK
    assert (tmp_path / "bundles" / "profiler.out.yaml").exists()


def test_main_returns_exit_warning_when_flagged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_flagged_parquet(tmp_path / "flagged.parquet")

    rc = main([str(parquet_path)])

    captured = capsys.readouterr()
    assert rc == EXIT_WARNING, captured.err
    assert "flag:" in captured.err
    assert "user_id" in captured.err


def test_main_returns_exit_user_error_for_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    rc = main(["/nonexistent/file.parquet"])

    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "file not found" in captured.err


def test_main_returns_exit_user_error_for_unsupported_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    rc = main([str(parquet_path), "--adapter", "snowflake"])

    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    # The driver's message mentions the adapter; surface verbatim.
    assert "snowflake" in captured.err.lower() or "adapter" in captured.err.lower()


def test_deep_flag_without_ydata_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    def _raise(*_a, **_kw):
        raise ImportError("install hint: pip install 'agentxp[deep-profile]'")

    monkeypatch.setattr(
        "agentxp.profiler.ydata_sidecar.run_ydata_deep_profile",
        _raise,
    )

    rc = main([str(parquet_path), "--deep"])

    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "install hint" in captured.err


def test_verbose_renders_column_table_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    rc = main(["--verbose", str(parquet_path)])

    captured = capsys.readouterr()
    assert rc == EXIT_OK
    # Column names must show up in the stderr column table.
    assert "row_pk" in captured.err
    assert "amount" in captured.err
    assert "country" in captured.err


def test_quiet_suppresses_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    rc = main(["--quiet", str(parquet_path)])

    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "wrote:" not in captured.out


# ---------------------------------------------------------------------------
# Path-guard tests (W_pre2 Hotfix-3) — bundle / deep-html / deep-json paths
# must resolve under cwd or ~/.agentxp/. Anything else → EXIT_USER_ERROR.
# ---------------------------------------------------------------------------


def test_bundle_under_cwd_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--bundle pointing under cwd should work (sanity check)."""
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    bundle_path = str(tmp_path / "out" / "p.yaml")
    rc = main([str(parquet_path), "--bundle", bundle_path])

    captured = capsys.readouterr()
    assert rc == EXIT_OK, captured.err
    assert (tmp_path / "out" / "p.yaml").exists()


def test_bundle_outside_cwd_and_home_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--bundle pointing outside cwd and outside ~/.agentxp/ → EXIT_USER_ERROR."""
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    # /etc is outside both tmp_path (cwd) and ~/.agentxp/ on any sane system.
    bad_bundle = "/etc/agentxp-evil.yaml"

    rc = main([str(parquet_path), "--bundle", bad_bundle])

    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "--bundle" in captured.err
    assert "must be under" in captured.err
    # And we must NOT have written the file.
    assert not Path(bad_bundle).exists()


def test_bundle_under_agentxp_home_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--bundle under ~/.agentxp/ should work even when cwd is elsewhere."""
    # Make a fake home so we don't pollute the real ~/.agentxp/.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".agentxp").mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # cwd is tmp_path, NOT inside fake_home/.agentxp.
    monkeypatch.chdir(tmp_path)

    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    bundle_path = str(fake_home / ".agentxp" / "p.yaml")
    rc = main([str(parquet_path), "--bundle", bundle_path])

    captured = capsys.readouterr()
    # EXIT_OK or EXIT_WARNING (depends on whether the clean data flags).
    assert rc in (EXIT_OK, EXIT_WARNING), captured.err
    assert (fake_home / ".agentxp" / "p.yaml").exists()


def test_bundle_traversal_dotdot_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--bundle ../../etc/foo.yaml → rejected after resolve()."""
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    rc = main(
        [str(parquet_path), "--bundle", "../../../etc/agentxp.yaml"]
    )

    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "--bundle" in captured.err
    assert "must be under" in captured.err


def test_deep_html_outside_cwd_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--deep-html outside cwd → EXIT_USER_ERROR before any ydata import."""
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    rc = main(
        [
            str(parquet_path),
            "--deep",
            "--deep-html",
            "/etc/agentxp-evil.html",
        ]
    )

    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "--deep-html" in captured.err
    assert "must be under" in captured.err


def test_deep_json_outside_cwd_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--deep-json outside cwd → EXIT_USER_ERROR before any ydata import."""
    monkeypatch.chdir(tmp_path)
    parquet_path = _write_clean_parquet(tmp_path / "clean.parquet")

    rc = main(
        [
            str(parquet_path),
            "--deep",
            "--deep-json",
            "/etc/agentxp-evil.json",
        ]
    )

    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "--deep-json" in captured.err
    assert "must be under" in captured.err
