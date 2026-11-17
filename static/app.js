(() => {
  "use strict";

  const wsDots = Array.from(document.querySelectorAll(".js-ws-dot"));
  const utilIcons = Array.from(document.querySelectorAll(".js-util-icon"));
  const layoutLabels = Array.from(document.querySelectorAll(".js-layout-label"));
  const vnBtns = Array.from(document.querySelectorAll(".js-vn-btn"));
  const vnLabels = Array.from(document.querySelectorAll(".js-vn-label"));
  const allKeys = Array.from(document.querySelectorAll(".key"));
  const hasAndroidBridge =
    typeof window.AndroidBridge !== "undefined" && window.AndroidBridge !== null;

  if (hasAndroidBridge) {
    utilIcons.forEach((el) => {
      el.textContent = "⚙";
    });
  }

  for (const btn of allKeys) {
    const flexVal = parseFloat(btn.dataset.flex || "1");
    btn.style.setProperty("--u", String(flexVal));
  }

  // ============================================================================
  // 1. TRẠNG THÁI 3 CHẾ ĐỘ (WIN NGANG / MAC NGANG / PAD DỌC) & BỘ GÕ (VN / EN)
  // ============================================================================
  const STORAGE_HOST_KEY = "mac_kb_server_host";
  const STORAGE_LAYOUT_KEY = "mac_kb_layout_mode";
  const STORAGE_VN_KEY = "mac_kb_vn_mode";
  const STORAGE_ROT_KEY = "mac_kb_pad_rot";

  const LAYOUT_ORDER = ["win", "mac", "pad"];
  const LAYOUT_LABELS = {
    win: "🖥 WIN",
    mac: " MAC",
    pad: "📱 DỌC",
  };

  let kbLayout = "win";
  let vnEnabled = true;
  let padRot = "ccw"; // "ccw" (-90deg) hoặc "cw" (+90deg) khi xoay dọc trong khung ngang

  try {
    const savedLayout = localStorage.getItem(STORAGE_LAYOUT_KEY);
    if (LAYOUT_ORDER.includes(savedLayout)) {
      kbLayout = savedLayout;
    }
    const savedVn = localStorage.getItem(STORAGE_VN_KEY);
    if (savedVn === "0" || savedVn === "false") {
      vnEnabled = false;
    }
    const savedRot = localStorage.getItem(STORAGE_ROT_KEY);
    if (savedRot === "ccw" || savedRot === "cw") {
      padRot = savedRot;
    }
  } catch {
    // ignore
  }

  function applyOrientationForLayout() {
    try {
      if (hasAndroidBridge && typeof window.AndroidBridge.setOrientation === "function") {
        window.AndroidBridge.setOrientation(kbLayout === "pad" ? "portrait" : "landscape");
      }
      if (screen.orientation && typeof screen.orientation.lock === "function") {
        const target = kbLayout === "pad" ? "portrait" : "landscape";
        screen.orientation.lock(target).catch(() => {});
      }
    } catch {
      // ignore
    }
  }

  function syncModeUI() {
    document.body.dataset.layout = kbLayout;
    document.body.dataset.rot = padRot;
    const lbl = LAYOUT_LABELS[kbLayout] || "🖥 WIN";
    layoutLabels.forEach((el) => {
      el.textContent = lbl;
    });
    vnBtns.forEach((el) => {
      el.classList.toggle("is-active", vnEnabled);
    });
    vnLabels.forEach((el) => {
      el.textContent = vnEnabled ? "🇻🇳 VN" : "🇬🇧 EN";
    });
    applyOrientationForLayout();
  }

  function pushConfigToServer() {
    sendPayload({
      type: "config",
      layout: kbLayout,
      vn: vnEnabled,
    });
  }

  function toggleKeyboardLayout() {
    releaseAllActiveTouches();
    const idx = LAYOUT_ORDER.indexOf(kbLayout);
    kbLayout = LAYOUT_ORDER[(idx + 1) % LAYOUT_ORDER.length];
    try {
      localStorage.setItem(STORAGE_LAYOUT_KEY, kbLayout);
    } catch {
      // ignore
    }
    syncModeUI();
    pushConfigToServer();
  }

  function flipPortraitRotation() {
    padRot = padRot === "ccw" ? "cw" : "ccw";
    try {
      localStorage.setItem(STORAGE_ROT_KEY, padRot);
    } catch {
      // ignore
    }
    syncModeUI();
  }

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
  }

  function sendPayload(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
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
  // 3. FULLSCREEN + PHẢN HỒI XÚC GIÁC (HAPTIC)
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
  // 4. MODIFIERS & BÀN PHÍM CẢM ỨNG ĐA ĐIỂM
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

    if (action === "toggle-layout") {
      toggleKeyboardLayout();
      return;
    }

    if (action === "flip-rot") {
      flipPortraitRotation();
      return;
    }

    if (action === "toggle-vn") {
      toggleVietnameseMode();
      return;
    }

    if (action === "util" || action === "fullscreen") {
      if (
        hasAndroidBridge &&
        typeof window.AndroidBridge.openServerDialog === "function"
      ) {
        window.AndroidBridge.openServerDialog();
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
      }
      consumeStickyModifiersAfterKey();
      return;
    }

    if (action === "press") {
      const rawKey = btn.dataset.key || "";
      if (!rawKey) return;
      markModifiersUsedInChord();
      sendPayload({ type: "press", key: rawKey });
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

    if (action === "mouse-left") {
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
  // 5. BỘ XỬ LÝ MAGIC TRACKPAD ĐA ĐIỂM (1 NGÓN DI CHUỘT/CLICK, 2 NGÓN CUỘN/CHUỘT PHẢI)
  // ============================================================================
  const trackpad = document.getElementById("trackpad-surface");
  const tpTouches = new Map(); // identifier -> { x, y, startX, startY }
  let tpGestureStartAt = 0;
  let tpMaxTouches = 0;
  let tpTotalMoved = 0;
  let tpLastTapAt = 0;
  let tpIsTapDragging = false;

  // Chuyển đổi vector (rawDx, rawDy) trên màn hình sang hệ tọa độ dọc thực tế khi cầm điện thoại
  function mapTrackpadDelta(rawDx, rawDy) {
    if (kbLayout === "pad" && window.innerWidth > window.innerHeight) {
      // Màn hình đang bị khóa ngang nhưng giao diện đã xoay dọc 90°
      if (padRot === "ccw") {
        // rotate(-90deg)
        return { dx: -rawDy, dy: rawDx };
      }
      // rotate(90deg)
      return { dx: rawDy, dy: -rawDx };
    }
    return { dx: rawDx, dy: rawDy };
  }

  function applyPointerAcceleration(dx, dy) {
    const dist = Math.hypot(dx, dy);
    const gain = Math.min(3.1, 1.35 + dist * 0.085);
    return {
      dx: dx * gain,
      dy: dy * gain,
    };
  }

  if (trackpad) {
    trackpad.addEventListener(
      "touchstart",
      (e) => {
        e.preventDefault();
        e.stopPropagation();
        ensureAutoFullscreenOnce();

        const now = performance.now();
        if (tpTouches.size === 0) {
          tpGestureStartAt = now;
          tpMaxTouches = 0;
          tpTotalMoved = 0;
          if (now - tpLastTapAt < 260 && e.touches.length === 1) {
            tpIsTapDragging = true;
            sendPayload({ type: "mouse_down", button: "left" });
            triggerHaptic(8);
          }
        }

        for (let i = 0; i < e.changedTouches.length; i += 1) {
          const t = e.changedTouches[i];
          tpTouches.set(t.identifier, {
            x: t.clientX,
            y: t.clientY,
          });
        }
        tpMaxTouches = Math.max(tpMaxTouches, tpTouches.size);
        trackpad.classList.add("is-touching");
      },
      { passive: false }
    );

    trackpad.addEventListener(
      "touchmove",
      (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (tpTouches.size === 0) return;

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
        const avgRawDx = sumDx / movedCount;
        const avgRawDy = sumDy / movedCount;
        const { dx, dy } = mapTrackpadDelta(avgRawDx, avgRawDy);
        tpTotalMoved += Math.hypot(dx, dy);

        if (tpTouches.size >= 2) {
          // Vuốt 2 ngón: Cuộn trang (Scroll)
          sendPayload({
            type: "mouse_scroll",
            dx: -dx * 2.2,
            dy: -dy * 2.2,
          });
        } else {
          // Rê 1 ngón: Di chuyển con trỏ chuột (hoặc kéo thả)
          const accel = applyPointerAcceleration(dx, dy);
          sendPayload({
            type: "mouse_move",
            dx: accel.dx,
            dy: accel.dy,
          });
        }
      },
      { passive: false }
    );

    const handleTrackpadTouchEnd = (e) => {
      e.preventDefault();
      e.stopPropagation();
      for (let i = 0; i < e.changedTouches.length; i += 1) {
        tpTouches.delete(e.changedTouches[i].identifier);
      }

      if (tpTouches.size === 0) {
        trackpad.classList.remove("is-touching");
        const duration = performance.now() - tpGestureStartAt;

        if (tpIsTapDragging) {
          tpIsTapDragging = false;
          sendPayload({ type: "mouse_up", button: "left" });
          if (tpTotalMoved < 6 && duration < 240) {
            // Chạm đúp nhanh (Double click)
            sendPayload({ type: "mouse_click", button: "left", count: 2 });
            tpLastTapAt = 0;
          }
          return;
        }

        if (tpTotalMoved < 9 && duration < 270) {
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

    trackpad.addEventListener("touchend", handleTrackpadTouchEnd, {
      passive: false,
    });
    trackpad.addEventListener("touchcancel", handleTrackpadTouchEnd, {
      passive: false,
    });
  }

  // ============================================================================
  // 6. LẮNG NGHE PHÍM TRÊN CẢ KHUNG NGANG (#kb-shell) & KHUNG DỌC (#pad-shell)
  // ============================================================================
  function bindShellEvents(container) {
    if (!container) return;

    container.addEventListener(
      "touchstart",
      (e) => {
        if (e.target.closest("#trackpad-surface")) return;
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

    container.addEventListener(
      "touchend",
      (e) => {
        if (e.target.closest("#trackpad-surface")) return;
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
        if (e.target.closest("#trackpad-surface")) return;
        e.preventDefault();
        for (let i = 0; i < e.changedTouches.length; i += 1) {
          endPointer(`t_${e.changedTouches[i].identifier}`);
        }
      },
      { passive: false }
    );

    container.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest("#trackpad-surface")) return;
      const btn = e.target.closest(".key");
      if (!btn) return;
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
