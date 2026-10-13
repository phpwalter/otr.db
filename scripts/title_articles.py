"""Shared article-insensitive OTR title normalization.

Canonical display moves a leading The/A/An to a terminal bracket.
Matching/sorting ignores either leading or terminal bracket article.
"""
from __future__ import annotations
import re
LEADING = re.compile(r"^\s*(the|an|a)\s+(.+?)\s*$", re.I | re.S)
TRAILING = re.compile(r"\s+\[(the|an|a)\]$", re.I)
ARTICLE = {"the":"The", "a":"A", "an":"An"}

def canonical_title(value: str | None) -> str | None:
    if value is None:
        return None
    match = LEADING.match(value)
    if not match:
        return value
    return f"{match.group(2)} [{ARTICLE[match.group(1).lower()]}]"

def title_match_key(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    lead = LEADING.match(value)
    if lead:
        value = lead.group(2)
    value = TRAILING.sub("", value)
    return re.sub(r"\s+", " ", value).casefold().strip()

def title_sort_key(value: str | None) -> str | None:
    return title_match_key(value)
