#!/usr/bin/env python3
"""
Mac Web Virtual Keyboard Server (LAN / Tailscale -> macOS Hardware Key Events)
Lắng nghe tại 0.0.0.0:5050, phục vụ giao diện PWA / Android WebView với:
- 2 bộ bàn phím vật lý chuẩn: Bàn phím dây Windows (ANSI PC) & Bàn phím Mac.
- Bộ gõ Tiếng Việt Telex chuẩn PC (Unikey / EVKey) tích hợp trực tiếp trên Server.
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
import threading
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
    "fn": 0x3F,
    "f1": 0x7A,
    "f2": 0x78,
    "f3": 0x63,
    "f4": 0x76,
    "f5": 0x60,
    "f6": 0x61,
    "f7": 0x62,
    "f8": 0x64,
    "f9": 0x65,
    "f10": 0x6D,
    "f11": 0x67,
    "f12": 0x6F,
    "home": 0x73,
    "pageup": 0x74,
    "del": 0x75,
    "delete": 0x75,
    "end": 0x77,
    "pagedown": 0x79,
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

# Các phím tắt trên bàn phím dây Windows khi giữ Ctrl sẽ ánh xạ sang Cmd trên macOS
WIN_CTRL_TO_CMD_KEYS: Set[str] = {
    "a", "b", "c", "f", "g", "h", "i", "k", "l", "n", "o", "p", "q",
    "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=",
    "[", "]", "/", ",", ".", ";", "'",
}


# ============================================================================
# BỘ GÕ TIẾNG VIỆT TELEX CHUẨN PC (UNIKEY / EVKEY ENGINE)
# ============================================================================
VOWEL_TONE_TABLE: Dict[str, Tuple[str, str, str, str, str, str]] = {
    "a": ("a", "á", "à", "ả", "ã", "ạ"),
    "ă": ("ă", "ắ", "ằ", "ẳ", "ẵ", "ặ"),
    "â": ("â", "ấ", "ầ", "ẩ", "ẫ", "ậ"),
    "e": ("e", "é", "è", "ẻ", "ẽ", "ẹ"),
    "ê": ("ê", "ế", "ề", "ể", "ễ", "ệ"),
    "i": ("i", "í", "ì", "ỉ", "ĩ", "ị"),
    "o": ("o", "ó", "ò", "ỏ", "õ", "ọ"),
    "ô": ("ô", "ố", "ồ", "ổ", "ỗ", "ộ"),
    "ơ": ("ơ", "ớ", "ờ", "ở", "ỡ", "ợ"),
    "u": ("u", "ú", "ù", "ủ", "ũ", "ụ"),
    "ư": ("ư", "ứ", "ừ", "ử", "ữ", "ự"),
    "y": ("y", "ý", "ỳ", "ỷ", "ỹ", "ỵ"),
    "A": ("A", "Á", "À", "Ả", "Ã", "Ạ"),
    "Ă": ("Ă", "Ắ", "Ằ", "Ẳ", "Ẵ", "Ặ"),
    "Â": ("Â", "Ấ", "Ầ", "Ẩ", "Ẫ", "Ậ"),
    "E": ("E", "É", "È", "Ẻ", "Ẽ", "Ẹ"),
    "Ê": ("Ê", "Ế", "Ề", "Ể", "Ễ", "Ệ"),
    "I": ("I", "Í", "Ì", "Ỉ", "Ĩ", "Ị"),
    "O": ("O", "Ó", "Ò", "Ỏ", "Õ", "Ọ"),
    "Ô": ("Ô", "Ố", "Ồ", "Ổ", "Ỗ", "Ộ"),
    "Ơ": ("Ơ", "Ớ", "Ờ", "Ở", "Ỡ", "Ợ"),
    "U": ("U", "Ú", "Ù", "Ủ", "Ũ", "Ụ"),
    "Ư": ("Ư", "Ứ", "Ừ", "Ử", "Ữ", "Ự"),
    "Y": ("Y", "Ý", "Ỳ", "Ỷ", "Ỹ", "Ỵ"),
}

CHAR_TO_BASE_TONE: Dict[str, Tuple[str, int]] = {}
for _base, _forms in VOWEL_TONE_TABLE.items():
    for _t_idx, _ch in enumerate(_forms):
        CHAR_TO_BASE_TONE[_ch] = (_base, _t_idx)

TONE_KEY_MAP: Dict[str, int] = {
    "s": 1,  # Sắc
    "f": 2,  # Huyền
    "r": 3,  # Hỏi
    "x": 4,  # Ngã
    "j": 5,  # Nặng
    "z": 0,  # Xóa dấu thanh
}

DIACRITIC_VOWELS_LOWER = {"ă", "â", "ê", "ô", "ơ", "ư"}


def _match_case(template: str, target_lower: str) -> str:
    return target_lower.upper() if template.isupper() else target_lower


def _compose_vowel(base: str, tone: int) -> str:
    forms = VOWEL_TONE_TABLE.get(base)
    if not forms:
        return base
    return forms[max(0, min(5, tone))]


class VietnameseTelexEngine:
    """Bộ xử lý âm tiết Telex kiểu Unikey/EVKey: bỏ dấu tự do, gõ lặp trả phím gốc."""

    def __init__(self) -> None:
        self.word: str = ""
        self.raw_locked: bool = False
        self.last_transform_key: str = ""

    def reset(self) -> None:
        self.word = ""
        self.raw_locked = False
        self.last_transform_key = ""

    def backspace(self) -> None:
        if self.word:
            self.word = self.word[:-1]
        if not self.word:
            self.raw_locked = False
            self.last_transform_key = ""

    def _extract_word_tone(self, chars: List[str]) -> Tuple[List[str], int]:
        tone = 0
        base_chars: List[str] = []
        for ch in chars:
            if ch in CHAR_TO_BASE_TONE:
                b, t = CHAR_TO_BASE_TONE[ch]
                if t != 0:
                    tone = t
                base_chars.append(b)
            else:
                base_chars.append(ch)
        return base_chars, tone

    def _find_vowel_span(self, base_chars: List[str]) -> List[int]:
        indices = [i for i, c in enumerate(base_chars) if c in VOWEL_TONE_TABLE]
        if not indices:
            return []
        # Xử lý phụ âm đầu 'qu' và 'gi' (không tính u/i là nguyên âm chính nếu phía sau còn nguyên âm)
        if len(indices) >= 2:
            first_v = indices[0]
            if first_v == 1 and base_chars[0].lower() == "q" and base_chars[1].lower() == "u":
                indices = indices[1:]
            elif first_v == 1 and base_chars[0].lower() == "g" and base_chars[1].lower() == "i":
                indices = indices[1:]
        return indices

    def _place_tone(self, base_chars: List[str], tone: int) -> List[str]:
        if tone == 0:
            return list(base_chars)
        v_indices = self._find_vowel_span(base_chars)
        if not v_indices:
            return list(base_chars)

        target_idx = v_indices[0]
        if len(v_indices) == 1:
            target_idx = v_indices[0]
        else:
            # Ưu tiên nguyên âm có mũ/móc (ă, â, ê, ô, ơ, ư); nếu là cụm 'ươ' thì đặt vào 'ơ'
            special = [
                idx
                for idx in v_indices
                if base_chars[idx].lower() in DIACRITIC_VOWELS_LOWER
            ]
            if len(special) >= 2:
                # Ví dụ ươ -> đặt dấu vào ơ
                target_idx = special[-1]
            elif len(special) == 1:
                target_idx = special[0]
            elif len(v_indices) == 3:
                target_idx = v_indices[1]
            else:
                # 2 nguyên âm không dấu phụ: nếu có phụ âm cuối hoặc oa/oe/uy -> nguyên âm thứ 2, ngược lại nguyên âm 1
                has_final_consonant = v_indices[-1] < len(base_chars) - 1
                pair_lower = (
                    base_chars[v_indices[0]].lower() + base_chars[v_indices[1]].lower()
                )
                if has_final_consonant or pair_lower in ("oa", "oe", "uy"):
                    target_idx = v_indices[1]
                else:
                    target_idx = v_indices[0]

        result = list(base_chars)
        result[target_idx] = _compose_vowel(result[target_idx], tone)
        return result

    def process_char(self, ch: str) -> Tuple[str, str]:
        """
        Nhận 1 ký tự chữ cái (a-z, A-Z).
        Trả về (old_word, new_word) để bộ phát phím tính số Backspace + chuỗi thay thế.
        """
        old_word = self.word
        low = ch.lower()

        if self.raw_locked:
            self.word += ch
            return old_word, self.word

        chars = list(self.word)
        base_chars, current_tone = self._extract_word_tone(chars)

        # 1. Xử lý gõ lặp phím vừa biến đổi (aa->a, ee->e, oo->o, ww->w, dd->d, ss->s...) -> Hoàn tác!
        if self.last_transform_key == low and len(chars) >= 1:
            if low == "d":
                for i in range(len(base_chars)):
                    if base_chars[i].lower() == "đ":
                        base_chars[i] = _match_case(base_chars[i], "d")
                        rebuilt = self._place_tone(base_chars, current_tone)
                        rebuilt.append(ch)
                        self.word = "".join(rebuilt)
                        self.raw_locked = True
                        self.last_transform_key = ""
                        return old_word, self.word
            elif low in ("a", "e", "o"):
                hat_map = {"a": "â", "e": "ê", "o": "ô"}
                target_hat = hat_map[low]
                for i in range(len(base_chars) - 1, -1, -1):
                    if base_chars[i].lower() == target_hat:
                        base_chars[i] = _match_case(base_chars[i], low)
                        rebuilt = self._place_tone(base_chars, current_tone)
                        rebuilt.append(ch)
                        self.word = "".join(rebuilt)
                        self.raw_locked = True
                        self.last_transform_key = ""
                        return old_word, self.word
            elif low == "w":
                undone = False
                for i in range(len(base_chars) - 1, -1, -1):
                    bl = base_chars[i].lower()
                    if bl in ("ă", "ơ", "ư"):
                        # Nếu là ư đứng độc lập do gõ 'w' trước đó -> thay bằng 'w'
                        if (
                            i == len(base_chars) - 1
                            and bl == "ư"
                            and self.last_transform_key == "w_standalone"
                        ):
                            base_chars[i] = _match_case(base_chars[i], "w")
                            rebuilt = self._place_tone(base_chars, current_tone)
                            self.word = "".join(rebuilt)
                            self.raw_locked = True
                            self.last_transform_key = ""
                            return old_word, self.word
                        orig_map = {"ă": "a", "ơ": "o", "ư": "u"}
                        base_chars[i] = _match_case(base_chars[i], orig_map[bl])
                        undone = True
                if undone:
                    rebuilt = self._place_tone(base_chars, current_tone)
                    rebuilt.append(ch)
                    self.word = "".join(rebuilt)
                    self.raw_locked = True
                    self.last_transform_key = ""
                    return old_word, self.word
            elif low in TONE_KEY_MAP:
                rebuilt = self._place_tone(base_chars, 0)
                rebuilt.append(ch)
                self.word = "".join(rebuilt)
                self.raw_locked = True
                self.last_transform_key = ""
                return old_word, self.word

        # 2. Xử lý 'dd' -> 'đ'
        if low == "d" and len(base_chars) >= 1 and base_chars[0].lower() == "d":
            # Chỉ biến thành 'đ' nếu chữ cái đầu là 'd' và từ hợp lệ
            base_chars[0] = _match_case(base_chars[0], "đ")
            rebuilt = self._place_tone(base_chars, current_tone)
            self.word = "".join(rebuilt)
            self.last_transform_key = "d"
            return old_word, self.word

        # 3. Xử lý mũ 'aa' -> 'â', 'ee' -> 'ê', 'oo' -> 'ô'
        if low in ("a", "e", "o"):
            hat_map = {"a": "â", "e": "ê", "o": "ô"}
            for i in range(len(base_chars) - 1, -1, -1):
                if base_chars[i].lower() == low:
                    base_chars[i] = _match_case(base_chars[i], hat_map[low])
                    rebuilt = self._place_tone(base_chars, current_tone)
                    self.word = "".join(rebuilt)
                    self.last_transform_key = low
                    return old_word, self.word

        # 4. Xử lý móc / trăng 'w' -> ươ / ư / ơ / ă
        if low == "w":
            v_span = self._find_vowel_span(base_chars)
            if v_span:
                # Kiểm tra cụm 'uo' / 'ưo' / 'uơ' / 'uô' -> 'ươ'
                for idx in range(len(v_span) - 1):
                    i1, i2 = v_span[idx], v_span[idx + 1]
                    b1, b2 = base_chars[i1].lower(), base_chars[i2].lower()
                    if b1 in ("u", "ư") and b2 in ("o", "ô", "ơ"):
                        base_chars[i1] = _match_case(base_chars[i1], "ư")
                        base_chars[i2] = _match_case(base_chars[i2], "ơ")
                        rebuilt = self._place_tone(base_chars, current_tone)
                        self.word = "".join(rebuilt)
                        self.last_transform_key = "w"
                        return old_word, self.word
                # Biến đổi nguyên âm đơn u->ư, o->ơ, a->ă (ưu tiên từ cuối lên)
                w_map = {"u": "ư", "o": "ơ", "a": "ă"}
                for i in reversed(v_span):
                    bl = base_chars[i].lower()
                    if bl in w_map:
                        base_chars[i] = _match_case(base_chars[i], w_map[bl])
                        rebuilt = self._place_tone(base_chars, current_tone)
                        self.word = "".join(rebuilt)
                        self.last_transform_key = "w"
                        return old_word, self.word

        # 5. Xử lý 5 dấu thanh (s, f, r, x, j) và xóa dấu (z)
        if low in TONE_KEY_MAP:
            v_span = self._find_vowel_span(base_chars)
            if v_span:
                new_tone = TONE_KEY_MAP[low]
                if new_tone == 0 and current_tone == 0:
                    # Từ chưa có dấu thanh mà bấm 'z' -> gõ chữ 'z' bình thường
                    pass
                elif new_tone == current_tone and new_tone != 0:
                    # Đã có đúng dấu thanh đó rồi mà bấm lại -> trả về không dấu + ký tự vừa bấm
                    rebuilt = self._place_tone(base_chars, 0)
                    rebuilt.append(ch)
                    self.word = "".join(rebuilt)
                    self.raw_locked = True
                    self.last_transform_key = ""
                    return old_word, self.word
                else:
                    rebuilt = self._place_tone(base_chars, new_tone)
                    self.word = "".join(rebuilt)
                    self.last_transform_key = low
                    return old_word, self.word

        # 6. Ký tự thường nối vào từ (và tự căn lại vị trí dấu thanh nếu thêm nguyên âm/phụ âm cuối, VD: hoàn, tiếng)
        base_chars.append(ch)
        if current_tone != 0:
            rebuilt = self._place_tone(base_chars, current_tone)
        else:
            rebuilt = base_chars
        self.word = "".join(rebuilt)
        self.last_transform_key = ""
        return old_word, self.word


def ensure_macos_abc_input_source() -> None:
    """Chuyển bộ gõ macOS về ABC để tránh xung đột gạch chân với bộ gõ Telex nội bộ của Server."""
    if not IS_MACOS:
        return
    try:
        import ctypes
        import Foundation  # noqa: F401 - đăng ký bridge NSArray/NSString cho PyObjC
        import objc

        carbon = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/Carbon.framework/Carbon"
        )
        carbon.TISCreateInputSourceList.restype = ctypes.c_void_p
        carbon.TISCreateInputSourceList.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
        carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        carbon.TISSelectInputSource.restype = ctypes.c_int
        carbon.TISSelectInputSource.argtypes = [ctypes.c_void_p]

        k_id = ctypes.c_void_p.in_dll(carbon, "kTISPropertyInputSourceID")
        arr = objc.objc_object(c_void_p=carbon.TISCreateInputSourceList(None, True))
        for src in arr:
            ptr = src.__c_void_p__()
            prop = carbon.TISGetInputSourceProperty(ptr, k_id)
            if prop and str(objc.objc_object(c_void_p=prop)) == "com.apple.keylayout.ABC":
                carbon.TISSelectInputSource(ptr)
                break
    except Exception as exc:
        logger.warning("Không thể tự chuyển về ABC: %s", exc)


class KeyboardInjector:
    """Bộ điều khiển bắn sự kiện phím vật lý + Unicode Telex cho macOS."""

    def __init__(self) -> None:
        self.held_modifiers: Set[str] = set()
        self.caps_locked: bool = False
        self.vn_enabled: bool = True
        self.kb_layout: str = "win"  # "win", "mac", hoặc "pad" (Chế độ dọc Trackpad + Phím)
        self.telex = VietnameseTelexEngine()
        self._use_quartz = False
        self._quartz = None
        self._event_source = None
        self._mouse_x: float = 500.0
        self._mouse_y: float = 500.0
        self._last_mouse_sync: float = 0.0
        self._mouse_buttons_down: Set[str] = set()
        self._last_left_click_at: float = 0.0
        self._left_click_count: int = 0

        if IS_MACOS:
            try:
                import Quartz  # type: ignore

                self._quartz = Quartz
                self._event_source = Quartz.CGEventSourceCreate(
                    Quartz.kCGEventSourceStatePrivate
                )
                self._use_quartz = True
                ensure_macos_abc_input_source()
                logger.info(
                    "Đã kích hoạt Quartz CGEvent + Bộ gõ Tiếng Việt Telex chuẩn PC."
                )
            except Exception as exc:
                logger.warning(
                    "Không tìm thấy Quartz (%s), chuyển sang chế độ pynput.", exc
                )

        from pynput.keyboard import Controller, Key, KeyCode
        from pynput.mouse import Button as MouseButton, Controller as MouseController

        self._kb = Controller()
        self._pynput_mouse = MouseController()
        self._MouseButton = MouseButton
        self.last_activity_at: float = time.monotonic()
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
        self,
        vk: int,
        is_down: bool,
        extra_mods: Set[str] | None = None,
        override_mods: Set[str] | None = None,
    ) -> None:
        q = self._quartz
        ev = q.CGEventCreateKeyboardEvent(self._event_source, vk, is_down)
        if override_mods is not None:
            saved = self.held_modifiers
            self.held_modifiers = set(override_mods)
            flags = self._compute_quartz_flags()
            self.held_modifiers = saved
        else:
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

    def _quartz_post_unicode(self, text: str) -> None:
        if not text:
            return
        q = self._quartz
        for ch in text:
            ev_down = q.CGEventCreateKeyboardEvent(self._event_source, 0, True)
            q.CGEventSetFlags(ev_down, 0)
            q.CGEventKeyboardSetUnicodeString(ev_down, len(ch), ch)
            q.CGEventPost(q.kCGHIDEventTap, ev_down)

            ev_up = q.CGEventCreateKeyboardEvent(self._event_source, 0, False)
            q.CGEventSetFlags(ev_up, 0)
            q.CGEventKeyboardSetUnicodeString(ev_up, len(ch), ch)
            q.CGEventPost(q.kCGHIDEventTap, ev_up)

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
            if norm in ("cmd", "alt", "ctrl"):
                self.telex.reset()

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

    def _handle_win_layout_shortcut(self, norm: str) -> bool:
        """
        Khi đang ở bộ bàn phím dây Windows ('win') hoặc chế độ dọc Trackpad ('pad') và người dùng giữ Ctrl:
        Tự động dịch các phím tắt chuẩn PC (Ctrl+C/V/X/Z/Y/A/S/F/Backspace/Arrows) sang thao tác tương ứng trên macOS.
        """
        if self.kb_layout not in ("win", "pad") or "ctrl" not in self.held_modifiers:
            return False
        if "cmd" in self.held_modifiers or "alt" in self.held_modifiers:
            return False

        self.telex.reset()
        has_shift = "shift" in self.held_modifiers

        # Ctrl + Y trên Windows -> Cmd + Shift + Z (Redo trên Mac)
        if norm == "y" and not has_shift:
            self._exec_translated_chord(
                MAC_VK_MAP["z"], {"cmd", "shift"}
            )
            return True

        # Ctrl + Backspace / Del / Left / Right trên Windows -> Option (Alt) trên Mac (xóa/nhảy từng từ)
        if norm in ("backspace", "del", "delete", "left", "right") and norm in MAC_VK_MAP:
            target_mods = {"alt"}
            if has_shift:
                target_mods.add("shift")
            self._exec_translated_chord(MAC_VK_MAP[norm], target_mods)
            return True

        # Ctrl + C/V/X/Z/A/S/F/T/W/R/L/N... -> Cmd + phím trên Mac
        if norm in WIN_CTRL_TO_CMD_KEYS and norm in MAC_VK_MAP:
            target_mods = {"cmd"}
            if has_shift:
                target_mods.add("shift")
            self._exec_translated_chord(MAC_VK_MAP[norm], target_mods)
            return True

        return False

    def _exec_translated_chord(self, vk: int, target_mods: Set[str]) -> None:
        if not self._use_quartz:
            return
        # Tạm nhả Ctrl vật lý, bắn tổ hợp đích (Cmd/Alt), rồi khôi phục Ctrl nếu vẫn đang giữ
        self._quartz_post_vk(MAC_VK_MAP["ctrl"], False, override_mods=set())
        for m in target_mods:
            if m in MAC_VK_MAP:
                self._quartz_post_vk(MAC_VK_MAP[m], True, override_mods=target_mods)
        time.sleep(0.002)
        self._quartz_post_vk(vk, True, override_mods=target_mods)
        self._quartz_post_vk(vk, False, override_mods=target_mods)
        time.sleep(0.002)
        for m in target_mods:
            if m in MAC_VK_MAP and m not in self.held_modifiers:
                self._quartz_post_vk(MAC_VK_MAP[m], False, override_mods=set())
        if "ctrl" in self.held_modifiers:
            self._quartz_post_vk(
                MAC_VK_MAP["ctrl"], True, override_mods=self.held_modifiers
            )

    def press_key(self, raw_key: str) -> None:
        self.last_activity_at = time.monotonic()
        norm, auto_shift = self.normalize_key(raw_key)
        if not norm:
            return

        if norm == "capslock":
            self.caps_locked = not self.caps_locked
            self.telex.reset()

        # Kiểm tra ánh xạ phím tắt Ctrl chuẩn PC nếu đang ở giao diện Bàn phím dây Windows
        if self._handle_win_layout_shortcut(norm):
            return

        has_non_shift_mod = any(
            m in self.held_modifiers for m in ("cmd", "alt", "ctrl")
        )

        # Xử lý Backspace với bộ đệm Telex
        if norm == "backspace" and not has_non_shift_mod:
            self.telex.backspace()
            self._send_raw_vk("backspace", False)
            return

        # Xử lý chữ cái qua bộ gõ Tiếng Việt Telex chuẩn PC
        if (
            self.vn_enabled
            and not has_non_shift_mod
            and len(norm) == 1
            and "a" <= norm <= "z"
        ):
            is_upper = (auto_shift or ("shift" in self.held_modifiers)) != self.caps_locked
            char_in = norm.upper() if is_upper else norm
            old_w, new_w = self.telex.process_char(char_in)

            # Tìm tiền tố chung dài nhất giữa từ cũ trên màn hình và từ mới sau khi ghép dấu
            common_len = 0
            max_common = min(len(old_w), len(new_w))
            while common_len < max_common and old_w[common_len] == new_w[common_len]:
                common_len += 1

            del_count = len(old_w) - common_len
            suffix = new_w[common_len:]

            # Nếu chỉ nối thêm đúng 1 ký tự ASCII không dấu ở cuối -> bắn mã phím vật lý cực nhanh
            if del_count == 0 and len(suffix) == 1 and suffix.isascii():
                self._send_raw_vk(norm, auto_shift)
                return

            if self._use_quartz:
                # Nếu đang đè Shift tay thì tạm nhả để Backspace và Unicode không bị kẹp Shift
                shift_was_held = "shift" in self.held_modifiers
                if shift_was_held:
                    self._quartz_post_vk(MAC_VK_MAP["shift"], False, override_mods=set())
                for _ in range(del_count):
                    self._quartz_post_vk(MAC_VK_MAP["backspace"], True, override_mods=set())
                    self._quartz_post_vk(MAC_VK_MAP["backspace"], False, override_mods=set())
                if del_count > 0:
                    time.sleep(0.003)
                self._quartz_post_unicode(suffix)
                if shift_was_held:
                    self._quartz_post_vk(
                        MAC_VK_MAP["shift"], True, override_mods=self.held_modifiers
                    )
                return

        # Mọi phím khác (Space, Enter, dấu câu, mũi tên, số...) -> reset bộ đệm từ Telex
        self.telex.reset()
        self._send_raw_vk(norm, auto_shift)

    def _send_raw_vk(self, norm: str, auto_shift: bool) -> None:
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
        self.last_activity_at = time.monotonic()
        self.telex.reset()
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
        self.telex.reset()
        if self._mouse_buttons_down:
            for btn in list(self._mouse_buttons_down):
                try:
                    self.mouse_up(btn)
                except Exception:
                    pass
            self._mouse_buttons_down.clear()
        if not self.held_modifiers:
            return
        stuck = list(self.held_modifiers)
        self.held_modifiers.clear()
        for m in stuck:
            try:
                self.key_up(m)
            except Exception:
                pass

    # -------------------- Mouse & Trackpad Control --------------------
    def get_current_mouse_pos(self) -> Tuple[float, float]:
        if self._use_quartz:
            try:
                q = self._quartz
                loc = q.CGEventGetLocation(q.CGEventCreate(None))
                return (float(loc.x), float(loc.y))
            except Exception:
                return (self._mouse_x, self._mouse_y)
        try:
            pos = self._pynput_mouse.position
            return (float(pos[0]), float(pos[1]))
        except Exception:
            return (self._mouse_x, self._mouse_y)

    def _sync_mouse_pos_if_needed(self) -> None:
        now = time.monotonic()
        if now - self._last_mouse_sync > 0.12:
            mx, my = self.get_current_mouse_pos()
            self._mouse_x = mx
            self._mouse_y = my
        self._last_mouse_sync = now

    def mouse_move(self, dx: float, dy: float) -> None:
        self.last_activity_at = time.monotonic()
        if not self._use_quartz:
            try:
                mx, my = self.get_current_mouse_pos()
                self._pynput_mouse.position = (int(round(mx + dx)), int(round(my + dy)))
                self._mouse_x, self._mouse_y = self.get_current_mouse_pos()
            except Exception:
                pass
            return
        q = self._quartz
        self._sync_mouse_pos_if_needed()
        # Hỗ trợ đa màn hình trên macOS (không kẹp cứng vào màn chính nếu có màn phụ)
        try:
            err, active_ids, count = q.CGGetActiveDisplayList(8, None, None)
            if err == 0 and count > 1:
                min_x = min(float(q.CGDisplayBounds(d).origin.x) for d in active_ids[:count])
                min_y = min(float(q.CGDisplayBounds(d).origin.y) for d in active_ids[:count])
                max_x = max(
                    float(q.CGDisplayBounds(d).origin.x + q.CGDisplayBounds(d).size.width)
                    for d in active_ids[:count]
                )
                max_y = max(
                    float(q.CGDisplayBounds(d).origin.y + q.CGDisplayBounds(d).size.height)
                    for d in active_ids[:count]
                )
            else:
                main_id = q.CGMainDisplayID()
                min_x, min_y = 0.0, 0.0
                max_x = float(q.CGDisplayPixelsWide(main_id))
                max_y = float(q.CGDisplayPixelsHigh(main_id))
        except Exception:
            main_id = q.CGMainDisplayID()
            min_x, min_y = 0.0, 0.0
            max_x = float(q.CGDisplayPixelsWide(main_id))
            max_y = float(q.CGDisplayPixelsHigh(main_id))

        self._mouse_x = max(min_x, min(max_x - 1.0, self._mouse_x + dx))
        self._mouse_y = max(min_y, min(max_y - 1.0, self._mouse_y + dy))

        if "left" in self._mouse_buttons_down:
            ev_type = q.kCGEventLeftMouseDragged
            btn = q.kCGMouseButtonLeft
        elif "right" in self._mouse_buttons_down:
            ev_type = q.kCGEventRightMouseDragged
            btn = q.kCGMouseButtonRight
        else:
            ev_type = q.kCGEventMouseMoved
            btn = q.kCGMouseButtonLeft

        ev = q.CGEventCreateMouseEvent(
            None, ev_type, (self._mouse_x, self._mouse_y), btn
        )
        q.CGEventSetIntegerValueField(ev, q.kCGMouseEventDeltaX, int(round(dx)))
        q.CGEventSetIntegerValueField(ev, q.kCGMouseEventDeltaY, int(round(dy)))
        q.CGEventPost(q.kCGHIDEventTap, ev)

    def mouse_down(self, button: str = "left") -> None:
        self.last_activity_at = time.monotonic()
        self.telex.reset()
        if not self._use_quartz:
            try:
                btn_obj = self._MouseButton.right if button == "right" else self._MouseButton.left
                self._mouse_buttons_down.add(button)
                self._pynput_mouse.press(btn_obj)
            except Exception:
                pass
            return
        q = self._quartz
        self._sync_mouse_pos_if_needed()
        self._mouse_buttons_down.add(button)

        if button == "right":
            ev_type = q.kCGEventRightMouseDown
            btn = q.kCGMouseButtonRight
            click_state = 1
        else:
            ev_type = q.kCGEventLeftMouseDown
            btn = q.kCGMouseButtonLeft
            now = time.monotonic()
            if now - self._last_left_click_at < 0.32:
                self._left_click_count += 1
            else:
                self._left_click_count = 1
            self._last_left_click_at = now
            click_state = self._left_click_count

        ev = q.CGEventCreateMouseEvent(
            None, ev_type, (self._mouse_x, self._mouse_y), btn
        )
        q.CGEventSetIntegerValueField(ev, q.kCGMouseEventClickState, click_state)
        q.CGEventPost(q.kCGHIDEventTap, ev)

    def mouse_up(self, button: str = "left") -> None:
        self.last_activity_at = time.monotonic()
        if not self._use_quartz:
            try:
                btn_obj = self._MouseButton.right if button == "right" else self._MouseButton.left
                self._mouse_buttons_down.discard(button)
                self._pynput_mouse.release(btn_obj)
            except Exception:
                pass
            return
        q = self._quartz
        self._sync_mouse_pos_if_needed()
        self._mouse_buttons_down.discard(button)

        if button == "right":
            ev_type = q.kCGEventRightMouseUp
            btn = q.kCGMouseButtonRight
            click_state = 1
        else:
            ev_type = q.kCGEventLeftMouseUp
            btn = q.kCGMouseButtonLeft
            click_state = max(1, self._left_click_count)

        ev = q.CGEventCreateMouseEvent(
            None, ev_type, (self._mouse_x, self._mouse_y), btn
        )
        q.CGEventSetIntegerValueField(ev, q.kCGMouseEventClickState, click_state)
        q.CGEventPost(q.kCGHIDEventTap, ev)

    def mouse_click(self, button: str = "left", count: int = 1) -> None:
        self.last_activity_at = time.monotonic()
        self.telex.reset()
        if not self._use_quartz:
            try:
                btn_obj = self._MouseButton.right if button == "right" else self._MouseButton.left
                self._pynput_mouse.click(btn_obj, max(1, count))
            except Exception:
                pass
            return
        q = self._quartz
        self._sync_mouse_pos_if_needed()
        if button == "right":
            down_type = q.kCGEventRightMouseDown
            up_type = q.kCGEventRightMouseUp
            btn = q.kCGMouseButtonRight
        else:
            down_type = q.kCGEventLeftMouseDown
            up_type = q.kCGEventLeftMouseUp
            btn = q.kCGMouseButtonLeft

        now = time.monotonic()
        if button == "left" and count == 1:
            if now - self._last_left_click_at < 0.32:
                self._left_click_count += 1
            else:
                self._left_click_count = 1
            self._last_left_click_at = now
            click_state = self._left_click_count
        else:
            click_state = max(1, count)

        ev_d = q.CGEventCreateMouseEvent(
            None, down_type, (self._mouse_x, self._mouse_y), btn
        )
        q.CGEventSetIntegerValueField(ev_d, q.kCGMouseEventClickState, click_state)
        q.CGEventPost(q.kCGHIDEventTap, ev_d)

        ev_u = q.CGEventCreateMouseEvent(
            None, up_type, (self._mouse_x, self._mouse_y), btn
        )
        q.CGEventSetIntegerValueField(ev_u, q.kCGMouseEventClickState, click_state)
        q.CGEventPost(q.kCGHIDEventTap, ev_u)

    def mouse_scroll(self, dx: float, dy: float) -> None:
        self.last_activity_at = time.monotonic()
        if not self._use_quartz:
            try:
                self._pynput_mouse.scroll(dx / 36.0, dy / 36.0)
            except Exception:
                pass
            return
        q = self._quartz
        ev = q.CGEventCreateScrollWheelEvent(
            None,
            q.kCGScrollEventUnitPixel,
            2,
            int(round(dy)),
            int(round(dx)),
        )
        q.CGEventPost(q.kCGHIDEventTap, ev)


class LiveLensCapturer:
    """
    Chụp trực tiếp vùng màn hình lấy con trỏ chuột trên Mac / PC làm trung tâm:
    - Trên macOS: dùng trực tiếp Quartz CGWindowListCreateImage (kCGWindowImageNominalResolution) + AppKit NSBitmapImageRep
      (tăng tốc phần cứng < 1ms, không cần cài thêm thư viện ngoài).
    - Trên Windows / Linux: dùng mss + Pillow.
    """

    def __init__(self, kb_injector: KeyboardInjector) -> None:
        self.inj = kb_injector
        self._quartz = None
        self._appkit = None
        self._mss_mod = None
        self._pil_image = None
        self._prev_mouse: Tuple[float, float] = (0.0, 0.0)

        if IS_MACOS:
            try:
                import AppKit  # type: ignore
                import Quartz  # type: ignore

                self._quartz = Quartz
                self._appkit = AppKit
            except Exception as exc:
                logger.warning("Không nạp được Quartz/AppKit cho Live Lens: %s", exc)

        if self._quartz is None:
            try:
                import mss  # type: ignore
                from PIL import Image  # type: ignore

                self._mss_mod = mss
                self._pil_image = Image
            except Exception as exc:
                logger.warning("Chưa cài mss/Pillow cho Live Lens (%s)", exc)

    @property
    def available(self) -> bool:
        return (self._quartz is not None and self._appkit is not None) or (
            self._mss_mod is not None and self._pil_image is not None
        )

    def _compute_crop_geometry(
        self,
        mx: float,
        my: float,
        mon_left: float,
        mon_top: float,
        mon_w: float,
        mon_h: float,
        aspect: float,
        fov_scale: float,
        mode: str,
    ) -> Tuple[int, int, int, int]:
        safe_aspect = max(1.05, min(16.0, float(aspect or 1.85)))
        safe_scale = max(0.55, min(1.85, float(fov_scale or 1.15)))

        if mode == "landscape":
            base_w = min(mon_w, max(700.0, mon_w * 0.62) * safe_scale)
            crop_w = int(round(base_w))
            crop_h = max(68, min(int(mon_h), int(round(crop_w / safe_aspect))))
        else:
            # Chế độ Windows dọc: lấy rộng ~68% bề ngang màn hình để chữ nhỏ vừa vặn, nhìn bao quát rộng quanh tâm chuột
            base_w = min(mon_w, max(860.0, mon_w * 0.68) * safe_scale)
            crop_w = int(round(base_w))
            crop_h = max(180, min(int(mon_h), int(round(crop_w / safe_aspect))))

        crop_w = max(240, min(int(mon_w), crop_w))
        crop_h = max(64, min(int(mon_h), crop_h))

        left = int(round(mx - crop_w / 2.0))
        top = int(round(my - crop_h / 2.0))

        min_l = int(round(mon_left))
        max_l = int(round(mon_left + mon_w - crop_w))
        min_t = int(round(mon_top))
        max_t = int(round(mon_top + mon_h - crop_h))

        left = max(min_l, min(max_l, left))
        top = max(min_t, min(max_t, top))
        return (left, top, crop_w, crop_h)

    def capture_packet(
        self, sct, aspect: float, fov_scale: float, mode: str
    ) -> Optional[bytes]:
        if not self.available:
            return None

        mx, my = self.inj.get_current_mouse_pos()
        if abs(mx - self._prev_mouse[0]) > 2.5 or abs(my - self._prev_mouse[1]) > 2.5:
            self._prev_mouse = (mx, my)
            self.inj.last_activity_at = time.monotonic()

        jpeg_bytes: Optional[bytes] = None
        left, top, crop_w, crop_h = 0, 0, 800, 400

        # 1. Đường dẫn phần cứng gốc trên macOS (Quartz + NSBitmapImageRep)
        if self._quartz is not None and self._appkit is not None:
            q = self._quartz
            ak = self._appkit
            mon_left, mon_top = 0.0, 0.0
            main_id = q.CGMainDisplayID()
            mon_w = float(q.CGDisplayPixelsWide(main_id))
            mon_h = float(q.CGDisplayPixelsHigh(main_id))
            try:
                err, active_ids, count = q.CGGetActiveDisplayList(8, None, None)
                if err == 0 and count > 0:
                    for did in active_ids[:count]:
                        b = q.CGDisplayBounds(did)
                        bx, by = float(b.origin.x), float(b.origin.y)
                        bw, bh = float(b.size.width), float(b.size.height)
                        if bx <= mx < bx + bw and by <= my < by + bh:
                            mon_left, mon_top, mon_w, mon_h = bx, by, bw, bh
                            break
            except Exception:
                pass

            left, top, crop_w, crop_h = self._compute_crop_geometry(
                mx, my, mon_left, mon_top, mon_w, mon_h, aspect, fov_scale, mode
            )
            rect = q.CGRectMake(float(left), float(top), float(crop_w), float(crop_h))
            nominal_flag = getattr(q, "kCGWindowImageNominalResolution", 16)
            cg_img = q.CGWindowListCreateImage(
                rect,
                q.kCGWindowListOptionOnScreenOnly,
                q.kCGNullWindowID,
                nominal_flag,
            )
            if cg_img is None:
                return None

            rep = ak.NSBitmapImageRep.alloc().initWithCGImage_(cg_img)
            if rep is None:
                return None
            jpeg_type = getattr(ak, "NSBitmapImageFileTypeJPEG", 4)
            comp_key = getattr(
                ak, "NSImageCompressionFactor", "NSImageCompressionFactor"
            )
            ns_data = rep.representationUsingType_properties_(
                jpeg_type, {comp_key: 0.66}
            )
            if ns_data is None:
                return None
            jpeg_bytes = bytes(ns_data)

        # 2. Đường dẫn đa nền tảng trên Windows / Linux (mss + Pillow)
        elif sct is not None and self._pil_image is not None:
            Image = self._pil_image
            monitors = sct.monitors
            chosen = monitors[1] if len(monitors) > 1 else monitors[0]
            for mon in monitors[1:]:
                if (
                    mon["left"] <= mx < mon["left"] + mon["width"]
                    and mon["top"] <= my < mon["top"] + mon["height"]
                ):
                    chosen = mon
                    break

            left, top, crop_w, crop_h = self._compute_crop_geometry(
                mx,
                my,
                float(chosen["left"]),
                float(chosen["top"]),
                float(chosen["width"]),
                float(chosen["height"]),
                aspect,
                fov_scale,
                mode,
            )
            raw = sct.grab(
                {"left": left, "top": top, "width": crop_w, "height": crop_h}
            )
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            target_w = 880 if mode == "landscape" else 840
            if img.width > target_w:
                out_h = max(48, int(round(img.height * (target_w / float(img.width)))))
                resample_attr = getattr(Image, "Resampling", Image).BILINEAR
                img = img.resize((target_w, out_h), resample_attr)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=68, optimize=False)
            jpeg_bytes = buf.getvalue()

        if not jpeg_bytes:
            return None

        rel_mx = max(0.0, min(1.0, (mx - left) / float(crop_w)))
        rel_my = max(0.0, min(1.0, (my - top) / float(crop_h)))
        u_mx = int(round(rel_mx * 10000))
        u_my = int(round(rel_my * 10000))

        header = struct.pack(">4sHHBHB", b"LENS", u_mx, u_my, 0, u_mx, 0)
        return header + jpeg_bytes


injector = KeyboardInjector()
lens_capturer = LiveLensCapturer(injector)
app = FastAPI(title="Mac Web Virtual Keyboard", docs_url=None, redoc_url=None)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/style.css")
async def style_css() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "style.css",
        media_type="text/css",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/app.js")
async def app_js() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "app.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/manifest.json")
async def manifest_json() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "manifest.json",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/apk")
async def download_apk() -> FileResponse:
    apk_path = BASE_DIR / "releases" / "app-release.apk"
    return FileResponse(
        apk_path,
        media_type="application/vnd.android.package-archive",
        filename="MacKeyboard-v1.1.0.apk",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "platform": sys.platform,
        "vn_enabled": injector.vn_enabled,
        "kb_layout": injector.kb_layout,
    }


@app.websocket("/ws")
async def keyboard_ws(ws: WebSocket) -> None:
    await ws.accept()
    client_host = ws.client.host if ws.client else "unknown"
    trusted = check_macos_accessibility(prompt=True)
    check_macos_screen_recording(prompt=True)
    if injector.vn_enabled:
        ensure_macos_abc_input_source()
    logger.info(
        "Đã kết nối điện thoại từ: %s (Accessibility=%s, Lens=%s, Layout=%s, VN=%s)",
        client_host,
        trusted,
        lens_capturer.available,
        injector.kb_layout,
        injector.vn_enabled,
    )
    warned_untrusted = not trusted
    await ws.send_text(
        json.dumps(
            {
                "type": "state",
                "vn": injector.vn_enabled,
                "layout": injector.kb_layout,
                "trusted": trusted,
                "lens": lens_capturer.available,
            }
        )
    )
    if IS_MACOS and not trusted:
        await ws.send_text('{"type":"error","reason":"accessibility_denied"}')

    lens_cfg = {
        "enabled": True,
        "aspect": 1.85,
        "scale": 1.15,
        "mode": "portrait",
        "running": True,
    }

    async def stream_lens_loop() -> None:
        if not lens_capturer.available:
            return
        sct = (
            lens_capturer._mss_mod.mss()
            if (lens_capturer._quartz is None and lens_capturer._mss_mod is not None)
            else None
        )
        try:
            while lens_cfg["running"]:
                if not lens_cfg["enabled"]:
                    await asyncio.sleep(0.25)
                    continue

                idle_sec = time.monotonic() - injector.last_activity_at
                interval = 0.045 if idle_sec < 2.5 else 0.24
                try:
                    packet = await asyncio.to_thread(
                        lens_capturer.capture_packet,
                        sct,
                        lens_cfg["aspect"],
                        lens_cfg["scale"],
                        lens_cfg["mode"],
                    )
                    if packet:
                        await ws.send_bytes(packet)
                except WebSocketDisconnect:
                    break
                except Exception as exc:
                    logger.debug("Lens frame skipped: %s", exc)
                    await asyncio.sleep(0.2)

                await asyncio.sleep(interval)
        finally:
            if sct is not None:
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
            elif msg_type == "mouse_move":
                dx = float(data.get("dx", 0.0))
                dy = float(data.get("dy", 0.0))
                injector.mouse_move(dx, dy)
            elif msg_type == "mouse_click":
                btn = str(data.get("button", "left"))
                cnt = int(data.get("count", 1))
                injector.mouse_click(btn, cnt)
            elif msg_type == "mouse_down":
                btn = str(data.get("button", "left"))
                injector.mouse_down(btn)
            elif msg_type == "mouse_up":
                btn = str(data.get("button", "left"))
                injector.mouse_up(btn)
            elif msg_type == "mouse_scroll":
                dx = float(data.get("dx", 0.0))
                dy = float(data.get("dy", 0.0))
                injector.mouse_scroll(dx, dy)
            elif msg_type == "config":
                if "vn" in data:
                    injector.vn_enabled = bool(data["vn"])
                    injector.telex.reset()
                    if injector.vn_enabled:
                        ensure_macos_abc_input_source()
                if "layout" in data and data["layout"] in ("win", "mac", "pad"):
                    injector.kb_layout = str(data["layout"])
                    injector.telex.reset()
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "state",
                            "vn": injector.vn_enabled,
                            "layout": injector.kb_layout,
                        }
                    )
                )
            elif msg_type == "lens_config":
                if "enabled" in data:
                    lens_cfg["enabled"] = bool(data["enabled"])
                if "aspect" in data:
                    lens_cfg["aspect"] = float(data["aspect"])
                if "scale" in data:
                    lens_cfg["scale"] = float(data["scale"])
                if "mode" in data:
                    lens_cfg["mode"] = str(data["mode"])
                injector.last_activity_at = time.monotonic()
            elif msg_type == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        logger.info("Điện thoại đã ngắt kết nối: %s", client_host)
    except Exception as exc:
        logger.error("Lỗi WebSocket (%s): %s", client_host, exc)
    finally:
        lens_cfg["running"] = False
        lens_task.cancel()
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


def check_macos_screen_recording(prompt: bool = True) -> bool:
    if not IS_MACOS:
        return True
    try:
        import Quartz  # type: ignore

        if hasattr(Quartz, "CGPreflightScreenCaptureAccess"):
            ok = bool(Quartz.CGPreflightScreenCaptureAccess())
            if not ok and prompt and hasattr(Quartz, "CGRequestScreenCaptureAccess"):
                Quartz.CGRequestScreenCaptureAccess()
            return ok
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


def start_notification_auto_dismisser(max_seconds: float = 4.0) -> None:
    """
    Tự động đóng mọi thông báo hệ thống cứng đầu (Pin yếu, Cài đặt hệ thống, Background Items...)
    nếu chúng treo ở góc màn hình quá `max_seconds` giây.
    """
    if not IS_MACOS:
        return

    def _worker() -> None:
        try:
            import ctypes
            import ctypes.util
            import AppKit  # type: ignore
            import Foundation  # type: ignore
            import objc  # type: ignore

            try:
                AppKit.NSApplication.sharedApplication().setActivationPolicy_(
                    AppKit.NSApplicationActivationPolicyProhibited
                )
            except Exception:
                pass

            app_services = ctypes.cdll.LoadLibrary(
                ctypes.util.find_library("ApplicationServices")
            )
            app_services.AXUIElementCreateApplication.restype = ctypes.c_void_p
            app_services.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
            app_services.AXUIElementCopyAttributeValue.restype = ctypes.c_int
            app_services.AXUIElementCopyAttributeValue.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            app_services.AXUIElementCopyActionNames.restype = ctypes.c_int
            app_services.AXUIElementCopyActionNames.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            app_services.AXUIElementPerformAction.restype = ctypes.c_int
            app_services.AXUIElementPerformAction.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]

            def ax_attr(elem_ptr: int, attr_name: str):
                out = ctypes.c_void_p()
                ns_str = Foundation.NSString.stringWithString_(attr_name)
                err = app_services.AXUIElementCopyAttributeValue(
                    elem_ptr, objc.pyobjc_id(ns_str), ctypes.byref(out)
                )
                if err == 0 and out.value:
                    return objc.objc_object(c_void_p=out.value)
                return None

            def ax_dismiss_recursive(elem_ptr: int, depth: int = 0) -> bool:
                if depth > 6 or not elem_ptr:
                    return False
                acts_out = ctypes.c_void_p()
                if (
                    app_services.AXUIElementCopyActionNames(
                        elem_ptr, ctypes.byref(acts_out)
                    )
                    == 0
                    and acts_out.value
                ):
                    acts = objc.objc_object(c_void_p=acts_out.value)
                    for a in acts:
                        a_str = str(a)
                        if any(
                            k in a_str
                            for k in ("Close", "Đóng", "Clear", "Xóa", "Cancel")
                        ):
                            ns_act = Foundation.NSString.stringWithString_(a_str)
                            app_services.AXUIElementPerformAction(
                                elem_ptr, objc.pyobjc_id(ns_act)
                            )
                            return True
                children = ax_attr(elem_ptr, "AXChildren")
                if children:
                    for ch in children:
                        if ax_dismiss_recursive(ch.__c_void_p__(), depth + 1):
                            return True
                return False

            visible_since: Optional[float] = None
            while True:
                time.sleep(1.2)
                nc_pid = None
                for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
                    if app.bundleIdentifier() == "com.apple.notificationcenterui":
                        nc_pid = int(app.processIdentifier())
                        break
                if not nc_pid:
                    visible_since = None
                    continue

                ax_app = app_services.AXUIElementCreateApplication(nc_pid)
                wins = ax_attr(ax_app, "AXWindows")
                if not wins or len(wins) == 0:
                    visible_since = None
                    continue

                now = time.monotonic()
                if visible_since is None:
                    visible_since = now
                elif now - visible_since >= max_seconds:
                    for w in wins:
                        ax_dismiss_recursive(w.__c_void_p__(), 0)
                    visible_since = None
        except Exception as exc:
            logger.debug("Notification auto-dismisser stopped: %s", exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


if __name__ == "__main__":
    check_macos_accessibility()
    start_notification_auto_dismisser(max_seconds=4.0)
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
