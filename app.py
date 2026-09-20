"""
Photobooth Flask backend.

Run with:  python3 app.py
Then open a browser (ideally Chromium in kiosk mode) to http://localhost:5000
"""
import base64
import io
import json
import os
import socket
import threading
import hashlib
import time
import uuid
from datetime import datetime

import cv2
import qrcode
from PIL import Image
from flask import Flask, Response, jsonify, request, send_from_directory, render_template, session

import compositor
import config
import video_builder
from camera import camera_manager

app = Flask(__name__)
app.secret_key = os.environ.get("PHOTOBOOTH_SECRET_KEY", "photobooth-local-admin-secret")


DEFAULT_ADMIN_SETTINGS = {
    "aspect_mode": config.DEFAULT_ASPECT_MODE,
    "countdown": int(config.SHOT_DURATION_SECONDS),
    "gif_duration": min(3, int(config.SHOT_DURATION_SECONDS)),
    "gif_scale": 50,
    "gif_fps": config.GIF_CAPTURE_FPS,
    "force_host_ip": config.FORCE_HOST_IP or "",
    "server_port": config.SERVER_PORT,
    "camera_source": "local",
    "droidcam_ip": "",
    "droidcam_port": 4747,
    "droidcam_resolution": "1280x720",
}


def _admin_pin_hash(pin):
    return hashlib.sha256(str(pin).encode("utf-8")).hexdigest()


def _load_admin_settings():
    settings = dict(DEFAULT_ADMIN_SETTINGS)
    try:
        with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            settings.update({k: v for k, v in saved.items() if k in settings})
            if saved.get("admin_pin_hash"):
                settings["admin_pin_hash"] = saved["admin_pin_hash"]
    except (OSError, ValueError, TypeError):
        pass
    return settings


def _save_admin_settings(settings):
    clean = {k: settings[k] for k in DEFAULT_ADMIN_SETTINGS if k in settings}
    if "admin_pin_hash" in settings:
        clean["admin_pin_hash"] = settings["admin_pin_hash"]
    tmp = config.SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)
    os.replace(tmp, config.SETTINGS_FILE)


def _public_admin_settings(settings):
    return {k: settings[k] for k in DEFAULT_ADMIN_SETTINGS if k in settings}


def _active_aspect_mode():
    mode = ADMIN_SETTINGS.get("aspect_mode", config.DEFAULT_ASPECT_MODE)
    return mode if mode in config.ASPECT_MODES else config.DEFAULT_ASPECT_MODE


def _active_aspect_ratio():
    return config.ASPECT_MODES[_active_aspect_mode()]["ratio"]


def _session_aspect_ratio():
    mode = SESSION.get("aspect_mode", _active_aspect_mode())
    return config.ASPECT_MODES.get(mode, config.ASPECT_MODES[config.DEFAULT_ASPECT_MODE])["ratio"]


ADMIN_SETTINGS = _load_admin_settings()
ADMIN_PIN_HASH = ADMIN_SETTINGS.get("admin_pin_hash") or _admin_pin_hash(config.ADMIN_PIN)
# Restore the persisted camera source before the camera worker starts.
camera_manager.droidcam = {
    "ip": ADMIN_SETTINGS.get("droidcam_ip", ""),
    "port": int(ADMIN_SETTINGS.get("droidcam_port", 4747)),
    "resolution": ADMIN_SETTINGS.get("droidcam_resolution", "1280x720"),
}
if ADMIN_SETTINGS.get("camera_source") == "droidcam":
    camera_manager.source_type = "droidcam"


# Apply persisted runtime settings immediately.
config.SHOT_DURATION_SECONDS = float(ADMIN_SETTINGS["countdown"])
config.GIF_CAPTURE_FPS = int(ADMIN_SETTINGS["gif_fps"])
config.GIF_FRAME_DURATION_MS = int(1000 / max(1, config.GIF_CAPTURE_FPS))
config.FORCE_HOST_IP = ADMIN_SETTINGS.get("force_host_ip") or None

# ---------------------------------------------------------------------------
# In-memory session state (single kiosk = single active session at a time)
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()
SESSION = {
    "id": None,
    "theme_id": "classic",
    "shots": [],        # list of {"photo": PIL.Image, "gif_frames": [PIL.Image, ...]}
    "filter": "Original",
    "aspect_mode": _active_aspect_mode(),
    "final_jpg_name": None,
    "final_gif_name": None,
}


