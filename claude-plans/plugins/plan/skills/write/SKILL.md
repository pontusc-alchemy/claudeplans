---
name: write
description: Author an actionable implementation plan as Markdown under ~/plans/src/projects/<project>/; it auto-renders to a navigable dark-themed HTML view at http://plans.claude. Turns a discussion — or an existing research document — into ordered, phased implementation steps with decisions and learnings.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Agent, Read, Write, Edit
---

Produce an **actionable** implementation plan, authored as Markdown per `${CLAUDE_PLUGIN_ROOT}/server/AUTHORING.md` — never write HTML, never touch the theme. This is the action cornerstone: where `/plan:research` gathers _what's possible_, `/plan:write` decides _what to do_ and _how_.

Argument: `<project> [research-slug]`.

## 0 — Scaffold from the template (never author from scratch)

- Slug the plan to kebab-case. Copy `${CLAUDE_PLUGIN_ROOT}/templates/plan.md` to `~/plans/src/projects/<project>/<slug>.md`, creating the project dir if new (`mkdir -p`). Fill the scaffold — it is the output contract.
- Author with the `Write`/`Edit` tools, never `cat >` heredocs — the guard-sensitive hook scans Bash command content and will false-positive on document text.

## Input — where the plan comes from

- **From a research doc:** given `research-slug`, delegate a Haiku `Agent` to read `~/plans/src/projects/<project>/<research-slug>.md` and return its options, recommendations, links, and constraints. Convert that into decisions and phases — don't restate it; link back via a relative `.md` link.
- **From the conversation:** structure the plan we've worked out.
- **From the repo:** any codebase context-gathering goes to `scout` agents — never `Explore` or `general-purpose` defaults.

Expect to iterate: the user reviews and discusses while the plan is constructed.

## Make it actionable

- Lead with `## Executive summary` answering the user's explicit questions, each linking to its phase via a descriptive anchor link.
- Order the work into phases per AUTHORING v2: `## Phase N — <name> {#phase-n}`, each with a status pill (`gap` → `partial` → `ok`), a `- [ ]` checklist of exact commands/config/paths/version pins, and explicit **Exit criteria**.
- Mark cross-cutting decisions in `## Gaps & decisions {#checklist}` with pills.
- Leave `## Learnings {#learnings}` and `## Review log {#review-log}` as stubs — `/plan:iterate` and `/plan:review` fill them.
- Flag unverified or risky claims with `!!! warning` / `!!! danger` admonitions.
