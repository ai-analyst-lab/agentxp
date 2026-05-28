"""openxp migrate metrics — v1 → v2 metric YAML migration tool.

Reads each metrics/*.yaml and upgrades v1 (existing, no schema_version) to v2
(with schema_version: 2 + fact_source binding). Writes .bak backups before
mutating. Idempotent: running twice is safe.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §30, §1.7.6, §1.8.6.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from openxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR, EXIT_WARNING


def migrate_metric_v1_to_v2(metric_dict: dict) -> tuple[dict, list[str]]:
    """Migrate one metric dict from v1 to v2.

    Returns (new_dict, list_of_changes). If already v2, returns the input
    unchanged with an empty changes list.
    """
    changes: list[str] = []

    if metric_dict.get("schema_version") == 2:
        return metric_dict, []  # already v2

    new_dict = dict(metric_dict)

    # Add schema_version: 2
    new_dict["schema_version"] = 2
    changes.append("added schema_version: 2")

    # Add fact_source field if not present (default to inline placeholder)
    if "fact_source" not in new_dict:
        # v1 had numerator inline; v2 wraps it in a fact_source binding.
        # Best-effort: add an inline placeholder pointer the user updates manually.
        new_dict["fact_source"] = "inline"
        changes.append(
            "added fact_source: inline (placeholder; update to point at fact_sources/*.yaml)"
        )

    return new_dict, changes


def migrate_one_file(path: Path, *, dry_run: bool) -> tuple[bool, list[str]]:
    """Migrate one metric YAML file.

    Returns (was_migrated, list_of_changes). In dry-run mode, no files are written.
    """
    raw_text = path.read_text(encoding="utf-8")
    raw_dict = yaml.safe_load(raw_text)

    if not isinstance(raw_dict, dict):
        return False, [f"{path.name}: not a YAML mapping; skipping"]

    new_dict, changes = migrate_metric_v1_to_v2(raw_dict)

    if not changes:
        return False, [f"{path.name}: already v2, no changes"]

    if dry_run:
        return True, [f"{path.name}: would apply: " + "; ".join(changes)]

    # Write .bak backup first
    bak_path = path.with_suffix(path.suffix + ".bak")
    bak_path.write_text(raw_text, encoding="utf-8")

    # Write the new YAML
    new_text = yaml.safe_dump(new_dict, sort_keys=False, default_flow_style=False)
    path.write_text(new_text, encoding="utf-8")

    return True, [f"{path.name}: migrated ({len(changes)} changes); backup at {bak_path.name}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openxp migrate metrics",
        description=(
            "Migrate metrics/*.yaml from v1 to v2 "
            "(adds schema_version + fact_source binding)."
        ),
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("metrics"),
        help="Directory containing metric YAMLs (default: ./metrics).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing.",
    )
    args = parser.parse_args(argv)

    if not args.dir.exists():
        print(f"Error: {args.dir} does not exist.", file=sys.stderr)
        return EXIT_USER_ERROR

    metric_files = sorted(args.dir.glob("*.yaml"))
    if not metric_files:
        print(f"No *.yaml files in {args.dir}. Nothing to migrate.")
        return EXIT_OK

    n_migrated = 0
    for path in metric_files:
        try:
            was_migrated, changes = migrate_one_file(path, dry_run=args.dry_run)
            for change in changes:
                print(change)
            if was_migrated:
                n_migrated += 1
        except yaml.YAMLError as e:
            print(f"  {path.name}: parse error: {e}", file=sys.stderr)
            return EXIT_WARNING

    action_word = "would be migrated" if args.dry_run else "migrated"
    print(f"\nResult: {n_migrated} file(s) {action_word}.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
