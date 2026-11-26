import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from etsy_engine import analysis
from etsy_engine.db import Database, days_ago_str, today_str
from etsy_engine.demo import DemoEtsy, DemoPinterest, seed_history
from etsy_engine.pin_designer import ImageFetcher
from etsy_engine.pinterest_campaign import plan_and_render, publish_due
from etsy_engine.pipeline import Clients, run_daily
from etsy_engine.seo import apply_proposal, make_proposal, rollback
from etsy_engine.sync import sync_shop

TODAY = today_str()


def at(hour):
    d = datetime.now(timezone.utc).date()
    return datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc)


def _shop(cfg, db, day=None):
    day = day or today_str()
    src = DemoEtsy()
    seed_history(db, src)
    sync_shop(src, db, day)
    return src, analysis.compute_metrics(db, cfg, day)


def test_weakest_listing_is_picked_and_diagnosed(cfg, db):
    _, metrics = _shop(cfg, db)
    focus = analysis.pick_focus(db, metrics, cfg, TODAY)
    assert len(focus) == 1
    weakest = focus[0]
    assert weakest.sales_w == 0 and weakest.diagnosis == analysis.TRAFFIC
    strong = max(metrics, key=lambda m: m.revenue_w)
    assert strong.score < weakest.score


def test_focus_cooldown_rotates_products(cfg, db):
    _, metrics = _shop(cfg, db)
    first = analysis.pick_focus(db, metrics, cfg, TODAY)[0]
    db.execute("INSERT INTO focus_history(run_date, listing_id, diagnosis, score) VALUES(?,?,?,?)",
               (days_ago_str(1), first.listing_id, "traffic", 1.0))
    second = analysis.pick_focus(db, metrics, cfg, TODAY)[0]
    assert second.listing_id != first.listing_id


def test_seo_suggest_apply_and_rollback(cfg, db):
    src, metrics = _shop(cfg, db)
    m = max(metrics, key=lambda x: x.score)
    pack = {"seo": {"title": "New Better Title, Gift for Her", "tags": ["gift for her", "earrings"],
                    "description_intro": "", "rationale": []}}
    prop = make_proposal(m.listing, pack)
    assert not apply_proposal(src, db, cfg, m.listing, prop, TODAY)["applied"]  # suggest-only default
    assert src.updates == []

    cfg.data["seo"]["auto_apply"] = True
    res = apply_proposal(src, db, cfg, m.listing, prop, TODAY)
    assert res["applied"] and src.updates[-1][1]["title"] == "New Better Title, Gift for Her"
    again = apply_proposal(src, db, cfg, m.listing, prop, days_ago_str(-5))
    assert not again["applied"] and "waiting" in again["reason"]  # 30-day guard

    rb = rollback(src, db, m.listing_id)
    assert rb["ok"] and src.updates[-1][1]["title"] == m.listing["title"]


def test_pins_planned_and_published_by_slot(cfg, db, tmp_path):
    cfg.data["pinterest"]["channel"] = "api"
    _, metrics = _shop(cfg, db)
    focus = analysis.pick_focus(db, metrics, cfg, TODAY)
    from etsy_engine.copywriter import build_content_pack

    packs = [(m, build_content_pack(None, m.listing, m, None, 5)) for m in focus]
    fetcher = ImageFetcher(tmp_path / "cache")
    rows = plan_and_render(db, cfg, TODAY, packs, metrics, fetcher, tmp_path / "pins")
    assert len(rows) == 10
    assert sum(r["is_focus"] for r in rows) == 5
    assert all((tmp_path / "pins" / r["image_path"]).exists() for r in rows)

    client = DemoPinterest()
    early = publish_due(db, cfg, client, fetcher, tmp_path / "pins",
                        now=at(1))
    assert early["posted"] == 2  # slot 0 only (10 pins / 5 slots)
    late = publish_due(db, cfg, client, fetcher, tmp_path / "pins",
                       now=at(23))
    assert late["posted"] == 8 and len(client.created) == 10
    assert publish_due(db, cfg, client, fetcher, tmp_path / "pins",
                       now=at(23))["posted"] == 0  # idempotent


def test_full_demo_run(demo_cfg):
    result = run_daily(demo_cfg, notify=False, now=at(6))
    assert result["pins"] == 10 and result["focus"]
    site = demo_cfg.path("site_dir")
    feed = ET.parse(site / "feed.xml").getroot()
    items = feed.findall("./channel/item")
    assert len(items) == 10
    assert items[0].find("enclosure").get("url").startswith("https://example.github.io/etsy-pins/pins/")
    assert (site / "index.html").exists() and list((site / "p").glob("*.html"))
    md = (demo_cfg.path("reports_dir") / "latest.md").read_text()
    assert "Aaj ka focus product" in md and "13 tags" in md
    csv_text = (demo_cfg.path("reports_dir") / "pinterest-bulk-latest.csv").read_text()
    assert csv_text.startswith("Title,Media URL,Pinterest board")


def test_demo_api_channel_posts_first_slot(demo_cfg):
    demo_cfg.data["pinterest"]["channel"] = "api"
    clients = Clients(DemoEtsy(), DemoPinterest(), None)
    from etsy_engine.llm import LLM

    clients.llm = LLM(demo_cfg)
    result = run_daily(demo_cfg, clients, notify=False, now=at(1))
    assert result["channel"] == "api"
    db = Database(demo_cfg.path("db_file"))
    posted = db.query("SELECT * FROM pin_queue WHERE run_date=? AND status='posted'", (TODAY,))
    assert len(posted) == 2 and len(clients.pinterest.created) == 2
    assert json.loads(posted[0]["recipe"])["template"]
