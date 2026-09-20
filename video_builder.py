"""
Combine the 3 short clips recorded during each shot's countdown into a
single H.264 MP4 laid out exactly like the photo strip (3 panels,
same slot geometry/theme), all playing back SIMULTANEOUSLY in one file.

Each clip may have a slightly different frame count because capture timing
is driven by a live camera. Clips are resampled onto one shared timeline
before compositing so every panel has the same duration and playback rate.
"""
from concurrent.futures import ThreadPoolExecutor
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


def _last_seconds_window(clip, seconds, fps):
    """Return the last N seconds of a clip, keeping the most recent motion."""
    if not clip:
        return []
    frames_needed = max(1, round(float(seconds) * max(1, int(fps))))
    if len(clip) <= frames_needed:
        return list(clip)
    return list(clip[-frames_needed:])


def _build_single_frame(i, synced_clips, scaled_slots, filter_name, video_w, video_h, overlay_img):
    """Compose one output frame at output resolution. Called in parallel."""
    frame = Image.new("RGB", (video_w, video_h), "white")
    for clip, (x, y, w, h) in zip(synced_clips, scaled_slots):
        src = clip[i]
        if src is None:
            continue
        # Crop and resize to slot size first (cheaper), then filter
        cropped = compositor.crop_to_aspect(src, w / h)
        fitted = cropped.resize((w, h), Image.BILINEAR)
        fitted = compositor.apply_filter(fitted, filter_name)
        frame.paste(fitted, (x, y))
    if overlay_img is not None:
        frame = frame.convert("RGBA")
        frame.alpha_composite(overlay_img)
        frame = frame.convert("RGB")
    return frame


def _build_output_frames(clips, theme, filter_name, target_length, freeze_seconds=1.0, gif_scale=50, motion_window_seconds=3.0):
    """Return the composed frames with the final captured still as the last frame."""
    slots = theme["slots"]
    motion_clips = [_last_seconds_window(clip, motion_window_seconds, config.GIF_CAPTURE_FPS) for clip in clips]
    synced_clips = [_resample_clip(clip, target_length) for clip in motion_clips]

    # Compute output dimensions once
    try:
        scale = max(15, min(80, int(gif_scale)))
    except (TypeError, ValueError):
        scale = 50
    video_w = max(160, int(config.STRIP_WIDTH * scale / 100))
    video_w -= video_w % 2
    video_h = int(config.STRIP_HEIGHT * (video_w / config.STRIP_WIDTH))
    video_h -= video_h % 2

    # Scale slots to output dimensions once, up front
    full_w = config.STRIP_WIDTH
    full_h = config.STRIP_HEIGHT
    scaled_slots = [
        (
            int(x * video_w / full_w),
            int(y * video_h / full_h),
            max(2, int(w * video_w / full_w)),
            max(2, int(h * video_h / full_h)),
        )
        for x, y, w, h in slots
    ]

    # Load and scale overlay once, not per frame
    overlay_img = None
    if theme["overlay_path"]:
        overlay_img = Image.open(theme["overlay_path"]).convert("RGBA")
        if overlay_img.size != (video_w, video_h):
            overlay_img = overlay_img.resize((video_w, video_h), Image.BILINEAR)

    # Build frames in parallel across available CPU threads
    with ThreadPoolExecutor() as pool:
        out_frames = list(pool.map(
            lambda i: _build_single_frame(
                i, synced_clips, scaled_slots, filter_name,
                video_w, video_h, overlay_img,
            ),
            range(target_length),
        ))

    if not out_frames:
        return []

    freeze_frames = max(1, round(float(freeze_seconds) * config.GIF_CAPTURE_FPS))
    return out_frames + [out_frames[-1].copy() for _ in range(freeze_frames)]


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
    if not clips:
        raise ValueError("No GIF frames were captured for this session")

    captured_lengths = [len(clip) for clip in clips]
    if not any(captured_lengths):
        raise ValueError("No GIF frames were captured for this session")

    if gif_duration is None:
        target_length = max(captured_lengths)
    else:
        target_length = max(1, round(float(gif_duration) * config.GIF_CAPTURE_FPS))

    out_frames = _build_output_frames(
        clips,
        theme,
        filter_name,
        target_length,
        freeze_seconds=0.5,
        gif_scale=gif_scale,
        motion_window_seconds=3.0,
    )

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
        "-preset", "fast",
        "-crf", "23",
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