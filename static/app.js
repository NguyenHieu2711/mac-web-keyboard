(() => {
  "use strict";

  const BUNDLED_BOOT_VER = "2.3.28";
  if (!window.__MAC_KB_HOT_BOOTED__) {
    try {
      const rawHot = localStorage.getItem("mac_kb_hot_bundle_v1");
      if (rawHot) {
        const bundle = JSON.parse(rawHot);
        const cmpBootVer = (a, b) => {
          const pa = String(a || "")
            .trim()
            .replace(/^[vV]/, "")
            .split("-")[0]
            .split(".")
            .map((n) => parseInt(n, 10) || 0);
          const pb = String(b || "")
            .trim()
            .replace(/^[vV]/, "")
            .split("-")[0]
            .split(".")
            .map((n) => parseInt(n, 10) || 0);
          for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
            if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
          }
          return 0;
        };
        if (
          bundle &&
          bundle.etag &&
          bundle.app_js &&
          bundle.body_html &&
          typeof bundle.style_css === "string"
        ) {
          if (cmpBootVer(BUNDLED_BOOT_VER, bundle.web_version || "0.0.0") > 0) {
            localStorage.removeItem("mac_kb_hot_bundle_v1");
          } else {
            window.__MAC_KB_HOT_BOOTED__ = String(bundle.etag);
            window.__MAC_KB_HOT_VERSION__ = String(bundle.web_version || BUNDLED_BOOT_VER);
            window.__MAC_KB_HOT_OK__ = false;
            document
              .querySelectorAll('link[rel="stylesheet"], style#hot-ota-style')
              .forEach((el) => el.remove());
            const st = document.createElement("style");
            st.id = "hot-ota-style";
            st.textContent = bundle.style_css;
            document.head.appendChild(st);
            document.body.innerHTML = bundle.body_html;
            const sc = document.createElement("script");
            sc.textContent = bundle.app_js;
            document.body.appendChild(sc);
            // Tự động tự cứu nếu gói hot-bundle bị lỗi runtime: xóa cache hỏng và tải lại bản gốc sạch!
            if (window.__MAC_KB_HOT_OK__ !== true) {
              try {
                localStorage.removeItem("mac_kb_hot_bundle_v1");
              } catch {
                // ignore
              }
              window.location.reload();
            }
            return;
          }
        }
      }
    } catch {
      try {
        localStorage.removeItem("mac_kb_hot_bundle_v1");
      } catch {
        // ignore
      }
    }
  }

  const wsDots = Array.from(document.querySelectorAll(".js-ws-dot"));
  const utilIcons = Array.from(document.querySelectorAll(".js-util-icon"));
  const layoutLabels = Array.from(document.querySelectorAll(".js-layout-label"));
  const vnBtns = Array.from(document.querySelectorAll(".js-vn-btn"));
  const vnLabels = Array.from(document.querySelectorAll(".js-vn-label"));
  const symPopup = document.getElementById("sym-floating-popup");
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
    mac_ext: "📱 Màn phụ",
  };

  let kbLayout = "pad";
  let lastNonRemoteLayout = "pad";
  let padSplitHorizontal = false;
  let vnEnabled = true;
  let symLayer = false;
  let symShifted = false;
  let modeMenuOpen = false;
  let rdpControlMode = "touch_mac"; // "touch_mac" | "pointer_mac" | "mouse_phone" | "mouse_bridge"
  let rdpInputMode = "touch"; // "touch" | "pointer"
  let rdpMouseMode = "mac"; // "mac" | "phone" | "bridge"
  let onEnterRemoteLayout = null;
  let onLeaveRemoteLayout = null;
  let handleKvmServerMessage = null;

  function applyDerivedControlModes(ctrlMode) {
    const valid =
      ctrlMode === "touch_mac" ||
      ctrlMode === "pointer_mac" ||
      ctrlMode === "mouse_phone" ||
      ctrlMode === "mouse_bridge"
        ? ctrlMode
        : "touch_mac";
    rdpControlMode = valid;
    if (valid === "mouse_phone") {
      // Chuột khóa riêng ở Điện thoại: đồng nhất dùng trỏ chuột (tuyệt đối không lệch sang Cảm ứng)
      rdpInputMode = "pointer";
      rdpMouseMode = "phone";
    } else if (valid === "mouse_bridge") {
      // Chuột nối 2 màn Mac ⇄ Điện thoại: di chuột xuyên 2 màn + ngón tay vẫn chạm cuộn tự nhiên
      rdpInputMode = "touch";
      rdpMouseMode = "bridge";
    } else if (valid === "pointer_mac") {
      rdpInputMode = "pointer";
      rdpMouseMode = "mac";
    } else {
      rdpInputMode = "touch";
      rdpMouseMode = "mac";
    }
  }

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
    const savedCtrlMode = localStorage.getItem("mac_kb_rdp_ctrl_mode");
    if (
      savedCtrlMode === "touch_mac" ||
      savedCtrlMode === "pointer_mac" ||
      savedCtrlMode === "mouse_phone" ||
      savedCtrlMode === "mouse_bridge"
    ) {
      applyDerivedControlModes(savedCtrlMode);
    } else {
      const legacyMouse = localStorage.getItem("mac_kb_rdp_mouse_mode");
      const legacyInput = localStorage.getItem("mac_kb_rdp_input_mode");
      if (legacyMouse === "phone") {
        applyDerivedControlModes("mouse_phone");
      } else if (legacyMouse === "bridge") {
        applyDerivedControlModes("mouse_bridge");
      } else if (legacyInput === "pointer") {
        applyDerivedControlModes("pointer_mac");
      } else {
        applyDerivedControlModes("touch_mac");
      }
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
    const hudModeLbl = document.getElementById("lbl-remote-mode-btn");
    if (hudModeLbl) {
      hudModeLbl.textContent = kbLayout === "mac_ext" ? "Màn phụ" : "Remote";
    }
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
    if (kbLayout === "remote" || kbLayout === "mac_ext") {
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
      enabled: activeRemote && rdpMouseMode !== "mac",
      mode: rdpMouseMode,
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
    if (prevLayout !== "remote" && prevLayout !== "mac_ext" && (newLayout === "remote" || newLayout === "mac_ext")) {
      lastNonRemoteLayout = prevLayout;
    }
    kbLayout = newLayout;
    modeMenuOpen = false;
    symLayer = false;
    symShifted = false;
    if (kbLayout !== "mac_ext") {
      try {
        localStorage.setItem(STORAGE_LAYOUT_KEY, kbLayout);
      } catch {
        // ignore
      }
    }
    syncModeUI();
    pushConfigToServer();
    if (prevLayout === "mac_ext" && kbLayout !== "mac_ext") {
      if (typeof toggleMacExtDisplay === "function") void toggleMacExtDisplay(false, false);
    } else if (prevLayout === "remote" && kbLayout !== "remote") {
      if (kbLayout === "mac_ext" && typeof disconnectRdpSession === "function") {
        // Khi rời Remote PC sang Màn phụ Mac -> ngắt hẳn phiên Remote PC trên ĐT (không động Windows App trên MacBook)
        disconnectRdpSession(true);
      }
      if (typeof onLeaveRemoteLayout === "function") onLeaveRemoteLayout();
    }
    if (kbLayout === "mac_ext") {
      if (typeof toggleMacExtDisplay === "function") void toggleMacExtDisplay(true, false);
    } else if (kbLayout === "remote") {
      if (typeof onEnterRemoteLayout === "function") onEnterRemoteLayout(true);
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
            (msg.type === "kvm_state" ||
              msg.type === "kvm_enter" ||
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
  // 8. TAB 4 ĐỘC LẬP: REMOTE PC (2248x1080 @ HiDPI SCALING • TOUCH + KVM + MIC)
  // ============================================================================
  const RDP_TARGET_W = 2248;
  const RDP_TARGET_H = 1080;
  const RDP_PHYS_W_MM = 155;
  const RDP_PHYS_H_MM = 74;
  const VALID_RDP_SCALES = [100, 125, 150, 175];
  const STORAGE_RDP_SCALE = "mac_kb_rdp_scale_v2";
  const STORAGE_RDP_HOST = "mac_kb_rdp_host";
  const STORAGE_RDP_USER = "mac_kb_rdp_user";
  const STORAGE_RDP_PASS = "mac_kb_rdp_pass";
  const STORAGE_RDP_EDGE = "mac_kb_rdp_edge_mode";

  let rdpDesktopScale = 125;
  try {
    const savedRdpScale = parseInt(localStorage.getItem(STORAGE_RDP_SCALE) || "125", 10);
    if (VALID_RDP_SCALES.includes(savedRdpScale)) {
      rdpDesktopScale = savedRdpScale;
    }
  } catch {
    // ignore
  }

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
  const remoteHudPills = document.getElementById("remote-hud-pills");
  const remoteHudPill = document.getElementById("remote-hud-pill");
  const remotePillModeIco = document.getElementById("remote-pill-mode-ico");
  const remoteHudBar = document.getElementById("remote-hud-bar");
  const remoteStatusDot = document.getElementById("remote-status-dot");
  const remoteModeMenu = document.getElementById("remote-mode-menu");
  const btnRemoteControl = document.getElementById("btn-remote-control");
  const lblRemoteControl = document.getElementById("lbl-remote-control");
  const remoteControlMenu = document.getElementById("remote-control-menu");
  const remoteScaleWrap = document.getElementById("remote-scale-wrap");
  const btnRemoteScale = document.getElementById("btn-remote-scale");
  const lblRemoteScale = document.getElementById("lbl-remote-scale");
  const remoteScaleMenu = document.getElementById("remote-scale-menu");
  const rdpResBadge = document.getElementById("rdp-res-badge");
  const btnRemoteCoexist = document.getElementById("btn-remote-coexist");
  const btnMacExtTouch = document.getElementById("btn-mac-ext-touch");
  const lblMacExtTouch = document.getElementById("lbl-mac-ext-touch");
  const btnMacExtDisplay = document.getElementById("btn-mac-ext-display");
  const lblMacExtDisplay = document.getElementById("lbl-mac-ext-display");
  const macExtOverlay = document.getElementById("mac-ext-overlay");
  const macExtStatus = document.getElementById("mac-ext-status");
  const btnMacExtBack = document.getElementById("btn-mac-ext-back");
  const btnMacExtRetry = document.getElementById("btn-mac-ext-retry");
  const btnMacExtOff = document.getElementById("btn-mac-ext-off");
  const btnRemoteKb = document.getElementById("btn-remote-kb");
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
  let rdpParallelWs = null;
  let rdpActiveEngine = "none"; // "none" | "parallel" | "native"
  let macExtWs = null;
  let macExtManualStop = false;
  let macExtReconnectRetries = 0;
  let macExtReconnectTimer = null;
  const remoteTouchRing = document.getElementById("remote-touch-ring");
  let macExtCursorVisible = false;
  let macExtTouchMode = "touch"; // "touch" (Cảm ứng) | "pointer" (Trackpad) | "off" (Khóa chạm)
  try {
    const savedExtTouch = localStorage.getItem("mac_kb_mac_ext_touch_v1");
    if (savedExtTouch === "0" || savedExtTouch === "off") macExtTouchMode = "off";
    else if (savedExtTouch === "pointer") macExtTouchMode = "pointer";
  } catch {
    // ignore
  }
  let rdpPreferExclusive = false;
  let rdpManualDisconnect = false;
  let rdpConnecting = false;
  let rdpHudExpanded = false;
  let rdpRemoteMenuOpen = false;
  let rdpControlMenuOpen = false;
  let rdpScaleMenuOpen = false;
  let rdpImeOpen = false;
  let rdpComposing = false;
  let rdpActiveMods = new Set();

  let rdpZoom = 1.0;
  let rdpPanX = 0;
  let rdpPanY = 0;

  let kvmActive = false;
  let kvmButtonsMask = 0;
  let kvmBridgeReturnPush = 0;
  let kvmBridgeEntryEdge = "right";
  let localPointerVisible = false;
  let localPointerHideTimer = null;
  let kvmX = RDP_TARGET_W / 2;
  let kvmY = RDP_TARGET_H / 2;
  let cursorHotspotX = 2;
  let cursorHotspotY = 1;
  let cursorHiddenByServer = false;

  let rdpAudioWs = null;
  let rdpAudioCtx = null;
  let rdpNextPlayTime = 0;
  let rdpSpkRate = 44100;
  let rdpSpkChannels = 2;
  // Loa & Microphone (Remote Audio) luôn tự động bật ngầm 100% không cần nút công tắc
  const rdpSpkEnabled = true;
  const rdpMicEnabled = true;
  let rdpServerMicOpen = false;
  let rdpServerMicSpec = { rate: 44100, channels: 1, framesPerPacket: 480 };
  let rdpWebMicStream = null;
  let rdpWebMicProc = null;

  let parallelDecoding = false;
  let parallelQueuedBuf = null;

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

  function isMacExtConnected() {
    return Boolean(macExtWs && macExtWs.readyState === WebSocket.OPEN);
  }

  function isRemoteConnected() {
    if (kbLayout === "mac_ext") {
      return isMacExtConnected();
    }
    return Boolean(
      rdpSession ||
        (rdpParallelWs && rdpParallelWs.readyState === WebSocket.OPEN)
    );
  }

  function isStreamInputEngine() {
    return kbLayout === "mac_ext" ? isMacExtConnected() : rdpActiveEngine === "parallel";
  }

  function closeAllRemoteSubMenus() {
    rdpRemoteMenuOpen = false;
    rdpControlMenuOpen = false;
    rdpScaleMenuOpen = false;
    if (remoteModeMenu) remoteModeMenu.classList.add("is-hidden");
    if (remoteControlMenu) remoteControlMenu.classList.add("is-hidden");
    if (remoteScaleMenu) remoteScaleMenu.classList.add("is-hidden");
  }

  function setRemoteStageAspect(w, h) {
    if (!remoteStage) return;
    const sw = w > 0 ? w : remoteCanvas ? remoteCanvas.width || RDP_TARGET_W : RDP_TARGET_W;
    const sh = h > 0 ? h : remoteCanvas ? remoteCanvas.height || RDP_TARGET_H : RDP_TARGET_H;
    const ratio = sw / Math.max(1, sh);
    // Phủ kín 100% màn hình điện thoại (không viền đen 2 bên) NHƯNG giữ nguyên tỉ lệ gốc 1:1 của nguồn ảnh để chữ tuyệt đối KHÔNG bị bè ngang!
    remoteStage.style.setProperty("--rdp-aspect", ratio.toFixed(5));
    remoteStage.style.aspectRatio = "";
    applyRdpStageTransform();
    updateOverlayCursorVisual();
  }

  function syncRemoteScaleUI() {
    if (lblRemoteScale) {
      lblRemoteScale.textContent = `${rdpDesktopScale}%`;
    }
    if (rdpResBadge) {
      rdpResBadge.textContent = `2248×1080 • ${rdpDesktopScale}%`;
    }
    if (remoteScaleMenu) {
      remoteScaleMenu.querySelectorAll("[data-rdp-scale]").forEach((el) => {
        el.classList.toggle(
          "is-selected",
          parseInt(el.dataset.rdpScale || "0", 10) === rdpDesktopScale
        );
      });
    }
  }

  function applyLiveRdpDesktopScale(forceToggleWidth = false) {
    if (!rdpSession || !remoteCanvas) return;
    const curW = remoteCanvas.width || RDP_TARGET_W;
    const targetW = forceToggleWidth
      ? curW === RDP_TARGET_W
        ? RDP_TARGET_W - 2
        : RDP_TARGET_W
      : RDP_TARGET_W;
    try {
      rdpSession.resize(
        targetW,
        RDP_TARGET_H,
        rdpDesktopScale,
        RDP_PHYS_W_MM,
        RDP_PHYS_H_MM
      );
      setRemoteStageAspect(targetW, RDP_TARGET_H);
    } catch {
      // ignore
    }
  }

  function setRemoteDesktopScale(rawScale) {
    const parsed = parseInt(String(rawScale || "125"), 10);
    if (!VALID_RDP_SCALES.includes(parsed)) return;
    const changed = parsed !== rdpDesktopScale;
    rdpDesktopScale = parsed;
    try {
      localStorage.setItem(STORAGE_RDP_SCALE, String(rdpDesktopScale));
    } catch {
      // ignore
    }
    syncRemoteScaleUI();
    if (changed && rdpSession && rdpActiveEngine === "native") {
      applyLiveRdpDesktopScale(true);
    }
  }

  const HUD_SVG = {
    touch:
      '<svg class="hud-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 11V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2"/><path d="M14 10V4a2 2 0 0 0-2-2 2 2 0 0 0-2 2v2"/><path d="M10 10.5V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>',
    trackpad:
      '<svg class="hud-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 15h18M12 15v5"/></svg>',
    mouse:
      '<svg class="hud-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="3" width="12" height="18" rx="6"/><path d="M12 7v4"/></svg>',
    bridge:
      '<svg class="hud-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m7 16-4-4 4-4"/><path d="m17 8 4 4-4 4"/><path d="M3 12h18"/></svg>',
    parallel:
      '<svg class="hud-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="8" height="16" rx="1.5"/><rect x="13" y="4" width="8" height="16" rx="1.5"/></svg>',
    phoneOnly:
      '<svg class="hud-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="2" width="12" height="20" rx="2"/><path d="M12 18h.01"/></svg>',
  };

  function syncRemoteControlModeUI() {
    const pillMarkup = {
      touch_mac: `${HUD_SVG.touch}<span>Cảm ứng</span>`,
      pointer_mac: `${HUD_SVG.trackpad}<span>Bàn rê ảo</span>`,
      mouse_phone: `${HUD_SVG.mouse}<span>Chuột ĐT</span>`,
      mouse_bridge: `${HUD_SVG.bridge}<span>${kvmActive ? "Đang ở ĐT" : "2 màn hình"}</span>`,
    };
    if (lblRemoteControl) {
      lblRemoteControl.innerHTML = pillMarkup[rdpControlMode] || pillMarkup.touch_mac;
    }
    if (btnRemoteControl) {
      btnRemoteControl.classList.toggle(
        "is-active",
        rdpControlMode === "mouse_phone" ||
          rdpControlMode === "pointer_mac" ||
          (rdpControlMode === "mouse_bridge" && kvmActive)
      );
    }
    if (remoteControlMenu) {
      remoteControlMenu.querySelectorAll("[data-rdp-ctrl]").forEach((el) => {
        const key = el.dataset.rdpCtrl;
        let isSelected = false;
        if (key === "touch_mac") {
          isSelected = rdpControlMode === "touch_mac" || rdpControlMode === "mouse_bridge";
        } else if (key === "pointer_mac") {
          isSelected = rdpControlMode === "pointer_mac";
        } else if (key === "mouse_mac") {
          isSelected = rdpMouseMode === "mac";
        } else if (key === "mouse_phone") {
          isSelected = rdpMouseMode === "phone";
        } else if (key === "mouse_bridge") {
          isSelected = rdpMouseMode === "bridge";
        }
        el.classList.toggle("is-selected", isSelected);
      });
    }
    updateOverlayCursorVisual();
  }

  function syncRemoteInputModeUI() {
    syncRemoteControlModeUI();
  }

  function syncSmartKvmButtonsUI() {
    syncRemoteControlModeUI();
  }

  function syncCoexistButtonUI() {
    const isPar = rdpActiveEngine === "parallel";
    const parHtml = `<span class="remote-btn-content">${HUD_SVG.parallel}<span>Song song</span></span>`;
    const mobileHtml = `<span class="remote-btn-content">${HUD_SVG.phoneOnly}<span>Chỉ điện thoại</span></span>`;
    if (btnRemoteCoexist) {
      if (isPar) {
        btnRemoteCoexist.innerHTML = parHtml;
        btnRemoteCoexist.classList.add("is-active");
      } else if (rdpActiveEngine === "native") {
        btnRemoteCoexist.innerHTML = mobileHtml;
        btnRemoteCoexist.classList.add("is-active");
      } else {
        btnRemoteCoexist.innerHTML = rdpPreferExclusive ? mobileHtml : parHtml;
        btnRemoteCoexist.classList.toggle("is-active", rdpPreferExclusive);
      }
    }
    if (remotePillModeIco) {
      remotePillModeIco.innerHTML = isPar ? HUD_SVG.parallel : HUD_SVG.phoneOnly;
    }
    if (remoteScaleWrap) {
      remoteScaleWrap.classList.toggle("is-hidden", isPar);
    }
  }

  function setRemoteHudExpanded(expanded) {
    rdpHudExpanded = Boolean(expanded);
    if (!rdpHudExpanded) {
      closeAllRemoteSubMenus();
    }
    if (remoteHudPills) remoteHudPills.classList.toggle("is-hidden", rdpHudExpanded);
    else if (remoteHudPill) remoteHudPill.classList.toggle("is-hidden", rdpHudExpanded);
    if (remoteHudBar) remoteHudBar.classList.toggle("is-hidden", !rdpHudExpanded);
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
    const connected = isRemoteConnected();
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
    syncCoexistButtonUI();
    syncRemoteInputModeUI();
    syncSmartKvmButtonsUI();
    syncRemoteScaleUI();
  }

  function isRemoteStageOverflowing() {
    if (!remoteViewport || !remoteStage) return false;
    const vw = remoteViewport.clientWidth || 1;
    const vh = remoteViewport.clientHeight || 1;
    return remoteStage.offsetWidth > vw + 2 || remoteStage.offsetHeight > vh + 2;
  }

  function clampRdpPan() {
    if (!remoteViewport || !remoteStage) return;
    // Ở tỉ lệ mặc định 100%: luôn khóa chặt fit 100% màn hình, tuyệt đối không cho tóm 2 ngón kéo trôi khung hình lên xuống
    if (rdpZoom <= 1.005) {
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
    if (sw <= vw + 1) {
      rdpPanX = (vw - sw) / 2 - baseLeft;
    } else {
      const boundX1 = -baseLeft;
      const boundX2 = vw - sw - baseLeft;
      rdpPanX = Math.max(Math.min(boundX1, boundX2), Math.min(Math.max(boundX1, boundX2), rdpPanX));
    }
    if (sh <= vh + 1) {
      rdpPanY = (vh - sh) / 2 - baseTop;
    } else {
      const boundY1 = -baseTop;
      const boundY2 = vh - sh - baseTop;
      rdpPanY = Math.max(Math.min(boundY1, boundY2), Math.min(Math.max(boundY1, boundY2), rdpPanY));
    }
  }

  function applyRdpStageTransform() {
    if (!remoteStage) return;
    clampRdpPan();
    const hasPan = Math.abs(rdpPanX) > 0.4 || Math.abs(rdpPanY) > 0.4;
    if (rdpZoom <= 1.005 && !hasPan) {
      remoteStage.style.transform = "";
      if (btnRemoteZoomReset) btnRemoteZoomReset.classList.add("is-hidden");
    } else {
      remoteStage.style.transform = `translate3d(${rdpPanX.toFixed(1)}px, ${rdpPanY.toFixed(1)}px, 0) scale(${rdpZoom.toFixed(3)})`;
      if (btnRemoteZoomReset) {
        if (rdpZoom > 1.01) {
          btnRemoteZoomReset.textContent = `${Math.round(rdpZoom * 100)}%`;
          btnRemoteZoomReset.classList.remove("is-hidden");
        } else {
          btnRemoteZoomReset.classList.add("is-hidden");
        }
      }
    }
  }

  function zoomRdpAtClientPoint(targetZoom, focalClientX, focalClientY, panDx = 0, panDy = 0) {
    if (!remoteViewport || !remoteStage) return;
    const clampedZoom = Math.max(1.0, Math.min(4.0, targetZoom));
    const vpRect = remoteViewport.getBoundingClientRect();
    const vw = remoteViewport.clientWidth || 1;
    const vh = remoteViewport.clientHeight || 1;
    const baseLeft = (vw - remoteStage.offsetWidth) / 2;
    const baseTop = (vh - remoteStage.offsetHeight) / 2;
    const prevFx = focalClientX - vpRect.left - panDx;
    const prevFy = focalClientY - vpRect.top - panDy;
    const stageX = (prevFx - baseLeft - rdpPanX) / (rdpZoom || 1.0);
    const stageY = (prevFy - baseTop - rdpPanY) / (rdpZoom || 1.0);
    const curFx = focalClientX - vpRect.left;
    const curFy = focalClientY - vpRect.top;
    rdpZoom = clampedZoom;
    rdpPanX = curFx - baseLeft - stageX * rdpZoom;
    rdpPanY = curFy - baseTop - stageY * rdpZoom;
    applyRdpStageTransform();
    updateOverlayCursorVisual();
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

  function autoPanViewportForCursor() {
    if (!remoteViewport || !remoteCanvas || (rdpZoom <= 1.01 && !isRemoteStageOverflowing())) {
      return;
    }
    const rect = remoteCanvas.getBoundingClientRect();
    const vw = remoteViewport.clientWidth || 1;
    const vh = remoteViewport.clientHeight || 1;
    const cw = Math.max(1, remoteCanvas.width || RDP_TARGET_W);
    const ch = Math.max(1, remoteCanvas.height || RDP_TARGET_H);
    const screenX = rect.left + (kvmX / cw) * rect.width;
    const screenY = rect.top + (kvmY / ch) * rect.height;
    const margin = 34;
    let changed = false;
    if (screenX < margin) {
      rdpPanX += margin - screenX;
      changed = true;
    } else if (screenX > vw - margin) {
      rdpPanX -= screenX - (vw - margin);
      changed = true;
    }
    if (screenY < margin) {
      rdpPanY += margin - screenY;
      changed = true;
    } else if (screenY > vh - margin) {
      rdpPanY -= screenY - (vh - margin);
      changed = true;
    }
    if (changed) {
      applyRdpStageTransform();
    }
  }

  function updateOverlayCursorVisual() {
    if (!remoteKvmCursor || !remoteCanvas) return;
    // Ở Màn phụ Mac: CHỈ hiện con trỏ khi chuột MacBook thật đang di sang màn phụ #2 (tách biệt hẳn với cảm ứng tay)
    // Ở Remote PC: hiện con trỏ khi chuột vật lý thuộc về Điện thoại (`kvmActive`) hoặc đang rê Trackpad (`localPointerVisible`)
    const shouldShow =
      kbLayout === "mac_ext"
        ? macExtCursorVisible
        : kvmActive || localPointerVisible;
    if (!shouldShow || cursorHiddenByServer) {
      remoteKvmCursor.classList.add("is-hidden");
      return;
    }
    const cw = remoteCanvas.offsetWidth || RDP_TARGET_W;
    const ch = remoteCanvas.offsetHeight || RDP_TARGET_H;
    const canvasW = remoteCanvas.width || RDP_TARGET_W;
    const canvasH = remoteCanvas.height || RDP_TARGET_H;
    const stageScale = cw / canvasW;
    const usingFallbackSvg =
      !remoteCursorImg || remoteCursorImg.classList.contains("is-hidden");
    const cursorScale =
      kbLayout === "mac_ext" && usingFallbackSvg
        ? 0.92
        : Math.max(usingFallbackSvg ? 0.65 : 0.36, Math.min(1.0, stageScale * 1.18));
    const px = (kvmX / canvasW) * cw - cursorHotspotX * cursorScale;
    const py = (kvmY / canvasH) * ch - cursorHotspotY * cursorScale;
    remoteKvmCursor.style.transform = `translate3d(${px.toFixed(2)}px, ${py.toFixed(2)}px, 0) scale(${cursorScale.toFixed(3)})`;
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

    const directPcUrl = pcIp ? `ws://${pcIp}:5051` : "";
    const liveMacProxy =
      ws && ws.readyState === WebSocket.OPEN && ws.url
        ? ws.url.replace(/\/ws(\?.*)?$/, "/rdp-ws")
        : "";

    // Ưu tiên kết nối thẳng 1 chặng Điện thoại -> PC (:5051) để không phụ thuộc MacBook restart / sleep
    if (directPcUrl) {
      const probe = await probeWsOpen(directPcUrl, 450);
      if (probe.ok) {
        return liveMacProxy ? [directPcUrl, liveMacProxy] : [directPcUrl];
      }
    }
    if (liveMacProxy) {
      return directPcUrl ? [liveMacProxy, directPcUrl] : [liveMacProxy];
    }

    const rawUrls = [];
    if (directPcUrl) {
      rawUrls.push(directPcUrl);
    }
    for (const h of resolveCandidateHosts()) {
      const cleanH = h.replace(/^https?:\/\/|^wss?:\/\//, "").split("/")[0];
      if (cleanH) rawUrls.push(`ws://${cleanH}/rdp-ws`);
    }

    const uniqueUrls = Array.from(new Set(rawUrls));
    if (uniqueUrls.length === 0) return [];

    // Đua mở WebSocket thật song song khi chưa có kênh ws sẵn:
    try {
      const fastest = await Promise.any(
        uniqueUrls.map(
          (u) =>
            new Promise((res, rej) => {
              probeWsOpen(u, 900).then((r) => (r.ok ? res(r.wsUrl) : rej()));
            })
        )
      );
      return [fastest, ...uniqueUrls.filter((u) => u !== fastest)];
    } catch {
      return uniqueUrls.slice(0, 1);
    }
  }

  let rdpAutoReconnectTimes = [];

  function canAutoReconnectRdp() {
    const now = performance.now();
    rdpAutoReconnectTimes = rdpAutoReconnectTimes.filter((t) => now - t < 18000);
    if (rdpAutoReconnectTimes.length >= 3) return false;
    rdpAutoReconnectTimes.push(now);
    return true;
  }

  function isAuthFailureRdpError(err) {
    try {
      if (err && typeof err.kind === "function") {
        const k = err.kind();
        return k === 1 || k === 2 || k === 3;
      }
    } catch {
      // ignore
    }
    return false;
  }

  function isTransientSocketRdpDrop(err) {
    if (!err || isAuthFailureRdpError(err)) return false;
    let combined = String(err.message || err || "").toLowerCase();
    try {
      if (typeof err.backtrace === "function") {
        combined += " " + String(err.backtrace() || "").toLowerCase();
      }
    } catch {
      // ignore
    }
    if (
      combined.includes("other connection") ||
      combined.includes("another user") ||
      combined.includes("replaced") ||
      combined.includes("0x00000005")
    ) {
      return false;
    }
    return (
      combined.includes("not enough bytes") ||
      combined.includes("read frame") ||
      combined.includes("unexpected eof") ||
      combined.includes("websocket") ||
      combined.includes("broken pipe")
    );
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
        const low = bt.toLowerCase();
        if (low.includes("not enough bytes") || low.includes("read frame")) {
          return "Đường truyền hình ảnh ngắt tạm thời — bấm Kết nối lại.";
        }
        const firstLine = bt.split("\n")[0].trim();
        if (firstLine) return firstLine;
      }
    } catch {
      // ignore
    }
    const raw = String(err.message || err);
    if (raw.toLowerCase().includes("not enough bytes")) {
      return "Đường truyền hình ảnh ngắt tạm thời — bấm Kết nối lại.";
    }
    return raw;
  }

  const CODE_TO_SERVER_KEY = {
    Escape: "esc", Tab: "tab", Backspace: "backspace", Enter: "enter",
    Space: "space", Delete: "delete", Home: "home", End: "end",
    PageUp: "pageup", PageDown: "pagedown",
    ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
    Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]",
    Backslash: "\\", Semicolon: ";", Quote: "'", Backquote: "`",
    Comma: ",", Period: ".", Slash: "/",
    F1: "f1", F2: "f2", F3: "f3", F4: "f4", F5: "f5", F6: "f6",
    F7: "f7", F8: "f8", F9: "f9", F10: "f10", F11: "f11", F12: "f12",
  };
  for (let i = 0; i <= 9; i += 1) CODE_TO_SERVER_KEY[`Digit${i}`] = String(i);
  for (let c = 65; c <= 90; c += 1) {
    const ch = String.fromCharCode(c);
    CODE_TO_SERVER_KEY[`Key${ch}`] = ch.toLowerCase();
  }

  function sendParallelJson(payload) {
    const targetWs = kbLayout === "mac_ext" ? macExtWs : rdpParallelWs;
    if (targetWs && targetWs.readyState === WebSocket.OPEN) {
      try {
        targetWs.send(JSON.stringify(payload));
      } catch {
        // ignore
      }
    }
  }

  function coordsToNormalizedRatio(rx, ry) {
    const cw = Math.max(1, remoteCanvas ? remoteCanvas.width || RDP_TARGET_W : RDP_TARGET_W);
    const ch = Math.max(1, remoteCanvas ? remoteCanvas.height || RDP_TARGET_H : RDP_TARGET_H);
    return {
      rx: +Math.max(0, Math.min(1, rx / cw)).toFixed(5),
      ry: +Math.max(0, Math.min(1, ry / ch)).toFixed(5),
    };
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

  function rdpSendMouseMove(rx, ry) {
    if (!isRemoteConnected()) return;
    const cx = Math.max(0, Math.min((remoteCanvas.width || RDP_TARGET_W) - 1, Math.round(rx)));
    const cy = Math.max(0, Math.min((remoteCanvas.height || RDP_TARGET_H) - 1, Math.round(ry)));
    kvmX = cx;
    kvmY = cy;
    updateOverlayCursorVisual();
    if (isStreamInputEngine()) {
      const norm = coordsToNormalizedRatio(cx, cy);
      sendParallelJson({ type: "ptr_move", rx: norm.rx, ry: norm.ry });
      return;
    }
    if (rdpSession && rdpMod) {
      applyRdpDeviceEvents([rdpMod.DeviceEvent.mouseMove(cx, cy)]);
    }
  }

  function rdpSendMouseDown(rx, ry, button = 0, count = 1) {
    if (!isRemoteConnected()) return;
    const cx = Math.max(0, Math.min((remoteCanvas.width || RDP_TARGET_W) - 1, Math.round(rx)));
    const cy = Math.max(0, Math.min((remoteCanvas.height || RDP_TARGET_H) - 1, Math.round(ry)));
    kvmX = cx;
    kvmY = cy;
    updateOverlayCursorVisual();
    if (isStreamInputEngine()) {
      const norm = coordsToNormalizedRatio(cx, cy);
      sendParallelJson({ type: "ptr_down", rx: norm.rx, ry: norm.ry, btn: button, count });
      return;
    }
    if (rdpSession && rdpMod) {
      applyRdpDeviceEvents([
        rdpMod.DeviceEvent.mouseMove(cx, cy),
        rdpMod.DeviceEvent.mouseButtonPressed(button),
      ]);
    }
  }

  function rdpSendMouseUp(rx, ry, button = 0, count = 1) {
    if (!isRemoteConnected()) return;
    const cx = Math.max(0, Math.min((remoteCanvas.width || RDP_TARGET_W) - 1, Math.round(rx)));
    const cy = Math.max(0, Math.min((remoteCanvas.height || RDP_TARGET_H) - 1, Math.round(ry)));
    if (isStreamInputEngine()) {
      const norm = coordsToNormalizedRatio(cx, cy);
      sendParallelJson({ type: "ptr_up", rx: norm.rx, ry: norm.ry, btn: button, count });
      return;
    }
    if (rdpSession && rdpMod) {
      applyRdpDeviceEvents([rdpMod.DeviceEvent.mouseButtonReleased(button)]);
    }
  }

  function rdpSendMouseClick(rx, ry, button = 0, count = 1) {
    if (!isRemoteConnected()) return;
    const cx = Math.max(0, Math.min((remoteCanvas.width || RDP_TARGET_W) - 1, Math.round(rx)));
    const cy = Math.max(0, Math.min((remoteCanvas.height || RDP_TARGET_H) - 1, Math.round(ry)));
    kvmX = cx;
    kvmY = cy;
    updateOverlayCursorVisual();
    if (isStreamInputEngine()) {
      const norm = coordsToNormalizedRatio(cx, cy);
      sendParallelJson({ type: "ptr_down", rx: norm.rx, ry: norm.ry, btn: button, count });
      sendParallelJson({ type: "ptr_up", rx: norm.rx, ry: norm.ry, btn: button, count });
      return;
    }
    if (!rdpSession || !rdpMod) return;
    const evs = [rdpMod.DeviceEvent.mouseMove(cx, cy)];
    for (let i = 0; i < count; i += 1) {
      evs.push(rdpMod.DeviceEvent.mouseButtonPressed(button));
      evs.push(rdpMod.DeviceEvent.mouseButtonReleased(button));
    }
    applyRdpDeviceEvents(evs);
  }

  function rdpSendWheel(dxPx, dyPx, unit = 0, targetX = null, targetY = null) {
    if (!isRemoteConnected()) return;
    let movedTarget = false;
    if (targetX !== null && targetY !== null) {
      const nx = Math.max(0, Math.min((remoteCanvas.width || RDP_TARGET_W) - 1, Math.round(targetX)));
      const ny = Math.max(0, Math.min((remoteCanvas.height || RDP_TARGET_H) - 1, Math.round(targetY)));
      if (Math.abs(nx - kvmX) > 2 || Math.abs(ny - kvmY) > 2) {
        movedTarget = true;
      }
      kvmX = nx;
      kvmY = ny;
    }
    if (isStreamInputEngine()) {
      const norm = coordsToNormalizedRatio(kvmX, kvmY);
      const mul = unit === 1 ? 36 : 1;
      sendParallelJson({
        type: "ptr_wheel",
        rx: norm.rx,
        ry: norm.ry,
        dx: dxPx * mul,
        dy: dyPx * mul,
      });
      return;
    }
    if (!rdpSession || !rdpMod) return;
    const evs = [];
    if (movedTarget) {
      evs.push(rdpMod.DeviceEvent.mouseMove(kvmX, kvmY));
    }
    const iy = Math.round(dyPx);
    const ix = Math.round(dxPx);
    if (iy !== 0) evs.push(rdpMod.DeviceEvent.wheelRotations(true, iy, unit));
    if (ix !== 0) evs.push(rdpMod.DeviceEvent.wheelRotations(false, ix, unit));
    if (evs.length > 0) applyRdpDeviceEvents(evs);
  }

  function rdpSendScancodeTap(codeName, withActiveMods = true) {
    if (!isRemoteConnected()) return;
    const modsToUse = withActiveMods ? Array.from(rdpActiveMods) : [];
    if (isStreamInputEngine()) {
      const srvKey = CODE_TO_SERVER_KEY[codeName];
      if (srvKey) {
        const mappedMods = modsToUse.map((m) => {
          if (m.startsWith("Control")) return "ctrl";
          if (m.startsWith("Alt")) return "alt";
          if (m.startsWith("Shift")) return "shift";
          return "cmd";
        });
        sendParallelJson({ type: "key_tap", key: srvKey, mods: mappedMods });
      }
      if (withActiveMods && rdpActiveMods.size > 0) {
        rdpActiveMods.clear();
        syncRdpModButtons();
      }
      return;
    }
    if (!rdpSession || !rdpMod) return;
    const sc = RDP_SCANCODE_MAP[codeName];
    if (sc === undefined) return;
    const evs = [];
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
    if (!isRemoteConnected() || !text) return;
    const str = String(text);
    if (rdpActiveMods.size > 0 && str.length === 1) {
      const lower = str.toLowerCase();
      if (CHAR_TO_CODE[lower]) {
        rdpSendScancodeTap(CHAR_TO_CODE[lower], true);
        return;
      }
    }
    if (isStreamInputEngine()) {
      sendParallelJson({ type: "unicode_text", text: str });
      return;
    }
    if (!rdpSession || !rdpMod) return;
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
    if (!isRemoteConnected()) return;
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
    if (isStreamInputEngine()) {
      if (txt) {
        sendParallelJson({ type: "unicode_text", text: txt });
      } else {
        sendParallelJson({ type: "combo", keys: ["ctrl", "v"] });
      }
      return;
    }
    if (!rdpSession || !rdpMod) return;
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

  function ensureRdpAudioContext() {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    if (!rdpAudioCtx) {
      try {
        rdpAudioCtx = new AudioCtx({ latencyHint: "interactive" });
      } catch {
        try {
          rdpAudioCtx = new AudioCtx();
        } catch {
          return null;
        }
      }
    }
    if (rdpAudioCtx && rdpAudioCtx.state === "suspended") {
      rdpAudioCtx.resume().catch(() => {});
    }
    return rdpAudioCtx;
  }

  function syncRdpAudioButtonsUI() {
    // Loa & Mic luôn hoạt động tự động dưới nền
  }

  function playRdpSpeakerPcm(arrayBuf) {
    if (!rdpSpkEnabled || !arrayBuf || arrayBuf.byteLength <= 3) return;
    const ctx = ensureRdpAudioContext();
    if (!ctx) return;
    const ch = rdpSpkChannels === 1 ? 1 : 2;
    const pcmByteLen = arrayBuf.byteLength - 1;
    const totalFrames = Math.floor(pcmByteLen / (ch * 2));
    if (totalFrames <= 0) return;

    try {
      const dv = new DataView(arrayBuf, 1, totalFrames * ch * 2);
      const audioBuf = ctx.createBuffer(ch, totalFrames, rdpSpkRate || 44100);
      if (ch === 2) {
        const left = audioBuf.getChannelData(0);
        const right = audioBuf.getChannelData(1);
        for (let i = 0, byteOff = 0; i < totalFrames; i += 1, byteOff += 4) {
          left[i] = dv.getInt16(byteOff, true) / 32768;
          right[i] = dv.getInt16(byteOff + 2, true) / 32768;
        }
      } else {
        const mono = audioBuf.getChannelData(0);
        for (let i = 0, byteOff = 0; i < totalFrames; i += 1, byteOff += 2) {
          mono[i] = dv.getInt16(byteOff, true) / 32768;
        }
      }

      const now = ctx.currentTime;
      if (rdpNextPlayTime < now + 0.012 || rdpNextPlayTime > now + 0.36) {
        rdpNextPlayTime = now + 0.042;
      }
      const src = ctx.createBufferSource();
      src.buffer = audioBuf;
      src.connect(ctx.destination);
      src.start(rdpNextPlayTime);
      rdpNextPlayTime += audioBuf.duration;
    } catch {
      // ignore transient decode error
    }
  }

  window.__onNativeMicPcm = (b64) => {
    if (
      !rdpMicEnabled ||
      !rdpServerMicOpen ||
      !rdpAudioWs ||
      rdpAudioWs.readyState !== WebSocket.OPEN ||
      !b64
    ) {
      return;
    }
    try {
      const bin = atob(b64);
      const len = bin.length;
      if (len <= 0) return;
      const pkt = new Uint8Array(1 + len);
      pkt[0] = 0x02;
      for (let i = 0; i < len; i += 1) {
        pkt[i + 1] = bin.charCodeAt(i);
      }
      rdpAudioWs.send(pkt);
    } catch {
      // ignore
    }
  };

  let rdpMicRetryTimer = null;
  let rdpAudioReconnectTimer = null;
  let activeAudioProxyUrl = "";
  let activeAudioSid = "";

  window.__onRemoteMicCaptureState = (running) => {
    if (!running && rdpServerMicOpen && rdpSession) {
      if (rdpMicRetryTimer !== null) clearTimeout(rdpMicRetryTimer);
      rdpMicRetryTimer = setTimeout(() => {
        rdpMicRetryTimer = null;
        if (rdpServerMicOpen && rdpSession && document.visibilityState === "visible") {
          void startRdpMicCapture(rdpServerMicSpec);
        }
      }, 850);
    }
  };

  async function startRdpMicCapture(spec) {
    const rate = (spec && spec.rate) || 44100;
    const channels = (spec && spec.channels) || 1;
    const framesPerPacket = (spec && spec.framesPerPacket) || 480;
    rdpServerMicSpec = { rate, channels, framesPerPacket };

    if (!rdpMicEnabled) return;

    if (
      hasAndroidBridge &&
      typeof window.AndroidBridge.startPcmMicCapture === "function"
    ) {
      try {
        window.AndroidBridge.startPcmMicCapture(rate, channels, framesPerPacket);
        return;
      } catch {
        // fallback Web Audio getUserMedia
      }
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    stopRdpMicCapture();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: rate,
          channelCount: channels,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const ctx = ensureRdpAudioContext();
      if (!ctx) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      rdpWebMicStream = stream;
      const source = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(1024, channels, channels);
      rdpWebMicProc = proc;
      proc.onaudioprocess = (ev) => {
        if (
          !rdpMicEnabled ||
          !rdpServerMicOpen ||
          !rdpAudioWs ||
          rdpAudioWs.readyState !== WebSocket.OPEN
        ) {
          return;
        }
        const ch0 = ev.inputBuffer.getChannelData(0);
        const ch1 = channels >= 2 && ev.inputBuffer.numberOfChannels >= 2
          ? ev.inputBuffer.getChannelData(1)
          : ch0;
        const frames = ch0.length;
        const out = new Uint8Array(1 + frames * channels * 2);
        out[0] = 0x02;
        const dv = new DataView(out.buffer, 1);
        if (channels >= 2) {
          for (let i = 0; i < frames; i += 1) {
            const s0 = Math.max(-1, Math.min(1, ch0[i]));
            const s1 = Math.max(-1, Math.min(1, ch1[i]));
            dv.setInt16(i * 4, s0 < 0 ? s0 * 32768 : s0 * 32767, true);
            dv.setInt16(i * 4 + 2, s1 < 0 ? s1 * 32768 : s1 * 32767, true);
          }
        } else {
          for (let i = 0; i < frames; i += 1) {
            const s0 = Math.max(-1, Math.min(1, ch0[i]));
            dv.setInt16(i * 2, s0 < 0 ? s0 * 32768 : s0 * 32767, true);
          }
        }
        rdpAudioWs.send(out);
      };
      source.connect(proc);
      proc.connect(ctx.destination);
    } catch {
      // ignore permission denied on web
    }
  }

  function stopRdpMicCapture() {
    if (
      hasAndroidBridge &&
      typeof window.AndroidBridge.stopPcmMicCapture === "function"
    ) {
      try {
        window.AndroidBridge.stopPcmMicCapture();
      } catch {
        // ignore
      }
    }
    if (rdpWebMicProc) {
      try {
        rdpWebMicProc.disconnect();
      } catch {
        // ignore
      }
      rdpWebMicProc.onaudioprocess = null;
      rdpWebMicProc = null;
    }
    if (rdpWebMicStream) {
      try {
        rdpWebMicStream.getTracks().forEach((t) => t.stop());
      } catch {
        // ignore
      }
      rdpWebMicStream = null;
    }
  }

  function closeRdpAudioWs(clearReconnect = true) {
    if (clearReconnect) {
      activeAudioProxyUrl = "";
      activeAudioSid = "";
      if (rdpAudioReconnectTimer !== null) {
        clearTimeout(rdpAudioReconnectTimer);
        rdpAudioReconnectTimer = null;
      }
      if (rdpMicRetryTimer !== null) {
        clearTimeout(rdpMicRetryTimer);
        rdpMicRetryTimer = null;
      }
    }
    rdpServerMicOpen = false;
    stopRdpMicCapture();
    if (rdpAudioWs) {
      try {
        rdpAudioWs.onclose = null;
        rdpAudioWs.onerror = null;
        rdpAudioWs.onmessage = null;
        rdpAudioWs.close();
      } catch {
        // ignore
      }
      rdpAudioWs = null;
    }
  }

  function openRdpAudioWs(baseProxyWsUrl, sid) {
    closeRdpAudioWs(false);
    activeAudioProxyUrl = baseProxyWsUrl;
    activeAudioSid = sid;
    try {
      const au = new URL(baseProxyWsUrl);
      au.pathname = "/rdp-audio-ws";
      au.searchParams.set("sid", sid);
      const sock = new WebSocket(au.toString());
      sock.binaryType = "arraybuffer";
      sock.onmessage = (ev) => {
        if (ev.data instanceof ArrayBuffer) {
          const b0 = new Uint8Array(ev.data, 0, 1)[0];
          if (b0 === 0x01) {
            playRdpSpeakerPcm(ev.data);
          }
          return;
        }
        if (typeof ev.data === "string") {
          try {
            const msg = JSON.parse(ev.data);
            if (msg.type === "spk_format") {
              rdpSpkRate = Number(msg.rate) || 44100;
              rdpSpkChannels = Number(msg.channels) || 2;
              rdpNextPlayTime = 0;
            } else if (msg.type === "mic_start") {
              rdpServerMicOpen = true;
              void startRdpMicCapture(msg);
            } else if (msg.type === "mic_stop") {
              rdpServerMicOpen = false;
              stopRdpMicCapture();
            }
          } catch {
            // ignore
          }
        }
      };
      sock.onclose = () => {
        if (rdpAudioWs === sock) {
          rdpAudioWs = null;
          rdpServerMicOpen = false;
          stopRdpMicCapture();
          // Tự động nối lại luồng Loa + Mic liên tục nếu phiên RDP vẫn đang mở
          if (activeAudioSid === sid && activeAudioProxyUrl === baseProxyWsUrl) {
            if (rdpAudioReconnectTimer !== null) clearTimeout(rdpAudioReconnectTimer);
            rdpAudioReconnectTimer = setTimeout(() => {
              rdpAudioReconnectTimer = null;
              if (activeAudioSid === sid && rdpSession) {
                openRdpAudioWs(baseProxyWsUrl, sid);
              }
            }, 550);
          }
        }
      };
      rdpAudioWs = sock;
    } catch {
      // ignore
    }
  }

  function resolveMacHttpBase() {
    if (ws && ws.readyState === WebSocket.OPEN && ws.url) {
      try {
        const u = new URL(ws.url);
        const proto = u.protocol === "wss:" ? "https:" : "http:";
        return `${proto}//${u.host}`;
      } catch {
        // ignore
      }
    }
    const cands = resolveCandidateHosts();
    if (cands.length > 0) {
      const clean = cands[0].replace(/^https?:\/\/|^wss?:\/\//, "").split("/")[0];
      if (clean) return `http://${clean}`;
    }
    return "http://192.168.52.103:5050";
  }

  function resolvePcHttpBase() {
    const raw = (rdpHostInput ? rdpHostInput.value : "192.168.52.230")
      .trim()
      .replace(/^https?:\/\/|^wss?:\/\//, "")
      .split(":")[0]
      .trim();
    return raw ? `http://${raw}:5051` : "http://192.168.52.230:5051";
  }

  async function probeParallelEndpoint(baseUrl, timeoutMs = 850) {
    const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const t = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
    try {
      const res = await fetch(`${baseUrl}/rdp-mode-check`, {
        cache: "no-store",
        signal: ctrl ? ctrl.signal : undefined,
      });
      if (!res.ok) return null;
      const j = await res.json();
      if (j && j.parallel_available) {
        return {
          available: true,
          macBase: baseUrl,
          source: j.source || "mac",
          window: j.window || null,
        };
      }
      return null;
    } catch {
      return null;
    } finally {
      if (t) clearTimeout(t);
    }
  }

  async function checkMacParallelAvailable() {
    const pcBase = resolvePcHttpBase();
    const macBase = resolveMacHttpBase();
    // 1. Ưu tiên kiểm tra luồng Song song trực tiếp trên PC chính (:5051) -> mở PC chính không bao giờ đá Điện thoại!
    const pcRes = await probeParallelEndpoint(pcBase, 650);
    if (pcRes) return pcRes;
    // 2. Nếu PC chính đang khóa màn hình / MacBook đang remote -> lấy luồng Song song từ MacBook (:5050)
    const macRes = await probeParallelEndpoint(macBase, 1000);
    if (macRes) return macRes;
    return { available: false, macBase };
  }

  function clearRemoteCanvas() {
    if (!remoteCanvas) return;
    try {
      const ctx2d = remoteCanvas.getContext("2d", { alpha: false });
      if (ctx2d) {
        ctx2d.fillStyle = "#090c12";
        ctx2d.fillRect(0, 0, remoteCanvas.width || 1, remoteCanvas.height || 1);
      }
    } catch {
      // ignore
    }
  }

  function closeParallelRdpWs() {
    parallelQueuedBuf = null;
    if (rdpParallelWs) {
      try {
        rdpParallelWs.onopen = null;
        rdpParallelWs.onmessage = null;
        rdpParallelWs.onerror = null;
        rdpParallelWs.onclose = null;
        rdpParallelWs.close();
      } catch {
        // ignore
      }
      rdpParallelWs = null;
    }
  }

  async function renderParallelJpegFrame(buf) {
    if (!remoteCanvas || !buf || buf.byteLength <= 6) return;
    if (parallelDecoding) {
      parallelQueuedBuf = buf;
      return;
    }
    parallelDecoding = true;
    try {
      let cur = buf;
      while (cur) {
        parallelQueuedBuf = null;
        const jpegSlice = new Uint8Array(cur, 5);
        const blob = new Blob([jpegSlice], { type: "image/jpeg" });
        const bmp = await createImageBitmap(blob);
        if (remoteCanvas.width !== bmp.width || remoteCanvas.height !== bmp.height) {
          const prevW = remoteCanvas.width || RDP_TARGET_W;
          const prevH = remoteCanvas.height || RDP_TARGET_H;
          kvmX = Math.round((kvmX / prevW) * bmp.width);
          kvmY = Math.round((kvmY / prevH) * bmp.height);
          remoteCanvas.width = bmp.width;
          remoteCanvas.height = bmp.height;
          setRemoteStageAspect(bmp.width, bmp.height);
        }
        const ctx2d = remoteCanvas.getContext("2d", { alpha: false });
        if (ctx2d) {
          ctx2d.imageSmoothingEnabled = true;
          if ("imageSmoothingQuality" in ctx2d) {
            ctx2d.imageSmoothingQuality = "high";
          }
          ctx2d.drawImage(bmp, 0, 0);
        }
        bmp.close();
        cur = parallelQueuedBuf;
      }
    } catch {
      // ignore single frame error
    } finally {
      parallelDecoding = false;
    }
  }

  let macExtDisplayActive = false;
  let macExtDisplayBusy = false;

  function setMacExtStatus(msg, isInfo = true) {
    if (!macExtStatus) return;
    macExtStatus.textContent = String(msg || "");
    macExtStatus.classList.toggle("is-info", Boolean(isInfo));
    macExtStatus.classList.remove("is-hidden");
  }

  function syncMacExtTouchUI() {
    if (btnMacExtTouch) {
      btnMacExtTouch.classList.toggle("is-active", macExtTouchMode !== "off");
    }
    if (lblMacExtTouch) {
      lblMacExtTouch.textContent =
        macExtTouchMode === "pointer"
          ? "Trackpad"
          : macExtTouchMode === "off"
            ? "Khóa chạm"
            : "Cảm ứng";
    }
  }

  function syncMacExtDisplayUI() {
    syncMacExtTouchUI();
    if (btnMacExtDisplay) {
      btnMacExtDisplay.classList.toggle("is-active", macExtDisplayActive);
      btnMacExtDisplay.disabled = macExtDisplayBusy;
    }
    if (lblMacExtDisplay) {
      lblMacExtDisplay.textContent = macExtDisplayBusy
        ? "Đang đổi..."
        : macExtDisplayActive
          ? "Tắt màn phụ"
          : "Bật màn phụ";
    }
  }

  function closeMacExtWs() {
    parallelQueuedBuf = null;
    macExtCursorVisible = false;
    if (macExtReconnectTimer !== null) {
      clearTimeout(macExtReconnectTimer);
      macExtReconnectTimer = null;
    }
    if (macExtWs) {
      try {
        macExtWs.onopen = null;
        macExtWs.onmessage = null;
        macExtWs.onerror = null;
        macExtWs.onclose = null;
        macExtWs.close();
      } catch {
        // ignore
      }
      macExtWs = null;
    }
    clearRemoteCanvas();
    updateOverlayCursorVisual();
  }

  function startMacExtStream(macBase) {
    return new Promise((resolve, reject) => {
      closeMacExtWs();
      const wsUrl = `${macBase.replace(/^http/, "ws")}/mac-virtual-display-ws`;
      let settled = false;
      const sock = new WebSocket(wsUrl);
      sock.binaryType = "arraybuffer";
      macExtWs = sock;

      const openTimer = setTimeout(() => {
        if (!settled) {
          settled = true;
          closeMacExtWs();
          reject(new Error("Quá thời gian mở luồng Màn phụ Mac."));
        }
      }, 2800);

      sock.onopen = () => {
        if (settled) return;
        settled = true;
        clearTimeout(openTimer);
        macExtReconnectRetries = 0;
        if (macExtReconnectTimer !== null) {
          clearTimeout(macExtReconnectTimer);
          macExtReconnectTimer = null;
        }
        cursorHiddenByServer = false;
        cursorHotspotX = 1;
        cursorHotspotY = 1;
        if (remoteCursorImg) remoteCursorImg.classList.add("is-hidden");
        if (remoteCursorSvg) remoteCursorSvg.classList.remove("is-hidden");
        if (remoteCanvas) remoteCanvas.style.cursor = "none";
        if (macExtOverlay) macExtOverlay.classList.add("is-hidden");
        setRemoteHudExpanded(false);
        syncMacExtDisplayUI();
        syncRdpConnectionUI();
        pushKvmConfigToServer();
        resolve(true);
      };

      sock.onmessage = (ev) => {
        if (ev.data instanceof ArrayBuffer) {
          if (ev.data.byteLength < 2) return;
          const b0 = new Uint8Array(ev.data, 0, 1)[0];
          if (b0 === 0x10) {
            void renderParallelJpegFrame(ev.data);
          }
          return;
        }
        if (typeof ev.data === "string") {
          try {
            const msg = JSON.parse(ev.data);
            if (msg.type === "cursor") {
              macExtCursorVisible = Boolean(msg.vis);
              if (macExtCursorVisible && remoteCanvas) {
                const cw = remoteCanvas.width || RDP_TARGET_W;
                const ch = remoteCanvas.height || RDP_TARGET_H;
                kvmX = Math.max(0, Math.min(cw, (Number(msg.rx) || 0) * cw));
                kvmY = Math.max(0, Math.min(ch, (Number(msg.ry) || 0) * ch));
              }
              updateOverlayCursorVisual();
            } else if (msg.type === "vdisp_ended") {
              closeMacExtWs();
              macExtDisplayActive = false;
              syncMacExtDisplayUI();
              syncRdpConnectionUI();
              if (kbLayout === "mac_ext" && macExtOverlay) {
                setMacExtStatus("Đã tắt Màn hình phụ #2 trên MacBook.", false);
                macExtOverlay.classList.remove("is-hidden");
              }
            }
          } catch {
            // ignore
          }
        }
      };

      sock.onerror = () => {
        if (!settled) {
          settled = true;
          clearTimeout(openTimer);
          closeMacExtWs();
          reject(new Error("Lỗi kết nối luồng Màn phụ Mac."));
        }
      };

      sock.onclose = () => {
        if (macExtWs === sock) {
          macExtWs = null;
          syncMacExtDisplayUI();
          syncRdpConnectionUI();
          if (!macExtManualStop && macExtDisplayActive && kbLayout === "mac_ext") {
            const backoff = [600, 1200, 2000, 3000, 4500];
            if (macExtReconnectRetries < backoff.length) {
              const waitMs = backoff[macExtReconnectRetries];
              macExtReconnectRetries += 1;
              if (macExtReconnectTimer !== null) clearTimeout(macExtReconnectTimer);
              macExtReconnectTimer = setTimeout(() => {
                macExtReconnectTimer = null;
                if (macExtDisplayActive && !macExtManualStop && kbLayout === "mac_ext" && !isMacExtConnected()) {
                  void startMacExtStream(macBase).catch(() => {});
                }
              }, waitMs);
            } else if (macExtOverlay) {
              setMacExtStatus("Mất kết nối Wi-Fi tới MacBook — bấm Kết nối lại.", false);
              macExtOverlay.classList.remove("is-hidden");
            }
          }
        }
      };
    });
  }

  function startParallelRdpSession(macBase) {
    return new Promise((resolve, reject) => {
      closeParallelRdpWs();
      closeRdpAudioWs();
      if (rdpSession) {
        try {
          rdpSession.shutdown();
        } catch {
          // ignore
        }
        rdpSession = null;
      }

      const wsUrl = `${macBase.replace(/^http/, "ws")}/rdp-parallel-ws`;
      let settled = false;
      const sock = new WebSocket(wsUrl);
      sock.binaryType = "arraybuffer";
      rdpParallelWs = sock;

      const openTimer = setTimeout(() => {
        if (!settled) {
          settled = true;
          closeParallelRdpWs();
          reject(new Error("Quá thời gian mở luồng Song song."));
        }
      }, 2200);

      sock.onopen = () => {
        if (settled) return;
        settled = true;
        clearTimeout(openTimer);
        rdpActiveEngine = "parallel";
        cursorHiddenByServer = false;
        cursorHotspotX = 1;
        cursorHotspotY = 1;
        if (remoteCursorImg) remoteCursorImg.classList.add("is-hidden");
        if (remoteCursorSvg) remoteCursorSvg.classList.remove("is-hidden");
        remoteCanvas.style.cursor = "none";
        rdpConnecting = false;
        setRdpStatus("", true);
        if (remoteLoginOverlay) remoteLoginOverlay.classList.add("is-hidden");
        setRemoteHudExpanded(false);
        syncRdpConnectionUI();
        pushKvmConfigToServer();
        resolve(true);
      };

      sock.onmessage = (ev) => {
        if (ev.data instanceof ArrayBuffer) {
          if (ev.data.byteLength < 2) return;
          const b0 = new Uint8Array(ev.data, 0, 1)[0];
          if (b0 === 0x10) {
            void renderParallelJpegFrame(ev.data);
          } else if (b0 === 0x01) {
            playRdpSpeakerPcm(ev.data);
          }
          return;
        }
        if (typeof ev.data === "string") {
          try {
            const msg = JSON.parse(ev.data);
            if (msg.type === "spk_format") {
              rdpSpkRate = Number(msg.rate) || 44100;
              rdpSpkChannels = Number(msg.channels) || 2;
              rdpNextPlayTime = 0;
            } else if (msg.type === "parallel_ended") {
              closeParallelRdpWs();
              rdpActiveEngine = "none";
              syncRdpConnectionUI();
              if (!rdpManualDisconnect && kbLayout === "remote") {
                // Tự chuyển mượt giữa PC chính <-> MacBook khi đổi máy mà không làm thoát Remote trên Điện thoại!
                void (async () => {
                  for (const waitMs of [250, 800, 1600]) {
                    await new Promise((r) => setTimeout(r, waitMs));
                    if (rdpManualDisconnect || kbLayout !== "remote" || isRemoteConnected() || rdpConnecting) return;
                    const chk = await checkMacParallelAvailable();
                    if (chk.available) {
                      void connectRdpSession();
                      return;
                    }
                  }
                  if (kbLayout === "remote" && remoteLoginOverlay && !isRemoteConnected()) {
                    setRdpStatus("Màn hình nguồn đã đóng — bấm Kết nối khi muốn mở lại trên ĐT.", false);
                    remoteLoginOverlay.classList.remove("is-hidden");
                  }
                })();
                return;
              }
              if (kbLayout === "remote" && remoteLoginOverlay) {
                setRdpStatus("Đã ngắt luồng Song song.", false);
                remoteLoginOverlay.classList.remove("is-hidden");
              }
            }
          } catch {
            // ignore
          }
        }
      };

      sock.onerror = () => {
        if (!settled) {
          settled = true;
          clearTimeout(openTimer);
          closeParallelRdpWs();
          reject(new Error("Lỗi kết nối luồng Song song."));
        }
      };

      sock.onclose = () => {
        if (rdpParallelWs === sock) {
          rdpParallelWs = null;
          if (rdpActiveEngine === "parallel") {
            rdpActiveEngine = "none";
          }
          syncRdpConnectionUI();
          if (settled && !rdpManualDisconnect && kbLayout === "remote") {
            if (canAutoReconnectRdp()) {
              setTimeout(async () => {
                if (rdpManualDisconnect || kbLayout !== "remote" || isRemoteConnected() || rdpConnecting) {
                  return;
                }
                const chk = await checkMacParallelAvailable();
                if (chk.available) {
                  void connectRdpSession();
                } else if (remoteLoginOverlay) {
                  setRdpStatus("Phiên Remote đã tạm dừng để không khóa PC chính.", false);
                  remoteLoginOverlay.classList.remove("is-hidden");
                }
              }, 550);
              return;
            }
            if (remoteLoginOverlay) {
              setRdpStatus("Phiên Song song đã ngắt.", false);
              remoteLoginOverlay.classList.remove("is-hidden");
            }
          }
        }
      };
    });
  }

  async function connectRdpSession() {
    if (rdpConnecting || !remoteCanvas) return;
    rdpManualDisconnect = false;
    ensureRdpAudioContext();

    rdpConnecting = true;
    syncRdpConnectionUI();

    // 1. Nếu không khóa cứng chế độ Độc quyền -> kiểm tra xem MacBook đang mở Microsoft Remote Desktop không.
    //    Nếu có -> vào thẳng chế độ Song song (⚡ Song song) trong ~0.1s, cả 2 máy cùng chạy không bao giờ đá nhau!
    if (!rdpPreferExclusive) {
      setRdpStatus("Đang kiểm tra kết nối Song song...", true);
      const parCheck = await checkMacParallelAvailable();
      if (parCheck.available) {
        try {
          await startParallelRdpSession(parCheck.macBase);
          return;
        } catch {
          // Nếu lỗi bất ngờ thì rơi xuống kết nối Native RDP trực tiếp
        }
      }
    }

    const rawHost = (rdpHostInput ? rdpHostInput.value : "192.168.52.230").trim() || "192.168.52.230";
    const rawUser = (rdpUserInput ? rdpUserInput.value : "DESKTOP-4LTT2HE\\User").trim() || "DESKTOP-4LTT2HE\\User";
    const rawPass = rdpPassInput ? rdpPassInput.value : "";

    if (!rawPass) {
      rdpConnecting = false;
      syncRdpConnectionUI();
      if (remoteLoginOverlay) remoteLoginOverlay.classList.remove("is-hidden");
      setRdpStatus("Nhập mật khẩu Windows PC để kết nối.", false);
      if (rdpPassInput) rdpPassInput.focus();
      return;
    }

    closeParallelRdpWs();
    if (rdpSession) {
      try {
        rdpSession.shutdown();
      } catch {
        // ignore
      }
      rdpSession = null;
    }

    setRemoteStageAspect(RDP_TARGET_W, RDP_TARGET_H);
    setRdpStatus(`Đang khởi tạo kết nối 2248×1080 (${rdpDesktopScale}%)...`, true);

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
          const sid =
            "s" +
            Date.now().toString(36) +
            Math.random().toString(36).slice(2, 8);
          const sessionUrlObj = new URL(proxyWsUrl);
          sessionUrlObj.searchParams.set("sid", sid);
          openRdpAudioWs(proxyWsUrl, sid);

          const initW =
            rdpDesktopScale === 100 ? RDP_TARGET_W : RDP_TARGET_W - 2;
          const builder = new mod.SessionBuilder();
          builder.username(username);
          if (domain) builder.serverDomain(domain);
          builder.password(rawPass);
          builder.destination(dest);
          builder.proxyAddress(sessionUrlObj.toString());
          builder.authToken("local");
          builder.desktopSize(new mod.DesktopSize(initW, RDP_TARGET_H));
          builder.renderCanvas(remoteCanvas);
          builder.extension(new mod.Extension("enable_credssp", true));
          builder.extension(new mod.Extension("display_control", true));
          builder.extension(new mod.Extension("enable_server_pointer", true));
          builder.extension(
            new mod.Extension("print_job_stream_callbacks", {
              onJobData: () => {},
              onJobComplete: () => {},
            })
          );

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

          connectedSession = await Promise.race([
            builder.connect(),
            new Promise((_, rej) =>
              setTimeout(
                () => rej(new Error("Quá thời gian bắt tay RDP (7.5s).")),
                7500
              )
            ),
          ]);
          break;
        } catch (err) {
          closeRdpAudioWs();
          lastErr = err;
          if (err && typeof err.kind === "function" && (err.kind() === 1 || err.kind() === 2)) {
            break;
          }
        }
      }

      if (!connectedSession) {
        throw lastErr || new Error("Không kết nối được tới PC.");
      }

      rdpSession = connectedSession;
      rdpActiveEngine = "native";
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
      setRemoteStageAspect(remoteCanvas.width, remoteCanvas.height);

      rdpConnecting = false;
      setRdpStatus("", true);
      if (remoteLoginOverlay) remoteLoginOverlay.classList.add("is-hidden");
      setRemoteHudExpanded(false);
      syncRdpConnectionUI();
      pushKvmConfigToServer();
      if (
        rdpMicEnabled &&
        hasAndroidBridge &&
        typeof window.AndroidBridge.ensureMicPermission === "function"
      ) {
        try {
          window.AndroidBridge.ensureMicPermission();
        } catch {
          // ignore
        }
      }

      if (
        rdpDesktopScale !== 100 ||
        remoteCanvas.width !== RDP_TARGET_W ||
        remoteCanvas.height !== RDP_TARGET_H
      ) {
        const activeRef = connectedSession;
        const triggerInitialScale = () => {
          if (rdpSession !== activeRef || !remoteCanvas) return;
          if (
            remoteCanvas.width === RDP_TARGET_W &&
            remoteCanvas.height === RDP_TARGET_H
          ) {
            setRemoteStageAspect(RDP_TARGET_W, RDP_TARGET_H);
            return;
          }
          applyLiveRdpDesktopScale(false);
        };
        for (const delayMs of [350, 850, 1500, 2400, 3600, 5000]) {
          setTimeout(triggerInitialScale, delayMs);
        }
      }

      const handleNativeEnded = async (errObj) => {
        rdpSession = null;
        if (rdpActiveEngine === "native") rdpActiveEngine = "none";
        closeRdpAudioWs();
        syncRdpConnectionUI();
        if (!rdpManualDisconnect && kbLayout === "remote") {
          // 1. Kiểm tra kỹ 2 nhịp xem MacBook vừa mở Microsoft Remote Desktop không -> nếu có thì sang thẳng Song song, tuyệt đối không giành lại cổng :3389!
          for (const waitMs of [320, 680]) {
            await new Promise((r) => setTimeout(r, waitMs));
            const chk = await checkMacParallelAvailable();
            if (chk.available) {
              rdpPreferExclusive = false;
              rdpConnecting = true;
              syncRdpConnectionUI();
              try {
                await startParallelRdpSession(chk.macBase);
                return;
              } catch {
                rdpConnecting = false;
                syncRdpConnectionUI();
              }
            }
          }
          // 2. Chỉ tự nối lại khi rớt mạng socket bất ngờ; TUYỆT ĐỐI KHÔNG tự giật lại cổng :3389 khi người dùng mở khóa PC chính (`errObj === null` / nhường phiên)!
          if (isTransientSocketRdpDrop(errObj) && canAutoReconnectRdp()) {
            void connectRdpSession();
            return;
          }
        }
        if (kbLayout === "remote" && remoteLoginOverlay) {
          setRdpStatus(
            errObj
              ? formatIronRdpError(errObj)
              : "Đã nhường phiên cho PC chính (bấm Kết nối khi muốn dùng lại trên ĐT).",
            false
          );
          remoteLoginOverlay.classList.remove("is-hidden");
        }
      };

      rdpSession
        .run()
        .then(() => handleNativeEnded(null))
        .catch((runErr) => handleNativeEnded(runErr));
    } catch (err) {
      closeRdpAudioWs();
      rdpConnecting = false;
      rdpSession = null;
      rdpActiveEngine = "none";
      syncRdpConnectionUI();
      if (remoteLoginOverlay) remoteLoginOverlay.classList.remove("is-hidden");
      setRdpStatus(formatIronRdpError(err), false);
    }
  }

  async function toggleMacExtDisplay(forceState = null, returnToKbOnOff = true) {
    const want = typeof forceState === "boolean" ? forceState : !macExtDisplayActive;
    // Cho phép TẮT ngay lập tức kể cả khi đang kết nối dở, tránh để lại màn ảo mồ côi trên MacBook
    if (want && macExtDisplayBusy) return;
    const macBase = resolveMacHttpBase();
    macExtDisplayBusy = true;
    syncMacExtDisplayUI();
    closeAllRemoteSubMenus();

    if (want) {
      macExtManualStop = false;
      setMacExtStatus("Đang bật Màn phụ bên trái MacBook...", true);
      if (macExtOverlay) macExtOverlay.classList.remove("is-hidden");
    } else {
      macExtManualStop = true;
      macExtDisplayActive = false;
      closeMacExtWs();
      syncRdpConnectionUI();
      if (kbLayout === "mac_ext" && macExtOverlay) {
        setMacExtStatus("Đang tắt Màn phụ trên MacBook...", true);
        macExtOverlay.classList.remove("is-hidden");
      }
    }

    try {
      const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
      const timer = ctrl ? setTimeout(() => ctrl.abort(), 16000) : null;
      let resData = null;
      try {
        const res = await fetch(`${macBase}/mac-virtual-display/toggle`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enable: want,
            logical_w: 1798,
            logical_h: 864,
            hidpi: true,
          }),
          signal: ctrl ? ctrl.signal : undefined,
        });
        resData = await res.json();
      } finally {
        if (timer) clearTimeout(timer);
      }

      if (want) {
        // Nếu người dùng đã rời tab Màn phụ trong lúc chờ MacBook bật -> tự tắt luôn
        if (kbLayout !== "mac_ext" || macExtManualStop) {
          macExtDisplayActive = false;
          fetch(`${macBase}/mac-virtual-display/toggle`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enable: false }),
          }).catch(() => {});
          return;
        }
        if (!resData || !resData.ok || !resData.active) {
          const msg = (resData && resData.error) || "Không bật được Màn phụ trên MacBook.";
          macExtDisplayActive = false;
          setMacExtStatus(msg, false);
          if (macExtOverlay) macExtOverlay.classList.remove("is-hidden");
          return;
        }
        macExtDisplayActive = true;
        try {
          await startMacExtStream(macBase);
        } catch {
          if (kbLayout !== "mac_ext" || macExtManualStop) return;
          await new Promise((r) => setTimeout(r, 450));
          await startMacExtStream(macBase);
        }
      } else {
        macExtDisplayActive = false;
        if (returnToKbOnOff && kbLayout === "mac_ext") {
          selectKeyboardLayout(lastNonRemoteLayout || "pad");
        }
      }
    } catch (err) {
      macExtDisplayActive = false;
      const errDetail = err && err.message ? ` (${err.message})` : "";
      if (kbLayout === "mac_ext") {
        setMacExtStatus(`Không kết nối được MacBook (:5050)${errDetail}`, false);
        if (macExtOverlay) macExtOverlay.classList.remove("is-hidden");
      }
    } finally {
      macExtDisplayBusy = false;
      syncMacExtDisplayUI();
      syncRdpConnectionUI();
    }
  }

  function disconnectRdpSession(silent = false) {
    rdpManualDisconnect = true;
    closeParallelRdpWs();
    closeRdpAudioWs();
    clearRemoteCanvas();
    if (rdpSession) {
      try {
        rdpSession.shutdown();
      } catch {
        // ignore
      }
      rdpSession = null;
    }
    rdpActiveEngine = "none";
    rdpConnecting = false;
    if (kvmActive) {
      sendPayload({ type: "kvm_set", captured: false });
    }
    kvmActive = false;
    syncSmartKvmButtonsUI();
    updateOverlayCursorVisual();
    syncRdpConnectionUI();
    if (!silent) {
      setRdpStatus("Đã ngắt kết nối.", false);
      if (remoteLoginOverlay && kbLayout === "remote") {
        remoteLoginOverlay.classList.remove("is-hidden");
      }
    }
  }

  // ── Nút điều khiển hợp nhất chia 2 phần: Cảm ứng (Chạm / Bàn rê ảo) | Chuột (MacBook / Điện thoại / Cả 2 màn hình) ──
  function setRemoteControlMode(ctrlMode) {
    let resolved = ctrlMode;
    if (ctrlMode === "mouse_mac") {
      // Chọn "Chuột MacBook" -> khóa chuột về MacBook; giữ Bàn rê ảo nếu đang dùng, ngược lại về Chạm cảm ứng
      resolved = rdpControlMode === "pointer_mac" ? "pointer_mac" : "touch_mac";
    }
    if (
      resolved !== "touch_mac" &&
      resolved !== "pointer_mac" &&
      resolved !== "mouse_phone" &&
      resolved !== "mouse_bridge"
    ) {
      return;
    }
    applyDerivedControlModes(resolved);
    kvmButtonsMask = 0;
    kvmBridgeReturnPush = 0;
    try {
      localStorage.setItem("mac_kb_rdp_ctrl_mode", rdpControlMode);
      localStorage.setItem("mac_kb_rdp_input_mode", rdpInputMode);
      localStorage.setItem("mac_kb_rdp_mouse_mode", rdpMouseMode);
    } catch {
      // ignore
    }

    if (rdpMouseMode === "mac") {
      kvmActive = false;
      if (rdpControlMode !== "pointer_mac") {
        localPointerVisible = false;
      }
    }

    if (rdpInputMode === "pointer") {
      const cw = remoteCanvas ? remoteCanvas.width || RDP_TARGET_W : RDP_TARGET_W;
      const ch = remoteCanvas ? remoteCanvas.height || RDP_TARGET_H : RDP_TARGET_H;
      if (kvmX <= 2 || kvmX >= cw - 2 || kvmY <= 2 || kvmY >= ch - 2) {
        kvmX = Math.round(cw * 0.5);
        kvmY = Math.round(ch * 0.5);
      }
      if (rdpControlMode === "pointer_mac") {
        showLocalRemoteCursor(kvmX, kvmY, 2200);
      }
      if (isRemoteConnected()) {
        rdpSendMouseMove(kvmX, kvmY);
      }
    } else {
      localPointerVisible = false;
    }

    // Giữ nguyên kết nối hiện tại (Song song hoặc Độc quyền), tuyệt đối KHÔNG đóng hay đá phiên Remote trên Mac!
    syncRemoteControlModeUI();
    pushKvmConfigToServer();
  }

  handleKvmServerMessage = (msg) => {
    if (!msg) return;
    if (msg.mode && (msg.mode === "mac" || msg.mode === "phone" || msg.mode === "bridge")) {
      if (msg.mode !== rdpMouseMode) {
        if (msg.mode === "phone") {
          applyDerivedControlModes("mouse_phone");
        } else if (msg.mode === "bridge") {
          applyDerivedControlModes("mouse_bridge");
        } else if (rdpControlMode === "mouse_phone" || rdpControlMode === "mouse_bridge") {
          applyDerivedControlModes("touch_mac");
        } else {
          rdpMouseMode = "mac";
        }
        try {
          localStorage.setItem("mac_kb_rdp_ctrl_mode", rdpControlMode);
          localStorage.setItem("mac_kb_rdp_input_mode", rdpInputMode);
          localStorage.setItem("mac_kb_rdp_mouse_mode", rdpMouseMode);
        } catch {
          // ignore
        }
      }
    }

    if (msg.type === "kvm_released" || (msg.type === "kvm_state" && !msg.captured)) {
      kvmActive = false;
      kvmButtonsMask = 0;
      kvmBridgeReturnPush = 0;
      syncSmartKvmButtonsUI();
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

    if (kbLayout !== "remote" || rdpMouseMode === "mac") {
      sendPayload({ type: "kvm_set", captured: false });
      return;
    }

    const cw = remoteCanvas ? remoteCanvas.width || RDP_TARGET_W : RDP_TARGET_W;
    const ch = remoteCanvas ? remoteCanvas.height || RDP_TARGET_H : RDP_TARGET_H;

    if (msg.type === "kvm_state" && msg.captured) {
      kvmActive = true;
      kvmButtonsMask = 0;
      kvmBridgeReturnPush = 0;
      const yr = Math.max(0.02, Math.min(0.98, Number(msg.y_ratio) || 0.5));
      if (msg.enter_edge === "right") {
        // Di từ mép TRÁI của MacBook -> đi vào mép PHẢI của Điện thoại đúng cao độ y_ratio
        kvmBridgeEntryEdge = "right";
        kvmX = Math.max(0, cw - 4);
        kvmY = Math.round(yr * (ch - 1));
      } else if (msg.enter_edge === "left") {
        // Di từ mép PHẢI của MacBook -> đi vào mép TRÁI của Điện thoại đúng cao độ y_ratio
        kvmBridgeEntryEdge = "left";
        kvmX = Math.min(cw - 1, 4);
        kvmY = Math.round(yr * (ch - 1));
      } else if (kvmX <= 4 || kvmX >= cw - 4 || kvmY <= 4 || kvmY >= ch - 4) {
        kvmX = Math.round(cw * 0.5);
        kvmY = Math.round(ch * 0.5);
      }
      syncSmartKvmButtonsUI();
      updateOverlayCursorVisual();
      rdpSendMouseMove(kvmX, kvmY);
      return;
    }

    if (msg.type === "kvm_mouse") {
      if (!kvmActive) {
        kvmActive = true;
        syncSmartKvmButtonsUI();
      }
      if (msg.ev === "move") {
        const scale = 1.35;
        const dx = (Number(msg.dx) || 0) * scale;
        const dy = (Number(msg.dy) || 0) * scale;

        // Chế độ 3 (`bridge`): di ngược qua mép nối -> ẩn hẳn chuột trên Điện thoại và trả về đúng mép của MacBook
        if (rdpMouseMode === "bridge" && kvmButtonsMask === 0) {
          if (kvmBridgeEntryEdge === "right" && kvmX >= cw - 3 && dx > 0) {
            kvmBridgeReturnPush += dx;
            if (kvmBridgeReturnPush >= 6) {
              const exitYRatio = kvmY / Math.max(1, ch - 1);
              kvmActive = false;
              localPointerVisible = false;
              kvmBridgeReturnPush = 0;
              syncSmartKvmButtonsUI();
              updateOverlayCursorVisual();
              if (rdpSession) {
                try {
                  rdpSession.releaseAllInputs();
                } catch {
                  // ignore
                }
              }
              sendPayload({
                type: "kvm_bridge_return",
                return_edge: "left",
                y_ratio: +Math.max(0.02, Math.min(0.98, exitYRatio)).toFixed(4),
              });
              return;
            }
          } else if (kvmBridgeEntryEdge === "left" && kvmX <= 3 && dx < 0) {
            kvmBridgeReturnPush += -dx;
            if (kvmBridgeReturnPush >= 6) {
              const exitYRatio = kvmY / Math.max(1, ch - 1);
              kvmActive = false;
              localPointerVisible = false;
              kvmBridgeReturnPush = 0;
              syncSmartKvmButtonsUI();
              updateOverlayCursorVisual();
              if (rdpSession) {
                try {
                  rdpSession.releaseAllInputs();
                } catch {
                  // ignore
                }
              }
              sendPayload({
                type: "kvm_bridge_return",
                return_edge: "right",
                y_ratio: +Math.max(0.02, Math.min(0.98, exitYRatio)).toFixed(4),
              });
              return;
            }
          } else if (kvmX > 10 && kvmX < cw - 10) {
            kvmBridgeReturnPush = 0;
          }
        }

        kvmX = Math.max(0, Math.min(cw - 1, kvmX + dx));
        kvmY = Math.max(0, Math.min(ch - 1, kvmY + dy));
        autoPanViewportForCursor();
        rdpSendMouseMove(kvmX, kvmY);
      } else if (msg.ev === "down") {
        const b = Number(msg.btn) || 0;
        kvmButtonsMask |= 1 << b;
        rdpSendMouseDown(kvmX, kvmY, b, 1);
      } else if (msg.ev === "up") {
        const b = Number(msg.btn) || 0;
        kvmButtonsMask &= ~(1 << b);
        rdpSendMouseUp(kvmX, kvmY, b, 1);
      } else if (msg.ev === "wheel") {
        const unit = msg.unit === "px" ? 0 : 1;
        const sy = Number(msg.sy) || 0;
        const sx = Number(msg.sx) || 0;
        rdpSendWheel(sx, sy, unit);
      }
    }
  };

  // ── 2 Chế độ Thao tác Cảm ứng chuẩn Microsoft Remote Desktop / Chrome Remote Desktop:
  //    1) `touch`   (👆 Chạm cảm ứng): chạm đâu bấm đấy trực tiếp như màn hình cảm ứng Windows.
  //    2) `pointer` (🖱 Dùng chuột)  : cả màn hình làm bàn rê Trackpad di chuyển mũi tên trỏ chuột chính xác.
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
    let rTouchMode = "none"; // "single" | "scroll" | "drag" | "two"
    let rStartAt = 0;
    let rPrevAt = 0;
    let rStartX = 0;
    let rStartY = 0;
    let rLastX = 0;
    let rLastY = 0;
    let rTotalMoved = 0;
    let rMaxFingers = 0;
    let rSmoothedVel = 0;
    let rMoved = false;
    let rLongFired = false;
    let rLongTimer = null;
    let rLastTapAt = 0;
    let rLastTapRx = 0;
    let rLastTapRy = 0;
    let rLastTapClientX = 0;
    let rLastTapClientY = 0;
    let rPendingDoubleTapDrag = false;
    let rPinchStartDist = 0;
    let rPinchStartZoom = 1.0;
    let rPinching = false;
    let rTwoLastMidX = 0;
    let rTwoLastMidY = 0;
    let rScrollAccY = 0;
    let rScrollAccX = 0;
    let rScrollAnchorX = 0;
    let rScrollAnchorY = 0;
    let rScrollVelX = 0;
    let rScrollVelY = 0;
    let rScrollInertiaRaf = null;

    const clearRdpLongTimer = () => {
      if (rLongTimer !== null) {
        clearTimeout(rLongTimer);
        rLongTimer = null;
      }
    };

    const stopRdpScrollInertia = () => {
      if (rScrollInertiaRaf !== null) {
        cancelAnimationFrame(rScrollInertiaRaf);
        rScrollInertiaRaf = null;
      }
      rScrollVelX = 0;
      rScrollVelY = 0;
    };

    const showTouchRing = (cx, cy, isDrag = false) => {
      if (!remoteTouchRing) return;
      remoteTouchRing.style.transform = `translate3d(${Math.round(cx)}px, ${Math.round(cy)}px, 0)`;
      remoteTouchRing.classList.toggle("is-drag", Boolean(isDrag));
      remoteTouchRing.classList.remove("is-hidden");
    };

    const hideTouchRing = () => {
      if (!remoteTouchRing) return;
      remoteTouchRing.classList.add("is-hidden");
      remoteTouchRing.classList.remove("is-drag");
    };

    const flushAccumulatedScroll = (anchorX = null, anchorY = null) => {
      const minStep = 2;
      const py = Math.trunc(rScrollAccY);
      const px = Math.trunc(rScrollAccX);
      let sdx = 0;
      let sdy = 0;
      if (Math.abs(py) >= minStep) {
        rScrollAccY -= py;
        sdy = py;
      }
      if (Math.abs(px) >= minStep + 1) {
        rScrollAccX -= px;
        sdx = px;
      }
      if (sdx !== 0 || sdy !== 0) {
        rdpSendWheel(sdx, sdy, 0, anchorX, anchorY);
      }
    };

    const startRdpScrollInertia = (vx, vy, anchorX = null, anchorY = null) => {
      stopRdpScrollInertia();
      let curVx = Math.max(-68, Math.min(68, vx));
      let curVy = Math.max(-68, Math.min(68, vy));
      let lastTs = performance.now();
      const step = (ts) => {
        if (!isRemoteConnected()) {
          rScrollInertiaRaf = null;
          return;
        }
        const dt = Math.max(8, Math.min(34, ts - lastTs));
        lastTs = ts;
        const decay = Math.pow(0.92, dt / 16.67);
        curVx *= decay;
        curVy *= decay;
        if (Math.hypot(curVx, curVy) < 0.75) {
          rScrollInertiaRaf = null;
          return;
        }
        rScrollAccX += curVx * (dt / 16.67);
        rScrollAccY += curVy * (dt / 16.67);
        flushAccumulatedScroll(anchorX, anchorY);
        rScrollInertiaRaf = requestAnimationFrame(step);
      };
      rScrollInertiaRaf = requestAnimationFrame(step);
    };

    const isPointerModeActive = () =>
      kbLayout === "mac_ext" ? macExtTouchMode === "pointer" : rdpInputMode === "pointer";
    const isMacExtTouchBlocked = () => kbLayout === "mac_ext" && macExtTouchMode === "off";

    remoteViewport.addEventListener(
      "touchstart",
      (e) => {
        ensureRdpAudioContext();
        stopRdpScrollInertia();
        if (rdpHudExpanded) {
          setRemoteHudExpanded(false);
        }
        if (!isRemoteConnected() || isMacExtTouchBlocked()) return;
        e.preventDefault();

        const now = performance.now();
        rMaxFingers = Math.max(rMaxFingers, e.touches.length);

        if (e.touches.length >= 2) {
          clearRdpLongTimer();
          hideTouchRing();
          if (rTouchMode === "none") {
            rStartAt = now;
            rTotalMoved = 0;
            rMaxFingers = e.touches.length;
          }
          rPrevAt = now;
          if (rTouchMode === "drag") {
            if (isPointerModeActive()) {
              rdpSendMouseUp(kvmX, kvmY, 0, 1);
            } else {
              const releasePt = clientToRemoteCoords(rLastX, rLastY);
              rdpSendMouseUp(releasePt.x, releasePt.y, 0, 1);
            }
          }
          rTouchMode = "two";
          rPinching = false;
          const t0 = e.touches[0];
          const t1 = e.touches[1];
          rPinchStartDist = Math.max(
            20,
            Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY)
          );
          rPinchStartZoom = rdpZoom;
          rTwoLastMidX = (t0.clientX + t1.clientX) / 2;
          rTwoLastMidY = (t0.clientY + t1.clientY) / 2;
          rScrollAccY = 0;
          rScrollAccX = 0;
          const midPt = clientToRemoteCoords(rTwoLastMidX, rTwoLastMidY);
          rScrollAnchorX = midPt.x;
          rScrollAnchorY = midPt.y;
          return;
        }

        if (e.touches.length === 1) {
          const t = e.touches[0];
          rTouchMode = "single";
          rStartAt = now;
          rPrevAt = now;
          rStartX = t.clientX;
          rStartY = t.clientY;
          rLastX = t.clientX;
          rLastY = t.clientY;
          rTotalMoved = 0;
          rMaxFingers = 1;
          rSmoothedVel = 0;
          rMoved = false;
          rLongFired = false;
          rScrollAccX = 0;
          rScrollAccY = 0;
          hideTouchRing();
          const nearPrevTap =
            Math.hypot(t.clientX - rLastTapClientX, t.clientY - rLastTapClientY) < 36;
          rPendingDoubleTapDrag =
            now - rLastTapAt < 290 && (isPointerModeActive() || nearPrevTap);
          clearRdpLongTimer();

          const holdDelay = isPointerModeActive() ? 235 : 280;
          const holdMaxMove = isPointerModeActive() ? 8 : 11;
          rLongTimer = setTimeout(() => {
            rLongTimer = null;
            if (rTouchMode === "single" && !rMoved && rTotalMoved < holdMaxMove) {
              rLongFired = true;
              triggerHaptic(16);
              if (isPointerModeActive()) {
                // Ở chế độ Trackpad: ấn giữ 1 ngón -> khóa nút chuột trái để bôi đen / kéo cửa sổ ngay tại đầu mũi tên!
                rTouchMode = "drag";
                showTouchRing(rLastX, rLastY, true);
                rdpSendMouseDown(kvmX, kvmY, 0, 1);
              } else {
                // Ở chế độ Cảm ứng: hiện vòng sáng báo đã khóa ấn giữ (nhấc tay = chuột phải; giữ và kéo = bôi đen / kéo thả!)
                showTouchRing(rLastX, rLastY, false);
              }
            }
          }, holdDelay);
        }
      },
      { passive: false }
    );

    remoteViewport.addEventListener(
      "touchmove",
      (e) => {
        if (!isRemoteConnected() || isMacExtTouchBlocked()) return;
        e.preventDefault();

        if (rTouchMode === "two" && e.touches.length >= 2) {
          const t0 = e.touches[0];
          const t1 = e.touches[1];
          const dist = Math.max(
            20,
            Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY)
          );
          const midX = (t0.clientX + t1.clientX) / 2;
          const midY = (t0.clientY + t1.clientY) / 2;
          const now = performance.now();
          const dt = Math.max(4, Math.min(50, now - rPrevAt || 16));
          rPrevAt = now;
          const dMidX = midX - rTwoLastMidX;
          const dMidY = midY - rTwoLastMidY;
          rTwoLastMidX = midX;
          rTwoLastMidY = midY;
          rTotalMoved += Math.hypot(dMidX, dMidY);

          // Hỗ trợ song song ở CẢ Cảm ứng LẪN Trackpad:
          // - Chụm/xòe 2 ngón (|Δdist| >= 22px) -> Pinch-Zoom + Pan
          // - Vuốt 2 ngón song song -> Cuộn Trackpad mượt dọc/ngang + quán tính!
          if (!rPinching && Math.abs(dist - rPinchStartDist) >= 22) {
            rPinching = true;
            rPinchStartDist = dist;
            rPinchStartZoom = rdpZoom;
          }
          if (rPinching) {
            const targetZoom = rPinchStartZoom * (dist / rPinchStartDist);
            zoomRdpAtClientPoint(targetZoom, midX, midY, dMidX, dMidY);
          } else {
            const gain = isStreamInputEngine() ? 2.2 : 2.6;
            const stepX = dMidX * gain * 0.85;
            const stepY = dMidY * gain;
            rScrollAccY += stepY;
            rScrollAccX += stepX;
            const normDt = 16.67 / dt;
            rScrollVelY = rScrollVelY * 0.45 + stepY * normDt * 0.55;
            rScrollVelX = rScrollVelX * 0.45 + stepX * normDt * 0.55;
            if (isPointerModeActive()) {
              flushAccumulatedScroll(null, null);
            } else {
              flushAccumulatedScroll(rScrollAnchorX, rScrollAnchorY);
            }
          }
          return;
        }

        if (
          e.touches.length === 1 &&
          (rTouchMode === "single" || rTouchMode === "scroll" || rTouchMode === "drag")
        ) {
          const t = e.touches[0];
          const now = performance.now();
          const dt = Math.max(4, Math.min(60, now - rPrevAt));
          rPrevAt = now;

          const dx = t.clientX - rLastX;
          const dy = t.clientY - rLastY;
          rLastX = t.clientX;
          rLastY = t.clientY;
          const stepDist = Math.hypot(dx, dy);
          rTotalMoved += stepDist;
          const distFromStart = Math.hypot(t.clientX - rStartX, t.clientY - rStartY);

          // ── NHÁNH A: CHẾ ĐỘ TRACKPAD (`pointer` — Bàn rê chuột toàn màn hình) ──
          if (isPointerModeActive()) {
            if (!rMoved && rTotalMoved >= 4.5) {
              rMoved = true;
              clearRdpLongTimer();
              if (rPendingDoubleTapDrag && rTouchMode !== "drag") {
                rPendingDoubleTapDrag = false;
                rTouchMode = "drag";
                triggerHaptic(12);
                showTouchRing(t.clientX, t.clientY, true);
                rdpSendMouseDown(kvmX, kvmY, 0, 1);
              }
            }
            if (!rMoved && rLongTimer !== null && rTotalMoved < 1.8) {
              return;
            }
            const vInst = stepDist / dt;
            rSmoothedVel =
              vInst < rSmoothedVel
                ? rSmoothedVel * 0.25 + vInst * 0.75
                : rSmoothedVel * 0.58 + vInst * 0.42;
            const cw = remoteCanvas.width || RDP_TARGET_W;
            const ch = remoteCanvas.height || RDP_TARGET_H;
            const vw = Math.max(320, remoteViewport.clientWidth || 800);
            const baseScale = (cw / vw) * 0.56;
            const gain = computeMacTrackpadGain(rSmoothedVel) * baseScale;
            kvmX = Math.max(0, Math.min(cw - 1, kvmX + dx * gain));
            kvmY = Math.max(0, Math.min(ch - 1, kvmY + dy * gain));
            if (rTouchMode === "drag") {
              showTouchRing(t.clientX, t.clientY, true);
            }
            showLocalRemoteCursor(kvmX, kvmY, 1600);
            autoPanViewportForCursor();
            rdpSendMouseMove(kvmX, kvmY);
            return;
          }

          // ── NHÁNH B: CHẾ ĐỘ CẢM ỨNG (`touch` — Vuốt 1 ngón = Cuộn mượt; Ấn giữ + kéo = Bôi đen / Kéo thả) ──
          const moveThreshold = rLongFired ? 6.5 : 10.5;
          if (!rMoved && distFromStart > moveThreshold) {
            rMoved = true;
            clearRdpLongTimer();
            const startPt = clientToRemoteCoords(rStartX, rStartY);
            if (rLongFired || rPendingDoubleTapDrag) {
              rPendingDoubleTapDrag = false;
              rTouchMode = "drag";
              if (!rLongFired) triggerHaptic(12);
              showTouchRing(t.clientX, t.clientY, true);
              rdpSendMouseDown(startPt.x, startPt.y, 0, 1);
            } else {
              // Vuốt 1 ngón trực tiếp -> Cuộn nội dung ngay tại vùng dưới ngón tay
              hideTouchRing();
              rTouchMode = "scroll";
              rScrollAnchorX = startPt.x;
              rScrollAnchorY = startPt.y;
              localPointerVisible = false;
              if (kbLayout !== "mac_ext") {
                rdpSendMouseMove(rScrollAnchorX, rScrollAnchorY);
              }
            }
          }

          if (rTouchMode === "drag") {
            showTouchRing(t.clientX, t.clientY, true);
            const pt = clientToRemoteCoords(t.clientX, t.clientY);
            rdpSendMouseMove(pt.x, pt.y);
          } else if (rTouchMode === "scroll") {
            const gain = isStreamInputEngine() ? 2.25 : 2.75;
            const stepX = dx * gain * 0.85;
            const stepY = dy * gain;
            rScrollAccY += stepY;
            rScrollAccX += stepX;
            const normDt = 16.67 / dt;
            rScrollVelY = rScrollVelY * 0.42 + stepY * normDt * 0.58;
            rScrollVelX = rScrollVelX * 0.42 + stepX * normDt * 0.58;
            flushAccumulatedScroll(rScrollAnchorX, rScrollAnchorY);
          }
        }
      },
      { passive: false }
    );

    const handleRdpTouchEnd = (e) => {
      if (e.touches.length > 0) {
        if (rTouchMode === "two" && e.touches.length === 1) {
          rLastX = e.touches[0].clientX;
          rLastY = e.touches[0].clientY;
        }
        return;
      }
      clearRdpLongTimer();
      hideTouchRing();
      if (!isRemoteConnected() || isMacExtTouchBlocked()) {
        rTouchMode = "none";
        return;
      }

      const now = performance.now();
      const duration = now - rStartAt;
      if (rdpZoom > 1.0 && rdpZoom < 1.02) {
        rdpZoom = 1.0;
        applyRdpStageTransform();
      }

      // ── KẾT THÚC CHẠM Ở CHẾ ĐỘ TRACKPAD (`pointer`) ──
      if (isPointerModeActive()) {
        rPendingDoubleTapDrag = false;
        if (rTouchMode === "drag") {
          rdpSendMouseUp(kvmX, kvmY, 0, 1);
          rTouchMode = "none";
          return;
        }
        if (rTouchMode === "two" && !rPinching && now - rPrevAt < 75 && Math.hypot(rScrollVelX, rScrollVelY) > 2.2) {
          startRdpScrollInertia(rScrollVelX, rScrollVelY, null, null);
          rTouchMode = "none";
          return;
        }
        if (rTotalMoved < 10 && duration < 290) {
          if (rMaxFingers >= 3) {
            triggerHaptic(10);
            rdpSendMouseClick(kvmX, kvmY, 1, 1);
          } else if (rMaxFingers === 2) {
            triggerHaptic(10);
            rdpSendMouseClick(kvmX, kvmY, 2, 1);
          } else if (now - rLastTapAt < 300) {
            triggerHaptic(10);
            rdpSendMouseClick(kvmX, kvmY, 0, 2);
            rLastTapAt = 0;
          } else {
            triggerHaptic(7);
            rdpSendMouseClick(kvmX, kvmY, 0, 1);
            rLastTapAt = now;
            rLastTapClientX = rLastX;
            rLastTapClientY = rLastY;
          }
        }
        rTouchMode = "none";
        return;
      }

      // ── KẾT THÚC CHẠM Ở CHẾ ĐỘ CẢM ỨNG (`touch`) ──
      rPendingDoubleTapDrag = false;
      if (rTouchMode === "drag") {
        const pt = clientToRemoteCoords(rLastX, rLastY);
        rdpSendMouseUp(pt.x, pt.y, 0, 1);
        rTouchMode = "none";
        return;
      }

      if (rTouchMode === "scroll") {
        if (now - rPrevAt < 75 && Math.hypot(rScrollVelX, rScrollVelY) > 2.2) {
          startRdpScrollInertia(rScrollVelX, rScrollVelY, rScrollAnchorX, rScrollAnchorY);
        }
        rTouchMode = "none";
        return;
      }

      if (rTouchMode === "two") {
        if (rTotalMoved < 12 && duration < 290) {
          triggerHaptic(10);
          const midPt = clientToRemoteCoords(rTwoLastMidX, rTwoLastMidY);
          if (rMaxFingers >= 3) {
            rdpSendMouseClick(midPt.x, midPt.y, 1, 1);
          } else {
            rdpSendMouseClick(midPt.x, midPt.y, 2, 1);
          }
        } else if (!rPinching && now - rPrevAt < 75 && Math.hypot(rScrollVelX, rScrollVelY) > 2.2) {
          startRdpScrollInertia(rScrollVelX, rScrollVelY, rScrollAnchorX, rScrollAnchorY);
        }
        rTouchMode = "none";
        return;
      }

      if (rTouchMode === "single") {
        const pt = clientToRemoteCoords(rLastX, rLastY);
        if (rLongFired && !rMoved) {
          rdpSendMouseClick(pt.x, pt.y, 2, 1);
        } else if (!rMoved) {
          if (
            now - rLastTapAt < 320 &&
            Math.hypot(rLastX - rLastTapClientX, rLastY - rLastTapClientY) < 32
          ) {
            triggerHaptic(9);
            rdpSendMouseClick(rLastTapRx, rLastTapRy, 0, 2);
            rLastTapAt = 0;
          } else {
            triggerHaptic(6);
            rdpSendMouseClick(pt.x, pt.y, 0, 1);
            rLastTapAt = now;
            rLastTapRx = pt.x;
            rLastTapRy = pt.y;
            rLastTapClientX = rLastX;
            rLastTapClientY = rLastY;
          }
        }
      }
      rTouchMode = "none";
    };

    remoteViewport.addEventListener("touchend", handleRdpTouchEnd, { passive: false });
    remoteViewport.addEventListener("touchcancel", handleRdpTouchEnd, { passive: false });

    // Nếu người dùng kết nối chuột trực tiếp với điện thoại: chỉ nhận khi chế độ chuột không khóa ở riêng Mac
    remoteViewport.addEventListener("pointermove", (e) => {
      if (e.pointerType !== "mouse" || rdpMouseMode === "mac" || !isRemoteConnected()) return;
      const pt = clientToRemoteCoords(e.clientX, e.clientY);
      kvmX = pt.x;
      kvmY = pt.y;
      rdpSendMouseMove(pt.x, pt.y);
    });

    remoteViewport.addEventListener("pointerdown", (e) => {
      if (e.pointerType !== "mouse" || rdpMouseMode === "mac" || !isRemoteConnected()) return;
      e.preventDefault();
      remoteCanvas.focus();
      const pt = clientToRemoteCoords(e.clientX, e.clientY);
      rdpSendMouseDown(pt.x, pt.y, e.button, 1);
    });

    remoteViewport.addEventListener("pointerup", (e) => {
      if (e.pointerType !== "mouse" || rdpMouseMode === "mac" || !isRemoteConnected()) return;
      e.preventDefault();
      const pt = clientToRemoteCoords(e.clientX, e.clientY);
      rdpSendMouseUp(pt.x, pt.y, e.button, 1);
    });

    remoteViewport.addEventListener(
      "wheel",
      (e) => {
        if (rdpMouseMode === "mac" || !isRemoteConnected()) return;
        e.preventDefault();
        const pt = clientToRemoteCoords(e.clientX, e.clientY);
        kvmX = pt.x;
        kvmY = pt.y;
        const dy = e.deltaY !== 0 ? (e.deltaY > 0 ? -1 : 1) : 0;
        const dx = e.deltaX !== 0 ? (e.deltaX > 0 ? 1 : -1) : 0;
        if (dx !== 0 || dy !== 0) {
          rdpSendWheel(dx, dy, 1);
        }
      },
      { passive: false }
    );
  }

  // ── Bàn phím vật lý / Bàn phím ảo điện thoại & Microphone Tiếng Việt ──
  if (remoteCanvas) {
    remoteCanvas.addEventListener("keydown", (e) => {
      if (!isRemoteConnected() || kbLayout !== "remote") return;
      if (document.activeElement === rdpHostInput || document.activeElement === rdpUserInput || document.activeElement === rdpPassInput) {
        return;
      }
      if (rdpActiveEngine === "parallel") {
        if (CODE_TO_SERVER_KEY[e.code]) {
          e.preventDefault();
          const mods = [];
          if (e.ctrlKey) mods.push("ctrl");
          if (e.altKey) mods.push("alt");
          if (e.shiftKey) mods.push("shift");
          if (e.metaKey) mods.push("cmd");
          sendParallelJson({ type: "key_tap", key: CODE_TO_SERVER_KEY[e.code], mods });
        }
        return;
      }
      if (!rdpMod) return;
      const sc = RDP_SCANCODE_MAP[e.code];
      if (sc !== undefined) {
        e.preventDefault();
        applyRdpDeviceEvents([rdpMod.DeviceEvent.keyPressed(sc)]);
      }
    });

    remoteCanvas.addEventListener("keyup", (e) => {
      if (!rdpSession || !rdpMod || rdpActiveEngine !== "native" || kbLayout !== "remote") return;
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

  window.__onRemoteVoiceText = (spokenText) => {
    const txt = String(spokenText || "").trim();
    if (!txt) return;
    injectUnicodeTextToRdp(txt + " ");
  };

  window.__onRemoteVoiceState = () => {};

  function switchCoexistMode(forceExclusive = null) {
    triggerHaptic(10);
    if (forceExclusive !== null) {
      rdpPreferExclusive = Boolean(forceExclusive);
    } else if (rdpActiveEngine === "parallel") {
      rdpPreferExclusive = true;
    } else if (rdpActiveEngine === "native") {
      rdpPreferExclusive = false;
    } else {
      rdpPreferExclusive = !rdpPreferExclusive;
    }
    syncCoexistButtonUI();
    syncSmartKvmButtonsUI();
    closeParallelRdpWs();
    closeRdpAudioWs();
    if (rdpSession) {
      try {
        rdpSession.shutdown();
      } catch {
        // ignore
      }
      rdpSession = null;
    }
    rdpActiveEngine = "none";
    rdpConnecting = false;
    syncRdpConnectionUI();
    void connectRdpSession();
  }

  if (btnRemoteCoexist) {
    btnRemoteCoexist.addEventListener("click", (e) => {
      e.stopPropagation();
      closeAllRemoteSubMenus();
      switchCoexistMode(null);
    });
  }

  if (btnMacExtTouch) {
    syncMacExtTouchUI();
    btnMacExtTouch.addEventListener("click", (e) => {
      e.stopPropagation();
      triggerHaptic(8);
      macExtTouchMode =
        macExtTouchMode === "touch"
          ? "pointer"
          : macExtTouchMode === "pointer"
            ? "off"
            : "touch";
      try {
        localStorage.setItem("mac_kb_mac_ext_touch_v1", macExtTouchMode);
      } catch {
        // ignore
      }
      syncMacExtTouchUI();
      if (macExtTouchMode === "pointer" && isMacExtConnected()) {
        showLocalRemoteCursor(kvmX, kvmY, 2200);
      }
    });
  }

  if (btnMacExtDisplay) {
    btnMacExtDisplay.addEventListener("click", (e) => {
      e.stopPropagation();
      triggerHaptic(8);
      void toggleMacExtDisplay(null, true);
    });
  }

  if (btnMacExtRetry) {
    btnMacExtRetry.addEventListener("click", () => {
      triggerHaptic(8);
      void toggleMacExtDisplay(true, false);
    });
  }

  if (btnMacExtOff) {
    btnMacExtOff.addEventListener("click", () => {
      triggerHaptic(8);
      void toggleMacExtDisplay(false, true);
    });
  }

  if (btnMacExtBack) {
    btnMacExtBack.addEventListener("click", () => {
      triggerHaptic(8);
      selectKeyboardLayout(lastNonRemoteLayout || "pad");
    });
  }

  // ── Menu điều khiển hợp nhất duy nhất (Cảm ứng | Bàn rê ảo | Chuột: ĐT | Chuột: Nối 2 màn) ──
  if (btnRemoteControl) {
    btnRemoteControl.addEventListener("click", (e) => {
      e.stopPropagation();
      triggerHaptic(8);
      const next = !rdpControlMenuOpen;
      closeAllRemoteSubMenus();
      rdpControlMenuOpen = next;
      if (remoteControlMenu) remoteControlMenu.classList.toggle("is-hidden", !rdpControlMenuOpen);
    });
  }

  if (remoteControlMenu) {
    remoteControlMenu.addEventListener("click", (e) => {
      const item = e.target.closest("[data-rdp-ctrl]");
      if (!item) return;
      e.stopPropagation();
      triggerHaptic(8);
      setRemoteControlMode(item.dataset.rdpCtrl);
      setRemoteHudExpanded(false);
    });
  }

  // ── Menu chọn Tỉ lệ hiển thị HiDPI (100% / 125% / 150% / 175%) cho chế độ Độc quyền ──
  if (btnRemoteScale) {
    btnRemoteScale.addEventListener("click", (e) => {
      e.stopPropagation();
      triggerHaptic(8);
      const next = !rdpScaleMenuOpen;
      closeAllRemoteSubMenus();
      rdpScaleMenuOpen = next;
      if (remoteScaleMenu) remoteScaleMenu.classList.toggle("is-hidden", !rdpScaleMenuOpen);
    });
  }

  if (remoteScaleMenu) {
    remoteScaleMenu.addEventListener("click", (e) => {
      const item = e.target.closest("[data-rdp-scale]");
      if (!item) return;
      e.stopPropagation();
      triggerHaptic(8);
      setRemoteDesktopScale(item.dataset.rdpScale);
      setRemoteHudExpanded(false);
    });
  }

  syncRemoteScaleUI();

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
      const next = !rdpRemoteMenuOpen;
      closeAllRemoteSubMenus();
      rdpRemoteMenuOpen = next;
      if (remoteModeMenu) remoteModeMenu.classList.toggle("is-hidden", !rdpRemoteMenuOpen);
    });
  }

  if (btnRemoteKb) {
    btnRemoteKb.addEventListener("click", (e) => {
      e.stopPropagation();
      triggerHaptic(8);
      closeAllRemoteSubMenus();
      if (rdpImeOpen) {
        closeRemoteSoftKeyboard();
      } else {
        setRemoteHudExpanded(false);
        openRemoteSoftKeyboard();
      }
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
      if (isRemoteConnected() && remoteLoginOverlay) {
        remoteLoginOverlay.classList.add("is-hidden");
      }
    });
  }

  onEnterRemoteLayout = (userInitiated = false) => {
    setRemoteHudExpanded(false);
    ensureRdpAudioContext();
    if (
      hasAndroidBridge &&
      typeof window.AndroidBridge.ensureMicPermission === "function"
    ) {
      try {
        window.AndroidBridge.ensureMicPermission();
      } catch {
        // ignore
      }
    }
    pushKvmConfigToServer();
    syncRdpConnectionUI();
    let resumeAfterHotUpdate = false;
    try {
      resumeAfterHotUpdate = sessionStorage.getItem("mac_kb_hot_reload_active_rdp") === "1";
      sessionStorage.removeItem("mac_kb_hot_reload_active_rdp");
    } catch {
      // ignore
    }
    if (!isRemoteConnected() && !rdpConnecting) {
      if (!userInitiated && !resumeAfterHotUpdate) {
        if (remoteLoginOverlay) remoteLoginOverlay.classList.remove("is-hidden");
        return;
      }
      const hasSavedPass = Boolean(rdpPassInput && rdpPassInput.value);
      if (hasSavedPass) {
        void connectRdpSession();
      } else {
        void checkMacParallelAvailable().then((chk) => {
          if (
            chk.available &&
            !rdpPreferExclusive &&
            kbLayout === "remote" &&
            !isRemoteConnected() &&
            !rdpConnecting
          ) {
            void connectRdpSession();
          } else if (remoteLoginOverlay) {
            remoteLoginOverlay.classList.remove("is-hidden");
          }
        });
      }
    }
  };

  onLeaveRemoteLayout = () => {
    closeRemoteSoftKeyboard();
    setRemoteHudExpanded(false);
    if (kvmActive) {
      sendPayload({ type: "kvm_set", captured: false });
    }
    kvmActive = false;
    syncSmartKvmButtonsUI();
    updateOverlayCursorVisual();
    pushKvmConfigToServer();
  };

  window.addEventListener("resize", () => {
    if (kbLayout === "remote" || kbLayout === "mac_ext") {
      applyRdpStageTransform();
      updateOverlayCursorVisual();
    }
  });

  if (kbLayout === "remote") {
    onEnterRemoteLayout(false);
  } else {
    // Nạp sẵn bộ giải mã WASM dưới nền để khi chuyển sang tab Remote PC sẽ kết nối tức thì (~0.3s)
    setTimeout(() => {
      void ensureIronRdpLoaded().catch(() => {});
    }, 900);
  }

  // ============================================================================
  // 9. CẬP NHẬT NÓNG TỨC THÌ TRỰC TIẾP KHI ĐANG MỞ APP (INSTANT LAN + GITHUB SHA HOT-OTA)
  //    Sửa bất kỳ dòng HTML / CSS / JS nào trên PC hoặc GitHub -> tự tải ngầm gói mới
  //    và áp dụng trực tiếp sau ~2-3s nghỉ tay (kể cả khi đang mở Remote PC), không cần tắt mở lại app!
  // ============================================================================
  const BUNDLED_WEB_VERSION = "2.3.28";
  const HOT_BUNDLE_STORAGE_KEY = "mac_kb_hot_bundle_v1";
  const GITHUB_REPO_SLUG = "NguyenHieu2711/mac-web-keyboard";
  let lastUserTouchAt = performance.now();
  let liveUpdateInFlight = false;
  let pendingHotBundleReady = false;
  let pendingUpdateApplyTimer = null;
  let lastGithubCheckAt = 0;

  const markUserActive = () => {
    lastUserTouchAt = performance.now();
    if (kbLayout === "remote") {
      ensureRdpAudioContext();
    }
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      if (kbLayout === "remote") {
        ensureRdpAudioContext();
        if (rdpServerMicOpen && rdpSession) {
          void startRdpMicCapture(rdpServerMicSpec);
        }
      }
      void pollLiveUpdateManifest();
    }
  });
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
    let best = window.__MAC_KB_HOT_VERSION__ || BUNDLED_WEB_VERSION;
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

  function getRunningEtag() {
    if (window.__MAC_KB_HOT_BOOTED__) {
      return String(window.__MAC_KB_HOT_BOOTED__);
    }
    try {
      return localStorage.getItem(`mac_kb_base_etag_${BUNDLED_WEB_VERSION}`) || "";
    } catch {
      return "";
    }
  }

  function buildLanLiveBaseUrls() {
    const bases = [];
    const pcHostVal = (rdpHostInput ? rdpHostInput.value : "192.168.52.230")
      .trim()
      .replace(/^https?:\/\/|^wss?:\/\//, "")
      .split(":")[0]
      .trim();
    if (pcHostVal) {
      bases.push(`http://${pcHostVal}:5051`);
    }
    const macBase = resolveMacHttpBase();
    if (macBase) {
      bases.push(macBase.replace(/\/+$/, ""));
    }
    for (const h of resolveCandidateHosts()) {
      const clean = h.replace(/^https?:\/\/|^wss?:\/\//, "").split("/")[0];
      if (clean) {
        bases.push(`http://${clean}`);
      }
    }
    return Array.from(new Set(bases));
  }

  async function fetchJsonFast(url, timeoutMs = 1200) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, {
        method: "GET",
        cache: "no-store",
        signal: ctrl.signal,
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  function applyReadyHotBundleWhenIdle() {
    if (!pendingHotBundleReady) return;
    const idleMs = performance.now() - lastUserTouchAt;
    // TUYỆT ĐỐI KHÔNG tự reload ngang khi đang mở Remote PC hoặc Màn phụ Mac (tránh rớt phiên & bung hộp thoại Cài đặt)
    if (
      document.visibilityState !== "visible" ||
      activePointers.size > 0 ||
      idleMs < 1800 ||
      kbLayout === "remote" ||
      kbLayout === "mac_ext" ||
      isRemoteConnected() ||
      rdpConnecting ||
      macExtDisplayActive ||
      isMacExtConnected()
    ) {
      if (pendingUpdateApplyTimer === null) {
        pendingUpdateApplyTimer = setTimeout(() => {
          pendingUpdateApplyTimer = null;
          applyReadyHotBundleWhenIdle();
        }, 2000);
      }
      return;
    }
    pendingHotBundleReady = false;
    try {
      sessionStorage.setItem("mac_kb_hot_reload_active_rdp", "0");
    } catch {
      // ignore
    }
    rdpManualDisconnect = true;
    closeParallelRdpWs();
    closeMacExtWs();
    closeRdpAudioWs();
    if (rdpSession) {
      try {
        rdpSession.shutdown();
      } catch {
        // ignore
      }
      rdpSession = null;
    }
    releaseAllActiveTouches();
    window.location.reload();
  }

  function saveHotBundleToStorage(bundle) {
    if (
      !bundle ||
      !bundle.etag ||
      !bundle.app_js ||
      !bundle.body_html ||
      typeof bundle.style_css !== "string"
    ) {
      return false;
    }
    try {
      localStorage.setItem(
        HOT_BUNDLE_STORAGE_KEY,
        JSON.stringify({
          web_version: String(bundle.web_version || BUNDLED_WEB_VERSION),
          etag: String(bundle.etag),
          body_html: bundle.body_html,
          style_css: bundle.style_css,
          app_js: bundle.app_js,
        })
      );
      localStorage.setItem(
        `mac_kb_base_etag_${bundle.web_version || BUNDLED_WEB_VERSION}`,
        String(bundle.etag)
      );
      return true;
    } catch {
      return false;
    }
  }

  async function tryUpdateFromGithubUncached(curVer, curEtag) {
    try {
      const commitRes = await fetchJsonFast(
        `https://api.github.com/repos/${GITHUB_REPO_SLUG}/commits/main`,
        4500
      );
      const sha = commitRes && typeof commitRes.sha === "string" ? commitRes.sha.trim() : "";
      if (!sha) return false;
      const shortSha = sha.slice(0, 12);
      const seenSha = localStorage.getItem("mac_kb_last_gh_sha") || "";
      if (seenSha === shortSha && curEtag) return false;

      const rawBase = `https://raw.githubusercontent.com/${GITHUB_REPO_SLUG}/${sha}`;
      const manifest = await fetchJsonFast(`${rawBase}/releases/latest.json`, 4500);
      if (!manifest) return false;

      const remoteTag = String(manifest.tag_name || "").trim();
      if (
        hasAndroidBridge &&
        typeof window.AndroidBridge.getAppVersion === "function" &&
        typeof window.AndroidBridge.startNativeUpdate === "function" &&
        remoteTag &&
        compareVer(remoteTag, BUNDLED_WEB_VERSION) > 0
      ) {
        // Chỉ gọi bộ cài APK gốc khi thực sự có bản APK mới (tag_name tăng)
        try {
          window.AndroidBridge.startNativeUpdate();
          return true;
        } catch {
          // ignore
        }
      }

      const remoteWeb = String(manifest.web_version || "").trim();
      // Chỉ tải từ GitHub khi bản trên GitHub THỰC SỰ mới hơn bản đang chạy (tránh xung đột etag MD5 LAN vs Git SHA)
      if (!remoteWeb || compareVer(remoteWeb, curVer) <= 0) {
        localStorage.setItem("mac_kb_last_gh_sha", shortSha);
        return false;
      }

      const [idxTxt, cssTxt, jsTxt] = await Promise.all([
        fetch(`${rawBase}/static/index.html`, { cache: "no-store" }).then((r) =>
          r.ok ? r.text() : ""
        ),
        fetch(`${rawBase}/static/style.css`, { cache: "no-store" }).then((r) =>
          r.ok ? r.text() : ""
        ),
        fetch(`${rawBase}/static/app.js`, { cache: "no-store" }).then((r) =>
          r.ok ? r.text() : ""
        ),
      ]);
      if (!idxTxt || !cssTxt || !jsTxt) return false;
      const mBody = idxTxt.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
      const bodyHtml = (mBody ? mBody[1] : idxTxt)
        .replace(/<script[^>]*src=["'][^"']*app\.js[^"']*["'][^>]*>\s*<\/script>/gi, "")
        .trim();

      localStorage.setItem("mac_kb_last_gh_sha", shortSha);
      if (
        saveHotBundleToStorage({
          web_version: remoteWeb,
          etag: shortSha,
          body_html: bodyHtml,
          style_css: cssTxt,
          app_js: jsTxt,
        })
      ) {
        pendingHotBundleReady = true;
        applyReadyHotBundleWhenIdle();
        return true;
      }
    } catch {
      // ignore
    }
    return false;
  }

  async function pollLiveUpdateManifest() {
    if (liveUpdateInFlight || pendingHotBundleReady || document.visibilityState !== "visible") {
      return;
    }
    liveUpdateInFlight = true;
    try {
      const curVer = getRunningWebVersion();
      const curEtag = getRunningEtag();

      // 1. Ưu tiên kiểm tra trực tiếp PC (:5051) và MacBook (:5050) qua Wi-Fi nội bộ (~3ms, cập nhật tức thì 0 độ trễ CDN!)
      const lanBases = buildLanLiveBaseUrls();
      for (const base of lanBases) {
        const mf = await fetchJsonFast(`${base}/web-manifest?t=${Date.now()}`, 900);
        if (!mf || !mf.ok || !mf.etag || !mf.web_version) continue;

        const rVer = String(mf.web_version).trim();
        const rEtag = String(mf.etag).trim();
        const verCmp = compareVer(rVer, curVer);
        if (verCmp < 0) continue;

        // Lần đầu khởi động bản gốc trên máy: ghi nhận mã etag gốc để tránh reload thừa 1 nhịp
        if (!curEtag && verCmp === 0) {
          try {
            localStorage.setItem(`mac_kb_base_etag_${BUNDLED_WEB_VERSION}`, rEtag);
          } catch {
            // ignore
          }
          return;
        }

        if (verCmp > 0 || rEtag !== curEtag) {
          const bundle = await fetchJsonFast(`${base}/web-bundle?t=${Date.now()}`, 3500);
          if (bundle && bundle.ok && saveHotBundleToStorage(bundle)) {
            pendingHotBundleReady = true;
            applyReadyHotBundleWhenIdle();
            return;
          }
        }
        // Đã kiểm tra thành công máy chủ LAN và đang khớp 100% mã mới nhất
        return;
      }

      // 2. Dự phòng khi đi ra ngoài mạng 4G/Tailscale: đọc trực tiếp SHA mới nhất qua GitHub Commits API (vượt cache 5 phút của Fastly CDN)
      const now = performance.now();
      if (now - lastGithubCheckAt >= 24000) {
        lastGithubCheckAt = now;
        await tryUpdateFromGithubUncached(curVer, curEtag);
      }
    } finally {
      liveUpdateInFlight = false;
    }
  }

  setTimeout(() => {
    void pollLiveUpdateManifest();
  }, 1800);
  setInterval(() => {
    void pollLiveUpdateManifest();
  }, 4200);
  window.__MAC_KB_HOT_OK__ = true;
})();
