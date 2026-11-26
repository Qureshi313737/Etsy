"""Daily performance analysis: per-listing metrics, quality audit, weakness score, diagnosis."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import median

from .config import Config
from .db import Database, days_ago_str

TRAFFIC, CONVERSION, APPEAL, MOMENTUM = "traffic", "conversion", "appeal", "momentum"

DIAGNOSIS_LABELS = {
    TRAFFIC: "Traffic problem - log is product ko dekh hi nahi rahe (low views)",
    CONVERSION: "Conversion problem - views aa rahe hain par sale nahi ho rahi",
    APPEAL: "Appeal problem - log dekhte hain par favorite/click nahi karte (photo/price)",
    MOMENTUM: "Momentum - theek chal raha hai, extra push se aur grow karega",
}


@dataclass
class ListingMetrics:
    listing: dict
    age_days: float = 0.0
    views_w: float = 0.0
    favs_w: float = 0.0
    sales_w: int = 0
    revenue_w: float = 0.0
    views_s: float = 0.0
    sales_s: int = 0
    conv: float = 0.0
    fav_rate: float = 0.0
    trend: float = 1.0
    estimated: bool = False
    quality: float = 100.0
    quality_issues: list[str] = field(default_factory=list)
    pct: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    diagnosis: str = MOMENTUM
    reasons: list[str] = field(default_factory=list)

    @property
    def listing_id(self) -> int:
        return int(self.listing["listing_id"])

    def to_dict(self) -> dict:
        return {
            "listing_id": self.listing_id, "title": self.listing["title"], "url": self.listing["url"],
            "price": self.listing["price"], "views_w": round(self.views_w, 1), "favs_w": round(self.favs_w, 1),
            "sales_w": self.sales_w, "revenue_w": round(self.revenue_w, 2), "views_s": round(self.views_s, 1),
            "sales_s": self.sales_s, "conv": round(self.conv, 4), "fav_rate": round(self.fav_rate, 4),
            "trend": round(self.trend, 2), "quality": round(self.quality), "score": round(self.score, 3),
            "diagnosis": self.diagnosis, "estimated": self.estimated,
        }


def _ts_end_of(day: str) -> int:
    d = date.fromisoformat(day) + timedelta(days=1)
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def quality_audit(listing: dict) -> tuple[float, list[str]]:
    score = 100.0
    issues: list[str] = []
    title = listing.get("title", "")
    tags = listing.get("tags", [])
    photos = len(listing.get("image_urls", []))
    desc = listing.get("description", "")
    if len(title) < 80:
        score -= 15
        issues.append(f"Title chhota hai ({len(title)}/140 chars) - aur search phrases add karo")
    if len(tags) < 13:
        score -= 3 * (13 - len(tags))
        issues.append(f"Sirf {len(tags)}/13 tags use ho rahe hain - saare 13 slots bharo")
    single = [t for t in tags if " " not in t.strip()]
    if tags and len(single) / len(tags) > 0.4:
        score -= 10
        issues.append(f"{len(single)} single-word tags - 2-3 word long-tail phrases zyada bikte hain")
    if photos < 5:
        score -= 4 * (5 - photos) + 5
        issues.append(f"Sirf {photos} photos - 7-10 photos rakho (lifestyle, scale, detail shots)")
    elif photos < 8:
        score -= 4
        issues.append(f"{photos} photos - 8-10 tak le jao")
    if not listing.get("has_video"):
        score -= 8
        issues.append("Video nahi hai - 5-15 sec ka video add karo (Etsy video listings ko boost karta hai)")
    if len(desc) < 300:
        score -= 10
        issues.append(f"Description chhoti hai ({len(desc)} chars) - benefits, size, materials, gift use-case likho")
    return max(score, 0.0), issues


def _window_delta(db: Database, listing: dict, run_date: str, days: int, field_name: str,
                  lifetime: float) -> tuple[float, bool]:
    """Change in a lifetime counter (views/favorites) over `days`. Estimates when history is short."""
    lid = listing["listing_id"]
    now = db.snapshot_on_or_before(lid, run_date)
    current = float(now[field_name]) if now else lifetime
    past = db.snapshot_on_or_before(lid, days_ago_str(days, run_date))
    if past:
        return max(current - float(past[field_name]), 0.0), False
    first = db.first_snapshot(lid)
    if first and first["snap_date"] < run_date:
        span = (date.fromisoformat(run_date) - date.fromisoformat(first["snap_date"])).days
        if span >= 3:
            return max(current - float(first[field_name]), 0.0) * days / span, True
    created = listing.get("created_ts") or 0
    age = max((_ts_end_of(run_date) - created) / 86400, 1.0) if created else 365.0
    return lifetime / age * min(days, age), True


def percentile_ranks(values: list[float]) -> list[float]:
    n = len(values)
    if n <= 1:
        return [0.5] * n
    out = []
    for v in values:
        less = sum(1 for x in values if x < v)
        equal = sum(1 for x in values if x == v)
        out.append((less + 0.5 * (equal - 1)) / (n - 1))
    return out


def compute_metrics(db: Database, cfg: Config, run_date: str) -> list[ListingMetrics]:
    window = int(cfg.get("analysis.window_days", 30))
    short = int(cfg.get("analysis.short_window_days", 7))
    end_ts = _ts_end_of(run_date)
    out: list[ListingMetrics] = []
    for listing in db.active_listings(run_date):
        m = ListingMetrics(listing=listing)
        created = listing.get("created_ts") or 0
        m.age_days = (end_ts - created) / 86400 if created else 365.0
        m.views_w, est1 = _window_delta(db, listing, run_date, window, "views", listing["views_lifetime"] or 0)
        m.favs_w, est2 = _window_delta(db, listing, run_date, window, "favorites", listing["favorites_lifetime"] or 0)
        m.views_s, est3 = _window_delta(db, listing, run_date, short, "views", listing["views_lifetime"] or 0)
        m.estimated = est1 or est2 or est3
        m.sales_w, m.revenue_w = db.sales_between(m.listing_id, end_ts - window * 86400, end_ts)
        m.sales_s, _ = db.sales_between(m.listing_id, end_ts - short * 86400, end_ts)
        m.conv = m.sales_w / m.views_w if m.views_w > 0 else 0.0
        m.fav_rate = m.favs_w / m.views_w if m.views_w > 0 else 0.0
        daily_w = m.views_w / window if window else 0
        daily_s = m.views_s / short if short else 0
        m.trend = (daily_s / daily_w) if daily_w > 0 else 1.0
        m.quality, m.quality_issues = quality_audit(listing)
        out.append(m)
    score_listings(out, cfg)
    return out


def score_listings(metrics: list[ListingMetrics], cfg: Config) -> None:
    if not metrics:
        return
    w = cfg.get("analysis.weights", {})
    dims = {
        "views": [m.views_w for m in metrics],
        "sales": [m.revenue_w for m in metrics],
        "conversion": [m.conv for m in metrics],
        "favorites": [m.fav_rate for m in metrics],
    }
    ranks = {k: percentile_ranks(v) for k, v in dims.items()}
    med_views = median(dims["views"]) or 0
    for i, m in enumerate(metrics):
        m.pct = {k: ranks[k][i] for k in dims}
        m.score = sum(float(w.get(k, 0)) * (1 - m.pct[k]) for k in dims)
        m.score += float(w.get("quality", 0)) * (1 - m.quality / 100)
        if m.trend < 0.7 and m.views_w > 0:
            m.score += 0.05  # traffic is falling - act before it's gone
        m.diagnosis, m.reasons = diagnose(m, med_views)


def diagnose(m: ListingMetrics, median_views: float) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if m.pct["views"] < 0.4 or m.views_w < 0.5 * median_views:
        diag = TRAFFIC
        reasons.append(f"Views {m.views_w:.0f} (shop median {median_views:.0f}) - search mein dikh nahi raha")
    elif m.pct["conversion"] < 0.4:
        diag = CONVERSION
        reasons.append(f"{m.views_w:.0f} views par sirf {m.sales_w} sale (conversion {m.conv:.1%})")
    elif m.pct["favorites"] < 0.35:
        diag = APPEAL
        reasons.append(f"Favorite rate {m.fav_rate:.1%} - pehli photo/price buyers ko attract nahi kar rahi")
    else:
        diag = MOMENTUM
        reasons.append("Numbers theek hain - marketing push se scale karo")
    if m.trend < 0.7 and m.views_w > 0:
        reasons.append(f"Pichhle hafte traffic {int((1 - m.trend) * 100)}% gira hai")
    if m.sales_w == 0:
        reasons.append("Is window mein ek bhi sale nahi")
    if m.quality < 70:
        reasons.append(f"Listing quality score {m.quality:.0f}/100")
    return diag, reasons


def pick_focus(db: Database, metrics: list[ListingMetrics], cfg: Config, run_date: str) -> list[ListingMetrics]:
    count = int(cfg.get("analysis.focus_count", 1))
    cooldown = int(cfg.get("analysis.focus_cooldown_days", 3))
    min_age = float(cfg.get("analysis.min_listing_age_days", 0))
    pool = [m for m in metrics if (m.listing.get("quantity") or 0) > 0 and m.age_days >= min_age]
    pool.sort(key=lambda m: m.score, reverse=True)
    chosen: list[ListingMetrics] = []
    for m in pool:
        last = db.last_focus_date(m.listing_id)
        if last and last != run_date and last > days_ago_str(cooldown, run_date):
            continue
        chosen.append(m)
        if len(chosen) >= count:
            break
    if len(chosen) < count:  # everything is on cooldown: fall back to the weakest ones
        for m in pool:
            if m not in chosen:
                chosen.append(m)
            if len(chosen) >= count:
                break
    return chosen


def shop_kpis(db: Database, metrics: list[ListingMetrics], cfg: Config, run_date: str) -> dict:
    window = int(cfg.get("analysis.window_days", 30))
    short = int(cfg.get("analysis.short_window_days", 7))
    end = _ts_end_of(run_date)

    def totals(start: int, stop: int) -> tuple[int, float]:
        row = db.one("SELECT COALESCE(SUM(quantity),0) u, COALESCE(SUM(quantity*price),0) r FROM sales "
                     "WHERE created_ts>=? AND created_ts<?", (start, stop))
        return int(row["u"]), float(row["r"])

    units_s, rev_s = totals(end - short * 86400, end)
    units_prev, rev_prev = totals(end - 2 * short * 86400, end - short * 86400)
    units_w, rev_w = totals(end - window * 86400, end)
    views_w = sum(m.views_w for m in metrics)
    return {
        "active_listings": len(metrics),
        "views_w": views_w,
        "views_s": sum(m.views_s for m in metrics),
        "units_w": units_w, "revenue_w": rev_w,
        "units_s": units_s, "revenue_s": rev_s,
        "units_prev_s": units_prev, "revenue_prev_s": rev_prev,
        "conversion_w": units_w / views_w if views_w else 0.0,
        "zero_sale_listings": sum(1 for m in metrics if m.sales_w == 0),
        "estimated": any(m.estimated for m in metrics),
    }


def measure_uplift(db: Database, cfg: Config, run_date: str) -> list[dict]:
    """For products focused 7-21 days ago: compare 7-day views/sales before vs after the push."""
    rows = db.query(
        "SELECT * FROM focus_history WHERE run_date<=? AND run_date>=? ORDER BY run_date DESC",
        (days_ago_str(7, run_date), days_ago_str(21, run_date)),
    )
    out, seen = [], set()
    for r in rows:
        lid = r["listing_id"]
        if lid in seen:
            continue
        seen.add(lid)
        listing = db.listing(lid)
        if not listing:
            continue
        end_ts = _ts_end_of(run_date)
        after_views, _ = _window_delta(db, listing, run_date, 7, "views", listing["views_lifetime"] or 0)
        after_sales, _ = db.sales_between(lid, end_ts - 7 * 86400, end_ts)
        out.append({
            "listing_id": lid, "title": listing["title"], "focused_on": r["run_date"],
            "diagnosis": r["diagnosis"],
            "views_before": r["views_7d"], "views_after": after_views,
            "sales_before": r["sales_7d"], "sales_after": after_sales,
            "views_change": (after_views - r["views_7d"]) / r["views_7d"] if r["views_7d"] else None,
        })
    return out
