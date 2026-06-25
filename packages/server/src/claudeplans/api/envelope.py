"""The single success-response shape: {data, warnings[]}.

Every 2xx body the API returns is a ResponseEnvelope. Structural errors do NOT use
this shape — they reject at the boundary and get the 4xx `detail` shape from the
exception handlers. Attaching drift warnings happens in exactly one place
(`envelope`), so a route can never forget to run the linter.
"""

from pydantic import BaseModel

from claudeplans_contracts import Document, DriftWarning

from ..drift import lint


class ResponseEnvelope(BaseModel):
    """The one success-response shape wrapping a document and its drift warnings."""

    data: Document
    warnings: list[DriftWarning]


def envelope(doc: Document, *, scope: str | None = None) -> ResponseEnvelope:
    """Wrap `doc` with its drift warnings — the single place the linter is run.

    scope: when set, only warnings whose `path` is None, equals `scope`, or starts
    with `scope + "."` are included. Pass None (default) to include all warnings.
    """
    warnings = lint(doc)
    if scope is not None:
        warnings = [
            w
            for w in warnings
            if w.path is None or w.path == scope or w.path.startswith(scope + ".")
        ]
    return ResponseEnvelope(data=doc, warnings=warnings)
