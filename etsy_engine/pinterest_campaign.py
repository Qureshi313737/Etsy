"""Pinterest campaign: plan today's pins, render them, publish through the best available channel.

Channels (pinterest.channel in config.yaml):
  api  - post via Pinterest API v5 (needs Standard access for public pins)
  rss  - Pinterest auto-publish from your RSS feed (free, no API approval; needs the site)
  csv  - Pinterest bulk-upload CSV with scheduled publish dates (free, upload manually)
  auto - api if Pinterest keys are set, else rss if site.base_url is set, else csv
"""
from __future__ import annotations

import csv
import json
import logging
import random
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import bandit
from .analysis import ListingMetrics
from .config import Config
from .copywriter import quick_pins
from .db import Database, days_ago_str
from .http import ApiError
from .pin_designer import TEMPLATES, ImageFetcher, render_recipe
from .text_utils import keywords, slugify

log = logging.getLogger(__name__)


def _stored_pinterest(cfg: Config) -> bool:
    from .secrets_store import TokenStore

    if not cfg.secret("TOKEN_ENCRYPTION_KEY"):
        return False
    return bool(TokenStore(cfg.path("token_file"), cfg.secret("TOKEN_ENCRYPTION_KEY")).get("pinterest").get("refresh_token"))


def resolve_channel(cfg: Config) -> str:
    channel = str(cfg.get("pinterest.channel", "auto")).lower()
    if channel != "auto":
        return channel
    if cfg.has("PINTEREST_APP_ID", "PINTEREST_APP_SECRET") and (
            cfg.secret("PINTEREST_REFRESH_TOKEN") or cfg.secret("PINTEREST_ACCESS_TOKEN") or _stored_pinterest(cfg)):
        return "api"
    if cfg.get("site.enabled") and cfg.get("site.base_url"):
        return "rss"
    return "csv"


def board_for(listing: dict, cfg: Config) -> str:
    text = set(keywords(listing.get("title", "") + " " + " ".join(listing.get("tags", []))))
    for rule in cfg.get("pinterest.board_rules", []) or []:
        if set(k.lower() for k in rule.get("keywords", [])) & text:
            return rule["board"]
    return cfg.get("pinterest.default_board", "Etsy Finds")


def utm_link(url: str, cfg: Config, content: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query.update({"utm_source": "pinterest", "utm_medium": "social",
                  "utm_campaign": cfg.get("pinterest.utm_campaign", "etsy_engine"), "utm_content": content})
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def landing_url(cfg: Config, listing: dict) -> str:
    base = (cfg.get("site.base_url") or "").rstrip("/")
    return f"{base}/p/{slugify(listing['title'])}-{listing['listing_id']}.html" if base else ""


def slots_per_day(cfg: Config) -> int:
    return max(1, int(cfg.get("pinterest.publish_runs_per_day", 5)))


def _rotation_candidates(db: Database, cfg: Config, metrics: list[ListingMetrics], focus_ids: set[int],
                         run_date: str) -> list[ListingMetrics]:
    gap = int(cfg.get("pinterest.min_days_between_same_listing", 2))
    cutoff = days_ago_str(gap, run_date)
    pool = []
    for m in metrics:
        if m.listing_id in focus_ids or (m.listing.get("quantity") or 0) <= 0:
            continue
        last = db.last_pinned_date(m.listing_id)
        if last and last > cutoff:
            continue
        pool.append((last or "0000-00-00", -m.score, m))
    pool.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in pool]


