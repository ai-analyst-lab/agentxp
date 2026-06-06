"""Orchestrator error hierarchy (W5.1).

CLAUDE.md §10 names three failure categories for the orchestrator:

  1. **Tool refusal** — a tool refused the action (R11 wall, schema
     validation, resource bound, etc.). Surfaced as ``ToolRefusal``.
  2. **Malformed specialist output** — the specialist returned something
     that doesn't validate against the role's output schema. Surfaced as
     ``MalformedSpecialistOutput``. The orchestrator's
     ``complete_dispatch`` retries once with the prior error attached
     (W1.5 ``BundleBase.prior_error``) before raising.
  3. **Crash** — process died. There's no exception to surface for that
     category; the next session reads ``log.md`` and asks the user
     where to resume.

This module declares the type hierarchy so consumers can catch at the
right granularity (one ``OrchestratorError`` base, leaf classes for each
named failure). ``ToolRefusal`` previously lived in ``tools.py``; it is
re-exported from here to keep the hierarchy consistent.
"""
from __future__ import annotations


class OrchestratorError(Exception):
    """Base class for every orchestrator-side failure.

    Catch this if you want to handle any orchestrator failure uniformly
    (e.g. at the verb-runner boundary). Catch a leaf class if you care
    about a specific category.
    """


class BundleAssemblyError(OrchestratorError):
    """The role's sources failed schema validation at assemble() time.

    R10 enforcement (CLAUDE.md): the bundle assembler refuses any source
    field outside the role's ``BundleSchema``. Raised by
    ``agentxp.orchestrator.bundle_assembler.assemble`` and re-raised by
    ``dispatch_specialist`` so the caller never sees a partially
    constructed bundle.
    """


class MalformedSpecialistOutput(OrchestratorError):
    """The specialist's output didn't validate against the role's output schema.

    CLAUDE.md §10 failure category 2. The orchestrator's
    ``complete_dispatch`` (W5.2) catches the first ``ValidationError``,
    repackages the per-field errors into ``BundleBase.prior_error``, and
    re-dispatches the bundle. On second failure this exception is raised
    with both error lists attached.
    """

    def __init__(
        self,
        message: str,
        first_errors: list[dict],
        second_errors: list[dict],
    ) -> None:
        super().__init__(message)
        self.first_errors = first_errors
        self.second_errors = second_errors


class DispatchTimeout(OrchestratorError):
    """The harness didn't return within the timeout window.

    Distinct from the silent-crash category (which has no exception to
    catch): a timeout means the harness was reachable, accepted the
    dispatch descriptor, and never came back with a response. The
    orchestrator should ask the user before retrying — a timeout on a
    long-running specialist (e.g. an analyst doing a long stats
    computation) may be a legitimate completion that just exceeded the
    budget.
    """


class ToolRefusal(OrchestratorError):
    """A tool refused to execute the requested action.

    Raised by orchestrator-side wrappers around the SQL safety pipeline,
    the seal verifier, ``commit_artifact``, and similar. The orchestrator
    surfaces the reason and the path forward to the user; not a crash,
    not a malformed output — a deliberate refusal.

    Pre-W5.1 this class lived in ``agentxp.orchestrator.tools``; the
    canonical home is now this module. ``tools`` re-exports for
    backwards compatibility.
    """


__all__ = [
    "OrchestratorError",
    "BundleAssemblyError",
    "MalformedSpecialistOutput",
    "DispatchTimeout",
    "ToolRefusal",
]
