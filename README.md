# Raspberry Pi Photobooth

A kiosk-style photobooth web app: Flask backend + vanilla JS frontend.
Guests tap to start, pick a frame, pose for 3 timed shots (each one also
recording a short video clip during its countdown), pick a filter, then
scan two QR codes to download the finished photo strip (JPG) and the
animated H.264 MP4 straight to their phone.

## Features

- **3×1 photo strip**, rendered at **1652 × 4576 px**, with selectable
  frame/background overlays.
- **Synced MP4**: while each of the 3 countdowns plays, a short clip
  (3s by default, adjustable) is recorded during the 5s countdown. The three clips are combined
  into **one H.264 MP4 laid out like the strip**, with all three panels
  animating **simultaneously**.
- **6 filters**: Original, Warm, Cool, Soft Light, Polaroid, Monochrome
  — applied after capture, previewed live before confirming.
- **QR code delivery**: two QR codes (photo, MP4) pointing at
  locally-served download links — same pattern as commercial booths.
- **Auto camera detection**: scans available camera indices using the
  platform-appropriate OpenCV backend. Linux uses `/dev/video*`/V4L2;
  Windows uses DirectShow indices. This supports USB webcams and phones
  running camera-forwarding apps such as DroidCam.
- Files saved to `saves/images/*.jpg` and `saves/video/*.mp4` in the
  working directory.

## 1. Install (Raspberry Pi OS / Debian-based)

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv libatlas-base-dev libjpeg-dev v4l-utils

cd photobooth
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

If you're using **DroidCam**:
```bash
sudo apt install -y droidcam-cli     # or the DroidCam Linux client from dev47apps.com
droidcam-cli -v <phone-ip> 4747      # or use USB mode per DroidCam's docs
```
Once connected it creates a `/dev/video*` device the app will auto-detect
just like any webcam. Run `v4l2-ctl --list-devices` to confirm which
index it landed on if you ever need to force it in `config.py`
(`CAMERA_INDEX`).

## 2. Add frame themes

Upload themes through the admin page — open
`http://<pi-ip>:5000/admin` from your own phone/laptop on the same
network (this page is intentionally *not* linked from the kiosk UI, so
guests can't reach it). Upload a transparent PNG, give it a name, and it
shows up in the kiosk's "Pick your frame" screen immediately. Design your
PNG at exactly 1652 × 4576px for a pixel-perfect fit; anything else gets
auto-scaled and centered. The admin page shows the default photo-window
coordinates so you know where to leave your artwork transparent. Existing
frames (other than the built-in Classic) can be deleted from the same page.

## 3. Run

```bash
python3 app.py
```

Then point a kiosk browser at `http://localhost:5000`. For a true kiosk
experience on the Pi's touchscreen, launch Chromium in kiosk mode, e.g.:

```bash
chromium-browser --noerrdialogs --disable-infobars --kiosk http://localhost:5000
```

You can autostart that with a `.desktop` file or systemd unit / your
window manager's autostart config.

## 4. Configuration

All tunables live in `config.py`:

| Setting | What it does |
|---|---|
| `CAMERA_INDEX` | Force a camera index; `None` = auto-detect |
| `STRIP_WIDTH` / `STRIP_HEIGHT` | Final strip resolution (default 1652×4576) |
| `SHOT_DURATION_SECONDS` | Countdown length **and** per-shot video clip length |
| `GIF_CAPTURE_FPS` | Frames/sec captured for the MP4 during each countdown |
| `GIF_PANEL_MAX_WIDTH` | Downscale width per video panel (keeps file size sane) |
| `FILTERS` | The 5(+) filters offered after capture |
| `SERVER_PORT` | Port used for the app **and** embedded in QR download links |
| `FORCE_HOST_IP` | Override the LAN IP embedded in QR codes if auto-detect picks the wrong NIC |
| `IDLE_RESET_SECONDS` | Auto-return-to-idle timeout after a finished session |

Guests' phones must be on the **same LAN** (or the same Wi-Fi the Pi is
hosting, if you run the Pi as its own access point) to scan the QR codes
and reach the download links.

## 5. Project layout

```
app.py              Flask routes + session state machine
camera.py           Camera auto-detection + threaded frame grabbing
compositor.py        Filters, frame-theme loading, strip compositing
video_builder.py     Builds the synced 3-panel H.264 MP4
config.py            All tunable settings
templates/index.html Kiosk single-page shell
templates/admin.html  Staff-only frame upload/manage page (/admin)
static/css/style.css Kiosk UI styling
static/css/admin.css Admin page styling
static/js/app.js     Kiosk UI flow/logic
static/js/admin.js   Admin page upload/delete logic
static/frames/themes/  Frame overlay PNGs + JSON metadata
saves/images/         Finished JPG strips land here
saves/video/           Finished MP4 videos land here
```

## Notes / known limitations

- This app assumes a **single active kiosk session at a time** (typical
  for a single-camera booth) — state lives in memory, not a database.
- The live preview streams MJPEG over HTTP, which is simple and reliable
  on a LAN but not meant for streaming over the open internet.
- QR download links are plain HTTP on your LAN; if you expose the booth
  beyond your local network, put it behind HTTPS and add auth.

## 6. Recent UI / framing changes

The current build uses a **dark-blue UI** throughout the guest kiosk and the admin panel. The previous gold/amber UI accent has been replaced by blue.

The default strip geometry is now:

- Strip: **1652 × 4576 px**
- Each photo window: **1352 × 1352 px**
- Side margin: **150 px**
- Top margin: **120 px**
- Gap: **50 px**
- Bottom/footer area: **300 px**

This gives each photo an exact **1:1 aspect ratio**. The live camera feed,
captured stills, and MP4 frames are center-cropped to the configured 1:1
photo aspect ratio before compositing. The kiosk preview therefore shows the
same framing that enters the final photo window.

Frame thumbnails use `contain` instead of `cover`, so the entire tall photo-strip frame is visible in the frame picker and admin page.

The `/admin` page now follows the supplied dashboard layout with sections for
Camera, Session, Frames, Output, Display, Security, and Network. The controls
are wired to the Flask backend and persist to `settings.json`.

### Admin PIN

The default admin PIN for a fresh installation is **1234**. Change it from **Admin → Security**. You can also set `PHOTOBOOTH_ADMIN_PIN` before the first run. The changed PIN is stored as a SHA-256 hash in `settings.json` rather than as plain text.

### Camera selection and rescan
Camera discovery is non-blocking: `start.sh`/`app.py` starts Flask while
available camera indices are scanned in a background thread. The Admin >
Camera panel can rescan and select any detected working camera without
requiring a code change. This prevents inactive camera devices from blocking
the localhost web interface during startup.
