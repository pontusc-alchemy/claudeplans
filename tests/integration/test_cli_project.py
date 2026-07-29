"""CLI end-to-end tests for the `project` command group."""

import json

import pytest
from _cli import VALID_CREATE, runner

from claudeplans_cli import cli
from claudeplans_contracts import ExitCode


@pytest.mark.usefixtures("patched_cli")
def test_project_lineage_json_shape() -> None:
    # Create a plan doc; lineage should have research+unlinked_plans keys.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["project", "lineage", "demo"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "data" in parsed
    assert "warnings" in parsed
    lineage = parsed["data"]
    assert "research" in lineage
    assert "unlinked_plans" in lineage
    # The plan (no primary_parent_ref) lands in unlinked_plans.
    slugs = [p["slug"] for p in lineage["unlinked_plans"]]
    assert "p1" in slugs


@pytest.mark.usefixtures("patched_cli")
def test_project_lineage_linked_plan_appears_under_research_node() -> None:
    # Create a research doc and a plan that cites it as primary; the plan must
    # appear under the research node's `plans` list and NOT in `unlinked_plans`.
    research_body = json.dumps({"type": "research", "slug": "r1", "title": "R One"})
    plan_body = json.dumps(
        {
            "type": "plan",
            "slug": "pl1",
            "title": "Plan",
            "primary_parent_ref": "r1",
            "research_refs": ["r1"],
        }
    )
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=research_body
    )
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=plan_body
    )
    result = runner.invoke(cli.app, ["project", "lineage", "demo"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    lineage = parsed["data"]
    # Research node for r1 must exist and contain pl1 in plans.
    research_nodes = {n["slug"]: n for n in lineage["research"]}
    assert "r1" in research_nodes
    plan_slugs_under_r1 = [p["slug"] for p in research_nodes["r1"]["plans"]]
    assert "pl1" in plan_slugs_under_r1
    # pl1 must NOT appear in unlinked_plans.
    unlinked_slugs = [p["slug"] for p in lineage["unlinked_plans"]]
    assert "pl1" not in unlinked_slugs


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
