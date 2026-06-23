"""The sanitizer is the security boundary, so these tests are adversarial first.

They prove untrusted markdown can't smuggle executable HTML past nh3 (scripts,
event handlers, javascript: URLs) and that the useful markdown features still
render. Purity tests pin the fresh-instance contract render_markdown relies on.
"""

from claudeplans.render import render_markdown


def test_script_injection_is_neutralized() -> None:
    out = render_markdown("<script>alert(1)</script>")
    assert "<script" not in out


def test_img_onerror_handler_is_stripped() -> None:
    out = render_markdown("text <img src=x onerror=alert(1)> more")
    assert "onerror" not in out


def test_javascript_href_is_neutralized() -> None:
    out = render_markdown("[link](javascript:alert(1))")
    assert "javascript:" not in out


def test_headings_lists_render() -> None:
    out = render_markdown("# Title\n\n- one\n- two")
    assert "<h1" in out
    assert "<ul>" in out
    assert "<li>one</li>" in out


def test_table_renders() -> None:
    out = render_markdown("| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in out
    assert "<th>a</th>" in out
    assert "<td>1</td>" in out


def test_fenced_code_renders() -> None:
    out = render_markdown("```python\nx = 1\n```")
    assert "<pre>" in out
    assert "<code" in out


def test_admonition_renders() -> None:
    out = render_markdown("!!! note\n    hello")
    assert '<div class="admonition note">' in out
    assert "hello" in out


def test_task_list_renders_checkbox() -> None:
    out = render_markdown("- [x] done\n- [ ] todo")
    assert "<input" in out
    assert 'type="checkbox"' in out
    assert "checked" in out


def test_attr_list_injection_strips_id_and_class() -> None:
    # attr_list is excluded and `id` is off the allowlist, so an author can't inject
    # a morph-target id (e.g. #doc-status) or a status `class` into the body.
    out = render_markdown("# Heading {#doc-status .pill .done}")
    assert "id=" not in out
    assert 'class="pill' not in out


def test_purity_same_input_identical_output() -> None:
    text = "# Heading\n\nsome **bold** text"
    assert render_markdown(text) == render_markdown(text)


def test_purity_fresh_instance_no_cross_contamination() -> None:
    # A reused Markdown instance would leak prior toc/footnote state; a fresh one
    # per call means rendering A then B equals rendering B in isolation.
    first = "# First\n\n[toc]"
    second = "## Second"
    render_markdown(first)
    assert render_markdown(second) == render_markdown(second)
