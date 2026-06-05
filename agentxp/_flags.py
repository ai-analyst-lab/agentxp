"""Process-wide feature flags. v0.1 build-time gates ship here.

`SURFACE_V01_ENABLED` gates the v0.1 user-facing surface flip (sub-verbs,
new readout adapters, share-tail wiring). Waves 0–3 of the v0.1 cleanup
land behind this flag. Wave 4 is the single atomic PR that flips the default
to True and removes the env-var fallback.

Until Wave 4: set ``AGENTXP_SURFACE_V01=1`` to exercise the new path in tests
or local dev; fresh clones see the v0.0 surface unchanged.
"""
from __future__ import annotations

import os

SURFACE_V01_ENABLED: bool = os.environ.get("AGENTXP_SURFACE_V01", "0") == "1"
"""Whether the v0.1 user-facing surface (sub-verbs, new adapters, share-tails)
is exposed. Default False until Wave 4's atomic flip."""
