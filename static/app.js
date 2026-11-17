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

  const LAYOUT_LABELS = {
    pad: "📱 Mac dọc",
    win: "🖥 Win",
    mac: " Mac",
  };

  let kbLayout = "pad";
  let vnEnabled = true;
  let symLayer = false;
  let modeMenuOpen = false;

  try {
    const savedLayout = localStorage.getItem(STORAGE_LAYOUT_KEY);
    if (savedLayout === "win" || savedLayout === "mac" || savedLayout === "pad") {
      kbLayout = savedLayout;
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
    const lbl = LAYOUT_LABELS[kbLayout] || "📱 Mac dọc";
    layoutLabels.forEach((el) => {
      el.textContent = lbl;
    });
    vnBtns.forEach((el) => {
      el.classList.toggle("is-active", vnEnabled);
    });
    vnLabels.forEach((el) => {
      el.textContent = vnEnabled ? "🇻🇳 VN" : "🇬🇧 EN";
    });
    modeItems.forEach((item) => {
      item.classList.toggle("is-selected", item.dataset.selectLayout === kbLayout);
    });
    modeMenus.forEach((menu) => {
      menu.classList.toggle("is-hidden", !modeMenuOpen);
    });
    if (symPopup) {
      symPopup.classList.toggle("is-hidden", !symLayer);
    }
    applyOrientationForLayout();
  }

  function pushConfigToServer() {
    sendPayload({
      type: "config",
      layout: kbLayout,
      vn: vnEnabled,
    });
  }

  function toggleModeMenu() {
    modeMenuOpen = !modeMenuOpen;
    if (modeMenuOpen) {
      symLayer = false;
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

  function toggleSymbolLayer() {
    symLayer = !symLayer;
    if (symLayer) {
      modeMenuOpen = false;
    }
    syncModeUI();
  }

  function closeSymbolPopup() {
    if (!symLayer) return;
    symLayer = false;
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
      const item = e.target.closest(".sym-item[data-sym-key]");
      if (item) {
        e.preventDefault();
        e.stopPropagation();
        triggerHaptic(10);
        const symKey = item.dataset.symKey || "";
        if (symKey) {
          markModifiersUsedInChord();
          sendPayload({ type: "press", key: symKey });
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

    if (action === "toggle-mode-menu") {
      toggleModeMenu();
      return;
    }

    if (action === "toggle-vn") {
      closeModeMenu();
      toggleVietnameseMode();
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
  // 5. NÚT MŨI TÊN THÔNG MINH 1 NÚT DUY NHẤT (ẤN & GẠT LÊN/XUỐNG/TRÁI/PHẢI)
  // ============================================================================
  const joyBtn = document.getElementById("btn-joy-arrow");
  const joyLabel = document.getElementById("joy-arrow-label");
  let joyState = null; // { id, startX, startY, activeDir, repeatTimer }

  const DIR_ICONS = {
    up: "▲",
    down: "▼",
    left: "◀",
    right: "▶",
  };

  function stopJoyRepeat() {
    if (joyState && joyState.repeatTimer) {
      clearInterval(joyState.repeatTimer);
      joyState.repeatTimer = null;
    }
  }

  function fireArrowDirection(dir) {
    markModifiersUsedInChord();
    sendPayload({ type: "press", key: dir });
    consumeStickyModifiersAfterKey();
  }

  function updateJoyDirection(curX, curY) {
    if (!joyState) return;
    const dx = curX - joyState.startX;
    const dy = curY - joyState.startY;
    const dist = Math.hypot(dx, dy);
    if (dist < 8) return;

    let newDir = "";
    if (Math.abs(dx) > Math.abs(dy)) {
      newDir = dx > 0 ? "right" : "left";
    } else {
      newDir = dy > 0 ? "down" : "up";
    }

    if (newDir && newDir !== joyState.activeDir) {
      joyState.activeDir = newDir;
      stopJoyRepeat();
      triggerHaptic(10);
      if (joyLabel) {
        joyLabel.textContent = DIR_ICONS[newDir] || "✥";
      }
      fireArrowDirection(newDir);
      joyState.repeatTimer = setInterval(() => {
        fireArrowDirection(newDir);
      }, 65);
    }
  }

  function endJoyGesture() {
    if (!joyState) return;
    stopJoyRepeat();
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
        stopJoyRepeat();
        joyState = {
          id: t.identifier,
          startX: t.clientX,
          startY: t.clientY,
          activeDir: "",
          repeatTimer: null,
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
        if (!joyState) return;
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
      stopJoyRepeat();
      joyState = {
        id: "mouse",
        startX: e.clientX,
        startY: e.clientY,
        activeDir: "",
        repeatTimer: null,
      };
      joyBtn.classList.add("is-active-joy");
    });

    window.addEventListener("mousemove", (e) => {
      if (joyState && joyState.id === "mouse") {
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
  // 6. BỘ XỬ LÝ MAGIC TRACKPAD ĐA ĐIỂM
  // ============================================================================
  const trackpad = document.getElementById("trackpad-surface");
  const tpTouches = new Map();
  let tpGestureStartAt = 0;
  let tpMaxTouches = 0;
  let tpTotalMoved = 0;
  let tpLastTapAt = 0;
  let tpIsTapDragging = false;

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
        closeModeMenu();
        closeSymbolPopup();
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
        const dx = sumDx / movedCount;
        const dy = sumDy / movedCount;
        tpTotalMoved += Math.hypot(dx, dy);

        if (tpTouches.size >= 2) {
          sendPayload({
            type: "mouse_scroll",
            dx: -dx * 2.2,
            dy: -dy * 2.2,
          });
        } else {
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
  // 7. LẮNG NGHE PHÍM TRÊN KHUNG NGANG (#kb-shell) & KHUNG DỌC (#pad-shell)
  // ============================================================================
  function bindShellEvents(container) {
    if (!container) return;

    container.addEventListener(
      "touchstart",
      (e) => {
        if (
          e.target.closest("#trackpad-surface") ||
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

  // ============================================================================
  // 8. KIỂM TRA BẮT BUỘC CẬP NHẬT NGAY KHI BẤM MỞ APP (MANDATORY UPDATE GATE)
  // ============================================================================
  const CURRENT_APP_VERSION = "1.6.0";
  const updateModal = document.getElementById("mandatory-update-modal");
  const updateTitle = document.getElementById("update-title");
  const updateDesc = document.getElementById("update-desc");
  const btnDoUpdate = document.getElementById("btn-do-update");

  function isNewerVer(remoteTag, currentVer) {
    const cleanR = String(remoteTag || "").trim().replace(/^[vV]/, "").split("-")[0];
    const cleanC = String(currentVer || "").trim().replace(/^[vV]/, "").split("-")[0];
    if (!cleanR || cleanR === cleanC) return false;
    const rParts = cleanR.split(".").map((n) => parseInt(n, 10) || 0);
    const cParts = cleanC.split(".").map((n) => parseInt(n, 10) || 0);
    const len = Math.max(rParts.length, cParts.length);
    for (let i = 0; i < len; i += 1) {
      const rv = rParts[i] || 0;
      const cv = cParts[i] || 0;
      if (rv > cv) return true;
      if (rv < cv) return false;
    }
    return false;
  }

  async function checkMandatoryUpdateGate() {
    if (!hasAndroidBridge) return;
    try {
      const resp = await fetch(
        `https://raw.githubusercontent.com/NguyenHieu2711/mac-web-keyboard/main/releases/latest.json?t=${Date.now()}`,
        { cache: "no-store" }
      );
      if (!resp.ok) return;
      const data = await resp.json();
      const tag = String(data.tag_name || "").trim();
      const apkUrl = String(data.apk_url || "").trim();
      if (tag && isNewerVer(tag, CURRENT_APP_VERSION) && updateModal) {
        if (updateTitle) {
          updateTitle.textContent = `Có bản cập nhật mới (${tag})`;
        }
        if (updateDesc) {
          updateDesc.textContent = `Phiên bản ${tag} đã sẵn sàng (bản hiện tại: v${CURRENT_APP_VERSION}). Bạn bắt buộc phải cập nhật ngay để tiếp tục sử dụng ứng dụng.`;
        }
        updateModal.classList.remove("is-hidden");
        if (btnDoUpdate) {
          btnDoUpdate.onclick = () => {
            btnDoUpdate.textContent = "Đang tải bản cập nhật...";
            btnDoUpdate.disabled = true;
            if (apkUrl) {
              window.location.href = apkUrl;
            }
          };
        }
      }
    } catch {
      // ignore
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      void checkMandatoryUpdateGate();
    }
  });

  syncModifierVisuals();
  connectWebSocket();
  void checkMandatoryUpdateGate();
})();
