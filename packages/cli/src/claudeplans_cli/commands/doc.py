"""`claudeplans doc <verb>` — document-level commands.

Reads project the fetched document client-side (fields/section/phase) so an agent
narrows a view without a second request. link/unlink read-modify-write the
research-ref set because the service exposes only an absolute set of the whole list.

Typer's option/argument descriptors are bound to module-level singletons (not inline
defaults) because ruff B008 forbids function calls in argument defaults; the
descriptor is shared and immutable, so a singleton is the sanctioned form.
"""

import sys
from typing import Annotated

import typer

from claudeplans_contracts import (
    DocStatus,
    DocType,
    DocumentCreate,
    ValidationError,
    unlink_research_ref,
)

from ..context import AppContext
from ..errors import handle_errors
from ..output import emit, emit_phases

app = typer.Typer(no_args_is_help=True)

_TYPE = typer.Option("--type")
_FROM_JSON = typer.Option("--from-json", help="'-' for stdin, or a literal JSON string")
_SLUG = typer.Option()
_TITLE = typer.Option()
_FIELDS = typer.Option(help="comma-separated")
_SECTION = typer.Option()
_PHASE = typer.Option()
_REV = typer.Option("--rev")
_STATUS_VALUE = typer.Argument()
_REF = typer.Argument()
_PRIMARY = typer.Option("--primary")


@app.command()
@handle_errors
def create(
    ctx: typer.Context,
    project: str,
    type_: Annotated[DocType | None, _TYPE] = None,
    from_json: Annotated[str | None, _FROM_JSON] = None,
    slug: Annotated[str | None, _SLUG] = None,
    title: Annotated[str | None, _TITLE] = None,
) -> None:
    """Create a document from a full JSON body or from --type/--slug/--title."""
    c: AppContext = ctx.obj
    if from_json is not None:
        raw = sys.stdin.read() if from_json == "-" else from_json
        payload = DocumentCreate.model_validate_json(raw)
    else:
        # Validate from a dict so missing flags surface as pydantic ValidationError
        # (-> exit 4) rather than a static type error on the constructor.
        payload = DocumentCreate.model_validate(
            {"type": type_, "slug": slug, "title": title}
        )
    reply = c.client.create_document(c.uid, project, payload.model_dump(mode="json"))
    emit(reply)


@app.command()
@handle_errors
def get(
    ctx: typer.Context,
    project: str,
    slug: str,
    fields: Annotated[str | None, _FIELDS] = None,
    section: Annotated[str | None, _SECTION] = None,
    phase: Annotated[str | None, _PHASE] = None,
) -> None:
    """Fetch a document, optionally projecting fields / a section / a phase."""
    c: AppContext = ctx.obj
    if sum(x is not None for x in (fields, section, phase)) > 1:
        raise ValidationError("choose at most one of --fields/--section/--phase")
    reply = c.client.get_document(c.uid, project, slug)
    field_list = [f.strip() for f in fields.split(",")] if fields is not None else None
    emit(reply, fields=field_list, section=section, phase=phase)


@app.command()
@handle_errors
def delete(
    ctx: typer.Context,
    project: str,
    slug: str,
    rev: Annotated[str, _REV],
) -> None:
    """Delete a document (conditional on --rev)."""
    c: AppContext = ctx.obj
    c.client.delete_document(c.uid, project, slug, rev=rev)
    print('{"deleted":true}')


@app.command()
@handle_errors
def status(
    ctx: typer.Context,
    project: str,
    slug: str,
    value: Annotated[DocStatus, _STATUS_VALUE],
) -> None:
    """Set a document's status."""
    c: AppContext = ctx.obj
    reply = c.client.set_document_status(c.uid, project, slug, value.value)
    emit(reply)


@app.command()
@handle_errors
def phases(ctx: typer.Context, project: str, slug: str) -> None:
    """List a document's phases."""
    c: AppContext = ctx.obj
    reply = c.client.get_document(c.uid, project, slug)
    emit_phases(reply)


@app.command()
@handle_errors
def link(
    ctx: typer.Context,
    project: str,
    slug: str,
    ref: Annotated[str, _REF],
    primary: Annotated[bool, _PRIMARY] = False,
) -> None:
    """Add a research ref (dedup, order-preserving); optionally make it primary."""
    c: AppContext = ctx.obj
    # GET-then-PUT is intentionally unguarded: single-writer local service, and the
    # PUT is an absolute set of the whole ref list (last-writer-wins).
    current = c.client.get_document(c.uid, project, slug)
    data = current.data or {}
    existing: list[str] = list(data.get("research_refs", []))
    existing_primary: str | None = data.get("primary_research_ref")
    new_refs = existing if ref in existing else [*existing, ref]
    new_primary = ref if primary else existing_primary
    reply = c.client.put_research_refs(c.uid, project, slug, new_refs, new_primary)
    emit(reply)


@app.command()
@handle_errors
def unlink(
    ctx: typer.Context,
    project: str,
    slug: str,
    ref: Annotated[str, _REF],
) -> None:
    """Remove a research ref; if it was primary, promote the next remaining ref."""
    c: AppContext = ctx.obj
    # GET-then-PUT is intentionally unguarded: single-writer local service, and the
    # PUT is an absolute set of the whole ref list (last-writer-wins).
    current = c.client.get_document(c.uid, project, slug)
    data = current.data or {}
    existing: list[str] = list(data.get("research_refs", []))
    existing_primary: str | None = data.get("primary_research_ref")
    new_refs, new_primary = unlink_research_ref(existing, existing_primary, ref)
    reply = c.client.put_research_refs(c.uid, project, slug, new_refs, new_primary)
    emit(reply)
