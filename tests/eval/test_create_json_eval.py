"""Offline regression for the LLM-emits-valid-create-JSON eval (gap #318).

The fixtures under ``fixtures/llm_create/`` are REAL payloads emitted by independent
LLM agents during the agent-client phase: each was given only the ``DocumentCreate``
JSON schema plus the two semantic constraints the schema cannot encode (research
docs carry no phases; ``primary_research_ref`` must be one of ``research_refs``) and
asked to author a document. The live run scored 6/6 valid; these tests pin that so a
later schema change that breaks LLM authorability fails CI loudly instead of silently.

Each fixture is validated against the SAME acceptance path the server runs
(``api.documents.create`` -> ``core.create_document``): parse the wire body as
``DocumentCreate``, then compose the full ``Document`` (adding the path-derived
``owner_id``/``project``) so the model invariants run exactly as a real create would.
"""

import json
from pathlib import Path

import pytest

from claudeplans_contracts import Document, DocumentCreate

_FIXTURES = sorted((Path(__file__).parent / "fixtures" / "llm_create").glob("*.json"))


def _accept(payload: dict) -> Document:
    """Mirror the server's create path: DocumentCreate body -> composed Document."""
    dc = DocumentCreate.model_validate(payload)
    return Document(
        type=dc.type,
        status=dc.status,
        project="demo",
        slug=dc.slug,
        title=dc.title,
        owner_id="dev",
        date=dc.date,
        description=dc.description,
        frontmatter=dc.frontmatter,
        research_refs=dc.research_refs,
        primary_research_ref=dc.primary_research_ref,
        sections=dc.sections,
        phases=dc.phases,
    )


def test_fixtures_present() -> None:
    # Guard against an empty glob silently passing the parametrized test below.
    assert len(_FIXTURES) == 6


@pytest.mark.parametrize("path", _FIXTURES, ids=lambda p: p.stem)
def test_llm_create_payload_is_accepted(path: Path) -> None:
    payload = json.loads(path.read_text())
    doc = _accept(payload)
    # Round-trips back through validation cleanly (no poison document).
    Document.model_validate(doc.model_dump(mode="json"))
