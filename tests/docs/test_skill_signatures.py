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
    "load_intent":         "agentxp.workflows.design:load_intent",
    "finalize_brief":      "agentxp.workflows.design:finalize_brief",
    "check_power_feasibility": "agentxp.workflows.design:check_power_feasibility",
    "seal_and_commit_brief": "agentxp.workflows.design:seal_and_commit_brief",
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
    "dispatch_specialist": "agentxp.orchestrator.loop:dispatch_specialist",
    "distill_verdict":     "agentxp.render.distill:distill_verdict",
    "build_provenance":    "agentxp.render.provenance:build_provenance",
    "srm_check":           "agentxp.stats.srm:srm_check",
    "map_confidence":      "agentxp.interpret.confidence:map_confidence",
    # Classes / view models cited in skill examples
    "AssignmentSurface":   "agentxp.schemas.bundles:AssignmentSurface",
    "ViewBundle":          "agentxp.render.viewmodel:ViewBundle",
    "WarehouseProfile":    "agentxp.schemas.bundles:WarehouseProfile",
    # AgentXP helpers cited by the analyze/audit/connect/readouts skills.
    "adjust_pvalues":      "agentxp.stats.corrections:adjust_pvalues",
    "guardrail_test":      "agentxp.stats.guardrails:guardrail_test",
    "load_metric":         "agentxp.metrics.registry:load_metric",
    "to_test_function":    "agentxp.metrics.schema:to_test_function",
    "walk_log":            "agentxp.workflows.audit:walk_log",
    "diff_logs":           "agentxp.workflows.audit:diff_logs",
    "run_wizard":          "agentxp.workflows.connect:run_wizard",
    "build_index":         "agentxp.render.catalog:build_index",
    "list_catalog":        "agentxp.workflows.readouts:list_catalog",
    "validate_catalog":    "agentxp.render.catalog:validate_catalog",
    # SystemExit is a builtin exception, not a helper
}
# Generic example names that appear in skill code blocks (e.g.
# `test_fn = to_test_function(metric)` — `test_fn` is a local var, not
# a helper). Listed here to keep _UNTRACKED_SYMBOLS focused on real drift.
_EXAMPLE_LOCALS: frozenset[str] = frozenset({
    "test_fn", "vm", "sm", "metric", "intent",
})
# Names that are builtins / exceptions / common kwarg-less classes; do not flag.
_BUILTIN_OR_KWARG_LESS: frozenset[str] = frozenset({
    "SystemExit", "KeyError", "ValueError", "TypeError", "RuntimeError",
    "Path", "datetime", "timedelta", "Decimal",
})


def _iter_python_blocks(md_text: str) -> Iterable[str]:
    """Yield the body of every python-tagged fenced block."""
    pattern = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
    for match in pattern.finditer(md_text):
        yield match.group(1)


def _parse_skill_imports(md_text: str) -> dict[str, str]:
    """W7.4 — each SKILL.md may declare an ``imports:`` block in its YAML
    frontmatter. Symbols declared there take precedence over SYMBOL_IMPORTS
    so a skill that uses a non-standard helper does not need a global
    registration.
    """
    frontmatter = re.match(r"^---\n(.*?)\n---", md_text, re.DOTALL)
    if not frontmatter:
        return {}
    try:
        import yaml

        data = yaml.safe_load(frontmatter.group(1))
    except Exception:
        return {}
    imports = data.get("imports") if isinstance(data, dict) else None
    if not isinstance(imports, dict):
        return {}
    return {str(k): str(v) for k, v in imports.items()}


_KNOWN_NON_HELPERS: frozenset[str] = _BUILTIN_OR_KWARG_LESS | _EXAMPLE_LOCALS | frozenset({
    "print", "open", "len", "str", "int", "float", "list", "dict",
    "tuple", "set", "range", "enumerate", "zip", "isinstance",
    "getattr", "hasattr", "yaml", "json",
    "Optional", "Literal", "Field", "BaseModel", "ConfigDict",
})


