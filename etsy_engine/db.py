"""SQLite storage. One file (data/engine.db) holds every snapshot so trends survive between runs."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id INTEGER PRIMARY KEY,
    title TEXT, description TEXT, url TEXT,
    price REAL, currency TEXT, quantity INTEGER,
    tags TEXT, materials TEXT, image_urls TEXT,
    num_photos INTEGER, has_video INTEGER,
    taxonomy_id INTEGER, state TEXT,
    created_ts INTEGER, updated_ts INTEGER,
    views_lifetime INTEGER, favorites_lifetime INTEGER,
    last_seen TEXT
);
CREATE TABLE IF NOT EXISTS listing_snapshots (
    snap_date TEXT, listing_id INTEGER,
    views INTEGER, favorites INTEGER, price REAL, quantity INTEGER,
    PRIMARY KEY (snap_date, listing_id)
);
CREATE TABLE IF NOT EXISTS sales (
    transaction_id INTEGER PRIMARY KEY,
    receipt_id INTEGER, listing_id INTEGER,
    quantity INTEGER, price REAL, created_ts INTEGER
);
CREATE TABLE IF NOT EXISTS focus_history (
    run_date TEXT, listing_id INTEGER, diagnosis TEXT, score REAL,
    views_7d REAL, sales_7d REAL, details TEXT,
    PRIMARY KEY (run_date, listing_id)
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT, listing_id INTEGER, action_type TEXT,
    channel TEXT, details TEXT, external_id TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS seo_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT, listing_id INTEGER, applied INTEGER,
    old_title TEXT, new_title TEXT, old_tags TEXT, new_tags TEXT,
    old_description TEXT, new_description TEXT, rolled_back INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS market_snapshots (
    snap_date TEXT, listing_id INTEGER, keyword TEXT,
    competitor_count INTEGER, median_price REAL, p25_price REAL, p75_price REAL,
    our_price_percentile REAL, top_tags TEXT, top_phrases TEXT,
    PRIMARY KEY (snap_date, listing_id, keyword)
);
CREATE TABLE IF NOT EXISTS pin_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT, listing_id INTEGER, is_focus INTEGER,
    template TEXT, headline_style TEXT, image_path TEXT, image_variant TEXT, recipe TEXT,
    title TEXT, description TEXT, alt_text TEXT, link TEXT, landing_link TEXT, board TEXT,
    channel TEXT, status TEXT DEFAULT 'queued', scheduled_slot INTEGER DEFAULT 0,
    pin_id TEXT, error TEXT, posted_at TEXT
);
CREATE TABLE IF NOT EXISTS pin_stats (
    pin_id TEXT PRIMARY KEY, listing_id INTEGER, template TEXT, headline_style TEXT,
    impressions INTEGER DEFAULT 0, saves INTEGER DEFAULT 0,
    pin_clicks INTEGER DEFAULT 0, outbound_clicks INTEGER DEFAULT 0,
    synced_at TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT
);
"""