def plan_and_render(db: Database, cfg: Config, run_date: str, focus: list[tuple[ListingMetrics, dict]],
                    metrics: list[ListingMetrics], fetcher: ImageFetcher, pins_dir: Path,
                    rng: random.Random | None = None) -> list[dict]:
    """Create today's pin queue. `focus` = [(metrics, content_pack)] for the weak products."""
    rng = rng or random.Random()
    channel = resolve_channel(cfg)
    if channel == "off":
        return []
    db.execute("DELETE FROM pin_queue WHERE run_date=? AND status IN ('queued','feed','exported')", (run_date,))
    total = int(cfg.get("pinterest.pins_per_day", 10))
    focus_ids = {m.listing_id for m, _ in focus}
    rotation = _rotation_candidates(db, cfg, metrics, focus_ids, run_date)
    n_focus_total = round(total * float(cfg.get("pinterest.focus_share", 0.5))) if focus else 0
    n_rotation = min(total - n_focus_total, len(rotation))
    n_focus_total = total - n_rotation if focus else 0

    plan: list[tuple[dict, dict, bool]] = []  # (listing, copy, is_focus)
    for idx, (m, pack) in enumerate(focus):
        share = n_focus_total // len(focus) + (1 if idx < n_focus_total % len(focus) else 0)
        pins = pack.get("pins", [])
        for i in range(share):
            if pins:
                plan.append((m.listing, pins[i % len(pins)], True))
    symbol = cfg.get("shop.currency_symbol", "$")
    rot_styles = bandit.choose(["keyword", "gift", "seasonal", "benefit"],
                               bandit.arm_stats(db, "headline_style"), max(n_rotation, 1), rng)
    for i, m in enumerate(rotation[:n_rotation]):
        plan.append((m.listing, quick_pins(m.listing, 1, [rot_styles[i % len(rot_styles)]], symbol,
                                           date.fromisoformat(run_date))[0], False))

    templates = bandit.choose(TEMPLATES, bandit.arm_stats(db, "template"), len(plan), rng)
    pins_dir.mkdir(parents=True, exist_ok=True)
    slots = slots_per_day(cfg)
    status = {"api": "queued", "rss": "feed", "csv": "exported"}.get(channel, "queued")
    accent = cfg.get("shop.brand_color", "#F1641E")
    cta = cfg.get("shop.cta_text", "Shop on Etsy")
    rows = []
    per_listing_count: dict[int, int] = {}
    for n, (listing, copy, is_focus) in enumerate(plan):
        k = per_listing_count.get(listing["listing_id"], 0)
        per_listing_count[listing["listing_id"]] = k + 1
        images = listing.get("image_urls") or []
        primary = k % min(len(images), 4) if images else 0
        ordered = ([images[primary]] + [u for j, u in enumerate(images) if j != primary])[:3] if images else []
        template = templates[n]
        recipe = {
            "template": template, "headline": copy["headline"], "subline": copy.get("subline", ""),
            "cta": cta, "accent": accent, "image_urls": ordered,
            "price": f"{symbol}{listing['price']:.2f}" if listing.get("price") and template in ("banner", "split", "frame", "label") and copy.get("style") == "price" else "",
        }
        filename = f"{run_date}-{listing['listing_id']}-{k}.jpg"
        try:
            img_bytes = render_recipe(recipe, fetcher)
            (pins_dir / filename).write_bytes(img_bytes)
        except Exception as exc:
            log.warning("Rendering pin for %s failed: %s", listing["listing_id"], exc)
            continue
        content = f"{template}-{copy.get('style', 'x')}"
        row = {
            "run_date": run_date, "listing_id": listing["listing_id"], "is_focus": int(is_focus),
            "template": template, "headline_style": copy.get("style", ""), "image_path": filename,
            "image_variant": f"img:{primary}", "recipe": json.dumps(recipe), "title": copy["title"],
            "description": copy["description"], "alt_text": copy.get("alt_text", ""),
            "link": utm_link(listing["url"], cfg, content), "landing_link": landing_url(cfg, listing),
            "board": board_for(listing, cfg), "channel": channel, "status": status,
            "scheduled_slot": n % slots,
        }
        cur = db.execute(
            f"INSERT INTO pin_queue({', '.join(row)}) VALUES({', '.join('?' * len(row))})", list(row.values()))
        row["id"] = cur.lastrowid
        rows.append(row)
        db.log_action(run_date, listing["listing_id"], "pin_planned", channel,
                      {"template": template, "style": copy.get("style"), "focus": is_focus})
    log.info("Planned %d pins via channel '%s'", len(rows), channel)
    return rows


