"""Seed a running claudeplans stack with demo data covering the sidebar/lineage
combinations:

- `empty`  — registry display name only, zero docs (must NOT appear anywhere).
- `atlas`  — a research doc + a standalone plan (no research link → unlinked).
- `beacon` — a research doc + a plan linked to it (primary ref → nests under the
  research node) + a standalone research doc with no plans.

Idempotent: doc creation treats 409 (slug already exists) as already-seeded and
skips; project display names re-PUT freely. Targets the dev stack by default —
override with CLAUDEPLANS_URL / CLAUDEPLANS_UID.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

URL = os.environ.get("CLAUDEPLANS_URL", "http://127.0.0.1:9394")
UID = os.environ.get("CLAUDEPLANS_UID", "dev")


def _phase(
    slug: str, name: str, status: str, tasks: list[tuple[str, bool]]
) -> dict[str, Any]:
    return {
        "slug": slug,
        "name": name,
        "status": status,
        "tasks": [{"text": text, "checked": checked} for text, checked in tasks],
    }


def _section(anchor: str, heading: str, body: str) -> dict[str, Any]:
    return {"anchor": anchor, "heading": heading, "body": body}


# (project, display name, [DocumentCreate payloads])
SEED: list[tuple[str, str, list[dict[str, Any]]]] = [
    ("empty", "Empty (should not appear)", []),
    (
        "atlas",
        "Atlas",
        [
            {
                "type": "research",
                "slug": "perf-audit",
                "title": "Performance Audit",
                "status": "active",
                "description": "Where the request time actually goes.",
                "sections": [
                    _section(
                        "findings",
                        "Findings",
                        "The p99 is dominated by cold template renders.",
                    )
                ],
            },
            {
                "type": "plan",
                "slug": "cache-layer",
                "title": "Cache Layer Rollout",
                "status": "draft",
                "description": "Standalone plan — not linked to any research.",
                "phases": [
                    _phase(
                        "design",
                        "Design",
                        "doing",
                        [("Pick eviction policy", True), ("Size the cache", False)],
                    ),
                    _phase(
                        "rollout", "Rollout", "todo", [("Enable behind flag", False)]
                    ),
                ],
            },
        ],
    ),
    (
        "beacon",
        "Beacon",
        [
            {
                "type": "research",
                "slug": "auth-review",
                "title": "Auth Review",
                "status": "done",
                "description": "Survey of the current auth boundary.",
                "sections": [
                    _section(
                        "summary",
                        "Summary",
                        "The noop provider is fine locally; SSO is the gap.",
                    )
                ],
            },
            {
                "type": "plan",
                "slug": "sso-rollout",
                "title": "SSO Rollout",
                "status": "active",
                "description": "Linked plan — nests under auth-review.",
                "research_refs": ["auth-review"],
                "primary_research_ref": "auth-review",
                "phases": [
                    _phase(
                        "provider",
                        "Provider integration",
                        "done",
                        [("Wire OIDC client", True), ("Map claims to uid", True)],
                    ),
                    _phase(
                        "cutover",
                        "Cutover",
                        "blocked",
                        [("Migrate existing sessions", False)],
                    ),
                ],
            },
            {
                "type": "research",
                "slug": "logging-spike",
                "title": "Logging Spike",
                "status": "draft",
                "description": "Standalone research — no plans hang off it.",
            },
        ],
    ),
]


def seed(client: httpx.Client) -> None:
    for project, name, docs in SEED:
        resp = client.put(
            f"/v1/users/{UID}/projects/{project}/name", json={"name": name}
        )
        resp.raise_for_status()
        print(f"named   {project} -> {name!r}")
        for doc in docs:
            resp = client.post(f"/v1/users/{UID}/projects/{project}/docs", json=doc)
            if resp.status_code == 409:
                print(f"exists  {project}/{doc['slug']}")
                continue
            resp.raise_for_status()
            print(f"created {project}/{doc['slug']}")


def main() -> int:
    try:
        with httpx.Client(base_url=URL, timeout=10.0) as client:
            seed(client)
    except httpx.HTTPStatusError as exc:
        print(
            f"seed failed: {exc.request.method} {exc.request.url} "
            f"-> {exc.response.status_code} {exc.response.text}",
            file=sys.stderr,
        )
        return 1
    except httpx.TransportError as exc:
        print(f"seed failed: cannot reach {URL} ({exc})", file=sys.stderr)
        return 1
    print(f"seeded {URL} (uid {UID})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
