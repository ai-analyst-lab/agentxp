"""Seeded DuckDB demo warehouse generator (T30-T32).

Produces ``sample-data/agentxp_demo.duckdb``: 6 tables, 8 pre-seeded
experiments spanning the verdict tree. Deterministic seed contract;
identical regeneration produces identical row hashes.

Run:
    python -m agentxp.data.demo.build [--out PATH]
"""
from agentxp.data.demo.scenarios import SCENARIOS, Scenario  # noqa: F401
from agentxp.data.demo.seed import streams  # noqa: F401
