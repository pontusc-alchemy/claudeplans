"""Wire-DTO field semantics for the Phase 1 prose/placement additions.

The model invariants live in test_models.py; this file pins the DTO contract the
CLI and API agree on: the optional set-fields default to None ("leave unchanged"),
AddSectionRequest carries a concrete `lead` default, extra="forbid" still rejects
unknown keys, and the placement enum rejects out-of-vocabulary values.
"""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from claudeplans_contracts import (
    AddSectionRequest,
    LineageResponse,
    SectionPlacement,
    SetPhaseRequest,
    SetSectionRequest,
)


def test_set_phase_prose_fields_default_none() -> None:
    # None = leave unchanged; this is the whole point of the absolute-set DTO.
    req = SetPhaseRequest()
    assert req.name is None
    assert req.intro is None
    assert req.exit_criteria is None
    assert req.notes is None


def test_set_phase_prose_accepts_empty_and_value() -> None:
    # "" is a real value (clear the field); a plain string sets it.
    req = SetPhaseRequest(intro="hello", exit_criteria="", notes="line\n\nline")
    assert req.intro == "hello"
    assert req.exit_criteria == ""
    assert req.notes == "line\n\nline"


def test_add_section_placement_defaults_lead() -> None:
    # The create DTO carries a concrete default (unlike the None set-DTOs below).
    req = AddSectionRequest(anchor="a", heading="H")
    assert req.placement is SectionPlacement.lead


def test_add_section_placement_accepts_trail() -> None:
    req = AddSectionRequest(anchor="a", heading="H", placement=SectionPlacement.trail)
    assert req.placement is SectionPlacement.trail


def test_set_section_placement_defaults_none() -> None:
    # Asymmetry with AddSectionRequest is intentional: None = leave unchanged.
    assert SetSectionRequest().placement is None


def test_set_section_placement_accepts_value() -> None:
    req = SetSectionRequest(placement=SectionPlacement.trail)
    assert req.placement is SectionPlacement.trail


def test_add_section_placement_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        AddSectionRequest.model_validate(
            {"anchor": "a", "heading": "H", "placement": "sideways"}
        )


def test_set_section_placement_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        SetSectionRequest.model_validate({"placement": "sideways"})


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (SetPhaseRequest, {"bogus": "x"}),
        (AddSectionRequest, {"anchor": "a", "heading": "H", "bogus": "x"}),
        (SetSectionRequest, {"bogus": "x"}),
    ],
)
def test_dtos_forbid_unknown_fields(
    model: type[BaseModel], payload: dict[str, Any]
) -> None:
    # extra="forbid" must still reject unknown keys after the field additions.
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def _node(slug: str, children: list[dict[str, object]] | None = None) -> dict:
    return {
        "slug": slug,
        "title": slug.upper(),
        "owner_id": "u",
        "project": "p",
        "status": "draft",
        "type": "plan",
        "children": children or [],
        "backlinks": [],
    }


def test_lineage_response_round_trips_a_deep_tree() -> None:
    """The self-referential field needs the forward ref resolved to nest at all."""
    payload = {"roots": [_node("a", [_node("b", [_node("c")])])]}
    parsed = LineageResponse.model_validate(payload)
    assert parsed.roots[0].children[0].children[0].slug == "c"
    assert parsed.model_dump(mode="json")["roots"] == payload["roots"]


def test_lineage_response_rejects_an_unknown_field() -> None:
    """extra="forbid" is what turns server-side shape drift into a loud failure."""
    with pytest.raises(ValidationError):
        LineageResponse.model_validate({"roots": [_node("a") | {"plans": []}]})


def test_lineage_response_defaults_to_an_empty_forest() -> None:
    empty = LineageResponse.model_validate({})
    assert empty.roots == []
    assert empty.over_cap == []
    assert empty.cycle_roots == []
