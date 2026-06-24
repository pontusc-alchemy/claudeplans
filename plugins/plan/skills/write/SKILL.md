---
name: write
description: Author an actionable implementation plan as a structured document in the claudeplans service (CLI + live HTML view). Turns a discussion — or an existing research document — into ordered, phased implementation steps with decisions and learnings.
user-invocable: true
model-invocable: false
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

→ the reply envelope `{rev, data:{...}, warnings}` (the created doc's fields are under `data`); non-zero exit → relay stderr and stop. The project is created implicitly on first doc — double-check the project name is right before continuing (there is no new-project warning).

## Input — where the plan comes from

- **From a research doc:** given `research-slug`, delegate a Haiku `Agent` to run `claudeplans doc get "<project>" "<research-slug>"` and return its sections, options, recommendations, links, and constraints. Convert those into decisions and phases — link the consumed research via:
  ```shell
  claudeplans doc link "<project>" "<plan-slug>" "<research-slug>" --primary
  ```
- **From the conversation:** structure the plan we've worked out.
- **From the repo:** any codebase context-gathering goes to `general-purpose` agents — never read large files in the main thread.

Expect to iterate: the user reviews and discusses while the plan is constructed. Lead with an "executive-summary" section answering the user's explicit questions, each referencing its phase.

## Build the structure

Add phases and tasks:

```shell
claudeplans phase add "<project>" "<slug>" "<phase-slug>" "<Phase Name>"
claudeplans task add "<project>" "<slug>" "<phase-slug>" "Task description"
```

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
