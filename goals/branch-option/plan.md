# Plan — host-plans: optional branch-level nesting

## Solution approach

Add an **optional** third path segment to the plans doc tree: `projects/<project>/<branch>/<slug>.md` alongside today's flat `projects/<project>/<slug>.md`. Detection is structural — a `.md` **file** under a project is a flat slug; a **subdirectory** is a branch whose `.md` files are slugs. The branch level is capped at one (enforced naturally by explicit two-pattern globs, not `**`). Two files change: `plugins/plan/scripts/plan-doc` (read/resolve path) and `plugins/plan/server/gen_index.py` (landing-page walk + diagram surfacing). Docs follow in `AUTHORING.md` + `README.md`. No write-path (`new --branch`) and no `check` validation this round (out of scope per interview). No migration — flat stays first-class.

Reserved subdir name: **`diagrams`** holds generated `*.html` and is never treated as a branch.

## Ordered steps

### Step 1 — `plan-doc` read + resolve path
File: `plugins/plan/scripts/plan-doc`

- `all_docs()`: glob **both** `projects/*/*.md` (flat) and `projects/*/*/*.md` (branched), merge + sort. The two fixed-depth patterns cap branch nesting at one level — `projects/a/b/c/d.md` matches neither. Covers `fact-discover-branched`, `fact-one-level-cap`.
- `card()`: derive project/branch from the path relative to `DOCS_ROOT/projects` — `parts` length 2 → `(project, branch="")`; length 3 → `(project=parts[0], branch=parts[1])`. Add a `"branch"` key to the returned dict. Covers `fact-card-branch-field`, `fact-flat-unchanged`.
- New helper `find_by_arg(arg)` used by both `resolve_path()` (status/touch/phases) and `cmd_resolve()`:
  - If `arg` contains `/` → split into `branch, slug`; match docs whose parent dir == `branch` and stem == `slug` (covers `fact-resolve-addressing`).
  - Else bare stem match across `all_docs()`: 1 match → resolve; >1 → ambiguous (covers `fact-resolve-branched`, `fact-resolve-ambiguity`).
- `cmd_resolve()` project branch: when `arg` is a project dir, list its docs via `*.md` **and** `*/*.md` so branched docs are included.
- `cmd_new()` untouched (stays flat-only).

### Step 2 — `gen_index.py` branch-aware walk + diagram surfacing
File: `plugins/plan/server/gen_index.py`

- `_projects(docs_dir)`: build a nested model per project:
  - flat docs: `projects/<project>/*.md`
  - branches: each subdir of `<project>` **except `diagrams`**; its docs = `<branch>/*.md`, its diagrams = `<branch>/diagrams/*.html`
  - project-level diagrams: `projects/<project>/diagrams/*.html`
  - A `diagrams/` dir yields no doc cards and is never a branch heading (covers `fact-diagrams-no-empty-group`).
- `_render(...)`: per project emit `<h2 id="project-<p>">`, then flat cards, then for each branch (sorted by newest doc date desc, then name) a `<h3 id="project-<p>-<branch>">` sub-heading with that branch's cards (covers `fact-index-nested`); projects with no branch dirs emit no sub-heading (covers `fact-index-flat-no-subheading`).
- Diagram link-list: a compact block (filename-stem labels, reusing existing `muted` styling — no new CSS) rendered under the matching branch (or project for flat-level diagrams). Covers `fact-diagrams-linklist`.

### Step 3 — Docs
Files: `plugins/plan/AUTHORING.md`, `README.md`

- Document the optional `projects/<project>/<branch>/<slug>.md` layout, the file-vs-dir rule, the one-level cap, and the reserved `diagrams/` convention. Covers `fact-docs-updated` (manual).

### Step 4 — Verification harness
Fixture-based; `plan-doc` is stdlib-only, `gen_index` rendering is a pure function callable without MkDocs (only needs `yaml`).

## Verification

Run from repo root. `PD` = `python3 plugins/plan/scripts/plan-doc`.

