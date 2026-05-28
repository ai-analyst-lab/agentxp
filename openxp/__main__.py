"""Enable `python -m openxp` as an alias for the openxp CLI."""
from openxp.cli.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
