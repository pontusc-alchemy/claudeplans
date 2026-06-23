"""The single derivation point for storage keys.

Called by BOTH the server and the CLI so the two can never disagree on the
on-disk layout. The key namespaces by owner first, so a prefix list scopes to one
user, matching the /v1/users/{uid}/... routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only: key_for_document reads attributes at runtime but needs Document
    # only for the annotation, which `from __future__ import annotations` defers to
    # a string — so this import breaks the keys <-> models cycle.
    from .models import Document


def validate_key_segment(value: str) -> str:
    """Validate one storage-key segment (owner_id / project / slug).

    Segments compose the opaque storage key `owner/project/slug`; one that is
    empty, contains '/', or is '.'/'..' would let the key collide or escape its
    directory. Raises ValueError so the Document field validator surfaces it as a
    pydantic ValidationError (-> HTTP 422) at the boundary.
    """
    if not value or "/" in value or value in (".", ".."):
        raise ValueError(
            f"invalid key segment {value!r}: must be non-empty and contain no "
            "'/' or path-traversal segment"
        )
    return value


def document_key(owner_id: str, project: str, slug: str) -> str:
    """Derive the opaque storage key from a document's identity tuple.

    Validates each raw segment here too (not just at the model boundary) so a CLI
    or raw caller that bypasses Document can't compose a colliding or escaping key.
    A slug is unique within an owner+project, so type is not part of the key.
    """
    validate_key_segment(owner_id)
    validate_key_segment(project)
    validate_key_segment(slug)
    return f"{owner_id}/{project}/{slug}"


def key_for_document(doc: Document) -> str:
    """Storage key for an already-built Document."""
    return document_key(doc.owner_id, doc.project, doc.slug)
