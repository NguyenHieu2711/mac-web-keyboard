#!/usr/bin/env python3
"""
Mac Web Virtual Keyboard Server (LAN / Tailscale -> macOS Hardware Key Events)
Lắng nghe tại 0.0.0.0:5050, phục vụ giao diện PWA và bắn tín hiệu phím vật lý
xuống macOS tương thích 100% với EVKey / OpenKey / Telex mặc định của macOS.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mac-web-keyboard")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

IS_MACOS = sys.platform == "darwin"

# ============================================================================
# BẢNG MÃ PHÍM VẬT LÝ CHUẨN APPLE VIRTUAL KEYCODE (macOS HIToolbox Events.h)
# Gửi đúng mã phím phần cứng tiếng Anh để EVKey / OpenKey / Bộ gõ Telex macOS
# tự động ghép dấu tiếng Việt và xử lý Backspace xuyên khoảng trắng mượt 100%.
# ============================================================================
MAC_VK_MAP: Dict[str, int] = {
    "a": 0x00,
    "s": 0x01,
    "d": 0x02,
    "f": 0x03,
    "h": 0x04,
    "g": 0x05,
    "z": 0x06,
    "x": 0x07,
    "c": 0x08,
    "v": 0x09,
    "b": 0x0B,
    "q": 0x0C,
    "w": 0x0D,
    "e": 0x0E,
    "r": 0x0F,
    "y": 0x10,
    "t": 0x11,
    "1": 0x12,
    "2": 0x13,
    "3": 0x14,
    "4": 0x15,
    "6": 0x16,
    "5": 0x17,
    "=": 0x18,
    "9": 0x19,
    "7": 0x1A,
    "-": 0x1B,
    "8": 0x1C,
    "0": 0x1D,
    "]": 0x1E,
    "o": 0x1F,
    "u": 0x20,
    "[": 0x21,
    "i": 0x22,
    "p": 0x23,
    "enter": 0x24,
    "return": 0x24,
    "l": 0x25,
    "j": 0x26,
    "'": 0x27,
    "k": 0x28,
    ";": 0x29,
    "\\": 0x2A,
    ",": 0x2B,
    "/": 0x2C,
    "n": 0x2D,
    "m": 0x2E,
    ".": 0x2F,
    "tab": 0x30,
    "space": 0x31,
    " ": 0x31,
    "`": 0x32,
    "backspace": 0x33,
    "esc": 0x35,
    "escape": 0x35,
    "cmd": 0x37,
    "command": 0x37,
    "win": 0x37,
    "super": 0x37,
    "shift": 0x38,
    "shift_l": 0x38,
    "capslock": 0x39,
    "alt": 0x3A,
    "option": 0x3A,
    "opt": 0x3A,
    "ctrl": 0x3B,
    "control": 0x3B,
    "shift_r": 0x3C,
    "del": 0x75,
    "delete": 0x75,
    "left": 0x7B,
    "arrowleft": 0x7B,
    "right": 0x7C,
    "arrowright": 0x7C,
    "down": 0x7D,
    "arrowdown": 0x7D,
    "up": 0x7E,
    "arrowup": 0x7E,
}

# Các ký tự viết hoa / ký hiệu cần tự động kẹp Shift nếu gửi trực tiếp
SHIFTED_SYMBOL_TO_BASE: Dict[str, str] = {
    "~": "`",
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
}

CANONICAL_MODIFIER: Dict[str, str] = {
    "cmd": "cmd",
    "command": "cmd",
    "win": "cmd",
    "super": "cmd",
    "shift": "shift",
    "shift_l": "shift",
    "shift_r": "shift",
    "alt": "alt",
    "option": "alt",
    "opt": "alt",
    "ctrl": "ctrl",
    "control": "ctrl",
}


class KeyboardInjector:
    """Bộ điều khiển bắn sự kiện phím vật lý tối ưu cho macOS (Quartz CGEvent + pynput fallback)."""

    def __init__(self) -> None:
        self.held_modifiers: Set[str] = set()
        self.caps_locked: bool = False
        self._use_quartz = False
        self._quartz = None
        self._event_source = None

        if IS_MACOS:
            try:
                import Quartz  # type: ignore

                self._quartz = Quartz
                # kCGEventSourceStatePrivate (-1): chuẩn của Hammerspoon/Espanso khi chạy ngầm qua launchd
                self._event_source = Quartz.CGEventSourceCreate(
                    Quartz.kCGEventSourceStatePrivate
                )
                self._use_quartz = True
                logger.info(
                    "Đã kích hoạt bộ phát phím phần cứng Quartz CGEvent (kCGHIDEventTap) cho macOS."
                )
            except Exception as exc:
                logger.warning(
                    "Không tìm thấy Quartz (%s), chuyển sang chế độ pynput.", exc
                )

        from pynput.keyboard import Controller, Key, KeyCode

        self._kb = Controller()
        self._Key = Key
        self._KeyCode = KeyCode
        self._pynput_special = {
            "enter": Key.enter,
            "return": Key.enter,
            "backspace": Key.backspace,
            "del": Key.delete,
            "delete": Key.delete,
            "tab": Key.tab,
            "space": Key.space,
            " ": Key.space,
            "esc": Key.esc,
            "escape": Key.esc,
            "capslock": Key.caps_lock,
            "up": Key.up,
            "arrowup": Key.up,
            "down": Key.down,
            "arrowdown": Key.down,
            "left": Key.left,
            "arrowleft": Key.left,
            "right": Key.right,
            "arrowright": Key.right,
            "cmd": Key.cmd,
            "shift": Key.shift,
            "alt": Key.alt,
            "ctrl": Key.ctrl,
        }

    # -------------------- Quartz Native macOS Path --------------------
    def _compute_quartz_flags(self, extra_mods: Set[str] | None = None) -> int:
        q = self._quartz
        mods = set(self.held_modifiers)
        if extra_mods:
            mods.update(extra_mods)
        flags = 0
        if "cmd" in mods:
            flags |= q.kCGEventFlagMaskCommand
        if "shift" in mods:
            flags |= q.kCGEventFlagMaskShift
        if "alt" in mods:
            flags |= q.kCGEventFlagMaskAlternate
        if "ctrl" in mods:
            flags |= q.kCGEventFlagMaskControl
        if self.caps_locked:
            flags |= q.kCGEventFlagMaskAlphaShift
        return flags

    def _quartz_post_vk(
        self, vk: int, is_down: bool, extra_mods: Set[str] | None = None
    ) -> None:
        q = self._quartz
        ev = q.CGEventCreateKeyboardEvent(self._event_source, vk, is_down)
        flags = self._compute_quartz_flags(extra_mods)
        existing = q.CGEventGetFlags(ev)
        mod_mask = (
            q.kCGEventFlagMaskCommand
            | q.kCGEventFlagMaskShift
            | q.kCGEventFlagMaskAlternate
            | q.kCGEventFlagMaskControl
            | q.kCGEventFlagMaskAlphaShift
        )
        q.CGEventSetFlags(ev, (existing & ~mod_mask) | flags)
        q.CGEventPost(q.kCGHIDEventTap, ev)

    # -------------------- Pynput Cross-Platform Fallback --------------------
    def _resolve_pynput_key(self, norm_key: str):
        if norm_key in self._pynput_special:
            return self._pynput_special[norm_key]
        if IS_MACOS and norm_key in MAC_VK_MAP:
            return self._KeyCode.from_vk(MAC_VK_MAP[norm_key])
        if len(norm_key) == 1:
            return self._KeyCode.from_char(norm_key)
        return None

    # -------------------- Public Actions --------------------
    def normalize_key(self, raw_key: str) -> tuple[str, bool]:
        """Trả về (tên_phím_chuẩn, có_cần_kẹp_shift_tạm_không)."""
        if not raw_key:
            return ("", False)
        if raw_key == " ":
            return ("space", False)
        if len(raw_key) == 1:
            if raw_key in SHIFTED_SYMBOL_TO_BASE:
                return (SHIFTED_SYMBOL_TO_BASE[raw_key], True)
            if "A" <= raw_key <= "Z":
                return (raw_key.lower(), True)
            return (raw_key.lower(), False)
        lowered = raw_key.strip().lower()
        if lowered in CANONICAL_MODIFIER:
            return (CANONICAL_MODIFIER[lowered], False)
        return (lowered, False)

    def key_down(self, raw_key: str) -> None:
        norm, _ = self.normalize_key(raw_key)
        if not norm:
            return
        if norm in ("cmd", "shift", "alt", "ctrl"):
            self.held_modifiers.add(norm)

        if self._use_quartz and norm in MAC_VK_MAP:
            self._quartz_post_vk(MAC_VK_MAP[norm], True)
            return

        pk = self._resolve_pynput_key(norm)
        if pk is not None:
            self._kb.press(pk)

    def key_up(self, raw_key: str) -> None:
        norm, _ = self.normalize_key(raw_key)
        if not norm:
            return
        if norm in ("cmd", "shift", "alt", "ctrl"):
            self.held_modifiers.discard(norm)

        if self._use_quartz and norm in MAC_VK_MAP:
            self._quartz_post_vk(MAC_VK_MAP[norm], False)
            return

        pk = self._resolve_pynput_key(norm)
        if pk is not None:
            self._kb.release(pk)

    def press_key(self, raw_key: str) -> None:
        norm, auto_shift = self.normalize_key(raw_key)
        if not norm:
            return

        if norm == "capslock":
            self.caps_locked = not self.caps_locked

        extra_mods: Set[str] = {"shift"} if auto_shift else set()

        if self._use_quartz and norm in MAC_VK_MAP:
            vk = MAC_VK_MAP[norm]
            need_temp_shift = auto_shift and "shift" not in self.held_modifiers
            if need_temp_shift:
                self._quartz_post_vk(MAC_VK_MAP["shift"], True, extra_mods)
            self._quartz_post_vk(vk, True, extra_mods)
            self._quartz_post_vk(vk, False, extra_mods)
            if need_temp_shift:
                self._quartz_post_vk(MAC_VK_MAP["shift"], False)
            return

        pk = self._resolve_pynput_key(norm)
        if pk is None:
            return
        need_temp_shift = auto_shift and "shift" not in self.held_modifiers
        if need_temp_shift:
            self._kb.press(self._Key.shift)
        try:
            self._kb.press(pk)
            self._kb.release(pk)
        finally:
            if need_temp_shift:
                self._kb.release(self._Key.shift)

    def press_combo(self, keys: List[str]) -> None:
        if not keys:
            return
        mods: List[str] = []
        normals: List[str] = []
        for k in keys:
            norm, _ = self.normalize_key(k)
            if not norm:
                continue
            if norm in ("cmd", "shift", "alt", "ctrl"):
                if norm not in mods:
                    mods.append(norm)
            else:
                normals.append(norm)

        if self._use_quartz:
            mod_set = set(mods)
            for m in mods:
                if m in MAC_VK_MAP:
                    self._quartz_post_vk(MAC_VK_MAP[m], True, mod_set)
            time.sleep(0.004)
            for n in normals:
                if n in MAC_VK_MAP:
                    self._quartz_post_vk(MAC_VK_MAP[n], True, mod_set)
                    time.sleep(0.004)
                    self._quartz_post_vk(MAC_VK_MAP[n], False, mod_set)
            time.sleep(0.004)
            for m in reversed(mods):
                if m in MAC_VK_MAP and m not in self.held_modifiers:
                    self._quartz_post_vk(MAC_VK_MAP[m], False)
            return

        # Fallback pynput (dùng trên Windows/Linux hoặc macOS thiếu Quartz)
        mapped_mods = []
        for m in mods:
            # Trên Windows/Linux khi test cục bộ: ánh xạ cmd -> ctrl để test nhanh Ctrl+Z/C/V/A
            effective_mod = "ctrl" if (m == "cmd" and not IS_MACOS) else m
            pk = self._resolve_pynput_key(effective_mod)
            if pk is not None:
                mapped_mods.append((m, pk))

        for _, pk in mapped_mods:
            self._kb.press(pk)
        try:
            for n in normals:
                pk_n = self._resolve_pynput_key(n)
                if pk_n is not None:
                    self._kb.press(pk_n)
                    self._kb.release(pk_n)
        finally:
            for orig_m, pk in reversed(mapped_mods):
                if orig_m not in self.held_modifiers:
                    self._kb.release(pk)

    def release_all_modifiers(self) -> None:
        if not self.held_modifiers:
            return
        stuck = list(self.held_modifiers)
        self.held_modifiers.clear()
        for m in stuck:
            try:
                self.key_up(m)
            except Exception:
                pass


injector = KeyboardInjector()
app = FastAPI(title="Mac Web Virtual Keyboard", docs_url=None, redoc_url=None)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/style.css")
async def style_css() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "style.css",
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/app.js")
async def app_js() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "app.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/manifest.json")
async def manifest_json() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "manifest.json",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "platform": sys.platform}


@app.websocket("/ws")
async def keyboard_ws(ws: WebSocket) -> None:
    await ws.accept()
    client_host = ws.client.host if ws.client else "unknown"
    trusted = check_macos_accessibility(prompt=True)
    logger.info(
        "Đã kết nối điện thoại từ: %s (Accessibility=%s)", client_host, trusted
    )
    warned_untrusted = not trusted
    if IS_MACOS and not trusted:
        await ws.send_text('{"type":"error","reason":"accessibility_denied"}')
    try:
        while True:
            raw_msg = await ws.receive_text()
            try:
                data = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")
            if warned_untrusted and msg_type in ("press", "down", "combo") and IS_MACOS:
                if check_macos_accessibility(prompt=False):
                    warned_untrusted = False
                else:
                    await ws.send_text(
                        '{"type":"error","reason":"accessibility_denied"}'
                    )

            if msg_type == "press":
                key = str(data.get("key", ""))
                injector.press_key(key)
            elif msg_type == "down":
                key = str(data.get("key", ""))
                injector.key_down(key)
            elif msg_type == "up":
                key = str(data.get("key", ""))
                injector.key_up(key)
            elif msg_type == "combo":
                keys = data.get("keys")
                if isinstance(keys, list):
                    injector.press_combo([str(k) for k in keys])
            elif msg_type == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        logger.info("Điện thoại đã ngắt kết nối: %s", client_host)
    except Exception as exc:
        logger.error("Lỗi WebSocket (%s): %s", client_host, exc)
    finally:
        # Chống kẹt phím bổ trợ (Cmd/Shift/Alt/Ctrl) nếu rớt mạng đột ngột
        injector.release_all_modifiers()


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def check_macos_accessibility(prompt: bool = True) -> bool:
    if not IS_MACOS:
        return True
    try:
        import ctypes
        import ctypes.util

        app_services_path = ctypes.util.find_library("ApplicationServices")
        cf_path = ctypes.util.find_library("CoreFoundation")
        if not app_services_path:
            return True
        app_services = ctypes.cdll.LoadLibrary(app_services_path)

        if prompt and cf_path:
            cf = ctypes.cdll.LoadLibrary(cf_path)
            prompt_key = ctypes.c_void_p.in_dll(
                app_services, "kAXTrustedCheckOptionPrompt"
            )
            k_true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
            cf.CFDictionaryCreate.restype = ctypes.c_void_p
            cf.CFDictionaryCreate.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            keys = (ctypes.c_void_p * 1)(prompt_key)
            vals = (ctypes.c_void_p * 1)(k_true)
            opts = cf.CFDictionaryCreate(None, keys, vals, 1, None, None)
            app_services.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
            app_svc_fn = app_services.AXIsProcessTrustedWithOptions
            app_svc_fn.argtypes = [ctypes.c_void_p]
            trusted = bool(app_svc_fn(opts))
        else:
            app_services.AXIsProcessTrusted.restype = ctypes.c_bool
            trusted = bool(app_services.AXIsProcessTrusted())

        if not trusted:
            real_exe = Path(sys.executable).resolve()
            logger.warning(
                "⚠️ CHƯA CẤP QUYỀN ACCESSIBILITY CHO PYTHON (%s)! "
                "Vào System Settings -> Privacy & Security -> Accessibility -> Bật Python.",
                real_exe,
            )
        return trusted
    except Exception:
        return True


def detect_network_ips() -> List[str]:
    ips: List[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
        if lan_ip and not lan_ip.startswith("127."):
            ips.append(f"LAN Wi-Fi : http://{lan_ip}:5050")
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["tailscale", "ip", "-4"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.5,
        ).strip()
        ts_ip = out.splitlines()[0].strip() if out else ""
        if ts_ip:
            ips.append(f"Tailscale : http://{ts_ip}:5050")
    except Exception:
        pass

    return ips


if __name__ == "__main__":
    check_macos_accessibility()
    banner_ips = detect_network_ips()
    print("\n" + "=" * 62)
    print("  ⌨️  MAC WEB VIRTUAL KEYBOARD SERVER ĐANG CHẠY (PORT 5050)")
    print("=" * 62)
    if banner_ips:
        for line in banner_ips:
            print(f"  👉 Mở trên Samsung S24+: {line}")
    else:
        print("  👉 Mở trên trình duyệt:  http://<IP-MacBook>:5050")
    print("=" * 62 + "\n")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5050,
        log_level="warning",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )
