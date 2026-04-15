#!/bin/bash
# Vendor sync: pull updated stats code from ai-analyst-plus
#
# Usage: ./scripts/vendor-sync.sh /path/to/ai-analyst-plus
#
# This script copies the experiment_stats modules from the ai-analyst-plus
# repo into openxp/stats/. Run this when ai-analyst-plus improves its
# statistical functions and you want to pull those improvements into OpenXP.

set -euo pipefail

SOURCE="${1:?Usage: vendor-sync.sh /path/to/ai-analyst-plus}"
DEST="$(cd "$(dirname "$0")/.." && pwd)/openxp/stats"

if [ ! -d "$SOURCE/helpers/experiment_stats" ]; then
    echo "ERROR: $SOURCE/helpers/experiment_stats/ not found"
    exit 1
fi

echo "Syncing from: $SOURCE/helpers/experiment_stats/"
echo "Syncing to:   $DEST/"
echo ""

# v0.1 modules (A/B testing core)
MODULES="ab_tests.py power.py srm.py effect_size.py corrections.py"

for module in $MODULES; do
    if [ -f "$SOURCE/helpers/experiment_stats/$module" ]; then
        cp "$SOURCE/helpers/experiment_stats/$module" "$DEST/$module"
        echo "  Synced: $module"
    else
        echo "  SKIP:   $module (not found in source)"
    fi
done

echo ""
echo "Done. Run 'pytest tests/' to verify nothing broke."
echo ""
echo "Note: __init__.py is NOT synced (OpenXP has its own exports)."
echo "If ai-analyst-plus adds new functions, update openxp/stats/__init__.py manually."
