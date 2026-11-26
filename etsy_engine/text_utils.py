"""Text helpers: keyword extraction and Etsy/Pinterest field rules."""
from __future__ import annotations

import html
import re
from collections import Counter

STOPWORDS = set("""
a an and are as at be by for from has have i in is it its of on or our that the this to was were will with
you your my me we us gift gifts set new free shipping item items etsy shop handmade made custom personalized
""".split()) - {"gift", "gifts", "handmade", "custom", "personalized"}
# keep "gift", "handmade", "custom", "personalized": strong buyer-intent words on Etsy
STOPWORDS |= {"x", "pcs", "piece", "pieces", "size", "color", "colour"}

TAG_MAX = 20
TAGS_PER_LISTING = 13
TITLE_MAX = 140
_TAG_ALLOWED = re.compile(r"[^\w\s\-'™©®]", re.UNICODE)


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'\-]*", (text or "").lower()) if len(w) > 1]


def keywords(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS and not w.isdigit()]


def ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def title_phrases(title: str) -> list[str]:
    """Etsy titles are usually 'phrase, phrase | phrase' - split on separators."""
    parts = re.split(r"[,|\-–—:/]+", title or "")
    return [p.strip() for p in parts if p.strip()]


def phrase_counts(titles: list[str], weights: list[float] | None = None) -> Counter:
    counts: Counter = Counter()
    for idx, title in enumerate(titles):
        w = weights[idx] if weights else 1.0
        for phrase in title_phrases(title):
            toks = keywords(phrase)
            seen = set()
            for n in (2, 3):
                for g in ngrams(toks, n):
                    if g not in seen:
                        counts[g] += w
                        seen.add(g)
    return counts


def clean_tag(tag: str) -> str:
    tag = _TAG_ALLOWED.sub(" ", (tag or "").lower())
    tag = re.sub(r"\s+", " ", tag).strip()
    if len(tag) <= TAG_MAX:
        return tag
    cut = tag[:TAG_MAX]
    return cut.rsplit(" ", 1)[0].strip() if " " in cut else cut


def clean_tags(tags: list[str], limit: int = TAGS_PER_LISTING) -> list[str]:
    out: list[str] = []
    for t in tags:
        c = clean_tag(t)
        if c and c not in out:
            out.append(c)
        if len(out) >= limit:
            break
    return out


def clean_title(title: str) -> str:
    """Etsy: max 140 chars; %, :, & and + may each appear only once."""
    title = re.sub(r"\s+", " ", (title or "").replace("\n", " ")).strip(" ,|-")
    for ch in "%:&+":
        first = title.find(ch)
        if first != -1:
            title = title[:first + 1] + title[first + 1:].replace(ch, " ")
    title = re.sub(r"\s+", " ", title)
    if len(title) > TITLE_MAX:
        cut = title[:TITLE_MAX]
        for sep in (" | ", ", ", " "):
            if sep in cut:
                cut = cut.rsplit(sep, 1)[0]
                break
        title = cut
    return title.strip(" ,|-")


def truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:-") + "…"


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_len].rstrip("-") or "item"


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def short_name(title: str, max_words: int = 6) -> str:
    """A human-friendly product name from a long SEO title."""
    first = title_phrases(title)[0] if title_phrases(title) else title
    toks = first.split()
    return " ".join(toks[:max_words]) if toks else title[:40]
