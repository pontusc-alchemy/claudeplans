---
name: research
description: Research a topic and present the findings as a Markdown document under ~/plans/src/projects/<project>/ that auto-renders to a dark-themed HTML view at http://plans.claude. Use to investigate a question, compare options, or gather and cite sources into a browsable deliverable.
user-invocable: true
model-invocable: false
allowed-tools: Bash, Agent, Read, Write, Edit
---

Gather material on a topic, then present it as a **Markdown** findings document authored per `${CLAUDE_PLUGIN_ROOT}/AUTHORING.md` — never write HTML, never touch the theme. This is the reference cornerstone: it captures _what's possible_ (options, docs, links) for `/plan:write` to turn into action.

Argument: `<project> <topic>`.

## 0 — Scaffold

```shell
"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" new "<project>" research "<topic>" [--slug S]
```

→ JSON `{path, slug, project, url}`; non-zero exit → relay stderr and stop. A `creating new project '<p>'` warning on stderr is a typo guard — confirm the project with the user before continuing. Then fill the scaffold with `Write`/`Edit`; the template is the section contract.

## 1 — Gather (delegate; don't read in the main thread)

Spawn `general-purpose` agents (`model: haiku`) to do the reading and web lookups:

- **Find the official docs / primary source first.** Verify any blog/third-party against official sources; if none cover the point, third-party is acceptable but MUST be flagged unverified.
- Have agents return verbatim specifics (versions, flags, exact config, URLs) — not paraphrase.
- Capture each claim's source for citation.

## 2 — Fill the findings

- Cite inline: `[official docs](url)`, `<span class="src">…</span>` for provenance.
- Mark every unverified / third-party claim: `<span class="tag">unverified</span>` and/or a `!!! warning`.
- When the findings are substantive, flip status: `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-doc" status <slug> active`.

## 3 — Hand off (optional)

When the research should drive decisions, point `/plan:write` at this doc.
