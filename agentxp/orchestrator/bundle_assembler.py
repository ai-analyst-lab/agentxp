"""Schema-enforced bundle assembly (T60, R10).

The orchestrator dispatches specialist sub-agents with schema-validated
bundles. The assembler looks up the role's BundleSchema from
``BUNDLE_SCHEMAS`` (defined in ``agentxp.schemas.bundles``) and constructs
an instance from the supplied source dict. Pydantic's ``extra="forbid"``
rejects any source field that is not declared in the schema — the
orchestrator cannot leak context to a sub-agent it should not see.

This module replaces the v0.1 ``orchestrator/bundle.py`` (which copied
project-level YAMLs into per-experiment bundle directories under a
shared-read project lock to prevent multi-session races). Single-user v2
does not need the COPY-and-lock pattern; the SHA-snapshot of bundle
contents is preserved per-source for audit replay.

R10 enforcement loop:
    raw_sources = {...}                         # orchestrator collects
    bundle = assemble("critic", raw_sources)    # Pydantic validates
    # bundle is an instance of CriticBundle; any unauthorized field in
    # raw_sources was either silently dropped (if Pydantic v2 default) or
    # raised as ValidationError (because extra="forbid" on every bundle).

The blindness manifest in ``agentxp.schemas.bundles.BLINDNESS_MANIFEST``
declares per-role forbidden field names. The closure test in
``tests/orchestrator/test_bundle_assembler.py`` (T61) iterates it and
asserts every forbidden field is absent from the schema's model_fields.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from agentxp.schemas.bundles import (
    BLINDNESS_MANIFEST,
    BUNDLE_SCHEMAS,
)


class UnknownSpecialistRole(KeyError):
    """The role name passed to :func:`assemble` is not registered.

    Raised when ``role`` is not a key in ``BUNDLE_SCHEMAS``. Adding a new
    specialist requires adding its schema to ``agentxp.schemas.bundles`` —
    this exception is the audit point for that gate.
    """


class BundleAssemblyError(ValueError):
    """The source dict failed bundle schema validation.

    The underlying ``pydantic.ValidationError`` is attached as
    ``__cause__``. Typical causes:

      - A required field is missing from the source dict.
      - An extra field was supplied that the role's schema does not
        declare (R10 enforcement — the orchestrator tried to leak a
        forbidden field; the schema refused).
      - A field's value failed the schema's per-field validation.

    The exception message names the role and reports the validation
    error count. The full error list is on ``__cause__``.
    """


class AssembledBundle(BaseModel):
    """Wrapper around a validated bundle instance.

    Carries the role name (so the orchestrator can re-dispatch by role),
    the schema-validated bundle as a Pydantic model, and the sha256
    snapshot used at assembly time for audit replay. The hash is computed
    over the bundle's canonical JSON serialization so re-running the
    assembler with identical sources produces an identical hash.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    role: str
    bundle: BaseModel
    sha256: str  # 64-char lowercase hex


def _canonical_bytes(model: BaseModel) -> bytes:
    """Return canonical JSON bytes for a Pydantic model (sorted keys).

    Used for the SHA snapshot so re-assembly with identical source
    fields produces an identical hash regardless of dict iteration order.
    """
    # Pydantic v2: model_dump_json with by_alias=False, exclude_unset=False
    # gives a stable dump; we re-serialize through json.dumps with
    # sort_keys=True for deterministic ordering.
    dump = json.loads(model.model_dump_json())
    return json.dumps(dump, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def assemble(role: str, sources: dict[str, Any]) -> AssembledBundle:
    """Build a schema-validated bundle for ``role`` from ``sources``.

    Looks up the role's bundle schema in ``BUNDLE_SCHEMAS`` and constructs
    an instance. Pydantic's ``extra="forbid"`` rejects any source field
    that the schema does not declare — this is R10 enforcement: the
    orchestrator cannot route a field to a specialist that the specialist's
    bundle schema does not authorize, no matter how it tries.

    Returns an :class:`AssembledBundle` carrying the validated model and
    a sha256 snapshot of its canonical serialization. Raises:

      - :class:`UnknownSpecialistRole` if ``role`` is not registered.
      - :class:`BundleAssemblyError` if the sources do not validate.
    """
    schema_cls = BUNDLE_SCHEMAS.get(role)
    if schema_cls is None:
        raise UnknownSpecialistRole(
            f"role {role!r} is not in BUNDLE_SCHEMAS; "
            f"registered roles: {sorted(BUNDLE_SCHEMAS)}"
        )

    try:
        instance = schema_cls(**sources)
    except ValidationError as ve:
        err = BundleAssemblyError(
            f"sources failed validation for role {role!r}: "
            f"{len(ve.errors())} error(s); "
            f"see __cause__ for the pydantic ValidationError"
        )
        raise err from ve

    return AssembledBundle(
        role=role,
        bundle=instance,
        sha256=_sha256_hex(_canonical_bytes(instance)),
    )


def assert_blindness_manifest_holds() -> None:
    """Closure-test invariant: every forbidden field is absent from its schema.

    Iterates ``BLINDNESS_MANIFEST`` and asserts each forbidden field name
    is NOT in the corresponding bundle's ``model_fields``. Raises
    AssertionError naming the offending role + field on violation.

    This is the runtime sibling to the static test in
    ``tests/orchestrator/test_bundle_assembler.py``. Callers may invoke it
    at orchestrator startup as a defense-in-depth check.
    """
    for role, forbidden_fields in BLINDNESS_MANIFEST.items():
        schema_cls = BUNDLE_SCHEMAS.get(role)
        if schema_cls is None:
            raise AssertionError(
                f"BLINDNESS_MANIFEST names role {role!r} which is not in "
                f"BUNDLE_SCHEMAS"
            )
        declared = set(schema_cls.model_fields.keys())
        for field_name in forbidden_fields:
            if field_name in declared:
                raise AssertionError(
                    f"{role} bundle declares field {field_name!r}, which is "
                    f"in BLINDNESS_MANIFEST as forbidden. "
                    f"R5/R6/R10 violation — review the bundle schema."
                )


__all__ = [
    "AssembledBundle",
    "BundleAssemblyError",
    "UnknownSpecialistRole",
    "assemble",
    "assert_blindness_manifest_holds",
]
