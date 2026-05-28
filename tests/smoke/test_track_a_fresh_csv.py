"""Track A — FRESH CSV path smoke tests.

Verifies the plumbing: a tiny CSV fixture flows through ``openxp profile``,
``bundles/profiler.out.yaml`` lands on disk with chmod 600, and the CLI exits
cleanly. We do NOT exercise the LLM dispatch loop here — v0.1's
``dispatch._invoke_llm`` is still stubbed.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.5 (failure modes
the FRESH-CSV path must survive).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from openxp.cli import profile as profile_cli

from tests.smoke.conftest import mode_of


def test_profile_csv_writes_bundle_yaml(
    tmp_path: Path, tiny_csv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CSV in → ``bundles/profiler.out.yaml`` out. Plumbing only."""
    monkeypatch.chdir(tmp_path)
    rc = profile_cli.main([str(tiny_csv), "--quiet"])
    assert rc in (0, 2), f"profile exit code unexpected: {rc}"
    bundle = tmp_path / "bundles" / "profiler.out.yaml"
    assert bundle.exists(), "expected bundles/profiler.out.yaml to be written"
    assert bundle.read_text().strip(), "bundle should not be empty"


def test_profile_bundle_is_chmod_600(
    tmp_path: Path, tiny_csv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§1.7.3 / B9 sweep: profiler.out.yaml must land at chmod 600."""
    monkeypatch.chdir(tmp_path)
    profile_cli.main([str(tiny_csv), "--quiet"])
    bundle = tmp_path / "bundles" / "profiler.out.yaml"
    assert bundle.exists()
    assert mode_of(bundle) == 0o600, (
        f"profiler bundle must be chmod 600; got {oct(mode_of(bundle))}"
    )


def test_profile_missing_csv_surfaces_user_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-existent .csv path must exit with EXIT_USER_ERROR, not crash."""
    monkeypatch.chdir(tmp_path)
    rc = profile_cli.main([str(tmp_path / "does_not_exist.csv"), "--quiet"])
    assert rc != 0, "missing file should not return EXIT_OK"
    # No bundle should have been created.
    assert not (tmp_path / "bundles" / "profiler.out.yaml").exists()


def test_profile_creates_bundles_dir_under_cwd(
    tmp_path: Path, tiny_csv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File-system layout: ``bundles/`` is created under cwd on first run."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "bundles").exists()
    profile_cli.main([str(tiny_csv), "--quiet"])
    assert (tmp_path / "bundles").is_dir()
