"""Unit coverage of the error -> exit-code mapping and `_reply` status mapping."""

import json

import httpx
import pytest
import typer
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from claudeplans_cli.client import PlanClient
from claudeplans_cli.errors import exit_code_for, handle_errors, kind_for
from claudeplans_contracts import (
    CorruptDocument,
    ExitCode,
    Forbidden,
    NotFound,
    PlanError,
    StaleRevision,
    ValidationError,
)

_CASES = [
    (NotFound(), ExitCode.NOT_FOUND),
    (Forbidden(), ExitCode.FORBIDDEN),
    (ValidationError(), ExitCode.VALIDATION),
    (StaleRevision(), ExitCode.STALE_REV),
    (CorruptDocument(), ExitCode.ERROR),
    (PlanError(), ExitCode.ERROR),
]


@pytest.mark.parametrize(("exc", "expected"), _CASES)
def test_exit_code_for(exc: PlanError, expected: ExitCode) -> None:
    assert exit_code_for(exc) == int(expected)


# The exit-code matrix: every domain failure class is distinguishable by exit code
# AND a parseable stderr `{"error":"<kind>",…}`. (USAGE/2 is Typer/Click's own and
# is exercised end-to-end, not here.)
_BOUNDARY_CASES = [
    (NotFound("missing"), ExitCode.NOT_FOUND, "not_found"),
    (Forbidden("nope"), ExitCode.FORBIDDEN, "forbidden"),
    (ValidationError("bad"), ExitCode.VALIDATION, "validation"),
    (CorruptDocument("corrupt"), ExitCode.ERROR, "error"),
    (PlanError("boom"), ExitCode.ERROR, "error"),
]


# Pin the exact kind string for every error class (a typo like `not_found` ->
# `notfound` must fail this, not slip through).
_KIND_CASES = [
    (NotFound(), "not_found"),
    (Forbidden(), "forbidden"),
    (ValidationError(), "validation"),
    (StaleRevision(), "stale_rev"),
    (CorruptDocument(), "error"),
    (PlanError(), "error"),
]


@pytest.mark.parametrize(("exc", "expected_kind"), _KIND_CASES)
def test_kind_for_matches_exit_mapping(exc: PlanError, expected_kind: str) -> None:
    # A mapped domain error gets its specific kind; the unmapped generic failures
    # (CorruptDocument, the PlanError base) report the generic "error".
    assert kind_for(exc) == expected_kind


@pytest.mark.parametrize(("exc", "code", "kind"), _BOUNDARY_CASES)
def test_handle_errors_emits_structured_stderr(
    exc: PlanError,
    code: ExitCode,
    kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    @handle_errors
    def boom() -> None:
        raise exc

    with pytest.raises(typer.Exit) as excinfo:
        boom()
    assert excinfo.value.exit_code == int(code)
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == kind
    assert err["detail"]


def test_handle_errors_stale_rev_carries_current_rev(
    capsys: pytest.CaptureFixture[str],
) -> None:
    @handle_errors
    def boom() -> None:
        raise StaleRevision("lost race", current_rev="7")

    with pytest.raises(typer.Exit) as excinfo:
        boom()
    assert excinfo.value.exit_code == int(ExitCode.STALE_REV)
    err = json.loads(capsys.readouterr().err)
    assert err == {"error": "stale_rev", "current_rev": "7", "detail": "lost race"}


def test_handle_errors_stale_rev_marks_a_create_collision(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The one 409 with no rev to retry against: the payload must say so and name the
    # key, or the agent is pointed at a retry that can never succeed.
    @handle_errors
    def boom() -> None:
        raise StaleRevision("dev/demo/p1", conflict="exists")

    with pytest.raises(typer.Exit) as excinfo:
        boom()
    assert excinfo.value.exit_code == int(ExitCode.STALE_REV)
    err = json.loads(capsys.readouterr().err)
    assert err == {
        "error": "stale_rev",
        "conflict": "exists",
        "current_rev": "",
        "detail": "dev/demo/p1",
    }


# Every request-side httpx failure must map to a structured transport error, not
# just the connect case: ConnectError/timeouts are TransportError, but DecodingError
# and TooManyRedirects are RequestError siblings that are NOT TransportError and
# would otherwise escape as a raw traceback.
_TRANSPORT_CASES = [
    httpx.ConnectError("connection refused"),
    httpx.ConnectTimeout("timed out"),
    httpx.DecodingError("bad body"),
    httpx.TooManyRedirects("loop"),
]


@pytest.mark.parametrize("exc", _TRANSPORT_CASES)
def test_handle_errors_transport_no_traceback(
    exc: httpx.RequestError, capsys: pytest.CaptureFixture[str]
) -> None:
    @handle_errors
    def boom() -> None:
        raise exc

    with pytest.raises(typer.Exit) as excinfo:
        boom()
    assert excinfo.value.exit_code == int(ExitCode.TRANSPORT)
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "transport"
    assert err["detail"]


def test_handle_errors_stderr_is_single_line_for_multiline_detail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A pydantic ValidationError's message spans multiple lines; the whole agent
    # contract rests on one parseable JSON object per error, so the embedded newlines
    # must be escaped, not emitted raw.
    class _M(BaseModel):
        n: int

    with pytest.raises(PydanticValidationError) as ve:
        _M.model_validate({"n": "not-an-int"})
    multiline = ve.value

    @handle_errors
    def boom() -> None:
        raise multiline

    with pytest.raises(typer.Exit) as excinfo:
        boom()
    assert excinfo.value.exit_code == int(ExitCode.VALIDATION)
    out = capsys.readouterr().err
    assert out.strip().count("\n") == 0  # exactly one physical line
    err = json.loads(out)
    assert err["error"] == "validation"
    assert "\n" in err["detail"]  # the newline survived, escaped, inside the JSON


def _response(status_code: int, detail: object = "boom") -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"detail": detail},
        request=httpx.Request("GET", "http://t"),
    )


# Each error status maps to its domain error; 428 -> ValidationError and 500 ->
# CorruptDocument are unreachable from the CLI itself (--rev is always required, the
# server raises 500 internally) but the mapping is still part of the wire contract.
_STATUS_CASES = [
    (403, Forbidden),
    (404, NotFound),
    (409, StaleRevision),
    (422, ValidationError),
    (428, ValidationError),
    (500, CorruptDocument),
]


@pytest.mark.parametrize(("status_code", "error_cls"), _STATUS_CASES)
def test_reply_maps_status_to_domain_error(
    status_code: int, error_cls: type[PlanError]
) -> None:
    client = PlanClient(http_client=httpx.Client(base_url="http://t"))
    with pytest.raises(error_cls):
        client._reply(_response(status_code))


def test_reply_unmapped_status_raises_base_plan_error() -> None:
    client = PlanClient(http_client=httpx.Client(base_url="http://t"))
    with pytest.raises(PlanError) as excinfo:
        client._reply(_response(418))
    # The base PlanError carries the status in its message.
    assert "418" in str(excinfo.value)


def test_reply_extracts_list_detail() -> None:
    client = PlanClient(http_client=httpx.Client(base_url="http://t"))
    # A pydantic-style list detail is json.dumps'd into the error message.
    with pytest.raises(ValidationError) as excinfo:
        client._reply(_response(422, detail=[{"loc": ["title"], "msg": "required"}]))
    assert "title" in str(excinfo.value)
