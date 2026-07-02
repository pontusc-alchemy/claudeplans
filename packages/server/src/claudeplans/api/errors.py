"""Centralized exception handlers: domain errors -> HTTP status codes in ONE place.

FastAPI auto-422s only REQUEST-BODY parsing (RequestValidationError), with the
`detail[{type,loc,msg,input}]` shape. A pydantic ValidationError raised INSIDE
route/core logic (merge-patch re-validation, the invariant re-validation on write)
is a different exception type that FastAPI does not catch, so it is mapped here
explicitly to a 422 carrying that same field-keyed error shape. The DOMAIN
ValidationError (a bad sub-resource reference) is handled separately as a plain
`detail` string. None of these use the {data, warnings[]} envelope — a structural
error gets the 4xx/5xx `detail` shape instead.

Starlette dispatches each handler by the registered exception class, but types the
handler callable as taking the base `Exception`; so each `exc` is annotated
`Exception` (not the narrow subclass) to match that contract — the registration in
`register_exception_handlers` is what guarantees the runtime type.
"""

import json

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from claudeplans_contracts import (
    CorruptDocument,
    Forbidden,
    InvalidRev,
    NotFound,
    StaleRevision,
)
from claudeplans_contracts import (
    ValidationError as DomainValidationError,
)


async def _handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc) or "not found"}, status_code=404)


async def _handle_stale_revision(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StaleRevision)
    current_rev = exc.current_rev
    body: dict[str, object] = {"detail": str(exc) or "revision conflict"}
    headers: dict[str, str] = {}
    if current_rev:
        body["current_rev"] = current_rev
        headers["ETag"] = current_rev
    return JSONResponse(body, status_code=409, headers=headers)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=422)


async def _handle_invalid_rev(request: Request, exc: Exception) -> JSONResponse:
    # A malformed If-Match token: a client input error, distinct from the 409
    # StaleRevision path, so it never carries a current_rev/ETag. 400 is also
    # Starlette's generic bad-request bucket (e.g. limits.py's body-size rewrap),
    # so the "error" field discriminates this path for the CLI's status mapping.
    return JSONResponse({"detail": str(exc), "error": "invalid_rev"}, status_code=400)


async def _handle_pydantic_validation_error(
    request: Request, exc: Exception
) -> JSONResponse:
    # A pydantic ValidationError from inside core (write-time re-validation, merge
    # patch): surface its field-keyed errors so the body matches FastAPI's own
    # request-body 422 shape. Use exc.json() (not exc.errors()) because an invariant
    # raised in a model_validator carries the raw ValueError in ctx, which the default
    # JSONResponse encoder can't serialize; exc.json() renders that context safely.
    assert isinstance(exc, PydanticValidationError)
    return JSONResponse({"detail": json.loads(exc.json())}, status_code=422)


async def _handle_forbidden(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc) or "forbidden"}, status_code=403)


async def _handle_corrupt_document(request: Request, exc: Exception) -> JSONResponse:
    # A server-side integrity fault: return a clean message, never echo the internal
    # detail/stacktrace to the client.
    return JSONResponse({"detail": "stored document is corrupt"}, status_code=500)


async def _handle_request_validation(request: Request, exc: Exception) -> JSONResponse:
    # Mirror FastAPI's default request-body 422 (detail[{type,loc,msg,input}]); but
    # serializing a pathologically deep error tree can itself exhaust the recursion
    # limit, so fall back to a flat (still list-shaped) entry — a hostile
    # deeply-nested body is then a clean 422, never an uncaught 500.
    assert isinstance(exc, RequestValidationError)
    try:
        detail: object = jsonable_encoder(exc.errors())
    except RecursionError:
        detail = [
            {
                "type": "too_deeply_nested",
                "loc": ["body"],
                "msg": "request body is too deeply nested",
            }
        ]
    return JSONResponse({"detail": detail}, status_code=422)


def register_exception_handlers(app: FastAPI) -> None:
    """Register the domain-error -> HTTP-status handlers on `app`."""
    app.add_exception_handler(NotFound, _handle_not_found)
    app.add_exception_handler(StaleRevision, _handle_stale_revision)
    app.add_exception_handler(InvalidRev, _handle_invalid_rev)
    app.add_exception_handler(Forbidden, _handle_forbidden)
    app.add_exception_handler(DomainValidationError, _handle_validation_error)
    app.add_exception_handler(
        PydanticValidationError, _handle_pydantic_validation_error
    )
    app.add_exception_handler(CorruptDocument, _handle_corrupt_document)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
