import datetime
import html
from pathlib import Path

import yaml

MARKER = "<!-- CARDS -->"

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


def _projects(docs_dir):
  root = Path(docs_dir)
  groups = {}
  # Project documents: projects/<project>/<slug>.md
  for path in root.glob("projects/*/*.md"):
    project = path.parent.name
    href = f"projects/{project}/{path.stem}.html"
    groups.setdefault(project, []).append(_card(path, href))
  # Stray docs (top-level except index.md, or directly under projects/) → "unfiled".
  for path in sorted(root.glob("*.md")):
    if path.name == "index.md":
      continue
    href = f"{path.stem}.html"
    groups.setdefault("unfiled", []).append(_card(path, href))
  for path in sorted(root.glob("projects/*.md")):
    href = f"projects/{path.stem}.html"
    groups.setdefault("unfiled", []).append(_card(path, href))
  for cards in groups.values():
    cards.sort(key=lambda c: c["title"])
    cards.sort(key=lambda c: c["date"], reverse=True)
  return groups


def _render_card(c):
  title = html.escape(c["title"])
  description = html.escape(c["description"])
  date = html.escape(c["date"])
  spans = []
  if c["type"]:
    spans.append(f'<span class="tag">{html.escape(str(c["type"]))}</span>')
  if c["status"]:
    status = str(c["status"])
    cls = STATUS_PILL.get(status, "gap")
    spans.append(f'<span class="pill {cls}">{html.escape(status)}</span>')
  if c["tag"]:
    spans.append(f'<span class="tag">{html.escape(str(c["tag"]))}</span>')
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


def _render(groups):
  # Project order: newest card date desc; "unfiled" always last.
  def project_key(name):
    if name == "unfiled":
      return (1, "")
    newest = max((c["date"] for c in groups[name]), default="")
    return (0, newest)

  ordered = sorted(groups, key=project_key)
  # Within the (0, …) bucket we want newest first; "unfiled" stays last.
  named = [n for n in ordered if n != "unfiled"]
  named.sort(key=lambda n: max((c["date"] for c in groups[n]), default=""), reverse=True)
  if "unfiled" in groups:
    named.append("unfiled")

  lines = []
  for name in named:
    lines.append(f'<h2 id="project-{html.escape(name)}">{html.escape(name)}</h2>')
    lines.append('<div class="grid cards">')
    lines.append("  <ul>")
    for c in groups[name]:
      lines.extend(_render_card(c))
    lines.append("  </ul>")
    lines.append("</div>")
  return "\n".join(lines)


def on_page_markdown(markdown, page, config, files):
  if page.file.src_uri != "index.md":
    return markdown
  if MARKER not in markdown:
    return markdown
  return markdown.replace(MARKER, _render(_projects(config["docs_dir"])))
