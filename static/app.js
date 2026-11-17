(() => {
  "use strict";

  const wsDot = document.getElementById("ws-dot");
  const utilIcon = document.getElementById("util-icon");
  const allKeys = Array.from(document.querySelectorAll(".key"));
  const hasAndroidBridge =
    typeof window.AndroidBridge !== "undefined" && window.AndroidBridge !== null;

  if (hasAndroidBridge && utilIcon) {
    utilIcon.textContent = "⚙";
  }

  // Áp dụng tỷ lệ độ rộng chuẩn PC/Mac cho từng phím theo data-flex
  for (const btn of allKeys) {
    const flexVal = parseFloat(btn.dataset.flex || "1");
    btn.style.flexGrow = String(flexVal);
  }

  // ============================================================================
  // 1. QUẢN LÝ KẾT NỐI WEBSOCKET TỰ ĐỘNG RECONNECT ĐỘ TRỄ 0MS (LAN / TAILSCALE)
  // ============================================================================
  const STORAGE_HOST_KEY = "mac_kb_server_host";
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
    if (!wsDot) return;
    wsDot.classList.toggle("is-online", online);
    wsDot.classList.toggle("is-offline", !online);
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
  // 2. FULLSCREEN + KHÓA XOAY NGANG LANDSCAPE CHO SAMSUNG S24+
  // ============================================================================
  let fullscreenAttempted = false;

  async function enterLandscapeFullscreen(forceToggle = false) {
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
      if (screen.orientation && typeof screen.orientation.lock === "function") {
        await screen.orientation.lock("landscape").catch(() => {});
      }
    } catch {
      // Trình duyệt có thể từ chối nếu chưa đủ tương tác
    }
  }

  function ensureAutoFullscreenOnce() {
    if (hasAndroidBridge) return;
    if (fullscreenAttempted) return;
    fullscreenAttempted = true;
    void enterLandscapeFullscreen(false);
  }

  function triggerHaptic(ms = 10) {
    if (hasAndroidBridge && typeof window.AndroidBridge.vibrate === "function") {
      try {
        window.AndroidBridge.vibrate(ms);
        return;
      } catch {
        // fallback navigator.vibrate
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
  // 3. TRẠNG THÁI MODIFIERS (ĐA ĐIỂM NHẤN GIỮ + CHẠM STICKY 1 NGÓN) & AUTO-REPEAT
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

    // Nếu đang Sticky mà người dùng chạm lại lần nữa -> tắt Sticky ngay
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
      // Chạm nhanh < 280ms và chưa bấm kèm phím chữ -> chuyển sang chế độ Sticky khóa sáng!
      if (!st.chordUsedWhileHeld && heldDuration < 280) {
        st.sticky = true;
        // Giữ nguyên trạng thái "down" trên server cho tới khi bấm phím tiếp theo
      } else {
        st.sticky = false;
        sendPayload({ type: "up", key: mod });
      }
    }
    syncModifierVisuals();
  }

  // Theo dõi từng ngón tay độc lập (pointerId / touch.identifier)
  // value: { btn, repeatDelayTimer, repeatIntervalTimer, action, mod }
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

    if (action === "util" || action === "fullscreen") {
      if (
        hasAndroidBridge &&
        typeof window.AndroidBridge.openServerDialog === "function"
      ) {
        window.AndroidBridge.openServerDialog();
      } else {
        void enterLandscapeFullscreen(true);
      }
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

    fireKeyButtonAction(btn);

    if (btn.dataset.repeat === "true" && action === "press") {
      const keyName = btn.dataset.key || "";
      entry.repeatDelayTimer = setTimeout(() => {
        entry.repeatDelayTimer = null;
        entry.repeatIntervalTimer = setInterval(() => {
          sendPayload({ type: "press", key: keyName });
        }, 46);
      }, 310);
    }
  }

  function endPointer(pointerId) {
    const entry = activePointers.get(pointerId);
    if (!entry) return;
    activePointers.delete(pointerId);
    clearRepeatTimers(entry);

    // Chỉ gỡ hiệu ứng sáng phím nếu không còn ngón tay nào khác đang đè trên chính nút đó
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

  // ============================================================================
  // 4. LẮNG NGHE CẢM ỨNG ĐA ĐIỂM (TOUCH EVENTS + MOUSE FALLBACK CHO DESKTOP)
  // ============================================================================
  const shell = document.getElementById("kb-shell");

  shell.addEventListener(
    "touchstart",
    (e) => {
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

  shell.addEventListener(
    "touchend",
    (e) => {
      e.preventDefault();
      for (let i = 0; i < e.changedTouches.length; i += 1) {
        endPointer(`t_${e.changedTouches[i].identifier}`);
      }
    },
    { passive: false }
  );

  shell.addEventListener(
    "touchcancel",
    (e) => {
      e.preventDefault();
      for (let i = 0; i < e.changedTouches.length; i += 1) {
        endPointer(`t_${e.changedTouches[i].identifier}`);
      }
    },
    { passive: false }
  );

  // Cho phép test trực tiếp bằng chuột khi mở thử trên trình duyệt Mac/PC
  shell.addEventListener("mousedown", (e) => {
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
    e.preventDefault();
  });

  syncModifierVisuals();
  connectWebSocket();
})();
