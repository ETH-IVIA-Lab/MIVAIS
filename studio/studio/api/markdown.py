"""A tiny markdown-subset renderer used by JSON API routes that need to turn
study-authored prose (consent text, task prompts) into HTML server-side.
"""
from __future__ import annotations

import re


def render_markdown(text: str) -> str:
    """Tiny markdown subset: headings (#, ##), bold **x**, paragraphs, line breaks.

    We deliberately avoid pulling in a markdown library; consent and prompts in
    studies are short and authors can include literal HTML if they need more.
    """
    if not text:
        return ""
    lines = text.split("\n")
    out: list[str] = []
    para_lines: list[str] = []

    def flush_para() -> None:
        if not para_lines:
            return
        formatted = _inline("\n".join(para_lines))
        out.append("<p>" + formatted.replace("\n", "<br>\n") + "</p>")
        para_lines.clear()

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            continue
        if line.startswith("## "):
            flush_para()
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            flush_para()
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        else:
            para_lines.append(line)
    flush_para()
    return "\n".join(out)


def _inline(text: str) -> str:
    text = _escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text, flags=re.DOTALL)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text, flags=re.DOTALL)
    return text


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