def _reset_session():
    with _state_lock:
        SESSION["id"] = uuid.uuid4().hex[:10]
        SESSION["theme_id"] = "classic"
        SESSION["shots"] = []
        SESSION["filter"] = "Original"
        SESSION["aspect_mode"] = _active_aspect_mode()
        SESSION["final_jpg_name"] = None
        SESSION["final_gif_name"] = None


# ---------------------------------------------------------------------------
# Networking helper for QR codes
# ---------------------------------------------------------------------------
def get_lan_ip():
    if config.FORCE_HOST_IP:
        return config.FORCE_HOST_IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def make_qr_data_uri(url: str) -> str:
    qr = qrcode.QRCode(border=1, box_size=8)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def pil_to_data_uri(img, fmt="JPEG", quality=85):
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/jpeg" if fmt.upper() == "JPEG" else f"image/{fmt.lower()}"
    return f"data:{mime};base64,{b64}"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", filters=config.FILTERS)


@app.route("/admin")
def admin_page():
    default_slots = compositor.default_slots(_active_aspect_mode())
    return render_template(
        "admin.html",
        themes=compositor.list_themes(_active_aspect_mode()),
        strip_width=config.STRIP_WIDTH,
        strip_height=config.STRIP_HEIGHT,
        default_slots=default_slots,
        photo_aspect=_active_aspect_ratio(),
        aspect_mode=_active_aspect_mode(),
        aspect_modes=config.ASPECT_MODES,
    )


# ---------------------------------------------------------------------------
# Live preview (MJPEG)
# ---------------------------------------------------------------------------
def _mjpeg_generator():
    while True:
        frame = camera_manager.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        # Crop the live feed to the exact square photo-window aspect ratio.
        # The same crop is used for captured stills, preventing the final
        # output from unexpectedly cutting off a different part of the image.
        h, w = frame.shape[:2]
        target_ratio = _session_aspect_ratio()
        current_ratio = w / h
        if current_ratio > target_ratio:
            new_w = max(1, int(round(h * target_ratio)))
            left = (w - new_w) // 2
            frame = frame[:, left:left + new_w]
        elif current_ratio < target_ratio:
            new_h = max(1, int(round(w / target_ratio)))
            top = (h - new_h) // 2
            frame = frame[top:top + new_h, :]
        h, w = frame.shape[:2]
        if w > config.PREVIEW_STREAM_MAX_WIDTH:
            scale = config.PREVIEW_STREAM_MAX_WIDTH / w
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        ok, buf = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, config.PREVIEW_JPEG_QUALITY]
        )
        if not ok:
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        )
        time.sleep(1 / 30)


@app.route("/video_feed")
def video_feed():
    return Response(
        _mjpeg_generator(), mimetype="multipart/x-mixed-replace; boundary=frame"
    )


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------
@app.route("/api/session/start", methods=["POST"])
def api_session_start():
    _reset_session()
    return jsonify({"session_id": SESSION["id"], "shots_per_strip": config.SHOTS_PER_STRIP,
                     "shot_duration": config.SHOT_DURATION_SECONDS,
                     "photo_aspect": _active_aspect_ratio(),
                     "aspect_mode": SESSION["aspect_mode"]})


@app.route("/api/themes", methods=["GET"])
def api_themes():
    themes = compositor.list_themes(_active_aspect_mode())
    return jsonify(
        [{"id": t["id"], "name": t["name"], "thumbnail": t["thumbnail"]} for t in themes if t["id"] != "classic"]
    )


