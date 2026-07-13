"""Canonical hashing helpers for validated persistence contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel


def _canonical_json(payload: Mapping[str, Any]) -> str:
    """Return compact deterministic JSON for a JSON-compatible mapping."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    """Hash a JSON-compatible mapping without reading or verifying external files."""

    canonical_json = _canonical_json(payload)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def canonical_contract_json(contract: BaseModel) -> str:
    """Return canonical JSON for a validated Pydantic contract object."""

    return _canonical_json(contract.model_dump(mode="json"))


def contract_sha256(contract: BaseModel) -> str:
    """Return the SHA-256 contract hash for audit and idempotency metadata."""

    canonical_json = canonical_contract_json(contract)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
