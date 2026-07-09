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


class ExperimentRunStatus(StrEnum):
    """Allowed experiment ledger run statuses."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    INVALID = "invalid"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class FailureLabel(StrEnum):
    """Machine-readable labels for experiment run failure modes."""

    DATA_UNAVAILABLE = "data_unavailable"
    DATA_VALIDATION_FAILED = "data_validation_failed"
    CONFIG_VALIDATION_FAILED = "config_validation_failed"
    LEAKAGE_CHECK_FAILED = "leakage_check_failed"
    ARTIFACT_VALIDATION_FAILED = "artifact_validation_failed"
    EXECUTION_ERROR = "execution_error"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    DEPENDENCY_ERROR = "dependency_error"
    UNKNOWN = "unknown"


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
