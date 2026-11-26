"""Daily report: Markdown (committed to the repo), HTML (readable on phone) and a short chat summary."""
from __future__ import annotations

import html as html_lib
import re
from pathlib import Path

from .analysis import DIAGNOSIS_LABELS
from .market import price_advice
from .text_utils import truncate


def _money(v: float, s: str) -> str:
    return f"{s}{v:,.2f}"


def _delta(cur: float, prev: float) -> str:
    if not prev:
        return "new" if cur else "-"
    change = (cur - prev) / prev
    return f"{'▲' if change >= 0 else '▼'} {abs(change):.0%}"


def build_markdown(ctx: dict) -> str:
    s = ctx["symbol"]
    k = ctx["kpis"]
    L: list[str] = []
    L.append(f"# 📊 {ctx['shop_name']} - Daily Growth Report ({ctx['run_date']})")
    if ctx.get("demo"):
        L.append("> **DEMO MODE** - yeh sample data hai. Asli shop connect karne ke liye SETUP_GUIDE.md dekho.")
    L.append("")
    L.append("## 🏪 Shop snapshot")
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| Active listings | {k['active_listings']} |")
    L.append(f"| Views (30 din){' *(estimate)*' if k['estimated'] else ''} | {k['views_w']:,.0f} |")
    L.append(f"| Sales (7 din) | {k['units_s']} ({_delta(k['units_s'], k['units_prev_s'])} vs pichhla hafta) |")
    L.append(f"| Revenue (7 din) | {_money(k['revenue_s'], s)} ({_delta(k['revenue_s'], k['revenue_prev_s'])}) |")
    L.append(f"| Revenue (30 din) | {_money(k['revenue_w'], s)} |")
    L.append(f"| Conversion (30 din) | {k['conversion_w']:.2%} |")
    L.append(f"| Zero-sale listings (30 din) | {k['zero_sale_listings']} |")
    L.append("")

    for f in ctx["focus"]:
        m, pack, ins, prop, res = f["metrics"], f["pack"], f.get("insight") or {}, f["proposal"], f["seo_result"]
        l = m.listing
        L.append(f"## 🎯 Aaj ka focus product: {truncate(l['title'], 90)}")
        L.append(f"[Etsy par dekho]({l['url']}) · Price {_money(l['price'], s)} · Weakness score **{m.score:.2f}**")
        L.append("")
        L.append(f"**Diagnosis:** {DIAGNOSIS_LABELS[m.diagnosis]}")
        for r in m.reasons:
            L.append(f"- {r}")
        L.append("")
        L.append("| Views 30d | Favorites 30d | Sales 30d | Conversion | Quality |")
        L.append("|---|---|---|---|---|")
        L.append(f"| {m.views_w:.0f} | {m.favs_w:.0f} | {m.sales_w} | {m.conv:.2%} | {m.quality:.0f}/100 |")
        L.append("")
        if ins.get("analyzed"):
            L.append("### 🔍 Market analysis (Etsy search, live)")
            for kw in ins["keywords"]:
                L.append(f"- **\"{kw['keyword']}\"** - {kw['competitors']:,} competing listings, "
                         f"median price {_money(kw['median_price'], s)}")
            adv = price_advice(ins, s)
            if adv:
                L.append(f"- 💰 {adv}")
            if ins.get("related_trends"):
                L.append(f"- 📈 Pinterest par trending: {', '.join(ins['related_trends'])}")
            L.append(f"- Top competitor tags: `{', '.join(t for t, _ in ins['top_tags'][:12])}`")
            if ins.get("missing_tags"):
                L.append(f"- Aapke paas missing: `{', '.join(ins['missing_tags'][:10])}`")
            if ins.get("competitor_samples"):
                L.append("- Best-performing competitors:")
                for c in ins["competitor_samples"][:3]:
                    L.append(f"  - [{truncate(c['title'], 70)}]({c['url']}) - {_money(c['price'], s)}, "
                             f"{c['favorites']} favorites")
            L.append("")
        L.append(f"### ✍️ SEO upgrade ({'✅ APPLIED' if res['applied'] else 'suggestion'} - {res['reason']})")
        L.append(f"**Old title:** {prop['old_title']}")
        L.append("")
        L.append(f"**New title:** `{prop['new_title']}`")
        L.append("")
        L.append("**New 13 tags (copy-paste):**")
        L.append("```")
        L.append(", ".join(prop["new_tags"]))
        L.append("```")
        if prop["added_tags"]:
            L.append(f"Added: {', '.join(prop['added_tags'])} · Removed: {', '.join(prop['removed_tags']) or '-'}")
        L.append("")
        L.append("**Description ki shuruaat (first 160 chars Google/Etsy dono padhte hain):**")
        L.append(f"> {prop['description_intro']}")
        for r in prop.get("rationale", []):
            L.append(f"- _{r}_")
        L.append("")
        L.append("### ✅ Aapke liye to-do (jo API se nahi ho sakta)")
        for t in dict.fromkeys(pack.get("conversion_tips", [])):
            L.append(f"- [ ] {t}")
        L.append("")
        soc = pack.get("social", {})
        L.append("### 📣 Free social posts (copy-paste)")
        L.append(f"- **Instagram:** {soc.get('instagram', '')}")
        L.append(f"- **Facebook:** {soc.get('facebook', '')}")
        L.append(f"- **TikTok/Reels hook:** {soc.get('tiktok_hook', '')}")
        L.append(f"- **Reddit title** (sirf allowed subreddits mein, self-promo rules padh ke): {soc.get('reddit_title', '')}")
        L.append(f"_Copy source: {pack.get('source')}_")
        L.append("")

    pins = ctx.get("pins", [])
    L.append(f"## 📌 Pinterest ({len(pins)} pins, channel: `{ctx['channel']}`)")
    channel_note = {
        "api": "Pins Pinterest API se time-slots mein post honge (publish workflow har kuch ghante chalta hai).",
        "rss": "Pins RSS feed mein add ho gaye - Pinterest inhe khud aapke board par publish karega.",
        "csv": "Pinterest > Create > 'Create Pins in bulk' mein aaj ki CSV upload karo (scheduled dates set hain).",
        "off": "Pinterest band hai.",
    }
    L.append(channel_note.get(ctx["channel"], ""))
    if ctx.get("publish"):
        p = ctx["publish"]
        L.append(f"- Abhi post hue: {p['posted']} · failed: {p['failed']}")
    if ctx.get("csv_path"):
        L.append(f"- Bulk CSV: `{ctx['csv_path']}`")
    if pins:
        L.append("")
        L.append("| # | Product | Template | Headline style | Board | Focus |")
        L.append("|---|---|---|---|---|---|")
        titles = {m.listing_id: m.listing["title"] for m in ctx["metrics"]}
        for i, p in enumerate(pins, 1):
            L.append(f"| {i} | {truncate(titles.get(p['listing_id'], ''), 40)} | {p['template']} | "
                     f"{p['headline_style']} | {p['board']} | {'⭐' if p['is_focus'] else ''} |")
    lb = ctx.get("leaderboard") or {}
    if any(lb.get(c) for c in ("template", "headline_style")):
        L.append("")
        L.append("**🧠 Learning (kaunsa design/headline best chal raha hai):**")
        for col, label in (("template", "Design"), ("headline_style", "Headline")):
            top = [f"{r['arm']} ({r['engagement_rate']:.2%}, {r['imp']:,} impr.)" for r in lb.get(col, [])[:3]]
            if top:
                L.append(f"- {label}: {' > '.join(top)}")
    L.append("")

    if ctx.get("uplift"):
        L.append("## 📈 Pichhle pushes ka result")
        L.append("| Product | Focus date | Views 7d before → after | Sales 7d before → after |")
        L.append("|---|---|---|---|")
        for u in ctx["uplift"]:
            L.append(f"| {truncate(u['title'], 45)} | {u['focused_on']} | {u['views_before']:.0f} → "
                     f"{u['views_after']:.0f} | {u['sales_before']} → {u['sales_after']} |")
        L.append("")

    if ctx.get("pulse"):
        L.append("## 🌍 Weekly market pulse")
        L.append("| Product keyword | Competitors | Median price | Aapka price position |")
        L.append("|---|---|---|---|")
        for p in ctx["pulse"]:
            pos = f"{p['our_percentile']:.0%} competitors se mehenga" if p["our_percentile"] is not None else "-"
            change = f" ({p['competitor_change']:+,})" if p.get("competitor_change") else ""
            L.append(f"| {p['keyword']} | {p['competitors']:,}{change} | {_money(p['median_price'], s)} | {pos} |")
        L.append("")

    L.append("## 🔻 Sabse weak 5 products")
    L.append("| Product | Score | Diagnosis | Views 30d | Sales 30d | Quality |")
    L.append("|---|---|---|---|---|---|")
    for m in sorted(ctx["metrics"], key=lambda x: -x.score)[:5]:
        L.append(f"| [{truncate(m.listing['title'], 45)}]({m.listing['url']}) | {m.score:.2f} | {m.diagnosis} | "
                 f"{m.views_w:.0f} | {m.sales_w} | {m.quality:.0f} |")
    L.append("")
    if ctx.get("warnings"):
        L.append("## ⚠️ System notes")
        for w in ctx["warnings"]:
            L.append(f"- {w}")
        L.append("")
    L.append(f"_Generated by Etsy Growth Engine · LLM: {ctx.get('llm') or 'rule-based (free)'}_")
    return "\n".join(L)


