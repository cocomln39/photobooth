# Raspberry Pi Photobooth

A kiosk-style photobooth web app: Flask backend + vanilla JS frontend.
Guests tap to start, pick a frame, pose for 3 timed shots (each one also
recording a short GIF clip during its countdown), pick a filter, then
scan two QR codes to download the finished photo strip (JPG) and the
animated GIF straight to their phone.

## Features

- **3×1 photo strip**, rendered at **1652 × 4920 px**, with selectable
  frame/background overlays.
- **Synced GIF**: while each of the 3 countdowns plays, a short clip
  (5s by default, adjustable) is recorded. The three clips are combined
  into **one GIF laid out like the strip**, with all three panels
  animating **simultaneously**.
- **5 filters**: Original, Warm, Cool, Soft Light, Polaroid, Monochrome
  — applied after capture, previewed live before confirming.
- **QR code delivery**: two QR codes (photo, GIF) pointing at
  locally-served download links — same pattern as commercial booths.
- **Auto camera detection**: scans `/dev/video*` for any working
  camera, including USB webcams and phones running USB camera-forwarding
  apps like DroidCam (they show up as a normal V4L2 device once their
  Pi-side client/driver is running — no special-casing needed).
- Files saved to `saves/images/*.jpg` and `saves/gif/*.gif` in the
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

Two example themes are already generated and committed under
`static/frames/themes/` (Gold Foil, Pastel Dots). Two ways to add more:

**A. Upload through the admin page (recommended)** — open
`http://<pi-ip>:5000/admin` from your own phone/laptop on the same
network (this page is intentionally *not* linked from the kiosk UI, so
guests can't reach it). Upload a transparent PNG, give it a name, and it
shows up in the kiosk's "Pick your frame" screen immediately. Design your
PNG at exactly 1652 × 4920px for a pixel-perfect fit; anything else gets
auto-scaled and centered. The admin page shows the default photo-window
coordinates so you know where to leave your artwork transparent, or you
can paste custom `[x, y, w, h]` slot coordinates per photo under
"Advanced" if your design doesn't follow the default grid. Existing
frames (other than the built-in Classic) can be deleted from the same
page.

**B. Script it** — `python3 make_demo_themes.py` regenerates the two
bundled examples and doubles as a template if you'd rather generate
frames programmatically.

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
| `CAMERA_INDEX` | Force a specific `/dev/videoN`; `None` = auto-detect |
| `STRIP_WIDTH` / `STRIP_HEIGHT` | Final strip resolution (default 1652×2990) |
| `SHOT_DURATION_SECONDS` | Countdown length **and** per-shot GIF clip length |
| `GIF_CAPTURE_FPS` | Frames/sec captured for the GIF during each countdown |
| `GIF_PANEL_MAX_WIDTH` | Downscale width per GIF panel (keeps file size sane) |
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
gif_builder.py       Builds the synced 3-panel animated GIF
config.py            All tunable settings
make_demo_themes.py  Generates/documents example frame overlays
templates/index.html Kiosk single-page shell
templates/admin.html  Staff-only frame upload/manage page (/admin)
static/css/style.css Kiosk UI styling
static/css/admin.css Admin page styling
static/js/app.js     Kiosk UI flow/logic
static/js/admin.js   Admin page upload/delete logic
static/frames/themes/  Frame overlay PNGs + JSON metadata
saves/images/         Finished JPG strips land here
saves/gif/             Finished GIFs land here
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

- Strip: **1652 × 4920 px**
- Each photo window: **1452 × 1452 px**
- Side margin: **100 px**
- Top margin: **60 px**
- Gap: **50 px**
- Bottom/footer area: about **402 px**

This gives each photo an exact **1:1 aspect ratio**. The live camera feed is center-cropped to 16:9 on the server, and captured stills/GIF frames use the same crop before compositing. The kiosk preview therefore shows the same framing that enters the final photo window rather than using a 16:9 `object-fit: cover` preview that later crops differently.

Frame thumbnails use `contain` instead of `cover`, so the entire tall photo-strip frame is visible in the frame picker and admin page.

The `/admin` page now follows the supplied dashboard layout with sections for Camera, Session, Frames, Text, Output, Display, Security, and Network. The controls are wired to the Flask backend and persist to `settings.json`.

### Admin PIN

The default admin PIN for a fresh installation is **1234**. Change it from **Admin → Security**. You can also set `PHOTOBOOTH_ADMIN_PIN` before the first run. The changed PIN is stored as a SHA-256 hash in `settings.json` rather than as plain text.

### Camera selection and rescan
Camera discovery is non-blocking: `start.sh`/`app.py` starts Flask while V4L2 devices are scanned in a background thread. The Admin > Camera panel can rescan and select any detected working `/dev/video*` device without requiring a code change. This prevents inactive V4L2 nodes from blocking the localhost web interface during startup.