@app.route("/api/themes/upload", methods=["POST"])
def api_themes_upload():
    auth = _require_admin()
    if auth:
        return auth
    name = request.form.get("name", "").strip()
    aspect_mode = request.form.get("aspect_mode", config.DEFAULT_ASPECT_MODE)
    if aspect_mode not in config.ASPECT_MODES:
        return jsonify({"error": "Unsupported aspect ratio mode"}), 400
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "No file was uploaded"}), 400
    if not name:
        name = os.path.splitext(file.filename)[0]

    slots = None
    slots_raw = request.form.get("slots", "").strip()
    if slots_raw:
        try:
            parsed = json.loads(slots_raw)
            if not (isinstance(parsed, list) and len(parsed) == config.SHOTS_PER_STRIP):
                raise ValueError
            slots = parsed
        except Exception:
            return jsonify(
                {"error": f"'slots' must be a JSON array of {config.SHOTS_PER_STRIP} [x, y, w, h] rects"}
            ), 400

    try:
        theme = compositor.save_uploaded_theme(name, file.stream, slots=slots, aspect_mode=aspect_mode)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Upload failed: {e}"}), 500

    return jsonify(
        {
            "ok": True,
            "theme": {"id": theme["id"], "name": theme["name"], "thumbnail": theme["thumbnail"]},
        }
    )


@app.route("/api/themes/delete/<theme_id>", methods=["POST"])
def api_themes_delete(theme_id):
    auth = _require_admin()
    if auth:
        return auth
    ok = compositor.delete_theme(theme_id)
    if not ok:
        return jsonify({"error": "That theme can't be deleted"}), 400
    return jsonify({"ok": True})


@app.route("/api/session/theme", methods=["POST"])
def api_session_theme():
    data = request.get_json(force=True)
    with _state_lock:
        SESSION["theme_id"] = data.get("theme_id", "classic")
    return jsonify({"ok": True, "theme_id": SESSION["theme_id"]})


@app.route("/api/session/capture/<int:shot_index>", methods=["POST"])
def api_session_capture(shot_index):
    """
    Blocking capture: records ~SHOT_DURATION_SECONDS of frames for the
    GIF clip (started the instant this request arrives, matching the
    on-screen countdown the frontend starts at the same time), then
    grabs one final full-resolution frame as the still photo.
    """
    if not (0 <= shot_index < config.SHOTS_PER_STRIP):
        return jsonify({"error": "invalid shot index"}), 400

    duration = float(config.SHOT_DURATION_SECONDS)
    gif_duration = min(float(ADMIN_SETTINGS.get("gif_duration", duration)), duration)
    fps = max(1, int(config.GIF_CAPTURE_FPS))
    interval = 1.0 / fps
    target_frames = max(1, round(gif_duration * fps))
    gif_frames = []
    last_frame = None

    start = time.monotonic()
    for frame_index in range(target_frames):
        target_time = start + frame_index * interval
        while True:
            remaining = target_time - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 0.005))

        frame = camera_manager.get_frame()
        if frame is not None:
            last_frame = frame
        elif last_frame is not None:
            frame = last_frame
        if frame is None:
            continue

        pil = compositor.cv2_to_pil(frame)
        # Match the live preview / final photo-window framing first.
        pil = compositor.crop_to_aspect(pil, config.ASPECT_MODES[SESSION["aspect_mode"]]["ratio"])
        ratio = config.GIF_PANEL_MAX_WIDTH / pil.width
        pil_small = pil.resize(
            (config.GIF_PANEL_MAX_WIDTH, int(pil.height * ratio)), Image.LANCZOS
        )
        gif_frames.append(pil_small)

    # Keep the final still aligned with the original countdown deadline even
    # when GIF capture is configured shorter than the countdown.
    while True:
        remaining = start + duration - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(remaining, 0.005))

    # one last fresh frame right at shutter time for the sharpest still
    final_frame = camera_manager.get_frame()
    if final_frame is None:
        final_frame = last_frame
    if final_frame is None:
        return jsonify({"error": "camera not available"}), 503

    still = compositor.crop_to_aspect(compositor.cv2_to_pil(final_frame), config.ASPECT_MODES[SESSION["aspect_mode"]]["ratio"])
    
    with _state_lock:
        shots = SESSION["shots"]
        while len(shots) <= shot_index:
            shots.append(None)
        shots[shot_index] = {"photo": still, "gif_frames": gif_frames}

    thumb = still.copy()
    thumb.thumbnail((500, 500))
    return jsonify({"ok": True, "shot_index": shot_index, "preview": pil_to_data_uri(thumb)})


