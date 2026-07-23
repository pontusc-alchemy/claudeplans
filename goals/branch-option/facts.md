# Facts — host-plans: optional branch-level nesting

- A `.md` file directly under `projects/<project>/` is still a flat slug with no branch; existing flat docs render and resolve unchanged (no migration required).
- `plan-doc list` discovers docs at both `projects/<project>/<slug>.md` and `projects/<project>/<branch>/<slug>.md`.
- `card()` output includes a `branch` field: empty string for flat docs, the branch directory name for branched docs.
- Branch detection is capped at exactly one level: only `projects/<project>/<branch>/<slug>.md` is recognized; deeper nesting is not treated as additional branch levels.
- `plan-doc resolve` finds a branched doc by bare slug when that slug is unique across the tree.
- When a bare slug matches multiple docs (flat + branched, or two branches), `resolve` reports ambiguity rather than silently picking one.
- `plan-doc resolve` accepts explicit `<branch>/<slug>` addressing to disambiguate a slug that exists under a branch.
- The plans.claude landing page renders branched docs under a per-branch sub-heading within each project section.
- Flat docs (no branch) render directly under their project with no spurious branch sub-heading.
- The landing page surfaces generated `diagrams/*.html` as a compact "Diagrams" link-list under the matching project/branch, with filename-derived labels (no frontmatter required).
- A directory containing only `.html` diagrams (no `.md`) does not appear as an empty branch or produce a doc card.
- `AUTHORING.md` and `README` document the optional branch level and the file-vs-dir detection rule.
