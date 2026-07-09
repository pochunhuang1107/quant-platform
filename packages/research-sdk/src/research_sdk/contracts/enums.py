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


class ArtifactKind(StrEnum):
    """Run artifact categories recorded in artifact manifests."""

    CONFIG = "config"
    METRICS = "metrics"
    TRADE_LOG = "trade_log"
    SIGNAL_LOG = "signal_log"
    DAILY_EQUITY = "daily_equity"
    DRAWDOWN_SERIES = "drawdown_series"
    MONTHLY_RETURNS = "monthly_returns"
    REGIME_BREAKDOWN = "regime_breakdown"
    FAILURE_ANALYSIS = "failure_analysis"
    RESEARCH_NOTE = "research_note"
    CHART = "chart"
    LOG = "log"
    DIAGNOSTIC = "diagnostic"
    OTHER = "other"


class ArtifactFormat(StrEnum):
    """Supported file formats for run artifact manifest entries."""

    JSON = "json"
    PARQUET = "parquet"
    MARKDOWN = "markdown"
    PNG = "png"
    SVG = "svg"
    HTML = "html"
    CSV = "csv"
    TEXT = "text"


class HashAlgorithm(StrEnum):
    """Content hash algorithms supported by artifact manifests."""

    SHA256 = "sha256"


class ArtifactStatus(StrEnum):
    """Production status for a run artifact manifest entry."""

    PRODUCED = "produced"
    MISSING = "missing"
    FAILED = "failed"
    SKIPPED = "skipped"


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
