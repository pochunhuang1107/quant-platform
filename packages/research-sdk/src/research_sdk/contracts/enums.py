"""Common enumerations shared by research contracts."""

from enum import StrEnum


class AssetClass(StrEnum):
    """Supported high-level asset classes for research contracts."""

    EQUITIES = "equities"
    ETFS = "etfs"
    FUTURES = "futures"
    FX = "fx"
    CRYPTO = "crypto"
    INDICES = "indices"
    OPTIONS = "options"
    MIXED = "mixed"


class ReviewStatus(StrEnum):
    """Review states captured as metadata, not approval workflow logic."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ReviewRole(StrEnum):
    """Reviewer role labels used in durable review metadata."""

    HUMAN_OWNER = "human_owner"
    RISK_REVIEWER = "risk_reviewer"
    AGENT_REVIEWER = "agent_reviewer"
