"""
One-off utility that generates a couple of example frame themes so the
booth has something selectable out of the box, and doubles as a
reference for how to add your own.

To add a CUSTOM theme:
  1. Design a transparent PNG exactly STRIP_WIDTH x STRIP_HEIGHT
     (1652 x 2990) in Photoshop/Figma/GIMP, with the 3 photo areas
     left transparent (or omit them and just set "slots" below to
     wherever you drew the cutouts).
  2. Save it as static/frames/themes/<your_id>.png
  3. Save a small preview (can just be a shrunk copy) as
     static/frames/themes/<your_id>_thumb.jpg
  4. Create static/frames/themes/<your_id>.json:
     {
       "name": "Display Name",
       "overlay": "<your_id>.png",
       "thumbnail": "<your_id>_thumb.jpg",
       "slots": [[x, y, w, h], [x, y, w, h], [x, y, w, h]]
     }
     (omit "slots" to fall back to the default even 3-up grid)
  5. Restart the app -- it'll show up in the theme picker automatically.

Run this file directly to (re)generate the two bundled examples:
    python3 make_demo_themes.py
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

import compositor
import config


def _font(size):
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _base_canvas():
    return Image.new("RGBA", (config.STRIP_WIDTH, config.STRIP_HEIGHT), (0, 0, 0, 0))


def _punch_slots(draw, slots, fill=(0, 0, 0, 0)):
    """No-op placeholder kept for clarity -- slots stay transparent since
    the canvas starts fully transparent; this exists so future themes can
    explicitly cut windows out of a filled background if needed."""
    pass


def make_gold_foil():
    w, h = config.STRIP_WIDTH, config.STRIP_HEIGHT
    slots = compositor.default_slots()
    canvas = _base_canvas()
    draw = ImageDraw.Draw(canvas)

    gold = (212, 175, 55, 255)
    # outer border
    border = 26
    draw.rectangle([0, 0, w - 1, h - 1], outline=gold, width=border)

    # thin frame around each photo slot
    for (x, y, sw, sh) in slots:
        pad = 10
        draw.rectangle(
            [x - pad, y - pad, x + sw + pad, y + sh + pad],
            outline=gold, width=6,
        )

    # footer label
    font = _font(64)
    text = "PHOTO BOOTH"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) / 2, h - 100), text, font=font, fill=gold)

    out_path = os.path.join(config.FRAMES_DIR, "gold_foil.png")
    canvas.save(out_path)

    thumb = canvas.copy()
    thumb.thumbnail((330, 984))
    thumb_bg = Image.new("RGB", thumb.size, (28, 25, 31))
    thumb_bg.paste(thumb, (0, 0), thumb)
    thumb_bg.save(os.path.join(config.FRAMES_DIR, "gold_foil_thumb.jpg"), quality=85)

    with open(os.path.join(config.FRAMES_DIR, "gold_foil.json"), "w") as f:
        json.dump(
            {
                "name": "Gold Foil",
                "overlay": "gold_foil.png",
                "thumbnail": "gold_foil_thumb.jpg",
                "slots": slots,
            },
            f,
            indent=2,
        )


def make_pastel_dots():
    w, h = config.STRIP_WIDTH, config.STRIP_HEIGHT
    slots = compositor.default_slots()
    canvas = _base_canvas()
    draw = ImageDraw.Draw(canvas)

    pink = (232, 143, 168, 255)
    mint = (150, 214, 189, 255)

    band_h = 30
    draw.rectangle([0, 0, w, band_h], fill=pink)
    draw.rectangle([0, h - band_h, w, h], fill=pink)

    import random
    rnd = random.Random(42)
    colors = [pink, mint]
    for _ in range(140):
        x = rnd.randint(0, w)
        y = rnd.randint(band_h, h - band_h)
        # keep dots out of the photo slots
        inside_slot = any(sx <= x <= sx + sw and sy <= y <= sy + sh for sx, sy, sw, sh in slots)
        if inside_slot:
            continue
        r = rnd.randint(6, 16)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=rnd.choice(colors))

    font = _font(56)
    text = "SAY CHEESE"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) / 2, h - band_h - 78), text, font=font, fill=(255, 255, 255, 255))

    out_path = os.path.join(config.FRAMES_DIR, "pastel_dots.png")
    canvas.save(out_path)

    thumb = canvas.copy()
    thumb.thumbnail((330, 984))
    thumb_bg = Image.new("RGB", thumb.size, (28, 25, 31))
    thumb_bg.paste(thumb, (0, 0), thumb)
    thumb_bg.save(os.path.join(config.FRAMES_DIR, "pastel_dots_thumb.jpg"), quality=85)

    with open(os.path.join(config.FRAMES_DIR, "pastel_dots.json"), "w") as f:
        json.dump(
            {
                "name": "Pastel Dots",
                "overlay": "pastel_dots.png",
                "thumbnail": "pastel_dots_thumb.jpg",
                "slots": slots,
            },
            f,
            indent=2,
        )


if __name__ == "__main__":
    make_gold_foil()
    make_pastel_dots()
    print(f"Demo themes written to {config.FRAMES_DIR}")
