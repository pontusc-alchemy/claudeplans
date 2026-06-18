"""MkDocs hook: inject a phase tracker at the top of `type: plan` pages.

The tracker is rendered from plan-doc's `phase_report` so phase state has a
single source of truth. Source markdown never contains the tracker, so the
injection is idempotent. Any failure (import, parse) degrades to the unchanged
body rather than breaking the build.
"""

import html
import importlib.util
import pathlib
from importlib.machinery import SourceFileLoader

# Locate plan-doc in both layouts: deployed render dir (sibling of this hook,
# copied there by `make config`) and the source plugin (../scripts/plan-doc).
# plan-doc is extensionless, so give importlib an explicit source loader rather
# than relying on extension-based loader inference (which yields a None spec).
# Any failure here leaves plan_doc=None and the hook degrades to a no-op.
try:
  _here = pathlib.Path(__file__).resolve().parent
  _pd_path = next(
    (c for c in (_here / "plan-doc", _here.parent / "scripts" / "plan-doc") if c.is_file()),
    None,
  )
  if _pd_path is None:
    plan_doc = None
  else:
    _spec = importlib.util.spec_from_file_location(
      "plan_doc", _pd_path, loader=SourceFileLoader("plan_doc", str(_pd_path))
    )
    plan_doc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(plan_doc)
except Exception:
  plan_doc = None


def _render_tracker(report):
  tally = report["tally"]
  done = tally["done"]
  total = tally["total"]
  blocked = tally["blocked"]
  pct = int(round(100 * done / total))  # total >= 1 guaranteed by caller

  summary = f"{done} of {total} phases done"
  if blocked > 0:
    summary += f' <span class="blocked">· {blocked} blocked</span>'

  parts = [
    '<div class="phase-tracker" markdown="0">',
    '  <div class="phase-progress">',
    f'    <div class="phase-progress-fill" style="width: {pct}%"></div>',
    "  </div>",
    f'  <p class="phase-summary">{summary}</p>',
    "  <ol>",
  ]
  for p in report["phases"]:
    name = html.escape(p["name"], quote=False)
    status = p["status"] or "todo"
    item = (
      f'    <li>Phase {p["ordinal"]} — {name} '
      f'<span class="pill {status}">{status}</span>'
    )
    # `note` is already-escaped on disk (came through parse_phases verbatim).
    if p["note"]:
      item += f' <span class="note">{p["note"]}</span>'
    item += "</li>"
    parts.append(item)
  parts.append("  </ol>")
  parts.append("</div>")
  return "\n".join(parts)


def on_page_markdown(markdown, page, config, files):
  if page.meta.get("type") != "plan":
    return markdown
  try:
    report = plan_doc.phase_report(markdown)
    if report["tally"]["total"] == 0:
      return markdown
    return _render_tracker(report) + "\n\n" + markdown
  except Exception:
    return markdown
