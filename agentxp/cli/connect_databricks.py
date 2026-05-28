"""agentxp connect databricks — register a Databricks credential profile (W2.B).

Databricks always needs ``server_hostname`` + ``http_path`` (the connector
requires both). On top of that this wizard collects one of two auth surfaces
(WAREHOUSE_AUTH_BRIEF §3):

  * **PAT** (``auth_method="pat"``) — a Personal Access Token via
    ``prompt_secret``. SECRET. The common, non-interactive path.
  * **OAuth M2M** (``auth_method="oauth_m2m"``) — a service principal:
    ``client_id`` (non-secret) + ``client_secret`` via ``prompt_secret``.
    SECRET.

``auth_method`` is stored in the profile so the adapter's
``_resolve_auth_method`` picks the surface directly. The wizard live-probes via
:func:`connect_common.live_probe` and writes a redacted profile (chmod 600).

Note: the shared ``adapter._SENSITIVE_KEYS`` does not list ``access_token`` /
``client_secret``; ``connect_common._safe_for_log`` (via ``_EXTRA_SECRET_KEYS``)
scrubs them, so confirmation prints never echo either secret.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 / §18.
Ground truth: research/v0.1.1-warehouse-auth/WAREHOUSE_AUTH_BRIEF.md §3.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Optional

from agentxp.cli.connect_common import (
    ConnectWizard,
    collect_secret,
    prompt_choice,
    prompt_text,
    reauth_profile,
    register_wizard,
    run_wizard,
)
from agentxp.cli.exit_codes import EXIT_FATAL, EXIT_OK, EXIT_USER_ERROR

__all__ = ["main", "collect"]

DIALECT = "databricks"

#: Auth surfaces the wizard offers. Maps to DatabricksAdapter auth methods:
#: "pat" -> access_token, "oauth_m2m" -> client_id + client_secret.
_AUTH_METHODS = ["pat", "oauth_m2m"]


def collect(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prompt for Databricks connection details (PAT vs OAuth M2M).

    Returns ``(conn_params, profile)``:
      * ``conn_params`` — kwargs for ``DatabricksAdapter``: ``server_hostname``,
        ``http_path``, ``auth_method`` and the per-method credential
        (``access_token`` or ``client_id`` + ``client_secret``).
      * ``profile`` — YAML-serialisable. Secrets the user supplies (PAT /
        client secret) live only in the chmod-600 profile and are never echoed.
    """
    server_hostname = prompt_text(
        "Server hostname (e.g. adb-1234.5.azuredatabricks.net)"
    )
    http_path = prompt_text(
        "HTTP path (e.g. /sql/1.0/warehouses/abc123)"
    )
    catalog = prompt_text("Unity Catalog (optional, e.g. main)", allow_empty=True)
    schema = prompt_text("Schema (optional, e.g. sales)", allow_empty=True)

    auth_method = prompt_choice("Auth method", _AUTH_METHODS, default="pat")

    conn_params: dict[str, Any] = {
        "server_hostname": server_hostname,
        "http_path": http_path,
        "auth_method": auth_method,
    }
    profile: dict[str, Any] = {
        "schema_version": 1,
        "adapter": DIALECT,
        "auth_kind": auth_method,
        "auth_method": auth_method,
        "profile_name": name,
        "server_hostname": server_hostname,
        "http_path": http_path,
    }
    # Optional Unity Catalog defaults (non-secret).
    for key, value in (("catalog", catalog), ("schema", schema)):
        if value:
            conn_params[key] = value
            profile[key] = value

    if auth_method == "pat":
        # Raw PAT stays in conn_params (in-memory, for the live probe); the
        # profile records an env-var reference by default. access_token is not
        # in adapter._SENSITIVE_KEYS, so connect_common._safe_for_log scrubs it
        # from any confirmation print via _EXTRA_SECRET_KEYS.
        raw, stored = collect_secret(
            "Personal Access Token (PAT)",
            profile_name=name,
            field="access_token",
            adapter=DIALECT,
        )
        conn_params["access_token"] = raw
        profile["access_token"] = stored

    elif auth_method == "oauth_m2m":
        client_id = prompt_text("Service principal client_id (application ID)")
        conn_params["client_id"] = client_id
        # client_id is non-secret; client_secret is SECRET.
        profile["client_id"] = client_id
        raw, stored = collect_secret(
            "Service principal client_secret",
            profile_name=name,
            field="client_secret",
            adapter=DIALECT,
        )
        conn_params["client_secret"] = raw
        profile["client_secret"] = stored

    else:  # pragma: no cover — prompt_choice already constrains the value.
        raise ValueError(f"unknown auth method {auth_method!r}")

    return conn_params, profile


# Register on import so the dispatcher resolves `connect databricks` to us.
register_wizard(ConnectWizard(DIALECT, collect))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp connect databricks",
        description=(
            "Register a Databricks credential profile under "
            "~/.agentxp/credentials/databricks/. Prompts for server hostname + "
            "HTTP path and one of two auth methods (PAT or OAuth M2M service "
            "principal), live-probes with SELECT 1, and writes the profile "
            "(secrets are never echoed)."
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
        print(f"unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_FATAL

    if not ok:
        print("connection probe failed — profile not written", file=sys.stderr)
        return EXIT_USER_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
