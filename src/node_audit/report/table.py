"""控制台表格渲染（纯标准库，处理中日韩字符的显示宽度对齐）。"""
from __future__ import annotations

import unicodedata


def dwidth(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def pad(s, width: int) -> str:
    s = str(s)
    if dwidth(s) > width:
        while s and dwidth(s) > width - 1:
            s = s[:-1]
        s += "…"
    return s + " " * max(0, width - dwidth(s))


def render(rows: list, headers: list) -> str:
    widths = []
    for i, h in enumerate(headers):
        w = dwidth(h)
        for r in rows:
            w = max(w, dwidth(r[i]))
        widths.append(w)
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [line, "| " + " | ".join(pad(h, w) for h, w in zip(headers, widths)) + " |", line]
    for r in rows:
        out.append("| " + " | ".join(pad(c, w) for c, w in zip(r, widths)) + " |")
    out.append(line)
    return "\n".join(out)
