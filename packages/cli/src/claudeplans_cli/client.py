"""Sync library mirror over the claudeplans HTTP service.

WHY a library, not just a CLI: agents and tests drive the service through the same
typed surface the CLI uses, so behaviour can't drift between the two. Transport is
HTTP only — this module never imports server code; it speaks the wire contract
(the `{"data", "warnings"}` envelope + `ETag` rev mirror) and maps HTTP error
statuses back to the shared domain errors so callers handle one error vocabulary.
"""

import json
from typing import NamedTuple

import httpx

from claudeplans_contracts import (
    AddPhaseRequest,
    AddSectionRequest,
    AddTaskRequest,
    CorruptDocument,
    DocStatus,
    DocStatusRequest,
    EditTaskRequest,
    Forbidden,
    MovePhaseRequest,
    MoveSectionRequest,
    NotFound,
    PatchSectionRequest,
    PhaseStatus,
    PhaseStatusRequest,
    PlanError,
    ResearchRefsRequest,
    SectionPlacement,
    SetDocumentMetaRequest,
    SetPhaseRequest,
    SetSectionRequest,
    StaleRevision,
    ToggleTaskRequest,
    ValidationError,
    validate_key_segment,
)


def _seg(value: str) -> str:
    """Validate a URL path segment client-side so a bad uid/project/slug can't
    silently mis-target a route (e.g. '#'/'?' truncating the URL)."""
    try:
        return validate_key_segment(value)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


# HTTP status -> domain error. 428 (missing If-Match precondition) is a client
# misuse of the conditional-write contract, surfaced as a domain ValidationError.
# 500 is the server's CorruptDocument path; both unmapped-and-mapped errors stay
# inside the PlanError hierarchy so the CLI's error boundary catches every one.
_STATUS_TO_ERROR: dict[int, type[PlanError]] = {
    403: Forbidden,
    404: NotFound,
    409: StaleRevision,
    422: ValidationError,
    428: ValidationError,
    500: CorruptDocument,
}


class Reply(NamedTuple):
    """A decoded successful response: rev, document, and any drift warnings."""

    rev: str | None
    data: dict | None
    warnings: list[dict]


