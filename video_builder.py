"""
Combine the 3 short clips recorded during each shot's countdown into a
single H.264 MP4 laid out exactly like the photo strip (3 panels,
same slot geometry/theme), all playing back SIMULTANEOUSLY in one file.

Each clip may have a slightly different frame count because capture timing
is driven by a live camera. Clips are resampled onto one shared timeline
before compositing so every panel has the same duration and playback rate.
"""
from PIL import Image
import subprocess

import imageio_ffmpeg
import compositor
import config


def _resample_clip(clip, target_length):
    """Map a captured clip onto the fixed output timeline."""
    if not clip:
        return [None] * target_length
    if len(clip) == target_length:
        return list(clip)
    if target_length == 1:
        return [clip[0]]

    last_source_index = len(clip) - 1
    last_target_index = target_length - 1
    return [
        clip[round(index * last_source_index / last_target_index)]
        for index in range(target_length)
    ]


def build_synced_mp4(clips, theme_id, filter_name, out_path, aspect_mode=config.DEFAULT_ASPECT_MODE, gif_duration=None, gif_scale=50):
    """
    clips: list of 3 lists of PIL RGB frames (already in chronological
           order), one list per shot, roughly config.GIF_CAPTURE_FPS fps.
    theme_id / filter_name: same as compose_strip, applied to every frame
           for visual consistency with the final still.
    out_path: where to write the .mp4
    gif_duration: target duration in seconds for every panel.
    gif_scale: output width as a percentage of the full strip width.
    """
    theme = compositor.get_theme(theme_id, aspect_mode)
    slots = theme["slots"]
    if not clips:
        raise ValueError("No GIF frames were captured for this session")

    captured_lengths = [len(clip) for clip in clips]
    if not any(captured_lengths):
        raise ValueError("No GIF frames were captured for this session")

    if gif_duration is None:
        target_length = max(captured_lengths)
    else:
        target_length = max(1, round(float(gif_duration) * config.GIF_CAPTURE_FPS))
    synced_clips = [_resample_clip(clip, target_length) for clip in clips]

    canvas_w, canvas_h = config.STRIP_WIDTH, config.STRIP_HEIGHT
    out_frames = []

    for i in range(target_length):
        frame = Image.new("RGB", (canvas_w, canvas_h), "white")

        if theme["overlay_path"]:
            overlay = Image.open(theme["overlay_path"]).convert("RGBA")
            if overlay.size != frame.size:
                overlay = overlay.resize(frame.size, Image.LANCZOS)
            frame = frame.convert("RGBA")
            frame.alpha_composite(overlay)
            frame = frame.convert("RGB")

        for clip, slot in zip(synced_clips, slots):
            src = clip[i]
            if src is None:
                continue
            filtered = compositor.apply_filter(src, filter_name)
            x, y, w, h = slot
            filtered = compositor.crop_to_aspect(filtered, w / h)
            fitted = filtered.resize((w, h), Image.LANCZOS)
            frame.paste(fitted, (x, y))

        # Downscale the whole composited strip-frame for a reasonable
        # video file size while keeping the 3-panel layout intact.
        try:
            scale = max(15, min(80, int(gif_scale)))
        except (TypeError, ValueError):
            scale = 50
        video_w = max(160, int(config.STRIP_WIDTH * scale / 100))
        # yuv420p/H.264 requires even dimensions.
        video_w -= video_w % 2
        video_h = int(frame.height * (video_w / frame.width))
        video_h -= video_h % 2
        out_frames.append(frame.resize((video_w, video_h), Image.LANCZOS).convert("RGB"))

    video_w, video_h = out_frames[0].size
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{video_w}x{video_h}",
        "-r", str(config.GIF_CAPTURE_FPS),
        "-i", "-",
        "-an",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out_path,
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for frame in out_frames:
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        error_output = process.stderr.read().decode("utf-8", errors="replace")
        return_code = process.wait()
    except Exception:
        process.kill()
        process.wait()
        raise
    if return_code:
        raise RuntimeError(f"H.264 encoding failed: {error_output[-1000:]}")
    return out_path
