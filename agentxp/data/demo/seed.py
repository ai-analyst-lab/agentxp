"""Deterministic seed contract for the demo warehouse (T30).

MASTER_SEED + per-experiment EXP_SEED feed numpy's SeedSequence so each
experiment's per-stream RNG is reproducible AND independent. Stream slot
allocation is pinned to FIXTURE_VERSION — bumping the version changes
the streams and the row hashes, by design.

Streams (per-experiment):
  0 — user sampling order
  1 — assignment (arm picking)
  2 — base outcome (conversion / metric)
  3 — treatment effect noise
  4 — guardrail noise
  5 — novelty + contamination signal
  6 — exposure timing
  7 — segment sampling
"""
from __future__ import annotations

import numpy as np


MASTER_SEED: int = 0xA9E47899
FIXTURE_VERSION: int = 1


def seed_root() -> np.random.SeedSequence:
    """Root SeedSequence; per-experiment seeds spawn from this."""
    return np.random.SeedSequence(entropy=[MASTER_SEED, FIXTURE_VERSION])


def spawn_experiment_seed(exp_seed: int) -> np.random.SeedSequence:
    """Per-experiment SeedSequence derived from root + per-experiment salt."""
    return np.random.SeedSequence(
        entropy=[MASTER_SEED, FIXTURE_VERSION, exp_seed]
    )


def streams(exp_seed: int, n_streams: int = 8) -> list[np.random.Generator]:
    """Return ``n_streams`` independent numpy Generators for one experiment."""
    ss = spawn_experiment_seed(exp_seed)
    return [np.random.default_rng(s) for s in ss.spawn(n_streams)]
