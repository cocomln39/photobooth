"""
Filters + photo-strip compositing.

All image work happens in PIL space (RGB). OpenCV frames (BGR numpy
arrays) coming from camera.py should be converted with cv2_to_pil()
before being handed to anything in this module.
"""
import json
import os
import re
import uuid

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

import config


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------
def cv2_to_pil(frame_bgr):
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def _warm(img):
    r, g, b = img.split()
    r = r.point(lambda i: min(255, int(i * 1.12) + 8))
    b = b.point(lambda i: max(0, int(i * 0.88) - 8))
    out = Image.merge("RGB", (r, g, b))
    return ImageEnhance.Color(out).enhance(1.12)


def _cool(img):
    r, g, b = img.split()
    r = r.point(lambda i: max(0, int(i * 0.90) - 5))
    b = b.point(lambda i: min(255, int(i * 1.15) + 8))
    out = Image.merge("RGB", (r, g, b))
    return ImageEnhance.Color(out).enhance(0.95)


def _soft_light(img):
    blurred = img.filter(ImageFilter.GaussianBlur(radius=4))
    softened = Image.blend(img, blurred, alpha=0.35)
    softened = ImageEnhance.Brightness(softened).enhance(1.08)
    softened = ImageEnhance.Contrast(softened).enhance(0.92)
    return softened


def _polaroid(img):
    out = ImageEnhance.Color(img).enhance(0.82)
    out = ImageEnhance.Contrast(out).enhance(0.95)
    out = ImageEnhance.Brightness(out).enhance(1.05)
    # warm-yellow cast typical of instant film
    r, g, b = out.split()
    r = r.point(lambda i: min(255, int(i * 1.06) + 6))
    g = g.point(lambda i: min(255, int(i * 1.02) + 3))
    b = b.point(lambda i: max(0, int(i * 0.90)))
    out = Image.merge("RGB", (r, g, b))
    # soft vignette
    w, h = out.size
    vignette = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(vignette)
    draw.ellipse((-w * 0.25, -h * 0.25, w * 1.25, h * 1.25), fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=min(w, h) * 0.18))
    dark = ImageEnhance.Brightness(out).enhance(0.78)
    out = Image.composite(out, dark, vignette)
    return out


def _monochrome(img):
    gray = ImageOps.grayscale(img)
    gray = ImageEnhance.Contrast(gray).enhance(1.12)
    return gray.convert("RGB")


_FILTER_FUNCS = {
    "Original": lambda img: img,
    "Warm": _warm,
    "Cool": _cool,
    "Soft Light": _soft_light,
    "Polaroid": _polaroid,
    "Monochrome": _monochrome,
}


def apply_filter(img: Image.Image, name: str) -> Image.Image:
    fn = _FILTER_FUNCS.get(name, _FILTER_FUNCS["Original"])
    return fn(img.convert("RGB"))


# ---------------------------------------------------------------------------
# Frame themes
# ---------------------------------------------------------------------------
def list_themes():
    """
    A theme is a folder OR pair of files in static/frames/themes:
      <theme_id>.png       - full 1652x4920 RGBA overlay, transparent
                              windows where photos show through
      <theme_id>.json      - {"name": "...", "thumbnail": "...", "slots": [...]}
                              slots: list of 3 [x, y, w, h] rects (in strip
                              pixel space) describing where each photo goes.
    If no themes exist, a single built-in "Classic" theme (no overlay,
    default even grid, thin white border) is used.
    """
    themes = [_default_theme()]
    if not os.path.isdir(config.FRAMES_DIR):
        return themes
    for fname in sorted(os.listdir(config.FRAMES_DIR)):
        if not fname.endswith(".json"):
            continue
        theme_id = fname[:-5]
        json_path = os.path.join(config.FRAMES_DIR, fname)
        try:
            with open(json_path) as f:
                meta = json.load(f)
        except Exception:
            continue
        overlay_path = os.path.join(config.FRAMES_DIR, meta.get("overlay", f"{theme_id}.png"))
        themes.append(
            {
                "id": theme_id,
                "name": meta.get("name", theme_id.title()),
                "thumbnail": f"/static/frames/themes/{os.path.basename(meta.get('thumbnail', meta.get('overlay', '')))}",
                "overlay_path": overlay_path if os.path.exists(overlay_path) else None,
                "slots": meta.get("slots", default_slots()),
            }
        )
    return themes


