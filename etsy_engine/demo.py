"""Offline demo: a fake shop with 30 days of history, fake competitors and fake Pinterest,
so the whole pipeline can be seen end-to-end before any API key is set up."""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

PRODUCTS = [
    ("Personalized Birth Flower Necklace, Dainty Gold Name Necklace, Gift for Mom",
     ["birth flower necklace", "name necklace", "gift for mom", "dainty necklace", "gold necklace",
      "personalized gift", "bridesmaid gift", "flower jewelry", "mothers day gift", "birthday gift",
      "minimalist jewelry", "custom necklace", "gift for her"], 34.0, ["gold filled", "sterling silver"]),
    ("Soy Candle", ["candle", "soy", "gift"], 18.0, []),
    ("Custom Pet Portrait from Photo, Digital Dog Portrait, Pet Memorial Gift",
     ["pet portrait", "dog portrait", "custom pet art", "pet memorial gift", "cat portrait",
      "pet lover gift", "dog mom gift", "digital portrait", "custom portrait", "pet drawing",
      "dog art", "gift for pet owner", "pet loss gift"], 25.0, ["digital file"]),
    ("Macrame Wall Hanging Boho Decor",
     ["macrame", "wall hanging", "boho decor", "wall decor", "macrame wall art"], 42.0, ["cotton cord"]),
    ("Leather Keychain Personalized Initials, Anniversary Gift for Him",
     ["leather keychain", "personalized keychain", "gift for him", "anniversary gift", "initial keychain",
      "groomsmen gift", "custom keychain", "fathers day gift", "boyfriend gift", "leather gift",
      "key fob", "monogram keychain", "husband gift"], 16.0, ["leather"]),
    ("Ceramic Mug", ["mug", "ceramic", "coffee"], 28.0, ["stoneware"]),
    ("Pressed Flower Phone Case, Real Dried Flower iPhone Case, Botanical Gift",
     ["pressed flower case", "dried flower case", "iphone case", "botanical gift", "flower phone case",
      "boho phone case", "cottagecore", "gift for her", "nature gift", "floral case", "real flowers",
      "clear phone case", "unique phone case"], 22.0, ["resin", "dried flowers"]),
    ("Knitted Baby Blanket Chunky Merino, Baby Shower Gift",
     ["baby blanket", "knitted blanket", "baby shower gift", "chunky blanket", "merino wool",
      "newborn gift", "nursery decor", "knit baby blanket"], 65.0, ["merino wool"]),
    ("Wedding Guest Book Alternative, Wooden Heart Drop Box, Rustic Wedding Decor",
     ["wedding guest book", "guest book alternative", "rustic wedding", "wedding decor", "drop box",
      "wooden guest book", "heart guest book", "wedding keepsake", "boho wedding", "custom guest book",
      "wedding gift", "reception decor", "unique guest book"], 48.0, ["wood"]),
    ("Earrings", ["earrings", "jewelry"], 14.0, []),
]

COMPETITOR_VOCAB = {
    "default": ["gift for her", "personalized gift", "birthday gift", "handmade gift", "christmas gift",
                "gift for mom", "custom gift", "unique gift", "best friend gift", "holiday gift"],
}


