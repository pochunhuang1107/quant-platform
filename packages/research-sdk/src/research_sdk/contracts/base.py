"""Base Pydantic model configuration for contract schemas."""

from pydantic import BaseModel, ConfigDict


class BaseContractModel(BaseModel):
    """Base model for JSON-friendly contract records."""

    model_config = ConfigDict(extra="forbid")