def today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def days_ago_str(days: int, ref: str | None = None) -> str:
    base = date.fromisoformat(ref) if ref else datetime.now(timezone.utc).date()
    return (base - timedelta(days=days)).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- generic helpers -------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, tuple(params))
        self.conn.commit()
        return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self.conn.close()

    # ---- key/value -------------------------------------------------------
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute("INSERT OR REPLACE INTO kv(key, value) VALUES(?, ?)", (key, json.dumps(value)))

    # ---- listings --------------------------------------------------------
    def upsert_listing(self, l: dict, seen_date: str) -> None:
        self.execute(
            """INSERT INTO listings(listing_id, title, description, url, price, currency, quantity,
                   tags, materials, image_urls, num_photos, has_video, taxonomy_id, state,
                   created_ts, updated_ts, views_lifetime, favorites_lifetime, last_seen)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(listing_id) DO UPDATE SET
                   title=excluded.title, description=excluded.description, url=excluded.url,
                   price=excluded.price, currency=excluded.currency, quantity=excluded.quantity,
                   tags=excluded.tags, materials=excluded.materials, image_urls=excluded.image_urls,
                   num_photos=excluded.num_photos, has_video=excluded.has_video,
                   taxonomy_id=excluded.taxonomy_id, state=excluded.state,
                   created_ts=excluded.created_ts, updated_ts=excluded.updated_ts,
                   views_lifetime=excluded.views_lifetime,
                   favorites_lifetime=excluded.favorites_lifetime, last_seen=excluded.last_seen""",
            (
                l["listing_id"], l.get("title", ""), l.get("description", ""), l.get("url", ""),
                l.get("price", 0.0), l.get("currency", "USD"), l.get("quantity", 0),
                json.dumps(l.get("tags", [])), json.dumps(l.get("materials", [])),
                json.dumps(l.get("image_urls", [])), len(l.get("image_urls", [])),
                1 if l.get("has_video") else 0, l.get("taxonomy_id"), l.get("state", "active"),
                l.get("created_ts", 0), l.get("updated_ts", 0),
                l.get("views", 0), l.get("num_favorers", 0), seen_date,
            ),
        )
        self.execute(
            """INSERT OR REPLACE INTO listing_snapshots(snap_date, listing_id, views, favorites, price, quantity)
               VALUES(?,?,?,?,?,?)""",
            (seen_date, l["listing_id"], l.get("views", 0), l.get("num_favorers", 0),
             l.get("price", 0.0), l.get("quantity", 0)),
        )

    def active_listings(self, seen_date: str) -> list[dict]:
        rows = self.query(
            "SELECT * FROM listings WHERE state='active' AND last_seen=? ORDER BY listing_id", (seen_date,)
        )
        for r in rows:
            for key in ("tags", "materials", "image_urls"):
                r[key] = json.loads(r[key] or "[]")
        return rows

    def listing(self, listing_id: int) -> dict | None:
        r = self.one("SELECT * FROM listings WHERE listing_id=?", (listing_id,))
        if r:
            for key in ("tags", "materials", "image_urls"):
                r[key] = json.loads(r[key] or "[]")
        return r

    def snapshot_on_or_before(self, listing_id: int, snap_date: str) -> dict | None:
        return self.one(
            """SELECT * FROM listing_snapshots WHERE listing_id=? AND snap_date<=?
               ORDER BY snap_date DESC LIMIT 1""",
            (listing_id, snap_date),
        )

    def first_snapshot(self, listing_id: int) -> dict | None:
        return self.one(
            "SELECT * FROM listing_snapshots WHERE listing_id=? ORDER BY snap_date ASC LIMIT 1",
            (listing_id,),
        )

    # ---- sales -----------------------------------------------------------
    def upsert_sale(self, s: dict) -> None:
        self.execute(
            """INSERT OR REPLACE INTO sales(transaction_id, receipt_id, listing_id, quantity, price, created_ts)
               VALUES(?,?,?,?,?,?)""",
            (s["transaction_id"], s.get("receipt_id"), s.get("listing_id"), s.get("quantity", 1),
             s.get("price", 0.0), s.get("created_ts", 0)),
        )

    def sales_between(self, listing_id: int, start_ts: int, end_ts: int) -> tuple[int, float]:
        row = self.one(
            """SELECT COALESCE(SUM(quantity),0) AS units, COALESCE(SUM(quantity*price),0) AS revenue
               FROM sales WHERE listing_id=? AND created_ts>=? AND created_ts<?""",
            (listing_id, start_ts, end_ts),
        )
        return int(row["units"]), float(row["revenue"])

    def latest_sale_ts(self) -> int:
        row = self.one("SELECT MAX(created_ts) AS ts FROM sales")
        return int(row["ts"] or 0)

    # ---- marketing log ---------------------------------------------------
    def log_action(self, run_date: str, listing_id: int | None, action_type: str, channel: str,
                   details: dict | None = None, external_id: str | None = None) -> None:
        self.execute(
            """INSERT INTO actions(run_date, listing_id, action_type, channel, details, external_id, created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (run_date, listing_id, action_type, channel, json.dumps(details or {}), external_id,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )

    def last_focus_date(self, listing_id: int) -> str | None:
        row = self.one("SELECT MAX(run_date) AS d FROM focus_history WHERE listing_id=?", (listing_id,))
        return row["d"] if row else None

    def last_pinned_date(self, listing_id: int) -> str | None:
        row = self.one(
            "SELECT MAX(run_date) AS d FROM pin_queue WHERE listing_id=? AND status IN ('queued','posted','exported')",
            (listing_id,),
        )
        return row["d"] if row else None

    def last_seo_change(self, listing_id: int) -> dict | None:
        return self.one(
            """SELECT * FROM seo_changes WHERE listing_id=? AND applied=1 AND rolled_back=0
               ORDER BY id DESC LIMIT 1""",
            (listing_id,),
        )