def publish_due(db: Database, cfg: Config, client, fetcher: ImageFetcher, pins_dir: Path,
                now: datetime | None = None, publish_all: bool = False) -> dict:
    """Post queued API pins whose time slot has arrived. Safe to run many times a day."""
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    slot_now = int(now.hour // (24 / slots_per_day(cfg)))
    db.execute("UPDATE pin_queue SET status='expired' WHERE status='queued' AND run_date<?", (yesterday,))
    rows = db.query(
        """SELECT * FROM pin_queue WHERE status='queued' AND channel='api'
           AND (run_date=? OR (run_date=? AND (scheduled_slot<=? OR ?)))
           ORDER BY run_date, scheduled_slot, id""",
        (yesterday, today, slot_now, int(publish_all)),
    )
    posted, failed = 0, 0
    for row in rows:
        try:
            path = pins_dir / row["image_path"]
            img = path.read_bytes() if path.exists() else render_recipe(json.loads(row["recipe"]), fetcher)
            board_id = client.board_id(row["board"])
            res = client.create_pin(board_id, row["title"], row["description"], row["link"], row["alt_text"], img)
            pin_id = str(res.get("id"))
            db.execute("UPDATE pin_queue SET status='posted', pin_id=?, posted_at=? WHERE id=?",
                       (pin_id, now.isoformat(timespec="seconds"), row["id"]))
            db.execute("INSERT OR IGNORE INTO pin_stats(pin_id, listing_id, template, headline_style) VALUES(?,?,?,?)",
                       (pin_id, row["listing_id"], row["template"], row["headline_style"]))
            db.log_action(row["run_date"], row["listing_id"], "pin_posted", "api", {"board": row["board"]}, pin_id)
            posted += 1
        except (ApiError, RuntimeError, OSError) as exc:
            failed += 1
            db.execute("UPDATE pin_queue SET status=?, error=? WHERE id=?",
                       ("failed" if getattr(exc, "status", 0) in (400, 401, 403) else "queued", str(exc)[:500], row["id"]))
            log.warning("Pin %s failed: %s", row["id"], exc)
            if getattr(exc, "status", 0) in (401, 403):
                break  # auth problem - stop and report instead of hammering the API
    return {"posted": posted, "failed": failed, "due": len(rows)}


def sync_pin_stats(db: Database, cfg: Config, client, today: date | None = None) -> int:
    today = today or datetime.now(timezone.utc).date()
    lookback = int(cfg.get("pinterest.analytics_lookback_days", 30))
    start = today - timedelta(days=lookback)
    rows = db.query("SELECT pin_id, posted_at FROM pin_queue WHERE status='posted' AND pin_id IS NOT NULL "
                    "AND run_date>=?", (start.isoformat(),))
    updated = 0
    for r in rows:
        try:
            s = client.pin_analytics(r["pin_id"], max(start, date.fromisoformat(r["posted_at"][:10])), today)
        except (ApiError, RuntimeError) as exc:
            log.info("Analytics for pin %s unavailable: %s", r["pin_id"], exc)
            continue
        db.execute("""UPDATE pin_stats SET impressions=?, saves=?, pin_clicks=?, outbound_clicks=?, synced_at=?
                      WHERE pin_id=?""",
                   (s["impressions"], s["saves"], s["pin_clicks"], s["outbound_clicks"], today.isoformat(), r["pin_id"]))
        updated += 1
    return updated


def export_bulk_csv(db: Database, cfg: Config, run_date: str, out_path: Path) -> Path | None:
    """Pinterest bulk-create CSV (Create > Create Pins in bulk). Needs public image URLs (the site)."""
    base = (cfg.get("site.base_url") or "").rstrip("/")
    rows = db.query("SELECT * FROM pin_queue WHERE run_date=? ORDER BY scheduled_slot, id", (run_date,))
    if not rows:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    day = date.fromisoformat(run_date)
    slots = slots_per_day(cfg)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Title", "Media URL", "Pinterest board", "Thumbnail", "Description", "Link",
                    "Publish date", "Keywords"])
        for r in rows:
            hour = 14 + int(r["scheduled_slot"] * (10 / slots))  # spread 14:00-24:00 UTC = US daytime
            publish = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1, hours=hour)
            listing = db.listing(r["listing_id"]) or {}
            w.writerow([
                r["title"], f"{base}/pins/{r['image_path']}" if base else r["image_path"], r["board"], "",
                r["description"], r["link"], publish.strftime("%Y-%m-%dT%H:%M:%S"),
                ", ".join((listing.get("tags") or [])[:5]),
            ])
    return out_path

