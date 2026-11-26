"""The daily orchestrator: sync -> analyse -> research -> fix -> promote -> learn -> report."""
from __future__ import annotations

import logging
import random
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from . import analysis, bandit
from .config import Config
from .copywriter import HEADLINE_STYLES, build_content_pack
from .db import Database, days_ago_str
from .http import ApiError
from .llm import LLM
from .market import analyze_market, seed_keywords
from .notify import send_email, send_telegram
from .pin_designer import ImageFetcher
from .pinterest_campaign import export_bulk_csv, plan_and_render, publish_due, resolve_channel, sync_pin_stats
from .report import build_summary, write_reports
from .secrets_store import TokenStore
from .seo import apply_proposal, make_proposal
from .site_builder import build_site
from .sync import sync_shop

log = logging.getLogger(__name__)


@dataclass
class Clients:
    etsy: Any
    pinterest: Any
    llm: Any
    store: TokenStore | None = None


def build_clients(cfg: Config) -> Clients:
    store = TokenStore(cfg.path("token_file"), cfg.secret("TOKEN_ENCRYPTION_KEY"))
    if cfg.demo:
        from .demo import DemoEtsy, DemoPinterest

        return Clients(DemoEtsy(), DemoPinterest(), LLM(cfg), store)
    etsy = None
    if cfg.has("ETSY_API_KEY", "ETSY_SHARED_SECRET"):
        from .etsy_client import EtsyClient

        etsy = EtsyClient(cfg.secret("ETSY_API_KEY"), cfg.secret("ETSY_SHARED_SECRET"), store,
                          refresh_token_seed=cfg.secret("ETSY_REFRESH_TOKEN"), shop_id=cfg.secret("ETSY_SHOP_ID") or None)
    pinterest = None
    if cfg.has("PINTEREST_APP_ID", "PINTEREST_APP_SECRET") or cfg.secret("PINTEREST_ACCESS_TOKEN"):
        from .pinterest_client import PinterestClient

        pinterest = PinterestClient(cfg.secret("PINTEREST_APP_ID"), cfg.secret("PINTEREST_APP_SECRET"), store,
                                    refresh_token_seed=cfg.secret("PINTEREST_REFRESH_TOKEN"),
                                    access_token=cfg.secret("PINTEREST_ACCESS_TOKEN"),
                                    sandbox=bool(cfg.get("pinterest.use_sandbox")))
    return Clients(etsy, pinterest, LLM(cfg), store)


def setup_warnings(cfg: Config, clients: Clients, channel: str) -> list[str]:
    w = []
    if cfg.demo:
        return w
    if clients.store and not clients.store.persistent:
        w.append("TOKEN_ENCRYPTION_KEY set nahi hai - naye refresh tokens save nahi honge (README dekho).")
    if not clients.llm.available:
        w.append("Koi LLM key nahi (GEMINI_API_KEY free hai) - rule-based copywriter use hua.")
    if channel == "rss" and not cfg.get("site.base_url"):
        w.append("site.base_url khaali hai - RSS feed public nahi hogi.")
    if channel == "csv" and not cfg.get("site.base_url"):
        w.append("CSV ke 'Media URL' ke liye public site chahiye (site.base_url).")
    return w


