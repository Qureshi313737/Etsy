"""Marketing copy: SEO title/tags/description, Pin copy and social captions.

Uses a free LLM when configured; always has a rule-based engine (driven by real competitor
data) as fallback, so copy is generated even with zero API keys.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date

from .analysis import APPEAL, CONVERSION, TRAFFIC, ListingMetrics
from .text_utils import (TAGS_PER_LISTING, clean_tag, clean_tags, clean_title, keywords, short_name,
                         title_phrases, truncate)

log = logging.getLogger(__name__)

HEADLINE_STYLES = ["keyword", "gift", "question", "seasonal", "benefit", "price"]

SYSTEM_PROMPT = """You are a senior Etsy SEO specialist and Pinterest marketer.
You write copy that ranks in Etsy search and gets clicks on Pinterest.
Rules:
- Etsy title: max 140 characters, most important buyer search phrase first, natural (no keyword stuffing,
  no ALL CAPS), separate phrases with commas. Characters %, :, &, + at most once each.
- Etsy tags: exactly 13, each max 20 characters, mostly 2-3 word long-tail phrases buyers actually type,
  no repeats of the same phrase, letters/numbers/spaces only.
- Never invent facts (materials, sizes, claims) that are not in the listing data.
- Pinterest: titles max 100 chars, descriptions 2-3 sentences, keyword-rich, end with a soft call to action.
Respond with a single JSON object only."""


def season_context(d: date) -> dict:
    m, day = d.month, d.day
    if m == 11 and day <= 30 or m == 12 and day <= 24:
        return {"occasion": "Christmas", "season": "Holiday", "hook": "Holiday gift guide pick"}
    if m == 12 or m == 1 and day <= 15:
        return {"occasion": "New Year", "season": "Winter", "hook": "Fresh start favourite"}
    if m == 1 or m == 2 and day <= 14:
        return {"occasion": "Valentine's Day", "season": "Valentine's", "hook": "Valentine's gift idea"}
    if m in (2, 3):
        return {"occasion": "Easter", "season": "Spring", "hook": "Spring must-have"}
    if m == 4 or m == 5 and day <= 12:
        return {"occasion": "Mother's Day", "season": "Spring", "hook": "Gift for mom"}
    if m == 5 or m == 6 and day <= 21:
        return {"occasion": "Father's Day", "season": "Summer", "hook": "Gift for dad"}
    if m in (6, 7, 8):
        return {"occasion": "birthday", "season": "Summer", "hook": "Summer favourite"}
    if m == 9 or m == 10:
        return {"occasion": "Halloween", "season": "Fall", "hook": "Cozy fall pick"}
    return {"occasion": "birthday", "season": "Fall", "hook": "Gift idea"}


def _title_case(s: str) -> str:
    small = {"a", "an", "and", "for", "of", "the", "to", "with", "in", "on", "or"}
    return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(s.split()))


DIGITAL_WORDS = {"template", "templates", "digital", "download", "downloadable", "printable", "printables",
                 "html", "website", "svg", "png", "pdf", "canva", "app", "font", "fonts", "ebook", "planner",
                 "spreadsheet", "notion", "wordpress", "shopify", "figma", "preset", "presets", "clipart",
                 "procreate", "mockup", "ui", "kit", "code", "theme", "plugin", "editable"}


def is_digital(listing: dict) -> bool:
    """Digital downloads need different copy (instant download, no shipping, no 'handmade')."""
    text = set(keywords(listing.get("title", "") + " " + " ".join(listing.get("tags", []))))
    return len(text & DIGITAL_WORDS) >= 2 or bool({"digital", "download", "printable"} & text)


def primary_phrase(listing: dict, insight: dict | None) -> str:
    # the seller's own leading phrase is the most reliable description of the product
    phrases = title_phrases(listing.get("title", ""))
    own_lead = keywords(phrases[0])[:4] if phrases else []
    if len(own_lead) >= 2:
        return " ".join(own_lead)
    own_words = set(keywords(listing.get("title", "")) + keywords(" ".join(listing.get("tags", []))))
    for phrase, _ in (insight or {}).get("top_phrases", []):
        if len(set(phrase.split()) & own_words) >= 2 or (len(phrase.split()) == 2 and set(phrase.split()) <= own_words):
            return phrase
    phrases = title_phrases(listing.get("title", ""))
    return " ".join(keywords(phrases[0])[:4]) if phrases else listing.get("title", "")[:40]


# ---------------------------------------------------------------------------
# rule-based engine
# ---------------------------------------------------------------------------
def rule_tags(listing: dict, insight: dict | None) -> list[str]:
    ours = [clean_tag(t) for t in listing.get("tags", []) if clean_tag(t)]
    top = [t for t, _ in (insight or {}).get("top_tags", [])]
    own_words = set(keywords(listing.get("title", "")) + keywords(" ".join(ours)))
    relevant_top = [t for t in top if set(keywords(t)) & own_words]
    keep = [t for t in ours if t in top]                       # proven by competitors
    add = [t for t in relevant_top if t not in keep and " " in t]  # long-tail winners we miss
    rest = [t for t in ours if t not in keep and " " in t]
    phrases = [clean_tag(p) for p, _ in (insight or {}).get("top_phrases", []) if set(p.split()) & own_words]
    singles = [t for t in ours if " " not in t]
    # still short of 13? competitors for *our* search terms use these - they are on-topic buyer phrases
    market_multi = [t for t in top if " " in t]
    return clean_tags(keep + add + rest + phrases + singles + relevant_top + market_multi + top, TAGS_PER_LISTING)


def rule_title(listing: dict, insight: dict | None, tags: list[str]) -> str:
    primary = _title_case(primary_phrase(listing, insight))
    parts = [primary]
    used = set(primary.lower().split())
    candidates = title_phrases(listing.get("title", "")) + [_title_case(t) for t in tags]
    # pass 1: only phrases that bring mostly new words (avoids keyword stuffing);
    # pass 2: if the title is still short, allow phrases sharing half their words
    for max_overlap in (0.49, 0.5):
        for p in candidates:
            p = p.strip()
            p_words = set(p.lower().split())
            if not p_words or p in parts or len(p_words & used) / len(p_words) > max_overlap:
                continue
            if len(", ".join(parts + [p])) > 140:
                continue
            parts.append(p)
            used |= p_words
        if len(", ".join(parts)) >= 110:
            break
    return clean_title(", ".join(parts))


def rule_description_intro(listing: dict, primary: str, season: dict) -> str:
    name = short_name(listing.get("title", ""))
    if is_digital(listing):
        return (f"Looking for a {primary.lower()}? This {name} is an instant digital download - "
                f"ready to use, easy to customise and fully yours after purchase. "
                f"No shipping and no waiting: get the files right after checkout.")
    mats = listing.get("materials") or []
    mat_txt = f" Made with {', '.join(mats[:3])}." if mats else ""
    return (f"Searching for the perfect {primary.lower()}? Meet our {name.lower()}: a thoughtful "
            f"{season['occasion']} gift and an everyday favourite.{mat_txt} "
            f"Add it to your cart today - it ships with care.")


def rule_pins(listing: dict, primary: str, season: dict, n: int, symbol: str, styles: list[str]) -> list[dict]:
    name = short_name(listing.get("title", ""))
    price = float(listing.get("price") or 0)
    nice_price = math.ceil(price / 5) * 5 if price else 0
    kw = _title_case(primary)
    if is_digital(listing):
        headlines = {
            "keyword": (kw, "Instant Download"),
            "gift": ("Launch Faster With This Template", name),
            "question": (f"Need a {kw}?", "Ready to use today"),
            "seasonal": (f"{season['season']} Launch Ready", name),
            "benefit": ("Save Hours of Work", name),
            "price": (f"Only {symbol}{price:.0f} - Instant Access" if price else "Instant Access", name),
        }
        hook = "instant digital download"
    else:
        headlines = {}
        hook = season["hook"].lower()
    headlines = headlines or {
        "keyword": (kw, name),
        "gift": (f"The Perfect {season['occasion']} Gift", name),
        "question": (f"Still Looking for the Perfect {kw}?", "You'll love this one"),
        "seasonal": (f"{season['season']} Must-Have", name),
        "benefit": (f"Handmade {name}", "Made to be loved"),
        "price": (f"Gift Under {symbol}{nice_price}" if nice_price else f"Shop {kw}", name),
    }
    tags = listing.get("tags", [])
    out = []
    for i in range(n):
        style = styles[i % len(styles)]
        h, sub = headlines.get(style, headlines["keyword"])
        if sub.lower() in h.lower() or h.lower() in sub.lower():
            sub = "Instant Download" if is_digital(listing) else season["hook"]
        title = truncate(f"{kw} | {h}" if style != "keyword" else f"{kw} - {name}", 100)
        desc = truncate(
            f"{h}. {name} - {hook}. Perfect for anyone who loves "
            f"{', '.join(tags[:3]) or primary}. Tap to see all photos and details on Etsy.", 500)
        out.append({
            "style": style, "headline": truncate(h, 48), "subline": truncate(sub, 40),
            "title": title, "description": desc,
            "alt_text": truncate(f"{name}: {listing.get('title', '')}", 500),
        })
    return out


def rule_social(listing: dict, primary: str, season: dict) -> dict:
    name = short_name(listing.get("title", ""))
    tags = [t.replace(" ", "") for t in listing.get("tags", [])[:6]]
    if is_digital(listing):
        hashtags = " ".join(f"#{t}" for t in tags) + " #etsy #digitaldownload #template #smallbusiness"
        return {
            "instagram": f"🚀 New: {name} - instant download, ready to customise. Link in bio! {hashtags}",
            "facebook": f"Save hours of work: {name} is ready to use today. Instant download on Etsy 👉",
            "reddit_title": f"I built a {primary.lower()} - would love feedback on the design",
            "tiktok_hook": f"POV: you launch your site in an afternoon with this {primary.lower()} ⚡",
            "hashtags": hashtags,
        }
    hashtags = " ".join(f"#{t}" for t in tags) + " #etsy #etsyfinds #handmade #shopsmall"
    return {
        "instagram": f"{season['hook']} ✨ Meet our {name}. Link in bio to shop on Etsy! {hashtags}",
        "facebook": f"New favourite alert: {name}. A thoughtful {season['occasion']} gift - shop it on Etsy 👉",
        "reddit_title": f"Handmade {primary.lower()} I've been working on - feedback welcome!",
        "tiktok_hook": f"POV: you found the perfect {season['occasion']} gift ({name}) 🎁",
        "hashtags": hashtags,
    }


def conversion_tips(m: ListingMetrics, insight: dict | None) -> list[str]:
    tips: list[str] = []
    if is_digital(m.listing):
        if m.diagnosis in (CONVERSION, APPEAL):
            tips += [
                "Pehli photo mein laptop/phone mockup par template dikhao - buyer ko turant samajh aaye kya mil raha hai.",
                "Ek live demo link ya 15-sec screen-recording video add karo (animated templates ke liye bahut zaroori).",
                "Description mein saaf likho: kya files milengi, kaise edit hoga, kaunse tools chahiye.",
                "Etsy Marketing > Sales and discounts se 15-20% ka 3-day sale chalao.",
            ]
        tips += m.quality_issues[:4]
        return tips
    if m.diagnosis == CONVERSION:
        tips += [
            "Pehli 3 photos mein product ka size/scale dikhao (haath mein ya room mein).",
            "Description ki pehli 2 lines mein buyer ka sabse bada sawal answer karo (size, delivery time).",
            "Etsy Marketing > Sales and discounts se 10-15% ka 3-day sale chalao (favoriters ko notification jaata hai).",
            "Free shipping (US $35+ threshold) on karo - Etsy search mein boost milta hai.",
        ]
    if m.diagnosis == APPEAL:
        tips += [
            "Thumbnail (pehli photo) badlo: plain bright background, product centre mein, crop square-safe.",
            "Pinterest par sabse zyada saves wali design ki photo ko Etsy ki pehli photo banao.",
        ]
    if m.diagnosis == TRAFFIC:
        tips += [
            "Naye title/tags apply karne ke baad 2-3 hafte ruko - Etsy ranking settle hone deti hai.",
            "Listing ko 'renew' karna paid hai ($0.20) - sirf tab karo jab SEO update ke baad bhi views na aaye.",
        ]
    tips += m.quality_issues[:4]
    return tips


# ---------------------------------------------------------------------------
# LLM engine
# ---------------------------------------------------------------------------
def _llm_prompt(listing: dict, m: ListingMetrics, insight: dict | None, season: dict, n_pins: int,
                styles: list[str], symbol: str) -> str:
    data = {
        "listing": {
            "title": listing.get("title"), "tags": listing.get("tags"),
            "materials": listing.get("materials"), "price": f"{symbol}{listing.get('price')}",
            "description_start": truncate(listing.get("description", ""), 700),
        },
        "performance": {"diagnosis": m.diagnosis, "reasons": m.reasons},
        "market": {
            "competitor_top_tags": [t for t, _ in (insight or {}).get("top_tags", [])[:25]],
            "competitor_title_phrases": [p for p, _ in (insight or {}).get("top_phrases", [])[:12]],
            "trending_on_pinterest": (insight or {}).get("related_trends", []),
            "price_range": (insight or {}).get("price"),
        },
        "season": season,
        "product_type": "digital download (no shipping, not handmade - do not mention shipping, "
                        "gifts or handmade unless the listing says so)" if is_digital(listing) else "physical item",
    }
    return (
        "Data:\n" + json.dumps(data, ensure_ascii=False, indent=1) +
        f"\n\nCreate JSON with keys:\n"
        f'"seo": {{"title": str, "tags": [13 str], "description_intro": str (2-3 sentences, first 160 chars '
        f'contain the main search phrase), "rationale": [str]}},\n'
        f'"pins": list of {n_pins} objects {{"style": one of {styles}, "headline": str (max 6 words, for the '
        f'image), "subline": str (max 6 words), "title": str, "description": str, "alt_text": str}} - '
        f"use the styles in this order: {[styles[i % len(styles)] for i in range(n_pins)]},\n"
        f'"social": {{"instagram": str, "facebook": str, "reddit_title": str, "tiktok_hook": str, '
        f'"hashtags": str}},\n"conversion_tips": [3-5 specific str]'
    )


def _validate(pack: dict, fallback: dict, n_pins: int) -> dict:
    seo = pack.get("seo") or {}
    out_seo = dict(fallback["seo"])
    if isinstance(seo.get("title"), str) and len(seo["title"]) > 40:
        out_seo["title"] = clean_title(seo["title"])
    if isinstance(seo.get("tags"), list):
        tags = clean_tags([str(t) for t in seo["tags"]])
        if len(tags) >= 10:
            out_seo["tags"] = clean_tags(tags + fallback["seo"]["tags"])
    if isinstance(seo.get("description_intro"), str) and len(seo["description_intro"]) > 60:
        out_seo["description_intro"] = seo["description_intro"].strip()
    if isinstance(seo.get("rationale"), list):
        out_seo["rationale"] = [str(r) for r in seo["rationale"]][:6]

    pins = []
    for i, fb in enumerate(fallback["pins"]):
        p = (pack.get("pins") or [])[i] if i < len(pack.get("pins") or []) else {}
        p = p if isinstance(p, dict) else {}
        pins.append({
            "style": fb["style"],
            "headline": truncate(str(p.get("headline") or fb["headline"]), 48),
            "subline": truncate(str(p.get("subline") or fb["subline"]), 40),
            "title": truncate(str(p.get("title") or fb["title"]), 100),
            "description": truncate(str(p.get("description") or fb["description"]), 500),
            "alt_text": truncate(str(p.get("alt_text") or fb["alt_text"]), 500),
        })
    social = {**fallback["social"], **{k: str(v) for k, v in (pack.get("social") or {}).items() if v}}
    tips = [str(t) for t in pack.get("conversion_tips") or []][:5]
    return {"seo": out_seo, "pins": pins[:n_pins], "social": social,
            "conversion_tips": tips + fallback["conversion_tips"]}


def build_content_pack(llm, listing: dict, m: ListingMetrics, insight: dict | None, n_pins: int,
                       styles: list[str] | None = None, symbol: str = "$", today: date | None = None) -> dict:
    today = today or date.today()
    season = season_context(today)
    styles = styles or HEADLINE_STYLES
    primary = primary_phrase(listing, insight)
    tags = rule_tags(listing, insight)
    fallback = {
        "seo": {
            "title": rule_title(listing, insight, tags),
            "tags": tags,
            "description_intro": rule_description_intro(listing, primary, season),
            "rationale": [
                f"Main search phrase '{primary}' title ke shuru mein rakha (competitors mein sabse common).",
                "Competitors ke top-ranked listings ke proven long-tail tags add kiye.",
            ],
        },
        "pins": rule_pins(listing, primary, season, n_pins, symbol, styles),
        "social": rule_social(listing, primary, season),
        "conversion_tips": conversion_tips(m, insight),
        "source": "rules",
        "season": season,
        "primary_phrase": primary,
    }
    if llm is None or not llm.available:
        return fallback
    raw = llm.generate_json(SYSTEM_PROMPT, _llm_prompt(listing, m, insight, season, n_pins, styles, symbol))
    if not raw:
        return fallback
    pack = _validate(raw, fallback, n_pins)
    pack.update({"source": llm.last_provider, "season": season, "primary_phrase": primary})
    return pack


def quick_pins(listing: dict, n: int, styles: list[str], symbol: str = "$",
               today: date | None = None) -> list[dict]:
    """Cheap copy for non-focus (rotation) pins: rules only, no LLM quota used."""
    season = season_context(today or date.today())
    return rule_pins(listing, primary_phrase(listing, None), season, n, symbol, styles)
