"""Orchestrator tool surface (T81) — the typed tools the agent calls.

The orchestrator is a Claude Code session running with rebuild/CLAUDE.md
as its system prompt. It uses these tools to do everything the worldview
permits (R1-R11). Each tool wraps a load-bearing module that the agent
must NOT reimplement.

Tool roster (CLAUDE.md §6):
  - read_experiment_dir(exp_id)         dir state -> ExperimentSnapshot
  - probe_data(sql, mode)               -> through agentxp.sql.safety
  - run_stat(test_name, **args)         -> through agentxp.stats.*
  - decision_tree(tree_input)           -> agentxp.interpret.tree.walk_tree
  - map_confidence(ci_low, ci_high, orientation) -> ConfidenceLabel
  - seal_brief(...)                     -> agentxp.schemas.brief_seal
  - verify_brief_seal(...)              -> agentxp.schemas.brief_seal
  - render(readout_type, vm, provenance) -> distill + catalog + write
  - commit_artifact(name, content)      -> file + log.md + git commit
  - confirm_with_user(question, options) -> the only gate primitive

Each tool either succeeds and returns a typed result, raises a typed
exception the agent should surface to the user, or refuses with a
ToolRefusal that names the rule it enforces.

The actual specialist dispatch (assembling a bundle, sending a prompt
to a sub-agent) is in dispatch.py (T82); this module is the
discipline-enforcing tool layer.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict

from agentxp.audit.redactor import redact_message
from agentxp.interpret.confidence import ConfidenceLabel
from agentxp.interpret.confidence import map_confidence as _map_confidence_impl
from agentxp.interpret.tree import TreeInput, TreeResult, walk_tree
from agentxp.render.catalog import (
    RenderCompletedEvent,
    catalog_append,
)
from agentxp.render.distill import (
    distill_design_brief,
    distill_intent,
    distill_mid_run,
    distill_verdict,
)
from agentxp.render.viewmodel import (
    DesignBriefVM,
    IntentVM,
    MidRunVM,
    VerdictVM,
)
from agentxp.schemas.brief_seal import (
    ExpectedShape,
    SealedBrief,
    VerifyResult,
    seal_brief as _seal_brief_impl,
    verify_brief_seal as _verify_brief_seal_impl,
)
from agentxp.sql.safety import SafetyMode, SafetyResult, run_pipeline


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────


from agentxp.orchestrator.errors import ToolRefusal  # W5.1 — canonical home


class ExperimentNotFound(FileNotFoundError):
    """The named experiment directory does not exist under experiments/."""


# ─────────────────────────────────────────────────────────────────────────────
# Experiment state snapshot
# ─────────────────────────────────────────────────────────────────────────────


class ExperimentSnapshot(BaseModel):
    """Read-time state of an experiment directory.

    Pure data; building this is `read_experiment_dir`'s job. The
    orchestrator's loop reads this at the start of every turn and decides
    what to do next based on what landed.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    experiment_id: str
    exp_dir: Path
    has_intent: bool
    has_brief: bool
    brief_sealed: bool
    has_analysis: bool
    has_interpretation: bool
    has_report: bool
    last_log_entry: Optional[str] = None
    git_head_sha: Optional[str] = None