def demo_product_image(url: str) -> Image.Image:
    seed = int(hashlib.md5(url.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    base = (rng.randint(150, 235), rng.randint(140, 225), rng.randint(130, 220))
    img = Image.new("RGB", (1200, 1200), base)
    d = ImageDraw.Draw(img)
    for y in range(1200):  # soft vertical gradient
        f = y / 1200
        d.line([(0, y), (1200, y)], fill=tuple(int(c * (1 - 0.18 * f)) for c in base))
    obj = (rng.randint(40, 200), rng.randint(40, 160), rng.randint(40, 160))
    shape = seed % 3
    if shape == 0:
        d.ellipse((330, 330, 870, 870), fill=obj)
        d.ellipse((460, 460, 740, 740), fill=base)
    elif shape == 1:
        d.rounded_rectangle((380, 260, 820, 940), radius=60, fill=obj)
        d.rectangle((380, 420, 820, 520), fill=tuple(min(255, c + 60) for c in obj))
    else:
        d.polygon([(600, 230), (930, 900), (270, 900)], fill=obj)
    d.ellipse((300, 930, 900, 1010), fill=tuple(int(c * 0.75) for c in base))
    return img


class DemoEtsy:
    shop_id = 999

    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        now = datetime.now(timezone.utc)
        self.listings = []
        for i, (title, tags, price, mats) in enumerate(PRODUCTS):
            lid = 1000 + i
            n_img = [8, 2, 9, 4, 7, 3, 6, 5, 8, 1][i]
            self.listings.append({
                "listing_id": lid, "shop_id": self.shop_id, "title": title,
                "description": (f"{title}. " * (6 if len(tags) > 8 else 1)).strip(),
                "url": f"https://www.etsy.com/listing/{lid}/demo-item", "price": price, "currency": "USD",
                "quantity": 10, "tags": tags, "materials": mats,
                "image_urls": [f"demo://{lid}/{k}" for k in range(n_img)],
                "has_video": i in (0, 2), "taxonomy_id": 1, "state": "active",
                "created_ts": int((now - timedelta(days=200 + 13 * i)).timestamp()), "updated_ts": 0,
                # popularity profile: strong listings get more views & sales
                "_daily_views": [42, 3, 35, 9, 20, 4, 26, 12, 30, 2][i],
                "_conv": [0.035, 0.0, 0.03, 0.01, 0.025, 0.0, 0.004, 0.02, 0.028, 0.0][i],
                "_fav": [0.08, 0.02, 0.09, 0.05, 0.06, 0.03, 0.07, 0.06, 0.07, 0.01][i],
            })
        self.updates: list[tuple[int, dict]] = []

    def history(self, days: int = 35):
        """Yields (date, listing snapshot dict, [sales]) for the simulated past."""
        now = datetime.now(timezone.utc)
        totals = {l["listing_id"]: [l["_daily_views"] * 150, int(l["_daily_views"] * 150 * l["_fav"])]
                  for l in self.listings}
        tx = 50000
        for d in range(days, 0, -1):
            day = now - timedelta(days=d)
            snaps, sales = [], []
            for l in self.listings:
                decline = 0.6 if l["listing_id"] == 1006 and d < 8 else 1.0  # one listing losing traffic
                views = max(0, int(self.rng.gauss(l["_daily_views"] * decline, l["_daily_views"] * 0.3)))
                totals[l["listing_id"]][0] += views
                totals[l["listing_id"]][1] += sum(1 for _ in range(views) if self.rng.random() < l["_fav"])
                for _ in range(views):
                    if self.rng.random() < l["_conv"]:
                        tx += 1
                        sales.append({"transaction_id": tx, "receipt_id": tx, "listing_id": l["listing_id"],
                                      "quantity": 1, "price": l["price"],
                                      "created_ts": int(day.timestamp()) + self.rng.randint(0, 80000)})
                snaps.append({**l, "views": totals[l["listing_id"]][0], "num_favorers": totals[l["listing_id"]][1]})
            yield day.date().isoformat(), snaps, sales
        self._totals = totals

    def iter_active_listings(self):
        totals = getattr(self, "_totals", {})
        for l in self.listings:
            v, f = totals.get(l["listing_id"], [l["_daily_views"] * 180, 10])
            yield {**{k: val for k, val in l.items() if not k.startswith("_")}, "views": v, "num_favorers": f}

    def iter_sales(self, min_created: int):
        return iter([])

    def search_active_listings(self, keywords: str, limit: int = 100) -> dict:
        rng = random.Random(keywords)
        words = keywords.split()
        own = next((l for l in self.listings if keywords in " ".join(l["tags"]) + " " + l["title"].lower()), None)
        pool = list(dict.fromkeys((own["tags"] if own else []) + COMPETITOR_VOCAB["default"]
                                  + [f"{w} {x}" for w in words for x in ("gift", "personalized", "handmade")]))
        base_price = own["price"] if own else 25.0
        results = []
        for i in range(min(limit, 60)):
            tags = rng.sample(pool, k=min(13, len(pool)))
            results.append({
                "listing_id": 500000 + i, "shop_id": 1 + i, "title": f"{keywords.title()}, "
                f"{tags[0].title()}, {tags[1].title()}", "description": "", "price": round(base_price * rng.uniform(0.6, 1.6), 2),
                "currency": "USD", "quantity": 5, "tags": tags, "materials": [], "image_urls": [],
                "url": f"https://www.etsy.com/listing/{500000 + i}", "views": rng.randint(100, 20000),
                "num_favorers": int(rng.paretovariate(1.2) * 20),
            })
        return {"count": rng.randint(800, 60000), "results": results}

    def update_listing(self, listing_id: int, fields: dict) -> dict:
        self.updates.append((listing_id, fields))
        return {"listing_id": listing_id, **fields}


class DemoPinterest:
    def __init__(self):
        self.created: list[dict] = []
        self.rng = random.Random(3)

    def board_id(self, name: str, create: bool = True) -> str:
        return "board-" + hashlib.md5(name.encode()).hexdigest()[:8]

    def create_pin(self, board_id, title, description, link, alt_text, image_bytes, content_type="image/jpeg"):
        pin = {"id": f"demo-pin-{len(self.created) + 1}", "board_id": board_id, "title": title, "link": link}
        self.created.append(pin)
        return pin

    def pin_analytics(self, pin_id, start, end):
        imp = self.rng.randint(200, 4000)
        return {"impressions": imp, "saves": int(imp * self.rng.uniform(0.002, 0.02)),
                "pin_clicks": int(imp * 0.01), "outbound_clicks": int(imp * self.rng.uniform(0.001, 0.012))}

    def trending_keywords(self, region="US", trend_type="growing", limit=20):
        return ["christmas gift ideas", "birth flower jewelry", "custom pet portrait", "boho wedding decor",
                "gift for mom", "cottagecore aesthetic"]


def seed_history(db, source: DemoEtsy) -> None:
    for day, snaps, sales in source.history():
        for s in snaps:
            db.upsert_listing({k: v for k, v in s.items() if not k.startswith("_")}, day)
        for sale in sales:
            db.upsert_sale(sale)


def seed_pin_history(db, source: DemoEtsy) -> None:
    """A few weeks of past pins with analytics so the learning loop has something to learn from."""
    from .pin_designer import TEMPLATES

    rng = random.Random(11)
    styles = ["keyword", "gift", "question", "seasonal", "benefit", "price"]
    template_bias = {"split": 1.6, "banner": 1.2, "label": 1.0, "frame": 0.9, "collage": 0.7}
    now = datetime.now(timezone.utc)
    for n in range(40):
        day = (now - timedelta(days=rng.randint(4, 25))).date().isoformat()
        l = rng.choice(source.listings)
        t, st = rng.choice(TEMPLATES), rng.choice(styles)
        pin_id = f"hist-{n}"
        db.execute("""INSERT INTO pin_queue(run_date, listing_id, is_focus, template, headline_style, image_path,
                      image_variant, title, description, link, board, channel, status, pin_id, posted_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (day, l["listing_id"], 0, t, st, f"hist-{n}.jpg", f"img:{n % 3}", l["title"][:100], "",
                    l["url"], "Etsy Finds", "api", "posted", pin_id, day + "T12:00:00"))
        imp = rng.randint(300, 3000)
        rate = 0.004 * template_bias[t] * (1.4 if st == "gift" else 1.0)
        db.execute("""INSERT OR REPLACE INTO pin_stats(pin_id, listing_id, template, headline_style, impressions,
                      saves, pin_clicks, outbound_clicks, synced_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                   (pin_id, l["listing_id"], t, st, imp, int(imp * rate * 1.5), int(imp * 0.01),
                    int(imp * rate), day))
