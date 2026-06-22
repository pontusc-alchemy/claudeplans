"""Rendering: the pure markdown->sanitized-HTML pipeline plus the per-fragment cache.

The render entrypoint is pure (no cache/SSE/app state) so it is reused unchanged
by the deferred Slack export. The cache and live view land in the rendering phase.
"""
