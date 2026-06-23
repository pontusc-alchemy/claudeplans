"""Deterministic identity minting for REAL users — the dev user is fixed, separate.

This is the minting mechanism the (deferred) IAP provider consumes via the
registry: a verified human identity maps to a stable uid derived from the person's
name, so the same name always yields the same uid regardless of case/whitespace.
Pure and dependency-free (stdlib only) so it is trivially testable in isolation.
"""

import re
import uuid
from typing import Final

# A derived, stable namespace for plan-system uids — no magic literal. Anchoring
# the uuid5 in a named DNS namespace keeps the constant reproducible and documented.
PLAN_SYSTEM_NS: Final = uuid.uuid5(uuid.NAMESPACE_DNS, "claudeplans.plan-system")

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def mint_uid(name: str) -> str:
    """A deterministic, case-insensitive identity (uid) from a human name."""
    return str(uuid.uuid5(PLAN_SYSTEM_NS, name.strip().casefold()))


def slugify(name: str) -> str:
    """Lowercase slug of `name`: non-[a-z0-9] runs -> '-', edges stripped.

    Raises ValueError if nothing slug-safe remains.
    """
    slug = _NON_SLUG.sub("-", name.casefold()).strip("-")
    if not slug:
        raise ValueError(f"name {name!r} has no slug-safe characters")
    return slug