**Fixture setup**
```bash
TMP=$(mktemp -d); P=$TMP/projects/demo
mkdir -p "$P/feat-x/diagrams" "$P/feat-x/sub" "$P/diagrams"
fm(){ printf -- '---\ntitle: %s\ndescription: d\ntype: plan\nstatus: draft\ndate: 2026-06-15\n---\n' "$1"; }
fm flat   > "$P/flatdoc.md"
fm branch > "$P/feat-x/branchdoc.md"
fm dupA   > "$P/dup.md"
fm dupB   > "$P/feat-x/dup.md"
fm deep   > "$P/feat-x/sub/toodeep.md"          # beyond one-level cap
printf '<html>flow</html>'   > "$P/feat-x/diagrams/flow.html"
printf '<html>recap</html>'  > "$P/feat-x/diagrams/recap.html"
export PLANS_SRC=$TMP
```

**plan-doc facts**
```bash
# discover-branched + one-level-cap: flatdoc, branchdoc, dup(x2) present; toodeep absent
$PD list | python3 -c 'import json,sys; s={d["slug"] for d in json.load(sys.stdin)}; assert {"flatdoc","branchdoc","dup"}<=s and "toodeep" not in s, s; print("OK discover+cap")'
# card-branch-field: flat -> "", branched -> "feat-x"
$PD list | python3 -c 'import json,sys; d={x["slug"]:x["branch"] for x in json.load(sys.stdin)}; assert d["flatdoc"]=="" and d["branchdoc"]=="feat-x", d; print("OK branch field")'
# resolve-branched (unique bare slug)
$PD resolve branchdoc | python3 -c 'import json,sys; assert json.load(sys.stdin)["kind"]=="doc"; print("OK resolve branched")'
# resolve-ambiguity (dup in flat + branch)
$PD resolve dup | python3 -c 'import json,sys; assert json.load(sys.stdin)["kind"]=="ambiguous"; print("OK ambiguity")'
# resolve-addressing (<branch>/<slug>)
$PD resolve feat-x/dup | python3 -c 'import json,sys; assert json.load(sys.stdin)["kind"]=="doc"; print("OK addressing")'
# flat-unchanged: status/touch still work on a flat doc
$PD touch flatdoc >/dev/null && echo "OK flat touch"
```

**gen_index facts** (PY = venv python if present, else any python3 with pyyaml)
```bash
PY=${HOME}/.config/plans-server/venv/bin/python; command -v "$PY" >/dev/null || PY=python3
"$PY" - <<'EOF'
import importlib.util, os
spec=importlib.util.spec_from_file_location("gi","plugins/plan/server/gen_index.py")
gi=importlib.util.module_from_spec(spec); spec.loader.exec_module(gi)
html=gi._render(gi._projects(os.path.join(os.environ["PLANS_SRC"])))
assert 'id="project-demo-feat-x"' in html, "nested branch sub-heading missing"     # fact-index-nested
assert html.index("flatdoc") < html.index('id="project-demo-feat-x"'), "flat not above branch"  # fact-index-flat
assert "flow" in html and "recap" in html, "diagram link-list missing"             # fact-diagrams-linklist
assert 'id="project-demo-diagrams"' not in html, "diagrams dir leaked as a branch" # fact-diagrams-no-empty-group
print("OK gen_index: nested + flat + diagrams + no-phantom-branch")
EOF
rm -rf "$TMP"
```

**Regression** — existing flat docs still render: after `make -C plugins/plan/server build` (if the venv is installed) the landing page contains `grid cards` (mirrors the Makefile `status` probe).

## Risks / open questions

- **CSS polish** — the Diagrams link-list reuses existing `muted` styling to avoid touching `extra.css` (out of scope). If it reads poorly, a small `.diagrams` rule in `extra.css` is a trivial follow-up.
- **Branch ordering on the landing page** — sorted by newest doc date desc then name; a branch with only diagrams (no dated docs) sorts last. Acceptable; revisit if it feels wrong.
- **`diagrams` as a reserved name** — a real git branch literally named `diagrams` would be swallowed by the diagram bucket. Vanishingly unlikely; documented in AUTHORING.md rather than guarded in code.
- **Cross-repo follow-up (not in this goal)** — the `output-dir.py` redirect in the cc-marketplace repo is what actually writes `diagrams/` into `PLANS_SRC`; until that lands, the diagram-surfacing path is exercised only by the fixture/manual files.
