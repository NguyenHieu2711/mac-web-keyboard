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
    remote: "🖥 Remote",
  };

  let kbLayout = "pad";
  let lastNonRemoteLayout = "pad";
  let padSplitHorizontal = false;
  let vnEnabled = true;
  let symLayer = false;
  let symShifted = false;
  let modeMenuOpen = false;
  let rdpEdgeMode = "any";
  let onEnterRemoteLayout = null;
  let onLeaveRemoteLayout = null;
  let handleKvmServerMessage = null;

  try {
    const savedLayout = localStorage.getItem(STORAGE_LAYOUT_KEY);
    if (
      savedLayout === "win" ||
      savedLayout === "mac" ||
      savedLayout === "pad" ||
      savedLayout === "remote"
    ) {
      kbLayout = savedLayout;
      if (savedLayout !== "remote") {
        lastNonRemoteLayout = savedLayout;
      }
    }
    const savedSplit = localStorage.getItem(STORAGE_PAD_SPLIT_KEY);
    if (savedSplit === "horizontal" || savedSplit === "1") {
      padSplitHorizontal = true;
    }
    const savedVn = localStorage.getItem(STORAGE_VN_KEY);
    if (savedVn === "0" || savedVn === "false") {
      vnEnabled = false;
    }
    const savedEdge = localStorage.getItem("mac_kb_rdp_edge_mode");
    if (
      savedEdge === "any" ||
      savedEdge === "bottom" ||
      savedEdge === "right" ||
      savedEdge === "left" ||
      savedEdge === "top"
    ) {
      rdpEdgeMode = savedEdge;
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
    const splitSvg = padSplitHorizontal
      ? '<svg class="split-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" d="M4 12h16M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5"/></svg><span>Ngang</span>'
      : '<svg class="split-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" d="M12 4v16M7.5 8.5L12 4l4.5 4.5M7.5 15.5L12 20l4.5-4.5"/></svg><span>Dọc</span>';
    padSplitLabels.forEach((el) => {
      el.innerHTML = splitSvg;
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
    if (kbLayout === "remote") {
      sendPayload({
        type: "lens_config",
        enabled: false,
        aspect: 1.85,
        scale: +lensFovScale.toFixed(2),
        mode: "landscape",
      });
      return;
    }
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

  function pushKvmConfigToServer() {
    const activeRemote =
      kbLayout === "remote" && document.visibilityState === "visible";
    sendPayload({
      type: "kvm_config",
      enabled: activeRemote,
      edge: rdpEdgeMode,
    });
  }

  function pushConfigToServer() {
    sendPayload({
      type: "config",
      layout: kbLayout,
      vn: vnEnabled,
    });
    pushKvmConfigToServer();
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
    const prevLayout = kbLayout;
    if (prevLayout !== "remote" && newLayout === "remote") {
      lastNonRemoteLayout = prevLayout;
    }
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
    if (kbLayout === "remote") {
      if (typeof onEnterRemoteLayout === "function") onEnterRemoteLayout();
    } else if (prevLayout === "remote") {
      if (typeof onLeaveRemoteLayout === "function") onLeaveRemoteLayout();
    }
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
          if (
            msg &&
            (msg.type === "kvm_enter" ||
              msg.type === "kvm_mouse" ||
              msg.type === "kvm_released")
          ) {
            if (typeof handleKvmServerMessage === "function") {
              handleKvmServerMessage(msg);
            }
          } else if (msg && msg.type === "typed_preview") {
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
      } else {
        pushKvmConfigToServer();
      }
    } else {
      releaseAllActiveTouches();
      pushKvmConfigToServer();
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

  // Đường cong gia tốc lũy thừa chuẩn Apple Magic Trackpad (đã hạ thêm ~16% tốc độ con trỏ cho đằm tay hơn)
  function computeMacTrackpadGain(smoothedVelPxMs) {
    const speedNorm = trackpadSpeed / 1.6;
    const minGain = 0.64 * Math.sqrt(speedNorm);
    const dynamicGain = 2.42 * speedNorm * Math.pow(Math.max(0, smoothedVelPxMs), 0.85);
    return Math.min(5.2 * speedNorm, minGain + dynamicGain);
  }

  // ============================================================================
  // CƠ CHẾ CUỘN GIA TỐC THÔNG MINH 3 TẦNG (CHUẨN macOS NSScrollView + Logitech SmartShift):
  // 1. Kéo chậm (< 0.28 px/ms): khóa phẳng 0.22x siêu đằm để đọc từng dòng, nhấc tay đứng im 100% không trôi.
  // 2. Vuốt nhanh (> 0.28 px/ms): tăng gia tốc lũy thừa theo vận tốc thực (lên tới 2.9x) để vọt nhanh.
  // 3. Bánh đà quán tính hàm mũ 0.9968^dt + Cộng bồi vận tốc khi gạt liên tiếp cùng chiều (Velocity Stacking)
  //    để 2 cú hất nhẹ lên thẳng đầu trang dài; chạm nhẹ 1 ngón phanh đứng khựng ngay (không click nhầm link).
  // ============================================================================
  const sharedScrollStripEl = document.getElementById("pad-scroll-strip");
  const sharedScrollThumbEl = sharedScrollStripEl
    ? sharedScrollStripEl.querySelector(".js-scroll-thumb")
    : null;
  let sharedThumbOffset = 0;
  let sharedScrollRemX = 0;
  let sharedScrollRemY = 0;
  let sharedScrollInertiaRaf = null;
  let activeCoastingVelY = 0;
  let savedCoastingVelY = 0;
  let savedCoastingAt = 0;

  function stopUnifiedScrollInertia(recordForStacking = true) {
    const wasCoasting = Math.abs(activeCoastingVelY) > 0.14;
    if (recordForStacking && wasCoasting) {
      savedCoastingVelY = activeCoastingVelY;
      savedCoastingAt = performance.now();
    }
    activeCoastingVelY = 0;
    if (sharedScrollInertiaRaf !== null) {
      cancelAnimationFrame(sharedScrollInertiaRaf);
      sharedScrollInertiaRaf = null;
    }
    return wasCoasting;
  }

  function setSharedThumbOffset(px) {
    if (!sharedScrollThumbEl) return;
    const trackEl = sharedScrollThumbEl.parentElement;
    const maxOff = trackEl ? Math.max(12, (trackEl.clientHeight - 34) / 2) : 36;
    sharedThumbOffset = Math.max(-maxOff, Math.min(maxOff, px));
    sharedScrollThumbEl.style.setProperty("--thumb-offset", `${sharedThumbOffset.toFixed(1)}px`);
  }

  function setSharedScrollVisual(active) {
    if (!sharedScrollStripEl) return;
    sharedScrollStripEl.classList.toggle("is-scrolling", active);
    if (!active) {
      setSharedThumbOffset(0);
    }
  }

  function resetUnifiedScrollState() {
    sharedScrollRemX = 0;
    sharedScrollRemY = 0;
  }

  function computeSmartScrollGain(velPxMs) {
    const absV = Math.abs(velPxMs);
    if (absV <= 0.28) {
      return 0.22;
    }
    const excess = absV - 0.28;
    return Math.min(2.9, 0.22 + 1.68 * Math.pow(excess, 1.32));
  }

  function emitUnifiedScroll(dx, dy, dtMs = 10) {
    if (Math.abs(dx) < 0.08 && Math.abs(dy) < 0.08) return;
    const safeDt = Math.max(4, Math.min(60, dtMs));
    const gainX = computeSmartScrollGain(dx / safeDt);
    const gainY = computeSmartScrollGain(dy / safeDt);
    sharedScrollRemX += -dx * gainX;
    sharedScrollRemY += -dy * gainY;
    if (Math.abs(sharedScrollRemX) < 1.2 && Math.abs(sharedScrollRemY) < 1.2) return;
    const sendX = Math.trunc(sharedScrollRemX);
    const sendY = Math.trunc(sharedScrollRemY);
    if (sendX !== 0 || sendY !== 0) {
      sharedScrollRemX -= sendX;
      sharedScrollRemY -= sendY;
      sendPayload({
        type: "mouse_scroll",
        dx: sendX,
        dy: sendY,
      });
    }
  }

  function startUnifiedScrollInertia(fingerVelPxMs) {
    stopUnifiedScrollInertia(false);
    // Kéo chậm đọc từng dòng (<= 0.48 px/ms) -> dừng im tại chỗ, không trôi quán tính
    if (Math.abs(fingerVelPxMs) <= 0.48) {
      savedCoastingVelY = 0;
      return;
    }

    const now = performance.now();
    const gainAtRelease = computeSmartScrollGain(fingerVelPxMs);
    // Vận tốc cuộn đầu ra (px/ms)
    let launchVel = -fingerVelPxMs * gainAtRelease;

    // Nếu gạt bồi liên tiếp cùng chiều trong vòng 420ms khi bánh đà đang quay -> cộng dồn vận tốc để phóng vút lên đầu/cuối trang!
    if (
      savedCoastingVelY !== 0 &&
      now - savedCoastingAt < 420 &&
      Math.sign(savedCoastingVelY) === Math.sign(launchVel)
    ) {
      const stackedMag = Math.min(
        7.5,
        Math.abs(savedCoastingVelY) * 0.78 + Math.abs(launchVel) * 1.35
      );
      launchVel = Math.sign(launchVel) * stackedMag;
    } else {
      launchVel = Math.sign(launchVel) * Math.min(4.2, Math.abs(launchVel));
    }
    savedCoastingVelY = 0;
    activeCoastingVelY = launchVel;

    let lastFrameAt = now;
    let inertiaRem = 0;

    const stepInertia = () => {
      const curAt = performance.now();
      const dt = Math.max(4, Math.min(48, curAt - lastFrameAt));
      lastFrameAt = curAt;

      // Hàm suy giảm mũ chuẩn UIScrollView / NSScrollView (0.9968 ^ dt_ms)
      activeCoastingVelY *= Math.pow(0.9968, dt);
      if (Math.abs(activeCoastingVelY) < 0.055) {
        activeCoastingVelY = 0;
        sharedScrollInertiaRaf = null;
        return;
      }

      inertiaRem += activeCoastingVelY * dt;
      if (Math.abs(inertiaRem) >= 1.1) {
        const sendY = Math.trunc(inertiaRem);
        if (sendY !== 0) {
          inertiaRem -= sendY;
          sendPayload({
            type: "mouse_scroll",
            dx: 0,
            dy: sendY,
          });
        }
      }
      sharedScrollInertiaRaf = requestAnimationFrame(stepInertia);
    };
    sharedScrollInertiaRaf = requestAnimationFrame(stepInertia);
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
    let tpTwoFingerScrollVelY = 0;
    let tpWasTwoFingerScrolling = false;
    let tpBrakedCoasting = false;
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

        // Chạm >= 2 ngón (Cuộn trang / Chuột phải) -> hủy chờ ấn giữ 1 ngón & phanh quán tính cuộn cũ
        if (tpTouches.size >= 2) {
          cancelLongPressTimer();
          if (stopUnifiedScrollInertia(true)) {
            tpBrakedCoasting = true;
          }
          resetUnifiedScrollState();
          tpTwoFingerScrollVelY = 0;
          tpPendingDoubleTapCandidate = false;
          return;
        }

        if (isFirstFingerDown) {
          tpBrakedCoasting = stopUnifiedScrollInertia(true);
          tpGestureStartAt = now;
          tpPrevMoveAt = now;
          tpSmoothedVel = 0;
          tpTotalMoved = 0;
          tpRemX = 0;
          tpRemY = 0;
          tpTwoFingerScrollVelY = 0;
          tpWasTwoFingerScrolling = false;
          resetUnifiedScrollState();
          tpPendingDoubleTapCandidate = !tpBrakedCoasting && now - tpLastTapAt < 270;

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

        // Chạm đúng 2 ngón và không ở chế độ Kéo -> Đồng bộ 100% cơ chế & thanh hiển thị với Thanh cuộn bên phải
        if (tpTouches.size === 2 && !tpDragActive) {
          cancelLongPressTimer();
          tpWasTwoFingerScrolling = true;
          const vNow = dy / dt;
          if (Math.abs(vNow) < Math.abs(tpTwoFingerScrollVelY)) {
            tpTwoFingerScrollVelY = tpTwoFingerScrollVelY * 0.3 + vNow * 0.7;
          } else {
            tpTwoFingerScrollVelY = tpTwoFingerScrollVelY * 0.55 + vNow * 0.45;
          }
          setSharedScrollVisual(true);
          setSharedThumbOffset(sharedThumbOffset + dy * 0.42);
          emitUnifiedScroll(dx, dy, dt);
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
        if (tpWasTwoFingerScrolling) {
          tpWasTwoFingerScrolling = false;
          setSharedScrollVisual(false);
          if (performance.now() - tpPrevMoveAt > 65) {
            savedCoastingVelY = 0;
          } else {
            startUnifiedScrollInertia(tpTwoFingerScrollVelY);
          }
        }
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
        // Nếu cú chạm vừa rồi chỉ để phanh dừng trang đang trôi nhanh -> tuyệt đối không Click nhầm vào link dưới trỏ chuột!
        if (tpBrakedCoasting && tpTotalMoved < 8) {
          tpBrakedCoasting = false;
          return;
        }
        tpBrakedCoasting = false;
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
    let activeId = null;
    let startAt = 0;
    let prevY = 0;
    let prevAt = 0;
    let totalMoved = 0;
    let velocityPxMs = 0;
    let stripBrakedCoasting = false;

    stripEl.addEventListener(
      "touchstart",
      (e) => {
        const t = e.changedTouches[0];
        if (!t) return;
        e.preventDefault();
        e.stopPropagation();
        stripBrakedCoasting = stopUnifiedScrollInertia(true);
        resetUnifiedScrollState();
        closeModeMenu();
        closeSymbolPopup();
        ensureAutoFullscreenOnce();
        triggerHaptic(6);

        activeId = t.identifier;
        startAt = performance.now();
        prevAt = startAt;
        prevY = t.clientY;
        totalMoved = 0;
        velocityPxMs = 0;
        setSharedScrollVisual(true);
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
            const vNow = dy / dt;
            if (Math.abs(vNow) < Math.abs(velocityPxMs)) {
              velocityPxMs = velocityPxMs * 0.3 + vNow * 0.7;
            } else {
              velocityPxMs = velocityPxMs * 0.55 + vNow * 0.45;
            }
            setSharedThumbOffset(sharedThumbOffset + dy * 0.42);
            emitUnifiedScroll(0, dy, dt);
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
          setSharedScrollVisual(false);

          const duration = performance.now() - startAt;
          if (totalMoved < 6 && duration < 240) {
            if (stripBrakedCoasting) {
              stripBrakedCoasting = false;
              return;
            }
            const rect = stripEl.getBoundingClientRect();
            const relY = rect.height > 0 ? (t.clientY - rect.top) / rect.height : 0.5;
            if (relY < 0.3) {
              triggerHaptic(6);
              sendPayload({ type: "mouse_scroll", dx: 0, dy: 11 });
            } else if (relY > 0.7) {
              triggerHaptic(6);
              sendPayload({ type: "mouse_scroll", dx: 0, dy: -11 });
            }
            return;
          }
          stripBrakedCoasting = false;

          // Nếu ngón tay đã giữ dừng yên trước khi nhấc lên (> 65ms không rê tiếp) -> hủy trôi đà
          if (performance.now() - prevAt > 65) {
            savedCoastingVelY = 0;
            return;
          }
          startUnifiedScrollInertia(velocityPxMs);
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

  // ============================================================================
  // 8. TAB 4 ĐỘC LẬP: REMOTE PC (2248x1080 @ 100% SCALING • TOUCH + KVM + MIC)
  // ============================================================================
  const RDP_TARGET_W = 2248;
  const RDP_TARGET_H = 1080;
  const RDP_SCALE_FACTOR = 100;
  const STORAGE_RDP_HOST = "mac_kb_rdp_host";
  const STORAGE_RDP_USER = "mac_kb_rdp_user";
  const STORAGE_RDP_PASS = "mac_kb_rdp_pass";
  const STORAGE_RDP_EDGE = "mac_kb_rdp_edge_mode";

  const EDGE_CYCLE = ["any", "bottom", "right", "left", "top"];
  const EDGE_LABELS = {
    any: "✥ Mọi phía",
    bottom: "⬇ Dưới",
    right: "➡ Phải",
    left: "⬅ Trái",
    top: "⬆ Trên",
  };

  const RDP_SCANCODE_MAP = {
    Escape: 0x01, Digit1: 0x02, Digit2: 0x03, Digit3: 0x04, Digit4: 0x05,
    Digit5: 0x06, Digit6: 0x07, Digit7: 0x08, Digit8: 0x09, Digit9: 0x0a,
    Digit0: 0x0b, Minus: 0x0c, Equal: 0x0d, Backspace: 0x0e, Tab: 0x0f,
    KeyQ: 0x10, KeyW: 0x11, KeyE: 0x12, KeyR: 0x13, KeyT: 0x14,
    KeyY: 0x15, KeyU: 0x16, KeyI: 0x17, KeyO: 0x18, KeyP: 0x19,
    BracketLeft: 0x1a, BracketRight: 0x1b, Enter: 0x1c, ControlLeft: 0x1d,
    KeyA: 0x1e, KeyS: 0x1f, KeyD: 0x20, KeyF: 0x21, KeyG: 0x22,
    KeyH: 0x23, KeyJ: 0x24, KeyK: 0x25, KeyL: 0x26, Semicolon: 0x27,
    Quote: 0x28, Backquote: 0x29, ShiftLeft: 0x2a, Backslash: 0x2b,
    KeyZ: 0x2c, KeyX: 0x2d, KeyC: 0x2e, KeyV: 0x2f, KeyB: 0x30,
    KeyN: 0x31, KeyM: 0x32, Comma: 0x33, Period: 0x34, Slash: 0x35,
    ShiftRight: 0x36, AltLeft: 0x38, Space: 0x39, CapsLock: 0x3a,
    F1: 0x3b, F2: 0x3c, F3: 0x3d, F4: 0x3e, F5: 0x3f, F6: 0x40,
    F7: 0x41, F8: 0x42, F9: 0x43, F10: 0x44, F11: 0x57, F12: 0x58,
    ControlRight: 0xe01d, AltRight: 0xe038, Home: 0xe047, ArrowUp: 0xe048,
    PageUp: 0xe049, ArrowLeft: 0xe04b, ArrowRight: 0xe04d, End: 0xe04f,
    ArrowDown: 0xe050, PageDown: 0xe051, Insert: 0xe052, Delete: 0xe053,
    MetaLeft: 0xe05b, MetaRight: 0xe05c,
  };

  const CHAR_TO_CODE = {
    a: "KeyA", b: "KeyB", c: "KeyC", d: "KeyD", e: "KeyE", f: "KeyF",
    g: "KeyG", h: "KeyH", i: "KeyI", j: "KeyJ", k: "KeyK", l: "KeyL",
    m: "KeyM", n: "KeyN", o: "KeyO", p: "KeyP", q: "KeyQ", r: "KeyR",
    s: "KeyS", t: "KeyT", u: "KeyU", v: "KeyV", w: "KeyW", x: "KeyX",
    y: "KeyY", z: "KeyZ", "0": "Digit0", "1": "Digit1", "2": "Digit2",
    "3": "Digit3", "4": "Digit4", "5": "Digit5", "6": "Digit6",
    "7": "Digit7", "8": "Digit8", "9": "Digit9",
  };

  const remoteViewport = document.getElementById("remote-viewport");
  const remoteStage = document.getElementById("remote-stage");
  const remoteCanvas = document.getElementById("remote-pc-canvas");
  const remoteKvmCursor = document.getElementById("remote-kvm-cursor");
  const remoteCursorImg = document.getElementById("remote-cursor-img");
  const remoteCursorSvg = document.getElementById("remote-cursor-svg");
  const remoteHudPill = document.getElementById("remote-hud-pill");
  const remoteHudBar = document.getElementById("remote-hud-bar");
  const remoteStatusDot = document.getElementById("remote-status-dot");
  const remoteModeMenu = document.getElementById("remote-mode-menu");
  const btnRemoteMic = document.getElementById("btn-remote-mic");
  const btnRemoteKb = document.getElementById("btn-remote-kb");
  const btnRemoteEdge = document.getElementById("btn-remote-edge");
  const btnRemoteZoomReset = document.getElementById("btn-remote-zoom-reset");
  const btnRemoteCfg = document.getElementById("btn-remote-cfg");
  const btnRemoteCollapse = document.getElementById("btn-remote-collapse");
  const remoteSpecialBar = document.getElementById("remote-special-bar");
  const btnRemoteHideKb = document.getElementById("btn-remote-hide-kb");
  const remoteImeInput = document.getElementById("remote-ime-input");
  const remoteLoginOverlay = document.getElementById("remote-login-overlay");
  const rdpHostInput = document.getElementById("rdp-host-input");
  const rdpUserInput = document.getElementById("rdp-user-input");
  const rdpPassInput = document.getElementById("rdp-pass-input");
  const rdpLoginStatus = document.getElementById("rdp-login-status");
  const btnRdpConnect = document.getElementById("btn-rdp-connect");
  const btnRdpDisconnect = document.getElementById("btn-rdp-disconnect");
  const btnRdpSwitchBack = document.getElementById("btn-rdp-switch-back");
  const btnRdpCloseCard = document.getElementById("btn-rdp-close-card");

  let rdpMod = null;
  let rdpModPromise = null;
  let rdpSession = null;
  let rdpConnecting = false;
  let rdpHudExpanded = false;
  let rdpRemoteMenuOpen = false;
  let rdpImeOpen = false;
  let rdpComposing = false;
  let rdpActiveMods = new Set();

  let rdpZoom = 1.0;
  let rdpPanX = 0;
  let rdpPanY = 0;

  let kvmActive = false;
  let localPointerVisible = false;
  let localPointerHideTimer = null;
  let kvmX = RDP_TARGET_W / 2;
  let kvmY = RDP_TARGET_H / 2;
  let kvmMacEdge = "bottom";
  let kvmPhoneEdge = "top";
  let kvmReturnPush = 0;
  let cursorHotspotX = 2;
  let cursorHotspotY = 1;
  let cursorHiddenByServer = false;

  let webSpeechRec = null;
  let voiceListening = false;

  try {
    const sHost = localStorage.getItem(STORAGE_RDP_HOST);
    const sUser = localStorage.getItem(STORAGE_RDP_USER);
    const sPass = localStorage.getItem(STORAGE_RDP_PASS);
    if (sHost && rdpHostInput) rdpHostInput.value = sHost;
    if (sUser && rdpUserInput) rdpUserInput.value = sUser;
    if (sPass && rdpPassInput) rdpPassInput.value = sPass;
  } catch {
    // ignore
  }

  function syncRemoteEdgeLabel() {
    if (btnRemoteEdge) {
      btnRemoteEdge.textContent = EDGE_LABELS[rdpEdgeMode] || EDGE_LABELS.any;
    }
  }
  syncRemoteEdgeLabel();

  function setRemoteHudExpanded(expanded) {
    rdpHudExpanded = Boolean(expanded);
    if (!rdpHudExpanded) rdpRemoteMenuOpen = false;
    if (remoteHudPill) remoteHudPill.classList.toggle("is-hidden", rdpHudExpanded);
    if (remoteHudBar) remoteHudBar.classList.toggle("is-hidden", !rdpHudExpanded);
    if (remoteModeMenu) remoteModeMenu.classList.toggle("is-hidden", !rdpRemoteMenuOpen);
  }

  function setRdpStatus(text, isOk = false) {
    if (!rdpLoginStatus) return;
    if (!text) {
      rdpLoginStatus.textContent = "";
      rdpLoginStatus.classList.add("is-hidden");
      return;
    }
    rdpLoginStatus.textContent = text;
    rdpLoginStatus.classList.toggle("is-ok", Boolean(isOk));
    rdpLoginStatus.classList.remove("is-hidden");
  }

  function syncRdpConnectionUI() {
    const connected = Boolean(rdpSession);
    if (remoteStatusDot) {
      remoteStatusDot.classList.toggle("is-online", connected);
      remoteStatusDot.classList.toggle("is-connecting", rdpConnecting && !connected);
    }
    if (btnRdpConnect) {
      btnRdpConnect.disabled = rdpConnecting;
      btnRdpConnect.textContent = rdpConnecting
        ? "Đang kết nối..."
        : connected
          ? "Kết nối lại"
          : "Kết nối";
    }
    if (btnRdpDisconnect) {
      btnRdpDisconnect.classList.toggle("is-hidden", !connected);
    }
    if (btnRdpCloseCard) {
      btnRdpCloseCard.classList.toggle("is-hidden", !connected);
    }
  }

  function clampRdpPan() {
    if (!remoteViewport || !remoteStage || rdpZoom <= 1.005) {
      rdpZoom = 1.0;
      rdpPanX = 0;
      rdpPanY = 0;
      return;
    }
    const vw = remoteViewport.clientWidth || 1;
    const vh = remoteViewport.clientHeight || 1;
    const sw = remoteStage.offsetWidth * rdpZoom;
    const sh = remoteStage.offsetHeight * rdpZoom;
    const baseLeft = (vw - remoteStage.offsetWidth) / 2;
    const baseTop = (vh - remoteStage.offsetHeight) / 2;
    const minX = Math.min(0, vw - sw - baseLeft);
    const maxX = Math.max(0, -baseLeft);
    const minY = Math.min(0, vh - sh - baseTop);
    const maxY = Math.max(0, -baseTop);
    rdpPanX = Math.max(minX, Math.min(maxX, rdpPanX));
    rdpPanY = Math.max(minY, Math.min(maxY, rdpPanY));
  }

  function applyRdpStageTransform() {
    if (!remoteStage) return;
    clampRdpPan();
    if (rdpZoom <= 1.005) {
      remoteStage.style.transform = "";
      if (btnRemoteZoomReset) btnRemoteZoomReset.classList.add("is-hidden");
    } else {
      remoteStage.style.transform = `translate3d(${rdpPanX.toFixed(1)}px, ${rdpPanY.toFixed(1)}px, 0) scale(${rdpZoom.toFixed(3)})`;
      if (btnRemoteZoomReset) {
        btnRemoteZoomReset.textContent = `${Math.round(rdpZoom * 100)}%`;
        btnRemoteZoomReset.classList.remove("is-hidden");
      }
    }
  }

  function showLocalRemoteCursor(rx, ry, autoHideMs = 1500) {
    kvmX = rx;
    kvmY = ry;
    localPointerVisible = true;
    if (localPointerHideTimer !== null) {
      clearTimeout(localPointerHideTimer);
      localPointerHideTimer = null;
    }
    if (autoHideMs > 0) {
      localPointerHideTimer = setTimeout(() => {
        localPointerHideTimer = null;
        localPointerVisible = false;
        updateOverlayCursorVisual();
      }, autoHideMs);
    }
    updateOverlayCursorVisual();
  }

  function updateOverlayCursorVisual() {
    if (!remoteKvmCursor || !remoteCanvas) return;
    if ((!kvmActive && !localPointerVisible) || cursorHiddenByServer) {
      remoteKvmCursor.classList.add("is-hidden");
      return;
    }
    const cw = remoteCanvas.offsetWidth || RDP_TARGET_W;
    const ch = remoteCanvas.offsetHeight || RDP_TARGET_H;
    const stageScale = cw / (remoteCanvas.width || RDP_TARGET_W);
    const cursorScale = Math.max(0.36, Math.min(1.0, stageScale * 1.18));
    const px =
      (kvmX / (remoteCanvas.width || RDP_TARGET_W)) * cw -
      cursorHotspotX * cursorScale;
    const py =
      (kvmY / (remoteCanvas.height || RDP_TARGET_H)) * ch -
      cursorHotspotY * cursorScale;
    remoteKvmCursor.style.transform = `translate3d(${px.toFixed(1)}px, ${py.toFixed(1)}px, 0) scale(${cursorScale.toFixed(3)})`;
    remoteKvmCursor.classList.remove("is-hidden");
  }

  async function ensureIronRdpLoaded() {
    if (rdpMod) return rdpMod;
    if (!rdpModPromise) {
      rdpModPromise = (async () => {
        const mod = await import("./ironrdp/rdp_client.js");
        const wasmRes = await fetch("./ironrdp/rdp_client_bg.wasm");
        if (!wasmRes.ok) {
          throw new Error(`Không tải được WASM (${wasmRes.status})`);
        }
        const wasmBuf = await wasmRes.arrayBuffer();
        await mod.default({ module_or_path: wasmBuf });
        mod.setup("warn");
        rdpMod = mod;
        return mod;
      })().catch((err) => {
        rdpModPromise = null;
        throw err;
      });
    }
    return rdpModPromise;
  }

  function probeWsOpen(wsUrl, timeoutMs = 950) {
    return new Promise((resolve) => {
      let done = false;
      let sock = null;
      const t0 = performance.now();
      const finish = (ok) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        try {
          if (sock) {
            sock.onopen = null;
            sock.onerror = null;
            sock.onclose = null;
            sock.close();
          }
        } catch {
          // ignore
        }
        resolve({ wsUrl, ok, rtt: performance.now() - t0 });
      };
      const timer = setTimeout(() => finish(false), timeoutMs);
      try {
        sock = new WebSocket(wsUrl);
        sock.onopen = () => finish(true);
        sock.onerror = () => finish(false);
      } catch {
        finish(false);
      }
    });
  }

  async function buildRdpProxyCandidates(pcHost) {
    const pcIp = String(pcHost || "192.168.52.230")
      .trim()
      .replace(/^https?:\/\/|^wss?:\/\//, "")
      .split(":")[0]
      .trim();

    const rawUrls = [];
    // Nếu đang có kênh WebSocket bàn phím mở sẵn tới MacBook -> đưa lên ưu tiên số 1
    if (ws && ws.readyState === WebSocket.OPEN && ws.url) {
      rawUrls.push(ws.url.replace(/\/ws(\?.*)?$/, "/rdp-ws"));
    }
    if (pcIp) {
      rawUrls.push(`ws://${pcIp}:5051`);
    }
    for (const h of resolveCandidateHosts()) {
      const cleanH = h.replace(/^https?:\/\/|^wss?:\/\//, "").split("/")[0];
      if (cleanH) rawUrls.push(`ws://${cleanH}/rdp-ws`);
    }

    const uniqueUrls = Array.from(new Set(rawUrls));
    if (uniqueUrls.length === 0) return [];

    // Đua mở WebSocket thật song song: cổng nào mở ngay trong vài mili-giây sẽ thắng tức thì,
    // loại bỏ hoàn toàn cổng bị tường lửa giữ gói tin (tránh treo chờ 2-3 phút của TCP SYN retry)
    try {
      const fastest = await Promise.any(
        uniqueUrls.map(
          (u) =>
            new Promise((res, rej) => {
              probeWsOpen(u, 1100).then((r) => (r.ok ? res(r.wsUrl) : rej()));
            })
        )
      );
      return [fastest];
    } catch {
      return uniqueUrls.slice(0, 1);
    }
  }

  function formatIronRdpError(err) {
    if (!err) return "Lỗi kết nối không xác định";
    try {
      if (typeof err.kind === "function") {
        const k = err.kind();
        if (k === 1) return "Sai mật khẩu Windows PC.";
        if (k === 2) return "Đăng nhập thất bại (kiểm tra tài khoản / mật khẩu PC).";
        if (k === 3) return "Tài khoản không có quyền Remote Desktop.";
        if (k === 5) return "Không kết nối được cổng Gateway trên Wi-Fi.";
      }
      if (typeof err.backtrace === "function") {
        const bt = String(err.backtrace() || "");
        const firstLine = bt.split("\n")[0].trim();
        if (firstLine) return firstLine;
      }
    } catch {
      // ignore
    }
    return String(err.message || err);
  }

  function applyRdpDeviceEvents(events) {
    if (!rdpSession || !rdpMod || !events || events.length === 0) return;
    try {
      const tx = new rdpMod.InputTransaction();
      for (const ev of events) {
        if (ev) tx.addEvent(ev);
      }
      rdpSession.applyInputs(tx);
    } catch {
      // ignore transient input error
    }
  }

  function rdpSendMouseMove(rx, ry, autoHideMs = 0) {
    if (!rdpSession || !rdpMod) return;
    const cx = Math.max(0, Math.min((remoteCanvas.width || RDP_TARGET_W) - 1, Math.round(rx)));
    const cy = Math.max(0, Math.min((remoteCanvas.height || RDP_TARGET_H) - 1, Math.round(ry)));
    if (!kvmActive) {
      showLocalRemoteCursor(cx, cy, autoHideMs);
    }
    applyRdpDeviceEvents([rdpMod.DeviceEvent.mouseMove(cx, cy)]);
  }

  function rdpSendMouseClick(rx, ry, button = 0, count = 1) {
    if (!rdpSession || !rdpMod) return;
    const cx = Math.max(0, Math.min((remoteCanvas.width || RDP_TARGET_W) - 1, Math.round(rx)));
    const cy = Math.max(0, Math.min((remoteCanvas.height || RDP_TARGET_H) - 1, Math.round(ry)));
    if (!kvmActive) {
      showLocalRemoteCursor(cx, cy, 1400);
    }
    const evs = [rdpMod.DeviceEvent.mouseMove(cx, cy)];
    for (let i = 0; i < count; i += 1) {
      evs.push(rdpMod.DeviceEvent.mouseButtonPressed(button));
      evs.push(rdpMod.DeviceEvent.mouseButtonReleased(button));
    }
    applyRdpDeviceEvents(evs);
  }

  function rdpSendScancodeTap(codeName, withActiveMods = true) {
    if (!rdpSession || !rdpMod) return;
    const sc = RDP_SCANCODE_MAP[codeName];
    if (sc === undefined) return;
    const evs = [];
    const modsToUse = withActiveMods ? Array.from(rdpActiveMods) : [];
    for (const m of modsToUse) {
      const msc = RDP_SCANCODE_MAP[m];
      if (msc !== undefined) evs.push(rdpMod.DeviceEvent.keyPressed(msc));
    }
    evs.push(rdpMod.DeviceEvent.keyPressed(sc));
    evs.push(rdpMod.DeviceEvent.keyReleased(sc));
    for (let i = modsToUse.length - 1; i >= 0; i -= 1) {
      const msc = RDP_SCANCODE_MAP[modsToUse[i]];
      if (msc !== undefined) evs.push(rdpMod.DeviceEvent.keyReleased(msc));
    }
    applyRdpDeviceEvents(evs);
    if (withActiveMods && rdpActiveMods.size > 0) {
      rdpActiveMods.clear();
      syncRdpModButtons();
    }
  }

  function injectUnicodeTextToRdp(text) {
    if (!rdpSession || !rdpMod || !text) return;
    const str = String(text);
    if (rdpActiveMods.size > 0 && str.length === 1) {
      const lower = str.toLowerCase();
      if (CHAR_TO_CODE[lower]) {
        rdpSendScancodeTap(CHAR_TO_CODE[lower], true);
        return;
      }
    }
    const chars = Array.from(str);
    const BATCH = 24;
    for (let i = 0; i < chars.length; i += BATCH) {
      const slice = chars.slice(i, i + BATCH);
      const evs = [];
      for (const ch of slice) {
        if (ch === "\r") continue;
        if (ch === "\n") {
          evs.push(rdpMod.DeviceEvent.keyPressed(RDP_SCANCODE_MAP.Enter));
          evs.push(rdpMod.DeviceEvent.keyReleased(RDP_SCANCODE_MAP.Enter));
        } else if (ch === "\t") {
          evs.push(rdpMod.DeviceEvent.keyPressed(RDP_SCANCODE_MAP.Tab));
          evs.push(rdpMod.DeviceEvent.keyReleased(RDP_SCANCODE_MAP.Tab));
        } else {
          evs.push(rdpMod.DeviceEvent.unicodePressed(ch));
          evs.push(rdpMod.DeviceEvent.unicodeReleased(ch));
        }
      }
      applyRdpDeviceEvents(evs);
    }
  }

  async function pasteLocalClipboardToRdp() {
    if (!rdpSession || !rdpMod) return;
    let txt = "";
    try {
      if (hasAndroidBridge && typeof window.AndroidBridge.getClipboardText === "function") {
        txt = String(window.AndroidBridge.getClipboardText() || "");
      } else if (navigator.clipboard && typeof navigator.clipboard.readText === "function") {
        txt = await navigator.clipboard.readText();
      }
    } catch {
      // ignore
    }
    if (txt) {
      try {
        const cd = new rdpMod.ClipboardData();
        cd.addText("text/plain", txt);
        await rdpSession.onClipboardPaste(cd);
      } catch {
        injectUnicodeTextToRdp(txt);
        return;
      }
    }
    applyRdpDeviceEvents([
      rdpMod.DeviceEvent.keyPressed(RDP_SCANCODE_MAP.ControlLeft),
      rdpMod.DeviceEvent.keyPressed(RDP_SCANCODE_MAP.KeyV),
      rdpMod.DeviceEvent.keyReleased(RDP_SCANCODE_MAP.KeyV),
      rdpMod.DeviceEvent.keyReleased(RDP_SCANCODE_MAP.ControlLeft),
    ]);
  }

  async function connectRdpSession() {
    if (rdpConnecting || !remoteCanvas) return;
    const rawHost = (rdpHostInput ? rdpHostInput.value : "192.168.52.230").trim() || "192.168.52.230";
    const rawUser = (rdpUserInput ? rdpUserInput.value : "DESKTOP-4LTT2HE\\User").trim() || "DESKTOP-4LTT2HE\\User";
    const rawPass = rdpPassInput ? rdpPassInput.value : "";

    if (!rawPass) {
      if (remoteLoginOverlay) remoteLoginOverlay.classList.remove("is-hidden");
      setRdpStatus("Nhập mật khẩu Windows PC để kết nối.", false);
      if (rdpPassInput) rdpPassInput.focus();
      return;
    }

    if (rdpSession) {
      try {
        rdpSession.shutdown();
      } catch {
        // ignore
      }
      rdpSession = null;
    }

    rdpConnecting = true;
    syncRdpConnectionUI();
    setRdpStatus("Đang khởi tạo kết nối 2248×1080 (100%)...", true);

    try {
      const mod = await ensureIronRdpLoaded();
      const dest = rawHost.includes(":") ? rawHost : `${rawHost}:3389`;
      let domain = "";
      let username = rawUser;
      if (rawUser.includes("\\")) {
        const parts = rawUser.split("\\");
        domain = parts[0] === "." ? "" : parts[0];
        username = parts.slice(1).join("\\") || rawUser;
      }

      const proxies = await buildRdpProxyCandidates(rawHost);
      if (proxies.length === 0) {
        throw new Error("Chưa có địa chỉ IP PC hoặc MacBook.");
      }

      let connectedSession = null;
      let lastErr = null;

      for (const proxyWsUrl of proxies) {
        try {
          const builder = new mod.SessionBuilder();
          builder.username(username);
          if (domain) builder.serverDomain(domain);
          builder.password(rawPass);
          builder.destination(dest);
          builder.proxyAddress(proxyWsUrl);
          builder.authToken("local");
          builder.desktopSize(new mod.DesktopSize(RDP_TARGET_W, RDP_TARGET_H));
          builder.renderCanvas(remoteCanvas);
          builder.extension(new mod.Extension("enable_credssp", true));
          builder.extension(new mod.Extension("display_control", true));
          builder.extension(new mod.Extension("enable_server_pointer", true));

          builder.remoteClipboardChangedCallback((clipData) => {
            try {
              const items = clipData.items();
              for (const item of items) {
                if (item.mimeType() === "text/plain") {
                  const val = String(item.value() || "");
                  if (val) {
                    if (
                      hasAndroidBridge &&
                      typeof window.AndroidBridge.setClipboardText === "function"
                    ) {
                      window.AndroidBridge.setClipboardText(val);
                    } else if (navigator.clipboard && navigator.clipboard.writeText) {
                      navigator.clipboard.writeText(val).catch(() => {});
                    }
                  }
                }
              }
            } catch {
              // ignore
            }
          });
          builder.forceClipboardUpdateCallback(() => {});

          builder.setCursorStyleCallbackContext(remoteCanvas);
          builder.setCursorStyleCallback(function (kind, data, hx, hy) {
            remoteCanvas.style.cursor = "none";
            if (kind === "hidden" || kind === "none") {
              cursorHiddenByServer = true;
            } else if (kind === "url" && typeof data === "string" && data.startsWith("data:")) {
              cursorHiddenByServer = false;
              cursorHotspotX = Number(hx) || 0;
              cursorHotspotY = Number(hy) || 0;
              if (remoteCursorImg) {
                remoteCursorImg.src = data;
                remoteCursorImg.classList.remove("is-hidden");
              }
              if (remoteCursorSvg) remoteCursorSvg.classList.add("is-hidden");
            } else {
              cursorHiddenByServer = false;
              cursorHotspotX = 2;
              cursorHotspotY = 1;
              if (remoteCursorImg) remoteCursorImg.classList.add("is-hidden");
              if (remoteCursorSvg) remoteCursorSvg.classList.remove("is-hidden");
            }
            updateOverlayCursorVisual();
          });

          connectedSession = await builder.connect();
          break;
        } catch (err) {
          lastErr = err;
          // Nếu sai mật khẩu thì dừng ngay không thử cổng kế tiếp
          if (err && typeof err.kind === "function" && (err.kind() === 1 || err.kind() === 2)) {
            break;
          }
        }
      }

      if (!connectedSession) {
        throw lastErr || new Error("Không kết nối được tới PC.");
      }

      rdpSession = connectedSession;
      try {
        localStorage.setItem(STORAGE_RDP_HOST, rawHost);
        localStorage.setItem(STORAGE_RDP_USER, rawUser);
        localStorage.setItem(STORAGE_RDP_PASS, rawPass);
      } catch {
        // ignore
      }

      const ds = rdpSession.desktopSize();
      remoteCanvas.width = ds.width || RDP_TARGET_W;
      remoteCanvas.height = ds.height || RDP_TARGET_H;

      rdpConnecting = false;
      setRdpStatus("", true);
      if (remoteLoginOverlay) remoteLoginOverlay.classList.add("is-hidden");
      setRemoteHudExpanded(false);
      syncRdpConnectionUI();
      pushKvmConfigToServer();

      // Chỉ gửi lệnh resize nếu độ phân giải ban đầu chưa khớp 2248x1080 (tránh DeactivateAll gây trễ màn hình)
      if (ds.width !== RDP_TARGET_W || ds.height !== RDP_TARGET_H) {
        setTimeout(() => {
          if (rdpSession) {
            try {
              rdpSession.resize(
                RDP_TARGET_W,
                RDP_TARGET_H,
                RDP_SCALE_FACTOR,
                RDP_TARGET_W,
                RDP_TARGET_H
              );
            } catch {
              // ignore
            }
          }
        }, 250);
      }

      rdpSession
        .run()
        .then(() => {
          rdpSession = null;
          syncRdpConnectionUI();
          if (kbLayout === "remote" && remoteLoginOverlay) {
            setRdpStatus("Phiên Remote PC đã ngắt.", false);
            remoteLoginOverlay.classList.remove("is-hidden");
          }
        })
        .catch((runErr) => {
          rdpSession = null;
          syncRdpConnectionUI();
          if (kbLayout === "remote" && remoteLoginOverlay) {
            setRdpStatus(formatIronRdpError(runErr), false);
            remoteLoginOverlay.classList.remove("is-hidden");
          }
        });
    } catch (err) {
      rdpConnecting = false;
      rdpSession = null;
      syncRdpConnectionUI();
      if (remoteLoginOverlay) remoteLoginOverlay.classList.remove("is-hidden");
      setRdpStatus(formatIronRdpError(err), false);
    }
  }

  function disconnectRdpSession() {
    if (rdpSession) {
      try {
        rdpSession.shutdown();
      } catch {
        // ignore
      }
      rdpSession = null;
    }
    rdpConnecting = false;
    kvmActive = false;
    updateOverlayCursorVisual();
    syncRdpConnectionUI();
    setRdpStatus("Đã ngắt kết nối.", false);
    if (remoteLoginOverlay) remoteLoginOverlay.classList.remove("is-hidden");
  }

  // ── Xử lý Chuột Bluetooth xuyên màn hình từ MacBook (MacKvmBridge) ──
  handleKvmServerMessage = (msg) => {
    if (!msg) return;
    if (msg.type === "kvm_released") {
      kvmActive = false;
      kvmReturnPush = 0;
      updateOverlayCursorVisual();
      if (rdpSession) {
        try {
          rdpSession.releaseAllInputs();
        } catch {
          // ignore
        }
      }
      return;
    }

    if (kbLayout !== "remote") {
      sendPayload({ type: "kvm_return" });
      return;
    }

    const cw = remoteCanvas ? remoteCanvas.width || RDP_TARGET_W : RDP_TARGET_W;
    const ch = remoteCanvas ? remoteCanvas.height || RDP_TARGET_H : RDP_TARGET_H;

    if (msg.type === "kvm_enter") {
      kvmActive = true;
      kvmMacEdge = msg.mac_edge || "bottom";
      kvmPhoneEdge = msg.phone_edge || "top";
      kvmReturnPush = 0;
      const r = Math.max(0.02, Math.min(0.98, Number(msg.ratio) || 0.5));
      if (kvmPhoneEdge === "top") {
        kvmX = Math.round(r * (cw - 1));
        kvmY = 4;
      } else if (kvmPhoneEdge === "bottom") {
        kvmX = Math.round(r * (cw - 1));
        kvmY = ch - 5;
      } else if (kvmPhoneEdge === "left") {
        kvmX = 4;
        kvmY = Math.round(r * (ch - 1));
      } else {
        kvmX = cw - 5;
        kvmY = Math.round(r * (ch - 1));
      }
      updateOverlayCursorVisual();
      rdpSendMouseMove(kvmX, kvmY);
      return;
    }

    if (msg.type === "kvm_mouse") {
      if (!kvmActive) kvmActive = true;
      if (msg.ev === "move") {
        const scale = 1.38;
        const dx = (Number(msg.dx) || 0) * scale;
        const dy = (Number(msg.dy) || 0) * scale;

        let pushingOut = false;
        if (kvmPhoneEdge === "top" && kvmY <= 2 && dy < 0) {
          kvmReturnPush += -dy;
          pushingOut = true;
        } else if (kvmPhoneEdge === "bottom" && kvmY >= ch - 3 && dy > 0) {
          kvmReturnPush += dy;
          pushingOut = true;
        } else if (kvmPhoneEdge === "left" && kvmX <= 2 && dx < 0) {
          kvmReturnPush += -dx;
          pushingOut = true;
        } else if (kvmPhoneEdge === "right" && kvmX >= cw - 3 && dx > 0) {
          kvmReturnPush += dx;
          pushingOut = true;
        }

        if (pushingOut && kvmReturnPush >= 18) {
          const exitRatio =
            kvmPhoneEdge === "top" || kvmPhoneEdge === "bottom"
              ? kvmX / Math.max(1, cw)
              : kvmY / Math.max(1, ch);
          kvmActive = false;
          kvmReturnPush = 0;
          updateOverlayCursorVisual();
          if (rdpSession) {
            try {
              rdpSession.releaseAllInputs();
            } catch {
              // ignore
            }
          }
          sendPayload({
            type: "kvm_return",
            mac_edge: kvmMacEdge,
            ratio: +Math.max(0.02, Math.min(0.98, exitRatio)).toFixed(4),
          });
          return;
        }

        kvmX = Math.max(0, Math.min(cw - 1, kvmX + dx));
        kvmY = Math.max(0, Math.min(ch - 1, kvmY + dy));
        if (!pushingOut && kvmX > 6 && kvmX < cw - 7 && kvmY > 6 && kvmY < ch - 7) {
          kvmReturnPush = 0;
        }
        updateOverlayCursorVisual();
        rdpSendMouseMove(kvmX, kvmY);
      } else if (msg.ev === "down" && rdpMod) {
        applyRdpDeviceEvents([rdpMod.DeviceEvent.mouseButtonPressed(Number(msg.btn) || 0)]);
      } else if (msg.ev === "up" && rdpMod) {
        applyRdpDeviceEvents([rdpMod.DeviceEvent.mouseButtonReleased(Number(msg.btn) || 0)]);
      } else if (msg.ev === "wheel" && rdpMod) {
        const unit = msg.unit === "px" ? 0 : 1;
        const sy = Number(msg.sy) || 0;
        const sx = Number(msg.sx) || 0;
        const evs = [];
        if (sy !== 0) evs.push(rdpMod.DeviceEvent.wheelRotations(true, sy, unit));
        if (sx !== 0) evs.push(rdpMod.DeviceEvent.wheelRotations(false, -sx, unit));
        applyRdpDeviceEvents(evs);
      }
    }
  };

  // ── Chạm cảm ứng trực tiếp (Direct Touch chuẩn Microsoft Remote Desktop) + Chuột gắn trực tiếp ──
  function clientToRemoteCoords(clientX, clientY) {
    if (!remoteCanvas) return { x: 0, y: 0 };
    const r = remoteCanvas.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) return { x: 0, y: 0 };
    const cw = remoteCanvas.width || RDP_TARGET_W;
    const ch = remoteCanvas.height || RDP_TARGET_H;
    const x = Math.max(0, Math.min(cw - 1, Math.round(((clientX - r.left) / r.width) * cw)));
    const y = Math.max(0, Math.min(ch - 1, Math.round(((clientY - r.top) / r.height) * ch)));
    return { x, y };
  }

  if (remoteViewport && remoteCanvas) {
    let rTouchMode = "none"; // "single" | "drag" | "two"
    let rStartX = 0;
    let rStartY = 0;
    let rLastX = 0;
    let rLastY = 0;
    let rMoved = false;
    let rLongFired = false;
    let rLongTimer = null;
    let rLastTapAt = 0;
    let rLastTapRx = 0;
    let rLastTapRy = 0;
    let rPinchStartDist = 0;
    let rPinchStartZoom = 1.0;
    let rTwoLastMidX = 0;
    let rTwoLastMidY = 0;
    let rScrollAccY = 0;
    let rScrollAccX = 0;

    const clearRdpLongTimer = () => {
      if (rLongTimer !== null) {
        clearTimeout(rLongTimer);
        rLongTimer = null;
      }
    };

    remoteViewport.addEventListener(
      "touchstart",
      (e) => {
        if (rdpHudExpanded) {
          setRemoteHudExpanded(false);
        }
        if (!rdpSession) return;
        e.preventDefault();

        if (e.touches.length >= 2) {
          clearRdpLongTimer();
          if (rTouchMode === "drag" && rdpMod) {
            applyRdpDeviceEvents([rdpMod.DeviceEvent.mouseButtonReleased(0)]);
          }
          rTouchMode = "two";
          const t0 = e.touches[0];
          const t1 = e.touches[1];
          rPinchStartDist = Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY);
          rPinchStartZoom = rdpZoom;
          rTwoLastMidX = (t0.clientX + t1.clientX) / 2;
          rTwoLastMidY = (t0.clientY + t1.clientY) / 2;
          rScrollAccY = 0;
          rScrollAccX = 0;
          return;
        }

        if (e.touches.length === 1) {
          const t = e.touches[0];
          rTouchMode = "single";
          rStartX = t.clientX;
          rStartY = t.clientY;
          rLastX = t.clientX;
          rLastY = t.clientY;
          rMoved = false;
          rLongFired = false;
          clearRdpLongTimer();

          rLongTimer = setTimeout(() => {
            rLongTimer = null;
            if (rTouchMode === "single" && !rMoved) {
              rLongFired = true;
              triggerHaptic(15);
            }
          }, 270);
        }
      },
      { passive: false }
    );

    remoteViewport.addEventListener(
      "touchmove",
      (e) => {
        if (!rdpSession) return;
        e.preventDefault();

        if (rTouchMode === "two" && e.touches.length >= 2) {
          const t0 = e.touches[0];
          const t1 = e.touches[1];
          const dist = Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY);
          const midX = (t0.clientX + t1.clientX) / 2;
          const midY = (t0.clientY + t1.clientY) / 2;
          const dMidX = midX - rTwoLastMidX;
          const dMidY = midY - rTwoLastMidY;
          rTwoLastMidX = midX;
          rTwoLastMidY = midY;

          if (Math.abs(dist - rPinchStartDist) > 24) {
            const nextZoom = Math.max(
              1.0,
              Math.min(3.5, rPinchStartZoom * (dist / Math.max(20, rPinchStartDist)))
            );
            rdpZoom = nextZoom;
            rdpPanX += dMidX;
            rdpPanY += dMidY;
            applyRdpStageTransform();
          } else if (rdpZoom > 1.03) {
            rdpPanX += dMidX;
            rdpPanY += dMidY;
            applyRdpStageTransform();
          } else if (rdpMod) {
            rScrollAccY += dMidY * 1.65;
            rScrollAccX += dMidX * 1.35;
            const py = Math.trunc(rScrollAccY);
            const px = Math.trunc(rScrollAccX);
            const evs = [];
            if (Math.abs(py) >= 2) {
              rScrollAccY -= py;
              evs.push(rdpMod.DeviceEvent.wheelRotations(true, py, 0));
            }
            if (Math.abs(px) >= 4) {
              rScrollAccX -= px;
              evs.push(rdpMod.DeviceEvent.wheelRotations(false, -px, 0));
            }
            if (evs.length > 0) applyRdpDeviceEvents(evs);
          }
          return;
        }

        if (e.touches.length === 1 && (rTouchMode === "single" || rTouchMode === "drag")) {
          const t = e.touches[0];
          const distFromStart = Math.hypot(t.clientX - rStartX, t.clientY - rStartY);
          const dx = t.clientX - rLastX;
          const dy = t.clientY - rLastY;
          rLastX = t.clientX;
          rLastY = t.clientY;

          if (!rMoved && distFromStart > 9) {
            rMoved = true;
            clearRdpLongTimer();
            if (rLongFired && rdpMod) {
              // Ấn giữ + kéo lướt -> Bôi đen văn bản / Kéo thả cửa sổ trên Windows PC
              rTouchMode = "drag";
              const startPt = clientToRemoteCoords(rStartX, rStartY);
              applyRdpDeviceEvents([
                rdpMod.DeviceEvent.mouseMove(startPt.x, startPt.y),
                rdpMod.DeviceEvent.mouseButtonPressed(0),
              ]);
            }
          }

          if (rTouchMode === "drag") {
            const pt = clientToRemoteCoords(t.clientX, t.clientY);
            rdpSendMouseMove(pt.x, pt.y, 1400);
          } else if (rMoved) {
            if (rdpZoom > 1.03) {
              rdpPanX += dx;
              rdpPanY += dy;
              applyRdpStageTransform();
            } else {
              const pt = clientToRemoteCoords(t.clientX, t.clientY);
              rdpSendMouseMove(pt.x, pt.y, 1400);
            }
          }
        }
      },
      { passive: false }
    );

    const handleRdpTouchEnd = (e) => {
      clearRdpLongTimer();
      if (!rdpSession) {
        rTouchMode = "none";
        return;
      }

      if (rTouchMode === "drag") {
        if (e.touches.length === 0) {
          if (rdpMod) {
            applyRdpDeviceEvents([rdpMod.DeviceEvent.mouseButtonReleased(0)]);
          }
          rTouchMode = "none";
        }
        return;
      }

      if (rTouchMode === "single" && e.touches.length === 0) {
        const pt = clientToRemoteCoords(rLastX, rLastY);
        if (rLongFired && !rMoved) {
          // Ấn giữ tại chỗ -> Chuột phải chuẩn Microsoft Remote Desktop
          rdpSendMouseClick(pt.x, pt.y, 2, 1);
        } else if (!rMoved) {
          const now = performance.now();
          if (
            now - rLastTapAt < 320 &&
            Math.hypot(pt.x - rLastTapRx, pt.y - rLastTapRy) < 28
          ) {
            rdpSendMouseClick(rLastTapRx, rLastTapRy, 0, 1);
            rLastTapAt = 0;
          } else {
            rdpSendMouseClick(pt.x, pt.y, 0, 1);
            rLastTapAt = now;
            rLastTapRx = pt.x;
            rLastTapRy = pt.y;
          }
        }
        rTouchMode = "none";
      } else if (e.touches.length === 0) {
        rTouchMode = "none";
      }
    };

    remoteViewport.addEventListener("touchend", handleRdpTouchEnd, { passive: false });
    remoteViewport.addEventListener("touchcancel", handleRdpTouchEnd, { passive: false });

    // Hỗ trợ cả chuột vật lý gắn trực tiếp vào điện thoại / trình duyệt
    remoteViewport.addEventListener("pointermove", (e) => {
      if (e.pointerType !== "mouse" || !rdpSession) return;
      const pt = clientToRemoteCoords(e.clientX, e.clientY);
      rdpSendMouseMove(pt.x, pt.y);
    });

    remoteViewport.addEventListener("pointerdown", (e) => {
      if (e.pointerType !== "mouse" || !rdpSession || !rdpMod) return;
      e.preventDefault();
      remoteCanvas.focus();
      const pt = clientToRemoteCoords(e.clientX, e.clientY);
      applyRdpDeviceEvents([
        rdpMod.DeviceEvent.mouseMove(pt.x, pt.y),
        rdpMod.DeviceEvent.mouseButtonPressed(e.button),
      ]);
    });

    remoteViewport.addEventListener("pointerup", (e) => {
      if (e.pointerType !== "mouse" || !rdpSession || !rdpMod) return;
      e.preventDefault();
      applyRdpDeviceEvents([rdpMod.DeviceEvent.mouseButtonReleased(e.button)]);
    });

    remoteViewport.addEventListener(
      "wheel",
      (e) => {
        if (!rdpSession || !rdpMod) return;
        e.preventDefault();
        const evs = [];
        if (e.deltaY !== 0) {
          evs.push(rdpMod.DeviceEvent.wheelRotations(true, e.deltaY > 0 ? -1 : 1, 1));
        }
        if (e.deltaX !== 0) {
          evs.push(rdpMod.DeviceEvent.wheelRotations(false, e.deltaX > 0 ? -1 : 1, 1));
        }
        applyRdpDeviceEvents(evs);
      },
      { passive: false }
    );
  }

  // ── Bàn phím vật lý / Bàn phím ảo điện thoại & Microphone Tiếng Việt ──
  if (remoteCanvas) {
    remoteCanvas.addEventListener("keydown", (e) => {
      if (!rdpSession || !rdpMod || kbLayout !== "remote") return;
      if (document.activeElement === rdpHostInput || document.activeElement === rdpUserInput || document.activeElement === rdpPassInput) {
        return;
      }
      const sc = RDP_SCANCODE_MAP[e.code];
      if (sc !== undefined) {
        e.preventDefault();
        applyRdpDeviceEvents([rdpMod.DeviceEvent.keyPressed(sc)]);
      }
    });

    remoteCanvas.addEventListener("keyup", (e) => {
      if (!rdpSession || !rdpMod || kbLayout !== "remote") return;
      const sc = RDP_SCANCODE_MAP[e.code];
      if (sc !== undefined) {
        e.preventDefault();
        applyRdpDeviceEvents([rdpMod.DeviceEvent.keyReleased(sc)]);
      }
    });
  }

  function syncRdpModButtons() {
    if (!remoteSpecialBar) return;
    remoteSpecialBar.querySelectorAll("[data-rdp-mod]").forEach((btn) => {
      btn.classList.toggle("is-active", rdpActiveMods.has(btn.dataset.rdpMod));
    });
  }

  function openRemoteSoftKeyboard() {
    if (!remoteImeInput) return;
    rdpImeOpen = true;
    remoteImeInput.value = "\u200B";
    remoteImeInput.focus();
    if (btnRemoteKb) btnRemoteKb.classList.add("is-active");
    if (remoteSpecialBar) remoteSpecialBar.classList.remove("is-hidden");
  }

  function closeRemoteSoftKeyboard() {
    rdpImeOpen = false;
    if (remoteImeInput) remoteImeInput.blur();
    if (btnRemoteKb) btnRemoteKb.classList.remove("is-active");
    if (remoteSpecialBar) remoteSpecialBar.classList.add("is-hidden");
  }

  if (remoteImeInput) {
    remoteImeInput.value = "\u200B";
    remoteImeInput.addEventListener("compositionstart", () => {
      rdpComposing = true;
    });
    remoteImeInput.addEventListener("compositionend", () => {
      rdpComposing = false;
      flushRemoteImeValue();
    });
    remoteImeInput.addEventListener("input", () => {
      if (!rdpComposing) {
        flushRemoteImeValue();
      }
    });
    remoteImeInput.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && remoteImeInput.value.length <= 1) {
        e.preventDefault();
        rdpSendScancodeTap("Backspace", true);
        remoteImeInput.value = "\u200B";
      } else if (e.key === "Enter") {
        e.preventDefault();
        rdpSendScancodeTap("Enter", true);
        remoteImeInput.value = "\u200B";
      }
    });
    remoteImeInput.addEventListener("blur", () => {
      if (rdpImeOpen) {
        setTimeout(() => {
          if (document.activeElement !== remoteImeInput) {
            rdpImeOpen = false;
            if (btnRemoteKb) btnRemoteKb.classList.remove("is-active");
            if (remoteSpecialBar) remoteSpecialBar.classList.add("is-hidden");
          }
        }, 180);
      }
    });
  }

  function flushRemoteImeValue() {
    if (!remoteImeInput) return;
    const val = remoteImeInput.value;
    if (val === "") {
      rdpSendScancodeTap("Backspace", true);
      remoteImeInput.value = "\u200B";
      return;
    }
    const clean = val.startsWith("\u200B") ? val.slice(1) : val;
    remoteImeInput.value = "\u200B";
    if (clean) {
      injectUnicodeTextToRdp(clean);
    }
  }

  // Nhận văn bản đọc từ Microphone (Android SpeechRecognizer hoặc Web Speech API) -> gõ thẳng vào Windows PC
  window.__onRemoteVoiceText = (spokenText) => {
    voiceListening = false;
    if (btnRemoteMic) btnRemoteMic.classList.remove("is-recording");
    const txt = String(spokenText || "").trim();
    if (!txt) return;
    injectUnicodeTextToRdp(txt + " ");
  };

  window.__onRemoteVoiceState = (active) => {
    voiceListening = Boolean(active);
    if (btnRemoteMic) btnRemoteMic.classList.toggle("is-recording", voiceListening);
  };

  function toggleRemoteMicrophone() {
    triggerHaptic(12);
    if (hasAndroidBridge && typeof window.AndroidBridge.startVoiceInput === "function") {
      try {
        window.AndroidBridge.startVoiceInput("vi-VN");
        return;
      } catch {
        // fallback Web Speech
      }
    }

    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      openRemoteSoftKeyboard();
      return;
    }

    if (voiceListening && webSpeechRec) {
      try {
        webSpeechRec.stop();
      } catch {
        // ignore
      }
      voiceListening = false;
      if (btnRemoteMic) btnRemoteMic.classList.remove("is-recording");
      return;
    }

    try {
      webSpeechRec = new SpeechRec();
      webSpeechRec.lang = "vi-VN";
      webSpeechRec.interimResults = false;
      webSpeechRec.continuous = false;
      webSpeechRec.onstart = () => {
        voiceListening = true;
        if (btnRemoteMic) btnRemoteMic.classList.add("is-recording");
      };
      webSpeechRec.onresult = (ev) => {
        let out = "";
        for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
          if (ev.results[i].isFinal) {
            out += ev.results[i][0].transcript;
          }
        }
        if (out.trim()) {
          injectUnicodeTextToRdp(out.trim() + " ");
        }
      };
      webSpeechRec.onend = () => {
        voiceListening = false;
        if (btnRemoteMic) btnRemoteMic.classList.remove("is-recording");
      };
      webSpeechRec.onerror = () => {
        voiceListening = false;
        if (btnRemoteMic) btnRemoteMic.classList.remove("is-recording");
      };
      webSpeechRec.start();
    } catch {
      openRemoteSoftKeyboard();
    }
  }

  // ── Gắn sự kiện thanh HUD tối giản & Hộp đăng nhập ──
  if (remoteHudPill) {
    remoteHudPill.addEventListener("click", (e) => {
      e.stopPropagation();
      triggerHaptic(8);
      setRemoteHudExpanded(true);
    });
  }

  if (btnRemoteCollapse) {
    btnRemoteCollapse.addEventListener("click", (e) => {
      e.stopPropagation();
      setRemoteHudExpanded(false);
    });
  }

  const btnToggleRemoteMenu = document.querySelector('[data-action="toggle-remote-menu"]');
  if (btnToggleRemoteMenu) {
    btnToggleRemoteMenu.addEventListener("click", (e) => {
      e.stopPropagation();
      triggerHaptic(8);
      rdpRemoteMenuOpen = !rdpRemoteMenuOpen;
      if (remoteModeMenu) remoteModeMenu.classList.toggle("is-hidden", !rdpRemoteMenuOpen);
    });
  }

  if (btnRemoteMic) {
    btnRemoteMic.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleRemoteMicrophone();
    });
  }

  if (btnRemoteKb) {
    btnRemoteKb.addEventListener("click", (e) => {
      e.stopPropagation();
      triggerHaptic(8);
      if (rdpImeOpen) {
        closeRemoteSoftKeyboard();
      } else {
        setRemoteHudExpanded(false);
        openRemoteSoftKeyboard();
      }
    });
  }

  if (btnRemoteEdge) {
    btnRemoteEdge.addEventListener("click", (e) => {
      e.stopPropagation();
      triggerHaptic(8);
      const idx = EDGE_CYCLE.indexOf(rdpEdgeMode);
      rdpEdgeMode = EDGE_CYCLE[(idx + 1) % EDGE_CYCLE.length];
      try {
        localStorage.setItem(STORAGE_RDP_EDGE, rdpEdgeMode);
      } catch {
        // ignore
      }
      syncRemoteEdgeLabel();
      pushKvmConfigToServer();
    });
  }

  if (btnRemoteZoomReset) {
    btnRemoteZoomReset.addEventListener("click", (e) => {
      e.stopPropagation();
      rdpZoom = 1.0;
      rdpPanX = 0;
      rdpPanY = 0;
      applyRdpStageTransform();
    });
  }

  if (btnRemoteCfg) {
    btnRemoteCfg.addEventListener("click", (e) => {
      e.stopPropagation();
      setRemoteHudExpanded(false);
      syncRdpConnectionUI();
      if (remoteLoginOverlay) remoteLoginOverlay.classList.remove("is-hidden");
    });
  }

  if (remoteSpecialBar) {
    remoteSpecialBar.addEventListener("pointerdown", (e) => {
      const target = e.target.closest("button");
      if (!target) return;
      e.preventDefault();
      e.stopPropagation();
      triggerHaptic(8);

      if (target.id === "btn-remote-hide-kb") {
        closeRemoteSoftKeyboard();
        return;
      }
      if (target.dataset.rdpCombo === "ctrl-v") {
        void pasteLocalClipboardToRdp();
        return;
      }
      if (target.dataset.rdpMod) {
        const mod = target.dataset.rdpMod;
        if (rdpActiveMods.has(mod)) {
          rdpActiveMods.delete(mod);
        } else {
          rdpActiveMods.add(mod);
        }
        syncRdpModButtons();
        return;
      }
      if (target.dataset.rdpKey) {
        rdpSendScancodeTap(target.dataset.rdpKey, true);
      }
    });
  }

  if (btnRdpConnect) {
    btnRdpConnect.addEventListener("click", () => {
      triggerHaptic(10);
      void connectRdpSession();
    });
  }

  if (rdpPassInput) {
    rdpPassInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        void connectRdpSession();
      }
    });
  }

  if (btnRdpDisconnect) {
    btnRdpDisconnect.addEventListener("click", () => {
      triggerHaptic(10);
      disconnectRdpSession();
    });
  }

  if (btnRdpSwitchBack) {
    btnRdpSwitchBack.addEventListener("click", () => {
      triggerHaptic(10);
      selectKeyboardLayout(lastNonRemoteLayout || "pad");
    });
  }

  if (btnRdpCloseCard) {
    btnRdpCloseCard.addEventListener("click", () => {
      if (rdpSession && remoteLoginOverlay) {
        remoteLoginOverlay.classList.add("is-hidden");
      }
    });
  }

  onEnterRemoteLayout = () => {
    setRemoteHudExpanded(false);
    pushKvmConfigToServer();
    syncRdpConnectionUI();
    if (!rdpSession && !rdpConnecting) {
      const hasSavedPass = Boolean(rdpPassInput && rdpPassInput.value);
      if (hasSavedPass) {
        void connectRdpSession();
      } else if (remoteLoginOverlay) {
        remoteLoginOverlay.classList.remove("is-hidden");
      }
    }
  };

  onLeaveRemoteLayout = () => {
    closeRemoteSoftKeyboard();
    setRemoteHudExpanded(false);
    kvmActive = false;
    updateOverlayCursorVisual();
    pushKvmConfigToServer();
  };

  window.addEventListener("resize", () => {
    if (kbLayout === "remote") {
      applyRdpStageTransform();
      updateOverlayCursorVisual();
    }
  });

  if (kbLayout === "remote") {
    onEnterRemoteLayout();
  } else {
    // Nạp sẵn bộ giải mã WASM dưới nền để khi chuyển sang tab Remote PC sẽ kết nối tức thì (~0.3s)
    setTimeout(() => {
      void ensureIronRdpLoaded().catch(() => {});
    }, 900);
  }

  // ============================================================================
  // 9. CẬP NHẬT THÔNG MINH TRỰC TIẾP KHI ĐANG DÙNG APP (LIVE OTA HOT-UPDATE)
  //    Đang mở app dùng bình thường mà có bản mới trên GitHub -> chờ ngón tay nghỉ 2s
  //    rồi tự kéo & áp dụng luôn tại chỗ, không cần tắt app mở lại!
  // ============================================================================
  const BUNDLED_WEB_VERSION = "2.1.3";
  const LIVE_MANIFEST_URL =
    "https://raw.githubusercontent.com/NguyenHieu2711/mac-web-keyboard/main/releases/latest.json";
  let lastUserTouchAt = performance.now();
  let liveUpdateTriggered = false;
  let pendingUpdateApplyTimer = null;

  const markUserActive = () => {
    lastUserTouchAt = performance.now();
  };
  window.addEventListener("touchstart", markUserActive, { passive: true, capture: true });
  window.addEventListener("touchmove", markUserActive, { passive: true, capture: true });
  window.addEventListener("touchend", markUserActive, { passive: true, capture: true });
  window.addEventListener("mousedown", markUserActive, { passive: true, capture: true });

  function compareVer(a, b) {
    const cleanA = String(a || "")
      .trim()
      .replace(/^[vV]/, "")
      .split("-")[0];
    const cleanB = String(b || "")
      .trim()
      .replace(/^[vV]/, "")
      .split("-")[0];
    if (!cleanA || cleanA === cleanB) return 0;
    const pa = cleanA.split(".").map((n) => parseInt(n, 10) || 0);
    const pb = cleanB.split(".").map((n) => parseInt(n, 10) || 0);
    const len = Math.max(pa.length, pb.length);
    for (let i = 0; i < len; i += 1) {
      const va = pa[i] || 0;
      const vb = pb[i] || 0;
      if (va > vb) return 1;
      if (va < vb) return -1;
    }
    return 0;
  }

  function getRunningWebVersion() {
    let best = BUNDLED_WEB_VERSION;
    if (hasAndroidBridge && typeof window.AndroidBridge.getAppVersion === "function") {
      try {
        const bridgeVer = String(window.AndroidBridge.getAppVersion() || "").trim();
        if (bridgeVer && compareVer(bridgeVer, best) > 0) {
          best = bridgeVer;
        }
      } catch {
        // ignore
      }
    }
    return best;
  }

  function triggerWhenIdle() {
    if (liveUpdateTriggered || rdpSession) return;
    const idleMs = performance.now() - lastUserTouchAt;
    if (document.visibilityState !== "visible" || activePointers.size > 0 || idleMs < 2000) {
      if (pendingUpdateApplyTimer === null) {
        pendingUpdateApplyTimer = setTimeout(() => {
          pendingUpdateApplyTimer = null;
          triggerWhenIdle();
        }, 1200);
      }
      return;
    }
    liveUpdateTriggered = true;
    releaseAllActiveTouches();
    if (hasAndroidBridge && typeof window.AndroidBridge.startNativeUpdate === "function") {
      try {
        window.AndroidBridge.startNativeUpdate();
        return;
      } catch {
        // fallback reload
      }
    }
    window.location.reload();
  }

  async function pollLiveUpdateManifest() {
    if (liveUpdateTriggered || document.visibilityState !== "visible") return;
    try {
      const res = await fetch(`${LIVE_MANIFEST_URL}?t=${Date.now()}`, {
        method: "GET",
        cache: "no-store",
      });
      if (!res.ok) return;
      const data = await res.json();
      if (!data || typeof data !== "object") return;
      const curVer = getRunningWebVersion();
      const remoteWeb = String(data.web_version || "").trim();
      const remoteTag = String(data.tag_name || "").trim();
      if (
        (remoteWeb && compareVer(remoteWeb, curVer) > 0) ||
        (remoteTag && compareVer(remoteTag, curVer) > 0)
      ) {
        triggerWhenIdle();
      }
    } catch {
      // ignore offline / transient network errors
    }
  }

  setTimeout(() => {
    void pollLiveUpdateManifest();
  }, 4000);
  setInterval(() => {
    void pollLiveUpdateManifest();
  }, 22000);
})();
