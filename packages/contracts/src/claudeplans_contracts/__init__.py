"""Shared contracts: models, enums, DTOs, and the error -> exit-code mapping.

Leaf package imported by BOTH the claudeplans service and the claudeplans-cli client, so
the two never drift on schema or error semantics. Models land in the data-model
phase; this skeleton defines only the stable error/exit-code contract that the
storage seam, core orchestration, API handlers, and CLI all reference.
"""

from .dto import DriftWarning
from .enums import DocStatus, DocType, PhaseStatus
from .errors import (
    ExitCode,
    NotFound,
    PlanError,
    StaleRevision,
    ValidationError,
)
from .migrate import CURRENT_SCHEMA_VERSION, migrate, migrate_document
from .models import Document, Phase, Section, Task, unlink_research_ref

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DocStatus",
    "DocType",
    "Document",
    "DriftWarning",
    "ExitCode",
    "NotFound",
    "Phase",
    "PhaseStatus",
    "PlanError",
    "Section",
    "StaleRevision",
    "Task",
    "ValidationError",
    "migrate",
    "migrate_document",
    "unlink_research_ref",
]
