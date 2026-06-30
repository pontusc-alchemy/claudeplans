---
name: write
description: Author an actionable implementation plan as a structured document in the claudeplans service (CLI + live HTML view). Turns a discussion — or an existing research document — into ordered, phased implementation steps with decisions and learnings.
user-invocable: true
model-invocable: true
allowed-tools: Bash, Agent
---

Produce an **actionable** implementation plan in the claudeplans service via the CLI. This is the action cornerstone: where `/plan:research` gathers _what's possible_, `/plan:write` decides _what to do_ and _how_.

<!-- This skill uses portable `general-purpose` agent names, not the house scout/investigator roster — a deliberate divergence so it works without those agents installed. -->

Argument: `<project> [research-slug]`.

## 0 — Scaffold

Generate a URL-safe slug for the plan title (kebab-case, ≤40 chars). Create the document:

```shell
claudeplans doc create "<project>" --type plan --slug "<slug>" --title "<plan title>"
```

→ the slim create reply `{slug, type, rev, warnings}` (pass `--full`/`-v` for the whole `{rev, data, warnings}` envelope); non-zero exit → relay stderr and stop. The project is created implicitly on the first doc and there is no new-project warning — so if this is a NEW project (not in `claudeplans project list`), **confirm the project name with the user first**: both the URL-safe slug and the intended display name. Keep the plan `--title` short and navigable (a few words); the descriptive detail belongs in the doc's summary, not the title. After creating a new project's first doc, set its display name: `claudeplans project set-name "<project>" "<Display Name>"`. The shell form also accepts `--status`/`--description`/`--date` in the same call (e.g. reconstructing a completed plan with `--status done`), avoiding a follow-up `doc set`/`set-status`.

## Input — where the plan comes from

- **From a research doc:** given `research-slug`, delegate a Haiku `Agent` to run `claudeplans doc get "<project>" "<research-slug>"` and return its sections, options, recommendations, links, and constraints. Convert those into decisions and phases — link the consumed research via:
  ```shell
  claudeplans doc link "<project>" "<plan-slug>" "<research-slug>" --primary
  ```
- **From the conversation:** structure the plan we've worked out.
- **From the repo:** any codebase context-gathering goes to `general-purpose` agents — never read large files in the main thread.

Build the complete doc — all phases, tasks, and prose sections — via the CLI, then point the user to the rendered view (`claudeplans doc view`) to review; do not preview the structure in chat (it is easier to read in the browser). Lead with an "executive-summary" section answering the user's explicit questions, each referencing its phase. Pause for explicit user approval only at the status flip (see "On approval" below).

## Build the structure

Add phases and tasks:

```shell
claudeplans phase add "<project>" "<slug>" "<phase-slug>" "<Phase Name>"
claudeplans task add "<project>" "<slug>" "<phase-slug>" "Task description"
```

`phase add` accepts the same prose flag spellings `phase set` does — `--intro`/`--exit-criteria`/`--notes` (inline) and `--intro-file`/`--exit-criteria-file`/`--notes-file` (a file path, or `-` for stdin) — so a phase and its intro / exit-criteria / notes land in one call instead of an `add` then a follow-up `set`. Note the omit-semantics differ: on `add` (a create) omitted prose defaults to **empty**, whereas on `set` omitted leaves the field unchanged and `''` clears it.

`task add --checked` creates a task already-checked in one rev-free call — use it when reconstructing an already-completed plan so you skip the per-task `toggle --rev` loop (read rev → toggle → repeat). The default is unchecked.

Add prose sections:

```shell
claudeplans section add "<project>" "<slug>" "<anchor>" "<Heading>" --body "<markdown>" --level 2
```

Section bodies are **plain markdown** — do not write HTML spans, pills, or admonitions; the service renders and sanitizes.

## On approval

Once the user approves the plan, flip status:

```shell
claudeplans doc status "<project>" "<slug>" active
```

When the plan was built from a research doc, its decision is now consumed — propose:

```shell
claudeplans doc status "<project>" "<research-slug>" done
```

Get the browsable view URL with `claudeplans doc view "<project>" "<slug>"`.
