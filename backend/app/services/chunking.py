from __future__ import annotations

import re


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def split_into_chunks(text: str, *, max_chars: int = 960, overlap: int = 160) -> list[str]:
    """Split long documents into overlapping windows, preferring paragraph boundaries."""
    text = normalize_whitespace(text)
    if not text:
        return []

    paragraphs = [normalize_whitespace(p) for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    merged: list[str] = []
    buf = ""
    for p in paragraphs:
        if not buf:
            buf = p
        elif len(buf) + 1 + len(p) <= max_chars:
            buf = f"{buf}\n\n{p}"
        else:
            merged.append(buf)
            buf = p
    if buf:
        merged.append(buf)

    out: list[str] = []
    for block in merged:
        if len(block) <= max_chars:
            out.append(block)
            continue
        start = 0
        while start < len(block):
            end = min(len(block), start + max_chars)
            piece = block[start:end].strip()
            if piece:
                out.append(piece)
            if end >= len(block):
                break
            start = max(0, end - overlap)
    return out
