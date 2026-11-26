"""SEO proposals for weak listings, with optional safe auto-apply and one-command rollback."""
from __future__ import annotations

import json
import logging

from .config import Config
from .db import Database, days_ago_str
from .http import ApiError

log = logging.getLogger(__name__)


def make_proposal(listing: dict, pack: dict) -> dict:
    seo = pack["seo"]
    old_tags = [t.lower().strip() for t in listing.get("tags", [])]
    new_tags = seo["tags"]
    return {
        "listing_id": listing["listing_id"],
        "old_title": listing.get("title", ""),
        "new_title": seo["title"],
        "old_tags": old_tags,
        "new_tags": new_tags,
        "added_tags": [t for t in new_tags if t not in old_tags],
        "removed_tags": [t for t in old_tags if t not in new_tags],
        "description_intro": seo.get("description_intro", ""),
        "rationale": seo.get("rationale", []),
        "changed": seo["title"] != listing.get("title", "") or set(new_tags) != set(old_tags),
    }


def apply_proposal(source, db: Database, cfg: Config, listing: dict, proposal: dict, run_date: str) -> dict:
    """Applies only if seo.auto_apply is on and the listing wasn't changed recently."""
    result = {"applied": False, "reason": ""}
    fields: dict = {}
    new_description = listing.get("description", "")
    if cfg.get("seo.apply_title", True) and proposal["new_title"] != proposal["old_title"]:
        fields["title"] = proposal["new_title"]
    if cfg.get("seo.apply_tags", True) and proposal["added_tags"]:
        fields["tags"] = proposal["new_tags"]
    intro = proposal.get("description_intro", "").strip()
    if cfg.get("seo.apply_description_intro", False) and intro and intro[:60] not in new_description:
        new_description = f"{intro}\n\n{new_description}".strip()
        fields["description"] = new_description

    if not cfg.get("seo.auto_apply", False):
        result["reason"] = "suggest-only mode (seo.auto_apply: false)"
    elif not fields:
        result["reason"] = "nothing to change"
    else:
        last = db.last_seo_change(listing["listing_id"])
        min_gap = int(cfg.get("seo.min_days_between_changes", 30))
        if last and last["run_date"] > days_ago_str(min_gap, run_date):
            result["reason"] = f"last change on {last['run_date']} - waiting {min_gap} days for Etsy to re-rank"
        else:
            try:
                source.update_listing(listing["listing_id"], fields)
                result.update({"applied": True, "reason": "applied", "fields": sorted(fields)})
            except ApiError as exc:
                result["reason"] = f"Etsy rejected the update: {exc}"
                log.warning("SEO update for %s failed: %s", listing["listing_id"], exc)

    db.execute(
        """INSERT INTO seo_changes(run_date, listing_id, applied, old_title, new_title, old_tags, new_tags,
               old_description, new_description) VALUES(?,?,?,?,?,?,?,?,?)""",
        (run_date, listing["listing_id"], int(result["applied"]), proposal["old_title"],
         fields.get("title", proposal["old_title"]), json.dumps(proposal["old_tags"]),
         json.dumps(fields.get("tags", proposal["old_tags"])), listing.get("description", ""), new_description),
    )
    db.log_action(run_date, listing["listing_id"], "seo_applied" if result["applied"] else "seo_suggested",
                  "etsy", {"reason": result["reason"], "added_tags": proposal["added_tags"]})
    return result


def rollback(source, db: Database, listing_id: int) -> dict:
    last = db.last_seo_change(listing_id)
    if not last:
        return {"ok": False, "reason": "no applied SEO change found for this listing"}
    fields = {"title": last["old_title"], "tags": json.loads(last["old_tags"] or "[]")}
    if last["old_description"] and last["old_description"] != last["new_description"]:
        fields["description"] = last["old_description"]
    source.update_listing(listing_id, fields)
    db.execute("UPDATE seo_changes SET rolled_back=1 WHERE id=?", (last["id"],))
    return {"ok": True, "restored": fields}
