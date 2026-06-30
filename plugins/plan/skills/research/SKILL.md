---
name: research
description: Research a topic and create a structured findings document in the claudeplans service (CLI + browsable view). Use to investigate a question, compare options, or gather and cite sources into a browsable deliverable.
user-invocable: true
model-invocable: true
allowed-tools: Bash, Agent
---

Gather material on a topic, then persist the findings as a **structured research document** in the claudeplans service via the CLI. This is the reference cornerstone: a FULL consideration of a topic (why, options, docs, gotchas). An action plan is not always the end goal — the findings doc itself may be the deliverable.

Argument: `<project> <topic>`.

## 0 — Scaffold

Generate a URL-safe slug from the topic (kebab-case, ≤40 chars). Create the document:

```shell
claudeplans doc create "<project>" --type research --slug "<slug>" --title "<topic title>"
```

→ the slim create reply `{slug, type, rev, warnings}` (pass `--full`/`-v` for the whole `{rev, data, warnings}` envelope); non-zero exit → relay stderr and stop. The project is created implicitly on the first doc and there is no new-project warning — so if this is a NEW project (not in `claudeplans project list`), **confirm the project name with the user first**: both the URL-safe slug and the intended display name. Keep the `--title` short and navigable (a few words); the descriptive detail belongs in the doc's summary, not the title. After creating a new project's first doc, set its display name: `claudeplans project set-name "<project>" "<Display Name>"`. The shell create form also accepts `--status`/`--description`/`--date` in the same call. Sections are added via `claudeplans section add` — the section contract is in `${CLAUDE_PLUGIN_ROOT}/AUTHORING.md`.

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

Build the document section by section using the CLI:

```shell
claudeplans section add "<project>" "<slug>" "<anchor>" "<Heading>" --body "<markdown text>" --level 2
claudeplans section set "<project>" "<slug>" "<anchor>" --body "<updated markdown>"
```

Section bodies are **plain markdown** — cite sources inline as `[official docs](url)`. Mark every unverified / third-party claim in the body text (e.g. `[unverified — third-party source]`). Do not write HTML spans, pills, or admonitions — the service renders and sanitizes the markdown.

When the findings are substantive, flip status:

```shell
claudeplans doc status "<project>" "<slug>" active
```

Get the browsable view URL with `claudeplans doc view "<project>" "<slug>"`.

## 4 — Hand off (optional)

When the research should drive action, offer to point `/plan:write` at this doc (pass the research slug as the second argument). Pure topic research with no implementation plan is a valid end state.
