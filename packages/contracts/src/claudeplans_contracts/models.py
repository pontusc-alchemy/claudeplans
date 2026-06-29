"""The structured document model — the canonical shape behind every plan/research doc.

All models forbid extra keys (extra="forbid") so unknown fields reject at the
boundary as a pydantic ValidationError (the API maps that to HTTP 422). The one
escape hatch is Document.frontmatter, a free-form dict for metadata we don't model.
"""

from __future__ import annotations

import datetime
import re
import unicodedata

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from .enums import DocStatus, DocType, PhaseStatus, SectionPlacement
from .keys import validate_key_segment

# Unicode categories that must never appear in single-line content: Cc (C0/C1
# controls + DEL, which includes tab/newline/CR and NEL U+0085), Zl (line separator
# U+2028), Zp (paragraph separator U+2029). Normal spaces (Zs) and zero-width/format
# chars (Cf) are left alone; the multi-line `body` is exempt entirely (raw markdown).
_FORBIDDEN_TEXT_CATEGORIES = frozenset({"Cc", "Zl", "Zp"})

# A clean, routable identifier: letters, digits, '-', '_'. Excludes '/', '.', URL
# metacharacters, and whitespace by construction (see validate_anchor).
_ANCHOR_RE = re.compile(r"[A-Za-z0-9_-]+")


def validate_text_field(value: str, *, field: str) -> str:
    """Reject empty/whitespace-only content and embedded control chars / line breaks.

    Applied to single-line content fields (title, description, section heading, phase
    name, task text) so an agent cannot persist a blank or line-break-laden value that
    corrupts rendering. Line breaks include the Unicode separators U+2028/U+2029 and
    NEL, not just ASCII newlines. Raises ValueError -> pydantic ValidationError (HTTP
    422 -> CLI exit 4).
    """
    if not value.strip():
        raise ValueError(f"{field} must not be empty or whitespace-only")
    bad = next(
        (c for c in value if unicodedata.category(c) in _FORBIDDEN_TEXT_CATEGORIES),
        None,
    )
    if bad is not None:
        raise ValueError(
            f"{field} must not contain control characters or line breaks "
            f"(found {bad!r})"
        )
    return value


def validate_anchor(value: str, *, field: str) -> str:
    """Validate a phase slug / section anchor as a clean, routable identifier.

    Restricts to `[A-Za-z0-9_-]`. The identifier is interpolated raw into request URLs
    (so a URL metacharacter like '#'/'?'/space would corrupt routing — a '#' silently
    truncates the request to a *different* target) and into the `phases.<slug>`
    drift-locator grammar (so '.' would make the locator ambiguous); the allowlist
    excludes all of these plus '/', path-traversal, and control chars in one rule. The
    '@'-prefix gets a tailored message: it is the `@end` footgun — agents reach for
    '@end' expecting append semantics, but sections and phases are always appended in
    order.
    """
    if _ANCHOR_RE.fullmatch(value) is None:
        if value.startswith("@"):
            raise ValueError(
                f"{field} {value!r}: '@'-prefixed anchors are reserved — sections and "
                "phases are appended in order, so there is no '@end'/position target; "
                "use a plain identifier"
            )
        raise ValueError(
            f"{field} {value!r} must be a non-empty identifier of letters, digits, "
            "'-' or '_' (no '/', '.', whitespace, or URL metacharacters)"
        )
    return value


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    checked: bool = False

    @field_validator("text")
    @classmethod
    def _validate_text(cls, v: str) -> str:
        return validate_text_field(v, field="task text")


class Section(BaseModel):
    """A prose markdown section. `body` is raw markdown."""

    model_config = ConfigDict(extra="forbid")

    anchor: str
    heading: str
    body: str = ""
    # Bounded to 1..6: it becomes an <h{level}> heading, and nh3 strips <h0>/<h7+>,
    # which would silently drop the heading. Reject out of range at the boundary.
    level: int = Field(2, ge=1, le=6)
    # Render bucket, not an ordinal: lead sections render before the phase group,
    # trail sections after. List order still governs ordering within a bucket.
    placement: SectionPlacement = SectionPlacement.lead

    @field_validator("anchor")
    @classmethod
    def _validate_anchor(cls, v: str) -> str:
        return validate_anchor(v, field="section anchor")

    @field_validator("heading")
    @classmethod
    def _validate_heading(cls, v: str) -> str:
        return validate_text_field(v, field="section heading")


class Phase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    status: PhaseStatus = PhaseStatus.todo
    tasks: list[Task] = Field(default_factory=list)
    # Phase prose, stored first-class (was reconstructed at render time). Plain raw
    # markdown like Section.body — empty/multiline allowed, so no text validator.
    intro: str = ""
    exit_criteria: str = ""
    notes: str = ""

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        return validate_anchor(v, field="phase slug")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return validate_text_field(v, field="phase name")


class Document(BaseModel):
    """A plan or research document.

    List order is the canonical ordering: the order of `sections`, `phases`, and a
    phase's `tasks` IS the single source of truth. There is deliberately no separate
    ordinal field — it would duplicate the list order and become its own drift surface.
    `Section.placement` is a render bucket (lead vs trail of the phase group), not an
    ordinal — it does not reintroduce the rejected ordinal field.
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

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        return validate_text_field(v, field="title")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: str | None) -> str | None:
        return v if v is None else validate_text_field(v, field="description")

    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = validate_text_field(v, field="date")
        try:
            datetime.date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(
                f"date must be an ISO date (YYYY-MM-DD), got {v!r}"
            ) from exc
        return v

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
        # locator in DriftWarning.path; duplicates make both ambiguous. Name the
        # offender so an agent can fix it without diffing the whole phase list.
        seen_slugs: set[str] = set()
        for p in self.phases:
            if p.slug in seen_slugs:
                raise ValueError(f"duplicate phase slug {p.slug!r}")
            seen_slugs.add(p.slug)
        # Section anchor is the identity key for section ops (set/patch/rm); duplicates
        # make addressing ambiguous, exactly as for phase slugs.
        seen_anchors: set[str] = set()
        for s in self.sections:
            if s.anchor in seen_anchors:
                raise ValueError(f"duplicate section anchor {s.anchor!r}")
            seen_anchors.add(s.anchor)
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
