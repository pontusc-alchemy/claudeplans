"""Upgrade-on-read schema migration.

Persisted JSON plus evolving extra="forbid" models breaks on the second schema
change without a migration path: a stored dict written under an old shape would
fail validation against the new model. This is the version-keyed registry that
upgrades a stored dict to the current shape before it is validated.
"""

from collections.abc import Callable

from .models import Document

CURRENT_SCHEMA_VERSION = 1


def _v0_to_v1(raw: dict) -> dict:
    """v0 had no schema_version, stored the owner under `owner` and had no
    research-ref fields. Establishes the migration pattern; real future
    migrations follow this signature (take a vN dict, return a vN+1 dict)."""
    data = dict(raw)
    if "owner" in data:
        data["owner_id"] = data.pop("owner")
    data.setdefault("research_refs", [])
    return data


MIGRATIONS: dict[int, Callable[[dict], dict]] = {0: _v0_to_v1}


def migrate(raw: dict) -> dict:
    """Upgrade a stored dict to the current schema. Does not mutate the input."""
    data = dict(raw)
    version = data.get("schema_version", 0)
    while version < CURRENT_SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ValueError(f"no migration path from schema_version {version}")
        data = step(data)
        version += 1
        data["schema_version"] = version
    return data


def migrate_document(raw: dict) -> Document:
    return Document.model_validate(migrate(raw))


# Keep the literal default in models.py honest against the registry's notion of current.
assert Document.model_fields["schema_version"].default == CURRENT_SCHEMA_VERSION
