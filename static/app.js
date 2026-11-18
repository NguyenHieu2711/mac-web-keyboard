(() => {
  "use strict";

  const wsDots = Array.from(document.querySelectorAll(".js-ws-dot"));
  const utilIcons = Array.from(document.querySelectorAll(".js-util-icon"));
  const layoutLabels = Array.from(document.querySelectorAll(".js-layout-label"));
  const vnBtns = Array.from(document.querySelectorAll(".js-vn-btn"));
  const vnLabels = Array.from(document.querySelectorAll(".js-vn-label"));
  const symPopup = document.getElementById("sym-floating-popup");
  const btnCloseSymPopup = document.getElementById("btn-close-sym-popup");
  const modeMenus = Array.from(document.querySelectorAll(".js-mode-menu"));
  const modeItems = Array.from(document.querySelectorAll(".mode-dropdown-item[data-select-layout]"));
  const allKeys = Array.from(document.querySelectorAll(".key, .mode-dropdown-anchor"));
  const hasAndroidBridge =
    typeof window.AndroidBridge !== "undefined" && window.AndroidBridge !== null;

  if (hasAndroidBridge) {
    utilIcons.forEach((el) => {
      el.textContent = "⚙";
    });
  }

  for (const btn of allKeys) {
    if (btn.dataset.flex) {
      const flexVal = parseFloat(btn.dataset.flex || "1");
      btn.style.setProperty("--u", String(flexVal));
    }
  }

  // ============================================================================
  // 1. QUẢN LÝ 3 CHẾ ĐỘ QUA DROPDOWN DỌC NHỎ GỌN & CỐ ĐỊNH CHIỀU MÀN HÌNH
  // ============================================================================
  const STORAGE_HOST_KEY = "mac_kb_server_host";
  const STORAGE_LAYOUT_KEY = "mac_kb_layout_mode";
  const STORAGE_VN_KEY = "mac_kb_vn_mode";
  const STORAGE_LENS_SCALE_KEY = "mac_kb_lens_scale";
  const STORAGE_LENS_ON_KEY = "mac_kb_lens_enabled";
  const STORAGE_PAD_VIEW_KEY = "mac_kb_pad_view_mode";
  const STORAGE_PAD_SPLIT_KEY = "mac_kb_pad_split_mode";
  const STORAGE_TP_SPEED_KEY = "mac_kb_trackpad_speed";

  const padLensCanvas = document.getElementById("pad-lens-canvas");
  const kbLensCanvas = document.getElementById("kb-lens-canvas");
  const kbRibbonLens = document.getElementById("kb-ribbon-lens");
  const padSplitBtns = Array.from(document.querySelectorAll(".js-pad-split-btn"));
  const padSplitLabels = Array.from(document.querySelectorAll(".js-pad-split-label"));
  const webSettingsModal = document.getElementById("web-settings-modal");
  const btnCloseWebSettings = document.getElementById("btn-close-web-settings");
  const webTpSpeedRange = document.getElementById("web-tp-speed-range");
  const webTpSpeedVal = document.getElementById("web-tp-speed-val");
  const btnWebFullscreen = document.getElementById("btn-web-fullscreen");
  const fovLabels = Array.from(document.querySelectorAll(".js-fov-label"));
  const fovOutBtns = Array.from(document.querySelectorAll(".js-fov-out"));
  const fovInBtns = Array.from(document.querySelectorAll(".js-fov-in"));
  const lensToggleBtns = Array.from(document.querySelectorAll(".js-lens-toggle"));
  const padViewBtns = Array.from(document.querySelectorAll(".js-pad-view-btn"));
  const clearTextBtns = Array.from(document.querySelectorAll(".js-clear-text"));
  const simpleWraps = Array.from(document.querySelectorAll(".js-simple-wrap"));
  const simplePlaceholders = Array.from(document.querySelectorAll(".js-simple-placeholder"));
  const simplePadTextEl = document.querySelector(".simple-text-pad .js-simple-text");
  const simpleRibbonTextEl = document.querySelector(".simple-text-ribbon .js-simple-text");
  const simpleBadges = Array.from(document.querySelectorAll(".js-simple-badge"));
  const screenPermBars = Array.from(document.querySelectorAll(".js-screen-perm-bar"));
  const openScreenPermBtns = Array.from(document.querySelectorAll(".js-open-screen-perm"));
  const respawnServerBtns = Array.from(document.querySelectorAll(".js-respawn-server"));

  // Mặc định 1.22 (~0.8x): thu nhỏ nội dung vừa phải để nhìn rộng bao quát quanh trung tâm con chuột
  let lensFovScale = 1.22;
  let lensEnabled = true;
  let padViewMode = "lens";
  let screenRecordingOk = true;
  let trackpadSpeed = 1.6;
  let simpleTextBuffer = "";
  let badgeHideTimer = null;

  try {
    const savedTpSpeed = parseFloat(localStorage.getItem(STORAGE_TP_SPEED_KEY) || "1.6");
    if (!Number.isNaN(savedTpSpeed) && savedTpSpeed >= 0.5 && savedTpSpeed <= 4.0) {
      trackpadSpeed = savedTpSpeed;
    }
    if (hasAndroidBridge && typeof window.AndroidBridge.getTrackpadSpeed === "function") {
      const nativeSpeed = parseFloat(window.AndroidBridge.getTrackpadSpeed());
      if (!Number.isNaN(nativeSpeed) && nativeSpeed >= 0.5 && nativeSpeed <= 4.0) {
        trackpadSpeed = nativeSpeed;
      }
    }
  } catch {
    // ignore
  }

  function applyTrackpadSpeedValue(val, syncNative = false) {
    const parsed = parseFloat(val);
    if (Number.isNaN(parsed)) return;
    trackpadSpeed = Math.max(0.5, Math.min(4.0, Math.round(parsed * 10) / 10));
    try {
      localStorage.setItem(STORAGE_TP_SPEED_KEY, String(trackpadSpeed));
    } catch {
      // ignore
    }
    if (webTpSpeedRange) webTpSpeedRange.value = String(trackpadSpeed);
    if (webTpSpeedVal) webTpSpeedVal.textContent = `${trackpadSpeed.toFixed(1)}x`;
    if (syncNative && hasAndroidBridge && typeof window.AndroidBridge.setTrackpadSpeed === "function") {
      try {
        window.AndroidBridge.setTrackpadSpeed(trackpadSpeed);
      } catch {
        // ignore
      }
    }
  }

  window.__setTrackpadSpeed = (val) => {
    applyTrackpadSpeedValue(val, false);
  };
  applyTrackpadSpeedValue(trackpadSpeed, false);

  try {
    const savedScale = parseFloat(localStorage.getItem(STORAGE_LENS_SCALE_KEY) || "1.22");
    if (!Number.isNaN(savedScale) && savedScale >= 0.55 && savedScale <= 1.85) {
      lensFovScale = savedScale;
    }
    const savedOn = localStorage.getItem(STORAGE_LENS_ON_KEY);
    if (savedOn === "0") {
      lensEnabled = false;
    }
    const savedPadView = localStorage.getItem(STORAGE_PAD_VIEW_KEY);
    if (savedPadView === "lens" || savedPadView === "text") {
      padViewMode = savedPadView;
    }
  } catch {
    // ignore
  }

  function renderSimpleText(text, badge = "") {
    simpleTextBuffer = String(text || "");
    const hasText = simpleTextBuffer.length > 0;
    if (simplePadTextEl) {
      simplePadTextEl.textContent = simpleTextBuffer;
    }
    if (simpleRibbonTextEl) {
      simpleRibbonTextEl.textContent = simpleTextBuffer.replace(/\n/g, "  ↵  ").slice(-62);
    }

    if (badge) {
      if (badgeHideTimer) clearTimeout(badgeHideTimer);
      simpleBadges.forEach((el) => {
        el.textContent = badge;
        el.classList.remove("is-hidden");
      });
      badgeHideTimer = setTimeout(() => {
        badgeHideTimer = null;
        simpleBadges.forEach((el) => el.classList.add("is-hidden"));
        const stillHasText = simpleTextBuffer.length > 0;
        simpleWraps.forEach((el) => el.classList.toggle("is-hidden", !stillHasText));
        simplePlaceholders.forEach((el) => el.classList.toggle("is-hidden", stillHasText));
      }, 1100);
    }

    const activeBadgeVisible = Boolean(badge) || Boolean(badgeHideTimer);
    const showWrap = hasText || activeBadgeVisible;
    simpleWraps.forEach((el) => el.classList.toggle("is-hidden", !showWrap));
    simplePlaceholders.forEach((el) => el.classList.toggle("is-hidden", showWrap));
    clearTextBtns.forEach((el) => el.classList.toggle("is-hidden", !hasText));
  }

  const APPLE_SVG =
    '<svg class="apple-ico" viewBox="0 0 384 512" aria-hidden="true"><path fill="currentColor" d="M318.7 268.7c-.2-36.7 16.4-64.4 50-84.8-18.8-26.9-47.2-41.7-84.7-44.6-35.5-2.8-74.3 20.7-88.5 20.7-15 0-49.4-19.7-76.4-19.7C63.3 141.2 4 184.8 4 273.5q0 39.3 14.4 81.2c12.8 36.7 59 126.7 107.2 125.2 25.2-.6 43-17.9 75.8-17.9 31.8 0 48.3 17.9 76.4 17.9 48.6-.7 90.4-82.5 102.6-119.3-65.2-30.7-61.7-90-61.7-91.9zm-56.6-164.2c27.3-32.4 24.8-61.9 24-72.5-24.1 1.4-52 16.4-67.9 34.9-17.5 19.8-27.8 44.3-25.6 71.9 26.1 2 49.9-11.4 69.5-34.3z"/></svg>';

  const LAYOUT_LABELS = {
    pad: "📱 Windows dọc",
    win: "🖥 Win",
    mac: `${APPLE_SVG} Mac`,
  };

  let kbLayout = "pad";
  let padSplitHorizontal = false;
  let vnEnabled = true;
  let symLayer = false;
  let symShifted = false;
  let modeMenuOpen = false;

  try {
    const savedLayout = localStorage.getItem(STORAGE_LAYOUT_KEY);
    if (savedLayout === "win" || savedLayout === "mac" || savedLayout === "pad") {
      kbLayout = savedLayout;
    }
    const savedSplit = localStorage.getItem(STORAGE_PAD_SPLIT_KEY);
    if (savedSplit === "horizontal" || savedSplit === "1") {
      padSplitHorizontal = true;
    }
    const savedVn = localStorage.getItem(STORAGE_VN_KEY);
    if (savedVn === "0" || savedVn === "false") {
      vnEnabled = false;
    }
  } catch {
    // ignore
  }

  function applyOrientationForLayout() {
    try {
      const wantPortrait = kbLayout === "pad" && !padSplitHorizontal;
      const target = wantPortrait ? "portrait" : "landscape";
      if (hasAndroidBridge && typeof window.AndroidBridge.setOrientation === "function") {
        window.AndroidBridge.setOrientation(target);
      }
      if (screen.orientation && typeof screen.orientation.lock === "function") {
        screen.orientation.lock(target).catch(() => {});
      }
    } catch {
      // ignore
    }
  }

  function syncModeUI() {
    document.body.dataset.layout = kbLayout;
    document.body.dataset.padSplit = padSplitHorizontal ? "horizontal" : "vertical";
    const lbl =
      kbLayout === "pad" && padSplitHorizontal
        ? "📱 Win dọc"
        : LAYOUT_LABELS[kbLayout] || "📱 Win dọc";
    layoutLabels.forEach((el) => {
      el.innerHTML = lbl;
    });
    padSplitBtns.forEach((el) => {
      el.classList.toggle("is-active", padSplitHorizontal);
    });
    padSplitLabels.forEach((el) => {
      el.textContent = padSplitHorizontal ? "↔ Ngang" : "↕ Dọc";
    });
    vnBtns.forEach((el) => {
      el.classList.toggle("is-active", vnEnabled);
    });
    vnLabels.forEach((el) => {
      el.textContent = vnEnabled ? "V" : "E";
    });
    modeItems.forEach((item) => {
      item.classList.toggle("is-selected", item.dataset.selectLayout === kbLayout);
    });
    modeMenus.forEach((menu) => {
      menu.classList.toggle("is-hidden", !modeMenuOpen);
    });
    if (symPopup) {
      symPopup.classList.toggle("is-hidden", !symLayer);
      symPopup.classList.toggle("is-sym-shifted", symShifted);
    }
    applyOrientationForLayout();
  }

  function syncLensControlsUI() {
    document.body.dataset.padView = padViewMode;
    document.body.classList.toggle("is-lens-off", !lensEnabled);
    padViewBtns.forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.padView === padViewMode);
    });
    const showPermWarning = !screenRecordingOk && padViewMode === "lens" && lensEnabled;
    screenPermBars.forEach((bar) => {
      bar.classList.toggle("is-hidden", !showPermWarning);
    });
    const zoomRatio = (1 / lensFovScale).toFixed(1) + "x";
    fovLabels.forEach((el) => {
      el.textContent = zoomRatio;
    });
  }

  function pushLensConfigToServer() {
    const activeSurface =
      kbLayout === "pad"
        ? document.getElementById("trackpad-surface")
        : kbRibbonLens;
    let aspect = kbLayout === "pad" ? 1.85 : 11.0;
    if (activeSurface) {
      const r = activeSurface.getBoundingClientRect();
      if (r.width > 40 && r.height > 20) {
        aspect = +(r.width / r.height).toFixed(2);
      }
    }
    sendPayload({
      type: "lens_config",
      enabled: lensEnabled && padViewMode === "lens",
      aspect,
      scale: +lensFovScale.toFixed(2),
      mode: kbLayout === "pad" ? "portrait" : "landscape",
    });
  }

  function pushConfigToServer() {
    sendPayload({
      type: "config",
      layout: kbLayout,
      vn: vnEnabled,
    });
    setTimeout(pushLensConfigToServer, 60);
  }

  function toggleModeMenu() {
    modeMenuOpen = !modeMenuOpen;
    if (modeMenuOpen) {
      symLayer = false;
      symShifted = false;
    }
    syncModeUI();
  }

  function closeModeMenu() {
    if (!modeMenuOpen) return;
    modeMenuOpen = false;
    syncModeUI();
  }

  function selectKeyboardLayout(newLayout) {
    if (!LAYOUT_LABELS[newLayout]) return;
    releaseAllActiveTouches();
    kbLayout = newLayout;
    modeMenuOpen = false;
    symLayer = false;
    symShifted = false;
    try {
      localStorage.setItem(STORAGE_LAYOUT_KEY, kbLayout);
    } catch {
      // ignore
    }
    syncModeUI();
    pushConfigToServer();
  }

  modeItems.forEach((item) => {
    const handlePick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      triggerHaptic(10);
      selectKeyboardLayout(item.dataset.selectLayout);
    };
    item.addEventListener("touchstart", handlePick, { passive: false });
    item.addEventListener("mousedown", handlePick);
  });

  function toggleVietnameseMode() {
    vnEnabled = !vnEnabled;
    try {
      localStorage.setItem(STORAGE_VN_KEY, vnEnabled ? "1" : "0");
    } catch {
      // ignore
    }
    syncModeUI();
    pushConfigToServer();
  }

  function togglePadSplitMode() {
    releaseAllActiveTouches();
    padSplitHorizontal = !padSplitHorizontal;
    modeMenuOpen = false;
    symLayer = false;
    symShifted = false;
    try {
      localStorage.setItem(
        STORAGE_PAD_SPLIT_KEY,
        padSplitHorizontal ? "horizontal" : "vertical"
      );
    } catch {
      // ignore
    }
    syncModeUI();
    setTimeout(pushLensConfigToServer, 160);
  }

  function toggleSymbolLayer() {
    symLayer = !symLayer;
    if (symLayer) {
      modeMenuOpen = false;
      symShifted = false;
    }
    syncModeUI();
  }

  function closeSymbolPopup() {
    if (!symLayer) return;
    symLayer = false;
    symShifted = false;
    syncModeUI();
  }

  if (btnCloseSymPopup) {
    btnCloseSymPopup.addEventListener("click", (e) => {
      e.stopPropagation();
      closeSymbolPopup();
    });
  }

  if (symPopup) {
    const handleSymSelect = (e) => {
      const shiftBtn = e.target.closest(".js-sym-shift");
      if (shiftBtn) {
        e.preventDefault();
        e.stopPropagation();
        triggerHaptic(10);
        symShifted = !symShifted;
        syncModeUI();
        return;
      }

      const item = e.target.closest(".sym-item[data-sym-key]");
      if (item) {
        e.preventDefault();
        e.stopPropagation();
        triggerHaptic(10);
        let symKey = item.dataset.symKey || "";
        const symShiftKey = item.dataset.symShift || "";

        if (symShiftKey) {
          if (symShifted || isModActive("shift")) {
            symKey = symShiftKey;
          } else {
            const touchObj =
              e.changedTouches && e.changedTouches.length > 0
                ? e.changedTouches[0]
                : e;
            const clientY =
              typeof touchObj.clientY === "number" ? touchObj.clientY : null;
            if (clientY !== null) {
              const rect = item.getBoundingClientRect();
              if (rect.height > 0 && clientY < rect.top + rect.height * 0.48) {
                symKey = symShiftKey;
              }
            }
          }
        }

        if (symKey) {
          markModifiersUsedInChord();
          const activeMods = MOD_NAMES.filter((m) => isModActive(m));
          sendPayload(
            activeMods.length > 0
              ? { type: "press", key: symKey, mods: activeMods }
              : { type: "press", key: symKey }
          );
          applyOfflinePreviewKey(symKey);
          consumeStickyModifiersAfterKey();
        }
        closeSymbolPopup();
        return;
      }
      if (e.target.closest(".sym-blank")) {
        e.preventDefault();
        e.stopPropagation();
        closeSymbolPopup();
      }
    };
    symPopup.addEventListener("touchstart", handleSymSelect, { passive: false });
    symPopup.addEventListener("mousedown", handleSymSelect);
  }

  syncModeUI();

  // ============================================================================
  // 2. QUẢN LÝ KẾT NỐI WEBSOCKET TỰ ĐỘNG RECONNECT ĐỘ TRỄ 0MS
  // ============================================================================
  let ws = null;
  let reconnectDelay = 400;
  let reconnectTimer = null;
  let pingInterval = null;
  let hostCycleIndex = 0;

  function normalizeEndpoint(item) {
    let clean = String(item || "").trim();
    if (!clean) return "";
    clean = clean.replace(/^https?:\/\//i, "").replace(/^wss?:\/\//i, "");
    clean = clean.replace(/\/.*$/, "");
    if (!clean) return "";
    if (!clean.includes(":")) {
      clean = `${clean}:5050`;
    }
    return clean;
  }

  function resolveCandidateHosts() {
    let raw = "";
    if (hasAndroidBridge && typeof window.AndroidBridge.getServerHost === "function") {
      try {
        raw = String(window.AndroidBridge.getServerHost() || "").trim();
      } catch {
        raw = "";
      }
    }
    if (!raw) {
      try {
        raw = String(localStorage.getItem(STORAGE_HOST_KEY) || "").trim();
      } catch {
        raw = "";
      }
    }
    if (raw) {
      const list = raw
        .split(",")
        .map(normalizeEndpoint)
        .filter(Boolean);
      if (list.length > 0) return list;
    }

    const host = window.location.host || "";
    if (
      host &&
      host !== "appassets.androidplatform.net" &&
      window.location.protocol !== "file:"
    ) {
      return [host];
    }
    return [];
  }

  function setOnlineUI(online) {
    wsDots.forEach((dot) => {
      dot.classList.toggle("is-online", online);
      dot.classList.toggle("is-offline", !online);
    });
    if (!online) {
      const tp = document.getElementById("trackpad-surface");
      if (tp) tp.classList.remove("has-stream");
      if (kbRibbonLens) kbRibbonLens.classList.remove("has-stream");
      screenRecordingOk = true;
      syncLensControlsUI();
    }
  }

  function sendPayload(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  // Giải mã khung hình nhị phân LENS & vẽ khoanh vùng trung tâm con chuột sắc nét
  let isDecodingLens = false;
  let queuedLensBuffer = null;

  function drawCenteredCursorMarker(ctx, cw, ch, relMx, relMy, isRibbon) {
    const dpr = Math.min(2.2, window.devicePixelRatio || 1);
    const px = relMx * cw;
    const py = relMy * ch;

    ctx.save();

    // Chỉ phủ một quầng sáng nhỏ dịu nhẹ ngay mũi con trỏ (bỏ hoàn toàn vòng tròn to)
    const glowR = (isRibbon ? 5.0 : 6.5) * dpr;
    const grad = ctx.createRadialGradient(px, py, 0, px, py, glowR);
    grad.addColorStop(0, "rgba(56, 189, 248, 0.32)");
    grad.addColorStop(0.55, "rgba(56, 189, 248, 0.11)");
    grad.addColorStop(1, "rgba(56, 189, 248, 0)");
    ctx.beginPath();
    ctx.arc(px, py, glowR, 0, Math.PI * 2);
    ctx.fillStyle = grad;
    ctx.fill();

    // Mũi tên con trỏ chuột kích thước vừa gọn, sắc nét tại đúng điểm (px, py)
    const s = (isRibbon ? 0.62 : 0.72) * dpr;
    ctx.translate(px, py);
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(0, 14.5 * s);
    ctx.lineTo(4.0 * s, 11.0 * s);
    ctx.lineTo(6.9 * s, 16.8 * s);
    ctx.lineTo(9.2 * s, 15.6 * s);
    ctx.lineTo(6.3 * s, 9.8 * s);
    ctx.lineTo(11.0 * s, 9.8 * s);
    ctx.closePath();

    ctx.lineJoin = "round";
    ctx.lineWidth = 1.8 * s;
    ctx.strokeStyle = "rgba(9, 12, 18, 0.92)";
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.fill();

    ctx.restore();
  }

  async function processLensPacket(buffer) {
    if (!lensEnabled || padViewMode !== "lens" || buffer.byteLength <= 12) return;
    const view = new DataView(buffer);
    if (view.getUint32(0, false) !== 0x4c454e53) return;

    if (isDecodingLens) {
      queuedLensBuffer = buffer;
      return;
    }
    isDecodingLens = true;

    try {
      const isPad = kbLayout === "pad";
      const targetCanvas = isPad ? padLensCanvas : kbLensCanvas;
      const targetHostEl = isPad
        ? document.getElementById("trackpad-surface")
        : kbRibbonLens;
      if (!targetCanvas || !targetHostEl) return;

      const relMx = view.getUint16(4, false) / 10000;
      const relMy = view.getUint16(6, false) / 10000;
      const jpegSlice = new Uint8Array(buffer, 12);
      const blob = new Blob([jpegSlice], { type: "image/jpeg" });
      const bitmap = await createImageBitmap(blob);

      const rect = targetHostEl.getBoundingClientRect();
      const dpr = Math.min(2.2, window.devicePixelRatio || 1);
      const cw = Math.max(80, Math.round(rect.width * dpr));
      const ch = Math.max(36, Math.round(rect.height * dpr));
      if (targetCanvas.width !== cw || targetCanvas.height !== ch) {
        targetCanvas.width = cw;
        targetCanvas.height = ch;
      }

      const ctx = targetCanvas.getContext("2d", { alpha: false });
      if (ctx) {
        ctx.drawImage(bitmap, 0, 0, cw, ch);
        drawCenteredCursorMarker(ctx, cw, ch, relMx, relMy, !isPad);
      }
      bitmap.close();

      if (!targetHostEl.classList.contains("has-stream")) {
        targetHostEl.classList.add("has-stream");
      }
    } catch {
      // ignore corrupted frame
    } finally {
      isDecodingLens = false;
      if (queuedLensBuffer) {
        const next = queuedLensBuffer;
        queuedLensBuffer = null;
        void processLensPacket(next);
      }
    }
  }

  function connectWebSocket() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    const candidates = resolveCandidateHosts();
    if (candidates.length === 0) {
      setOnlineUI(false);
      return;
    }

    const targetHost = candidates[hostCycleIndex % candidates.length];
    hostCycleIndex = (hostCycleIndex + 1) % candidates.length;

    const useSecure =
      window.location.protocol === "https:" &&
      window.location.host !== "appassets.androidplatform.net";
    const proto = useSecure ? "wss:" : "ws:";
    const url = `${proto}//${targetHost}/ws`;

    if (ws) {
      try {
        ws.onclose = null;
        ws.onerror = null;
        ws.close();
      } catch {
        // ignore
      }
      ws = null;
    }

    try {
      ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
    } catch {
      scheduleReconnect();
      return;
    }

    ws.addEventListener("open", () => {
      setOnlineUI(true);
      reconnectDelay = 400;
      pushConfigToServer();
      if (pingInterval) clearInterval(pingInterval);
      pingInterval = setInterval(() => {
        sendPayload({ type: "ping" });
      }, 15000);
    });

    ws.addEventListener("message", (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        void processLensPacket(ev.data);
        return;
      }
      if (typeof ev.data === "string") {
        try {
          const msg = JSON.parse(ev.data);
          if (msg && msg.type === "typed_preview") {
            renderSimpleText(msg.text || "", msg.badge || "");
          } else if (msg && msg.type === "state" && typeof msg.screen_ok === "boolean") {
            screenRecordingOk = msg.screen_ok;
            syncLensControlsUI();
          }
        } catch {
          // ignore
        }
      }
    });

    ws.addEventListener("close", () => {
      setOnlineUI(false);
      if (pingInterval) {
        clearInterval(pingInterval);
        pingInterval = null;
      }
      scheduleReconnect();
    });

    ws.addEventListener("error", () => {
      try {
        ws.close();
      } catch {
        // ignore
      }
    });
  }

  window.__applyServerHost = (newRawHost) => {
    const cleaned = String(newRawHost || "").trim();
    try {
      if (cleaned) {
        localStorage.setItem(STORAGE_HOST_KEY, cleaned);
      } else {
        localStorage.removeItem(STORAGE_HOST_KEY);
      }
    } catch {
      // ignore
    }
    hostCycleIndex = 0;
    reconnectDelay = 200;
    connectWebSocket();
  };

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectWebSocket();
    }, reconnectDelay);
    reconnectDelay = Math.min(2500, Math.round(reconnectDelay * 1.5));
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reconnectDelay = 200;
        connectWebSocket();
      }
    } else {
      releaseAllActiveTouches();
    }
  });

  // ============================================================================
  // 3. FULLSCREEN + HAPTIC
  // ============================================================================
  let fullscreenAttempted = false;

  async function enterFullscreen(forceToggle = false) {
    try {
      if (forceToggle && document.fullscreenElement) {
        await document.exitFullscreen();
        return;
      }
      if (!document.fullscreenElement) {
        const root = document.documentElement;
        if (root.requestFullscreen) {
          await root.requestFullscreen({ navigationUI: "hide" });
        } else if (root.webkitRequestFullscreen) {
          root.webkitRequestFullscreen();
        }
      }
      applyOrientationForLayout();
    } catch {
      // ignore
    }
  }

  function ensureAutoFullscreenOnce() {
    if (hasAndroidBridge) return;
    if (fullscreenAttempted) return;
    fullscreenAttempted = true;
    void enterFullscreen(false);
  }

  function triggerHaptic(ms = 10) {
    if (hasAndroidBridge && typeof window.AndroidBridge.vibrate === "function") {
      try {
        window.AndroidBridge.vibrate(ms);
        return;
      } catch {
        // fallback
      }
    }
    if (navigator.vibrate) {
      try {
        navigator.vibrate(ms);
      } catch {
        // ignore
      }
    }
  }

  // ============================================================================
  // 4. MODIFIERS & BÀN PHÍM ĐA ĐIỂM
  // ============================================================================
  const MOD_NAMES = ["ctrl", "alt", "cmd", "shift"];
  const modState = {
    ctrl: { heldCount: 0, sticky: false, chordUsedWhileHeld: false },
    alt: { heldCount: 0, sticky: false, chordUsedWhileHeld: false },
    cmd: { heldCount: 0, sticky: false, chordUsedWhileHeld: false },
    shift: { heldCount: 0, sticky: false, chordUsedWhileHeld: false },
  };
  let capsLocked = false;

  function isModActive(mod) {
    return modState[mod].heldCount > 0 || modState[mod].sticky;
  }

  function syncModifierVisuals() {
    for (const mod of MOD_NAMES) {
      const st = modState[mod];
      const modBtns = document.querySelectorAll(`.key-mod[data-mod="${mod}"]`);
      modBtns.forEach((b) => {
        b.classList.toggle("is-held", st.heldCount > 0);
        b.classList.toggle("is-sticky", st.heldCount === 0 && st.sticky);
      });
    }
    const capsBtns = document.querySelectorAll(".key-caps");
    capsBtns.forEach((b) => {
      b.classList.toggle("is-locked", capsLocked);
    });

    const effectiveUpper = isModActive("shift") !== capsLocked;
    document.body.classList.toggle("is-shifted", isModActive("shift"));
    document.body.classList.toggle("is-lowercase", !effectiveUpper);
  }

  function markModifiersUsedInChord() {
    for (const mod of MOD_NAMES) {
      if (modState[mod].heldCount > 0) {
        modState[mod].chordUsedWhileHeld = true;
      }
    }
  }

  function consumeStickyModifiersAfterKey() {
    let changed = false;
    for (const mod of MOD_NAMES) {
      if (modState[mod].sticky && modState[mod].heldCount === 0) {
        modState[mod].sticky = false;
        changed = true;
      }
    }
    if (changed) {
      syncModifierVisuals();
    }
  }

  function handleModifierDown(mod) {
    const st = modState[mod];
    if (!st) return;

    if (st.sticky && st.heldCount === 0) {
      st.sticky = false;
      st._justCancelledSticky = true;
      sendPayload({ type: "up", key: mod });
      syncModifierVisuals();
      return;
    }

    st._justCancelledSticky = false;
    st.heldCount += 1;
    if (st.heldCount === 1) {
      st.chordUsedWhileHeld = false;
      st._downAt = performance.now();
      sendPayload({ type: "down", key: mod });
    }
    syncModifierVisuals();
  }

  function handleModifierUp(mod) {
    const st = modState[mod];
    if (!st) return;
    if (st._justCancelledSticky) {
      st._justCancelledSticky = false;
      return;
    }
    if (st.heldCount > 0) {
      st.heldCount -= 1;
    }
    if (st.heldCount === 0) {
      const heldDuration = performance.now() - (st._downAt || 0);
      sendPayload({ type: "up", key: mod });
      if (!st.chordUsedWhileHeld && heldDuration < 850) {
        st.sticky = true;
      } else {
        st.sticky = false;
      }
    }
    syncModifierVisuals();
  }

  const activePointers = new Map();

  function clearRepeatTimers(entry) {
    if (!entry) return;
    if (entry.repeatDelayTimer) {
      clearTimeout(entry.repeatDelayTimer);
      entry.repeatDelayTimer = null;
    }
    if (entry.repeatIntervalTimer) {
      clearInterval(entry.repeatIntervalTimer);
      entry.repeatIntervalTimer = null;
    }
  }

  function applyOfflinePreviewKey(rawKey, btnShiftChar = "") {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    const lower = String(rawKey || "").toLowerCase();
    const hasNonShift = isModActive("cmd") || isModActive("ctrl") || isModActive("alt");
    if (hasNonShift) {
      const mods = MOD_NAMES.filter((m) => isModActive(m)).map((m) => m.toUpperCase());
      renderSimpleText(simpleTextBuffer, `${mods.join("+")}+${lower.toUpperCase()}`);
      return;
    }
    if (lower === "backspace") {
      renderSimpleText(simpleTextBuffer.slice(0, -1));
      return;
    }
    if (lower === "space") {
      renderSimpleText((simpleTextBuffer + " ").slice(-220));
      return;
    }
    if (lower === "enter" || lower === "return") {
      if (isModActive("shift")) {
        const lines = (simpleTextBuffer + "\n").slice(-220).split("\n").slice(-4);
        renderSimpleText(lines.join("\n"));
      } else {
        renderSimpleText("", "");
      }
      return;
    }
    if (lower === "tab") {
      renderSimpleText((simpleTextBuffer + "  ").slice(-220));
      return;
    }
    if (rawKey.length === 1) {
      let ch = rawKey;
      if (lower >= "a" && lower <= "z") {
        const upper = isModActive("shift") !== capsLocked;
        ch = upper ? lower.toUpperCase() : lower;
      } else if (isModActive("shift") && btnShiftChar) {
        ch = btnShiftChar;
      }
      renderSimpleText((simpleTextBuffer + ch).slice(-220));
      return;
    }
    if (["up", "down", "left", "right", "esc", "del", "delete"].includes(lower)) {
      renderSimpleText(simpleTextBuffer, lower.toUpperCase());
    }
  }

  function fireKeyButtonAction(btn) {
    const action = btn.dataset.action;

    if (action === "toggle-mode-menu") {
      toggleModeMenu();
      return;
    }

    if (action === "toggle-vn") {
      closeModeMenu();
      toggleVietnameseMode();
      return;
    }

    if (action === "toggle-pad-split") {
      closeModeMenu();
      togglePadSplitMode();
      return;
    }

    if (action === "toggle-sym" || action === "toggle-sym-popup") {
      closeModeMenu();
      toggleSymbolLayer();
      return;
    }

    closeModeMenu();
    if (symLayer) {
      closeSymbolPopup();
    }

    if (action === "util" || action === "fullscreen") {
      if (
        hasAndroidBridge &&
        typeof window.AndroidBridge.openServerDialog === "function"
      ) {
        window.AndroidBridge.openServerDialog();
      } else if (webSettingsModal) {
        webSettingsModal.classList.remove("is-hidden");
      } else {
        void enterFullscreen(true);
      }
      return;
    }

    if (action === "mouse-right") {
      sendPayload({ type: "mouse_click", button: "right", count: 1 });
      return;
    }

    if (action === "scroll-up") {
      sendPayload({ type: "mouse_scroll", dx: 0, dy: 42 });
      return;
    }

    if (action === "scroll-down") {
      sendPayload({ type: "mouse_scroll", dx: 0, dy: -42 });
      return;
    }

    if (action === "caps") {
      capsLocked = !capsLocked;
      sendPayload({ type: "press", key: "capslock" });
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        renderSimpleText(simpleTextBuffer, capsLocked ? "CAPS" : "caps");
      }
      syncModifierVisuals();
      return;
    }

    if (action === "combo") {
      const rawCombo = btn.dataset.combo || "";
      const keys = rawCombo
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (keys.length > 0) {
        sendPayload({ type: "combo", keys });
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          const lowerK = keys.map((k) => k.toLowerCase());
          if (lowerK.includes("backspace") && (lowerK.includes("cmd") || lowerK.includes("ctrl"))) {
            const nl = simpleTextBuffer.lastIndexOf("\n");
            renderSimpleText(nl >= 0 ? simpleTextBuffer.slice(0, nl + 1) : "", "⌘⌫");
          } else {
            renderSimpleText(simpleTextBuffer, keys.map((k) => k.toUpperCase()).join("+"));
          }
        }
      }
      consumeStickyModifiersAfterKey();
      return;
    }

    if (action === "press") {
      const rawKey = btn.dataset.key || "";
      if (!rawKey) return;
      const lowerKey = rawKey.toLowerCase();
      if ((lowerKey === "enter" || lowerKey === "return") && !isModActive("shift")) {
        renderSimpleText("", "");
      }
      markModifiersUsedInChord();
      const activeMods = MOD_NAMES.filter((m) => isModActive(m));
      sendPayload(
        activeMods.length > 0
          ? { type: "press", key: rawKey, mods: activeMods }
          : { type: "press", key: rawKey }
      );
      applyOfflinePreviewKey(rawKey, btn.dataset.shift || "");
      consumeStickyModifiersAfterKey();
    }
  }

  function startPointerOnButton(pointerId, btn) {
    ensureAutoFullscreenOnce();
    triggerHaptic(10);

    btn.classList.add("is-pressed");
    const action = btn.dataset.action || "press";
    const mod = btn.dataset.mod || "";

    const entry = {
      btn,
      action,
      mod,
      repeatDelayTimer: null,
      repeatIntervalTimer: null,
    };
    activePointers.set(pointerId, entry);

    if (action === "modifier" && mod) {
      closeModeMenu();
      handleModifierDown(mod);
      return;
    }

    if (action === "mouse-left") {
      closeModeMenu();
      sendPayload({ type: "mouse_down", button: "left" });
      return;
    }

    fireKeyButtonAction(btn);

    if (btn.dataset.repeat === "true") {
      entry.repeatDelayTimer = setTimeout(() => {
        entry.repeatDelayTimer = null;
        entry.repeatIntervalTimer = setInterval(() => {
          fireKeyButtonAction(btn);
        }, 46);
      }, 300);
    }
  }

  function endPointer(pointerId) {
    const entry = activePointers.get(pointerId);
    if (!entry) return;
    activePointers.delete(pointerId);
    clearRepeatTimers(entry);

    let stillPressed = false;
    for (const other of activePointers.values()) {
      if (other.btn === entry.btn) {
        stillPressed = true;
        break;
      }
    }
    if (!stillPressed) {
      entry.btn.classList.remove("is-pressed");
    }

    if (entry.action === "modifier" && entry.mod) {
      handleModifierUp(entry.mod);
    } else if (entry.action === "mouse-left") {
      sendPayload({ type: "mouse_up", button: "left" });
    }
  }

  function releaseAllActiveTouches() {
    for (const id of Array.from(activePointers.keys())) {
      endPointer(id);
    }
    for (const mod of MOD_NAMES) {
      if (modState[mod].heldCount > 0 || modState[mod].sticky) {
        modState[mod].heldCount = 0;
        modState[mod].sticky = false;
        sendPayload({ type: "up", key: mod });
      }
    }
    syncModifierVisuals();
  }

  // ============================================================================
  // 5. NÚT MŨI TÊN THÔNG MINH 1 NÚT DUY NHẤT (MỖI LẦN ẤN GẠT CHỈ ĐI ĐÚNG 1 NẤC)
  // ============================================================================
  const joyBtn = document.getElementById("btn-joy-arrow");
  const joyLabel = document.getElementById("joy-arrow-label");
  let joyState = null; // { id, startX, startY, fired }

  const DIR_ICONS = {
    up: "▲",
    down: "▼",
    left: "◀",
    right: "▶",
  };

  function fireArrowDirection(dir) {
    markModifiersUsedInChord();
    const activeMods = MOD_NAMES.filter((m) => isModActive(m));
    sendPayload(
      activeMods.length > 0
        ? { type: "press", key: dir, mods: activeMods }
        : { type: "press", key: dir }
    );
    applyOfflinePreviewKey(dir);
    consumeStickyModifiersAfterKey();
  }

  function updateJoyDirection(curX, curY) {
    if (!joyState || joyState.fired) return;
    const dx = curX - joyState.startX;
    const dy = curY - joyState.startY;
    const dist = Math.hypot(dx, dy);
    if (dist < 10) return;

    let newDir = "";
    if (Math.abs(dx) > Math.abs(dy)) {
      newDir = dx > 0 ? "right" : "left";
    } else {
      newDir = dy > 0 ? "down" : "up";
    }

    if (newDir) {
      joyState.fired = true;
      triggerHaptic(10);
      if (joyLabel) {
        joyLabel.textContent = DIR_ICONS[newDir] || "✥";
      }
      fireArrowDirection(newDir);
    }
  }

  function endJoyGesture() {
    if (!joyState) return;
    joyState = null;
    if (joyBtn) {
      joyBtn.classList.remove("is-active-joy");
    }
    if (joyLabel) {
      joyLabel.textContent = "✥";
    }
  }

  if (joyBtn) {
    joyBtn.addEventListener(
      "touchstart",
      (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeModeMenu();
        closeSymbolPopup();
        const t = e.changedTouches[0];
        if (!t) return;
        joyState = {
          id: t.identifier,
          startX: t.clientX,
          startY: t.clientY,
          fired: false,
        };
        joyBtn.classList.add("is-active-joy");
        triggerHaptic(8);
      },
      { passive: false }
    );

    joyBtn.addEventListener(
      "touchmove",
      (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!joyState || joyState.fired) return;
        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const t = e.changedTouches[i];
          if (t.identifier === joyState.id) {
            updateJoyDirection(t.clientX, t.clientY);
            break;
          }
        }
      },
      { passive: false }
    );

    const onJoyTouchEnd = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!joyState) return;
      for (let i = 0; i < e.changedTouches.length; i += 1) {
        if (e.changedTouches[i].identifier === joyState.id) {
          endJoyGesture();
          break;
        }
      }
    };

    joyBtn.addEventListener("touchend", onJoyTouchEnd, { passive: false });
    joyBtn.addEventListener("touchcancel", onJoyTouchEnd, { passive: false });

    joyBtn.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      joyState = {
        id: "mouse",
        startX: e.clientX,
        startY: e.clientY,
        fired: false,
      };
      joyBtn.classList.add("is-active-joy");
    });

    window.addEventListener("mousemove", (e) => {
      if (joyState && joyState.id === "mouse" && !joyState.fired) {
        updateJoyDirection(e.clientX, e.clientY);
      }
    });

    window.addEventListener("mouseup", () => {
      if (joyState && joyState.id === "mouse") {
        endJoyGesture();
      }
    });
  }

  // ============================================================================
  // 6. BỘ XỬ LÝ MAGIC TRACKPAD ĐA ĐIỂM + ĐIỀU KHIỂN ZOOM KÍNH SOI TÂM CHUỘT
  // ============================================================================
  function updateLensFov(delta, resetDefault = false) {
    triggerHaptic(8);
    if (resetDefault) {
      lensFovScale = 1.22;
    } else {
      lensFovScale = Math.max(0.55, Math.min(1.85, +(lensFovScale + delta).toFixed(2)));
    }
    try {
      localStorage.setItem(STORAGE_LENS_SCALE_KEY, String(lensFovScale));
    } catch {
      // ignore
    }
    syncLensControlsUI();
    pushLensConfigToServer();
  }

  function bindHudTap(btn, callback) {
    if (!btn) return;
    let lastTouchAt = 0;
    btn.addEventListener(
      "touchstart",
      (e) => {
        e.preventDefault();
        e.stopPropagation();
        lastTouchAt = performance.now();
        callback();
      },
      { passive: false }
    );
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (performance.now() - lastTouchAt < 450) return;
      callback();
    });
  }

  function setPadViewMode(nextMode) {
    if (nextMode !== "lens" && nextMode !== "text") return;
    if (padViewMode === nextMode) return;
    triggerHaptic(10);
    padViewMode = nextMode;
    try {
      localStorage.setItem(STORAGE_PAD_VIEW_KEY, padViewMode);
    } catch {
      // ignore
    }
    syncLensControlsUI();
    pushLensConfigToServer();
  }

  padViewBtns.forEach((btn) => {
    bindHudTap(btn, () => {
      setPadViewMode(btn.dataset.padView || "lens");
    });
  });

  clearTextBtns.forEach((btn) => {
    bindHudTap(btn, () => {
      triggerHaptic(8);
      renderSimpleText("", "");
      sendPayload({ type: "clear_preview" });
    });
  });

  openScreenPermBtns.forEach((btn) => {
    bindHudTap(btn, () => {
      triggerHaptic(12);
      sendPayload({ type: "open_screen_perm" });
    });
  });

  respawnServerBtns.forEach((btn) => {
    bindHudTap(btn, () => {
      triggerHaptic(12);
      sendPayload({ type: "respawn_server" });
    });
  });

  fovOutBtns.forEach((btn) => {
    bindHudTap(btn, () => {
      updateLensFov(0.18, false);
    });
  });

  fovInBtns.forEach((btn) => {
    bindHudTap(btn, () => {
      updateLensFov(-0.18, false);
    });
  });

  fovLabels.forEach((btn) => {
    bindHudTap(btn, () => {
      updateLensFov(0, true);
    });
  });

  lensToggleBtns.forEach((btn) => {
    bindHudTap(btn, () => {
      triggerHaptic(10);
      lensEnabled = !lensEnabled;
      try {
        localStorage.setItem(STORAGE_LENS_ON_KEY, lensEnabled ? "1" : "0");
      } catch {
        // ignore
      }
      syncLensControlsUI();
      pushLensConfigToServer();
    });
  });

  syncLensControlsUI();
  renderSimpleText("", "");

  if (webTpSpeedRange) {
    webTpSpeedRange.addEventListener("input", () => {
      applyTrackpadSpeedValue(webTpSpeedRange.value, true);
    });
  }
  if (btnCloseWebSettings && webSettingsModal) {
    btnCloseWebSettings.addEventListener("click", () => {
      webSettingsModal.classList.add("is-hidden");
    });
    webSettingsModal.addEventListener("click", (e) => {
      if (e.target === webSettingsModal) {
        webSettingsModal.classList.add("is-hidden");
      }
    });
  }
  if (btnWebFullscreen && webSettingsModal) {
    btnWebFullscreen.addEventListener("click", () => {
      webSettingsModal.classList.add("is-hidden");
      void enterFullscreen(true);
    });
  }

  // Đường cong gia tốc lũy thừa liên tục chuẩn Apple Magic Trackpad (Direct 1:1 Power Ballistics):
  // - Nhích nhẹ tức thời (không có vùng chết gây lì tay), tỉ lệ ~0.8x-1.0x để bám sát từng ký tự/nút nhỏ
  // - Vẩy nhanh tăng mượt tự nhiên theo hàm mũ 0.85 không bị gãy khúc đột ngột
  function computeMacTrackpadGain(smoothedVelPxMs) {
    const speedNorm = trackpadSpeed / 1.6;
    const minGain = 0.76 * Math.sqrt(speedNorm);
    const dynamicGain = 2.95 * speedNorm * Math.pow(Math.max(0, smoothedVelPxMs), 0.85);
    return Math.min(6.4 * speedNorm, minGain + dynamicGain);
  }

  function bindTrackpadSurface(surface) {
    if (!surface) return;
    const tpTouches = new Map();
    let tpGestureStartAt = 0;
    let tpPrevMoveAt = 0;
    let tpSmoothedVel = 0;
    let tpMaxTouches = 0;
    let tpTotalMoved = 0;
    let tpRemX = 0;
    let tpRemY = 0;
    let tpScrollRemX = 0;
    let tpScrollRemY = 0;
    let tpLastTapAt = 0;
    let tpPendingDoubleTapCandidate = false;
    let tpDragActive = false;
    let tpLongPressTimer = null;
    let tpDragReleaseTimer = null;

    function cancelLongPressTimer() {
      if (tpLongPressTimer !== null) {
        clearTimeout(tpLongPressTimer);
        tpLongPressTimer = null;
      }
    }

    function engageDragLock(hapticMs = 18) {
      if (tpDragActive) return;
      cancelLongPressTimer();
      if (tpDragReleaseTimer !== null) {
        clearTimeout(tpDragReleaseTimer);
        tpDragReleaseTimer = null;
      }
      tpDragActive = true;
      tpPendingDoubleTapCandidate = false;
      surface.classList.add("is-dragging");
      triggerHaptic(hapticMs);
      sendPayload({ type: "mouse_down", button: "left", drag: true });
    }

    function releaseDragLockImmediate() {
      cancelLongPressTimer();
      if (tpDragReleaseTimer !== null) {
        clearTimeout(tpDragReleaseTimer);
        tpDragReleaseTimer = null;
      }
      if (!tpDragActive) return;
      tpDragActive = false;
      surface.classList.remove("is-dragging");
      sendPayload({ type: "mouse_up", button: "left" });
    }

    surface.addEventListener(
      "touchstart",
      (e) => {
        if (e.target.closest(".lens-hud-right, .lens-hud-left, .lens-perm-bar, .pad-scroll-strip")) {
          return;
        }
        e.preventDefault();
        e.stopPropagation();
        closeModeMenu();
        closeSymbolPopup();
        ensureAutoFullscreenOnce();

        const now = performance.now();
        const isFirstFingerDown = tpTouches.size === 0;

        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const t = e.changedTouches[i];
          tpTouches.set(t.identifier, {
            x: t.clientX,
            y: t.clientY,
          });
        }
        tpMaxTouches = Math.max(tpMaxTouches, tpTouches.size);
        surface.classList.add("is-touching");

        // Nếu đang trong nhịp nối kéo 320ms (hết mặt Trackpad nhấc tay đặt lại kéo tiếp như MacBook): giữ nguyên bôi đen!
        if (tpDragReleaseTimer !== null) {
          clearTimeout(tpDragReleaseTimer);
          tpDragReleaseTimer = null;
          if (tpTouches.size === 1) {
            tpGestureStartAt = now;
            tpPrevMoveAt = now;
            tpTotalMoved = 0;
            return;
          }
        }

        // Chạm 3 ngón -> kích hoạt Three-Finger Drag chuẩn MacBook ngay lập tức
        if (tpTouches.size >= 3) {
          cancelLongPressTimer();
          engageDragLock(14);
          return;
        }

        // Chạm >= 2 ngón (Cuộn trang / Chuột phải) -> hủy chờ ấn giữ 1 ngón
        if (tpTouches.size >= 2) {
          cancelLongPressTimer();
          tpPendingDoubleTapCandidate = false;
          return;
        }

        if (isFirstFingerDown) {
          tpGestureStartAt = now;
          tpPrevMoveAt = now;
          tpSmoothedVel = 0;
          tpTotalMoved = 0;
          tpRemX = 0;
          tpRemY = 0;
          tpScrollRemX = 0;
          tpScrollRemY = 0;
          tpPendingDoubleTapCandidate = now - tpLastTapAt < 270;

          // Cơ chế Force-Touch mô phỏng trên điện thoại: Ấn giữ yên ~230ms rồi kéo lướt -> Bôi đen / Kéo thả!
          cancelLongPressTimer();
          tpLongPressTimer = setTimeout(() => {
            tpLongPressTimer = null;
            if (tpTouches.size === 1 && tpTotalMoved < 5.5 && !tpDragActive) {
              engageDragLock(18);
            }
          }, 230);
        }
      },
      { passive: false }
    );

    surface.addEventListener(
      "touchmove",
      (e) => {
        if (tpTouches.size === 0) return;
        e.preventDefault();
        e.stopPropagation();

        let sumDx = 0;
        let sumDy = 0;
        let movedCount = 0;

        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const t = e.changedTouches[i];
          const prev = tpTouches.get(t.identifier);
          if (prev) {
            sumDx += t.clientX - prev.x;
            sumDy += t.clientY - prev.y;
            prev.x = t.clientX;
            prev.y = t.clientY;
            movedCount += 1;
          }
        }

        if (movedCount === 0) return;
        const now = performance.now();
        const dt = Math.max(4, Math.min(60, now - tpPrevMoveAt));
        tpPrevMoveAt = now;

        const dx = sumDx / movedCount;
        const dy = sumDy / movedCount;
        const stepDist = Math.hypot(dx, dy);
        tpTotalMoved += stepDist;

        // Nếu ngón tay bắt đầu lướt đi trước 230ms:
        // - Nếu là nhịp chạm thứ 2 (Double-Tap & Drag) -> vào chế độ kéo bôi đen ngay!
        // - Nếu là nhịp chạm đơn bình thường -> hủy timer ấn giữ để di chuột 1:1 mượt tức thì
        if (tpTotalMoved >= 4.2 && !tpDragActive && tpTouches.size === 1) {
          cancelLongPressTimer();
          if (tpPendingDoubleTapCandidate) {
            engageDragLock(12);
          }
        }

        // Chạm đúng 2 ngón và không ở chế độ Kéo -> Cuộn trang 2 ngón
        if (tpTouches.size === 2 && !tpDragActive) {
          cancelLongPressTimer();
          tpScrollRemX += -dx * 0.85;
          tpScrollRemY += -dy * 0.85;
          const sendSx = Math.trunc(tpScrollRemX);
          const sendSy = Math.trunc(tpScrollRemY);
          if (sendSx !== 0 || sendSy !== 0) {
            tpScrollRemX -= sendSx;
            tpScrollRemY -= sendSy;
            sendPayload({
              type: "mouse_scroll",
              dx: sendSx,
              dy: sendSy,
            });
          }
          return;
        }

        // Lọc nhiễu vi mô < 0.35px khi đang giữ ngón tay chờ Long-Press
        if (!tpDragActive && tpLongPressTimer !== null && tpTotalMoved < 1.6) {
          return;
        }

        const vInst = stepDist / dt;
        if (vInst < tpSmoothedVel) {
          tpSmoothedVel = tpSmoothedVel * 0.25 + vInst * 0.75;
        } else {
          tpSmoothedVel = tpSmoothedVel * 0.58 + vInst * 0.42;
        }

        const gain = computeMacTrackpadGain(tpSmoothedVel);
        tpRemX += dx * gain;
        tpRemY += dy * gain;

        if (Math.hypot(tpRemX, tpRemY) >= 0.2) {
          const outX = Math.round(tpRemX * 100) / 100;
          const outY = Math.round(tpRemY * 100) / 100;
          tpRemX -= outX;
          tpRemY -= outY;
          sendPayload({
            type: "mouse_move",
            dx: outX,
            dy: outY,
          });
        }
      },
      { passive: false }
    );

    const handleTrackpadTouchEnd = (e) => {
      if (tpTouches.size === 0) return;
      e.preventDefault();
      e.stopPropagation();
      for (let i = 0; i < e.changedTouches.length; i += 1) {
        tpTouches.delete(e.changedTouches[i].identifier);
      }

      if (tpTouches.size === 0) {
        cancelLongPressTimer();
        surface.classList.remove("is-touching");
        const duration = performance.now() - tpGestureStartAt;

        if (tpDragActive) {
          // Nếu người dùng chạm nhẹ 1 cái để thả ngay -> nhả chuột trái lập tức
          if (tpTotalMoved < 4.5 && duration < 190) {
            releaseDragLockImmediate();
            tpLastTapAt = 0;
            return;
          }
          // Mở cửa sổ 300ms chuẩn MacBook để nếu đụng mép Trackpad có thể đặt ngón lại kéo nối tiếp vùng bôi đen!
          tpDragReleaseTimer = setTimeout(() => {
            tpDragReleaseTimer = null;
            releaseDragLockImmediate();
          }, 300);
          return;
        }

        if (tpPendingDoubleTapCandidate && tpTotalMoved < 7 && duration < 250) {
          tpPendingDoubleTapCandidate = false;
          tpLastTapAt = 0;
          triggerHaptic(10);
          sendPayload({ type: "mouse_click", button: "left", count: 2 });
          return;
        }

        tpPendingDoubleTapCandidate = false;
        if (tpTotalMoved < 8 && duration < 260) {
          triggerHaptic(8);
          if (tpMaxTouches >= 2) {
            sendPayload({ type: "mouse_click", button: "right", count: 1 });
          } else {
            sendPayload({ type: "mouse_click", button: "left", count: 1 });
            tpLastTapAt = performance.now();
          }
        }
      }
    };

    surface.addEventListener("touchend", handleTrackpadTouchEnd, {
      passive: false,
    });
    surface.addEventListener("touchcancel", handleTrackpadTouchEnd, {
      passive: false,
    });
  }

  function bindScrollStrip(stripEl) {
    if (!stripEl) return;
    const thumbEl = stripEl.querySelector(".js-scroll-thumb");
    let activeId = null;
    let startAt = 0;
    let prevY = 0;
    let prevAt = 0;
    let totalMoved = 0;
    let thumbOffset = 0;
    let scrollRemY = 0;
    let velocityPxMs = 0;
    let inertiaRaf = null;

    function stopInertia() {
      if (inertiaRaf !== null) {
        cancelAnimationFrame(inertiaRaf);
        inertiaRaf = null;
      }
    }

    function setThumbOffset(px) {
      if (!thumbEl) return;
      const trackEl = thumbEl.parentElement;
      const maxOff = trackEl ? Math.max(12, (trackEl.clientHeight - 34) / 2) : 36;
      thumbOffset = Math.max(-maxOff, Math.min(maxOff, px));
      thumbEl.style.setProperty("--thumb-offset", `${thumbOffset.toFixed(1)}px`);
    }

    function emitScrollStep(deltaY) {
      if (Math.abs(deltaY) < 0.1) return;
      const gain = Math.min(1.25, 0.68 + Math.abs(deltaY) * 0.02);
      scrollRemY += -deltaY * gain;
      const sendY = Math.trunc(scrollRemY);
      if (sendY !== 0) {
        scrollRemY -= sendY;
        sendPayload({
          type: "mouse_scroll",
          dx: 0,
          dy: sendY,
        });
      }
    }

    stripEl.addEventListener(
      "touchstart",
      (e) => {
        const t = e.changedTouches[0];
        if (!t) return;
        e.preventDefault();
        e.stopPropagation();
        stopInertia();
        closeModeMenu();
        closeSymbolPopup();
        ensureAutoFullscreenOnce();
        triggerHaptic(6);

        activeId = t.identifier;
        startAt = performance.now();
        prevAt = startAt;
        prevY = t.clientY;
        totalMoved = 0;
        scrollRemY = 0;
        velocityPxMs = 0;
        stripEl.classList.add("is-scrolling");
      },
      { passive: false }
    );

    stripEl.addEventListener(
      "touchmove",
      (e) => {
        if (activeId === null) return;
        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const t = e.changedTouches[i];
          if (t.identifier === activeId) {
            e.preventDefault();
            e.stopPropagation();
            const now = performance.now();
            const dt = Math.max(4, now - prevAt);
            const dy = t.clientY - prevY;
            prevY = t.clientY;
            prevAt = now;
            totalMoved += Math.abs(dy);
            velocityPxMs = velocityPxMs * 0.5 + (dy / dt) * 0.5;
            setThumbOffset(thumbOffset + dy * 0.45);
            emitScrollStep(dy);
            break;
          }
        }
      },
      { passive: false }
    );

    const onScrollTouchEnd = (e) => {
      if (activeId === null) return;
      for (let i = 0; i < e.changedTouches.length; i += 1) {
        const t = e.changedTouches[i];
        if (t.identifier === activeId) {
          e.preventDefault();
          e.stopPropagation();
          activeId = null;
          stripEl.classList.remove("is-scrolling");
          setThumbOffset(0);

          const duration = performance.now() - startAt;
          if (totalMoved < 6 && duration < 240) {
            const rect = stripEl.getBoundingClientRect();
            const relY = rect.height > 0 ? (t.clientY - rect.top) / rect.height : 0.5;
            if (relY < 0.3) {
              triggerHaptic(6);
              sendPayload({ type: "mouse_scroll", dx: 0, dy: 24 });
            } else if (relY > 0.7) {
              triggerHaptic(6);
              sendPayload({ type: "mouse_scroll", dx: 0, dy: -24 });
            }
            return;
          }

          if (Math.abs(velocityPxMs) > 0.65) {
            let vFrame = velocityPxMs * 6.0;
            let inertiaRem = 0;
            const stepInertia = () => {
              vFrame *= 0.85;
              if (Math.abs(vFrame) < 0.6) {
                inertiaRaf = null;
                return;
              }
              inertiaRem += -vFrame * 0.85;
              const sendY = Math.trunc(inertiaRem);
              if (sendY !== 0) {
                inertiaRem -= sendY;
                sendPayload({
                  type: "mouse_scroll",
                  dx: 0,
                  dy: sendY,
                });
              }
              inertiaRaf = requestAnimationFrame(stepInertia);
            };
            inertiaRaf = requestAnimationFrame(stepInertia);
          }
          break;
        }
      }
    };

    stripEl.addEventListener("touchend", onScrollTouchEnd, { passive: false });
    stripEl.addEventListener("touchcancel", onScrollTouchEnd, { passive: false });
  }

  bindTrackpadSurface(document.getElementById("trackpad-surface"));
  bindTrackpadSurface(kbRibbonLens);
  bindScrollStrip(document.getElementById("pad-scroll-strip"));

  if (typeof ResizeObserver !== "undefined") {
    let roTimer = null;
    const ro = new ResizeObserver(() => {
      if (roTimer) clearTimeout(roTimer);
      roTimer = setTimeout(pushLensConfigToServer, 80);
    });
    const tpEl = document.getElementById("trackpad-surface");
    if (tpEl) ro.observe(tpEl);
    if (kbRibbonLens) ro.observe(kbRibbonLens);
  }

  // ============================================================================
  // 7. LẮNG NGHE PHÍM TRÊN KHUNG NGANG (#kb-shell) & KHUNG DỌC (#pad-shell)
  // ============================================================================
  function bindShellEvents(container) {
    if (!container) return;

    container.addEventListener(
      "touchstart",
      (e) => {
        if (
          e.target.closest("#trackpad-surface") ||
          e.target.closest("#kb-ribbon-lens") ||
          e.target.closest("#sym-floating-popup") ||
          e.target.closest(".js-mode-menu") ||
          e.target.closest("#btn-joy-arrow")
        ) {
          return;
        }
        e.preventDefault();
        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const t = e.changedTouches[i];
          const el = document.elementFromPoint(t.clientX, t.clientY);
          const btn = el ? el.closest(".key") : null;
          if (btn) {
            startPointerOnButton(`t_${t.identifier}`, btn);
          } else {
            closeModeMenu();
            closeSymbolPopup();
          }
        }
      },
      { passive: false }
    );

    container.addEventListener(
      "touchend",
      (e) => {
        if (
          e.target.closest("#trackpad-surface") ||
          e.target.closest("#kb-ribbon-lens") ||
          e.target.closest("#sym-floating-popup") ||
          e.target.closest(".js-mode-menu") ||
          e.target.closest("#btn-joy-arrow")
        ) {
          return;
        }
        e.preventDefault();
        for (let i = 0; i < e.changedTouches.length; i += 1) {
          endPointer(`t_${e.changedTouches[i].identifier}`);
        }
      },
      { passive: false }
    );

    container.addEventListener(
      "touchcancel",
      (e) => {
        if (
          e.target.closest("#trackpad-surface") ||
          e.target.closest("#kb-ribbon-lens") ||
          e.target.closest("#sym-floating-popup") ||
          e.target.closest(".js-mode-menu") ||
          e.target.closest("#btn-joy-arrow")
        ) {
          return;
        }
        e.preventDefault();
        for (let i = 0; i < e.changedTouches.length; i += 1) {
          endPointer(`t_${e.changedTouches[i].identifier}`);
        }
      },
      { passive: false }
    );

    container.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      if (
        e.target.closest("#trackpad-surface") ||
        e.target.closest("#kb-ribbon-lens") ||
        e.target.closest("#sym-floating-popup") ||
        e.target.closest(".js-mode-menu") ||
        e.target.closest("#btn-joy-arrow")
      ) {
        return;
      }
      const btn = e.target.closest(".key");
      if (!btn) {
        closeModeMenu();
        closeSymbolPopup();
        return;
      }
      e.preventDefault();
      startPointerOnButton("mouse", btn);
    });
  }

  bindShellEvents(document.getElementById("kb-shell"));
  bindShellEvents(document.getElementById("pad-shell"));

  window.addEventListener("mouseup", () => {
    endPointer("mouse");
  });

  window.addEventListener("contextmenu", (e) => {
    e.preventDefault();
  });

  syncModifierVisuals();
  connectWebSocket();
})();
