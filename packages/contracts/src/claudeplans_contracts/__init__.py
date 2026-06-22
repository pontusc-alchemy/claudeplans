"""Shared contracts: models, enums, DTOs, and the error -> exit-code mapping.

Leaf package imported by BOTH the claudeplans service and the claudeplans-cli client, so
the two never drift on schema or error semantics. Models land in the data-model
phase; this skeleton defines only the stable error/exit-code contract that the
storage seam, core orchestration, API handlers, and CLI all reference.

Each `X as X` is an explicit re-export: it marks the name as part of this
package's public surface (ruff F401 / the no-implicit-reexport rule). The import
line IS the API declaration — there is no separate `__all__` list to drift from it.
"""

from .dto import DriftWarning as DriftWarning
from .enums import DocStatus as DocStatus
from .enums import DocType as DocType
from .enums import PhaseStatus as PhaseStatus
from .errors import ExitCode as ExitCode
from .errors import NotFound as NotFound
from .errors import PlanError as PlanError
from .errors import StaleRevision as StaleRevision
from .errors import ValidationError as ValidationError
from .keys import document_key as document_key
from .keys import key_for_document as key_for_document
from .keys import validate_key_segment as validate_key_segment
from .migrate import CURRENT_SCHEMA_VERSION as CURRENT_SCHEMA_VERSION
from .migrate import migrate as migrate
from .migrate import migrate_document as migrate_document
from .models import Document as Document
from .models import Phase as Phase
from .models import Section as Section
from .models import Task as Task
from .models import unlink_research_ref as unlink_research_ref
