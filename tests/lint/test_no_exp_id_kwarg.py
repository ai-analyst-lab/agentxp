"""AST lint — assert no function under ``agentxp/`` carries an ``exp_id`` parameter.

v0.1 cleanup W0.6 (audit G3) — the canonical internal name is ``experiment_id``.
CLI argument names like ``--exp-id`` remain user-facing for ergonomics, but the
kwarg name inside Python must be ``experiment_id``. Local variables are out of
scope (this lint scans function signatures only).

If anyone reintroduces an ``exp_id`` parameter, this test fails first and loudly
with a file:line:function pointer.
"""
from __future__ import annotations

import ast
import pathlib


_AGENTXP_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent / "agentxp"


def test_no_exp_id_in_function_signatures() -> None:
    """No `def foo(exp_id: ...)` or `def foo(..., exp_id=...)` anywhere in agentxp/."""
    forbidden: list[str] = []
    for py in _AGENTXP_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = (
                    node.args.args
                    + node.args.kwonlyargs
                    + node.args.posonlyargs
                )
                for arg in params:
                    if arg.arg == "exp_id":
                        rel = py.relative_to(_AGENTXP_ROOT.parent)
                        forbidden.append(
                            f"{rel}:{node.lineno} def {node.name}({arg.arg}: ...)"
                        )
    assert not forbidden, (
        "function signatures with `exp_id` param are forbidden in agentxp/.\n"
        "Use `experiment_id` instead. Offending definitions:\n  "
        + "\n  ".join(forbidden)
    )