def _resolve(
    name: str,
    skill_imports: dict[str, str],
    skill_path: Path,
    untracked: set[tuple[str, str]],
):
    """Resolve a name to its callable target, or None.

    Audit clarification #l: previously this function mutated a module-
    level `_UNTRACKED_SYMBOLS` set as a side effect, which made the two
    consumer tests race-prone under pytest parallelism / reordering.
    Untracked names now flow through an explicit `untracked` parameter
    that the caller (a fixture) owns the lifecycle of.
    """
    spec = skill_imports.get(name) or SYMBOL_IMPORTS.get(name)
    if spec is None:
        if name in _KNOWN_NON_HELPERS:
            return None
        untracked.add((str(skill_path), name))
        return None
    module_path, qualname = spec.split(":")
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
    """Get the bare function name from a Call node, or None.

    Audit item #7: only direct function calls (``ast.Name``) are
    validatable. Method calls (``ast.Attribute`` — e.g.
    ``path.read_text()``, ``Path.cwd()``, ``vm.model_dump()``) are
    called on instances or classes that the test cannot resolve to a
    static signature, so we skip them. The strict-symbols test only
    fires on direct top-level function references.
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _walk_skills() -> tuple[
    list[tuple[Path, str, str, list[str]]],
    set[tuple[str, str]],
]:
    """Walk every SKILL.md once; collect both kwarg drifts AND untracked
    symbols in a single pass. Returns ``(violations, untracked)`` as a
    pair the two tests below consume.

    No module-level mutable state — both outputs flow through the return
    value, so the tests are race-free under pytest parallelism /
    reordering (audit clarification #l).
    """
    violations: list[tuple[Path, str, str, list[str]]] = []
    untracked: set[tuple[str, str]] = set()

    for skill_md in SKILLS_DIR.glob("**/SKILL.md"):
        text = skill_md.read_text()
        skill_imports = _parse_skill_imports(text)
        for block in _iter_python_blocks(text):
            cleaned = re.sub(r"<[^>]+>", "None", block)
            try:
                tree = ast.parse(cleaned)
            except SyntaxError:
                continue

            for call in _iter_calls(tree):
                name = _call_name(call)
                if name is None:
                    continue
                target = _resolve(name, skill_imports, skill_md, untracked)
                if target is None:
                    continue
                try:
                    sig = inspect.signature(target)
                except (TypeError, ValueError):
                    continue
                params = set(sig.parameters)
                has_kwargs = any(
                    p.kind is inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
                if has_kwargs:
                    continue
                for kw in call.keywords:
                    if kw.arg is None:
                        continue
                    if kw.arg not in params:
                        violations.append(
                            (skill_md, name, kw.arg, sorted(params))
                        )
    return violations, untracked


@pytest.fixture(scope="module")
def skill_walk_results():
    """Module-scoped fixture so both consumer tests share one walk
    (the walk is the expensive part — ~30 SKILL.md code blocks to ast.parse)."""
    return _walk_skills()


def test_skill_signatures_match_live_api(skill_walk_results) -> None:
    """Every kwarg cited in every SKILL.md code block exists in the live signature."""
    violations, _ = skill_walk_results
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


def test_skill_signatures_no_unknown_symbols(skill_walk_results) -> None:
    """A symbol cited in a SKILL.md code block must resolve.

    Either declare the symbol in the skill's ``imports:`` preamble or
    extend the global ``SYMBOL_IMPORTS`` map; this test fails if neither
    names it.
    """
    _, untracked = skill_walk_results
    if untracked:
        by_skill: dict[str, list[str]] = {}
        for skill_path, name in sorted(untracked):
            by_skill.setdefault(skill_path, []).append(name)
        lines = []
        for skill, names in sorted(by_skill.items()):
            rel = Path(skill).relative_to(Path(__file__).resolve().parents[2])
            lines.append(f"  {rel}: {sorted(set(names))}")
        pytest.fail(
            f"Skill text cites symbols neither declared in the skill's "
            f"`imports:` preamble nor in SYMBOL_IMPORTS:\n"
            + "\n".join(lines)
        )
