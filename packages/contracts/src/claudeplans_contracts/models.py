"""The structured document model — the canonical shape behind every plan/research doc.

All models forbid extra keys (extra="forbid") so unknown fields reject at the
boundary as a pydantic ValidationError (the API maps that to HTTP 422). The one
escape hatch is Document.frontmatter, a free-form dict for metadata we don't model.
"""

from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from .enums import DocStatus, DocType, PhaseStatus
from .keys import validate_key_segment


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    checked: bool = False


class Section(BaseModel):
    """A prose markdown section. `body` is raw markdown."""

    model_config = ConfigDict(extra="forbid")

    anchor: str
    heading: str
    body: str = ""
    # Bounded to 1..6: it becomes an <h{level}> heading, and nh3 strips <h0>/<h7+>,
    # which would silently drop the heading. Reject out of range at the boundary.
    level: int = Field(2, ge=1, le=6)


class Phase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    status: PhaseStatus = PhaseStatus.todo
    tasks: list[Task] = Field(default_factory=list)


class Document(BaseModel):
    """A plan or research document.

    List order is the canonical ordering: the order of `sections`, `phases`, and a
    phase's `tasks` IS the single source of truth. There is deliberately no separate
    ordinal field — it would duplicate the list order and become its own drift surface.
    """

    model_config = ConfigDict(extra="forbid")

    # Must equal migrate.CURRENT_SCHEMA_VERSION; asserted there. Set as a literal
    # here to avoid a circular import (migrate imports Document).
    schema_version: int = 1
    type: DocType
    status: DocStatus = DocStatus.draft
    project: str
    slug: str
    title: str
    owner_id: str
    date: str | None = None
    description: str | None = None
    # Free-form metadata escape hatch: Document forbids extra keys, so anything we
    # don't model explicitly lives here. Must be JSON-serializable (JsonValue) — it
    # round-trips through storage as JSON, so non-JSON values (datetime/set/bytes/
    # tuple) are intentionally rejected at validation.
    frontmatter: dict[str, JsonValue] = Field(default_factory=dict)
    research_refs: list[str] = Field(default_factory=list)
    primary_research_ref: str | None = None
    sections: list[Section] = Field(default_factory=list)
    phases: list[Phase] = Field(default_factory=list)

    @field_validator("owner_id", "project", "slug")
    @classmethod
    def _key_safe(cls, v: str) -> str:
        # These three fields are storage-key segments; the rule lives in keys.py so
        # the model and raw document_key callers validate against one shared source.
        return validate_key_segment(v)

    @field_validator("research_refs")
    @classmethod
    def _dedup_research_refs(cls, v: list[str]) -> list[str]:
        # Duplicates are meaningless and make `primary in refs` / listing ambiguous.
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def _check_invariants(self) -> Document:
        # Research documents describe findings, not work — phases belong to plans only.
        if self.type is DocType.research and self.phases:
            raise ValueError("research documents cannot carry phases")
        # The primary ref is a designation among the refs, not a standalone field.
        if (
            self.primary_research_ref is not None
            and self.primary_research_ref not in self.research_refs
        ):
            raise ValueError("primary_research_ref must be one of research_refs")
        # Phase slug is the identity key for phase ops (set-status/move/rm) and the
        # locator in DriftWarning.path; duplicates make both ambiguous.
        if len({p.slug for p in self.phases}) != len(self.phases):
            raise ValueError("phase slugs must be unique")
        # Section anchor is the identity key for section ops (set/patch/rm); duplicates
        # make addressing ambiguous, exactly as for phase slugs.
        if len({s.anchor for s in self.sections}) != len(self.sections):
            raise ValueError("section anchors must be unique")
        return self


def unlink_research_ref(
    research_refs: list[str], primary_research_ref: str | None, ref: str
) -> tuple[list[str], str | None]:
    """Remove `ref` from the refs, returning the new (refs, primary) pair.

    Pure: builds a new list, never mutates the inputs. Removing `ref` is a no-op if
    it isn't present. When the removed ref was the primary, the primary is promoted to
    the first remaining ref, or cleared to None if nothing remains.
    """
    new_refs = [r for r in research_refs if r != ref]
    if primary_research_ref == ref:
        new_primary = new_refs[0] if new_refs else None
    else:
        new_primary = primary_research_ref
    return new_refs, new_primary
