"""Command line:  python -m etsy_engine <command>

  demo                 full pipeline on a fake shop (no keys needed)
  check                which keys are set and what is still missing
  gen-key              create TOKEN_ENCRYPTION_KEY
  auth etsy            one-time Etsy login -> prints ETSY_REFRESH_TOKEN
  auth pinterest       one-time Pinterest login -> prints PINTEREST_REFRESH_TOKEN
  daily                the daily run (sync, analyse, SEO, pins, site, report)
  publish [--all]      post queued Pinterest pins whose time slot has come
  analyze              read-only: print the weakness ranking
  rollback LISTING_ID  undo the last automatic SEO change of a listing
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import load_config


def _print_table(rows: list[dict], cols: list[str]) -> None:
    widths = {c: max(len(c), *(len(str(r.get(c, ""))[:50]) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, ""))[:50].ljust(widths[c]) for c in cols))


def cmd_check(cfg) -> int:
    groups = [
        ("Etsy (zaroori)", ["ETSY_API_KEY", "ETSY_SHARED_SECRET", "ETSY_REFRESH_TOKEN"]),
        ("Token store (zaroori for GitHub Actions)", ["TOKEN_ENCRYPTION_KEY"]),
        ("Pinterest API (optional - RSS/CSV free channels bina iske chalte hain)",
         ["PINTEREST_APP_ID", "PINTEREST_APP_SECRET", "PINTEREST_REFRESH_TOKEN"]),
        ("AI copywriter (optional, free)", ["GEMINI_API_KEY", "GROQ_API_KEY"]),
        ("Claude (optional, paid)", ["ANTHROPIC_API_KEY"]),
        ("Telegram report (optional, free)", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]),
        ("Email report (optional)", ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "REPORT_EMAIL_TO"]),
    ]
    for title, keys in groups:
        print(f"\n{title}")
        for k in keys:
            print(f"  {'✅' if cfg.secret(k) else '❌'} {k}")
    from .pinterest_campaign import resolve_channel

    print(f"\nPinterest channel in use: {resolve_channel(cfg)}")
    print(f"Site base_url: {cfg.get('site.base_url') or '(not set)'}")
    print("\nSETUP_GUIDE.md mein har key ka step-by-step tarika hai.")
    return 0


def cmd_auth(cfg, service: str) -> int:
    from .oauth import DEFAULT_REDIRECT, run_etsy_flow, run_pinterest_flow

    if service == "etsy":
        if not cfg.secret("ETSY_API_KEY"):
            print("Pehle .env mein ETSY_API_KEY daalo (Etsy app ka keystring).")
            return 1
        tok = run_etsy_flow(cfg.secret("ETSY_API_KEY"), cfg.secret("ETSY_REDIRECT_URI") or DEFAULT_REDIRECT)
        print("\n✅ Etsy connected. Yeh value GitHub secret ETSY_REFRESH_TOKEN mein daalo:\n")
        print(tok["refresh_token"])
        user_id = str(tok.get("access_token", "")).split(".")[0]
        if user_id.isdigit():
            print(f"\n(Etsy user id: {user_id})")
    else:
        if not cfg.has("PINTEREST_APP_ID", "PINTEREST_APP_SECRET"):
            print("Pehle .env mein PINTEREST_APP_ID aur PINTEREST_APP_SECRET daalo.")
            return 1
        tok = run_pinterest_flow(cfg.secret("PINTEREST_APP_ID"), cfg.secret("PINTEREST_APP_SECRET"),
                                 cfg.secret("PINTEREST_REDIRECT_URI") or DEFAULT_REDIRECT)
        print("\n✅ Pinterest connected. Yeh value GitHub secret PINTEREST_REFRESH_TOKEN mein daalo:\n")
        print(tok.get("refresh_token") or tok.get("access_token"))
    return 0


def cmd_analyze(cfg) -> int:
    from . import analysis
    from .db import Database, today_str
    from .pipeline import build_clients
    from .sync import sync_shop

    clients = build_clients(cfg)
    if clients.etsy is None:
        print("Etsy keys missing - `check` chalao.")
        return 1
    db = Database(cfg.path("db_file"))
    run_date = today_str()
    if cfg.demo:
        from .demo import seed_history

        seed_history(db, clients.etsy)
    sync_shop(clients.etsy, db, run_date)
    metrics = sorted(analysis.compute_metrics(db, cfg, run_date), key=lambda m: -m.score)
    _print_table([m.to_dict() for m in metrics],
                 ["listing_id", "score", "diagnosis", "views_w", "sales_w", "conv", "quality", "title"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etsy_engine", description="Free Etsy sales automation engine")
    parser.add_argument("--config", help="path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_demo = sub.add_parser("demo")
    p_demo.add_argument("--channel", choices=["api", "rss", "csv"], help="Pinterest channel to simulate")
    sub.add_parser("check")
    sub.add_parser("gen-key")
    p_auth = sub.add_parser("auth")
    p_auth.add_argument("service", choices=["etsy", "pinterest"])
    p_daily = sub.add_parser("daily")
    p_daily.add_argument("--no-notify", action="store_true")
    p_pub = sub.add_parser("publish")
    p_pub.add_argument("--all", action="store_true", help="post every queued pin now")
    p_an = sub.add_parser("analyze")
    p_an.add_argument("--demo", action="store_true")
    p_rb = sub.add_parser("rollback")
    p_rb.add_argument("listing_id", type=int)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "gen-key":
        from .secrets_store import generate_key

        print("TOKEN_ENCRYPTION_KEY =", generate_key())
        print("Isko GitHub > Settings > Secrets and variables > Actions mein save karo. Kisi ko share mat karna.")
        return 0

    demo = args.cmd == "demo" or getattr(args, "demo", False)
    cfg = load_config(args.config, demo=demo)

    if args.cmd == "check":
        return cmd_check(cfg)
    if args.cmd == "auth":
        return cmd_auth(cfg, args.service)
    if args.cmd == "analyze":
        return cmd_analyze(cfg)
    if args.cmd in ("demo", "daily"):
        from .pipeline import run_daily

        if args.cmd == "demo" and args.channel:
            cfg.data["pinterest"]["channel"] = args.channel
        result = run_daily(cfg, notify=args.cmd == "daily" and not args.no_notify)
        print("\n" + result["summary"])
        print(f"\nReport: {result['report']}")
        if result.get("site"):
            print(f"Site:   {result['site']['dir']}/index.html")
        return 0
    if args.cmd == "publish":
        from .pipeline import run_publish

        print(json.dumps(run_publish(cfg, publish_all=args.all), indent=2))
        return 0
    if args.cmd == "rollback":
        from .db import Database
        from .pipeline import build_clients
        from .seo import rollback

        db = Database(cfg.path("db_file"))
        print(json.dumps(rollback(build_clients(cfg).etsy, db, args.listing_id), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
