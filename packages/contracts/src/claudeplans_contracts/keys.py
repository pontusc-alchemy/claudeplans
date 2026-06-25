"""The single derivation point for storage keys.

Called by BOTH the server and the CLI so the two can never disagree on the
on-disk layout. The key namespaces by owner first, so a prefix list scopes to one
user, matching the /v1/users/{uid}/... routes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only: key_for_document reads attributes at runtime but needs Document
    # only for the annotation, which `from __future__ import annotations` defers to
    # a string — so this import breaks the keys <-> models cycle.
    from .models import Document

# Positive allowlist identical in spirit to validate_anchor: only letters, digits,
# '-', '_'. Excludes '/', '.', URL metacharacters (#, ?, space, @), NUL/control
# chars, and newlines by construction. A NUL byte triggers a server HTTP 500 on
# filesystem._path_for; '#'/'?' make the slug permanently unaddressable when
# interpolated raw into request URLs; a newline causes httpx.InvalidURL on the
# client side. The allowlist stops all of these in one rule.
_KEY_SEGMENT_RE = re.compile(r"[A-Za-z0-9_-]+")


def validate_key_segment(value: str) -> str:
    """Validate one storage-key segment (owner_id / project / slug).

    Segments compose the opaque storage key `owner/project/slug`. The allowlist
    `[A-Za-z0-9_-]` prevents: path traversal ('/', '.', '..'), URL metacharacters
    ('#', '?', '@', space) that silently truncate request URLs to the wrong key,
    NUL bytes that crash the filesystem layer, and newlines/control chars that
    cause httpx.InvalidURL on the client. Raises ValueError so the Document field
    validator surfaces it as a pydantic ValidationError (-> HTTP 422 -> CLI exit 4).
    """
    if _KEY_SEGMENT_RE.fullmatch(value) is None:
        raise ValueError(
            f"invalid key segment {value!r}: only letters, digits, '-' and '_' allowed"
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


def owner_of(key: str) -> str:
    """The owner/namespace segment of a `document_key` (its inverse-prefix).

    `document_key` builds `owner/project/slug`, so the owner is the first segment.
    """
    return key.split("/", 1)[0]
