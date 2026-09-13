"""
Central configuration for the photobooth app.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
CAMERA_INDEX = None
CAMERA_REQUEST_WIDTH = 1920
CAMERA_REQUEST_HEIGHT = 1080
CAMERA_MAX_INDEX_SCAN = 10
PREVIEW_JPEG_QUALITY = 80
PREVIEW_STREAM_MAX_WIDTH = 960

# The final photo windows use the same 1:1 framing as the camera feed.
# The live feed, captured stills, and GIF frames are cropped to this ratio
# before being placed into the frame, so the guest sees the same composition
# that appears in the final output.
PHOTO_ASPECT_RATIO = 1.0

# ---------------------------------------------------------------------------
# Photo strip output
# ---------------------------------------------------------------------------
SHOTS_PER_STRIP = 3
STRIP_WIDTH = 1652
# Three square photo windows with generous white margins/gutters.
STRIP_HEIGHT = 4476

STRIP_MARGIN_SIDE = 150
STRIP_MARGIN_TOP = 80
STRIP_MARGIN_BOTTOM = 240
STRIP_GAP = 50

# ---------------------------------------------------------------------------
# Countdown / GIF capture defaults
# ---------------------------------------------------------------------------
SHOT_DURATION_SECONDS = 5.0
GIF_CAPTURE_FPS = 8
GIF_PANEL_MAX_WIDTH = 480
GIF_FRAME_DURATION_MS = int(1000 / GIF_CAPTURE_FPS)
GIF_LOOP = 0

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
FILTERS = ["Original", "Warm", "Cool", "Soft Light", "Polaroid", "Monochrome"]

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
SAVE_ROOT = os.path.join(BASE_DIR, "saves")
IMAGES_DIR = os.path.join(SAVE_ROOT, "images")
GIFS_DIR = os.path.join(SAVE_ROOT, "gif")
FRAMES_DIR = os.path.join(BASE_DIR, "static", "frames", "themes")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(GIFS_DIR, exist_ok=True)
os.makedirs(FRAMES_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Network / QR
# ---------------------------------------------------------------------------
SERVER_PORT = 5000
FORCE_HOST_IP = None

# ---------------------------------------------------------------------------
# Idle behaviour
# ---------------------------------------------------------------------------
IDLE_RESET_SECONDS = 90

# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
# Change this through the environment on a fresh installation if desired.
# The admin panel also supports changing the PIN after login.
ADMIN_PIN = os.environ.get("PHOTOBOOTH_ADMIN_PIN", "1234")
