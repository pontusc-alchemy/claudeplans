---
name: write
description: Author an actionable implementation plan as Markdown under ~/plans/src/projects/<project>/; it auto-renders to a navigable dark-themed HTML view at http://plans.claude. Turns a discussion — or an existing research document — into ordered, phased implementation steps with decisions and learnings.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Agent, Read, Write, Edit
---

Produce an **actionable** implementation plan, authored as Markdown per `${CLAUDE_PLUGIN_ROOT}/AUTHORING.md` — never write HTML, never touch the theme. This is the action cornerstone: where `/plan:research` gathers _what's possible_, `/plan:write` decides _what to do_ and _how_.

<!-- This skill uses portable `general-purpose` agent names, not the house scout/investigator roster — a deliberate divergence so it works without those agents installed. -->

Argument: `<project> [research-slug]`.

## 0 — Scaffold

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" new "<project>" plan "<title>" [--slug S]
```

→ JSON `{path, slug, project, url}`; non-zero exit → relay stderr and stop. A `creating new project '<p>'` warning on stderr is a typo guard — confirm the project with the user. Then fill the scaffold with `Write`/`Edit`; the template is the output contract.

## Input — where the plan comes from

- **From a research doc:** given `research-slug`, delegate a Haiku `Agent` to read `~/plans/src/projects/<project>/<research-slug>.md` and return its options, recommendations, links, and constraints. Convert that into decisions and phases — don't restate it; link back via a relative `.md` link.
- **From the conversation:** structure the plan we've worked out.
- **From the repo:** any codebase context-gathering goes to `general-purpose` agents — never read large files in the main thread.

Expect to iterate: the user reviews and discusses while the plan is constructed. Lead with `## Executive summary` answering the user's explicit questions, each linking to its phase.

## On approval

Once the user approves the plan, flip status:

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" status <path> active
```

When the plan was built from a research doc, its decision is now consumed — propose `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" status <research path> done`.
