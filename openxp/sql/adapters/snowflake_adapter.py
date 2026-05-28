"""Snowflake warehouse adapter — STUB for OpenXP v0.1 (§12).

The full Snowflake adapter (password / externalbrowser / oauth / keypair auth
surfaces) is ~16h of work per §12 / D1 and lands in v0.1.1. v0.1 ships this
stub so the :class:`openxp.sql.adapter.BaseAdapter` Protocol has a registered
implementation under the ``snowflake`` dialect — the dispatcher / connect
wizard can refuse cleanly with NotImplementedError rather than ImportError.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 (adapters table).
"""
from __future__ import annotations

from typing import Any

from openxp.sql.adapter import AdapterResult, PreviewResult


class SnowflakeAdapter:
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
        raise NotImplementedError("Snowflake adapter ships in v0.1.1")

    def explain(self, sql: str) -> str:
        raise NotImplementedError("Snowflake adapter ships in v0.1.1")

    def dry_run(self, sql: str) -> PreviewResult:
        raise NotImplementedError("Snowflake adapter ships in v0.1.1")

    def get_dialect(self) -> str:
        return "snowflake"

    def close(self) -> None:
        pass


__all__ = ["SnowflakeAdapter"]
