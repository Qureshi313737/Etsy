"""Pinterest pin image generator (1000x1500, 2:3) built with Pillow - no paid design tools.

Five templates; the learning loop (bandit.py) finds which one gets the most clicks for your shop.
Rendering is deterministic, so a queued pin can be re-rendered later from its saved recipe.
"""
from __future__ import annotations

import hashlib
import io
import logging
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .http import HttpClient

log = logging.getLogger(__name__)

W, H = 1000, 1500
TEMPLATES = ["banner", "split", "collage", "frame", "label"]

FONT_CANDIDATES = {
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
    "serif": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/Library/Fonts/Georgia Bold.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
    ],
}


@lru_cache(maxsize=64)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES.get(kind, []) + FONT_CANDIDATES["bold"]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------------------
# image sourcing
# ---------------------------------------------------------------------------
class ImageFetcher:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.http = HttpClient(qps=5.0, timeout=30)

    def get(self, url: str) -> Image.Image | None:
        if not url:
            return None
        if url.startswith("demo://"):
            from .demo import demo_product_image

            return demo_product_image(url)
        name = hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg"
        path = self.cache_dir / name
        try:
            if not path.exists():
                path.write_bytes(self.http.request("GET", url).content)
            img = Image.open(path)
            img.load()
            return ImageOps.exif_transpose(img).convert("RGB")
        except Exception as exc:
            log.warning("Could not load image %s: %s", url, exc)
            return None


