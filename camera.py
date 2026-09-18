"""Camera manager supporting local V4L2/OBS cameras and DroidCam IP streams."""
import glob
import os
import threading
import time
import urllib.parse

import cv2

import config


def _capture_backend():
    """Return the OpenCV capture backend appropriate for this operating system."""
    if os.name == "nt":
        return cv2.CAP_DSHOW
    if hasattr(cv2, "CAP_V4L2"):
        return cv2.CAP_V4L2
    return cv2.CAP_ANY


def _open_capture(source):
    return cv2.VideoCapture(source, _capture_backend())


def list_candidate_devices():
    paths = sorted(glob.glob("/dev/video*"))
    indices = []
    for p in paths:
        try:
            indices.append(int(p.replace("/dev/video", "")))
        except ValueError:
            pass
    return sorted(set(indices)) if indices else list(range(config.CAMERA_MAX_INDEX_SCAN))


def probe_camera(index, timeout_frames=5):
    cap = _open_capture(index)
    if not cap.isOpened():
        cap.release()
        return False
    try:
        for _ in range(timeout_frames):
            ret, frame = cap.read()
            if ret and frame is not None and getattr(frame, "size", 0):
                return True
            time.sleep(0.05)
    finally:
        cap.release()
    return False


def detect_working_cameras():
    return [idx for idx in list_candidate_devices() if probe_camera(idx)]


def droidcam_url(ip, port, resolution="1280x720", force=False):
    ip = str(ip or "").strip()
    port = int(port)
    if not ip:
        raise ValueError("DroidCam IP address is required")
    if not (1 <= port <= 65535):
        raise ValueError("DroidCam port must be between 1 and 65535")
    # Accept hostnames as well as IPv4 addresses, but reject URL/path injection.
    if any(c in ip for c in "/\\?:#@"):
        raise ValueError("Enter only the DroidCam IP address or hostname")
    if resolution not in ("640x480", "1280x720", "1920x1080"):
        resolution = "1280x720"
    path = "/video/force/" if force else "/video/"
    return f"http://{ip}:{port}{path}{resolution}"


def probe_droidcam(ip, port, resolution="1280x720"):
    """Open the DroidCam HTTP stream and verify that a real frame arrives."""
    url = droidcam_url(ip, port, resolution)
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        cap.release()
        return False, url
    try:
        for _ in range(12):
            ret, frame = cap.read()
            if ret and frame is not None and getattr(frame, "size", 0):
                return True, url
            time.sleep(0.1)
    finally:
        cap.release()
    return False, url


class CameraManager:
    def __init__(self, index=None):
        self._lock = threading.Lock()
        self._frame = None
        self._cap = None
        self._running = False
        self._thread = None
        self.index = index
        self.source_type = "local" if index is not None else None
        self.droidcam = {"ip": "", "port": 4747, "resolution": "1280x720"}
        self.available_indices = []
        self.scan_state = "idle"
        self.scan_error = None
        self._scan_thread = None

    def start(self):
        if self.source_type == "droidcam" and self.droidcam.get("ip"):
            try:
                self._open_droidcam(self.droidcam["ip"], self.droidcam["port"], self.droidcam["resolution"])
                return "droidcam"
            except Exception as exc:
                self.scan_error = str(exc)
                # Keep the booth usable: fall back to local camera detection.
                self.source_type = None
        if self.index is not None:
            self._open_local(self.index)
            return self.index
        self.rescan(background=True)
        return None

    def _open_local(self, chosen):
        self.stop()
        cap = _open_capture(int(chosen))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_REQUEST_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_REQUEST_HEIGHT)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Failed to open camera index {chosen}")
        self._cap = cap
        self.index = int(chosen)
        self.source_type = "local"
        self._start_loop()
        return self.index

    def _open_droidcam(self, ip, port, resolution="1280x720"):
        url = droidcam_url(ip, port, resolution)
        self.stop()
        cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Could not open DroidCam at {url}")
        # Verify that this is a live stream before replacing the active camera.
        good = False
        for _ in range(12):
            ok, frame = cap.read()
            if ok and frame is not None and getattr(frame, "size", 0):
                with self._lock:
                    self._frame = frame
                good = True
                break
            time.sleep(0.1)
        if not good:
            cap.release()
            raise RuntimeError(f"DroidCam connected at {url}, but no video frames were received")
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        self._cap = cap
        self.index = None
        self.source_type = "droidcam"
        self.droidcam = {"ip": str(ip).strip(), "port": int(port), "resolution": resolution}
        self._start_loop()
        return url

    def _start_loop(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def switch(self, new_index):
        return self._open_local(int(new_index))

    def switch_droidcam(self, ip, port, resolution="1280x720"):
        return self._open_droidcam(ip, port, resolution)

    def rescan(self, background=True):
        candidates = list_candidate_devices()
        self.available_indices = candidates
        if not background:
            self._scan_worker()
            return self.available_indices
        if self._scan_thread and self._scan_thread.is_alive():
            return candidates
        self.scan_state = "scanning"
        self.scan_error = None
        self._scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._scan_thread.start()
        return candidates

    def _scan_worker(self):
        try:
            self.scan_state = "scanning"
            working = []
            for idx in list_candidate_devices():
                if probe_camera(idx):
                    working.append(idx)
            self.available_indices = working
            self.scan_state = "ready"
            # Only auto-select a local camera when nothing is configured.
            if self.source_type is None and self.index is None and working:
                try:
                    self._open_local(working[0])
                except Exception as exc:
                    self.scan_error = str(exc)
        except Exception as exc:
            self.scan_state = "error"
            self.scan_error = str(exc)

    def _loop(self):
        while self._running:
            if self._cap is None:
                break
            ok, frame = self._cap.read()
            if ok and frame is not None:
                with self._lock:
                    self._frame = frame
            else:
                time.sleep(0.01)

    def get_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def status(self):
        return {
            "active": self.index,
            "source_type": self.source_type,
            "droidcam": dict(self.droidcam),
            "available": self.available_indices,
            "state": self.scan_state,
            "error": self.scan_error,
        }

    def stop(self):
        self._running = False
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None


camera_manager = CameraManager(index=config.CAMERA_INDEX)
