"""Enable `python -m agentxp` as an alias for the agentxp CLI."""
from agentxp.cli.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
