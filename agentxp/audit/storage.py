"""Audit storage primitives.

In v3 the audit surface is git (every commit_artifact runs a git commit)
plus a human-readable ``experiments/<id>/log.md``. The structured
``log.jsonl`` event log + 9-field action receipt machinery from v0.1 are
deleted (T114); this module retains only the small atomic-file-write
helper that the renders catalog still uses.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


_FILE_MODE = 0o600  # owner read/write only; v0.1 secrets policy preserved


def _atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    mode: int = _FILE_MODE,
) -> None:
    """Write ``data`` to ``path`` atomically, chmod 600 by default.

    Strategy: open a temp file in the same directory, write + fsync, chmod,
    then ``os.replace`` onto the target. POSIX guarantees a reader sees
    either the old bytes or the new bytes, never a torn write.

    The ``mode`` kwarg is preserved from v0.1 callers; default is 0o600.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


__all__ = ["_atomic_write_bytes"]
