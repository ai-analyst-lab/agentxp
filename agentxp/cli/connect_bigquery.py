"""agentxp connect bigquery — register a BigQuery credential profile (W2.A).

Two auth surfaces (WAREHOUSE_AUTH_BRIEF §2):

  * **ADC** (``auth_kind="adc"``) — Application Default Credentials. No key
    material in the app; the user confirms ADC is configured (env var
    ``GOOGLE_APPLICATION_CREDENTIALS`` / ``gcloud auth application-default
    login`` / attached SA on GCP compute). The safer default.
  * **Service-account JSON** (``auth_kind="sa"``) — either a path to a key
    file on disk (preferred: the profile stores the *path*, not the key) or an
    inline dict the user explicitly pastes. An inline private key is only ever
    written to the chmod-600 profile and is NEVER echoed back.

Live-probes with ``SELECT 1`` and writes to
``~/.agentxp/credentials/bigquery/{name}.yaml``.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 / §18.
Ground-truth: research/v0.1.1-warehouse-auth/WAREHOUSE_AUTH_BRIEF.md §2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from agentxp.cli.connect_common import (
    ConnectWizard,
    prompt_choice,
    prompt_secret,
    prompt_text,
    prompt_yes_no,
    reauth_profile,
    register_wizard,
    run_wizard,
)
from agentxp.cli.exit_codes import EXIT_FATAL, EXIT_OK, EXIT_USER_ERROR

__all__ = ["main", "collect"]

DIALECT = "bigquery"


def collect(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prompt for BigQuery connection details (ADC vs service-account JSON).

    Returns ``(conn_params, profile)``:
      * ``conn_params`` — kwargs for ``BigQueryAdapter`` (``project`` plus, for
        SA, ``credentials_path`` or ``credentials_info``).
      * ``profile`` — YAML-serialisable. SA path is stored as a *reference*;
        an inline SA dict is only stored when the user explicitly pasted one.
    """
    project = prompt_text("GCP project id")

    auth_kind = prompt_choice(
        "Auth method",
        ["adc", "sa"],
        default="adc",
    )

    if auth_kind == "adc":
        print(
            "Using Application Default Credentials. Ensure ADC is configured "
            "(GOOGLE_APPLICATION_CREDENTIALS, `gcloud auth "
            "application-default login`, or an attached service account).",
            file=sys.stderr,
        )
        conn_params: dict[str, Any] = {"project": project}
        profile: dict[str, Any] = {
            "schema_version": 1,
            "adapter": DIALECT,
            "auth_kind": "adc",
            "profile_name": name,
            "project_id": project,
        }
        return conn_params, profile

    # auth_kind == "sa": file path (preferred) or inline paste.
    use_inline = prompt_yes_no(
        "Paste the service-account JSON inline? (No = give a file path)",
        default=False,
    )

    if not use_inline:
        sa_path = prompt_text("Path to service-account JSON key file")
        resolved = str(Path(sa_path).expanduser())
        conn_params = {"project": project, "credentials_path": resolved}
        profile = {
            "schema_version": 1,
            "adapter": DIALECT,
            "auth_kind": "sa",
            "profile_name": name,
            "project_id": project,
            # Store a REFERENCE to the key file, not its contents.
            "credentials_path": resolved,
        }
        return conn_params, profile

    # Inline paste — the user explicitly chose this. The pasted JSON contains a
    # private key. It is read via the no-echo secret prompt, used in-memory for
    # the live-probe, and written ONLY to the chmod-600 profile. Never echoed.
    print(
        "Paste the full service-account JSON (single line). It will NOT be "
        "echoed and is stored only in the chmod-600 profile file.",
        file=sys.stderr,
    )
    raw = prompt_secret("service-account JSON")
    try:
        sa_info = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"service-account JSON is not valid JSON: {e}") from None
    if not isinstance(sa_info, dict):
        raise ValueError("service-account JSON must be a JSON object")

    conn_params = {"project": project, "credentials_info": sa_info}
    profile = {
        "schema_version": 1,
        "adapter": DIALECT,
        "auth_kind": "sa",
        "profile_name": name,
        "project_id": project,
        # Inline secret: written to the chmod-600 file only. The redacted
        # confirmation print scrubs this (see _redact_creds_for_log).
        "credentials_info": sa_info,
    }
    return conn_params, profile


# Register on import so the dispatcher resolves `connect bigquery` to us.
register_wizard(ConnectWizard(DIALECT, collect))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp connect bigquery",
        description=(
            "Register a BigQuery credential profile under "
            "~/.agentxp/credentials/bigquery/. Prompts for project + auth "
            "(ADC or service-account JSON), live-probes with SELECT 1, and "
            "writes the profile (SA key material is never echoed)."
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
        # Bad inline JSON, etc. — user error, message carries no secret.
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