def market_pulse(db: Database, source, cfg: Config, run_date: str, metrics: list, shop_id: int | None) -> list[dict]:
    every = int(cfg.get("market.shop_scan_every_days", 7))
    last = db.kv_get("last_market_pulse")
    if not cfg.get("market.enabled", True) or (last and last > days_ago_str(every, run_date)):
        return []
    out = []
    for m in sorted(metrics, key=lambda x: -x.score)[:25]:
        kws = seed_keywords(m.listing, 1)
        if not kws:
            continue
        prev = db.one("SELECT competitor_count FROM market_snapshots WHERE listing_id=? AND keyword=? AND snap_date<? "
                      "ORDER BY snap_date DESC LIMIT 1", (m.listing_id, kws[0], run_date))
        try:
            res = source.search_active_listings(kws[0], limit=50)
        except ApiError as exc:
            log.warning("Market pulse search failed: %s", exc)
            break
        prices = sorted(r["price"] for r in res["results"] if r["price"] > 0 and r.get("shop_id") != shop_id)
        med = prices[len(prices) // 2] if prices else 0.0
        pct = sum(1 for p in prices if p < m.listing["price"]) / len(prices) if prices else None
        db.execute("""INSERT OR REPLACE INTO market_snapshots(snap_date, listing_id, keyword, competitor_count,
                      median_price, our_price_percentile) VALUES(?,?,?,?,?,?)""",
                   (run_date, m.listing_id, kws[0], res["count"], med, pct))
        out.append({"keyword": kws[0], "competitors": res["count"], "median_price": med, "our_percentile": pct,
                    "competitor_change": res["count"] - prev["competitor_count"] if prev else None})
    db.kv_set("last_market_pulse", run_date)
    return out


def run_daily(cfg: Config, clients: Clients | None = None, now: datetime | None = None,
              notify: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    run_date = now.date().isoformat()
    clients = clients or build_clients(cfg)
    if clients.etsy is None:
        raise RuntimeError("Etsy keys missing. `python -m etsy_engine check` chalao ya pehle `demo` try karo.")
    if cfg.demo:
        shutil.rmtree(cfg.path("data_dir").parent, ignore_errors=True)
    db = Database(cfg.path("db_file"))
    rng = random.Random(run_date)
    channel = resolve_channel(cfg)
    warnings = setup_warnings(cfg, clients, channel)

    # 1. sync -------------------------------------------------------------------
    if cfg.demo:
        from .demo import seed_history, seed_pin_history

        seed_history(db, clients.etsy)
        seed_pin_history(db, clients.etsy)
    sync_shop(clients.etsy, db, run_date)
    shop_id = getattr(clients.etsy, "shop_id", None)

    # 2. learn from yesterday's pins ----------------------------------------------
    if channel == "api" and clients.pinterest is not None and not cfg.demo:
        try:
            n = sync_pin_stats(db, cfg, clients.pinterest, now.date())
            log.info("Updated analytics for %d pins", n)
        except Exception as exc:
            warnings.append(f"Pinterest analytics sync failed: {exc}")

    # 3. analyse ------------------------------------------------------------------
    metrics = analysis.compute_metrics(db, cfg, run_date)
    if not metrics:
        raise RuntimeError("Shop mein koi active listing nahi mili.")
    kpis = analysis.shop_kpis(db, metrics, cfg, run_date)
    focus = analysis.pick_focus(db, metrics, cfg, run_date)

    trending: list[str] = []
    if clients.pinterest is not None:
        try:
            trending = clients.pinterest.trending_keywords()
        except Exception as exc:
            log.info("Pinterest trends unavailable: %s", exc)

    # 4. research + fix each weak product ----------------------------------------------
    pins_per_day = int(cfg.get("pinterest.pins_per_day", 10))
    n_focus_pins = max(1, min(6, round(pins_per_day * float(cfg.get("pinterest.focus_share", 0.5)))
                              // max(len(focus), 1)))
    style_stats = bandit.arm_stats(db, "headline_style")
    symbol = cfg.get("shop.currency_symbol", "$")
    focus_out = []
    for m in focus:
        insight = None
        if cfg.get("market.enabled", True):
            insight = analyze_market(clients.etsy, m.listing, cfg, db, run_date, shop_id, trending)
        styles = bandit.choose(HEADLINE_STYLES, style_stats, n_focus_pins, rng)
        pack = build_content_pack(clients.llm, m.listing, m, insight, n_focus_pins, styles, symbol,
                                  date.fromisoformat(run_date))
        proposal = make_proposal(m.listing, pack)
        seo_result = apply_proposal(clients.etsy, db, cfg, m.listing, proposal, run_date)
        db.execute("""INSERT OR REPLACE INTO focus_history(run_date, listing_id, diagnosis, score, views_7d,
                      sales_7d, details) VALUES(?,?,?,?,?,?,?)""",
                   (run_date, m.listing_id, m.diagnosis, m.score, m.views_s, m.sales_s,
                    "; ".join(m.reasons)))
        focus_out.append({"metrics": m, "insight": insight, "pack": pack, "proposal": proposal,
                          "seo_result": seo_result})

    # 5. promote -------------------------------------------------------------------
    fetcher = ImageFetcher(cfg.path("data_dir") / "image_cache")
    pins_dir = cfg.path("site_dir") / "pins"
    pins = plan_and_render(db, cfg, run_date, [(f["metrics"], f["pack"]) for f in focus_out], metrics,
                           fetcher, pins_dir, rng)
    publish = None
    if channel == "api" and clients.pinterest is not None:
        try:
            publish = publish_due(db, cfg, clients.pinterest, fetcher, pins_dir, now)
        except Exception as exc:
            warnings.append(f"Pinterest publish failed: {exc}")
    csv_path = export_bulk_csv(db, cfg, run_date, cfg.path("reports_dir") / "pinterest-bulk-latest.csv")
    site_info = None
    if cfg.get("site.enabled", True):
        site_info = build_site(db, cfg, run_date, [m.listing for m in metrics])

    # 6. learn + report ---------------------------------------------------------------
    pulse = market_pulse(db, clients.etsy, cfg, run_date, metrics, shop_id)
    ctx = {
        "run_date": run_date, "shop_name": cfg.get("shop.name"), "symbol": symbol, "demo": cfg.demo,
        "kpis": kpis, "metrics": metrics, "focus": focus_out, "pins": pins, "channel": channel,
        "publish": publish, "csv_path": str(csv_path.relative_to(cfg.root)) if csv_path else None,
        "uplift": analysis.measure_uplift(db, cfg, run_date), "leaderboard": bandit.leaderboard(db),
        "pulse": pulse, "warnings": warnings,
        "llm": next((f["pack"]["source"] for f in focus_out if f["pack"].get("source") != "rules"), None),
    }
    paths = write_reports(ctx, cfg.path("reports_dir"))
    summary = build_summary(ctx)
    if notify:
        send_telegram(cfg, summary)
        send_email(cfg, f"{cfg.get('shop.name')} - daily report {run_date}", paths["md_text"], paths["html_text"])
    db.kv_set("last_run", now.isoformat(timespec="seconds"))
    db.close()
    return {"run_date": run_date, "focus": [f["metrics"].listing["title"] for f in focus_out],
            "pins": len(pins), "channel": channel, "report": paths["html"], "markdown": paths["markdown"],
            "site": site_info, "summary": summary, "warnings": warnings,
            "seo": [f["seo_result"] for f in focus_out]}


def run_publish(cfg: Config, clients: Clients | None = None, publish_all: bool = False) -> dict:
    clients = clients or build_clients(cfg)
    if resolve_channel(cfg) != "api":
        return {"skipped": "pinterest channel is not 'api'"}
    if clients.pinterest is None:
        return {"skipped": "Pinterest keys missing"}
    db = Database(cfg.path("db_file"))
    fetcher = ImageFetcher(cfg.path("data_dir") / "image_cache")
    try:
        return publish_due(db, cfg, clients.pinterest, fetcher, cfg.path("site_dir") / "pins",
                           publish_all=publish_all)
    finally:
        db.close()
