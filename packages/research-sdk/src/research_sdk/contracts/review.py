"""Review metadata skeleton for research contracts."""

from research_sdk.contracts.base import BaseContractModel
from research_sdk.contracts.enums import ReviewRole, ReviewStatus
from research_sdk.contracts.time import UtcDatetime
from research_sdk.contracts.types import NonEmptyString


class ReviewMetadata(BaseContractModel):
    """Structured review metadata without approval workflow behavior."""

    review_status: ReviewStatus
    reviewer_id: NonEmptyString | None = None
    review_role: ReviewRole | None = None
    reviewed_at: UtcDatetime | None = None
    decision: str | None = None
    approval_scope: str | None = None
    approval_expires_at: UtcDatetime | None = None
    linked_pr: str | None = None
    review_notes_uri: str | None = None
    risk_approval_required: bool
