import datetime
import html
import re
from pathlib import Path

import yaml

MARKER = "<!-- CARDS -->"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)

STATUS_PILL = {
  "draft": "gap",
  "active": "partial",
  "done": "ok",
}


def _frontmatter(text):
  if not text.startswith("---"):
    return {}
  parts = text.split("---", 2)
  if len(parts) < 3:
    return {}
  try:
    data = yaml.safe_load(parts[1])
  except (yaml.YAMLError, ValueError):
    return {}
  return data if isinstance(data, dict) else {}


def _date(value, fallback):
  if isinstance(value, datetime.date):
    return value.isoformat()
  if isinstance(value, str) and value:
    return value
  return fallback


def _card(path, href):
  fm = _frontmatter(path.read_text(encoding="utf-8"))
  stem = path.stem
  mtime = datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()
  return {
    "href": href,
    "title": fm.get("title") or stem,
    "description": fm.get("description") or "",
    "type": fm.get("type"),
    "status": fm.get("status"),
    "tag": fm.get("tag"),
    "date": _date(fm.get("date"), mtime),
  }


def _html_card(path, href):
  # Standalone .html doc: title from <title>/<h1>, else humanized stem; mtime
  # as date. No frontmatter parsing for HTML, so status/type stay blank.
  text = path.read_text(encoding="utf-8", errors="ignore")
  match = _TITLE_RE.search(text) or _H1_RE.search(text)
  title = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip() if match else ""
  if not title:
    title = path.stem.replace("-", " ").replace("_", " ").title()
  mtime = datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()
  return {
    "href": href,
    "title": title,
    "description": "",
    "type": None,
    "status": None,
    "tag": None,
    "date": mtime,
  }


def _diagrams(diagrams_dir, href_prefix):
  # Diagram link-list entries from a diagrams/ dir: filename-stem label + href.
  items = []
  for path in sorted(diagrams_dir.glob("*.html")):
    items.append({"label": path.stem, "href": f"{href_prefix}{path.name}"})
  return items


def _sort_cards(cards):
  cards.sort(key=lambda c: c["title"])
  cards.sort(key=lambda c: c["date"], reverse=True)


def _new_project():
  return {"flat": [], "branches": {}, "diagrams": [], "branch_diagrams": {}}


def _projects(docs_dir):
  root = Path(docs_dir)
  projects = {}

  projects_dir = root / "projects"
  if projects_dir.is_dir():
    for project_dir in sorted(projects_dir.iterdir()):
      if not project_dir.is_dir():
        continue
      project = project_dir.name
      model = projects.setdefault(project, _new_project())
      # Flat docs: projects/<project>/<slug>.md
      for path in sorted(project_dir.glob("*.md")):
        href = f"projects/{project}/{path.stem}.html"
        model["flat"].append(_card(path, href))
      # Standalone .html docs sitting directly in the project dir (diagrams/
      # files live in a subdir, so this non-recursive glob skips them).
      for path in sorted(project_dir.glob("*.html")):
        href = f"projects/{project}/{path.name}"
        model["flat"].append(_html_card(path, href))
      # Subdirs: either the reserved diagrams/ bucket or a branch.
      for sub in sorted(project_dir.iterdir()):
        if not sub.is_dir():
          continue
        if sub.name == "diagrams":
          model["diagrams"] = _diagrams(sub, f"projects/{project}/diagrams/")
          continue
        branch = sub.name
        cards = [
          _card(path, f"projects/{project}/{branch}/{path.stem}.html")
          for path in sorted(sub.glob("*.md"))
        ]
        cards += [
          _html_card(path, f"projects/{project}/{branch}/{path.name}")
          for path in sorted(sub.glob("*.html"))
        ]
        # A subdir with no .md docs yields no branch heading; its diagrams are
        # still surfaced (a branch may exist purely to hold generated diagrams).
        diagrams = _diagrams(sub / "diagrams", f"projects/{project}/{branch}/diagrams/") if (sub / "diagrams").is_dir() else []
        if cards:
          model["branches"][branch] = cards
        if diagrams:
          model["branch_diagrams"][branch] = diagrams

  # Stray docs (top-level except index.md, or directly under projects/) → "unfiled".
  unfiled = projects.setdefault("unfiled", _new_project())
  for path in sorted(root.glob("*.md")):
    if path.name == "index.md":
      continue
    unfiled["flat"].append(_card(path, f"{path.stem}.html"))
  for path in sorted(root.glob("*.html")):
    if path.name == "index.html":
      continue
    unfiled["flat"].append(_html_card(path, path.name))
  for path in sorted(root.glob("projects/*.md")):
    unfiled["flat"].append(_card(path, f"projects/{path.stem}.html"))
  for path in sorted(root.glob("projects/*.html")):
    unfiled["flat"].append(_html_card(path, f"projects/{path.name}"))
  if not (unfiled["flat"] or unfiled["branches"] or unfiled["diagrams"] or unfiled["branch_diagrams"]):
    del projects["unfiled"]

  for model in projects.values():
    _sort_cards(model["flat"])
    for cards in model["branches"].values():
      _sort_cards(cards)
  return projects


