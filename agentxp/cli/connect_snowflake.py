"""agentxp connect snowflake — register a Snowflake credential profile (W2.B).

Snowflake exposes four auth surfaces (WAREHOUSE_AUTH_BRIEF §1), so this is the
most branchy wizard. It first collects the common connection fields
(``account``, ``user``, ``warehouse``, ``database``, ``schema``, ``role``) then
the chosen auth method:

  * **password** (``auth_method="password"``) — ``prompt_secret`` for the
    password. SECRET.
  * **externalbrowser** (``auth_method="externalbrowser"``) — browser SSO; no
    secret is collected (the connector opens a browser at connect time).
  * **oauth** (``auth_method="oauth"``) — ``prompt_secret`` for an OAuth bearer
    ``token``. SECRET.
  * **keypair** (``auth_method="keypair"``) — a ``private_key_file`` path plus
    an optional ``private_key_file_pwd`` passphrase. The path is stored as a
    *reference*; the passphrase (SECRET) is only written to the chmod-600 file
    and is never echoed.

``auth_method`` is stored in the profile so the adapter's
``_resolve_auth_method`` picks the surface directly. The wizard live-probes via
:func:`connect_common.live_probe` and writes a redacted profile (chmod 600).

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 / §18.
Ground truth: research/v0.1.1-warehouse-auth/WAREHOUSE_AUTH_BRIEF.md §1.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional

from agentxp.cli.connect_common import (
    ConnectWizard,
    collect_secret,
    prompt_choice,
    prompt_secret,
    prompt_text,
    reauth_profile,
    register_wizard,
    run_wizard,
)
from agentxp.cli.exit_codes import EXIT_FATAL, EXIT_OK, EXIT_USER_ERROR

__all__ = ["main", "collect"]

DIALECT = "snowflake"

#: Auth surfaces the adapter understands (SnowflakeAdapter._resolve_auth_method).
_AUTH_METHODS = ["password", "externalbrowser", "oauth", "keypair"]


def collect(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prompt for Snowflake connection details across the four auth surfaces.

    Returns ``(conn_params, profile)``:
      * ``conn_params`` — kwargs for ``SnowflakeAdapter``: the common fields plus
        ``auth_method`` and the per-method secret (``password`` / ``token`` /
        ``private_key_file`` + ``private_key_file_pwd``).
      * ``profile`` — YAML-serialisable. The key-file PATH is stored as a
        reference; secrets that the user explicitly supplies (password / token /
        key passphrase) live only in the chmod-600 profile and are never echoed.
    """
    # Common, non-secret connection fields. account / user / warehouse are the
    # ones a probe actually needs; database / schema / role are optional.
    account = prompt_text(
        "Snowflake account identifier (e.g. myorg-myaccount, no domain suffix)"
    )
    user = prompt_text("User")
    warehouse = prompt_text("Warehouse (e.g. WH_XS)", allow_empty=True)
    database = prompt_text("Database (e.g. ANALYTICS)", allow_empty=True)
    schema = prompt_text("Schema (e.g. PUBLIC)", allow_empty=True)
    role = prompt_text("Role (optional)", allow_empty=True)

    auth_method = prompt_choice(
        "Auth method", _AUTH_METHODS, default="password"
    )

    # Shared, non-secret fields go into both dicts.
    conn_params: dict[str, Any] = {
        "account": account,
        "user": user,
        "auth_method": auth_method,
    }
    profile: dict[str, Any] = {
        "schema_version": 1,
        "adapter": DIALECT,
        "auth_kind": auth_method,
        "auth_method": auth_method,
        "profile_name": name,
        "account": account,
        "user": user,
    }
    # Optional non-secret fields — only set when supplied.
    for key, value in (
        ("warehouse", warehouse),
        ("database", database),
        ("schema", schema),
        ("role", role),
    ):
        if value:
            conn_params[key] = value
            profile[key] = value

    if auth_method == "password":
        # The raw secret stays in conn_params (in-memory, for the live probe);
        # the profile records an env-var reference by default (raw value only
        # if the user explicitly opts to store it inline in the 600 file).
        raw, stored = collect_secret(
            "Password",
            profile_name=name,
            field="password",
            adapter=DIALECT,
        )
        conn_params["password"] = raw
        profile["password"] = stored

    elif auth_method == "externalbrowser":
        print(
            "External-browser SSO: a browser will open for IdP login at connect "
            "time. No secret is stored.",
            file=sys.stderr,
        )
        # The adapter selects the surface from auth_method; no secret needed.

    elif auth_method == "oauth":
        raw, stored = collect_secret(
            "OAuth access token",
            profile_name=name,
            field="token",
            adapter=DIALECT,
        )
        conn_params["token"] = raw
        profile["token"] = stored

    elif auth_method == "keypair":
        key_path_str = prompt_text("Path to private key file (PEM/P8)")
        key_path = str(Path(key_path_str).expanduser())
        conn_params["private_key_file"] = key_path
        # Store the key-file PATH as a reference (not its contents).
        profile["private_key_file"] = key_path

        raw, stored = collect_secret(
            "Private key passphrase (leave empty if the key is unencrypted)",
            profile_name=name,
            field="private_key_file_pwd",
            adapter=DIALECT,
            required=False,
        )
        if raw is not None:
            conn_params["private_key_file_pwd"] = raw
            profile["private_key_file_pwd"] = stored

    else:  # pragma: no cover — prompt_choice already constrains the value.
        raise ValueError(f"unknown auth method {auth_method!r}")

    return conn_params, profile


# Register on import so the dispatcher resolves `connect snowflake` to us.
register_wizard(ConnectWizard(DIALECT, collect))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp connect snowflake",
        description=(
            "Register a Snowflake credential profile under "
            "~/.agentxp/credentials/snowflake/. Prompts for the common "
            "connection fields and one of four auth methods (password / "
            "externalbrowser / oauth / keypair), live-probes with SELECT 1, "
            "and writes the profile (secrets are never echoed)."
        ),
    )
    parser.add_argument(
        "name",
        help="Profile name (e.g. 'prod', 'dev'). Stored as {name}.yaml.",
    )
    parser.add_argument(
        "--reauth",
        action="store_true",
        help="Refresh an EXISTING profile (re-run collect + live-probe).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-error output.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point. Returns an EXIT_* code (see exit_codes.py)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.reauth:
            ok, _ = reauth_profile(DIALECT, args.name, quiet=args.quiet)
        else:
            ok, _ = run_wizard(DIALECT, args.name, quiet=args.quiet)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return EXIT_USER_ERROR
    except ValueError as e:
        # Missing required secret, etc. — user error, message carries no secret.
        print(str(e), file=sys.stderr)
        return EXIT_USER_ERROR
    except KeyboardInterrupt:  # pragma: no cover — interactive abort
        print("\naborted", file=sys.stderr)
        return EXIT_USER_ERROR
    except Exception as e:
        print(f"unexpected error: {type(e).__name__}", file=sys.stderr)
        return EXIT_FATAL

    if not ok:
        print("connection probe failed — profile not written", file=sys.stderr)
        return EXIT_USER_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
