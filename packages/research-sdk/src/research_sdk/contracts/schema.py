"""Schema version primitives for research SDK contracts."""

from typing import Annotated

from pydantic import Field

from research_sdk.contracts.base import BaseContractModel

RESEARCH_SDK_CONTRACT_SCHEMA_VERSION = "1.0.0"

type SchemaVersion = Annotated[
    str,
    Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"),
]


class VersionedContract(BaseContractModel):
    """Base class for contracts that carry an explicit schema version."""

    schema_version: SchemaVersion
