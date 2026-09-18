(() => {
  "use strict";

  let pin = "";
  let settings = {};

  const $ = (id) => document.getElementById(id);

  function toast(message, error = false) {
    const el = $("toast");
    el.textContent = message;
    el.className = `toast${error ? " error" : ""}`;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 2600);
  }

  async function api(path, options = {}) {
    const res = await fetch(path, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed: ${res.status}`);
    return data;
  }

  // ---------------------------------------------------------------------
  // PIN gate
  // ---------------------------------------------------------------------
  window.pinDigit = function (digit) {
    if (pin.length >= 8) return;
    pin += digit;
    renderPinDots();
    $("pin-error").classList.add("hidden");
    if (pin.length >= 4) loginPin();
  };

  window.pinClear = function () {
    pin = pin.slice(0, -1);
    renderPinDots();
    $("pin-error").classList.add("hidden");
  };

  function renderPinDots() {
    document.querySelectorAll(".pin-dot").forEach((dot, i) => {
      dot.classList.toggle("filled", i < pin.length);
    });
  }

  async function loginPin() {
    try {
      await api("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin }),
      });
      $("pin-gate").classList.add("hidden");
      $("admin-app").classList.remove("hidden");
      await bootAdmin();
    } catch (err) {
      $("pin-error").textContent = err.message;
      $("pin-error").classList.remove("hidden");
      pin = "";
      renderPinDots();
    }
  }

  // ---------------------------------------------------------------------
  // Tabs
  // ---------------------------------------------------------------------
  window.showTab = function (name) {
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
    document.querySelectorAll(".nav-btn").forEach((btn) => btn.classList.remove("active"));
    const panel = $(`tab-${name}`);
    if (panel) panel.classList.add("active");
    const btn = document.querySelector(`.nav-btn[onclick="showTab('${name}')"]`);
    if (btn) btn.classList.add("active");

    if (name === "camera") startAdminFeed();
    else stopAdminFeed();
  };

  function startAdminFeed() {
    const img = $("admin-live-feed");
    if (!img.src || !img.src.includes("/video_feed")) img.src = `/video_feed?admin=${Date.now()}`;
  }

  function stopAdminFeed() {
    const img = $("admin-live-feed");
    if (img) img.src = "";
  }

  // ---------------------------------------------------------------------
  // Settings
  // ---------------------------------------------------------------------
  async function bootAdmin() {
    settings = await api("/api/admin/settings");
    applySettings();
    await scanCameras();
    await loadThemes();
    startAdminFeed();
  }

  function applySettings() {
    $("s-countdown").value = settings.countdown;
    $("s-gif-dur").value = Math.min(settings.gif_duration, settings.countdown);
    $("s-gif-scale").value = settings.gif_scale;
    $("s-gif-fps").value = settings.gif_fps;
    $(`rm-${settings.feed_mode || "fit"}`).checked = true;
    $("n-ip").value = settings.force_host_ip || "";
    $("n-port").value = settings.server_port || 5000;
    $("droidcam-ip").value = settings.droidcam_ip || "";
    $("droidcam-port").value = settings.droidcam_port || 4747;
    $("droidcam-resolution").value = settings.droidcam_resolution || "1280x720";
    const source = settings.camera_source || (settings.camera_index != null ? "local" : "local");
    $(`camera-source-${source}`).checked = true;
    updateCameraSourceUI();
    updateSliderLabel("countdown");
    updateSliderLabel("gif-dur");
    updateSliderLabel("gif-scale");
    updateSliderLabel("gif-fps");
    updateNetworkInfo();
  }

  window.updateSliderLabel = function (name) {
    const ids = {
      countdown: ["s-countdown", "lbl-countdown", "s"],
      "gif-dur": ["s-gif-dur", "lbl-gif-dur", "s"],
      "gif-scale": ["s-gif-scale", "lbl-gif-scale", "%"],
      "gif-fps": ["s-gif-fps", "lbl-gif-fps", " fps"],
    };
    const spec = ids[name];
    if (!spec) return;
    const value = Number($(spec[0]).value);
    $(spec[1]).textContent = `${value}${spec[2]}`;
    if (name === "gif-scale") {
      const baseW = settings.strip_width || 1652;
      const baseH = settings.strip_height || 4576;
      const w = Math.max(160, Math.floor(Math.round(baseW * value / 100) / 2) * 2);
      const h = Math.floor((baseH * (w / baseW)) / 2) * 2;
      $("gif-dim-hint").textContent = `Output: ${w} × ${h} px`;
    }
    if (name === "countdown") {
      const dur = $("s-gif-dur");
      if (Number(dur.value) > value) dur.value = value;
      $("s-gif-dur").max = value;
      updateSliderLabel("gif-dur");
    }
  };

  async function saveSettings(partial) {
    settings = { ...settings, ...partial };
    const data = await api("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(partial),
    });
    settings = { ...settings, ...data.settings };
    applySettings();
    toast(data.restart_required ? "Saved. Restart required for network changes." : "Saved.");
  }

  window.saveSessionSettings = async function () {
    try {
      await saveSettings({
        countdown: Number($("s-countdown").value),
        gif_duration: Math.min(Number($("s-gif-dur").value), Number($("s-countdown").value)),
      });
    } catch (err) { toast(err.message, true); }
  };

  window.saveOutputSettings = async function () {
    try {
      await saveSettings({ gif_scale: Number($("s-gif-scale").value), gif_fps: Number($("s-gif-fps").value) });
    } catch (err) { toast(err.message, true); }
  };

  window.saveDisplaySettings = async function () {
    try {
      const selected = document.querySelector('input[name="feed-mode"]:checked');
      await saveSettings({ feed_mode: selected ? selected.value : "fit" });
    } catch (err) { toast(err.message, true); }
  };

  function updateNetworkInfo() {
    const ip = settings.force_host_ip || "Automatic LAN IP";
    $("net-info").textContent = `QR base address: ${ip}:${settings.server_port || 5000}`;
  }

  window.saveNetworkSettings = async function () {
    try {
      await saveSettings({ force_host_ip: $("n-ip").value.trim(), server_port: Number($("n-port").value) });
    } catch (err) { toast(err.message, true); }
  };

  // ---------------------------------------------------------------------
  // Cameras
  // ---------------------------------------------------------------------
  function updateCameraSourceUI() {
    const source = document.querySelector('input[name="camera-source"]:checked')?.value || "local";
    $("local-camera-card").classList.toggle("hidden", source !== "local");
    $("droidcam-card").classList.toggle("hidden", source !== "droidcam");
  }

  document.querySelectorAll('input[name="camera-source"]').forEach((radio) => {
    radio.addEventListener("change", updateCameraSourceUI);
  });

  window.testDroidCam = async function () {
    const status = $("droidcam-status");
    status.textContent = "Testing DroidCam stream…";
    try {
      const data = await api("/api/cameras/droidcam/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ip: $("droidcam-ip").value.trim(),
          port: Number($("droidcam-port").value),
          resolution: $("droidcam-resolution").value
        })
      });
      status.textContent = `✓ Connected: ${data.url}`;
      toast("DroidCam connection works.");
    } catch (err) {
      status.textContent = `✕ ${err.message}`;
      toast(err.message, true);
    }
  };

  window.saveDroidCam = async function () {
    try {
      const data = await api("/api/cameras/droidcam", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ip: $("droidcam-ip").value.trim(),
          port: Number($("droidcam-port").value),
          resolution: $("droidcam-resolution").value
        })
      });
      settings.camera_source = "droidcam";
      $("camera-source-droidcam").checked = true;
      updateCameraSourceUI();
      $("droidcam-status").textContent = `✓ Active: ${data.url}`;
      toast("DroidCam is now the active camera.");
      startAdminFeed();
    } catch (err) {
      toast(err.message, true);
      $("droidcam-status").textContent = `✕ ${err.message}`;
    }
  };

  window.scanCameras = async function () {
    const list = $("camera-list");
    list.innerHTML = '<div class="loading-pill">Scanning camera devices…</div>';
    try {
      await api("/api/cameras");
      await refreshCameraStatus();
    } catch (err) {
      list.innerHTML = `<div class="camera-pill">${escapeHtml(err.message)}</div>`;
    }
  };

  async function refreshCameraStatus() {
    const list = $("camera-list");
    try {
      const data = await api("/api/cameras/status");
      list.innerHTML = "";
      if (data.state === "scanning") {
        list.innerHTML = '<div class="loading-pill">Scanning… this can take a little while for inactive V4L2 devices.</div>';
        setTimeout(refreshCameraStatus, 1000);
        return;
      }
      if (data.error) {
        list.innerHTML = `<div class="camera-pill">${escapeHtml(data.error)}</div>`;
      }
      if (!data.available || !data.available.length) {
        if (!data.error) list.innerHTML = '<div class="camera-pill">No working cameras detected</div>';
        return;
      }
      data.available.forEach((idx) => {
        const pill = document.createElement("button");
        pill.type = "button";
        pill.className = `camera-pill${idx === data.active ? " active" : ""}`;
        pill.textContent = `/dev/video${idx}${idx === data.active ? " • Active" : " • Use this"}`;
        pill.addEventListener("click", async () => {
          try {
            pill.disabled = true;
            pill.textContent = `Opening /dev/video${idx}…`;
            await api("/api/cameras/switch", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ index: idx })
            });
            toast(`Camera switched to /dev/video${idx}.`);
            await refreshCameraStatus();
            startAdminFeed();
          } catch (err) {
            toast(err.message, true);
            pill.disabled = false;
            await refreshCameraStatus();
          }
        });
        list.appendChild(pill);
      });
    } catch (err) {
      list.innerHTML = `<div class="camera-pill">${escapeHtml(err.message)}</div>`;
    }
  }

  // ---------------------------------------------------------------------
  // Frames
  // ---------------------------------------------------------------------
  async function loadThemes() {
    const grid = $("frames-admin-grid");
    grid.innerHTML = '<div class="loading-pill">Loading frames…</div>';
    try {
      const themes = await api("/api/themes");
      grid.innerHTML = "";
      themes.forEach((theme) => addThemeCard(theme, grid));
    } catch (err) { grid.innerHTML = `<div class="camera-pill">${escapeHtml(err.message)}</div>`; }
  }

  function addThemeCard(theme, grid) {
    const card = document.createElement("div");
    card.className = "admin-theme-card";
    card.dataset.themeId = theme.id;
    const thumb = document.createElement("div");
    thumb.className = "admin-theme-thumb";
    if (theme.thumbnail) {
      const img = document.createElement("img");
      img.src = theme.thumbnail;
      img.alt = `${theme.name} frame preview`;
      thumb.appendChild(img);
    }
    const name = document.createElement("div");
    name.className = "admin-theme-name";
    name.textContent = theme.name;
    const actions = document.createElement("div");
    actions.className = "frame-card-actions";
    if (theme.id === "classic") {
      const tag = document.createElement("span"); tag.className = "built-in-tag"; tag.textContent = "Built-in"; actions.appendChild(tag);
    } else {
      const btn = document.createElement("button"); btn.type = "button"; btn.className = "btn-secondary btn-small"; btn.textContent = "Delete";
      btn.addEventListener("click", () => deleteTheme(theme.id, card)); actions.appendChild(btn);
    }
    card.append(thumb, name, actions);
    grid.appendChild(card);
  }

  async function deleteTheme(id, card) {
    if (!confirm("Remove this frame from the kiosk?")) return;
    try {
      await api(`/api/themes/delete/${encodeURIComponent(id)}`, { method: "POST" });
      card.remove();
      toast("Frame removed.");
    } catch (err) { toast(err.message, true); }
  }

  window.uploadFrame = async function () {
    const file = $("custom-frame-file").files[0];
    const name = $("custom-frame-label").value.trim();
    const status = $("upload-status");
    if (!file) { status.textContent = "Choose a PNG or JPG first."; status.className = "status-msg error"; return; }
    const form = new FormData();
    form.append("name", name || file.name.replace(/\.[^.]+$/, ""));
    form.append("file", file);
    status.textContent = "Uploading…"; status.className = "status-msg";
    try {
      const data = await api("/api/themes/upload", { method: "POST", body: form });
      status.textContent = `“${data.theme.name}” was added.`; status.className = "status-msg ok";
      $("custom-frame-label").value = ""; $("custom-frame-file").value = "";
      await loadThemes();
      toast("Frame uploaded.");
    } catch (err) { status.textContent = err.message; status.className = "status-msg error"; }
  };

  // ---------------------------------------------------------------------
  // Security
  // ---------------------------------------------------------------------
  window.changePin = async function () {
    const status = $("pin-change-status");
    try {
      await api("/api/admin/pin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current: $("sec-current").value, new: $("sec-new").value, confirm: $("sec-confirm").value }),
      });
      status.textContent = "PIN changed successfully."; status.className = "status-msg ok mt-8";
      $("sec-current").value = $("sec-new").value = $("sec-confirm").value = "";
    } catch (err) { status.textContent = err.message; status.className = "status-msg error mt-8"; }
  };

  function escapeHtml(value) {
    const div = document.createElement("div"); div.textContent = value; return div.innerHTML;
  }
})();
