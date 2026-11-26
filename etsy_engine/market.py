"""Market research through Etsy's public search API: competitors, prices, winning tags & phrases."""
from __future__ import annotations

import json
import logging
import math
from collections import Counter
from statistics import median

from .config import Config
from .db import Database
from .http import ApiError
from .text_utils import clean_tag, keywords, phrase_counts, title_phrases

log = logging.getLogger(__name__)


def seed_keywords(listing: dict, n: int = 3) -> list[str]:
    seeds: list[str] = []
    phrases = title_phrases(listing.get("title", ""))
    if phrases:
        main = " ".join(keywords(phrases[0])[:4])
        if main:
            seeds.append(main)
    multi = sorted((t for t in listing.get("tags", []) if " " in t.strip()), key=len, reverse=True)
    for t in multi + list(listing.get("tags", [])):
        t = t.strip().lower()
        if t and t not in seeds and not any(t in s or s in t for s in seeds):
            seeds.append(t)
        if len(seeds) >= n:
            break
    return seeds[:n]


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    idx = (len(vals) - 1) * q
    lo, hi = math.floor(idx), math.ceil(idx)
    return vals[lo] + (vals[hi] - vals[lo]) * (idx - lo)


def analyze_market(source, listing: dict, cfg: Config, db: Database | None = None,
                   run_date: str | None = None, own_shop_id: int | None = None,
                   trending: list[str] | None = None) -> dict:
    limit = int(cfg.get("market.competitors_per_keyword", 100))
    seeds = seed_keywords(listing, int(cfg.get("market.keywords_per_listing", 3)))
    our_tags = {t.lower().strip() for t in listing.get("tags", [])}
    tag_scores: Counter = Counter()
    titles: list[str] = []
    title_weights: list[float] = []
    prices: list[float] = []
    per_keyword: list[dict] = []
    samples: dict[int, dict] = {}

    for kw in seeds:
        try:
            res = source.search_active_listings(kw, limit=limit)
        except ApiError as exc:
            log.warning("Market search for %r failed: %s", kw, exc)
            continue
        comps = [r for r in res["results"]
                 if r["listing_id"] != listing["listing_id"] and (own_shop_id is None or r.get("shop_id") != own_shop_id)]
        kw_prices = [c["price"] for c in comps if c["price"] > 0]
        per_keyword.append({
            "keyword": kw, "competitors": res["count"],
            "median_price": round(median(kw_prices), 2) if kw_prices else 0.0,
        })
        for rank, c in enumerate(comps):
            # popularity weight: favourites + search position (Etsy ranks best sellers higher)
            weight = 1.0 + math.log1p(c.get("num_favorers", 0)) + max(0.0, 2.0 - rank / 25)
            for t in c.get("tags", []):
                ct = clean_tag(t)
                if ct:
                    tag_scores[ct] += weight
            titles.append(c["title"])
            title_weights.append(weight)
            if c["price"] > 0:
                prices.append(c["price"])
            if c["listing_id"] not in samples or samples[c["listing_id"]]["_w"] < weight:
                samples[c["listing_id"]] = {**c, "_w": weight}

    phrases = phrase_counts(titles, title_weights)
    our_price = float(listing.get("price") or 0)
    price_stats = {
        "min": round(min(prices), 2) if prices else 0.0,
        "p25": round(_quantile(prices, 0.25), 2),
        "median": round(_quantile(prices, 0.5), 2),
        "p75": round(_quantile(prices, 0.75), 2),
        "max": round(max(prices), 2) if prices else 0.0,
        "ours": our_price,
        "our_percentile": round(sum(1 for p in prices if p < our_price) / len(prices), 2) if prices else None,
    }
    top_tags = [(t, round(s, 1)) for t, s in tag_scores.most_common(40)]
    missing = [t for t, _ in top_tags if t not in our_tags][:15]
    top_samples = sorted(samples.values(), key=lambda s: -s["_w"])[:5]
    related_trends = []
    if trending:
        our_words = set(keywords(" ".join(seeds + list(our_tags))))
        related_trends = [t for t in trending if our_words & set(keywords(t))][:10]

    insight = {
        "keywords": per_keyword,
        "price": price_stats,
        "top_tags": top_tags[:25],
        "missing_tags": missing,
        "top_phrases": [(p, round(s, 1)) for p, s in phrases.most_common(15)],
        "competitor_samples": [
            {"title": s["title"], "price": s["price"], "favorites": s.get("num_favorers", 0), "url": s["url"]}
            for s in top_samples
        ],
        "related_trends": related_trends,
        "analyzed": bool(per_keyword),
    }
    if db is not None and run_date:
        for k in per_keyword:
            db.execute(
                """INSERT OR REPLACE INTO market_snapshots(snap_date, listing_id, keyword, competitor_count,
                       median_price, p25_price, p75_price, our_price_percentile, top_tags, top_phrases)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (run_date, listing["listing_id"], k["keyword"], k["competitors"], k["median_price"],
                 price_stats["p25"], price_stats["p75"], price_stats["our_percentile"],
                 json.dumps(insight["top_tags"][:15]), json.dumps(insight["top_phrases"][:10])),
            )
    return insight


def price_advice(insight: dict, symbol: str = "$") -> str | None:
    p = insight.get("price") or {}
    if not p.get("median") or p.get("our_percentile") is None:
        return None
    ours, med = p["ours"], p["median"]
    if p["our_percentile"] >= 0.85:
        return (f"Aapka price {symbol}{ours:.2f} competitors ke top 15% mein hai (median {symbol}{med:.2f}). "
                f"Ya to price {symbol}{p['p75']:.2f} ke paas lao, ya photos/description mein premium value clearly dikhao.")
    if p["our_percentile"] <= 0.10:
        return (f"Aapka price {symbol}{ours:.2f} market ke sabse saste 10% mein hai (median {symbol}{med:.2f}). "
                f"Bahut sasta price quality par shak paida karta hai - {symbol}{p['p25']:.2f}-{symbol}{med:.2f} test karo.")
    if p["our_percentile"] < 0.25:
        return (f"Aapka price {symbol}{ours:.2f} market ke saste side par hai (median {symbol}{med:.2f}). "
                f"Agar photos/quality strong hain to {symbol}{p['p25']:.2f}-{symbol}{med:.2f} test karke margin badhao.")
    if p["our_percentile"] > 0.75:
        return (f"Aapka price {symbol}{ours:.2f} mehenge side par hai (median {symbol}{med:.2f}) - "
                f"listing mein premium value (material, size, packaging, personalization) clearly dikhao.")
    return f"Price {symbol}{ours:.2f} market range mein hai (25%-75%: {symbol}{p['p25']:.2f}-{symbol}{p['p75']:.2f})."