@app.route("/api/session/frame_previews", methods=["POST"])
def api_frame_previews():
    """Render a strip preview for each selectable frame so the UI can show
    a full-size-looking strip thumbnail in the same style as the filter picker."""
    with _state_lock:
        shots = list(SESSION["shots"])
        filter_name = SESSION.get("filter", "Original")
        aspect_mode = SESSION["aspect_mode"]
    if len(shots) != config.SHOTS_PER_STRIP or any(s is None for s in shots):
        return jsonify({"error": "not all shots captured yet"}), 400

    photos = [s["photo"] for s in shots]
    previews = {}
    for theme in compositor.list_themes(aspect_mode):
        if theme["id"] == "classic":
            continue
        thumb = compositor.compose_strip_thumbnail(photos, theme["id"], filter_name, max_width=300, aspect_mode=aspect_mode)
        previews[theme["id"]] = pil_to_data_uri(thumb, fmt="JPEG", quality=78)
    return jsonify({"previews": previews})


@app.route("/api/session/filter_preview", methods=["POST"])
def api_filter_preview():
    """Render a small composite for every filter so the UI can show a
    live picker without regenerating the full-res strip each time."""
    with _state_lock:
        shots = list(SESSION["shots"])
        theme_id = SESSION["theme_id"]
        aspect_mode = SESSION["aspect_mode"]
    if len(shots) != config.SHOTS_PER_STRIP or any(s is None for s in shots):
        return jsonify({"error": "not all shots captured yet"}), 400

    photos = [s["photo"] for s in shots]
    previews = {}
    for name in config.FILTERS:
        thumb = compositor.compose_strip_thumbnail(photos, theme_id, name, max_width=300, aspect_mode=aspect_mode)
        previews[name] = pil_to_data_uri(thumb, fmt="JPEG", quality=78)
    return jsonify({"previews": previews})


@app.route("/api/session/set_filter", methods=["POST"])
def api_set_filter():
    data = request.get_json(force=True)
    name = data.get("filter", "Original")
    if name not in config.FILTERS:
        name = "Original"
    with _state_lock:
        SESSION["filter"] = name
    return jsonify({"ok": True, "filter": name})


