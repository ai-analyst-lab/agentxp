"""Design verb helpers — called by .claude/skills/design/SKILL.md.

The design verb pre-registers an experiment: intent → semantic models →
metrics → hypothesis → brief → data plan → sealed brief. These helpers
do the Python-side allocation and bookkeeping; the agentic loop (which
specialist to dispatch when, which gate to confirm) lives in the skill.

Public surface:
  - allocate_experiment(project_root, *, data_path=None, experiment_id=None) -> Path
  - record_intent(exp_dir, intent_text, captured_by) -> Path
"""
from __future__ import annotations

import datetime as _dt
import uuid
from pathlib import Path
from typing import NamedTuple, Optional


def _new_experiment_id() -> str:
    """Generate a short ULID-flavored experiment id: ``exp_<8-hex>``."""
    return f"exp_{uuid.uuid4().hex[:8]}"


def allocate_experiment(
    project_root: Path,
    *,
    data_path: Optional[Path] = None,
    experiment_id: Optional[str] = None,
) -> Path:
    """Allocate a fresh experiment directory under ``project_root/experiments/``.

    Returns the absolute path to the new directory. Seeds ``log.md`` with
    a single open-line entry. If ``data_path`` is supplied, stashes the
    resolved path at ``.data_path`` for the orchestrator to pick up.

    Raises ``FileExistsError`` if ``experiment_id`` is supplied and the directory
    already exists (no silent collision).
    """
    experiment_id = experiment_id or _new_experiment_id()
    exp_dir = Path(project_root) / "experiments" / experiment_id
    if exp_dir.exists():
        raise FileExistsError(
            f"experiment directory already exists: {exp_dir}"
        )
    exp_dir.mkdir(parents=True)

    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    log = exp_dir / "log.md"
    log.write_text(
        f"# log — {experiment_id}\n\n"
        f"- `{ts}` — design verb opened\n"
    )

    if data_path is not None:
        (exp_dir / ".data_path").write_text(str(Path(data_path).resolve()))

    return exp_dir


def record_intent(
    exp_dir: Path,
    intent_text: str,
    captured_by: str,
) -> Path:
    """Write ``intent.yaml`` and append a log entry. Returns the intent path.

    The intent is the user's plain-English statement of what they want to
    test. It's the trigger for everything downstream: semantic models,
    metrics, hypothesis, brief. The orchestrator dispatches the designer
    after this lands.

    Raises ``ValueError`` if ``intent_text`` is empty or whitespace-only.
    """
    if not intent_text or not intent_text.strip():
        raise ValueError("intent_text must be non-empty")
    if not captured_by or not captured_by.strip():
        raise ValueError("captured_by must be non-empty")

    exp_dir = Path(exp_dir)
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    intent_path = exp_dir / "intent.yaml"

    # Minimal YAML — the schema lives in agentxp/schemas/experiment.py; this
    # writer keeps the format flat so log.md remains readable.
    intent_path.write_text(
        f"schema_version: 1\n"
        f"text: |\n"
        f"  {intent_text.strip()}\n"
        f"captured_at: {ts}\n"
        f"captured_by: {captured_by}\n"
    )

    log = exp_dir / "log.md"
    with log.open("a") as f:
        f.write(f"- `{ts}` — intent captured by {captured_by}\n")

    return intent_path


class LoadedIntent(NamedTuple):
    """Named-tuple result for ``load_intent`` (audit item #12).

    ``bundle`` is the R10-compliant ``IntentText`` the specialist sees;
    ``schema_version`` and ``captured_by`` are the audit metadata that
    lives on disk + the render path but not in the bundle. Subscriptable
    as a tuple for callers that prefer the old destructuring shape:
    ``bundle, audit = load_intent(path)`` still works because
    ``LoadedIntent`` exposes a 2-element view through ``__iter__`` (see
    ``_LegacyLoadedIntentView``).
    """
    bundle: "IntentText"  # forward ref — IntentText imported below
    schema_version: int
    captured_by: str


