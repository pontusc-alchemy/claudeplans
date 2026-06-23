"""Unit coverage of the error -> exit-code mapping and `_reply` status mapping."""

import httpx
import pytest

from claudeplans_cli.client import PlanClient
from claudeplans_cli.errors import exit_code_for
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
