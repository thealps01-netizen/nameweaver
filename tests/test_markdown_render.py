"""Tests for the chat Markdown helpers (pure, no Qt)."""

from widgets.markdown_render import md_to_html, split_segments


def test_split_text_code_text():
    segs = split_segments("hi\n```py\nprint(1)\n```\nbye")
    assert segs[0][0] == "text"
    assert segs[1] == ("code", "print(1)\n", "py")
    assert segs[2][0] == "text"


def test_split_open_fence_during_streaming():
    segs = split_segments("start\n```js\nlet x = 1")
    assert segs[-1][0] == "code" and segs[-1][2] == "js"
    assert "let x = 1" in segs[-1][1]


def test_md_table():
    h = md_to_html("| A | B |\n|---|---|\n| 1 | 2 |")
    assert "<table" in h and "<th>A</th>" in h and "<td>2</td>" in h


def test_md_lists_and_heading_and_inline():
    h = md_to_html("# Title\n- one\n- two\n**bold** and [x](https://a.b)")
    assert "font-weight:700" in h
    assert "<li>one</li>" in h and "<li>two</li>" in h
    assert "<b>bold</b>" in h
    assert '<a href="https://a.b">x</a>' in h


def test_md_ordered_list_and_blockquote():
    assert "<ol>" in md_to_html("1. a\n2. b")
    assert "<blockquote" in md_to_html("> quoted")


def test_md_escapes_html():
    h = md_to_html("<script>alert(1)</script>")
    assert "<script>" not in h and "&lt;script&gt;" in h