def _default_theme():
    return {
        "id": "classic",
        "name": "Classic",
        "thumbnail": None,
        "overlay_path": None,
        "slots": default_slots(),
    }


def get_theme(theme_id):
    for t in list_themes():
        if t["id"] == theme_id:
            return t
    return _default_theme()


def default_slots():
    """Compute the 3 square photo slots with generous outer margins."""
    w = config.STRIP_WIDTH
    h = config.STRIP_HEIGHT
    mx = config.STRIP_MARGIN_SIDE
    mt = config.STRIP_MARGIN_TOP
    mb = config.STRIP_MARGIN_BOTTOM
    gap = config.STRIP_GAP
    n = config.SHOTS_PER_STRIP

    slot_w = w - 2 * mx
    total_gap = gap * (n - 1)
    slot_h = (h - mt - mb - total_gap) / n

    slots = []
    y = mt
    for _ in range(n):
        slots.append([int(mx), int(y), int(slot_w), int(slot_h)])
        y += slot_h + gap
    return slots


# ---------------------------------------------------------------------------
# Compositing
# ---------------------------------------------------------------------------
def crop_to_aspect(img: Image.Image, target_ratio: float) -> Image.Image:
    """Center-crop an image to an exact width/height aspect ratio."""
    img = img.convert("RGB")
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    if abs(src_ratio - target_ratio) < 1e-6:
        return img.copy()
    if src_ratio > target_ratio:
        # Too wide: trim the sides.
        new_w = max(1, int(round(src_h * target_ratio)))
        left = (src_w - new_w) // 2
        return img.crop((left, 0, left + new_w, src_h))
    # Too tall: trim the top/bottom.
    new_h = max(1, int(round(src_w / target_ratio)))
    top = (src_h - new_h) // 2
    return img.crop((0, top, src_w, top + new_h))


def _fit_cover(img: Image.Image, target_w, target_h) -> Image.Image:
    """Resize+crop img to exactly fill target_w x target_h (cover fit)."""
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    dst_ratio = target_w / target_h
    if src_ratio > dst_ratio:
        new_h = target_h
        new_w = int(new_h * src_ratio)
    else:
        new_w = target_w
        new_h = int(new_w / src_ratio)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _load_text_font(size: int):
    from PIL import ImageFont
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _draw_strip_text(canvas: Image.Image, settings: dict):
    draw = ImageDraw.Draw(canvas)
    title = str(settings.get("title", "PHOTO BOOTH"))
    subtitle = str(settings.get("subtitle", ""))
    show_title = bool(settings.get("show_title", False))
    show_subtitle = bool(settings.get("show_subtitle", False))
    if not (show_title or show_subtitle):
        return

    w, h = canvas.size
    if show_title and title:
        font = _load_text_font(max(28, int(w * 0.038)))
        box = draw.textbbox((0, 0), title, font=font)
        tw = box[2] - box[0]
        draw.text(((w - tw) / 2, 12), title, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
    if show_subtitle and subtitle:
        font = _load_text_font(max(22, int(w * 0.026)))
        box = draw.textbbox((0, 0), subtitle, font=font)
        tw = box[2] - box[0]
        draw.text(((w - tw) / 2, h - (box[3] - box[1]) - 16), subtitle, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))


def compose_strip(photos, theme_id, filter_name, text_settings=None) -> Image.Image:
    """Compose a final strip at the exact configured output resolution."""
    theme = get_theme(theme_id)
    canvas = Image.new("RGB", (config.STRIP_WIDTH, config.STRIP_HEIGHT), "white")

    for photo, slot in zip(photos, theme["slots"]):
        x, y, w, h = slot
        filtered = apply_filter(photo, filter_name)
        # The camera/live preview uses this same crop, so guests see the
        # square framing that will actually enter the printed photo window.
        filtered = crop_to_aspect(filtered, w / h)
        fitted = filtered.resize((w, h), Image.LANCZOS)
        canvas.paste(fitted, (x, y))

    if theme["overlay_path"]:
        overlay = Image.open(theme["overlay_path"]).convert("RGBA")
        if overlay.size != canvas.size:
            overlay = overlay.resize(canvas.size, Image.LANCZOS)
        canvas = canvas.convert("RGBA")
        canvas.alpha_composite(overlay)
        canvas = canvas.convert("RGB")

    # Optional text is drawn last so it remains visible over transparent frame
    # artwork. Defaults are disabled to preserve existing frame designs.
    if text_settings:
        _draw_strip_text(canvas, text_settings)

    return canvas


