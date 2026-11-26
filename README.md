# 🚀 Etsy Growth Engine

A free, self-hosted automation system that grows an Etsy shop's sales.
Every day it finds your **weakest product**, studies the live market, fixes its SEO,
promotes it on **Pinterest** with auto-designed pins, learns what works, and sends you a report.

**Cost: ₹0 / $0** - runs on GitHub Actions (free minutes), GitHub Pages, free API tiers.
👉 **Setup (Hinglish, step-by-step): [SETUP_GUIDE.md](SETUP_GUIDE.md)**

```bash
pip install -r requirements.txt
python -m etsy_engine demo      # full run on a fake shop - no keys needed
```

---

## What happens every day

```
 ┌────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐   ┌─────────────┐
 │ 1. SYNC    │──▶│ 2. ANALYSE   │──▶│ 3. RESEARCH   │──▶│ 4. FIX       │──▶│ 5. PROMOTE  │
 │ Etsy API:  │   │ views, favs, │   │ Etsy search:  │   │ SEO title,   │   │ 10 pins/day │
 │ listings,  │   │ sales, conv. │   │ competitors,  │   │ 13 tags,     │   │ (5 designs) │
 │ sales      │   │ -> weakest   │   │ prices, tags, │   │ description, │   │ RSS / API / │
 │ (snapshots)│   │ product +    │   │ Pinterest     │   │ to-do list   │   │ bulk CSV +  │
 └────────────┘   │ diagnosis    │   │ trends        │   │ (auto-apply  │   │ landing site│
                  └──────────────┘   └───────────────┘   │  optional)   │   └──────┬──────┘
                                                         └──────────────┘          │
 ┌──────────────────────────────────────────────────────────────────────────┐      │
 │ 6. LEARN + REPORT: pin analytics -> Thompson-sampling picks best designs │◀─────┘
 │ & headlines; before/after uplift of each push; Markdown/HTML + Telegram  │
 └──────────────────────────────────────────────────────────────────────────┘
```

### 1. Weak-product detection
For every active listing: 30-day and 7-day views & favourites (from daily snapshots), sales, revenue,
conversion, favourite rate, traffic trend, and a **listing-quality audit** (title length, 13 tags used,
long-tail tags, photo count, video, description). A weighted percentile score ranks the weakest
products; a cooldown rotates the focus so every product gets pushed.

Each focus product gets a **diagnosis** that decides the playbook:

| Diagnosis | Meaning | Playbook |
|---|---|---|
| `traffic` | nobody sees it | SEO rewrite from competitor data + heavy Pinterest push |
| `conversion` | seen, not bought | price positioning, photo/description fixes, sale/free-shipping to-dos |
| `appeal` | low favourites | thumbnail A/B via pins, first-photo advice |
| `momentum` | doing OK | scale with more pins |

### 2. Market research (official Etsy API only)
Searches Etsy for the product's own keywords and reads the top competitors: competition size,
price quartiles and your position, **tags and title phrases weighted by popularity**, the tags you
are missing, best-performing competitor examples, and matching Pinterest trends.
A weekly **market pulse** tracks every product's keyword.

### 3. SEO & copy
A free LLM (Gemini / Groq; Claude optional) writes the title, 13 tags, description opening,
pin copy and social captions from the real market data. Without any key a rule-based engine does
it. All output is validated against Etsy rules (140-char title, 13 tags x 20 chars, allowed
characters). `seo.auto_apply: true` pushes title/tags to Etsy - at most once per 30 days per
listing, logged, and reversible with `python -m etsy_engine rollback <id>`.

### 4. Pinterest engine
* 5 pin templates rendered with Pillow (1000x1500): `banner`, `split`, `collage`, `frame`, `label`.
* Half the daily pins go to the focus product (different photos, headlines, designs), the rest
  rotate through the catalogue.
* Board routing by keywords, UTM-tagged links so Etsy Stats shows Pinterest traffic.
* Channels: **RSS auto-publish** (free, no approval), **bulk CSV** with scheduled dates, or the
  **Pinterest API** (Standard access) posting through 5 time slots a day.
* **Self-learning**: pin impressions/saves/outbound clicks feed a Thompson-sampling bandit that
  picks templates and headline styles; it also finds which product photo makes the best thumbnail.

### 5. Free mini-site (GitHub Pages)
Landing page per product (Open Graph + product price tags, indexable by Google), `sitemap.xml`,
and RSS feeds per board that Pinterest turns into pins automatically.

### 6. Report
`reports/YYYY-MM-DD.md` + `reports/latest.html` (phone-friendly), Telegram summary, optional email:
shop KPIs, focus product diagnosis, market analysis, copy-paste SEO, to-do list for things the API
can't do, pin plan, learning leaderboard, uplift of previous pushes, weakest-5 table.

---

## Commands

| Command | What it does |
|---|---|
| `python -m etsy_engine demo [--channel api\|rss\|csv]` | full pipeline on a fake shop |
| `python -m etsy_engine check` | which keys are set / missing |
| `python -m etsy_engine gen-key` | create `TOKEN_ENCRYPTION_KEY` |
| `python -m etsy_engine auth etsy` | one-time Etsy OAuth -> refresh token |
| `python -m etsy_engine auth pinterest` | one-time Pinterest OAuth -> refresh token |
| `python -m etsy_engine daily` | the daily run |
| `python -m etsy_engine publish [--all]` | post due Pinterest pins (API channel) |
| `python -m etsy_engine analyze` | read-only weakness ranking |
| `python -m etsy_engine rollback <listing_id>` | undo the last auto SEO change |

All settings live in [`config.yaml`](config.yaml); secrets in GitHub Secrets (or `.env` locally - see `.env.example`).

## Automation (GitHub Actions)

| Workflow | When | Job |
|---|---|---|
| `daily.yml` | daily 02:17 UTC + manual | full run, commits `data/` + `reports/`, deploys the pins site |
| `publish-pins.yml` | 4x/day (if `PINTEREST_API_ENABLED=true`) | posts the next slot of pins |
| `tests.yml` | on push | test suite |

State (`data/engine.db` SQLite history, `data/tokens.enc` encrypted tokens) is committed back to the
private repo by the workflow, so trends and learning survive between runs.

## Project layout

```
etsy_engine/
  etsy_client.py        Etsy Open API v3 (OAuth2 PKCE, keystring:secret header, retries)
  pinterest_client.py   Pinterest API v5 (boards, pins, analytics, trends)
  sync.py  db.py        snapshots of listings & sales in SQLite
  analysis.py           metrics, quality audit, weakness score, diagnosis, uplift
  market.py             competitor research via Etsy search
  copywriter.py llm.py  SEO + pin + social copy (Gemini/Groq/Claude or rules)
  seo.py                proposals, guarded auto-apply, rollback
  pin_designer.py       Pillow pin templates
  bandit.py             Thompson-sampling learning loop
  pinterest_campaign.py pin planning, slots, publishing, bulk CSV
  site_builder.py       landing pages, sitemap, RSS feeds
  report.py notify.py   Markdown/HTML report, Telegram, email
  pipeline.py cli.py    orchestration + commands
  demo.py               offline fake shop
tests/                  pytest suite (python -m pytest -q)
```

## Safety & rules
* Official APIs only - no scraping (against Etsy's terms).
* SEO auto-apply is **off** by default; every change is logged and reversible.
* Conservative pin volume (default 10/day) and no duplicate posting across channels.
* Secrets never live in the repo; rotating tokens are stored encrypted.
