"""Shared, offline-only data tooling for the SupportHR ML pipeline."""

from .contracts import (
    GRAPH_FACT_SCHEMA_VERSION,
    NORMALIZED_DOCUMENT_SCHEMA_VERSION,
    SOURCE_MANIFEST_SCHEMA_VERSION,
)

__all__ = [
    "GRAPH_FACT_SCHEMA_VERSION",
    "NORMALIZED_DOCUMENT_SCHEMA_VERSION",
    "SOURCE_MANIFEST_SCHEMA_VERSION",
]
