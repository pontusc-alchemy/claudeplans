"""Per-user project display-name registry (`projects.json`).

Keys are `"<owner_id>/<project>"` → display name (free-form text). The slug
remains the routable identity; display names are resolved at render time with
a fallback to the slug when unset. Atomic write mirrors UserRegistry._save.
"""

import json
import os
from pathlib import Path


class ProjectRegistry:
    """Loads/stores project display names keyed by `owner_id/project`."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._names: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return dict(json.loads(self._path.read_text()))

    def get(self, owner_id: str, project: str) -> str | None:
        """The display name for `owner_id/project`, or None if unset."""
        return self._names.get(f"{owner_id}/{project}")

    def set(self, owner_id: str, project: str, name: str) -> None:
        """Set the display name for `owner_id/project` and persist."""
        self._names[f"{owner_id}/{project}"] = name
        self._save()

    def names_for(self, owner_id: str) -> dict[str, str]:
        """Return `{project: display_name}` for every project owned by `owner_id`."""
        result: dict[str, str] = {}
        for key, name in self._names.items():
            owner, sep, project = key.partition("/")
            if sep and owner == owner_id:
                result[project] = name
        return result

    def _save(self) -> None:
        """Atomically rewrite the JSON file (temp file + os.replace)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f"{self._path.name}.tmp")
        tmp.write_text(json.dumps(self._names))
        os.replace(tmp, self._path)
