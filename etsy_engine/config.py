"""Configuration loading: config.yaml (non-secret settings) + environment (secrets)."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "shop": {
        "name": "My Etsy Shop",
        "currency_symbol": "$",
        "brand_color": "#F1641E",
        "cta_text": "Shop on Etsy",
    },
    "analysis": {
        "window_days": 30,
        "short_window_days": 7,
        "min_listing_age_days": 0,
        "focus_count": 1,
        "focus_cooldown_days": 3,
        "weights": {
            "views": 0.35,
            "sales": 0.30,
            "conversion": 0.15,
            "favorites": 0.10,
            "quality": 0.10,
        },
    },
    "market": {
        "enabled": True,
        "competitors_per_keyword": 100,
        "keywords_per_listing": 3,
        "shop_scan_every_days": 7,
    },
    "seo": {
        "auto_apply": False,
        "apply_title": True,
        "apply_tags": True,
        "apply_description_intro": False,
        "min_days_between_changes": 30,
    },
    "llm": {
        "providers": ["gemini", "groq", "anthropic"],
        "gemini_model": "gemini-flash-latest",
        "gemini_fallback_models": ["gemini-flash-lite-latest"],
        "groq_model": "llama-3.3-70b-versatile",
        "anthropic_model": "claude-opus-5-5",
        "temperature": 0.7,
        "timeout_seconds": 60,
    },
    "pinterest": {
        "channel": "auto",
        "pins_per_day": 10,
        "publish_runs_per_day": 5,
        "focus_share": 0.5,
        "min_days_between_same_listing": 2,
        "default_board": "Etsy Finds",
        "board_rules": [],
        "utm_campaign": "etsy_engine",
        "use_sandbox": False,
        "analytics_lookback_days": 30,
    },
    "site": {
        "enabled": True,
        "base_url": "",
        "title": "",
        "link_target": "landing",
        "pinterest_verify": "",
        "max_items_in_feed": 50,
        "keep_pin_images": 300,
    },
    "notify": {
        "telegram": True,
        "email": False,
    },
    "paths": {
        "data_dir": "data",
        "reports_dir": "reports",
        "site_dir": "site",
        "db_file": "data/engine.db",
        "token_file": "data/tokens.enc",
    },
}

SECRET_KEYS = [
    "ETSY_API_KEY",
    "ETSY_SHARED_SECRET",
    "ETSY_REFRESH_TOKEN",
    "ETSY_SHOP_ID",
    "ETSY_REDIRECT_URI",
    "PINTEREST_APP_ID",
    "PINTEREST_APP_SECRET",
    "PINTEREST_REFRESH_TOKEN",
    "PINTEREST_ACCESS_TOKEN",
    "PINTEREST_REDIRECT_URI",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "REPORT_EMAIL_TO",
    "TOKEN_ENCRYPTION_KEY",
]


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class Config:
    data: dict[str, Any]
    secrets: dict[str, str] = field(default_factory=dict)
    root: Path = ROOT
    demo: bool = False

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def secret(self, key: str) -> str:
        return (self.secrets.get(key) or "").strip()

    def has(self, *keys: str) -> bool:
        return all(self.secret(k) for k in keys)

    def path(self, key: str) -> Path:
        p = Path(self.get(f"paths.{key}"))
        return p if p.is_absolute() else self.root / p


def load_config(config_path: str | os.PathLike | None = None, demo: bool = False,
                root: Path | None = None) -> Config:
    root = Path(root) if root else ROOT
    try:  # .env is optional and only for local runs
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
    except ImportError:
        pass

    path = Path(config_path) if config_path else root / "config.yaml"
    user_cfg: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            user_cfg = yaml.safe_load(fh) or {}
    data = deep_merge(DEFAULTS, user_cfg)
    secrets = {k: os.environ.get(k, "") for k in SECRET_KEYS}
    if demo:
        # Demo mode never touches real accounts and keeps its files separate.
        secrets = {k: "" for k in SECRET_KEYS}
        data["paths"] = {
            "data_dir": "demo_output/data",
            "reports_dir": "demo_output/reports",
            "site_dir": "demo_output/site",
            "db_file": "demo_output/data/engine.db",
            "token_file": "demo_output/data/tokens.enc",
        }
        if not data["site"].get("base_url"):
            data["site"]["base_url"] = "https://example.github.io/etsy-pins"
    return Config(data=data, secrets=secrets, root=root, demo=demo)