def _inline(text: str) -> str:
    t = html_lib.escape(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])_([^_]+)_(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', t)
    return t


def markdown_to_html(md: str, title: str) -> str:
    out: list[str] = []
    lines = md.split("\n")
    i = 0
    in_list = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(html_lib.escape(lines[i]))
                i += 1
            out.append(f"<pre>{chr(10).join(block)}</pre>")
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-| ]+\|$", lines[i + 1]):
            head = [c.strip() for c in line.strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            out.append("<div class='t'><table><tr>" + "".join(f"<th>{_inline(h)}</th>" for h in head) + "</tr>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows)
                       + "</table></div>")
            continue
        is_item = re.match(r"^\s*- (\[ \] )?(.*)", line)
        if is_item and not in_list:
            out.append("<ul>")
            in_list = True
        if not is_item and in_list:
            out.append("</ul>")
            in_list = False
        if is_item:
            box = "☐ " if is_item.group(1) else ""
            indent = " class='sub'" if line.startswith("  ") else ""
            out.append(f"<li{indent}>{box}{_inline(is_item.group(2))}</li>")
        elif line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            out.append(f"<h{level}>{_inline(line[level:].strip())}</h{level}>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
        elif line.strip():
            out.append(f"<p>{_inline(line)}</p>")
        i += 1
    if in_list:
        out.append("</ul>")
    css = """:root{--bg:#fff;--fg:#1d1d1f;--muted:#666;--line:#e5e5e5;--code:#f4f1ec;--accent:#F1641E}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#eee;--muted:#aaa;--line:#333;--code:#1e1e1e}}
body{background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
max-width:920px;margin:auto;padding:16px;line-height:1.55}h1{font-size:1.5rem}h2{border-top:1px solid var(--line);
padding-top:18px;margin-top:28px}a{color:var(--accent)}code,pre{background:var(--code);border-radius:6px}
code{padding:1px 5px}pre{padding:12px;white-space:pre-wrap}.t{overflow-x:auto}table{border-collapse:collapse;
width:100%;font-size:.92rem}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}
blockquote{border-left:4px solid var(--accent);margin:0;padding:4px 12px;color:var(--muted)}li.sub{margin-left:20px}"""
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>{html_lib.escape(title)}</title>"
            f"<style>{css}</style></head><body>{''.join(out)}</body></html>")


def build_summary(ctx: dict) -> str:
    s, k = ctx["symbol"], ctx["kpis"]
    lines = [f"📊 {ctx['shop_name']} - {ctx['run_date']}",
             f"Sales 7d: {k['units_s']} ({_delta(k['units_s'], k['units_prev_s'])}) · "
             f"Revenue 7d: {_money(k['revenue_s'], s)}"]
    for f in ctx["focus"]:
        m = f["metrics"]
        lines.append(f"🎯 Focus: {truncate(m.listing['title'], 60)}")
        lines.append(f"   {DIAGNOSIS_LABELS[m.diagnosis]}")
        lines.append(f"   SEO: {'applied ✅' if f['seo_result']['applied'] else 'suggestion ready'}")
    lines.append(f"📌 Pinterest: {len(ctx.get('pins', []))} pins ({ctx['channel']})")
    if ctx.get("warnings"):
        lines.append("⚠️ " + " | ".join(ctx["warnings"][:3]))
    lines.append("Full report: reports/latest.html")
    return "\n".join(lines)


def write_reports(ctx: dict, reports_dir: Path) -> dict:
    reports_dir.mkdir(parents=True, exist_ok=True)
    md = build_markdown(ctx)
    title = f"{ctx['shop_name']} report {ctx['run_date']}"
    html = markdown_to_html(md, title)
    md_path = reports_dir / f"{ctx['run_date']}.md"
    md_path.write_text(md, encoding="utf-8")
    (reports_dir / "latest.md").write_text(md, encoding="utf-8")
    (reports_dir / "latest.html").write_text(html, encoding="utf-8")
    return {"markdown": str(md_path), "html": str(reports_dir / "latest.html"), "md_text": md, "html_text": html}
