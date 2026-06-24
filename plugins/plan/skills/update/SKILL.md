---
name: update
description: Make a targeted revision to a saved plan or research document in the claudeplans service — edit a section, phase status, task state, or doc status on request via the CLI. Takes the project and doc slug plus the change to make. The direct-edit loop of the lifecycle.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Agent
---

Apply an intent-driven revision to a saved document via the claudeplans CLI. This is the direct loop: change content because the user asked, when no implementation or audit is happening. (`/plan:iterate` is the forward loop that edits as work happens; `/plan:review` is the reverse loop that reconciles against reality.) Works on both `research` and `plan` docs.

Arguments must carry both `<project>` and `<slug>` — there is no fuzzy resolve. For project-wide discovery: list projects with `claudeplans project list`, list a project's documents with `claudeplans doc list <project>` (both return JSON). The lineage page is the human browser view — open it with `claudeplans project view <project>` which prints its URL. (The search endpoint requires `?q=<term>` and performs keyword search, not enumeration.)

## Read before editing

Load what the change targets (use projections to stay narrow):

```shell
claudeplans doc get "<project>" "<slug>" --section "<anchor>"
claudeplans doc get "<project>" "<slug>" --phase "<phase-slug>"
claudeplans doc get "<project>" "<slug>" --fields "title,description,status"
claudeplans doc phases "<project>" "<slug>"   # returns rev — required for position-sensitive ops
```

Non-zero exit → relay stderr and stop.

## Confirm, then revise

- Confirm the change with the user before editing — restate what will change and where.
- Never create a new slug or version.

**Section prose** — replace a section body or patch individual fields:
```shell
claudeplans section set "<project>" "<slug>" "<anchor>" --body "<updated markdown>"
claudeplans section set "<project>" "<slug>" "<anchor>" --heading "<new heading>" --level 3
claudeplans section patch "<project>" "<slug>" "<anchor>" --merge-patch '{"body":"<updated>"}'
```
Section bodies are **plain markdown** — do not write HTML spans, pills, or admonitions.

**Phase status** — use `phase set-status` (never hand-edit):
```shell
claudeplans phase set-status "<project>" "<slug>" "<phase-slug>" todo|doing|done|blocked
```

**Task state** — read `doc phases` first to get `rev` and the task index (0-based):
```shell
claudeplans task toggle "<project>" "<slug>" "<phase-slug>" <index> --rev <rev>
claudeplans task toggle "<project>" "<slug>" "<phase-slug>" <index> --rev <rev> --unchecked
claudeplans task edit "<project>" "<slug>" "<phase-slug>" <index> "<new text>" --rev <rev>
```

**Doc status** — flip the lifecycle state:
```shell
claudeplans doc status "<project>" "<slug>" draft|active|done
```

**Structural moves** (rename slug, reorder sections across docs, delete) are out of scope — the slug is the document's identity; renaming requires re-creating the doc. Flag these and ask the user to handle them explicitly.

## Validate

A write that violates a server-side invariant is **rejected** with exit 4 (ValidationError) — relay the error and stop; there is no separate drift linter. If the edit closes all open gaps or re-opens decided work, propose the matching `doc status` flip.
