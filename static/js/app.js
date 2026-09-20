(() => {
  "use strict";

  const screens = {};
  document.querySelectorAll(".screen").forEach((el) => {
    screens[el.dataset.screen] = el;
  });

  function showScreen(name) {
    Object.values(screens).forEach((el) => el.classList.remove("active"));
    screens[name].classList.add("active");
  }

  function setLoading(visible, text) {
    const veil = document.getElementById("loading-veil");
    if (text) document.getElementById("loading-text").textContent = text;
    veil.classList.toggle("hidden", !visible);
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `Request failed: ${path}`);
    }
    return res.json();
  }

  // ---------------------------------------------------------------------
  // App state
  // ---------------------------------------------------------------------
  const state = {
    shotsPerStrip: 3,
    shotDuration: 5,
    photoAspect: 1,
    themeId: "classic",
    framePreviews: {},
    frameNames: {},
    currentShot: 0,
    filterPreviews: {},
    selectedFilter: "Original",
    idleTimer: null,
  };

  const els = {
    btnStart: document.getElementById("btn-start"),
    frameList: document.getElementById("frame-list"),
    framePreviewImg: document.getElementById("frame-preview-img"),
    btnFrameNext: document.getElementById("btn-frame-next"),
    liveFeed: document.getElementById("live-feed"),
    countdownNum: document.getElementById("countdown-num"),
    flashEl: document.getElementById("flash-el"),
    shotProgress: document.getElementById("shot-progress"),
    captureHeading: document.getElementById("capture-heading"),
    shotRail: document.getElementById("shot-rail"),
    btnTakeShot: document.getElementById("btn-take-shot"),
    stripPreviewImg: document.getElementById("strip-preview-img"),
    filterList: document.getElementById("filter-list"),
    btnReviewRetake: document.getElementById("btn-review-retake"),
    btnReviewConfirm: document.getElementById("btn-review-confirm"),
    finalStripImg: document.getElementById("final-strip-img"),
    qrJpg: document.getElementById("qr-jpg"),
    qrVideo: document.getElementById("qr-video"),
    btnFinalRestart: document.getElementById("btn-final-restart"),
  };

  // ---------------------------------------------------------------------
  // Idle -> Theme
  // ---------------------------------------------------------------------
  els.btnStart.addEventListener("click", async () => {
    setLoading(true, "Getting the booth ready…");
    try {
      const startData = await api("/api/session/start", { method: "POST" });
      state.shotsPerStrip = startData.shots_per_strip;
      state.shotDuration = startData.shot_duration;
      state.photoAspect = startData.photo_aspect || 1;
      state.themeId = "classic";
      startCaptureFlow();
    } catch (err) {
      alert(err.message);
    } finally {
      setLoading(false);
    }
  });

  function renderFrameList() {
    const themes = Object.keys(state.framePreviews || {});
    if (!themes.length) return;

    els.frameList.innerHTML = "";
    themes.forEach((themeId) => {
      const name = state.frameNames[themeId] || themeId;
      const row = document.createElement("button");
      row.className = "filter-row" + (themeId === state.themeId ? " selected" : "");
      row.innerHTML = `<img src="${state.framePreviews[themeId]}" alt="${name} frame preview"><span>${name}</span>`;
      row.addEventListener("click", async () => {
        state.themeId = themeId;
        els.frameList.querySelectorAll(".filter-row").forEach((r) => r.classList.remove("selected"));
        row.classList.add("selected");
        els.framePreviewImg.src = state.framePreviews[themeId];
        await api("/api/session/theme", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ theme_id: state.themeId }),
        });
      });
      els.frameList.appendChild(row);
    });

    if (!state.themeId || !state.framePreviews[state.themeId]) {
      state.themeId = themes[0];
    }
    els.framePreviewImg.src = state.framePreviews[state.themeId];
  }

  els.btnFrameNext.addEventListener("click", async () => {
    els.btnFrameNext.disabled = true;
    setLoading(true, "Processing your frame…");
    try {
      const data = await api("/api/session/filter_preview", { method: "POST" });
      state.filterPreviews = data.previews;
      state.selectedFilter = "Original";
      renderFilterList();
      els.stripPreviewImg.src = state.filterPreviews["Original"];
      showScreen("review");
    } catch (err) {
      alert(err.message);
      els.btnFrameNext.disabled = false;
    } finally {
      setLoading(false);
    }
  });

  // ---------------------------------------------------------------------
  // Capture flow
  // ---------------------------------------------------------------------
  function startCaptureFlow() {
    state.currentShot = 0;
    els.shotRail.querySelectorAll(".shot-slot").forEach((s) => {
      s.classList.remove("filled");
      s.style.backgroundImage = "";
    });
    els.liveFeed.src = "/video_feed?ts=" + Date.now();
    const viewfinder = document.querySelector("#screen-capture .viewfinder");
    if (viewfinder) viewfinder.style.aspectRatio = `${state.photoAspect || 1}`;
    updateCaptureHeading();
    els.btnTakeShot.disabled = false;
    els.btnTakeShot.textContent = "Start countdown";
    showScreen("capture");
    requestAnimationFrame(syncCaptureLayout);
  }

  function syncCaptureLayout() {
    const viewfinder = document.querySelector("#screen-capture .viewfinder");
    const rail = els.shotRail;
    if (!viewfinder || !rail) return;

    const width = Math.round(viewfinder.getBoundingClientRect().width);
    if (!width) return;
    const aspect = state.photoAspect || 1;
    const height = Math.round(width / aspect);
    viewfinder.style.height = `${height}px`;
    const styles = getComputedStyle(rail);
    const gap = parseFloat(styles.rowGap || styles.gap) || 0;
    const slotWidth = Math.max(1, Math.floor(width / 3));
    const slotHeight = Math.max(1, Math.floor((height - gap * 2) / 3));
    rail.style.width = `${slotWidth}px`;
    rail.style.height = `${height}px`;
    rail.querySelectorAll(".shot-slot").forEach((slot) => {
      slot.style.width = `${slotWidth}px`;
      slot.style.height = `${slotHeight}px`;
    });
  }

  if (window.ResizeObserver) {
    const captureViewfinder = document.querySelector("#screen-capture .viewfinder");
    if (captureViewfinder) new ResizeObserver(syncCaptureLayout).observe(captureViewfinder);
  }
  window.addEventListener("resize", syncCaptureLayout);

  function updateCaptureHeading() {
    els.shotProgress.textContent = `Shot ${state.currentShot + 1} of ${state.shotsPerStrip}`;
    const prompts = ["Strike a pose", "One more time", "Last one, make it count"];
    els.captureHeading.textContent = prompts[state.currentShot] || "Strike a pose";
  }

  els.btnTakeShot.addEventListener("click", () => runCountdownAndCapture());

  function runCountdownAndCapture() {
    els.btnTakeShot.disabled = true;
    els.btnTakeShot.textContent = "Hold still…";

    const duration = Math.max(1, Math.round(state.shotDuration));
    let remaining = duration;
    els.countdownNum.textContent = remaining;
    els.countdownNum.classList.add("show");

    // Fire the capture request the instant the countdown starts so the
    // server-side GIF clip recording window lines up with what's on screen.
    const capturePromise = api(`/api/session/capture/${state.currentShot}`, { method: "POST" });

    const tick = setInterval(() => {
      remaining -= 1;
      if (remaining > 0) {
        els.countdownNum.textContent = remaining;
      } else {
        clearInterval(tick);
        els.countdownNum.classList.remove("show");
      }
    }, 1000);

    capturePromise
      .then((data) => {
        clearInterval(tick);
        els.countdownNum.classList.remove("show");
        fireFlash();
        fillShotSlot(state.currentShot, data.preview);
        state.currentShot += 1;

        if (state.currentShot >= state.shotsPerStrip) {
          setTimeout(goToReview, 500);
        } else {
          updateCaptureHeading();
          els.btnTakeShot.disabled = false;
          els.btnTakeShot.textContent = "Start countdown";
        }
      })
      .catch((err) => {
        clearInterval(tick);
        els.countdownNum.classList.remove("show");
        alert(err.message);
        els.btnTakeShot.disabled = false;
        els.btnTakeShot.textContent = "Try again";
      });
  }

  function fireFlash() {
    els.flashEl.classList.remove("fire");
    // force reflow so the animation can retrigger
    void els.flashEl.offsetWidth;
    els.flashEl.classList.add("fire");
  }

  function fillShotSlot(index, dataUri) {
    const slot = els.shotRail.querySelector(`[data-slot="${index}"]`);
    if (slot) {
      slot.style.backgroundImage = `url('${dataUri}')`;
      slot.classList.add("filled");
    }
  }

  // ---------------------------------------------------------------------
  // Review / filters
  // ---------------------------------------------------------------------
  async function goToReview() {
    setLoading(true, "Building your frame choices…");
    try {
      const [themeData, frameData] = await Promise.all([
        api("/api/themes"),
        api("/api/session/frame_previews", { method: "POST" }),
      ]);
      if (!Object.keys(frameData.previews || {}).length) {
        throw new Error("No frame options available");
      }

      state.frameNames = {};
      themeData.forEach((theme) => {
        state.frameNames[theme.id] = theme.name;
      });

      state.framePreviews = frameData.previews;
      state.themeId = Object.keys(state.framePreviews)[0];
      renderFrameList();
      showScreen("frame");
    } catch (err) {
      alert(err.message);
      showScreen("capture");
    } finally {
      setLoading(false);
    }
  }

  function renderFilterList() {
    els.filterList.innerHTML = "";
    Object.keys(state.filterPreviews).forEach((name) => {
      const row = document.createElement("button");
      row.className = "filter-row" + (name === state.selectedFilter ? " selected" : "");
      row.innerHTML = `<img src="${state.filterPreviews[name]}" alt="${name} filter preview"><span>${name}</span>`;
      row.addEventListener("click", async () => {
        state.selectedFilter = name;
        els.filterList.querySelectorAll(".filter-row").forEach((r) => r.classList.remove("selected"));
        row.classList.add("selected");
        els.stripPreviewImg.src = state.filterPreviews[name];
        await api("/api/session/set_filter", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filter: name }),
        });
      });
      els.filterList.appendChild(row);
    });
  }

  els.btnReviewRetake.addEventListener("click", async () => {
    await api("/api/session/reset", { method: "POST" });
    showScreen("idle");
  });

  els.btnReviewConfirm.addEventListener("click", async () => {
    setLoading(true, "Printing your memories…");
    try {
      const data = await api("/api/session/finalize", { method: "POST" });
      els.finalStripImg.src = data.strip_preview;
      els.qrJpg.src = data.jpg_qr;
      els.qrVideo.src = data.video_qr;
      showScreen("final");
      armIdleReset();
    } catch (err) {
      alert(err.message);
    } finally {
      setLoading(false);
    }
  });

  // ---------------------------------------------------------------------
  // Final screen
  // ---------------------------------------------------------------------
  els.btnFinalRestart.addEventListener("click", () => returnToIdle());

  function armIdleReset() {
    if (state.idleTimer) clearTimeout(state.idleTimer);
    state.idleTimer = setTimeout(returnToIdle, 90 * 1000);
  }

  async function returnToIdle() {
    if (state.idleTimer) clearTimeout(state.idleTimer);
    els.liveFeed.src = "";
    try {
      await api("/api/session/reset", { method: "POST" });
    } catch (_) { /* ignore */ }
    showScreen("idle");
  }

  // ---------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------
  showScreen("idle");
})();
