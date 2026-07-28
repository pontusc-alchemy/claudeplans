"""Seed a running claudeplans stack with demo data covering the sidebar/lineage
combinations:

- `empty`  — registry display name only, zero docs (must NOT appear anywhere).
- `atlas`  — a research doc + a standalone plan (no research link → unlinked) +
  two long lorem-ipsum docs (research + plan) for testing page scrolling.
- `beacon` — a research doc + a plan linked to it (primary ref → nests under the
  research node) + a standalone research doc with no plans + an archived plan
  (surfaces in the sidebar's collapsed "Archived" group).

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


_LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim "
    "veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea "
    "commodo consequat. Duis aute irure dolor in reprehenderit in voluptate "
    "velit esse cillum dolore eu fugiat nulla pariatur."
)


def _lorem_sections(count: int, paragraphs: int) -> list[dict[str, Any]]:
    """Filler sections that make a document long enough to scroll."""
    body = "\n\n".join([_LOREM] * paragraphs)
    return [
        _section(f"lorem-{i}", f"Lorem section {i}", body) for i in range(1, count + 1)
    ]


def _lorem_phases(count: int, tasks: int) -> list[dict[str, Any]]:
    """Filler phases with wordy tasks — the plan-page scrolling counterpart."""
    return [
        _phase(
            f"phase-{i}",
            f"Phase {i}: {_LOREM[:40].lower()}",
            "todo",
            [(f"{_LOREM[:120]} (task {j})", False) for j in range(1, tasks + 1)],
        )
        for i in range(1, count + 1)
    ]


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
            {
                "type": "research",
                "slug": "lorem-research",
                "title": "Lorem Research (long)",
                "status": "draft",
                "description": "Long lorem-ipsum research doc for scroll testing.",
                "sections": _lorem_sections(count=14, paragraphs=4),
            },
            {
                "type": "plan",
                "slug": "lorem-plan",
                "title": "Lorem Plan (long)",
                "status": "active",
                "description": "Long lorem-ipsum plan for scroll testing.",
                "phases": _lorem_phases(count=10, tasks=8),
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
            {
                "type": "plan",
                "slug": "legacy-migration",
                "title": "Legacy Migration",
                "status": "archived",
                "description": (
                    "Retired plan — surfaces in the sidebar's Archived group."
                ),
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