@app.route("/api/session/finalize", methods=["POST"])
def api_finalize():
    with _state_lock:
        shots = list(SESSION["shots"])
        theme_id = SESSION["theme_id"]
        filter_name = SESSION["filter"]
        session_id = SESSION["id"]
        aspect_mode = SESSION["aspect_mode"]

    if len(shots) != config.SHOTS_PER_STRIP or any(s is None for s in shots):
        return jsonify({"error": "not all shots captured yet"}), 400

    photos = [s["photo"] for s in shots]
    clips = [s["gif_frames"] for s in shots]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{timestamp}_{session_id}"
    jpg_name = f"{base_name}.jpg"
    video_name = f"{base_name}.mp4"

    strip = compositor.compose_strip(photos, theme_id, filter_name, aspect_mode=aspect_mode)
    jpg_path = f"{config.IMAGES_DIR}/{jpg_name}"
    strip.save(jpg_path, format="JPEG", quality=92)

    video_path = f"{config.VIDEOS_DIR}/{video_name}"
    video_builder.build_synced_mp4(
        clips, theme_id, filter_name, video_path, aspect_mode=aspect_mode, gif_duration=min(
            float(ADMIN_SETTINGS.get("gif_duration", config.SHOT_DURATION_SECONDS)),
            float(config.SHOT_DURATION_SECONDS),
        ), gif_scale=ADMIN_SETTINGS.get("gif_scale", 50)
    )

    with _state_lock:
        SESSION["final_jpg_name"] = jpg_name
        SESSION["final_gif_name"] = video_name

    ip = get_lan_ip()
    jpg_url = f"http://{ip}:{config.SERVER_PORT}/download/image/{jpg_name}"
    video_url = f"http://{ip}:{config.SERVER_PORT}/download/video/{video_name}"

    return jsonify(
        {
            "ok": True,
            "jpg_url": jpg_url,
            "video_url": video_url,
            "jpg_qr": make_qr_data_uri(jpg_url),
            "video_qr": make_qr_data_uri(video_url),
            "strip_preview": pil_to_data_uri(strip.copy().resize(
                (strip.width // 3, strip.height // 3)
            )),
        }
    )


@app.route("/api/session/reset", methods=["POST"])
def api_reset():
    _reset_session()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------
def _require_admin():
    if not session.get("admin_authenticated"):
        return jsonify({"error": "Admin authentication required"}), 401
    return None


@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    global ADMIN_PIN_HASH
    data = request.get_json(force=True) or {}
    pin = str(data.get("pin", ""))
    if pin and _admin_pin_hash(pin) == ADMIN_PIN_HASH:
        session["admin_authenticated"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Incorrect PIN"}), 401


@app.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.pop("admin_authenticated", None)
    return jsonify({"ok": True})


@app.route("/api/admin/settings", methods=["GET"])
def api_admin_settings_get():
    auth = _require_admin()
    if auth:
        return auth
    settings = _public_admin_settings(ADMIN_SETTINGS)
    settings["photo_aspect"] = _active_aspect_ratio()
    settings["aspect_mode"] = _active_aspect_mode()
    settings["aspect_modes"] = config.ASPECT_MODES
    settings["strip_width"] = config.STRIP_WIDTH
    settings["strip_height"] = config.STRIP_HEIGHT
    settings["camera_index"] = camera_manager.index
    settings["camera_source"] = camera_manager.source_type or settings.get("camera_source", "local")
    settings["droidcam_ip"] = camera_manager.droidcam.get("ip", settings.get("droidcam_ip", ""))
    settings["droidcam_port"] = camera_manager.droidcam.get("port", settings.get("droidcam_port", 4747))
    settings["droidcam_resolution"] = camera_manager.droidcam.get("resolution", settings.get("droidcam_resolution", "1280x720"))
    return jsonify(settings)


@app.route("/api/admin/settings", methods=["POST"])
def api_admin_settings_save():
    auth = _require_admin()
    if auth:
        return auth
    global ADMIN_SETTINGS
    data = request.get_json(force=True) or {}
    updated = dict(ADMIN_SETTINGS)

    def integer(key, lo, hi):
        value = int(data.get(key, updated[key]))
        if not lo <= value <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi}")
        updated[key] = value

    try:
        if "aspect_mode" in data:
            if data["aspect_mode"] not in config.ASPECT_MODES:
                raise ValueError("Unsupported aspect ratio mode")
            updated["aspect_mode"] = data["aspect_mode"]
        if "countdown" in data: integer("countdown", 2, 15)
        if "gif_duration" in data: integer("gif_duration", 1, 10)
        if "gif_scale" in data: integer("gif_scale", 15, 80)
        if "gif_fps" in data: integer("gif_fps", 6, 24)
        if "force_host_ip" in data: updated["force_host_ip"] = str(data["force_host_ip"]).strip()
        if "server_port" in data: integer("server_port", 1024, 65535)
        if "camera_source" in data:
            if data["camera_source"] not in ("local", "droidcam"):
                raise ValueError("camera_source must be local or droidcam")
            updated["camera_source"] = data["camera_source"]
        if "droidcam_ip" in data: updated["droidcam_ip"] = str(data["droidcam_ip"]).strip()[:255]
        if "droidcam_port" in data:
            value = int(data["droidcam_port"])
            if not 1 <= value <= 65535: raise ValueError("droidcam_port must be between 1 and 65535")
            updated["droidcam_port"] = value
        if "droidcam_resolution" in data:
            if data["droidcam_resolution"] not in ("640x480", "1280x720", "1920x1080"):
                raise ValueError("Unsupported DroidCam resolution")
            updated["droidcam_resolution"] = data["droidcam_resolution"]
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400

    ADMIN_SETTINGS = updated
    if "aspect_mode" in data:
        with _state_lock:
            SESSION["aspect_mode"] = _active_aspect_mode()
    config.SHOT_DURATION_SECONDS = float(updated["countdown"])
    config.GIF_CAPTURE_FPS = int(updated["gif_fps"])
    config.GIF_FRAME_DURATION_MS = int(1000 / max(1, config.GIF_CAPTURE_FPS))
    config.FORCE_HOST_IP = updated.get("force_host_ip") or None
    _save_admin_settings(ADMIN_SETTINGS)
    # Camera source changes take effect immediately.
    try:
        if updated.get("camera_source") == "droidcam":
            camera_manager.switch_droidcam(
                updated.get("droidcam_ip", ""),
                updated.get("droidcam_port", 4747),
                updated.get("droidcam_resolution", "1280x720"),
            )
        elif updated.get("camera_source") == "local" and camera_manager.index is None:
            camera_manager.rescan(background=True)
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "ok": True,
        "settings": _public_admin_settings(ADMIN_SETTINGS),
        "restart_required": "server_port" in data or "force_host_ip" in data,
    })


