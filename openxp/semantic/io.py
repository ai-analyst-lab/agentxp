"""I/O helpers that wrap semantic / metric / fact_source / assignment YAML
read/write with ``project_read_lock`` / ``project_write_lock`` from
W_pre1.12.

Per HG-F3 / H14: agents that write to project-level YAMLs
(``semantic_modeler``, ``metric_drafter``) must hold the project write lock;
orchestrator reads must hold the project read lock. Without this, a reader
mid-write sees a partial document.

Validation is performed via the Pydantic models in
``openxp.semantic.validators``; this module composes locking + atomic write
+ Pydantic ``model_validate`` so callers never see partial state and never
land an invalid YAML on disk.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Type, TypeVar

import yaml
from pydantic import BaseModel

from openxp.orchestrator.project_lock import (
    project_read_lock,
    project_write_lock,
)

T = TypeVar("T", bound=BaseModel)

_FILE_MODE = 0o600  # §1.7.3 secrets policy — owner read/write only


def load_yaml(path: Path, model: Type[T], project_root: Path) -> T:
    """Read + validate a project YAML under a shared read lock.

    Args:
        path: absolute path to the YAML file to read.
        model: Pydantic model class to validate against.
        project_root: project root (the lock file lives at
            ``{project_root}/.openxp/.project.lock``).

    Returns:
        The validated model instance.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        yaml.YAMLError: if the file is not valid YAML.
        pydantic.ValidationError: if the parsed YAML violates ``model``.
        ProjectLockTimeout: if the read lock cannot be acquired in time.
    """
    with project_read_lock(project_root):
        text = path.read_text()
        data = yaml.safe_load(text) or {}
        return model.model_validate(data)


def write_yaml(path: Path, value: BaseModel, project_root: Path) -> None:
    """Write a validated Pydantic model to disk atomically under an
    exclusive project write lock.

    Atomicity strategy: serialize to YAML, write to a tempfile in the same
    directory as ``path``, chmod 600, then ``os.replace`` onto ``path``.
    ``os.replace`` is atomic on POSIX and Windows for same-filesystem
    targets, so readers either see the old file or the new one — never a
    half-written intermediate.

    Args:
        path: absolute destination path. Parent directories are created
            if missing.
        value: a Pydantic model instance to serialize. Must already be
            valid (Pydantic raises on construction, not on write).
        project_root: project root for the write lock.

    Raises:
        ProjectLockTimeout: if the write lock cannot be acquired in time.
        OSError: on filesystem-level failures (disk full, permission, etc.).
    """
    with project_write_lock(project_root):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = yaml.safe_dump(
            value.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=False,
        )
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(payload)
            os.chmod(tmp_path, _FILE_MODE)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


__all__ = ["load_yaml", "write_yaml"]