def _render_card(c):
  title = html.escape(c["title"])
  description = html.escape(c["description"])
  date = html.escape(c["date"])
  spans = []
  if c["status"]:
    status = str(c["status"])
    cls = STATUS_PILL.get(status, "gap")
    spans.append(f'<span class="pill {cls}">{html.escape(status)}</span>')
  if c["type"]:
    spans.append(f'<span class="muted">{html.escape(str(c["type"]))} · {date}</span>')
  else:
    spans.append(f'<span class="muted">{date}</span>')
  meta = " ".join(spans)
  return [
    "    <li>",
    f'      <p><strong><a href="{c["href"]}">{title}</a></strong></p>',
    "      <hr />",
    f"      <p>{description}</p>",
    f"      <p>{meta}</p>",
    "    </li>",
  ]


def _render_cards(cards):
  lines = ['<div class="grid cards">', "  <ul>"]
  for c in cards:
    lines.extend(_render_card(c))
  lines.append("  </ul>")
  lines.append("</div>")
  return lines


def _render_diagrams(items):
  # Compact link-list reusing existing `muted` styling (no new CSS).
  links = " · ".join(
    f'<a href="{html.escape(d["href"])}">{html.escape(d["label"])}</a>' for d in items
  )
  return [f'<p class="muted">Diagrams: {links}</p>']


def _project_newest(model):
  dates = [c["date"] for c in model["flat"]]
  for cards in model["branches"].values():
    dates.extend(c["date"] for c in cards)
  return max(dates, default="")


def _render(projects):
  # Project order: newest doc date desc; "unfiled" always last.
  named = [n for n in projects if n != "unfiled"]
  named.sort(key=lambda n: _project_newest(projects[n]), reverse=True)
  if "unfiled" in projects:
    named.append("unfiled")

  lines = []
  for name in named:
    model = projects[name]
    # A project renders only if it has any content (flat docs, project-level
    # diagrams, or any branch with docs or diagrams) — never an empty <h2>.
    branches = set(model["branches"]) | set(model["branch_diagrams"])
    if not (model["flat"] or model["diagrams"] or branches):
      continue
    pid = html.escape(name)
    lines.append(f'<h2 id="project-{pid}">{html.escape(name)}</h2>')
    if model["flat"]:
      lines.extend(_render_cards(model["flat"]))
    if model["diagrams"]:
      lines.extend(_render_diagrams(model["diagrams"]))
    # Branches: newest doc date desc, then name. A diagram-only branch has no
    # dated docs ("") so it sorts last.
    def branch_key(b):
      newest = max((c["date"] for c in model["branches"].get(b, ())), default="")
      return (newest, b)

    for branch in sorted(branches, key=branch_key, reverse=True):
      bid = html.escape(branch)
      lines.append(f'<h3 id="project-{pid}-{bid}">{html.escape(branch)}</h3>')
      if branch in model["branches"]:
        lines.extend(_render_cards(model["branches"][branch]))
      if branch in model["branch_diagrams"]:
        lines.extend(_render_diagrams(model["branch_diagrams"][branch]))
  return "\n".join(lines)


def on_page_markdown(markdown, page, config, files):
  if page.file.src_uri != "index.md":
    return markdown
  if MARKER not in markdown:
    return markdown
  return markdown.replace(MARKER, _render(_projects(config["docs_dir"])))
