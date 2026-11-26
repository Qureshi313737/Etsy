"""Self-learning: Thompson sampling over pin templates and headline styles.

Every pin's Pinterest analytics (impressions, saves, outbound clicks) feed a Beta posterior per
arm. Arms that win get picked more often, but losers still get occasional tries - so the
engine keeps adapting as tastes and seasons change.
"""
from __future__ import annotations

import random

from .db import Database


def arm_stats(db: Database, column: str) -> dict[str, dict]:
    if column not in ("template", "headline_style"):
        raise ValueError(column)
    rows = db.query(
        f"""SELECT {column} AS arm, COUNT(*) AS pins, SUM(impressions) AS imp, SUM(saves) AS saves,
                   SUM(outbound_clicks) AS clicks, SUM(pin_clicks) AS pin_clicks
            FROM pin_stats GROUP BY {column}"""
    )
    return {r["arm"]: {k: (r[k] or 0) for k in ("pins", "imp", "saves", "clicks", "pin_clicks")} for r in rows}


def engagement(stat: dict) -> float:
    # outbound click = someone went to Etsy (best); a save keeps the pin circulating
    return stat.get("clicks", 0) + 0.5 * stat.get("saves", 0) + 0.2 * stat.get("pin_clicks", 0)


def choose(arms: list[str], stats: dict[str, dict], k: int, rng: random.Random | None = None) -> list[str]:
    rng = rng or random.Random()
    picks: list[str] = []
    while len(picks) < k:
        samples = []
        for arm in arms:
            s = stats.get(arm, {})
            success = engagement(s)
            trials = max(s.get("imp", 0) / 50.0, success)  # scale impressions so priors aren't swamped
            samples.append((rng.betavariate(1 + success, 1 + trials - success), arm))
        samples.sort(reverse=True)
        for _, arm in samples:  # prefer variety inside one day
            if arm not in picks or len(picks) >= len(arms):
                picks.append(arm)
                break
    return picks


def leaderboard(db: Database) -> dict[str, list[dict]]:
    out = {}
    for col in ("template", "headline_style"):
        rows = []
        for arm, s in arm_stats(db, col).items():
            rate = engagement(s) / s["imp"] if s["imp"] else 0.0
            rows.append({"arm": arm, **s, "engagement_rate": rate})
        out[col] = sorted(rows, key=lambda r: -r["engagement_rate"])
    return out


def best_image_index(db: Database, listing_id: int) -> int | None:
    """Which of a listing's photos performs best as the main pin image (thumbnail A/B test)."""
    rows = db.query(
        """SELECT q.image_variant AS img, SUM(s.impressions) imp, SUM(s.saves) saves, SUM(s.outbound_clicks) clicks
           FROM pin_queue q JOIN pin_stats s ON s.pin_id = q.pin_id
           WHERE q.listing_id=? GROUP BY q.image_variant""",
        (listing_id,),
    )
    scored = [(engagement({"saves": r["saves"] or 0, "clicks": r["clicks"] or 0}) / r["imp"], r["img"])
              for r in rows if (r["imp"] or 0) >= 200]
    if len(scored) < 2:
        return None
    best = max(scored)[1]
    try:
        return int(str(best).split(":")[-1])
    except ValueError:
        return None
