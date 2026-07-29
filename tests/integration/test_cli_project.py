"""CLI end-to-end tests for the `project` command group."""

import json

import pytest
from _cli import VALID_CREATE, runner

from claudeplans_cli import cli
from claudeplans_contracts import ExitCode


@pytest.mark.usefixtures("patched_cli")
def test_project_lineage_json_shape() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["project", "lineage", "demo"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "data" in parsed
    assert "warnings" in parsed
    lineage = parsed["data"]
    assert set(lineage) == {"roots", "over_cap"}
    # A doc with no parent is a root of the tree.
    assert [r["slug"] for r in lineage["roots"]] == ["p1"]


def _create(project: str, **fields: object) -> None:
    runner.invoke(
        cli.app,
        ["doc", "create", project, "--from-json", "-"],
        input=json.dumps(fields),
    )


@pytest.mark.usefixtures("patched_cli")
def test_project_lineage_nests_a_child_under_its_parent() -> None:
    _create("demo", type="research", slug="r1", title="R One")
    _create(
        "demo",
        type="plan",
        slug="pl1",
        title="Plan",
        primary_parent_ref="r1",
        research_refs=["r1"],
    )
    result = runner.invoke(cli.app, ["project", "lineage", "demo"])
    assert result.exit_code == 0
    roots = json.loads(result.stdout)["data"]["roots"]
    assert [r["slug"] for r in roots] == ["r1"]
    assert [c["slug"] for c in roots[0]["children"]] == ["pl1"]


@pytest.mark.usefixtures("patched_cli")
def test_project_lineage_nests_to_depth_three() -> None:
    """The shape a two-level fold could not express at all."""
    _create("demo", type="research", slug="a", title="A")
    _create(
        "demo",
        type="plan",
        slug="b",
        title="B",
        primary_parent_ref="a",
        research_refs=["a"],
    )
    _create(
        "demo",
        type="plan",
        slug="c",
        title="C",
        primary_parent_ref="b",
        research_refs=["b"],
    )
    result = runner.invoke(cli.app, ["project", "lineage", "demo"])
    assert result.exit_code == 0
    roots = json.loads(result.stdout)["data"]["roots"]
    assert roots[0]["slug"] == "a"
    assert roots[0]["children"][0]["slug"] == "b"
    assert roots[0]["children"][0]["children"][0]["slug"] == "c"


@pytest.mark.usefixtures("patched_cli")
def test_project_lineage_nests_a_research_doc_under_a_plan() -> None:
    """`type` is orthogonal to tree position — any doc may parent any doc."""
    _create("demo", type="plan", slug="parent-plan", title="Parent")
    _create(
        "demo",
        type="research",
        slug="child-research",
        title="Child",
        primary_parent_ref="parent-plan",
        research_refs=["parent-plan"],
    )
    result = runner.invoke(cli.app, ["project", "lineage", "demo"])
    assert result.exit_code == 0
    roots = json.loads(result.stdout)["data"]["roots"]
    assert [r["slug"] for r in roots] == ["parent-plan"]
    assert [c["slug"] for c in roots[0]["children"]] == ["child-research"]


@pytest.mark.usefixtures("patched_cli")
def test_project_view_emits_json_with_url_key() -> None:
    result = runner.invoke(cli.app, ["project", "view", "demo"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "url" in parsed
    assert "demo" in parsed["url"]


@pytest.mark.usefixtures("patched_cli")
def test_project_set_name_round_trips() -> None:
    # set-name exits 0 and returns {project, name}.
    result = runner.invoke(
        cli.app, ["project", "set-name", "demo", "My Project (2026)"]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["project"] == "demo"
    assert parsed["name"] == "My Project (2026)"


@pytest.mark.usefixtures("patched_cli")
def test_project_list_reports_name_after_set() -> None:
    # Create a doc so the project exists, then name it and verify list carries name.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["project", "set-name", "demo", "Demo Project"])
    result = runner.invoke(cli.app, ["project", "list"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    items = parsed["data"]["items"]
    demo = next((i for i in items if i["project"] == "demo"), None)
    assert demo is not None
    assert demo["name"] == "Demo Project"


@pytest.mark.usefixtures("patched_cli")
def test_project_list_name_is_none_when_unset() -> None:
    # A project with no display name set should return name=null in the listing.
    # Use a unique project slug that has never been named in this fixture scope.
    unnamed_body = json.dumps({"type": "plan", "slug": "u1", "title": "Unnamed"})
    runner.invoke(
        cli.app,
        ["doc", "create", "unnamed-proj", "--from-json", "-"],
        input=unnamed_body,
    )
    result = runner.invoke(cli.app, ["project", "list"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    items = parsed["data"]["items"]
    proj = next((i for i in items if i["project"] == "unnamed-proj"), None)
    assert proj is not None
    assert proj["name"] is None


@pytest.mark.usefixtures("patched_cli")
def test_project_set_name_empty_exits_validation() -> None:
    result = runner.invoke(cli.app, ["project", "set-name", "demo", "   "])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"


@pytest.mark.usefixtures("patched_cli")
def test_project_set_name_foreign_uid_exits_forbidden() -> None:
    result = runner.invoke(
        cli.app, ["--uid", "evil", "project", "set-name", "demo", "Name"]
    )
    assert result.exit_code == ExitCode.FORBIDDEN
