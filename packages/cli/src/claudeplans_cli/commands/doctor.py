"""`claudeplans doctor` — flat command reporting the resolved service target,
whether it is reachable, and (when reachable) the server's identity.

A diagnostic, not a mutation: it ALWAYS exits 0 and never emits a traceback. Any
failure to complete the /status probe — transport error, non-2xx, a malformed
--url whose host fails IDNA resolution at request-build time, or a non-JSON body
— is reported as `reachable: false` with the structured detail. The except clause
is deliberately broad: `httpx.HTTPError` covers transport + status errors,
`httpx.InvalidURL` is a sibling (not an HTTPError), and `ValueError` covers both
the IDNA/UnicodeError raised while building the request and a JSON decode failure.
It does NOT wear `handle_errors` (which would map a transport failure to a
non-zero exit), and `health()` deliberately surfaces raw httpx/parse errors.
"""

import httpx
import typer

from ..context import AppContext
from ..output import emit_obj

_IDENTITY_FIELDS = ("version", "storage_backend", "auth_mode")


def doctor(ctx: typer.Context) -> None:
    """Report the resolved url/uid, whether the server is reachable, and — when
    reachable — its version / storage backend / auth mode (a /status probe)."""
    c: AppContext = ctx.obj
    out: dict[str, object] = {"url": c.base_url, "uid": c.uid}
    try:
        status = c.client.health()
        out["reachable"] = True
        # Surface server identity so a caller can spot a mis-targeted (but live)
        # server, not merely that something answered on the URL.
        for key in _IDENTITY_FIELDS:
            if key in status:
                out[key] = status[key]
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        out["reachable"] = False
        out["detail"] = str(exc)
    emit_obj(out)
