#!/usr/bin/env python3
"""
Mac & Windows Web Virtual Keyboard + Live Cursor Lens Server (Port 5050)
- Truyền phím vật lý độ trễ 0ms (Quartz CGEvent trên macOS / pynput trên Windows)
- Điều khiển chuột Trackpad (di chuột, click trái/phải, cuộn 2 ngón)
- Bơm trực tiếp chuỗi tiếng Việt Unicode từ Gboard / Giọng nói không ghi đè Clipboard
- Truyền luồng Kính Soi Vùng Con Trỏ (Live Lens) nhị phân tốc độ cao luôn lấy con chuột làm trung tâm
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import io
import json
import logging
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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
IS_WINDOWS = sys.platform == "win32"

# Bật nhận diện DPI thật trên Windows để tọa độ chuột khớp 100% với ảnh chụp màn hình mss
if IS_WINDOWS:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# ============================================================================
# BẢNG MÃ PHÍM VẬT LÝ CHUẨN APPLE VIRTUAL KEYCODE (macOS HIToolbox Events.h)
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


class InputAndLensController:
    """Điều khiển bàn phím, chuột Trackpad và chụp Kính Soi trung tâm con chuột (macOS + Windows)."""

    def __init__(self) -> None:
        self.held_modifiers: Set[str] = set()
        self.caps_locked: bool = False
        self._use_quartz = False
        self._quartz = None
        self._event_source = None

        # Trạng thái neo tâm Kính Soi khi gõ phím
        self.last_input_ts: float = time.monotonic()
        self.typing_locked: bool = False
        self.anchor_x: Optional[float] = None
        self.anchor_y: Optional[float] = None
        self.last_observed_mouse: Tuple[float, float] = (0.0, 0.0)

        if IS_MACOS:
            try:
                import Quartz  # type: ignore

                self._quartz = Quartz
                self._event_source = Quartz.CGEventSourceCreate(
                    Quartz.kCGEventSourceStatePrivate
                )
                self._use_quartz = True
                logger.info(
                    "Đã kích hoạt Quartz CGEvent (Keyboard + Mouse + Unicode) cho macOS."
                )
            except Exception as exc:
                logger.warning(
                    "Không tìm thấy Quartz (%s), chuyển sang chế độ pynput.", exc
                )

        from pynput.keyboard import Controller as KBController, Key, KeyCode
        from pynput.mouse import Button as MouseButton, Controller as MouseController

        self._kb = KBController()
        self._mouse = MouseController()
        self._MouseButton = MouseButton
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
            "cmd": Key.cmd if IS_MACOS else Key.ctrl,
            "shift": Key.shift,
            "alt": Key.alt,
            "ctrl": Key.ctrl,
        }

        try:
            pos = self.get_mouse_position()
            self.last_observed_mouse = pos
            self.anchor_x, self.anchor_y = pos
        except Exception:
            pass

    def mark_activity(self) -> None:
        self.last_input_ts = time.monotonic()

    # -------------------- Mouse & Trackpad --------------------
    def get_mouse_position(self) -> Tuple[float, float]:
        if self._use_quartz:
            q = self._quartz
            ev = q.CGEventCreate(None)
            loc = q.CGEventGetLocation(ev)
            return (float(loc.x), float(loc.y))
        pos = self._mouse.position
        return (float(pos[0]), float(pos[1]))

    def move_mouse_relative(self, dx: float, dy: float) -> None:
        self.mark_activity()
        self.typing_locked = False
        cur_x, cur_y = self.get_mouse_position()
        nx = cur_x + dx
        ny = cur_y + dy

        if self._use_quartz:
            q = self._quartz
            # Kẹp trong phạm vi màn hình chính/phụ để không trôi vô cực
            ev = q.CGEventCreateMouseEvent(
                self._event_source,
                q.kCGEventMouseMoved,
                (nx, ny),
                q.kCGMouseButtonLeft,
            )
            q.CGEventPost(q.kCGHIDEventTap, ev)
            new_pos = self.get_mouse_position()
            self.anchor_x, self.anchor_y = new_pos
            self.last_observed_mouse = new_pos
            return

        self._mouse.position = (int(round(nx)), int(round(ny)))
        new_pos = self.get_mouse_position()
        self.anchor_x, self.anchor_y = new_pos
        self.last_observed_mouse = new_pos

    def click_mouse(self, button: str = "left", count: int = 1) -> None:
        self.mark_activity()
        cur_x, cur_y = self.get_mouse_position()
        self.anchor_x, self.anchor_y = cur_x, cur_y
        self.last_observed_mouse = (cur_x, cur_y)
        self.typing_locked = True

        is_right = button == "right"
        clicks = max(1, min(3, int(count)))

        if self._use_quartz:
            q = self._quartz
            btn_const = q.kCGMouseButtonRight if is_right else q.kCGMouseButtonLeft
            down_type = (
                q.kCGEventRightMouseDown if is_right else q.kCGEventLeftMouseDown
            )
            up_type = q.kCGEventRightMouseUp if is_right else q.kCGEventLeftMouseUp
            for click_idx in range(1, clicks + 1):
                ev_down = q.CGEventCreateMouseEvent(
                    self._event_source, down_type, (cur_x, cur_y), btn_const
                )
                q.CGEventSetIntegerValueField(
                    ev_down, q.kCGMouseEventClickState, click_idx
                )
                q.CGEventPost(q.kCGHIDEventTap, ev_down)

                ev_up = q.CGEventCreateMouseEvent(
                    self._event_source, up_type, (cur_x, cur_y), btn_const
                )
                q.CGEventSetIntegerValueField(
                    ev_up, q.kCGMouseEventClickState, click_idx
                )
                q.CGEventPost(q.kCGHIDEventTap, ev_up)
            return

        btn_obj = self._MouseButton.right if is_right else self._MouseButton.left
        self._mouse.click(btn_obj, clicks)

    def scroll_mouse(self, dx: float, dy: float) -> None:
        self.mark_activity()
        self.typing_locked = False
        if self._use_quartz:
            q = self._quartz
            ev = q.CGEventCreateScrollWheelEvent(
                self._event_source,
                q.kCGScrollEventUnitPixel,
                2,
                int(round(dy)),
                int(round(dx)),
            )
            q.CGEventPost(q.kCGHIDEventTap, ev)
            return

        # Trên Windows/Linux pynput tính theo nấc bánh xe (120px ~ 1 nấc)
        step_y = dy / 36.0
        step_x = dx / 36.0
        if abs(step_y) >= 0.1 or abs(step_x) >= 0.1:
            self._mouse.scroll(step_x, step_y)

    # -------------------- Unicode Vietnamese Text Injection --------------------
    def inject_unicode_text(self, text: str) -> None:
        if not text:
            return
        self.mark_activity()
        self.typing_locked = True
        if self.anchor_x is None or self.anchor_y is None:
            self.anchor_x, self.anchor_y = self.get_mouse_position()

        if self._use_quartz:
            q = self._quartz
            # Chia nhỏ theo cụm 16 ký tự để macOS xử lý mượt mọi chuỗi tiếng Việt dài
            chunk_size = 16
            for i in range(0, len(text), chunk_size):
                chunk = text[i : i + chunk_size]
                utf16_len = len(chunk.encode("utf-16-le")) // 2
                ev_down = q.CGEventCreateKeyboardEvent(self._event_source, 0, True)
                q.CGEventKeyboardSetUnicodeString(ev_down, utf16_len, chunk)
                q.CGEventPost(q.kCGHIDEventTap, ev_down)

                ev_up = q.CGEventCreateKeyboardEvent(self._event_source, 0, False)
                q.CGEventKeyboardSetUnicodeString(ev_up, utf16_len, chunk)
                q.CGEventPost(q.kCGHIDEventTap, ev_up)
            return

        # Fallback chuẩn trên Windows / Linux
        self._kb.type(text)

    # -------------------- Quartz Native Keyboard Path --------------------
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

    def _resolve_pynput_key(self, norm_key: str):
        if norm_key in self._pynput_special:
            return self._pynput_special[norm_key]
        if IS_MACOS and norm_key in MAC_VK_MAP:
            return self._KeyCode.from_vk(MAC_VK_MAP[norm_key])
        if len(norm_key) == 1:
            return self._KeyCode.from_char(norm_key)
        return None

    def normalize_key(self, raw_key: str) -> tuple[str, bool]:
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
        self.mark_activity()
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
        self.mark_activity()
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
        self.mark_activity()
        self.typing_locked = True
        if self.anchor_x is None or self.anchor_y is None:
            self.anchor_x, self.anchor_y = self.get_mouse_position()

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
        self.mark_activity()
        self.typing_locked = True
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

        mapped_mods = []
        for m in mods:
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

    # -------------------- Caret Detection (Windows GUIThreadInfo) --------------------
    def get_system_caret_position(self) -> Optional[Tuple[float, float]]:
        if IS_WINDOWS:
            try:
                user32 = ctypes.windll.user32

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long),
                    ]

                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                class GUITHREADINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", ctypes.c_ulong),
                        ("flags", ctypes.c_ulong),
                        ("hwndActive", ctypes.c_void_p),
                        ("hwndFocus", ctypes.c_void_p),
                        ("hwndCapture", ctypes.c_void_p),
                        ("hwndMenuOwner", ctypes.c_void_p),
                        ("hwndMoveSize", ctypes.c_void_p),
                        ("hwndCaret", ctypes.c_void_p),
                        ("rcCaret", RECT),
                    ]

                fg = user32.GetForegroundWindow()
                tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
                gti = GUITHREADINFO()
                gti.cbSize = ctypes.sizeof(GUITHREADINFO)
                if user32.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndCaret:
                    pt = POINT(
                        (gti.rcCaret.left + gti.rcCaret.right) // 2,
                        (gti.rcCaret.top + gti.rcCaret.bottom) // 2,
                    )
                    if user32.ClientToScreen(gti.hwndCaret, ctypes.byref(pt)):
                        if pt.x != 0 or pt.y != 0:
                            return (float(pt.x), float(pt.y))
            except Exception:
                pass
        return None


class LiveLensStreamer:
    """Chụp vùng màn hình lấy con trỏ chuột / dấu nháy làm trung tâm và đóng gói nhị phân tốc độ cao."""

    def __init__(self, ctrl: InputAndLensController) -> None:
        self.ctrl = ctrl
        self._mss_mod = None
        self._pil_image = None
        try:
            import mss  # type: ignore
            from PIL import Image  # type: ignore

            self._mss_mod = mss
            self._pil_image = Image
        except Exception as exc:
            logger.warning(
                "Chưa cài mss/Pillow (%s) — tính năng Kính Soi Live Lens sẽ tạm tắt.",
                exc,
            )

    @property
    def available(self) -> bool:
        return self._mss_mod is not None and self._pil_image is not None

    def capture_frame_packet(
        self,
        sct,
        aspect: float,
        fov_scale: float,
        mode: str,
        pan_x: float = 0.0,
        pan_y: float = 0.0,
    ) -> Optional[bytes]:
        if not self.available:
            return None

        Image = self._pil_image
        mx, my = self.ctrl.get_mouse_position()

        # Nếu chuột vật lý trên bàn Mac/PC vừa nhích > 3px -> tự mở khóa đi theo chuột ngay!
        prev_mx, prev_my = self.ctrl.last_observed_mouse
        if abs(mx - prev_mx) > 3.0 or abs(my - prev_my) > 3.0:
            self.ctrl.last_observed_mouse = (mx, my)
            self.ctrl.anchor_x, self.ctrl.anchor_y = mx, my
            self.ctrl.typing_locked = False
            self.ctrl.mark_activity()

        # Xác định tâm nhìn (Focus Center): luôn ưu tiên vị trí chuột (hoặc Caret khi đang gõ)
        caret = self.ctrl.get_system_caret_position() if self.ctrl.typing_locked else None
        if caret is not None:
            focus_x, focus_y = caret
        elif self.ctrl.typing_locked and self.ctrl.anchor_x is not None and self.ctrl.anchor_y is not None:
            focus_x = self.ctrl.anchor_x + pan_x
            focus_y = self.ctrl.anchor_y + pan_y
        else:
            focus_x, focus_y = mx + pan_x, my + pan_y

        # Tìm màn hình chứa điểm focus_x, focus_y
        monitors = sct.monitors
        chosen_mon = monitors[1] if len(monitors) > 1 else monitors[0]
        for mon in monitors[1:]:
            if (
                mon["left"] <= focus_x < mon["left"] + mon["width"]
                and mon["top"] <= focus_y < mon["top"] + mon["height"]
            ):
                chosen_mon = mon
                break

        mon_w = float(chosen_mon["width"])
        mon_h = float(chosen_mon["height"])

        # Khung nhìn rộng thoáng mặc định (~62% chiều ngang màn hình để chữ nhỏ vừa vặn, nhìn bao quát rộng)
        safe_aspect = max(1.1, min(14.0, float(aspect or 1.8)))
        safe_scale = max(0.55, min(1.8, float(fov_scale or 1.0)))

        if mode == "landscape":
            base_w = min(mon_w, max(680.0, mon_w * 0.58) * safe_scale)
            crop_w = int(round(base_w))
            crop_h = max(72, int(round(crop_w / safe_aspect)))
            target_out_w = 860
        else:
            # Màn dọc: lấy rộng ~65% bề ngang màn máy tính (VD ~1100px trên màn 1728px / 1920px)
            # để nội dung thu nhỏ vừa phải, nhìn thoáng trọn cả cột ghi chú quanh tâm con chuột!
            base_w = min(mon_w, max(780.0, mon_w * 0.64) * safe_scale)
            crop_w = int(round(base_w))
            crop_h = max(180, min(int(mon_h), int(round(crop_w / safe_aspect))))
            target_out_w = 820

        crop_w = max(240, min(int(mon_w), crop_w))
        crop_h = max(70, min(int(mon_h), crop_h))

        left = int(round(focus_x - crop_w / 2.0))
        top = int(round(focus_y - crop_h / 2.0))

        min_left = int(chosen_mon["left"])
        max_left = int(chosen_mon["left"] + chosen_mon["width"] - crop_w)
        min_top = int(chosen_mon["top"])
        max_top = int(chosen_mon["top"] + chosen_mon["height"] - crop_h)

        left = max(min_left, min(max_left, left))
        top = max(min_top, min(max_top, top))

        raw = sct.grab({"left": left, "top": top, "width": crop_w, "height": crop_h})
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        if img.width > target_out_w:
            out_h = max(48, int(round(img.height * (target_out_w / float(img.width)))))
            resample_attr = getattr(Image, "Resampling", Image).BILINEAR
            img = img.resize((target_out_w, out_h), resample_attr)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=68, optimize=False)
        jpeg_bytes = buf.getvalue()

        # Tọa độ tương đối chính xác [0..10000] của con chuột bên trong khung ảnh vừa cắt
        rel_mx = max(0.0, min(1.0, (mx - left) / float(crop_w)))
        rel_my = max(0.0, min(1.0, (my - top) / float(crop_h)))
        u_mx = int(round(rel_mx * 10000))
        u_my = int(round(rel_my * 10000))

        flags = 1 if self.ctrl.typing_locked else 0
        u_cx = u_mx
        u_cy = int(round(rel_my * 255))
        if caret is not None:
            flags |= 2
            rel_cx = max(0.0, min(1.0, (caret[0] - left) / float(crop_w)))
            rel_cy = max(0.0, min(1.0, (caret[1] - top) / float(crop_h)))
            u_cx = int(round(rel_cx * 10000))
            u_cy = int(round(rel_cy * 255))

        # Header 12 bytes: b"LENS" + uint16 mx + uint16 my + uint8 flags + uint16 cx + uint8 cy
        header = struct.pack(">4sHHBHB", b"LENS", u_mx, u_my, flags, u_cx, u_cy)
        return header + jpeg_bytes


controller = InputAndLensController()
lens_streamer = LiveLensStreamer(controller)
app = FastAPI(title="Mac Web Virtual Keyboard & Live Lens", docs_url=None, redoc_url=None)


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
    return {
        "ok": True,
        "platform": sys.platform,
        "lens_available": lens_streamer.available,
    }


@app.websocket("/ws")
async def keyboard_ws(ws: WebSocket) -> None:
    await ws.accept()
    client_host = ws.client.host if ws.client else "unknown"
    trusted = check_macos_accessibility(prompt=True)
    check_macos_screen_recording(prompt=True)
    logger.info(
        "Đã kết nối điện thoại từ: %s (Accessibility=%s, Lens=%s)",
        client_host,
        trusted,
        lens_streamer.available,
    )
    warned_untrusted = not trusted
    if IS_MACOS and not trusted:
        await ws.send_text('{"type":"error","reason":"accessibility_denied"}')

    # Cấu hình phiên Kính Soi cho kết nối hiện tại
    lens_state = {
        "enabled": True,
        "aspect": 1.75,
        "scale": 1.0,
        "mode": "portrait",
        "pan_x": 0.0,
        "pan_y": 0.0,
        "running": True,
    }

    async def stream_lens_loop() -> None:
        if not lens_streamer.available:
            return
        sct = lens_streamer._mss_mod.mss()
        try:
            while lens_state["running"]:
                if not lens_state["enabled"]:
                    await asyncio.sleep(0.25)
                    continue

                idle_sec = time.monotonic() - controller.last_input_ts
                # Đang rê chuột/gõ phím: 22 FPS siêu mượt; nghỉ > 2.5s: hạ xuống 4 FPS tiết kiệm pin
                interval = 0.045 if idle_sec < 2.5 else 0.24

                try:
                    packet = await asyncio.to_thread(
                        lens_streamer.capture_frame_packet,
                        sct,
                        lens_state["aspect"],
                        lens_state["scale"],
                        lens_state["mode"],
                        lens_state["pan_x"],
                        lens_state["pan_y"],
                    )
                    if packet:
                        await ws.send_bytes(packet)
                except WebSocketDisconnect:
                    break
                except Exception as exc:
                    logger.debug("Bỏ qua khung hình Lens: %s", exc)
                    await asyncio.sleep(0.2)

                await asyncio.sleep(interval)
        finally:
            try:
                sct.close()
            except Exception:
                pass

    lens_task = asyncio.create_task(stream_lens_loop())

    try:
        while True:
            raw_msg = await ws.receive_text()
            try:
                data = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")
            if warned_untrusted and msg_type in ("press", "down", "combo", "text") and IS_MACOS:
                if check_macos_accessibility(prompt=False):
                    warned_untrusted = False
                else:
                    await ws.send_text(
                        '{"type":"error","reason":"accessibility_denied"}'
                    )

            if msg_type == "press":
                key = str(data.get("key", ""))
                controller.press_key(key)
            elif msg_type == "down":
                key = str(data.get("key", ""))
                controller.key_down(key)
            elif msg_type == "up":
                key = str(data.get("key", ""))
                controller.key_up(key)
            elif msg_type == "combo":
                keys = data.get("keys")
                if isinstance(keys, list):
                    controller.press_combo([str(k) for k in keys])
            elif msg_type == "text":
                txt = str(data.get("text", ""))
                if txt:
                    controller.inject_unicode_text(txt)
            elif msg_type == "mouse_move":
                dx = float(data.get("dx", 0.0))
                dy = float(data.get("dy", 0.0))
                lens_state["pan_x"] = 0.0
                lens_state["pan_y"] = 0.0
                controller.move_mouse_relative(dx, dy)
            elif msg_type == "mouse_click":
                btn = str(data.get("button", "left"))
                cnt = int(data.get("count", 1))
                lens_state["pan_x"] = 0.0
                lens_state["pan_y"] = 0.0
                controller.click_mouse(btn, cnt)
            elif msg_type == "mouse_scroll":
                dx = float(data.get("dx", 0.0))
                dy = float(data.get("dy", 0.0))
                controller.scroll_mouse(dx, dy)
            elif msg_type == "lens_pan":
                lens_state["pan_x"] += float(data.get("dx", 0.0))
                lens_state["pan_y"] += float(data.get("dy", 0.0))
                controller.mark_activity()
            elif msg_type == "lens_unlock":
                controller.typing_locked = False
                lens_state["pan_x"] = 0.0
                lens_state["pan_y"] = 0.0
                controller.mark_activity()
            elif msg_type == "lens_config":
                if "enabled" in data:
                    lens_state["enabled"] = bool(data["enabled"])
                if "aspect" in data:
                    lens_state["aspect"] = float(data["aspect"])
                if "scale" in data:
                    lens_state["scale"] = float(data["scale"])
                if "mode" in data:
                    lens_state["mode"] = str(data["mode"])
                controller.mark_activity()
            elif msg_type == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        logger.info("Điện thoại đã ngắt kết nối: %s", client_host)
    except Exception as exc:
        logger.error("Lỗi WebSocket (%s): %s", client_host, exc)
    finally:
        lens_state["running"] = False
        lens_task.cancel()
        controller.release_all_modifiers()


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def check_macos_accessibility(prompt: bool = True) -> bool:
    if not IS_MACOS:
        return True
    try:
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
            app_svc_fn = app_services.AXIsProcessTrustedWithOptions
            app_svc_fn.restype = ctypes.c_bool
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


def check_macos_screen_recording(prompt: bool = True) -> bool:
    if not IS_MACOS:
        return True
    try:
        import Quartz  # type: ignore

        if hasattr(Quartz, "CGPreflightScreenCaptureAccess"):
            has_perm = bool(Quartz.CGPreflightScreenCaptureAccess())
            if not has_perm and prompt and hasattr(Quartz, "CGRequestScreenCaptureAccess"):
                Quartz.CGRequestScreenCaptureAccess()
            return has_perm
    except Exception:
        pass
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
    check_macos_accessibility(prompt=True)
    check_macos_screen_recording(prompt=True)
    banner_ips = detect_network_ips()
    print("\n" + "=" * 66)
    print("  ⌨️  MAC/PC WEB KEYBOARD + LIVE CURSOR LENS SERVER (PORT 5050)")
    print("=" * 66)
    if banner_ips:
        for line in banner_ips:
            print(f"  👉 Nhập vào S24+: {line}")
    else:
        print("  👉 Nhập vào S24+: http://<IP-Máy-Tính>:5050")
    print("=" * 66 + "\n")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5050,
        log_level="warning",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )
