"""Unit test: search hits are stamped with their project's display name.

`_with_names` is the route-layer helper that joins index hits to the project
registry. It must resolve a registered display name and fall back to the slug
when none is set — the user-facing reason cross-project search reads nicely.
"""

from pathlib import Path

from claudeplans.api.search import _with_names
from claudeplans.projects import ProjectRegistry
from claudeplans_contracts.dto import SearchHit, SearchResults
from claudeplans_contracts.enums import DocStatus, DocType


def _hit(project: str, slug: str) -> SearchHit:
    return SearchHit(
        key=f"dev/{project}/{slug}",
        project=project,
        slug=slug,
        title="T",
        type=DocType.plan,
        status=DocStatus.draft,
        kind="title",
        text="T",
    )


def test_with_names_resolves_display_name_and_falls_back(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.set("dev", "demo", "Demo Project")

    results = SearchResults(query="t", hits=[_hit("demo", "p1"), _hit("other", "q1")])
    stamped = _with_names(results, registry, "dev")

    by_project = {h.project: h.project_name for h in stamped.hits}
    assert by_project["demo"] == "Demo Project"  # registry display name
    assert by_project["other"] == "other"  # fallback to the slug
