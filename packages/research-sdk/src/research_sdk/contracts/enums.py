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


class DataSnapshotKind(StrEnum):
    """Dataset snapshot categories used by reproducible research runs."""

    MARKET_DATA = "market_data"
    FUNDAMENTAL_DATA = "fundamental_data"
    REFERENCE_DATA = "reference_data"
    CORPORATE_ACTIONS = "corporate_actions"
    UNIVERSE_MEMBERSHIP = "universe_membership"
    BENCHMARK_DATA = "benchmark_data"
    MIXED = "mixed"
    OTHER = "other"


class DataSourceType(StrEnum):
    """Source categories for data snapshot manifests."""

    VENDOR = "vendor"
    EXCHANGE = "exchange"
    PUBLIC_DATASET = "public_dataset"
    INTERNAL = "internal"
    RESEARCH_GENERATED = "research_generated"
    MANUAL = "manual"
    OTHER = "other"


class DataAdjustmentPolicy(StrEnum):
    """Adjustment policy labels for data snapshot manifests."""

    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"
    TOTAL_RETURN = "total_return"
    CONTINUOUS = "continuous"
    OTHER = "other"


class TemporalCoverage(StrEnum):
    """Point-in-time semantics for a data snapshot."""

    POINT_IN_TIME = "point_in_time"
    FIRST_AVAILABLE = "first_available"
    LATEST_KNOWN = "latest_known"
    MIXED = "mixed"
    NOT_APPLICABLE = "not_applicable"


class DataSnapshotStatus(StrEnum):
    """Lifecycle status recorded by a data snapshot manifest."""

    CREATED = "created"
    COMPLETED = "completed"
    FAILED = "failed"
    INVALID = "invalid"
    SUPERSEDED = "superseded"


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


class ResearchNoteType(StrEnum):
    """Structured research note categories."""

    HYPOTHESIS = "hypothesis"
    EXPERIMENT_RESULT = "experiment_result"
    FAILURE_ANALYSIS = "failure_analysis"
    REVIEW_NOTE = "review_note"
    OTHER = "other"


class ResearchNoteStatus(StrEnum):
    """Lifecycle status for a structured research note."""

    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    UNDER_REVIEW = "under_review"
    FINALIZED = "finalized"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class HypothesisStatus(StrEnum):
    """Validation status for a research hypothesis."""

    PROPOSED = "proposed"
    TESTING = "testing"
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NOT_SUPPORTED = "not_supported"
    INCONCLUSIVE = "inconclusive"
    SUPERSEDED = "superseded"


class EvidenceStrength(StrEnum):
    """Qualitative evidence strength for a research note decision."""

    NONE = "none"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class DecisionOutcome(StrEnum):
    """Decision outcomes captured by research notes."""

    NO_DECISION = "no_decision"
    CONTINUE_RESEARCH = "continue_research"
    ACCEPT_RESULT = "accept_result"
    REJECT_RESULT = "reject_result"
    MARK_INVALID = "mark_invalid"
    SUPERSEDE_PRIOR = "supersede_prior"
    NEEDS_CHANGES = "needs_changes"


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
