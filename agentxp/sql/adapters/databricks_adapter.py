"""Databricks warehouse adapter — STUB for AgentXP v0.1 (§12).

The full Databricks adapter (PAT / OAuth M2M / Azure AD auth surfaces against
the ``databricks-sql-connector`` SQL warehouse endpoint) lands in v0.1.1 per
§12 / D1. v0.1 ships this stub so the BaseAdapter Protocol has a registered
implementation under the ``databricks`` dialect.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 (adapters table).
"""
from __future__ import annotations

from typing import Any

from agentxp.sql.adapter import AdapterResult, PreviewResult


class DatabricksAdapter:
    """Stub for v0.1. Full implementation lands in v0.1.1.

    Stores the connection params on construction so a v0.1.1 swap-in can
    pick them up without changing call sites. Every BaseAdapter method
    except :meth:`get_dialect` / :meth:`close` raises NotImplementedError.
    """

    def __init__(self, **conn_params: Any) -> None:
        self._conn_params = conn_params

    # ------------------------------------------------------------------
    # BaseAdapter Protocol
    # ------------------------------------------------------------------

    def execute(
        self, sql: str, max_rows: int = 10_000, timeout_s: int = 30
    ) -> AdapterResult:
        raise NotImplementedError("Databricks adapter ships in v0.1.1")

    def explain(self, sql: str) -> str:
        raise NotImplementedError("Databricks adapter ships in v0.1.1")

    def dry_run(self, sql: str) -> PreviewResult:
        raise NotImplementedError("Databricks adapter ships in v0.1.1")

    def get_dialect(self) -> str:
        return "databricks"

    def close(self) -> None:
        pass


__all__ = ["DatabricksAdapter"]