def load_intent(intent_path: Path) -> LoadedIntent:
    """Project the on-disk ``intent.yaml`` into a bundle-shaped IntentText.

    The on-disk artifact carries audit metadata — ``schema_version`` (the
    file format version) and ``captured_by`` (the email/handle of the user
    who recorded the intent). The bundle type ``IntentText`` deliberately
    does NOT carry these (R10 — the specialist sees only what the schema
    declares; audit metadata stays on disk and on the render path).

    Returns a :class:`LoadedIntent` named tuple. For backwards-compat the
    old destructuring pattern ``bundle, audit = load_intent(path)`` still
    works — the second element is a dict shape projected from the named
    fields. New callers should use the named-attribute access:

        loaded = load_intent(path)
        loaded.bundle           # IntentText
        loaded.captured_by      # str
    """
    import yaml

    from agentxp.schemas.bundles import IntentText

    raw = yaml.safe_load(Path(intent_path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"intent.yaml at {intent_path} is not a mapping")

    bundle = IntentText(text=raw["text"], captured_at=raw["captured_at"])
    return _LegacyLoadedIntentView(
        bundle=bundle,
        schema_version=raw.get("schema_version", 1),
        captured_by=raw.get("captured_by", ""),
    )


class _LegacyLoadedIntentView(LoadedIntent):
    """Internal helper — supports the legacy ``(bundle, audit_dict)`` unpack
    while exposing the new named attributes. Iterating yields the two-
    element tuple ``(bundle, audit_dict)`` callers wrote against pre-#12.
    """
    def __iter__(self):
        audit = {
            "schema_version": self.schema_version,
            "captured_by": self.captured_by,
        }
        yield self.bundle
        yield audit


def finalize_brief(exp_dir: Path) -> dict:
    """Stamp deterministic fields onto a designer-drafted ``brief.yaml``.

    The designer LLM provides judgments — ``baseline``, ``mde_pct``,
    ``alpha``, ``power``, and the structured ``primary_decision_rule``.
    Quantities that are *derived* from those judgments (``n_required``,
    ``n_required_total``) are computed here by a deterministic stats helper
    rather than by the LLM. This closes the magnitude-variance gap the
    Option-A benchmark surfaced: two runs of the same intent had picked
    ``n_required`` values 7.4× apart because the LLM was both judging
    *and* arithmetic-ing.

    Contract:
      * The designer writes ``brief.yaml`` with ``baseline`` (numeric),
        ``mde_pct`` (numeric, percent), and ``primary_metric_type``.
        Optional: ``alpha`` (default 0.05), ``power`` (default 0.80),
        ``baseline_std`` (required for ``primary_metric_type == "mean"``).
      * The designer writes ``primary_decision_rule`` as a structured
        mapping that validates against
        :class:`agentxp.schemas.bundles.DecisionRule` (with the brief's
        primary metric name and ``severity == "primary"``).
      * This function overwrites ``n_required`` and ``n_required_total``
        with the power calculation, stamps ``alpha`` + ``power`` if
        defaulted, and validates the decision rule. It writes the brief
        back to disk.

    Raises:
      ValueError: brief missing required judgment fields, or
        ``primary_decision_rule`` failing structured validation.
      NotImplementedError: ``primary_metric_type`` not in the wired set.

    Returns:
      The updated brief dict (also written to ``exp_dir/brief.yaml``).
    """
    import yaml

    from agentxp.schemas.bundles import DecisionRule
    from agentxp.stats.power import power_mean, power_proportion

    brief_path = Path(exp_dir) / "brief.yaml"
    brief = yaml.safe_load(brief_path.read_text())
    if not isinstance(brief, dict):
        raise ValueError(f"brief.yaml at {brief_path} is not a mapping")

    for field in ("baseline", "mde_pct", "primary_metric_type", "primary_metric"):
        if field not in brief:
            raise ValueError(f"brief.yaml missing required field: {field}")

    alpha = brief.setdefault("alpha", 0.05)
    power = brief.setdefault("power", 0.80)
    mde_relative = brief["mde_pct"] / 100.0
    metric_type = brief["primary_metric_type"]

    if metric_type == "proportion":
        result = power_proportion(brief["baseline"], mde_relative, alpha=alpha, power=power)
    elif metric_type == "mean":
        if "baseline_std" not in brief:
            raise ValueError("brief.yaml missing baseline_std (required for mean metric)")
        result = power_mean(
            brief["baseline"], brief["baseline_std"], mde_relative,
            alpha=alpha, power=power,
        )
    else:
        raise NotImplementedError(
            f"finalize_brief does not yet support primary_metric_type={metric_type!r}; "
            f"wire power_ratio in agentxp.stats.ratio_power."
        )

    if "error" in result:
        raise ValueError(f"power calculation failed: {result['error']}")

    brief["n_required"] = result["sample_size_per_group"]
    brief["n_required_total"] = result["total_sample_size"]
    brief["n_required_computed_by"] = f"agentxp.stats.power.power_{metric_type}"

    if "primary_decision_rule" not in brief:
        raise ValueError("brief.yaml missing primary_decision_rule")
    rule = brief["primary_decision_rule"]
    if not isinstance(rule, dict):
        raise ValueError(
            "primary_decision_rule must be a structured mapping (DecisionRule), "
            f"got {type(rule).__name__}. Free-text decision rules are no longer "
            "accepted — the design verb stamps the structure deterministically."
        )
    # Validate; surfaces pydantic ValidationError as ValueError to the caller
    try:
        DecisionRule.model_validate(rule)
    except Exception as e:
        raise ValueError(f"primary_decision_rule failed DecisionRule validation: {e}") from e

    brief_path.write_text(yaml.safe_dump(brief, sort_keys=False))
    return brief


def check_power_feasibility(brief: dict, units_available: int) -> None:
    """Refuse the seal when required sample size exceeds the assignment surface.

    Expects a *finalized* brief (``finalize_brief`` has stamped
    ``n_required`` / ``n_required_total``). Raises ``ValueError`` with a
    math-rich message on infeasibility; returns ``None`` when feasible.
    There is no force flag — the resolution is to widen ``mde_pct`` or
    expand the surface, then re-finalize and re-seal.
    """
    import math

    n_total = brief.get("n_required_total")
    if n_total is None:
        raise ValueError(
            "brief.yaml has no n_required_total — run finalize_brief() "
            "before sealing so the power calculation is stamped."
        )
    if n_total <= units_available:
        return

    msg = (
        f"power-feasibility refusal: the brief requires {n_total:,} units total "
        f"({brief.get('n_required', 0):,} per arm at "
        f"alpha={brief.get('alpha', 0.05)}, power={brief.get('power', 0.80)}), "
        f"but the assignment surface offers {units_available:,} — a shortfall "
        f"of {n_total - units_available:,} ({n_total / units_available:.1f}x over)."
    )
    mde_pct = brief.get("mde_pct")
    if mde_pct:
        # n scales ~ 1/MDE^2, so the smallest MDE this surface can power is
        # approximately mde * sqrt(n_required / available).
        feasible_mde = mde_pct * math.sqrt(n_total / units_available)
        msg += (
            f" At this surface the smallest detectable relative effect is "
            f"roughly {feasible_mde:.1f}% (n scales with 1/MDE^2); widen "
            f"mde_pct to at least that, or expand the surface. No --force."
        )
    raise ValueError(msg)


def seal_and_commit_brief(
    exp_dir: Path,
    *,
    metric_paths: dict,
    expected_shape,
    sealed_by: str,
    units_available: int,
):
    """Seal ``brief.yaml`` and git-commit the result so the seal verifies.

    Ordering is the point of this helper. The naive sequence
    (``seal_brief`` then ``commit_artifact``) is self-invalidating:
    ``seal_brief`` hashes ``log.md`` into ``design_chain_hash``, then
    ``commit_artifact`` appends a "brief sealed" log row — so the committed
    ``log.md`` never matches the hash and ``build_provenance_for_brief``
    can never return VERIFIED for a discipline-following seal. This helper
    appends the seal log row *before* hashing, then seals, writes
    ``brief.sealed.yaml``, and commits both files with no further log
    mutation.

    Also runs the power-feasibility check (required-n vs
    ``units_available``) before any side effect, so an infeasible brief
    refuses cleanly with the dir untouched.

    Returns the :class:`agentxp.schemas.brief_seal.SealedBrief`.
    """
    import subprocess

    import yaml

    import agentxp
    from agentxp.schemas.brief_seal import seal_brief

    exp_dir = Path(exp_dir)
    brief_path = exp_dir / "brief.yaml"
    brief = yaml.safe_load(brief_path.read_text())
    if not isinstance(brief, dict):
        raise ValueError(f"brief.yaml at {brief_path} is not a mapping")

    check_power_feasibility(brief, units_available)

    # 1. Seal log row FIRST — design_chain_hash must cover the final log.md.
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    log_path = exp_dir / "log.md"
    with log_path.open("a") as f:
        f.write(f"- `{ts}` — brief sealed by {sealed_by}\n")

    # 2. Hash + seal (log.md now includes the seal row).
    sealed = seal_brief(
        brief_content=brief,
        design_chain_path=log_path,
        metric_paths=metric_paths,
        expected_shape=expected_shape,
        sealed_by=sealed_by,
        agentxp_version=agentxp.__version__,
    )

    # 3. Atomic write of brief.sealed.yaml.
    sealed_path = exp_dir / "brief.sealed.yaml"
    tmp = sealed_path.parent / (sealed_path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(sealed.model_dump(mode="json"), sort_keys=False))
    tmp.replace(sealed_path)

    # 4. Commit both files. Deliberately NOT commit_artifact — that helper
    # appends its own log row, which would re-break the hash.
    from agentxp.orchestrator.tools import _project_root_for

    project_root = _project_root_for(exp_dir)
    rel_sealed = sealed_path.resolve().relative_to(project_root.resolve())
    rel_log = log_path.resolve().relative_to(project_root.resolve())
    subprocess.run(
        ["git", "add", str(rel_sealed), str(rel_log)],
        cwd=project_root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m",
         f"brief.sealed.yaml: {exp_dir.name}: brief sealed"],
        cwd=project_root, check=True, capture_output=True, text=True,
    )
    return sealed


__all__ = [
    "allocate_experiment",
    "record_intent",
    "finalize_brief",
    "check_power_feasibility",
    "seal_and_commit_brief",
]