# ---------------------------------------------------------------------------
# drawing helpers
# ---------------------------------------------------------------------------
def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(img, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (241, 100, 30)


def luminance(c: tuple[int, int, int]) -> float:
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255


def dominant_color(img: Image.Image) -> tuple[int, int, int]:
    small = img.resize((64, 64)).quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    palette = small.getpalette()
    counts = sorted(small.getcolors(), reverse=True)
    for _, idx in counts:
        c = tuple(palette[idx * 3: idx * 3 + 3])
        if 0.12 < luminance(c) < 0.9:  # skip pure white/black backgrounds
            return c
    return tuple(palette[counts[0][1] * 3: counts[0][1] * 3 + 3])


def panel_color(img: Image.Image) -> tuple[int, int, int]:
    c = dominant_color(img)
    # deepen the colour so white text stays readable
    factor = 0.55 if luminance(c) > 0.45 else 0.9
    return tuple(int(v * factor) for v in c)


def text_color_for(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    return (25, 25, 25) if luminance(bg) > 0.6 else (255, 255, 255)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_text(draw, text: str, kind: str, max_width: int, max_height: int, start: int, min_size: int = 28,
             max_lines: int = 3):
    size = start
    while size >= min_size:
        fnt = font(kind, size)
        lines = wrap(draw, text, fnt, max_width)
        line_h = int(size * 1.18)
        if len(lines) <= max_lines and line_h * len(lines) <= max_height:
            return fnt, lines, line_h
        size -= 4
    fnt = font(kind, min_size)
    return fnt, wrap(draw, text, fnt, max_width)[:max_lines], int(min_size * 1.18)


def draw_block(draw, lines, fnt, line_h, center_x: int, top: int, fill, shadow=None) -> int:
    y = top
    for ln in lines:
        w = draw.textlength(ln, font=fnt)
        x = center_x - w / 2
        if shadow:
            draw.text((x + 3, y + 3), ln, font=fnt, fill=shadow)
        draw.text((x, y), ln, font=fnt, fill=fill)
        y += line_h
    return y


def pill(draw, text: str, center_x: int, top: int, bg, fg, size: int = 38) -> int:
    fnt = font("bold", size)
    tw = draw.textlength(text, font=fnt)
    pad_x, h = 44, int(size * 1.9)
    box = (center_x - tw / 2 - pad_x, top, center_x + tw / 2 + pad_x, top + h)
    draw.rounded_rectangle(box, radius=h // 2, fill=bg)
    draw.text((center_x - tw / 2, top + (h - size * 1.15) / 2), text, font=fnt, fill=fg)
    return top + h


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------
def _banner(images, headline, subline, cta, price, accent):
    canvas = cover(images[0], (W, H))
    grad = Image.new("L", (1, H))
    for y in range(H):
        grad.putpixel((0, y), int(max(0, (y - H * 0.45) / (H * 0.55)) ** 1.4 * 235))
    shade = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(shade, (0, 0), grad.resize((W, H)))
    d = ImageDraw.Draw(canvas)
    fnt, lines, lh = fit_text(d, headline, "bold", W - 120, 330, 104)
    top = H - 140 - 90 - lh * len(lines) - (60 if subline else 0)
    y = draw_block(d, lines, fnt, lh, W // 2, top, (255, 255, 255), shadow=(0, 0, 0))
    if subline:
        sf = font("regular", 42)
        draw_block(d, [subline], sf, 52, W // 2, y + 6, (235, 235, 235))
    pill(d, cta, W // 2, H - 150, accent, text_color_for(accent))
    if price:
        pill(d, price, W - 150, 50, (255, 255, 255), (30, 30, 30), size=36)
    return canvas


def _split(images, headline, subline, cta, price, accent):
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    canvas.paste(cover(images[0], (W, 1020)), (0, 0))
    bg = panel_color(images[0])
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 1020, W, H), fill=bg)
    fg = text_color_for(bg)
    fnt, lines, lh = fit_text(d, headline, "serif", W - 120, 220, 84, max_lines=2)
    y = draw_block(d, lines, fnt, lh, W // 2, 1060, fg)
    if subline:
        y = draw_block(d, [subline], font("regular", 38), 46, W // 2, y + 4, fg)
    pill(d, cta, W // 2, H - 125, accent if accent != bg else (255, 255, 255), text_color_for(accent))
    if price:
        pill(d, price, 150, 40, (255, 255, 255), (30, 30, 30), size=36)
    return canvas


def _collage(images, headline, subline, cta, price, accent):
    imgs = (images * 3)[:3]
    canvas = Image.new("RGB", (W, H), (250, 247, 242))
    canvas.paste(cover(imgs[0], (W, 820)), (0, 0))
    canvas.paste(cover(imgs[1], (W // 2 - 4, 680)), (0, 820 + 0))
    canvas.paste(cover(imgs[2], (W // 2 - 4, 680)), (W // 2 + 4, 820))
    d = ImageDraw.Draw(canvas)
    band_top, band_h = 700, 240
    d.rectangle((60, band_top, W - 60, band_top + band_h), fill=(255, 255, 255))
    d.rectangle((60, band_top, W - 60, band_top + 10), fill=accent)
    fnt, lines, lh = fit_text(d, headline, "bold", W - 200, 150, 70, max_lines=2)
    y = draw_block(d, lines, fnt, lh, W // 2, band_top + 30, (30, 30, 30))
    if subline:
        draw_block(d, [subline], font("regular", 34), 40, W // 2, y + 2, (90, 90, 90))
    pill(d, cta, W // 2, H - 130, accent, text_color_for(accent))
    return canvas


def _frame(images, headline, subline, cta, price, accent):
    bg = (246, 241, 233)
    canvas = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(canvas)
    fnt, lines, lh = fit_text(d, headline, "serif", W - 140, 240, 88, max_lines=2)
    y = draw_block(d, lines, fnt, lh, W // 2, 70, (40, 34, 30))
    if subline:
        y = draw_block(d, [subline], font("regular", 38), 46, W // 2, y + 4, (110, 100, 90))
    photo_top = max(y + 40, 330)
    photo_h = H - photo_top - 220
    photo = cover(images[0], (W - 160, photo_h))
    shadow = Image.new("RGBA", (W - 120, photo_h + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((20, 20, W - 140, photo_h + 20), fill=(0, 0, 0, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.paste(shadow, (60, photo_top), shadow)
    d.rectangle((70, photo_top - 10, W - 70, photo_top + photo_h + 10), fill=(255, 255, 255))
    canvas.paste(photo, (80, photo_top))
    pill(d, cta, W // 2, H - 160, accent, text_color_for(accent))
    if price:
        d.text((W // 2, H - 52), price, font=font("bold", 34), fill=(60, 50, 45), anchor="mm")
    return canvas


def _label(images, headline, subline, cta, price, accent):
    canvas = cover(images[0], (W, H))
    d = ImageDraw.Draw(canvas)
    fnt, lines, lh = fit_text(d, headline, "bold", W - 240, 260, 80, max_lines=3)
    box_h = lh * len(lines) + (60 if subline else 0) + 80
    d.rounded_rectangle((70, 80, W - 70, 80 + box_h), radius=28, fill=(255, 255, 255))
    d.rectangle((70, 80, 84, 80 + box_h), fill=accent)
    y = draw_block(d, lines, fnt, lh, W // 2, 120, (25, 25, 25))
    if subline:
        draw_block(d, [subline], font("regular", 36), 44, W // 2, y + 4, (90, 90, 90))
    pill(d, cta, W // 2, H - 150, accent, text_color_for(accent))
    if price:
        pill(d, price, W // 2, H - 250, (255, 255, 255), (30, 30, 30), size=34)
    return canvas


RENDERERS = {"banner": _banner, "split": _split, "collage": _collage, "frame": _frame, "label": _label}


def placeholder(text: str = "Product") -> Image.Image:
    img = Image.new("RGB", (1000, 1000), (232, 226, 218))
    d = ImageDraw.Draw(img)
    d.text((500, 500), text, font=font("bold", 60), fill=(120, 110, 100), anchor="mm")
    return img


def render_pin(images: list[Image.Image], template: str, headline: str, subline: str = "",
               cta: str = "Shop on Etsy", price: str = "", accent_hex: str = "#F1641E") -> bytes:
    imgs = [im for im in images if im is not None] or [placeholder()]
    renderer = RENDERERS.get(template, _banner)
    canvas = renderer(imgs, headline, subline, cta, price, hex_rgb(accent_hex))
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, "JPEG", quality=88, optimize=True, progressive=True)
    return buf.getvalue()


def render_recipe(recipe: dict, fetcher: ImageFetcher) -> bytes:
    images = [fetcher.get(u) for u in recipe.get("image_urls", [])]
    return render_pin(images, recipe.get("template", "banner"), recipe.get("headline", ""),
                      recipe.get("subline", ""), recipe.get("cta", "Shop on Etsy"),
                      recipe.get("price", ""), recipe.get("accent", "#F1641E"))
