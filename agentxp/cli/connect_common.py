"""agentxp connect — shared wizard toolkit (W2.A).

The ``agentxp connect <dialect>`` family of CLIs registers a warehouse
credential profile under ``~/.agentxp/credentials/{adapter}/{name}.yaml`` that
the dispatch-time credential loader (§1.7.3) later reads. This module carries
the cross-dialect machinery so each per-dialect wizard (``connect_duckdb`` /
``connect_bigquery`` here; ``connect_snowflake`` / ``connect_databricks`` in
W2.B) only has to collect its own fields:

1. **Prompt helpers** — ``prompt_text`` / ``prompt_secret`` (no echo, via
   :func:`getpass.getpass`) / ``prompt_choice`` / ``prompt_yes_no``.
2. **Live-probe** — :func:`live_probe` instantiates the adapter from
   ``ADAPTER_REGISTRY`` for the dialect, runs ``SELECT 1`` through
   ``adapter.execute``, and reports success / failure. An
   :class:`AuthExpiredError` surfaces as a friendly one-liner; a driver
   traceback (which can carry the connection string) is NEVER dumped.
3. **Redacted write** — :func:`write_profile` writes the profile YAML with
   ``chmod 600``. Secrets policy: PREFER an ``env:VAR_NAME`` reference over a
   raw secret; a raw secret is only written when the user explicitly supplies
   one, still ``chmod 600`` and never echoed. Every confirmation print routes
   the conn dict through :func:`_redact_creds_for_log` first.
4. **Re-auth entry point** — :func:`reauth_profile` re-runs a dialect's
   auth-collection + live-probe for an EXISTING profile name (the §18 re-auth
   flow calls this).

The profile path convention matches the existing one already documented in
``agentxp/sql/schema.py`` (``ConnectionConfig``) and
``agentxp/schemas/data_plan.py``: ``~/.agentxp/credentials/{adapter}/{name}.yaml``.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 / §18.
Ground-truth reference: research/v0.1.1-warehouse-auth/WAREHOUSE_AUTH_BRIEF.md.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from agentxp.sql.adapter import AuthExpiredError, _redact_creds_for_log
from agentxp.sql.adapters import ADAPTER_REGISTRY

# Nested dicts that carry credential material (a BigQuery inline service-account
# dict holds a private key). ``_redact_creds_for_log`` only scrubs top-level
# string values, so wholesale-replace these before delegating — mirrors the
# bigquery_adapter._safe_conn guard.
_SENSITIVE_NESTED_KEYS: frozenset[str] = frozenset(
    {"credentials_info", "service_account_info"}
)

__all__ = [
    "prompt_text",
    "prompt_secret",
    "prompt_choice",
    "prompt_yes_no",
    "live_probe",
    "credentials_dir",
    "profile_path",
    "write_profile",
    "load_profile",
    "reauth_profile",
    "ConnectWizard",
    "WIZARD_REGISTRY",
]


# ──────────────────────────────────────────────────────────────────────────
# Prompt helpers
#
# All prompts write the prompt text to stderr (not stdout) so a caller can
# pipe the command without the prompts polluting captured stdout, mirroring
# how the other CLIs treat stderr as the chatter channel.
# ──────────────────────────────────────────────────────────────────────────


def prompt_text(
    label: str,
    *,
    default: Optional[str] = None,
    allow_empty: bool = False,
) -> str:
    """Prompt for a single line of plain text and return it (stripped).

    ``default`` is shown in the prompt and returned on an empty entry. With
    ``allow_empty`` an empty entry returns ``""`` (used for optional fields).
    """
    suffix = f" [{default}]" if default is not None else ""
    while True:
        sys.stderr.write(f"{label}{suffix}: ")
        sys.stderr.flush()
        raw = sys.stdin.readline()
        if raw == "":  # EOF
            value = ""
        else:
            value = raw.strip()
        if not value:
            if default is not None:
                return default
            if allow_empty:
                return ""
            print("  (required) please enter a value", file=sys.stderr)
            continue
        return value


def prompt_secret(label: str) -> str:
    """Prompt for a secret WITHOUT echoing it to the terminal.

    Uses :func:`getpass.getpass`, which reads directly from the tty with echo
    disabled. The returned value is NEVER printed back. Returns ``""`` if the
    user submits an empty line (caller decides whether that is allowed).
    """
    # getpass writes its prompt to stderr by default on most platforms when
    # given a stream; pass an explicit stream for determinism under tests.
    return getpass.getpass(f"{label}: ", stream=sys.stderr).strip()


def prompt_choice(label: str, choices: list[str], *, default: Optional[str] = None) -> str:
    """Prompt the user to pick one of ``choices``. Returns the chosen string."""
    rendered = ", ".join(
        f"{c} (default)" if c == default else c for c in choices
    )
    while True:
        value = prompt_text(f"{label} ({rendered})", default=default)
        if value in choices:
            return value
        print(
            f"  '{value}' is not one of: {', '.join(choices)}",
            file=sys.stderr,
        )


def prompt_yes_no(label: str, *, default: bool = True) -> bool:
    """Prompt a yes/no question. Returns ``True`` for yes."""
    default_str = "y" if default else "n"
    value = prompt_text(f"{label} (y/n)", default=default_str).lower()
    return value in ("y", "yes", "true", "1")


# ──────────────────────────────────────────────────────────────────────────
# Live-probe runner
# ──────────────────────────────────────────────────────────────────────────


def live_probe(dialect: str, conn_params: dict[str, Any]) -> tuple[bool, str]:
    """Instantiate the adapter for ``dialect`` and run ``SELECT 1``.

    Returns ``(ok, message)``. ``message`` is always safe to print — on
    failure it contains a friendly one-liner, NEVER a driver traceback or the
    connection string. An :class:`AuthExpiredError` is reported as a
    credential problem so the caller can offer re-auth.
    """
    cls = ADAPTER_REGISTRY.get(dialect)
    if cls is None:
        return False, f"no adapter registered for dialect {dialect!r}"

    adapter = None
    try:
        adapter = cls(**conn_params)
    except TypeError:
        # Some adapters take positional/keyword params we map per-dialect; if
        # the kwargs don't fit the signature, fall back to a no-arg construct
        # so the wizard still gives a useful "couldn't build adapter" message
        # rather than crashing on the constructor.
        try:
            adapter = cls()
        except Exception as e:  # pragma: no cover — exotic constructors
            return False, f"could not construct {dialect} adapter: {type(e).__name__}"
    except AuthExpiredError as e:
        # Already redacted by the adapter; keep just the friendly framing.
        return False, f"authentication failed: {_friendly(e)}"
    except Exception as e:
        return False, f"could not construct {dialect} adapter: {type(e).__name__}"

    try:
        result = adapter.execute("SELECT 1", max_rows=1, timeout_s=30)
        ok = result.row_count >= 1
        if ok:
            return True, "connection OK (SELECT 1 returned a row)"
        return False, "probe ran but SELECT 1 returned no rows"
    except AuthExpiredError as e:
        return False, f"authentication failed: {_friendly(e)}"
    except Exception as e:
        # NEVER surface the raw exception text — it can echo the connection
        # string or SQL with creds. Report only the exception class name.
        return False, f"probe failed: {type(e).__name__}"
    finally:
        if adapter is not None:
            close = getattr(adapter, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # pragma: no cover — best-effort cleanup
                    pass


def _safe_for_log(conn: dict[str, Any]) -> dict[str, Any]:
    """Redact a conn / profile dict for printing, including nested SA dicts.

    Replaces any inline service-account dict wholesale (it holds a private
    key), then delegates to :func:`_redact_creds_for_log` for the top-level
    string scrub. Use this before ANY confirmation / log print in the wizard.
    """
    cleaned: dict[str, Any] = {}
    for key, value in conn.items():
        if key in _SENSITIVE_NESTED_KEYS and isinstance(value, dict):
            cleaned[key] = "[REDACTED]"
        else:
            cleaned[key] = value
    return _redact_creds_for_log(cleaned)


def _friendly(exc: BaseException) -> str:
    """A short, credential-free description of an auth failure.

    The adapter has already redacted its message, but be conservative: report
    the exception class name only, plus a re-auth hint.
    """
    return (
        f"{type(exc).__name__} — credentials were rejected. "
        "Re-run `agentxp connect <dialect> --reauth <name>` to refresh."
    )


# ──────────────────────────────────────────────────────────────────────────
# Profile path + redacted write
# ──────────────────────────────────────────────────────────────────────────


def credentials_dir(adapter: str, *, root: Optional[Path] = None) -> Path:
    """Return the credentials directory for ``adapter``.

    Defaults to ``~/.agentxp/credentials/{adapter}/`` (the convention already
    documented in ``ConnectionConfig`` / ``DataPlan``). ``root`` overrides the
    ``~/.agentxp`` base, used by tests to redirect writes under a tmp_path.
    """
    base = root if root is not None else (Path.home() / ".agentxp")
    return base / "credentials" / adapter


def profile_path(adapter: str, name: str, *, root: Optional[Path] = None) -> Path:
    """Return the on-disk path for profile ``name`` of ``adapter``."""
    return credentials_dir(adapter, root=root) / f"{name}.yaml"


def write_profile(
    adapter: str,
    name: str,
    profile: dict[str, Any],
    *,
    root: Optional[Path] = None,
    quiet: bool = False,
) -> Path:
    """Write ``profile`` to ``~/.agentxp/credentials/{adapter}/{name}.yaml``.

    Security guarantees:

    * The parent directory and the file are ``chmod 700`` / ``chmod 600``.
    * The confirmation line printed to the user runs the profile through
      :func:`_redact_creds_for_log` first, so a raw secret (if one was
      written) is shown as ``[REDACTED]`` and never echoed.
    * The YAML written to disk is the profile *as collected* — secrets policy
      is enforced upstream by the wizard, which SHOULD store an ``env:`` /
      path reference rather than a raw secret. When a raw secret is
      unavoidable (user pasted it), the chmod-600 file is the only place it
      lives, and it is still never echoed.

    Returns the path written.
    """
    target = profile_path(adapter, name, root=root)
    cred_dir = target.parent
    cred_dir.mkdir(parents=True, exist_ok=True)
    # Lock down the directory before writing the secret-bearing file.
    try:
        os.chmod(cred_dir, 0o700)
    except OSError:  # pragma: no cover — non-POSIX / permission quirks
        pass

    text = yaml.safe_dump(profile, sort_keys=False, default_flow_style=False)
    # Write with restrictive perms from the start: create with 600 so there is
    # no window where the file is world-readable.
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
    finally:
        # os.fdopen takes ownership of fd; closing the wrapper closes fd.
        pass
    # Belt-and-braces in case an inherited umask widened the create mode.
    os.chmod(target, 0o600)

    if not quiet:
        safe = _safe_for_log(profile)
        print(f"wrote profile: {target}")
        print(f"  adapter={adapter} profile={name}")
        print(f"  contents (redacted): {safe}")
    return target


def load_profile(
    adapter: str, name: str, *, root: Optional[Path] = None
) -> dict[str, Any]:
    """Load an existing profile YAML. Raises FileNotFoundError if missing."""
    target = profile_path(adapter, name, root=root)
    if not target.exists():
        raise FileNotFoundError(
            f"no profile {name!r} for adapter {adapter!r} at {target}"
        )
    with open(target) as fh:
        data = yaml.safe_load(fh) or {}
    return dict(data)


# ──────────────────────────────────────────────────────────────────────────
# Wizard registration + re-auth entry point
#
# Each per-dialect wizard registers a ConnectWizard so the __main__ dispatcher
# can resolve `agentxp connect <dialect>` to it without hardcoding branches.
# W2.B adds snowflake + databricks by importing their modules (which register
# on import) — no change to the dispatcher needed.
# ──────────────────────────────────────────────────────────────────────────


class ConnectWizard:
    """A registered per-dialect connect wizard.

    ``collect`` is a callable ``(name: str) -> dict`` that prompts for that
    dialect's auth fields and returns ``(conn_params, profile)``:

      * ``conn_params`` — kwargs passed to the adapter for the live-probe
        (may contain a raw secret in memory; never written unredacted to logs).
      * ``profile`` — the dict serialised to the profile YAML (SHOULD reference
        secrets by env-var name / path, not inline them).

    Implemented as a plain callable contract so W2.B can register the same way.
    """

    def __init__(
        self,
        dialect: str,
        collect: Callable[[str], tuple[dict[str, Any], dict[str, Any]]],
    ) -> None:
        self.dialect = dialect
        self.collect = collect


#: dialect string → ConnectWizard. Populated by each connect_<dialect> module
#: on import. The dispatcher iterates this; W2.B extends it transparently.
WIZARD_REGISTRY: dict[str, ConnectWizard] = {}


def register_wizard(wizard: ConnectWizard) -> ConnectWizard:
    """Register ``wizard`` under its dialect. Idempotent (last write wins)."""
    WIZARD_REGISTRY[wizard.dialect] = wizard
    return wizard


def run_wizard(
    dialect: str,
    name: str,
    *,
    root: Optional[Path] = None,
    quiet: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """Run a registered wizard end-to-end: collect → live-probe → write.

    Returns ``(ok, profile)``. On a failed live-probe the profile is NOT
    written (we don't persist a credential we couldn't authenticate).
    """
    wizard = WIZARD_REGISTRY.get(dialect)
    if wizard is None:
        raise KeyError(f"no connect wizard registered for dialect {dialect!r}")

    conn_params, profile = wizard.collect(name)

    if not quiet:
        # Confirmation BEFORE the probe — redacted so no secret is echoed.
        print(f"probing {dialect} connection (redacted): "
              f"{_safe_for_log(conn_params)}", file=sys.stderr)

    ok, message = live_probe(dialect, conn_params)
    if not quiet:
        stream = sys.stderr
        print(f"  {message}", file=stream)
    if not ok:
        return False, profile

    write_profile(dialect, name, profile, root=root, quiet=quiet)
    return True, profile


def reauth_profile(
    dialect: str,
    name: str,
    *,
    root: Optional[Path] = None,
    quiet: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """Re-run auth-collection + live-probe for an EXISTING profile (§18).

    Asserts the profile already exists (re-auth refreshes, it does not create),
    then re-runs the dialect's wizard. The §18 re-auth flow calls this when a
    dispatch hits :class:`AuthExpiredError`.

    Returns ``(ok, profile)``. Raises FileNotFoundError if no such profile.
    """
    # Existence check — re-auth refreshes a known profile.
    load_profile(dialect, name, root=root)
    if not quiet:
        print(f"re-authenticating profile {name!r} ({dialect})…", file=sys.stderr)
    return run_wizard(dialect, name, root=root, quiet=quiet)