@app.route("/api/admin/pin", methods=["POST"])
def api_admin_change_pin():
    auth = _require_admin()
    if auth:
        return auth
    global ADMIN_PIN_HASH
    data = request.get_json(force=True) or {}
    current = str(data.get("current", ""))
    new_pin = str(data.get("new", ""))
    confirm = str(data.get("confirm", ""))
    if _admin_pin_hash(current) != ADMIN_PIN_HASH:
        return jsonify({"error": "Current PIN is incorrect"}), 400
    if len(new_pin) < 4 or not new_pin.isdigit():
        return jsonify({"error": "New PIN must contain at least 4 digits"}), 400
    if new_pin != confirm:
        return jsonify({"error": "New PINs do not match"}), 400
    ADMIN_PIN_HASH = _admin_pin_hash(new_pin)
    # Store only a hash; never persist the PIN itself.
    ADMIN_SETTINGS["admin_pin_hash"] = ADMIN_PIN_HASH
    # Keep backward compatibility with the compact settings file by writing
    # the hash separately without exposing it through GET.
    try:
        saved = _load_admin_settings()
        saved["admin_pin_hash"] = ADMIN_PIN_HASH
        with open(config.SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(saved, f, indent=2)
    except OSError as exc:
        return jsonify({"error": f"Could not save PIN: {exc}"}), 500
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# File downloads (what the QR codes point to)
# ---------------------------------------------------------------------------
@app.route("/download/image/<path:filename>")
def download_image(filename):
    return send_from_directory(config.IMAGES_DIR, filename, as_attachment=True)


@app.route("/download/video/<path:filename>")
def download_video(filename):
    return send_from_directory(config.VIDEOS_DIR, filename, as_attachment=True)


# ---------------------------------------------------------------------------
# Camera utilities
# ---------------------------------------------------------------------------
@app.route("/api/cameras", methods=["GET"])
def api_cameras():
    # Never perform a blocking V4L2 probe in the Flask request thread.
    camera_manager.rescan(background=True)
    return jsonify(camera_manager.status())


@app.route("/api/cameras/status", methods=["GET"])
def api_cameras_status():
    return jsonify(camera_manager.status())


@app.route("/api/cameras/switch", methods=["POST"])
def api_camera_switch():
    data = request.get_json(force=True) or {}
    idx = data.get("index")
    try:
        camera_manager.switch(int(idx))
        ADMIN_SETTINGS["camera_source"] = "local"
        _save_admin_settings(ADMIN_SETTINGS)
        return jsonify({"ok": True, "active": camera_manager.index, "source_type": camera_manager.source_type})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/cameras/droidcam/test", methods=["POST"])
def api_droidcam_test():
    data = request.get_json(force=True) or {}
    try:
        from camera import probe_droidcam
        ok, url = probe_droidcam(data.get("ip", ""), int(data.get("port", 4747)), data.get("resolution", "1280x720"))
        if not ok:
            return jsonify({"ok": False, "error": f"No video frames received from {url}"}), 400
        return jsonify({"ok": True, "url": url})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/cameras/droidcam", methods=["POST"])
def api_droidcam_save():
    auth = _require_admin()
    if auth:
        return auth
    data = request.get_json(force=True) or {}
    try:
        ip = str(data.get("ip", "")).strip()
        port = int(data.get("port", 4747))
        resolution = data.get("resolution", "1280x720")
        camera_manager.switch_droidcam(ip, port, resolution)
        ADMIN_SETTINGS.update({
            "camera_source": "droidcam",
            "droidcam_ip": ip,
            "droidcam_port": port,
            "droidcam_resolution": resolution,
        })
        _save_admin_settings(ADMIN_SETTINGS)
        return jsonify({"ok": True, "source_type": "droidcam", "url": f"http://{ip}:{port}/video/{resolution}"})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Starting camera detection in background...")
    idx = camera_manager.start()
    if idx is not None:
        print(f"Camera ready on /dev/video{idx}")
    else:
        print("Camera scan is running in the background. The admin page can rescan/select a camera.")
    _reset_session()
    app.run(host="0.0.0.0", port=config.SERVER_PORT, threaded=True, debug=False)