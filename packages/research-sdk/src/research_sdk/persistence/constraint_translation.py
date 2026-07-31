"""Pure constraint-name translation for persistence domain conflicts."""

from __future__ import annotations

from dataclasses import replace

from research_sdk.persistence.errors import (
    DuplicateReviewEventError,
    PersistenceConflictError,
    PersistenceErrorContext,
    UnsupportedVersioningConflictError,
)

_CONSTRAINT_ERROR_TYPES: dict[
    str,
    type[PersistenceConflictError],
] = {
    "pk_review_events": DuplicateReviewEventError,
    "uq_run_artifact_manifests_run_id": UnsupportedVersioningConflictError,
}


def translate_constraint_violation(
    *,
    constraint_name: str,
    context: PersistenceErrorContext,
) -> PersistenceConflictError | None:
    """Translate an approved exact constraint name to a domain conflict."""

    if not constraint_name.strip():
        raise ValueError("constraint_name must not be blank")

    validated_context = _context_with_matching_constraint_name(
        constraint_name=constraint_name,
        context=context,
    )
    error_type = _CONSTRAINT_ERROR_TYPES.get(constraint_name)
    if error_type is None:
        return None

    return error_type(validated_context)


def _context_with_matching_constraint_name(
    *,
    constraint_name: str,
    context: PersistenceErrorContext,
) -> PersistenceErrorContext:
    if context.constraint_name is None:
        return replace(context, constraint_name=constraint_name)

    if context.constraint_name != constraint_name:
        raise ValueError("context constraint_name must match constraint_name")

    return context


__all__ = ["translate_constraint_violation"]
