(() => {
  "use strict";

  const wsDot = document.getElementById("ws-dot");
  const utilIcon = document.getElementById("util-icon");
  const lensStage = document.getElementById("lens-stage");
  const lensCanvas = document.getElementById("lens-canvas");
  const lensCtx = lensCanvas ? lensCanvas.getContext("2d", { alpha: false }) : null;
  const offlinePreviewText = document.getElementById("offline-preview-text");
  const btnLockState = document.getElementById("btn-lock-state");
  const lockStateText = document.getElementById("lock-state-text");
  const btnFovOut = document.getElementById("btn-fov-out");
  const btnFovReset = document.getElementById("btn-fov-reset");
  const btnFovIn = document.getElementById("btn-fov-in");
  const btnSettings = document.getElementById("btn-settings");
  const btnSyncMode = document.getElementById("btn-sync-mode");
  const vnInput = document.getElementById("vn-input");
  const btnSendEnter = document.getElementById("btn-send-enter");

  const allKeys = Array.from(document.querySelectorAll(".key"));
  const hasAndroidBridge =
    typeof window.AndroidBridge !== "undefined" && window.AndroidBridge !== null;

  if (!hasAndroidBridge && utilIcon) {
    utilIcon.textContent = "⛶";
  }

  for (const btn of allKeys) {
    const flexVal = parseFloat(btn.dataset.flex || "1");
    btn.style.flexGrow = String(flexVal);
  }

  // ============================================================================
  // 1. QUẢN LÝ KẾT NỐI WEBSOCKET + LUỒNG NHỊ PHÂN LIVE LENS
  // ============================================================================
  const STORAGE_HOST_KEY = "mac_kb_server_host";
  const STORAGE_FOV_KEY = "mac_kb_lens_fov";
  const STORAGE_SYNC_MODE_KEY = "mac_kb_vn_live_word";

  let ws = null;
  let isWsOnline = false;
  let reconnectDelay = 400;
  let reconnectTimer = null;
  let pingInterval = null;
  let hostCycleIndex = 0;
  let offlineBuffer = "";

  // Tầm nhìn mặc định 1.1x (nhìn rộng thoáng quanh tâm con chuột)
  let fovScale = parseFloat(localStorage.getItem(STORAGE_FOV_KEY) || "1.1") || 1.1;
  let liveWordMode = localStorage.getItem(STORAGE_SYNC_MODE_KEY) !== "0";

  function updateFovLabel() {
    if (!btnFovReset) return;
    const zoomDisplay = (1 / fovScale).toFixed(2).replace(/\.00$/, ".0");
    btnFovReset.textContent = `${zoomDisplay}x`;
  }

  function updateSyncModeUI() {
    if (!btnSyncMode) return;
    btnSyncMode.textContent = liveWordMode ? "Từng từ" : "Cả câu";
    btnSyncMode.classList.toggle("is-live-word", liveWordMode);
  }

  updateFovLabel();
  updateSyncModeUI();

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
    isWsOnline = online;
    if (wsDot) {
      wsDot.classList.toggle("is-online", online);
      wsDot.classList.toggle("is-offline", !online);
    }
    if (!online && lensStage) {
      lensStage.classList.remove("has-stream");
    }
  }

  function appendOfflinePreview(token) {
    if (isWsOnline || !offlinePreviewText) return;
    if (token === "⌫") {
      offlineBuffer = offlineBuffer.slice(0, -1);
    } else if (token === "⌘⌫") {
      offlineBuffer = "";
    } else {
      offlineBuffer = (offlineBuffer + token).slice(-48);
    }
    offlinePreviewText.textContent = offlineBuffer
      ? `Nháp tạm (chưa kết nối): ${offlineBuffer}▎`
      : "Chưa kết nối máy tính (🔴) • Bấm ⚙ để nhập IP LAN / Tailscale";
  }

  function sendPayload(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }

  function isLandscapeMode() {
    return window.matchMedia("(orientation: landscape)").matches;
  }

  function sendLensConfig() {
    if (!lensStage) return;
    const rect = lensStage.getBoundingClientRect();
    const w = Math.max(120, rect.width || window.innerWidth);
    const h = Math.max(44, rect.height || 120);
    const aspect = +(w / h).toFixed(2);
    const mode = isLandscapeMode() ? "landscape" : "portrait";
    sendPayload({
      type: "lens_config",
      enabled: true,
      aspect,
      scale: +fovScale.toFixed(2),
      mode,
    });
  }

  // ============================================================================
  // 2. GIẢI MÃ KHUNG HÌNH NHỊ PHÂN & VẼ KHOANH VÙNG TÂM CON CHUỘT SẮC NÉT
  // ============================================================================
  let isDecodingFrame = false;
  let pendingPacket = null;
  let lastLockFlag = false;

  function syncCanvasResolution() {
    if (!lensCanvas || !lensStage) return;
    const rect = lensStage.getBoundingClientRect();
    const dpr = Math.min(2.2, window.devicePixelRatio || 1);
    const targetW = Math.max(100, Math.round(rect.width * dpr));
    const targetH = Math.max(40, Math.round(rect.height * dpr));
    if (lensCanvas.width !== targetW || lensCanvas.height !== targetH) {
      lensCanvas.width = targetW;
      lensCanvas.height = targetH;
    }
  }

  function updateLockBadge(locked) {
    if (locked === lastLockFlag) return;
    lastLockFlag = locked;
    if (lensStage) {
      lensStage.classList.toggle("is-locked", locked);
    }
    if (btnLockState && lockStateText) {
      btnLockState.classList.toggle("is-locked-mode", locked);
      lockStateText.textContent = locked ? "🔒 Khóa dòng" : "🖱 Tâm chuột";
    }
  }

  function drawCursorReticleAndArrow(ctx, cw, ch, relMx, relMy, isLocked) {
    const dpr = Math.min(2.2, window.devicePixelRatio || 1);
    const px = relMx * cw;
    const py = relMy * ch;
    const landscape = isLandscapeMode();

    ctx.save();

    // 1. Vòng tròn khoanh vùng tâm con chuột (Cursor Focus Ring)
    const ringRadius = (landscape ? 13 : 19) * dpr;
    ctx.beginPath();
    ctx.arc(px, py, ringRadius, 0, Math.PI * 2);
    ctx.fillStyle = isLocked
      ? "rgba(56, 189, 248, 0.08)"
      : "rgba(56, 189, 248, 0.13)";
    ctx.fill();
    ctx.lineWidth = 1.4 * dpr;
    ctx.strokeStyle = isLocked
      ? "rgba(56, 189, 248, 0.52)"
      : "rgba(56, 189, 248, 0.88)";
    ctx.stroke();

    // 4 vạch chia tâm ngắm (Crosshair Ticks) mảnh tinh tế
    const tickIn = ringRadius - 3 * dpr;
    const tickOut = ringRadius + 3.5 * dpr;
    ctx.beginPath();
    ctx.moveTo(px - tickOut, py);
    ctx.lineTo(px - tickIn, py);
    ctx.moveTo(px + tickIn, py);
    ctx.lineTo(px + tickOut, py);
    ctx.moveTo(px, py - tickOut);
    ctx.lineTo(px, py - tickIn);
    ctx.moveTo(px, py + tickIn);
    ctx.lineTo(px, py + tickOut);
    ctx.lineWidth = 1.2 * dpr;
    ctx.stroke();

    // 2. Vẽ mũi tên con trỏ chuột sắc nét tại đúng đỉnh (px, py)
    const s = (landscape ? 0.85 : 1.05) * dpr;
    ctx.translate(px, py);
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(0, 15 * s);
    ctx.lineTo(4.2 * s, 11.4 * s);
    ctx.lineTo(7.2 * s, 17.5 * s);
    ctx.lineTo(9.6 * s, 16.3 * s);
    ctx.lineTo(6.6 * s, 10.2 * s);
    ctx.lineTo(11.4 * s, 10.2 * s);
    ctx.closePath();

    ctx.lineJoin = "round";
    ctx.lineWidth = 2.1 * s;
    ctx.strokeStyle = "rgba(9, 12, 18, 0.92)";
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.fill();

    ctx.restore();
  }

  async function processLensPacket(buffer) {
    if (!lensCtx || !lensCanvas || buffer.byteLength <= 12) return;
    const view = new DataView(buffer);
    // Kiểm tra magic "LENS" (0x4C454E53)
    if (view.getUint32(0, false) !== 0x4c454e53) return;

    if (isDecodingFrame) {
      pendingPacket = buffer;
      return;
    }
    isDecodingFrame = true;

    try {
      const relMx = view.getUint16(4, false) / 10000;
      const relMy = view.getUint16(6, false) / 10000;
      const flags = view.getUint8(8);
      const isLocked = (flags & 1) !== 0;

      const jpegBytes = new Uint8Array(buffer, 12);
      const blob = new Blob([jpegBytes], { type: "image/jpeg" });
      const bitmap = await createImageBitmap(blob);

      syncCanvasResolution();
      const cw = lensCanvas.width;
      const ch = lensCanvas.height;

      lensCtx.drawImage(bitmap, 0, 0, cw, ch);
      bitmap.close();

      drawCursorReticleAndArrow(lensCtx, cw, ch, relMx, relMy, isLocked);
      updateLockBadge(isLocked);

      if (lensStage && !lensStage.classList.contains("has-stream")) {
        lensStage.classList.add("has-stream");
      }
    } catch {
      // Bỏ qua khung lỗi lẻ
    } finally {
      isDecodingFrame = false;
      if (pendingPacket) {
        const next = pendingPacket;
        pendingPacket = null;
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
      sendLensConfig();
      if (pingInterval) clearInterval(pingInterval);
      pingInterval = setInterval(() => {
        sendPayload({ type: "ping" });
      }, 15000);
    });

    ws.addEventListener("message", (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        void processLensPacket(ev.data);
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

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectWebSocket();
    }, reconnectDelay);
    reconnectDelay = Math.min(2500, Math.round(reconnectDelay * 1.5));
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

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reconnectDelay = 200;
        connectWebSocket();
      } else {
        sendLensConfig();
      }
    } else {
      releaseAllActiveTouches();
    }
  });

  // ============================================================================
  // 3. CỬ CHỈ CẢM ỨNG TRÊN MẶT KÍNH SOI TRACKPAD (DI CHUỘT / CLICK / CUỘN 2 NGÓN)
  // ============================================================================
  const padTouches = new Map();
  let padGestureStartTs = 0;
  let padMaxFingerCount = 0;
  let padTotalMoveDist = 0;
  let lastSingleTapTs = 0;

  function isHudControlElement(el) {
    if (!el) return false;
    return Boolean(el.closest(".lens-hud-left, .lens-hud-right"));
  }

  if (lensStage) {
    lensStage.addEventListener(
      "touchstart",
      (e) => {
        if (isHudControlElement(e.target)) return;
        e.preventDefault();

        if (padTouches.size === 0) {
          padGestureStartTs = performance.now();
          padMaxFingerCount = 0;
          padTotalMoveDist = 0;
        }

        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const t = e.changedTouches[i];
          padTouches.set(t.identifier, { x: t.clientX, y: t.clientY });
        }
        padMaxFingerCount = Math.max(padMaxFingerCount, padTouches.size);
      },
      { passive: false }
    );

    lensStage.addEventListener(
      "touchmove",
      (e) => {
        if (padTouches.size === 0) return;
        e.preventDefault();

        let sumDx = 0;
        let sumDy = 0;
        let movedCount = 0;

        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const t = e.changedTouches[i];
          const prev = padTouches.get(t.identifier);
          if (!prev) continue;
          const dx = t.clientX - prev.x;
          const dy = t.clientY - prev.y;
          prev.x = t.clientX;
          prev.y = t.clientY;
          sumDx += dx;
          sumDy += dy;
          movedCount += 1;
        }

        if (movedCount === 0) return;
        const avgDx = sumDx / movedCount;
        const avgDy = sumDy / movedCount;
        const dist = Math.hypot(avgDx, avgDy);
        padTotalMoveDist += dist;

        if (dist < 0.25) return;

        if (padTouches.size >= 2) {
          // 2 ngón trượt -> Cuộn trang mượt trên Mac / Windows
          sendPayload({
            type: "mouse_scroll",
            dx: +(avgDx * 2.4).toFixed(1),
            dy: +(avgDy * 2.4).toFixed(1),
          });
        } else {
          // 1 ngón rê -> Di chuột có gia tốc tự nhiên + Kính Soi trượt theo tâm chuột
          const accel = 1.35 + Math.min(1.85, dist * 0.085);
          sendPayload({
            type: "mouse_move",
            dx: +(avgDx * accel).toFixed(2),
            dy: +(avgDy * accel).toFixed(2),
          });
        }
      },
      { passive: false }
    );

    const handlePadTouchEnd = (e) => {
      if (padTouches.size === 0) return;
      e.preventDefault();
      for (let i = 0; i < e.changedTouches.length; i += 1) {
        padTouches.delete(e.changedTouches[i].identifier);
      }

      if (padTouches.size === 0) {
        const elapsed = performance.now() - padGestureStartTs;
        if (padMaxFingerCount === 1 && elapsed < 240 && padTotalMoveDist < 9) {
          const now = performance.now();
          const isDouble = now - lastSingleTapTs < 280;
          lastSingleTapTs = isDouble ? 0 : now;
          triggerHaptic(12);
          sendPayload({
            type: "mouse_click",
            button: "left",
            count: isDouble ? 2 : 1,
          });
        } else if (padMaxFingerCount === 2 && elapsed < 270 && padTotalMoveDist < 14) {
          triggerHaptic(18);
          sendPayload({
            type: "mouse_click",
            button: "right",
            count: 1,
          });
        }
      }
    };

    lensStage.addEventListener("touchend", handlePadTouchEnd, { passive: false });
    lensStage.addEventListener("touchcancel", handlePadTouchEnd, { passive: false });
  }

  // Nút điều chỉnh độ rộng Kính Soi (− = nhìn rộng ra chữ nhỏ hơn; + = phóng gần chữ to hơn)
  function adjustFov(delta) {
    triggerHaptic(10);
    fovScale = Math.max(0.55, Math.min(1.75, +(fovScale + delta).toFixed(2)));
    try {
      localStorage.setItem(STORAGE_FOV_KEY, String(fovScale));
    } catch {
      // ignore
    }
    updateFovLabel();
    sendLensConfig();
  }

  if (btnFovOut) {
    btnFovOut.addEventListener("click", () => adjustFov(0.18));
  }
  if (btnFovIn) {
    btnFovIn.addEventListener("click", () => adjustFov(-0.18));
  }
  if (btnFovReset) {
    btnFovReset.addEventListener("click", () => {
      triggerHaptic(10);
      fovScale = 1.1;
      try {
        localStorage.setItem(STORAGE_FOV_KEY, String(fovScale));
      } catch {
        // ignore
      }
      updateFovLabel();
      sendLensConfig();
    });
  }
  if (btnLockState) {
    btnLockState.addEventListener("click", () => {
      triggerHaptic(10);
      sendPayload({ type: "lens_unlock" });
    });
  }
  if (btnSettings) {
    btnSettings.addEventListener("click", () => {
      triggerHaptic(10);
      if (hasAndroidBridge && typeof window.AndroidBridge.openServerDialog === "function") {
        window.AndroidBridge.openServerDialog();
      } else {
        void enterBrowserFullscreen(true);
      }
    });
  }

  // ============================================================================
  // 4. Ô GÕ TIẾNG VIỆT GBOARD / GIỌNG NÓI Ở MÀN DỌC (PORTRAIT COMPOSER)
  // ============================================================================
  let isImeComposing = false;

  function flushVnInput(sendEnterIfEmpty = false) {
    if (!vnInput) return;
    const text = vnInput.value;
    if (text.length > 0) {
      if (!sendPayload({ type: "text", text })) {
        appendOfflinePreview(text);
      }
      vnInput.value = "";
    } else if (sendEnterIfEmpty) {
      if (!sendPayload({ type: "press", key: "enter" })) {
        appendOfflinePreview("⏎");
      }
    }
  }

  if (btnSyncMode) {
    btnSyncMode.addEventListener("click", () => {
      triggerHaptic(10);
      liveWordMode = !liveWordMode;
      try {
        localStorage.setItem(STORAGE_SYNC_MODE_KEY, liveWordMode ? "1" : "0");
      } catch {
        // ignore
      }
      updateSyncModeUI();
      if (vnInput) vnInput.focus();
    });
  }

  if ( vnInput ) {
    vnInput.addEventListener("compositionstart", () => {
      isImeComposing = true;
    });

    vnInput.addEventListener("compositionend", () => {
      isImeComposing = false;
      if (liveWordMode && vnInput.value.endsWith(" ")) {
        flushVnInput(false);
      }
    });

    vnInput.addEventListener("input", () => {
      if (!liveWordMode || isImeComposing) return;
      // Khi người dùng gõ xong 1 từ tiếng Việt + dấu cách (hoặc đọc giọng nói xong cụm từ)
      if (vnInput.value.endsWith(" ")) {
        flushVnInput(false);
      }
    });

    vnInput.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && vnInput.value.length === 0) {
        e.preventDefault();
        triggerHaptic(8);
        if (!sendPayload({ type: "press", key: "backspace" })) {
          appendOfflinePreview("⌫");
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        triggerHaptic(10);
        flushVnInput(true);
      }
    });
  }

  if (btnSendEnter) {
    btnSendEnter.addEventListener("click", () => {
      triggerHaptic(12);
      flushVnInput(true);
      if (vnInput && !isLandscapeMode()) {
        vnInput.focus();
      }
    });
  }

  // Tự động đóng Gboard khi xoay ngang sang bàn phím Full PC 6 hàng
  const landscapeMql = window.matchMedia("(orientation: landscape)");
  landscapeMql.addEventListener("change", (ev) => {
    if (ev.matches) {
      if (vnInput) vnInput.blur();
      if (hasAndroidBridge && typeof window.AndroidBridge.hideSoftKeyboard === "function") {
        try {
          window.AndroidBridge.hideSoftKeyboard();
        } catch {
          // ignore
        }
      }
    }
    setTimeout(() => {
      syncCanvasResolution();
      sendLensConfig();
    }, 80);
  });

  if (typeof ResizeObserver !== "undefined" && lensStage) {
    let resizeTimer = null;
    const ro = new ResizeObserver(() => {
      syncCanvasResolution();
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        sendLensConfig();
      }, 90);
    });
    ro.observe(lensStage);
  }

  // ============================================================================
  // 5. HỆ THỐNG BÀN PHÍM CỨNG ĐA ĐIỂM + STICKY MODIFIERS + AUTO-REPEAT
  // ============================================================================
  let fullscreenAttempted = false;

  async function enterBrowserFullscreen(forceToggle = false) {
    try {
      if (forceToggle && document.fullscreenElement) {
        await document.exitFullscreen();
        return;
      }
      if (!document.fullscreenElement) {
        const root = document.documentElement;
        if (root.requestFullscreen) {
          await root.requestFullscreen({ navigationUI: "hide" });
        }
      }
    } catch {
      // ignore
    }
  }

  function ensureAutoFullscreenOnce() {
    if (hasAndroidBridge || fullscreenAttempted) return;
    fullscreenAttempted = true;
    void enterBrowserFullscreen(false);
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
    const capsBtn = document.querySelector(".key-caps");
    if (capsBtn) {
      capsBtn.classList.toggle("is-locked", capsLocked);
    }

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
        sendPayload({ type: "up", key: mod });
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
      if (!st.chordUsedWhileHeld && heldDuration < 280) {
        st.sticky = true;
      } else {
        st.sticky = false;
        sendPayload({ type: "up", key: mod });
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

  function fireKeyButtonAction(btn) {
    const action = btn.dataset.action;

    if (action === "caps") {
      capsLocked = !capsLocked;
      sendPayload({ type: "press", key: "capslock" });
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
        if (!sendPayload({ type: "combo", keys })) {
          appendOfflinePreview(rawCombo === "cmd,backspace" ? "⌘⌫" : `[${keys.join("+")}]`);
        }
      }
      consumeStickyModifiersAfterKey();
      return;
    }

    if (action === "press") {
      const rawKey = btn.dataset.key || "";
      if (!rawKey) return;
      markModifiersUsedInChord();
      if (!sendPayload({ type: "press", key: rawKey })) {
        const previewChar =
          rawKey === "space"
            ? " "
            : rawKey === "backspace"
            ? "⌫"
            : rawKey === "enter"
            ? "⏎"
            : rawKey.length === 1
            ? rawKey
            : `[${rawKey}]`;
        appendOfflinePreview(previewChar);
      }
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
      handleModifierDown(mod);
      return;
    }

    fireKeyButtonAction(btn);

    if (btn.dataset.repeat === "true" && action === "press") {
      const keyName = btn.dataset.key || "";
      entry.repeatDelayTimer = setTimeout(() => {
        entry.repeatDelayTimer = null;
        entry.repeatIntervalTimer = setInterval(() => {
          if (!sendPayload({ type: "press", key: keyName })) {
            if (keyName === "backspace") appendOfflinePreview("⌫");
          }
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

  // Lắng nghe cảm ứng đa điểm trên các vùng phím cứng (.key)
  function bindKeyZoneTouch(zoneEl) {
    if (!zoneEl) return;
    zoneEl.addEventListener(
      "touchstart",
      (e) => {
        const hitKey = e.target.closest(".key");
        if (!hitKey) return;
        e.preventDefault();
        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const t = e.changedTouches[i];
          const el = document.elementFromPoint(t.clientX, t.clientY);
          const btn = el ? el.closest(".key") : null;
          if (btn) {
            startPointerOnButton(`t_${t.identifier}`, btn);
          }
        }
      },
      { passive: false }
    );

    zoneEl.addEventListener(
      "touchend",
      (e) => {
        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const id = `t_${e.changedTouches[i].identifier}`;
          if (activePointers.has(id)) {
            e.preventDefault();
            endPointer(id);
          }
        }
      },
      { passive: false }
    );

    zoneEl.addEventListener(
      "touchcancel",
      (e) => {
        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const id = `t_${e.changedTouches[i].identifier}`;
          if (activePointers.has(id)) {
            e.preventDefault();
            endPointer(id);
          }
        }
      },
      { passive: false }
    );
  }

  bindKeyZoneTouch(document.getElementById("landscape-rows"));
  bindKeyZoneTouch(document.getElementById("portrait-deck"));

  // Hỗ trợ bấm chuột khi mở test trên máy tính
  document.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    const btn = e.target.closest(".key");
    if (!btn) return;
    e.preventDefault();
    startPointerOnButton("mouse", btn);
  });

  window.addEventListener("mouseup", () => {
    endPointer("mouse");
  });

  window.addEventListener("contextmenu", (e) => {
    if (!e.target.closest(".vn-input")) {
      e.preventDefault();
    }
  });

  syncCanvasResolution();
  syncModifierVisuals();
  connectWebSocket();
})();
