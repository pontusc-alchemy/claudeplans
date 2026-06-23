"""Wire DTOs shared by the service and the CLI."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .enums import DocStatus, DocType, PhaseStatus
from .models import Phase, Section


class DriftWarning(BaseModel):
    """An item in the shared {data, warnings[]} envelope.

    Named DriftWarning rather than Warning to avoid shadowing the builtin. Produced
    by the server's drift linter, consumed by the CLI.

    `path` is a dotted locator into the document: "phases.<slug>" for a phase-scoped
    warning, None for a document-level warning. The CLI parses this, so the grammar
    is a contract; it keys phases by slug, which is why phase slugs must be unique
    (see models.py Document._check_invariants).
    """

    code: str
    message: str
    path: str | None = None


class DocumentCreate(BaseModel):
    """The create payload for a new document.

    The server composes the full Document by adding owner_id/project from the URL
    path (they are not on the wire body) and the server-set schema_version. Mirrors
    Document's extra="forbid" so unknown wire fields reject as a 422.
    """

    model_config = ConfigDict(extra="forbid")

    type: DocType
    slug: str
    title: str
    status: DocStatus = DocStatus.draft
    date: str | None = None
    description: str | None = None
    frontmatter: dict[str, JsonValue] = Field(default_factory=dict)
    research_refs: list[str] = Field(default_factory=list)
    primary_research_ref: str | None = None
    sections: list[Section] = Field(default_factory=list)
    phases: list[Phase] = Field(default_factory=list)


class DocStatusRequest(BaseModel):
    """Set the document's status."""

    model_config = ConfigDict(extra="forbid")

    status: DocStatus


class AddPhaseRequest(BaseModel):
    """Add a phase (appended; reposition is the separate move op)."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    status: PhaseStatus = PhaseStatus.todo


class PhaseStatusRequest(BaseModel):
    """Set a phase's status."""

    model_config = ConfigDict(extra="forbid")

    status: PhaseStatus


class MovePhaseRequest(BaseModel):
    """Move a phase to a new position in the ordering."""

    model_config = ConfigDict(extra="forbid")

    to_index: int


class AddTaskRequest(BaseModel):
    """Add a task to a phase (appended)."""

    model_config = ConfigDict(extra="forbid")

    text: str


class ToggleTaskRequest(BaseModel):
    """Set a task's checked state to an ABSOLUTE target value.

    Never a relative flip — the absolute value is what keeps the op re-apply-safe.
    """

    model_config = ConfigDict(extra="forbid")

    checked: bool


class EditTaskRequest(BaseModel):
    """Replace a task's text."""

    model_config = ConfigDict(extra="forbid")

    text: str


class AddSectionRequest(BaseModel):
    """Add a prose section (appended)."""

    model_config = ConfigDict(extra="forbid")

    anchor: str
    heading: str
    body: str = ""
    level: int = Field(2, ge=1, le=6)


class SetSectionRequest(BaseModel):
    """Absolute set of the provided section fields; None leaves a field unchanged."""

    model_config = ConfigDict(extra="forbid")

    heading: str | None = None
    body: str | None = None
    level: int | None = Field(None, ge=1, le=6)


class PatchSectionRequest(BaseModel):
    """An RFC 7386 JSON Merge Patch applied over the section."""

    model_config = ConfigDict(extra="forbid")

    patch: dict[str, JsonValue]


class ResearchRefsRequest(BaseModel):
    """Replace the document's research refs and optional primary designation."""

    model_config = ConfigDict(extra="forbid")

    research_refs: list[str]
    primary_research_ref: str | None = None


class SearchHit(BaseModel):
    """One search match: which document matched, and what in it matched.

    `kind` says whether the query hit the document title, a section heading, or a
    phase name; `text` is the matched string; `anchor` is the in-document target for
    navigation — a section anchor or a phase slug — and is None for a title hit.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    project: str
    slug: str
    title: str
    type: DocType
    status: DocStatus
    kind: Literal["title", "section", "phase"]
    text: str
    anchor: str | None = None


class SearchResults(BaseModel):
    """The search response: the echoed query and its ordered hits."""

    model_config = ConfigDict(extra="forbid")

    query: str
    hits: list[SearchHit]
