"""Free mini-site on GitHub Pages: product landing pages + RSS feeds for Pinterest auto-publishing.

* Pinterest "Auto-publish from RSS" turns every new feed item into a Pin - no API approval needed.
* Landing pages are indexable by Google (free extra traffic) and link straight to Etsy.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from .config import Config
from .db import Database
from .pinterest_campaign import utm_link
from .text_utils import esc, short_name, slugify, truncate

log = logging.getLogger(__name__)

CSS = """
:root{--bg:#faf8f5;--fg:#222;--muted:#666;--card:#fff;--accent:ACCENT}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#eee;--muted:#aaa;--card:#1f1f1f}}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:var(--bg);color:var(--fg);line-height:1.5}a{color:inherit}
header{padding:28px 16px;text-align:center}header h1{margin:0;font-size:1.8rem}header p{color:var(--muted);margin:6px 0 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;padding:0 16px 40px;max-width:1200px;margin:auto}
.card{background:var(--card);border-radius:14px;overflow:hidden;text-decoration:none;box-shadow:0 1px 4px #0002}
.card img{width:100%;aspect-ratio:1;object-fit:cover;display:block}.card div{padding:10px 12px}
.card h2{font-size:.95rem;margin:0 0 6px;font-weight:600}.price{font-weight:700}
.wrap{max-width:980px;margin:auto;padding:16px;display:grid;gap:24px;grid-template-columns:1fr}
@media(min-width:800px){.wrap{grid-template-columns:1.1fr 1fr}}
.hero{width:100%;border-radius:16px;display:block}.thumbs{display:flex;gap:8px;margin-top:8px;overflow-x:auto}
.thumbs img{width:84px;height:84px;object-fit:cover;border-radius:8px}
.btn{display:inline-block;background:var(--accent);color:#fff;padding:14px 26px;border-radius:999px;
text-decoration:none;font-weight:700;margin:12px 0}.desc{white-space:pre-line;color:var(--muted)}
footer{text-align:center;color:var(--muted);padding:24px;font-size:.85rem}
"""


def _page(title: str, body: str, cfg: Config, head_extra: str = "") -> str:
    css = CSS.replace("ACCENT", cfg.get("shop.brand_color", "#F1641E"))
    verify = cfg.get("site.pinterest_verify", "")
    verify_tag = f'<meta name="p:domain_verify" content="{esc(verify)}">' if verify else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
{verify_tag}{head_extra}<style>{css}</style></head><body>{body}
<footer>{esc(cfg.get('shop.name'))} &middot; Handmade on Etsy</footer></body></html>"""


def listing_page_name(listing: dict) -> str:
    return f"{slugify(listing['title'])}-{listing['listing_id']}.html"


def _demo_images(site: Path, listings: list[dict], depth_prefix: str = "") -> list[dict]:
    """Demo listings use demo:// placeholders - save them as real files so the pages render."""
    from .demo import demo_product_image

    (site / "img").mkdir(parents=True, exist_ok=True)
    out = []
    for l in listings:
        urls = []
        for u in l.get("image_urls") or []:
            if u.startswith("demo://"):
                name = slugify(u) + ".jpg"
                if not (site / "img" / name).exists():
                    demo_product_image(u).resize((600, 600)).save(site / "img" / name, quality=80)
                u = f"img/{name}"
            urls.append(u)
        out.append({**l, "image_urls": urls})
    return out


def build_site(db: Database, cfg: Config, run_date: str, listings: list[dict]) -> dict:
    site = cfg.path("site_dir")
    if cfg.demo:
        listings = _demo_images(site, listings)
    (site / "p").mkdir(parents=True, exist_ok=True)
    (site / "pins").mkdir(parents=True, exist_ok=True)
    base = (cfg.get("site.base_url") or "").rstrip("/")
    shop = cfg.get("shop.name")
    symbol = cfg.get("shop.currency_symbol", "$")
    title = cfg.get("site.title") or f"{shop} - Handmade Finds"

    cards = []
    for l in listings:
        page = listing_page_name(l)
        img = (l.get("image_urls") or [""])[0]
        etsy = utm_link(l["url"], cfg, "site")
        cards.append(
            f'<a class="card" href="p/{page}"><img loading="lazy" src="{esc(img)}" alt="{esc(short_name(l["title"]))}">'
            f'<div><h2>{esc(truncate(l["title"], 70))}</h2><span class="price">{symbol}{l["price"]:.2f}</span></div></a>')
        rel = [u if u.startswith("http") else f"../{u}" for u in (l.get("image_urls") or [""])]
        hero = rel[0]
        thumbs = "".join(f'<img loading="lazy" src="{esc(u)}" alt="">' for u in rel[1:7])
        og = (f'<meta property="og:title" content="{esc(l["title"])}"><meta property="og:type" content="product">'
              f'<meta property="og:image" content="{esc(img)}"><meta property="og:url" content="{esc(base)}/p/{page}">'
              f'<meta property="og:description" content="{esc(truncate(l.get("description", ""), 200))}">'
              f'<meta property="product:price:amount" content="{l["price"]:.2f}">'
              f'<meta property="product:price:currency" content="{esc(l.get("currency", "USD"))}">'
              f'<meta name="description" content="{esc(truncate(l.get("description", ""), 155))}">'
              f'<link rel="canonical" href="{esc(l["url"])}">')
        body = (f'<header><p><a href="../index.html">&larr; {esc(shop)}</a></p></header><div class="wrap">'
                f'<div><img class="hero" src="{esc(hero)}" alt="{esc(l["title"])}"><div class="thumbs">{thumbs}</div></div>'
                f'<div><h1>{esc(l["title"])}</h1><p class="price">{symbol}{l["price"]:.2f}</p>'
                f'<a class="btn" href="{esc(etsy)}">View &amp; buy on Etsy</a>'
                f'<p class="desc">{esc(truncate(l.get("description", ""), 1200))}</p>'
                f'<a class="btn" href="{esc(etsy)}">Shop on Etsy</a></div></div>')
        (site / "p" / page).write_text(_page(l["title"], body, cfg, og), encoding="utf-8")

    index_body = (f"<header><h1>{esc(title)}</h1><p>Every item ships from our Etsy shop.</p></header>"
                  f'<div class="grid">{"".join(cards)}</div>')
    (site / "index.html").write_text(_page(title, index_body, cfg), encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    (site / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    urls = [f"{base}/index.html"] + [f"{base}/p/{listing_page_name(l)}" for l in listings]
    (site / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{xml_escape(u)}</loc><lastmod>{run_date}</lastmod></url>" for u in urls)
        + "</urlset>", encoding="utf-8")

    feeds = build_feeds(db, cfg, site)
    pruned = prune_pins(cfg, site / "pins")
    return {"pages": len(listings), "feeds": feeds, "pruned_images": pruned, "dir": str(site)}


def build_feeds(db: Database, cfg: Config, site: Path) -> list[str]:
    base = (cfg.get("site.base_url") or "").rstrip("/")
    limit = int(cfg.get("site.max_items_in_feed", 50))
    use_landing = cfg.get("site.link_target", "landing") == "landing"
    rows = db.query("SELECT * FROM pin_queue WHERE status IN ('feed','exported','queued','posted') "
                    "AND channel='rss' ORDER BY id DESC LIMIT ?", (limit * 5,))
    rows = [r for r in rows if (site / "pins" / r["image_path"]).exists()]
    boards: dict[str, list[dict]] = {}
    for r in rows:
        boards.setdefault(r["board"], []).append(r)
    written = []
    groups = [("feed.xml", "All pins", rows[:limit])] + [
        (f"feed-{slugify(b)}.xml", b, items[:limit]) for b, items in boards.items()]
    for filename, label, items in groups:
        entries = []
        for r in items:
            img = f"{base}/pins/{r['image_path']}"
            link = r["landing_link"] if use_landing and r["landing_link"] else r["link"]
            size = (site / "pins" / r["image_path"]).stat().st_size
            posted = datetime.fromisoformat(r["run_date"]).replace(tzinfo=timezone.utc)
            entries.append(
                f"<item><title>{xml_escape(r['title'])}</title><link>{xml_escape(link)}</link>"
                f"<guid isPermaLink=\"false\">pin-{r['id']}-{r['image_path']}</guid>"
                f"<pubDate>{format_datetime(posted)}</pubDate>"
                f"<description>{xml_escape(r['description'])}&lt;br&gt;&lt;img src=\"{xml_escape(img)}\"&gt;</description>"
                f"<enclosure url=\"{xml_escape(img)}\" length=\"{size}\" type=\"image/jpeg\"/>"
                f"<media:content url=\"{xml_escape(img)}\" medium=\"image\" type=\"image/jpeg\"/></item>")
        xml = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" '
               'xmlns:media="http://search.yahoo.com/mrss/"><channel>'
               f"<title>{xml_escape(cfg.get('shop.name'))} - {xml_escape(label)}</title>"
               f"<link>{xml_escape(base or '/')}</link><description>New handmade finds</description>"
               + "".join(entries) + "</channel></rss>")
        (site / filename).write_text(xml, encoding="utf-8")
        written.append(filename)
    return written


def prune_pins(cfg: Config, pins_dir: Path) -> int:
    keep = int(cfg.get("site.keep_pin_images", 300))
    files = sorted(pins_dir.glob("*.jpg"), key=lambda p: p.name, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)
    return max(len(files) - keep, 0)
