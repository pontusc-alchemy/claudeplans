"""Upgrade-on-read schema migration.

Persisted JSON plus evolving extra="forbid" models breaks on the second schema
change without a migration path: a stored dict written under an old shape would
fail validation against the new model. This is the version-keyed registry that
upgrades a stored dict to the current shape before it is validated.
"""

from collections.abc import Callable
from typing import Any

from .errors import ValidationError
from .models import Document

CURRENT_SCHEMA_VERSION = 1


def _v0_to_v1(raw: dict[str, Any]) -> dict[str, Any]:
    """v0 had no schema_version, stored the owner under `owner` and had no
    research-ref fields. Establishes the migration pattern; real future
    migrations follow this signature (take a vN dict, return a vN+1 dict)."""
    data = dict(raw)
    if "owner" in data:
        data["owner_id"] = data.pop("owner")
    data.setdefault("research_refs", [])
    return data


MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {0: _v0_to_v1}


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a stored dict to the current schema. Does not mutate the input."""
    data = dict(raw)
    version = data.get("schema_version", 0)
    # A corrupted/hand-edited persisted version field must surface as a domain
    # ValidationError (-> 422), not leak a raw TypeError from the comparison (-> 500).
    # type(...) is int excludes bool, which is an int subclass.
    if type(version) is not int:
        raise ValidationError(f"schema_version must be an integer, got {version!r}")
    # A document written by a newer server (downgrade/rollback) must fail loud, not
    # silently pass through to validation as if it were already current.
    if version > CURRENT_SCHEMA_VERSION:
        raise ValidationError(
            f"document schema_version {version} is newer than "
            f"supported {CURRENT_SCHEMA_VERSION}"
        )
    while version < CURRENT_SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ValueError(f"no migration path from schema_version {version}")
        data = step(data)
        version += 1
        data["schema_version"] = version
    return data


def migrate_document(raw: dict[str, Any]) -> Document:
    return Document.model_validate(migrate(raw))


# Tie the literal default in models.py to the registry's notion of current. An
# explicit guard (not a bare assert) so it survives `python -O`, which strips asserts.
if Document.model_fields["schema_version"].default != CURRENT_SCHEMA_VERSION:
    raise RuntimeError(
        "schema_version default in models.py is out of sync with CURRENT_SCHEMA_VERSION"
    )
