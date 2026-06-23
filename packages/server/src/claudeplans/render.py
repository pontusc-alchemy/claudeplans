"""Markdown -> sanitized-HTML: the single trusted rendering boundary.

Stored section/description bodies are author markdown that may embed raw HTML, so
the rendered output is UNTRUSTED until sanitized. Every path that turns stored
text into HTML for a browser goes through here: convert with a fixed extension set,
then `nh3.clean` against an EXPLICIT allowlist. Anything outside the allowlist
(scripts, event handlers, `javascript:` URLs, style/iframe) is dropped — the
template layer can therefore mark this output `| safe` and nothing else.

Kept PURE on purpose (markdown + nh3 + nothing else): no cache, no SSE, no FastAPI
imports, so a deferred Slack export can reuse the exact same sanitizer without
dragging in the web stack. A fresh `markdown.Markdown` is built per call because
Markdown instances are stateful and not reentrant; a fresh one keeps the function
pure and thread-safe.
"""

from typing import Final

import markdown
import nh3

# Material's documented core set, trimmed to what is both safe and useful. No
# `md_in_html` or any raw-HTML-enabling extension: raw HTML must reach nh3 as text,
# not as a parser-blessed passthrough. `attr_list` is deliberately EXCLUDED: its
# `{#id .class key=val}` syntax lets an author inject ids/classes/attributes into the
# rendered body, which would spoof the template's trusted morph-target ids (e.g.
# `#doc-status`) and corrupt idiomorph's id-matching.
_EXTENSIONS: Final = [
    "tables",
    "fenced_code",
    "admonition",
    "toc",
    "def_list",
    "pymdownx.betterem",
    "pymdownx.caret",
    "pymdownx.tilde",
    "pymdownx.tasklist",
    "pymdownx.superfences",
    "pymdownx.highlight",
    "pymdownx.inlinehilite",
    "pymdownx.smartsymbols",
    "pymdownx.details",
]

_EXTENSION_CONFIGS: Final = {
    "pymdownx.tasklist": {"custom_checkbox": True},
    "pymdownx.highlight": {"anchor_linenums": False},
}

# The sanitizer allowlist IS the security boundary. nh3 already strips `on*`
# handlers, `<script>`/`<style>`, and `javascript:` URLs by default; this explicit
# set is belt-and-suspenders and the single place to audit what HTML can survive.
# `input`/`label` are present only so pymdownx.tasklist's disabled checkbox glyph
# (`<input type=checkbox disabled checked>`) renders — see the attribute allowlist,
# which permits no interactive attributes on them.
_ALLOWED_TAGS: Final[set[str]] = {
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    "blockquote",
    "pre",
    "code",
    "em",
    "strong",
    "del",
    "ins",
    "sub",
    "sup",
    "mark",
    "a",
    "span",
    "div",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "caption",
    "img",
    "details",
    "summary",
    "input",
    "label",
}

# `id` is intentionally absent from "*": rendered body content must carry NO id, so
# even an extension's auto-generated heading id (toc) can't collide with the
# template's trusted morph-target ids. `class` is kept — the admonition/highlight/
# details/tasklist extensions emit presentational classes — and with attr_list
# excluded an author can no longer inject one.
_ALLOWED_ATTRS: Final[dict[str, set[str]]] = {
    "*": {"class"},
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "td": {"align"},
    "th": {"align"},
    "ol": {"start"},
    # Disabled-only: the tasklist checkbox is presentational, never interactive.
    "input": {"type", "checked", "disabled"},
}


def render_markdown(text: str) -> str:
    """Convert markdown `text` to sanitized HTML safe to inject into the page."""
    md = markdown.Markdown(extensions=_EXTENSIONS, extension_configs=_EXTENSION_CONFIGS)
    html = md.convert(text)
    return nh3.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)
