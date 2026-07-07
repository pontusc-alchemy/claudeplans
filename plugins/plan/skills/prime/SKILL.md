---
name: prime
description: Bootstrap session context from a claudeplans document or project. Given a project and slug, brief that document; for project-wide discovery use `claudeplans project list` / `claudeplans doc list <project>`.
user-invocable: true
model-invocable: true
allowed-tools: Bash, Agent
model: sonnet
---

Load context from a document in the claudeplans service by delegating the reads to an agent — never read large JSON payloads in the main thread. Arguments must carry both `<project>` and `<slug>` — there is no fuzzy resolve.

For project-wide discovery (no slug known): enumerate with the CLI — `claudeplans project list` lists all projects, `claudeplans doc list <project>` lists a project's documents (both return JSON). Ask the user to supply the slug before continuing. The lineage page is the human browser view; get its URL with `claudeplans project view <project>`. (The search endpoint `…/search?q=<term>` performs keyword search — it requires a query term and is not a listing.)

## Load the source

```shell
claudeplans doc get "<project>" "<slug>"
claudeplans doc phases "<project>" "<slug>"
```

Non-zero exit → relay stderr and stop. For a `type: plan` doc, `doc phases` returns `{rev, phases:[{slug, name, status, tasks:[{text, checked}], intro, exit_criteria, notes}], warnings}` — phase prose comes back inline — and the current phase is the first entry whose status is not `done`.

## Brief (delegate)

Spawn one `Agent` (`general-purpose`, `sonnet`) with the JSON output from both calls and instruct it to return a DENSE briefing focused on:

- title + description; section list (anchors + headings) in order;
- module map, if present: module list with owner phases, dependency edges, and
  the **verbatim card contracts** (`mod-*` Requires/Provides) for modules owned
  by the current phase;
- done phases / locked decisions (status `done`);
- open/blocked phases and caveats (status `todo|doing|blocked`), open tasks;
- progress summary (done/total phases, blocked count) and the current phase;
- verbatim config / commands / paths / version pins found in section bodies.

Relay the result as restored context and continue.