def _detail_message(resp: httpx.Response) -> str:
    """Extract a human message from an error body's `detail` (str | list | obj)."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if detail is not None:
        return json.dumps(detail)
    return resp.text


class PlanClient:
    """Sync client over the claudeplans HTTP API.

    Tests inject `http_client` (an ASGITransport-backed client) so they exercise
    the full router -> core -> storage stack in-process; production builds a plain
    `httpx.Client` against `base_url`.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        if http_client is not None:
            self._http = http_client
        else:
            self._http = httpx.Client(base_url=base_url)

    def _raise_for_status(self, resp: httpx.Response) -> None:
        """Raise the matching domain error for any non-2xx response."""
        if resp.status_code >= 400:
            detail = _detail_message(resp)
            error_cls = _STATUS_TO_ERROR.get(resp.status_code)
            if error_cls is not None:
                if resp.status_code == 409:
                    # Extract the current server rev so the caller can retry without
                    # a re-read. Prefer the ETag header; fall back to body field.
                    current_rev = resp.headers.get("ETag", "")
                    if not current_rev:
                        try:
                            body = resp.json()
                            current_rev = (
                                body.get("current_rev", "")
                                if isinstance(body, dict)
                                else ""
                            )
                        except ValueError:
                            current_rev = ""
                    raise StaleRevision(detail, current_rev=current_rev)
                raise error_cls(detail)
            # Any unmapped error status stays inside PlanError so the CLI's error
            # boundary catches it (-> generic exit code) rather than leaking an
            # httpx.HTTPStatusError traceback.
            raise PlanError(f"unexpected HTTP {resp.status_code}: {detail}")

    def _reply(self, resp: httpx.Response) -> Reply:
        """Map a response to a Reply, raising the matching domain error on failure."""
        self._raise_for_status(resp)
        rev = resp.headers.get("ETag")
        if resp.status_code == 204 or not resp.content:
            return Reply(rev=rev, data=None, warnings=[])
        body = resp.json()
        return Reply(rev=rev, data=body["data"], warnings=body.get("warnings", []))

    def _get_json(self, path: str) -> object:
        """GET a plain-JSON endpoint (not the {rev,data,warnings} envelope)."""
        resp = self._http.get(path)
        self._raise_for_status(resp)
        return resp.json()

    def health(self) -> dict[str, str]:
        """GET /status — a liveness + identity probe for `doctor`.

        Hits /status rather than /healthz so the probe also returns the server's
        version, storage backend, and auth mode — enough to tell a mis-targeted
        but live server from the intended one, not merely that *something*
        answered. Raises the raw httpx/parse error (it does NOT route through
        `_raise_for_status` into the PlanError hierarchy) so `doctor` can report
        it as `reachable: false`."""
        resp = self._http.get("/status")
        resp.raise_for_status()
        return resp.json()

    def list_projects(self, uid: str) -> object:
        """GET /v1/users/{uid}/projects → ProjectList plain JSON."""
        return self._get_json(f"/v1/users/{_seg(uid)}/projects")

    def list_docs(self, uid: str, project: str) -> object:
        """GET /v1/users/{uid}/projects/{project}/docs → DocList plain JSON."""
        return self._get_json(f"/v1/users/{_seg(uid)}/projects/{_seg(project)}/docs")

    def _doc_base(self, uid: str, project: str, slug: str) -> str:
        """The collection-item URL a single document's mutations hang off."""
        return f"/v1/users/{_seg(uid)}/projects/{_seg(project)}/docs/{_seg(slug)}"

    def _task_base(
        self, uid: str, project: str, slug: str, phase_slug: str, task_index: int
    ) -> str:
        """The item URL a single task's conditional mutations hang off."""
        doc = self._doc_base(uid, project, slug)
        return f"{doc}/phases/{_seg(phase_slug)}/tasks/{task_index}"

    def create_document(self, uid: str, project: str, body: dict) -> Reply:
        resp = self._http.post(
            f"/v1/users/{_seg(uid)}/projects/{_seg(project)}/docs", json=body
        )
        return self._reply(resp)

    def get_document(self, uid: str, project: str, slug: str) -> Reply:
        resp = self._http.get(self._doc_base(uid, project, slug))
        return self._reply(resp)

    def delete_document(self, uid: str, project: str, slug: str, *, rev: str) -> Reply:
        resp = self._http.request(
            "DELETE",
            self._doc_base(uid, project, slug),
            headers={"If-Match": rev},
        )
        return self._reply(resp)

    def set_document_status(
        self, uid: str, project: str, slug: str, status: str
    ) -> Reply:
        body = DocStatusRequest(status=DocStatus(status))
        resp = self._http.put(
            f"{self._doc_base(uid, project, slug)}/status",
            json=body.model_dump(mode="json"),
        )
        return self._reply(resp)

    def put_research_refs(
        self,
        uid: str,
        project: str,
        slug: str,
        research_refs: list[str],
        primary: str | None,
    ) -> Reply:
        body = ResearchRefsRequest(
            research_refs=research_refs, primary_research_ref=primary
        )
        resp = self._http.put(
            f"{self._doc_base(uid, project, slug)}/research-refs",
            json=body.model_dump(mode="json"),
        )
        return self._reply(resp)

    def add_phase(
        self,
        uid: str,
        project: str,
        slug: str,
        phase_slug: str,
        name: str,
        status: str,
        intro: str = "",
        exit_criteria: str = "",
        notes: str = "",
    ) -> Reply:
        body = AddPhaseRequest(
            slug=phase_slug,
            name=name,
            status=PhaseStatus(status),
            intro=intro,
            exit_criteria=exit_criteria,
            notes=notes,
        )
        resp = self._http.post(
            f"{self._doc_base(uid, project, slug)}/phases",
            json=body.model_dump(mode="json"),
        )
        return self._reply(resp)

    def set_phase(
        self,
        uid: str,
        project: str,
        slug: str,
        phase_slug: str,
        name: str | None,
        intro: str | None = None,
        exit_criteria: str | None = None,
        notes: str | None = None,
    ) -> Reply:
        # exclude_none: an omitted flag leaves that field unchanged server-side.
        body = SetPhaseRequest(
            name=name, intro=intro, exit_criteria=exit_criteria, notes=notes
        )
        resp = self._http.put(
            f"{self._doc_base(uid, project, slug)}/phases/{_seg(phase_slug)}",
            json=body.model_dump(mode="json", exclude_none=True),
        )
        return self._reply(resp)

    def set_phase_status(
        self, uid: str, project: str, slug: str, phase_slug: str, status: str
    ) -> Reply:
        body = PhaseStatusRequest(status=PhaseStatus(status))
        resp = self._http.put(
            f"{self._doc_base(uid, project, slug)}/phases/{_seg(phase_slug)}/status",
            json=body.model_dump(mode="json"),
        )
        return self._reply(resp)

    def move_phase(
        self,
        uid: str,
        project: str,
        slug: str,
        phase_slug: str,
        to_index: int,
        *,
        rev: str,
    ) -> Reply:
        body = MovePhaseRequest(to_index=to_index)
        resp = self._http.post(
            f"{self._doc_base(uid, project, slug)}/phases/{_seg(phase_slug)}/move",
            json=body.model_dump(mode="json"),
            headers={"If-Match": rev},
        )
        return self._reply(resp)

    def remove_phase(self, uid: str, project: str, slug: str, phase_slug: str) -> Reply:
        resp = self._http.request(
            "DELETE",
            f"{self._doc_base(uid, project, slug)}/phases/{_seg(phase_slug)}",
        )
        return self._reply(resp)

    def add_task(
        self,
        uid: str,
        project: str,
        slug: str,
        phase_slug: str,
        text: str,
        at: int | None = None,
        checked: bool = False,
    ) -> Reply:
        body = AddTaskRequest(text=text, at=at, checked=checked)
        resp = self._http.post(
            f"{self._doc_base(uid, project, slug)}/phases/{_seg(phase_slug)}/tasks",
            json=body.model_dump(mode="json", exclude_none=True),
        )
        return self._reply(resp)

    def toggle_task(
        self,
        uid: str,
        project: str,
        slug: str,
        phase_slug: str,
        task_index: int,
        checked: bool,
        *,
        rev: str,
    ) -> Reply:
        base = self._task_base(uid, project, slug, phase_slug, task_index)
        body = ToggleTaskRequest(checked=checked)
        resp = self._http.put(
            f"{base}/toggle",
            json=body.model_dump(mode="json"),
            headers={"If-Match": rev},
        )
        return self._reply(resp)

    def edit_task(
        self,
        uid: str,
        project: str,
        slug: str,
        phase_slug: str,
        task_index: int,
        text: str,
        *,
        rev: str,
    ) -> Reply:
        base = self._task_base(uid, project, slug, phase_slug, task_index)
        body = EditTaskRequest(text=text)
        resp = self._http.put(
            base,
            json=body.model_dump(mode="json"),
            headers={"If-Match": rev},
        )
        return self._reply(resp)

    def remove_task(
        self,
        uid: str,
        project: str,
        slug: str,
        phase_slug: str,
        task_index: int,
        *,
        rev: str,
    ) -> Reply:
        base = self._task_base(uid, project, slug, phase_slug, task_index)
        resp = self._http.request(
            "DELETE",
            base,
            headers={"If-Match": rev},
        )
        return self._reply(resp)

    def add_section(
        self,
        uid: str,
        project: str,
        slug: str,
        anchor: str,
        heading: str,
        body: str,
        level: int,
        at: int | None = None,
        placement: SectionPlacement = SectionPlacement.lead,
    ) -> Reply:
        req = AddSectionRequest(
            anchor=anchor,
            heading=heading,
            body=body,
            level=level,
            at=at,
            placement=placement,
        )
        resp = self._http.post(
            f"{self._doc_base(uid, project, slug)}/sections",
            json=req.model_dump(mode="json", exclude_none=True),
        )
        return self._reply(resp)

    def move_section(
        self,
        uid: str,
        project: str,
        slug: str,
        anchor: str,
        to_index: int,
        *,
        rev: str,
    ) -> Reply:
        body = MoveSectionRequest(to_index=to_index)
        resp = self._http.post(
            f"{self._doc_base(uid, project, slug)}/sections/{_seg(anchor)}/move",
            json=body.model_dump(mode="json"),
            headers={"If-Match": rev},
        )
        return self._reply(resp)

    def set_section(
        self,
        uid: str,
        project: str,
        slug: str,
        anchor: str,
        heading: str | None,
        body: str | None,
        level: int | None,
        placement: SectionPlacement | None = None,
    ) -> Reply:
        # exclude_none: an omitted flag leaves that field unchanged server-side.
        req = SetSectionRequest(
            heading=heading, body=body, level=level, placement=placement
        )
        resp = self._http.put(
            f"{self._doc_base(uid, project, slug)}/sections/{_seg(anchor)}",
            json=req.model_dump(mode="json", exclude_none=True),
        )
        return self._reply(resp)

    def patch_section(
        self, uid: str, project: str, slug: str, anchor: str, patch: dict
    ) -> Reply:
        req = PatchSectionRequest(patch=patch)
        resp = self._http.patch(
            f"{self._doc_base(uid, project, slug)}/sections/{_seg(anchor)}",
            json=req.model_dump(mode="json"),
        )
        return self._reply(resp)

    def remove_section(self, uid: str, project: str, slug: str, anchor: str) -> Reply:
        resp = self._http.request(
            "DELETE",
            f"{self._doc_base(uid, project, slug)}/sections/{_seg(anchor)}",
        )
        return self._reply(resp)

    def search(self, uid: str, project: str, q: str) -> object:
        """GET /v1/users/{uid}/projects/{project}/search?q=... → SearchResults JSON."""
        resp = self._http.get(
            f"/v1/users/{_seg(uid)}/projects/{_seg(project)}/search", params={"q": q}
        )
        self._raise_for_status(resp)
        return resp.json()

    def set_project_name(self, uid: str, project: str, name: str) -> dict[str, str]:
        """PUT /v1/users/{uid}/projects/{project}/name → {project, name}."""
        resp = self._http.put(
            f"/v1/users/{_seg(uid)}/projects/{_seg(project)}/name",
            json={"name": name},
        )
        self._raise_for_status(resp)
        return resp.json()  # type: ignore[return-value]

    def lineage(self, uid: str, project: str) -> object:
        """GET /v1/users/{uid}/projects/{project}/lineage → lineage dict plain JSON."""
        return self._get_json(f"/v1/users/{_seg(uid)}/projects/{_seg(project)}/lineage")

    def get_rev(self, uid: str, project: str, slug: str) -> str:
        """HEAD the document and return its ETag (rev) without fetching the body."""
        resp = self._http.head(self._doc_base(uid, project, slug))
        self._raise_for_status(resp)
        return resp.headers.get("ETag", "")

    def set_document_meta(
        self,
        uid: str,
        project: str,
        slug: str,
        *,
        title: str | None,
        description: str | None,
        date: str | None,
        frontmatter: dict | None,
    ) -> Reply:
        # exclude_none: omitted fields are left unchanged server-side.
        body = SetDocumentMetaRequest(
            title=title,
            description=description,
            date=date,
            frontmatter=frontmatter,
        )
        resp = self._http.put(
            self._doc_base(uid, project, slug),
            json=body.model_dump(mode="json", exclude_none=True),
        )
        return self._reply(resp)
