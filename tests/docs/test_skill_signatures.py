"""W8.1 — skill-text ↔ live-signature drift CI.

The DIAGNOSTIC §B.1 family (allocate_experiment(exp_id=) vs
experiment_id=; verify_brief_seal vs verify_or_raise) hit because skill
text drifted from the live API and no test caught it. This test walks
every python-tagged code block in `.claude/skills/*/SKILL.md`, parses
with `ast`, finds every `Call` node where the function name resolves to
an importable target, and asserts every kwarg in the call appears in
``inspect.signature(target).parameters``.

A SKILL.md that names a stale kwarg fails the build, not the session.

The walker is intentionally permissive: it skips calls whose target it
cannot resolve (e.g., method calls on instances, conditional imports,
nonsense literals in code-block examples). The check is positive — when
it CAN resolve a target, it must match.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path
from typing import Iterable

import pytest


SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"

# Map names that appear in code blocks to their canonical import paths.
# Extend when a skill cites a new helper; absence of a name in this table
# means the test skips that call (positive check).
SYMBOL_IMPORTS: dict[str, str] = {
    "allocate_experiment": "agentxp.workflows.design:allocate_experiment",
    "record_intent":       "agentxp.workflows.design:record_intent",
    "distill_intent":      "agentxp.render.distill:distill_intent",
    "distill_design_brief": "agentxp.render.distill:distill_design_brief",
    "render_share_tail":   "agentxp.orchestrator.tools:render_share_tail",
    "commit_artifact":     "agentxp.orchestrator.tools:commit_artifact",
    "commit_artifacts":    "agentxp.orchestrator.tools:commit_artifacts",
    "fan_out":             "agentxp.render.fan_out:fan_out",
    "seal_brief":          "agentxp.schemas.brief_seal:seal_brief",
    "verify_or_raise":     "agentxp.schemas.brief_seal:verify_or_raise",
    "open_dispatch":       "agentxp.orchestrator.bridge:open_dispatch",
    "complete_dispatch":   "agentxp.orchestrator.bridge:complete_dispatch",
    "dispatch_critic":     "agentxp.orchestrator.bridge:dispatch_critic",
    "probe_data":          "agentxp.orchestrator.tools:probe_data",
}


def _iter_python_blocks(md_text: str) -> Iterable[str]:
    """Yield the body of every python-tagged fenced block."""
    pattern = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
    for match in pattern.finditer(md_text):
        yield match.group(1)


def _resolve(name: str):
    if name not in SYMBOL_IMPORTS:
        return None
    module_path, qualname = SYMBOL_IMPORTS[name].split(":")
    try:
        module = importlib.import_module(module_path)
        return getattr(module, qualname, None)
    except ImportError:
        return None


def _iter_calls(tree: ast.AST) -> Iterable[ast.Call]:
    """Yield every Call node in the AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _call_name(node: ast.Call) -> str | None:
    """Get the bare function name from a Call node, or None."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _collect_drift_violations() -> list[tuple[Path, str, str, list[str]]]:
    """Walk every SKILL.md and return any kwarg drifts.

    Returns ``[(skill_path, function_name, drift_kwarg, valid_kwargs), ...]``.
    """
    violations: list[tuple[Path, str, str, list[str]]] = []

    for skill_md in SKILLS_DIR.glob("**/SKILL.md"):
        text = skill_md.read_text()
        for block in _iter_python_blocks(text):
            # Strip leading prompt placeholders like `<from intent.yaml>`,
            # which break ast.parse. Allow lines that start with these
            # placeholders by replacing them with `None` for parsing only.
            cleaned = re.sub(r"<[^>]+>", "None", block)
            try:
                tree = ast.parse(cleaned)
            except SyntaxError:
                # Code block is illustrative, not executable. Skip.
                continue

            for call in _iter_calls(tree):
                name = _call_name(call)
                if name is None:
                    continue
                target = _resolve(name)
                if target is None:
                    continue
                try:
                    sig = inspect.signature(target)
                except (TypeError, ValueError):
                    continue
                params = set(sig.parameters)
                # Accept VAR_KEYWORD targets (e.g. **kwargs); we cannot
                # statically validate against them.
                has_kwargs = any(
                    p.kind is inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
                if has_kwargs:
                    continue
                for kw in call.keywords:
                    if kw.arg is None:  # **kwargs splat
                        continue
                    if kw.arg not in params:
                        violations.append(
                            (skill_md, name, kw.arg, sorted(params))
                        )
    return violations


def test_skill_signatures_match_live_api() -> None:
    """Every kwarg cited in every SKILL.md code block exists in the live signature."""
    violations = _collect_drift_violations()
    if violations:
        lines = []
        for path, fn, drift, valid in violations:
            rel = path.relative_to(Path(__file__).resolve().parents[2])
            lines.append(
                f"  {rel} cites {fn}({drift}=...) — not in signature; "
                f"valid kwargs: {valid}"
            )
        details = "\n".join(lines)
        pytest.fail(
            f"Skill text drift detected ({len(violations)} kwargs):\n{details}\n"
            "Either update the SKILL.md to use the current kwarg name or "
            "extend SYMBOL_IMPORTS in tests/docs/test_skill_signatures.py."
        )
