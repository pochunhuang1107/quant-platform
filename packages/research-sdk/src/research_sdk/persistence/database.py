"""Database configuration helpers for persistence tooling."""

from __future__ import annotations

import os
from typing import Final

DATABASE_URL_ENV_VAR: Final = "DATABASE_URL"


def get_database_url() -> str:
    """Return DATABASE_URL from the environment.

    The helper intentionally does not create engines, sessions, or connections.
    """

    database_url = os.environ.get(DATABASE_URL_ENV_VAR, "").strip()
    if not database_url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV_VAR} must be set for online database migrations."
        )

    return database_url
