"""
Combine the 3 short clips recorded during each shot's countdown into a
single animated GIF laid out exactly like the photo strip (3 panels,
same slot geometry/theme), all playing back SIMULTANEOUSLY in one file.

Each clip may have a slightly different frame count (timing jitter), so
frames are indexed with clamping: once a panel's clip runs out of frames
it holds on its last frame while the others keep animating, then the
whole GIF loops.
"""
from PIL import Image

import compositor
import config


def build_synced_gif(clips, theme_id, filter_name, out_path, text_settings=None):
    """
    clips: list of 3 lists of PIL RGB frames (already in chronological
           order), one list per shot, roughly config.GIF_CAPTURE_FPS fps.
    theme_id / filter_name: same as compose_strip, applied to every frame
           for visual consistency with the final still.
    out_path: where to write the .gif
    """
    theme = compositor.get_theme(theme_id)
    slots = theme["slots"]
    max_len = max(len(c) for c in clips)
    if max_len == 0:
        raise ValueError("No GIF frames were captured for this session")

    canvas_w, canvas_h = config.STRIP_WIDTH, config.STRIP_HEIGHT
    out_frames = []

    for i in range(max_len):
        frame = Image.new("RGB", (canvas_w, canvas_h), "white")
        for clip, slot in zip(clips, slots):
            if not clip:
                continue
            src = clip[min(i, len(clip) - 1)]
            filtered = compositor.apply_filter(src, filter_name)
            x, y, w, h = slot
            filtered = compositor.crop_to_aspect(filtered, w / h)
            fitted = filtered.resize((w, h), Image.LANCZOS)
            frame.paste(fitted, (x, y))

        if theme["overlay_path"]:
            overlay = Image.open(theme["overlay_path"]).convert("RGBA")
            if overlay.size != frame.size:
                overlay = overlay.resize(frame.size, Image.LANCZOS)
            frame = frame.convert("RGBA")
            frame.alpha_composite(overlay)
            frame = frame.convert("RGB")

        if text_settings:
            compositor._draw_strip_text(frame, text_settings)

        # Downscale the whole composited strip-frame for a reasonable
        # GIF file size while keeping the 3-panel layout intact.
        gif_scale = 50
        if text_settings:
            try:
                gif_scale = max(15, min(80, int(text_settings.get("gif_scale", 50))))
            except (TypeError, ValueError):
                gif_scale = 50
        gif_w = max(160, int(config.STRIP_WIDTH * gif_scale / 100))
        gif_h = int(frame.height * (gif_w / frame.width))
        frame = frame.resize((gif_w, gif_h), Image.LANCZOS)

        out_frames.append(frame.convert("P", palette=Image.ADAPTIVE, colors=256))

    out_frames[0].save(
        out_path,
        save_all=True,
        append_images=out_frames[1:],
        duration=config.GIF_FRAME_DURATION_MS,
        loop=config.GIF_LOOP,
        optimize=True,
    )
    return out_path
