"""Pull the latest shop data (listings + sales) into the local database."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .db import Database

log = logging.getLogger(__name__)

SALES_BACKFILL_DAYS = 120


def sync_shop(source, db: Database, run_date: str) -> dict:
    """`source` is EtsyClient (or the demo stand-in with the same methods)."""
    listings = list(source.iter_active_listings())
    for l in listings:
        db.upsert_listing(l, run_date)

    latest = db.latest_sale_ts()
    now = int(datetime.now(timezone.utc).timestamp())
    # re-read the last 3 days every run so late status changes are picked up
    min_created = max(latest - 3 * 86400, now - SALES_BACKFILL_DAYS * 86400) if latest else now - SALES_BACKFILL_DAYS * 86400
    sales = 0
    for sale in source.iter_sales(min_created):
        db.upsert_sale(sale)
        sales += 1
    log.info("Synced %d active listings and %d sale rows", len(listings), sales)
    return {"listings": len(listings), "sales_rows": sales}
