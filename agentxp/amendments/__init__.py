"""
Amendments — structured change tracking for locked experiment.yaml files.

Once an experiment leaves DESIGNING, any change to the pre-registered
hypothesis, metrics, power config, or decision rules is an *amendment*: it
must be recorded with a reason, an author, and a diff, so the final readout
can disclose mid-flight changes.

Public API:
    Amendment              - dataclass record
    AmendmentTracker       - writes/reads amendments.jsonl under the store
    diff_experiments       - deep-diff two experiment dicts
    classify_change        - material vs administrative change classifier
    require_amendment_for_transition - which lifecycle retreats need reasons
"""

from .diff import classify_change, diff_experiments
from .tracker import Amendment, AmendmentTracker, require_amendment_for_transition

__all__ = [
    "Amendment",
    "AmendmentTracker",
    "classify_change",
    "diff_experiments",
    "require_amendment_for_transition",
]
