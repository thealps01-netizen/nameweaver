"""Pure Markdown helpers for the chat UI — no Qt, fully unit-testable.

Splits a message into text/code segments, and converts the text parts to safe
HTML (headings, bold/italic, inline code, links, lists, blockquotes, tables).
Code blocks are handled separately by the UI so each gets its own copy button.
"""

from __future__ import annotations

import html
import re

_FENCE = re.compile(r"```([a-zA-Z0-9_+-]*)\n?(.*?)```", re.DOTALL)
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def split_segments(text: str) -> list[tuple[str, str, str]]:
    """Split into ordered segments: ('text', content, '') or ('code', code, lang).

    An unterminated trailing fence (mid-stream) is treated as an open code block
    so the layout never breaks on incomplete markdown.
    """
    segments: list[tuple[str, str, str]] = []
    pos = 0
    for m in _FENCE.finditer(text):
        if m.start() > pos:
            segments.append(("text", text[pos:m.start()], ""))
        segments.append(("code", m.group(2), (m.group(1) or "").strip()))
        pos = m.end()
    rest = text[pos:]
    # Open (unterminated) fence during streaming.
    open_fence = rest.find("```")
    if open_fence != -1:
        if open_fence > 0:
            segments.append(("text", rest[:open_fence], ""))
        after = rest[open_fence + 3:]
        lang, _, code = after.partition("\n")
        segments.append(("code", code, lang.strip()))
    elif rest:
        segments.append(("text", rest, ""))
    return segments


def _inline(s: str) -> str:
    """Escape + inline formatting (code, bold, italic, links)."""
    stash: list[str] = []

    def _keep(frag: str) -> str:
        stash.append(frag)
        return f"\x00{len(stash) - 1}\x00"

    # inline code first (its contents must not be further formatted)
    s = re.sub(r"`([^`\n]+)`",
               lambda m: _keep(f"<code>{html.escape(m.group(1))}</code>"), s)
    s = html.escape(s)
    # links [text](url)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
               r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__([^_]+)__", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", s)
    for i, frag in enumerate(stash):
        s = s.replace(f"\x00{i}\x00", frag)
    return s


def _table_html(rows: list[str]) -> str:
    def cells(line: str) -> list[str]:
        line = line.strip().strip("|")
        return [c.strip() for c in line.split("|")]

    header = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ['<table border="1" cellspacing="0" cellpadding="4" style="border-collapse:collapse;">']
    out.append("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in header) + "</tr>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
    out.append("</table>")
    return "".join(out)


def md_to_html(text: str) -> str:
    """Convert a text segment (no fenced code) to safe rich HTML."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # Table: a header row followed by a |---|---| separator.
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            block = [line, lines[i + 1]]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                block.append(lines[i])
                i += 1
            out.append(_table_html(block))
            continue

        # Heading
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            size = max(12, 20 - (len(m.group(1)) - 1) * 2)
            out.append(f'<div style="font-weight:700; font-size:{size}px;">'
                       f'{_inline(m.group(2))}</div>')
            i += 1
            continue

        # Blockquote
        if line.lstrip().startswith(">"):
            quote = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote.append(_inline(lines[i].lstrip()[1:].lstrip()))
                i += 1
            out.append('<blockquote style="border-left:3px solid #8888;'
                       ' margin:4px 0; padding-left:8px;">'
                       + "<br>".join(quote) + "</blockquote>")
            continue

        # Unordered list
        if re.match(r"^\s*[-*+]\s+", line):
            items = []
            while i < n and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(f"<li>{_inline(re.sub(r'^\s*[-*+]\s+', '', lines[i]))}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        # Ordered list
        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(f"<li>{_inline(re.sub(r'^\s*\d+\.\s+', '', lines[i]))}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue

        # Blank line → spacing
        if not line.strip():
            i += 1
            continue

        # Paragraph: gather consecutive plain lines.
        para = []
        while i < n and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|>|\s*[-*+]\s|\s*\d+\.\s)", lines[i]
        ) and not ("|" in lines[i] and i + 1 < n and _TABLE_SEP.match(lines[i + 1])):
            para.append(_inline(lines[i]))
            i += 1
        out.append("<div>" + "<br>".join(para) + "</div>")

    return "".join(out)
