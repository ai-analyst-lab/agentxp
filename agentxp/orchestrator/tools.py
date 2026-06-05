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


class ToolRefusal(Exception):
    """A tool refused to execute because doing so would violate a rule.

    Carries the rule citation (R1-R11) and a human-readable reason. The
    orchestrator surfaces ``args[0]`` to the user along with the
    suggested resolution (which tool to use instead, what brief to seal,
    etc.). Not a bug — a designed refusal.
    """


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


def render_share_tail(
    *,
    exp_dir: Path,
    experiment_id: str,
    readout_type: Literal["intent", "design_brief", "monitor_check", "verdict", "audit"],
    vm: IntentVM | DesignBriefVM | MidRunVM | VerdictVM,
    vm_sha256: str,
    provenance_render_status: Literal["VERIFIED", "DRAFT_UNVERIFIED", "UNVERIFIABLE"],
    audience: Literal["exec", "operator", "engineer"] = "exec",
    fmt: Literal["html", "md", "png", "json", "pdf"] = "md",
    entry_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
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
            pdf_ok = share_tail_html.html_to_pdf(html, out_path)
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

    catalog = exp_dir / "readouts" / "catalog.jsonl"
    catalog_append(
        catalog_path=catalog,
        experiment_id=experiment_id,
        entry_id=entry_id or f"rndr_{ts.timestamp():.0f}",
        payload=RenderCompletedEvent(
            readout_type=readout_type,
            audience=audience,
            format=fmt,
            path=str(out_path.relative_to(exp_dir)),
            vm_sha256=vm_sha256,
            provenance_render_status=provenance_render_status,
        ),
        timestamp=ts,
    )

    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Commit artifact — atomic file write + log.md + git
# ─────────────────────────────────────────────────────────────────────────────


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

    # Git add + commit
    git_msg = git_message or f"{artifact_name}: {safe_entry}"
    subprocess.run(
        ["git", "add", str(art_path), str(log_path)],
        cwd=exp_dir, check=True, capture_output=True,
    )
    result = subprocess.run(
        ["git", "commit", "-m", git_msg],
        cwd=exp_dir, check=True, capture_output=True, text=True,
    )
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=exp_dir, check=True, capture_output=True, text=True,
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
]
