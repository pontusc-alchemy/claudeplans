"""Jinja rendering of the live-view pages — the one place HTML is assembled.

The security contract lives here: section/description bodies are run through
`render.render_markdown` (markdown -> nh3-sanitized HTML) in PYTHON, then handed to
the template as pre-rendered strings marked `| safe`. Everything else (titles,
slugs, statuses) flows through Jinja's autoescape. So the ONLY HTML marked safe is
nh3 output; the templates stay logic-free (no Python called from Jinja).

A single module-level `Environment` is built once (templates are immutable on disk);
`autoescape=True` is the default-deny that makes the `| safe` markers the explicit,
auditable exceptions.
"""

from collections.abc import Callable
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from claudeplans_contracts import Document

from . import render
from .lineage import Lineage

_TEMPLATE_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(default=True, default_for_string=True),
)


def _section_context(doc: Document) -> list[dict[str, object]]:
    return [
        {
            "anchor": s.anchor,
            "heading": s.heading,
            "level": s.level,
            "body_html": render.render_markdown(s.body),
        }
        for s in doc.sections
    ]


def _phase_context(doc: Document) -> list[dict[str, object]]:
    return [
        {
            "slug": p.slug,
            "name": p.name,
            "status": p.status.value,
            "tasks": [{"text": t.text, "checked": t.checked} for t in p.tasks],
        }
        for p in doc.phases
    ]


def _doc_context(doc: Document) -> dict[str, object]:
    description_html = (
        render.render_markdown(doc.description) if doc.description else ""
    )
    return {
        "doc": doc,
        "description_html": description_html,
        "sections": _section_context(doc),
        "phases": _phase_context(doc),
    }


def render_doc_body(doc: Document) -> str:
    """Render the inner morph payload (the SSE frame body) for `doc`."""
    return env.get_template("_doc_body.html").render(**_doc_context(doc))


def render_page(doc: Document, events_url: str) -> str:
    """Render the full document page (the morph target wrapping the body)."""
    return env.get_template("document.html").render(
        title=doc.title, events_url=events_url, **_doc_context(doc)
    )


def render_lineage_page(
    lineage: Lineage, title: str, view_url: Callable[[str], str]
) -> str:
    """Render the project lineage index. `view_url(slug)` builds each doc link."""
    research = [
        {
            "title": node.title,
            "view_url": view_url(node.slug),
            "plans": [
                {"title": p.title, "view_url": view_url(p.slug)} for p in node.plans
            ],
            "backlinks": [
                {"title": p.title, "view_url": view_url(p.slug)} for p in node.backlinks
            ],
        }
        for node in lineage.research
    ]
    unlinked = [
        {"title": p.title, "view_url": view_url(p.slug)} for p in lineage.unlinked_plans
    ]
    return env.get_template("lineage.html").render(
        title=title,
        lineage={"research": research, "unlinked_plans": unlinked},
    )
