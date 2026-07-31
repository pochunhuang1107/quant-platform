"""Narrow SQLAlchemy driver-exception translation for persistence conflicts."""

from __future__ import annotations

from typing import Final

from sqlalchemy.exc import IntegrityError

from research_sdk.persistence.constraint_translation import (
    translate_constraint_violation,
)
from research_sdk.persistence.errors import (
    PersistenceConflictError,
    PersistenceErrorContext,
)

_UNIQUE_VIOLATION_SQLSTATE: Final = "23505"


def translate_sqlalchemy_integrity_error(
    *,
    error: IntegrityError,
    context: PersistenceErrorContext,
) -> PersistenceConflictError | None:
    """Translate an approved PostgreSQL unique constraint violation."""

    constraint_name = _extract_psycopg_unique_constraint_name(error)
    if constraint_name is None:
        return None

    return translate_constraint_violation(
        constraint_name=constraint_name,
        context=context,
    )


def _extract_psycopg_unique_constraint_name(
    error: IntegrityError,
) -> str | None:
    orig = error.orig
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate != _UNIQUE_VIOLATION_SQLSTATE:
        return None

    diag = getattr(orig, "diag", None)
    if diag is None:
        return None

    constraint_name = getattr(diag, "constraint_name", None)
    if not isinstance(constraint_name, str):
        return None

    if not constraint_name.strip():
        return None

    return constraint_name


__all__ = ["translate_sqlalchemy_integrity_error"]