def read_experiment_dir(exp_dir: Path) -> ExperimentSnapshot:
    """Read the on-disk state of an experiment directory.

    No mutation, no commit. Just file checks + log tail. The orchestrator
    calls this at the start of every turn so its working state is the
    disk, not in-memory accumulation (CLAUDE.md §9).
    """
    if not exp_dir.exists() or not exp_dir.is_dir():
        raise ExperimentNotFound(f"experiment dir does not exist: {exp_dir}")

    log_path = exp_dir / "log.md"
    last_entry: Optional[str] = None
    if log_path.exists():
        # Last non-empty line — a quick sanity peek, not full parse.
        lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
        last_entry = lines[-1] if lines else None

    git_head: Optional[str] = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=exp_dir, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            git_head = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return ExperimentSnapshot(
        experiment_id=exp_dir.name,
        exp_dir=exp_dir,
        has_intent=(exp_dir / "intent.yaml").exists(),
        has_brief=(exp_dir / "brief.yaml").exists(),
        brief_sealed=(exp_dir / "brief.sealed.yaml").exists(),
        has_analysis=(exp_dir / "analysis.json").exists(),
        has_interpretation=(exp_dir / "interpretation.json").exists(),
        has_report=(exp_dir / "report.md").exists(),
        last_log_entry=last_entry,
        git_head_sha=git_head,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stats + SQL tool wrappers
# ─────────────────────────────────────────────────────────────────────────────


def probe_data(
    sql: str,
    *,
    mode: SafetyMode,
    dialect: str = "duckdb",
    purpose: str = "shape_probe",
    semantic_models: Optional[list] = None,
) -> SafetyResult:
    """Run a query through the 5- or 6-layer safety pipeline.

    R11 enforcement: ``mode="design"`` activates Layer 3d (outcome-column
    reject). ``mode="analyze"`` is the v0.1 behavior. The pipeline is
    fail-closed — any layer that rejects raises a SafetyViolation.
    """
    return run_pipeline(
        sql,
        dialect=dialect,
        purpose=purpose,
        mode=mode,
        semantic_models=semantic_models,
    )


def decision_tree(tree_input: TreeInput) -> TreeResult:
    """Run the 8-step verdict tree. The verdict is the function's output;
    R3 forbids the orchestrator from improvising one. UNVERIFIABLE on null
    required inputs (T10)."""
    return walk_tree(tree_input)


def map_confidence(
    ci_low: float,
    ci_high: float,
    orientation: Literal["higher_is_better", "lower_is_better", "neither"],
) -> ConfidenceLabel:
    """Compute the seven-value confidence label deterministically. R8 forbids
    upgrading the label through prose."""
    return _map_confidence_impl(ci_low, ci_high, orientation)


# ─────────────────────────────────────────────────────────────────────────────
# Brief seal wrappers
# ─────────────────────────────────────────────────────────────────────────────


def seal_brief_tool(
    *,
    brief_content: dict,
    design_chain_path: Path,
    metric_paths: dict[str, Path],
    expected_shape: ExpectedShape,
    sealed_by: str,
    agentxp_version: str,
) -> SealedBrief:
    """Compute the three-part integrity lock. R11 wall. No --force."""
    return _seal_brief_impl(
        brief_content=brief_content,
        design_chain_path=design_chain_path,
        metric_paths=metric_paths,
        expected_shape=expected_shape,
        sealed_by=sealed_by,
        agentxp_version=agentxp_version,
    )


def verify_brief_seal_tool(
    *,
    sealed: SealedBrief,
    design_chain_path: Path,
    metric_paths: dict[str, Path],
) -> VerifyResult:
    """Re-check all three lock components. Never raises — returns a
    structured VerifyResult. The orchestrator decides whether to proceed
    or refuse based on the result."""
    return _verify_brief_seal_impl(
        sealed=sealed,
        design_chain_path=design_chain_path,
        metric_paths=metric_paths,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Render tool — fires at share-tail moments
# ─────────────────────────────────────────────────────────────────────────────


_SHARE_TAIL_KINDS = {"intent", "design_brief", "monitor_check", "verdict", "audit"}


def _new_entry_id(prefix: str = "r") -> str:
    """Collision-resistant entry id for the renders catalog.

    W6.3 — replaces the pre-W6.3 second-resolution timestamp default
    ``rndr_{ts.timestamp():.0f}``, which collided when ``fan_out``'s six
    variants landed within the same second. Uses uuid4 (122 bits of
    randomness) which is collision-resistant under tight succession.
    The ``prefix`` keeps the id human-skimmable (e.g. ``r_<uuid>``).
    """
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def render_share_tail(
    *,
    exp_dir: Path,
    experiment_id: str,
    readout_type: Literal["intent", "design_brief", "monitor_check", "verdict", "audit"],
    vm: IntentVM | DesignBriefVM | MidRunVM | VerdictVM,
    vm_sha256: str,
    audience: Literal["exec", "operator", "engineer"] = "exec",
    fmt: Literal["html", "md", "png", "json", "pdf"] = "md",
    entry_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    strict_voice: bool = False,
    pdf_browser: Optional[object] = None,
) -> Path:
    """Render a share-tail readout to disk and append to the catalog.

    Lands at:
        experiments/<id>/readouts/<type>/<slot>/<audience>.<format>

    Appends a RenderCompletedEvent to the catalog. Returns the path the
    readout was written to. The slot is the timestamp's date (so multiple
    re-renders of the same type land at sibling paths and the catalog
    tracks supersession).

    ``html`` and ``pdf`` route through ``agentxp.render.share_tail_html``,
    which renders the Jinja templates in ``agentxp/render/templates/``.
    PDF requires Playwright; if it's unavailable the call falls back to
    writing the HTML alongside an ``.unrendered.txt`` marker and the
    returned path points at the HTML.
    """
    if readout_type not in _SHARE_TAIL_KINDS:
        raise ToolRefusal(
            f"unknown readout_type {readout_type!r}; "
            f"R10 — readout kinds are a closed set: {sorted(_SHARE_TAIL_KINDS)}"
        )

    ts = timestamp or datetime.now(timezone.utc)
    slot = ts.strftime("%Y-%m-%dT%H%M%S")
    out_dir = exp_dir / "readouts" / readout_type / slot
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{audience}.{fmt}"

    if fmt == "json":
        out_path.write_text(vm.model_dump_json(indent=2))
    elif fmt == "md":
        # Minimum-viable Markdown: dump VM as a fenced JSON block.
        out_path.write_text(
            f"# {readout_type} — {experiment_id}\n\n"
            f"```json\n{vm.model_dump_json(indent=2)}\n```\n"
        )
    elif fmt in ("html", "pdf"):
        from agentxp.render import share_tail_html

        renderers = {
            "intent": share_tail_html.render_intent_html,
            "design_brief": share_tail_html.render_design_brief_html,
            "verdict": share_tail_html.render_verdict_html,
            "monitor_check": share_tail_html.render_mid_run_html,
        }
        renderer = renderers.get(readout_type)
        if renderer is None:
            raise ToolRefusal(
                f"no html renderer wired for readout_type={readout_type!r}; "
                f"share_tail_html exposes: {sorted(renderers)}"
            )
        html = renderer(vm=vm, audience=audience)
        if fmt == "html":
            out_path.write_text(html)
        else:  # pdf
            html_path = out_path.with_suffix(".html")
            html_path.write_text(html)
            # Audit item #1: pdf_browser lets fan_out reuse one Chromium
            # across all 3 PDF renders in the batch.
            pdf_ok = share_tail_html.html_to_pdf(html, out_path, browser=pdf_browser)
            if not pdf_ok:
                # Playwright unavailable — surface the html, mark the gap.
                (out_dir / f"{audience}.pdf.unrendered.txt").write_text(
                    "playwright not available; pdf not rendered. "
                    "Install with: pip install playwright && playwright install chromium\n"
                )
                out_path = html_path
    else:
        # png + any future format — write JSON sidecar so the catalog has
        # something to reference until that adapter lands.
        json_path = out_path.with_suffix(".json")
        json_path.write_text(vm.model_dump_json(indent=2))
        out_path = json_path

    # W4.2 — render status is COMPUTED, not passed. Pre-W4.2 callers passed
    # provenance_render_status as a Literal string; render_share_tail trusted
    # the label. That was the R9 bypass (DIAGNOSTIC §A / debate §3.4). Now the
    # status is a function of the on-disk state (sealed brief verification +
    # readout type), so a caller cannot upgrade a render to VERIFIED by
    # passing the wrong label.
    from agentxp.render.provenance import build_provenance_for_brief

    computed_status = build_provenance_for_brief(exp_dir, readout_type)

    # W6.2 — voice audit fires before the catalog row appends. Only rule 5
    # (banned vocabulary per CLAUDE.md §12) is enforceable; the other voice
    # rules (paragraph length, sentence variance) are author-register
    # advice that does not apply to rendered templates and produced
    # constant stderr noise on every render (audit item #3 — fixed).
    # Audit also skipped on binary formats (PDF, PNG, JSON) — these can't
    # decode as utf-8, so the previous wrapper silently caught the
    # UnicodeDecodeError and the audit ran on nothing.
    from agentxp.render.voice_audit import (
        BannedVocabularyError,
        audit_voice_file,
    )

    voice_violations: list = []
    if fmt in ("md", "html"):
        try:
            all_violations = audit_voice_file(out_path) or []
            # Filter to banned-vocabulary rule (rule_id 5) only — the
            # others are noise on rendered templates.
            voice_violations = [v for v in all_violations if getattr(v, "rule_id", None) == 5]
        except Exception as exc:  # noqa: BLE001 — voice audit must never crash render
            # Audit item #3: was a silent pass; now surfaces the error to
            # stderr so a real audit bug is at least visible.
            import sys
            print(
                f"[render_share_tail] voice audit raised "
                f"{type(exc).__name__}; render proceeds. {exc}",
                file=sys.stderr,
            )
    if strict_voice and voice_violations:
        raise BannedVocabularyError(out_path, voice_violations)

    catalog = exp_dir / "readouts" / "catalog.jsonl"
    catalog_append(
        catalog_path=catalog,
        experiment_id=experiment_id,
        entry_id=entry_id or _new_entry_id(),
        payload=RenderCompletedEvent(
            readout_type=readout_type,
            audience=audience,
            format=fmt,
            path=str(out_path.relative_to(exp_dir)),
            vm_sha256=vm_sha256,
            provenance_render_status=computed_status.value.upper(),
        ),
        timestamp=ts,
    )

    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Commit artifact — atomic file write + log.md + git
# ─────────────────────────────────────────────────────────────────────────────


_GIT_TOPLEVEL_CACHE: dict[str, Path] = {}
"""Audit item #10 — cache ``git rev-parse --show-toplevel`` per resolved
exp_dir parent so commit_artifact + commit_artifacts share one lookup
per project root. ``git rev-parse`` is cheap but shells out; six
batched commits is six unnecessary subprocess starts."""


def _project_root_for(exp_dir: Path) -> Path:
    """Resolve the git worktree root for ``exp_dir``, with a process-local cache."""
    key = str(exp_dir.resolve().parent)
    cached = _GIT_TOPLEVEL_CACHE.get(key)
    if cached is not None:
        return cached
    toplevel = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=exp_dir, check=True, capture_output=True, text=True,
    ).stdout.strip()
    root = Path(toplevel)
    _GIT_TOPLEVEL_CACHE[key] = root
    return root


def commit_artifact(
    *,
    exp_dir: Path,
    artifact_name: str,
    content: str,
    log_entry: str,
    git_message: Optional[str] = None,
) -> str:
    """Write artifact, append to log.md, git commit.

    Returns the resulting git commit SHA. R11 / audit-trail enforcement:
    every commit-worthy artifact lands as a git commit so the audit
    surface is git + log.md (CLAUDE.md §8).

    Atomic: write artifact under tmp+rename, append log entry, git
    add+commit in one shell call. If git commit fails (e.g., empty diff),
    raises subprocess.CalledProcessError; the orchestrator decides how to
    handle (typically: the artifact already matched, no-op).
    """
    exp_dir.mkdir(parents=True, exist_ok=True)
    art_path = exp_dir / artifact_name
    art_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write
    tmp = art_path.with_suffix(art_path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(art_path)

    # Append to log.md
    ts = datetime.now(timezone.utc).isoformat()
    log_path = exp_dir / "log.md"
    safe_entry = redact_message(log_entry)
    with log_path.open("a") as f:
        f.write(f"- `{ts}` — {safe_entry}\n")

    # Git add + commit. The pre-W0 bug: paths were passed root-relative
    # ("experiments/exp_<id>/...") while cwd=exp_dir, so git resolved them
    # to "experiments/exp_<id>/experiments/exp_<id>/..." and failed with
    # exit 128. The fix: ask git itself for the worktree root via
    # `rev-parse --show-toplevel` (works at any depth, agnostic to whether
    # exp_dir IS the repo or is nested under it), then make the artifact
    # and log paths relative to that root.
    project_root = _project_root_for(exp_dir)
    rel_art = art_path.resolve().relative_to(project_root.resolve())
    rel_log = log_path.resolve().relative_to(project_root.resolve())
    git_msg = git_message or f"{artifact_name}: {safe_entry}"
    subprocess.run(
        ["git", "add", str(rel_art), str(rel_log)],
        cwd=project_root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", git_msg],
        cwd=project_root, check=True, capture_output=True, text=True,
    )
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root, check=True, capture_output=True, text=True,
    )
    return sha_result.stdout.strip()


def commit_artifacts(
    *,
    exp_dir: Path,
    artifacts: list[tuple[str, str]],
    log_entry: str,
    git_message: str,
) -> str:
    """Batched form of :func:`commit_artifact` — one commit, one log entry.

    W5.4 — Renders' ``fan_out`` helper (W6.4) writes six files (3
    audiences × 2 formats) in tight succession per readout type. Without
    a batched commit form, fan_out would produce six commits and six
    ``log.md`` rows per render, polluting the audit chain with what
    should be a single logical event. This overload:

      * Writes every ``(name, content)`` pair atomically (each via
        ``tmp + rename``).
      * Appends a single ``log.md`` row covering all of them.
      * Stages every artifact + the log row in one ``git add``.
      * Produces one commit with ``git_message``.
      * Returns the resulting commit SHA.

    Parameters
    ----------
    exp_dir
        Same as ``commit_artifact``.
    artifacts
        ``[(artifact_name, content), ...]``. Empty list raises
        ``ToolRefusal`` — fan_out always has at least one file.
    log_entry
        Single human-readable line describing the batch (e.g.
        ``"design_brief share-tail fan-out × 6"``). Goes through
        ``redact_message`` like the single form.
    git_message
        Same as the single form's ``git_message``; here it's required
        because batches have no obvious default.
    """
    if not artifacts:
        raise ToolRefusal(
            "commit_artifacts called with empty artifacts list; "
            "every batched commit must include at least one file."
        )

    exp_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    for name, content in artifacts:
        art_path = exp_dir / name
        art_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = art_path.with_suffix(art_path.suffix + ".tmp")
        tmp.write_text(content)
        tmp.replace(art_path)
        written_paths.append(art_path)

    ts = datetime.now(timezone.utc).isoformat()
    log_path = exp_dir / "log.md"
    safe_entry = redact_message(log_entry)
    with log_path.open("a") as f:
        f.write(f"- `{ts}` — {safe_entry}\n")

    project_root = _project_root_for(exp_dir)
    rels = [
        str(p.resolve().relative_to(project_root.resolve()))
        for p in written_paths
    ]
    rel_log = str(log_path.resolve().relative_to(project_root.resolve()))

    subprocess.run(
        ["git", "add", *rels, rel_log],
        cwd=project_root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", git_message],
        cwd=project_root, check=True, capture_output=True, text=True,
    )
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root, check=True, capture_output=True, text=True,
    )
    return sha_result.stdout.strip()


__all__ = [
    # Errors
    "ToolRefusal",
    "ExperimentNotFound",
    # State
    "ExperimentSnapshot",
    "read_experiment_dir",
    # Wrappers
    "probe_data",
    "decision_tree",
    "map_confidence",
    "seal_brief_tool",
    "verify_brief_seal_tool",
    "render_share_tail",
    "commit_artifact",
    "commit_artifacts",
]
