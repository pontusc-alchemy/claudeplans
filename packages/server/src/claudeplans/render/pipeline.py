"""The render entrypoint: markdown -> sanitized HTML. PURE by design.

No cache, no SSE, no app state — text in, safe HTML out. Agent markdown is
UNTRUSTED: the real pipeline (rendering phase) runs Python-Markdown +
pymdown-extensions with raw-HTML passthrough disabled, then sanitizes the output
with nh3. This skeleton fixes the signature; the rendering phase fills it in.
"""


def render_markdown(text: str) -> str:
    """Render untrusted markdown `text` to sanitized HTML. (Rendering phase.)"""
    raise NotImplementedError("render pipeline lands in the rendering phase")