def compose_strip_thumbnail(photos, theme_id, filter_name, max_width=420) -> Image.Image:
    """Cheaper low-res version for fast filter-preview thumbnails."""
    full = compose_strip(photos, theme_id, filter_name)
    ratio = max_width / full.width
    return full.resize((max_width, int(full.height * ratio)), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Admin: upload / delete custom frame themes
# ---------------------------------------------------------------------------
def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug:
        slug = "theme"
    return slug


def _unique_theme_id(base_slug: str) -> str:
    existing = {t["id"] for t in list_themes()}
    if base_slug not in existing and base_slug != "classic":
        return base_slug
    n = 2
    while f"{base_slug}_{n}" in existing:
        n += 1
    return f"{base_slug}_{n}"


def _contain_onto_canvas(img: Image.Image, canvas_w, canvas_h) -> Image.Image:
    """Scale (preserving aspect ratio) to fit fully inside the canvas,
    centered, on a transparent background -- avoids distorting artwork
    that wasn't drawn at the exact strip resolution."""
    img = img.convert("RGBA")
    src_w, src_h = img.size
    scale = min(canvas_w / src_w, canvas_h / src_h)
    new_w, new_h = max(1, int(src_w * scale)), max(1, int(src_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    x = (canvas_w - new_w) // 2
    y = (canvas_h - new_h) // 2
    canvas.alpha_composite(resized, (x, y))
    return canvas


def save_uploaded_theme(name: str, file_stream, slots=None) -> dict:
    """
    Save a staff-uploaded frame overlay as a new selectable theme.

    file_stream: any file-like object PIL.Image.open() accepts (e.g. a
                 Flask FileStorage from request.files).
    slots:       optional list of 3 [x, y, w, h] rects in strip pixel
                 space overriding the default even grid -- use this if
                 the uploaded artwork's transparent windows don't line
                 up with default_slots().
    Returns the theme dict as it will appear from list_themes().
    """
    try:
        img = Image.open(file_stream)
        img.load()
    except Exception as e:
        raise ValueError(f"Could not read image file: {e}")

    theme_id = _unique_theme_id(_slugify(name) or "theme")
    canvas = _contain_onto_canvas(img, config.STRIP_WIDTH, config.STRIP_HEIGHT)

    overlay_filename = f"{theme_id}.png"
    thumb_filename = f"{theme_id}_thumb.jpg"
    overlay_path = os.path.join(config.FRAMES_DIR, overlay_filename)
    thumb_path = os.path.join(config.FRAMES_DIR, thumb_filename)
    json_path = os.path.join(config.FRAMES_DIR, f"{theme_id}.json")

    canvas.save(overlay_path)

    thumb = canvas.copy()
    thumb.thumbnail((330, 984))
    thumb_bg = Image.new("RGB", thumb.size, (28, 25, 31))
    thumb_bg.paste(thumb, (0, 0), thumb)
    thumb_bg.save(thumb_path, quality=85)

    display_name = name.strip() or theme_id.replace("_", " ").title()
    meta = {
        "name": display_name,
        "overlay": overlay_filename,
        "thumbnail": thumb_filename,
        "slots": slots if slots else default_slots(),
    }
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2)

    return get_theme(theme_id)


def delete_theme(theme_id: str) -> bool:
    """Remove a theme's overlay/thumbnail/json. Returns False for the
    built-in 'classic' theme (cannot be deleted) or an unknown id."""
    if theme_id == "classic":
        return False
    json_path = os.path.join(config.FRAMES_DIR, f"{theme_id}.json")
    if not os.path.exists(json_path):
        return False
    try:
        with open(json_path) as f:
            meta = json.load(f)
    except Exception:
        meta = {}

    for key in ("overlay", "thumbnail"):
        fname = meta.get(key)
        if fname:
            fpath = os.path.join(config.FRAMES_DIR, fname)
            if os.path.exists(fpath):
                os.remove(fpath)
    os.remove(json_path)
    return True
