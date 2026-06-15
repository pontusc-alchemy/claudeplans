---
name: research
description: Research a topic and present the findings as a Markdown document under ~/plans/src/projects/<project>/ that auto-renders to a dark-themed HTML view at http://plans.claude. Use to investigate a question, compare options, or gather and cite sources into a browsable deliverable.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Agent, Read, Write, Edit
---

Gather material on a topic, then present it as a **Markdown** findings document authored per `${CLAUDE_PLUGIN_ROOT}/AUTHORING.md` — never write HTML, never touch the theme. This is the reference cornerstone: a FULL consideration of a topic (why, options, docs, gotchas). An action plan is not always the end goal — the findings doc itself may be the deliverable.

Argument: `<project> <topic>`.

## 0 — Scaffold

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" new "<project>" research "<topic>" [--slug S]
```

→ JSON `{path, slug, project, url}`; non-zero exit → relay stderr and stop. A `creating new project '<p>'` warning on stderr is a typo guard — confirm the project with the user before continuing. Fill the scaffold with `Write`/`Edit`; the template is the section contract.

## 1 — Survey (delegate, sonnet)

Map the domain before going deep. Spawn `general-purpose` agents (`sonnet` minimum — never haiku) to gather breadth: what exists, what's adjacent, links, hard facts from documentation.

- **Find the official docs / primary source first.** Verify any blog/third-party against official sources; if none cover the point, third-party is acceptable but MUST be flagged unverified.
- Return verbatim specifics (versions, flags, exact config, URLs) — not paraphrase. Capture each claim's source.

## 2 — Deepen (delegate, opus — iterate)

Review the survey in the main thread: the domain is now roughly known, so decide what needs solidifying. Spawn `general-purpose` agents (`opus`) with targeted briefs to iterate on the first wave:

- Solidify load-bearing claims against primary sources; resolve contradictions between survey findings.
- Extract actionable detail: exact config, constraints, trade-offs between options, gotchas.

Run as many deepening passes as a subject warrants — judgment call. A narrow topic may collapse to a single pass; stop only when the findings are solid enough to carry decisions.

## 3 — Construct the findings

- Cite inline: `[official docs](url)`, `<span class="src">…</span>` for provenance.
- Mark every unverified / third-party claim: `<span class="tag">unverified</span>` and/or a `!!! warning`.
- When the findings are substantive, flip status: `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" status <slug> active`.

## 4 — Hand off (optional)

When the research should drive action, offer to point `/plan:write` at this doc. Pure topic research with no implementation plan is a valid end state.
