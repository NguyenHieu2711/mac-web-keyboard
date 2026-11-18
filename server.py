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
import ssl
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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

REMOTE_PC_APP_KEYWORDS = (
    "microsoft remote desktop",
    "windows app",
    "com.microsoft.rdc",
    "parallels",
    "vmware",
    "jump desktop",
    "anydesk",
    "teamviewer",
    "moonlight",
    "parsec",
    "royal tsx",
)
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
        self.preview_committed: str = ""
        self.last_badge: str = ""
        self._use_quartz = False
        self._quartz = None
        self._objc = None
        self._event_source = None
        self._mouse_x: float = 500.0
        self._mouse_y: float = 500.0
        self._last_mouse_sync: float = 0.0
        self._mouse_buttons_down: Set[str] = set()
        self._last_left_click_at: float = 0.0
        self._left_click_count: int = 0
        self._focused_cache_at: float = 0.0
        self._focused_is_remote: bool = False
        self._focused_app_name: str = ""
        self._ax_sys_wide = None
        self._ax_focused_attr = None
        self._ax_lib = None
        self._cf_lib = None
        self._proc_lib = None

        if IS_MACOS:
            try:
                import objc  # type: ignore
                import Quartz  # type: ignore

                self._objc = objc
                self._quartz = Quartz
                self._event_source = Quartz.CGEventSourceCreate(
                    Quartz.kCGEventSourceStateHIDSystemState
                )
                if self._event_source is not None and hasattr(
                    Quartz, "CGEventSourceSetUserData"
                ):
                    Quartz.CGEventSourceSetUserData(self._event_source, 0x4D4B4231)
                self._use_quartz = True
                ensure_macos_abc_input_source()
                self._init_macos_focus_detector()
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

    # -------------------- Nhận diện cửa sổ Remote PC (Microsoft Remote Desktop / Windows App) --------------------
    def _init_macos_focus_detector(self) -> None:
        if not IS_MACOS:
            return
        try:
            import ctypes
            import ctypes.util

            app_svc_path = ctypes.util.find_library("ApplicationServices")
            cf_path = ctypes.util.find_library("CoreFoundation")
            proc_path = ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib"
            if not app_svc_path or not cf_path:
                return

            app_svc = ctypes.cdll.LoadLibrary(app_svc_path)
            cf = ctypes.cdll.LoadLibrary(cf_path)
            proc = ctypes.cdll.LoadLibrary(proc_path)

            app_svc.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
            app_svc.AXUIElementCreateSystemWide.argtypes = []

            app_svc.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
            app_svc.AXUIElementCopyAttributeValue.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]

            app_svc.AXUIElementGetPid.restype = ctypes.c_int32
            app_svc.AXUIElementGetPid.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_int32),
            ]

            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFStringCreateWithCString.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_uint32,
            ]
            cf.CFRelease.restype = None
            cf.CFRelease.argtypes = [ctypes.c_void_p]

            proc.proc_pidpath.restype = ctypes.c_int32
            proc.proc_pidpath.argtypes = [
                ctypes.c_int32,
                ctypes.c_char_p,
                ctypes.c_uint32,
            ]

            self._ax_sys_wide = app_svc.AXUIElementCreateSystemWide()
            self._ax_focused_attr = cf.CFStringCreateWithCString(
                None, b"AXFocusedApplication", 0x08000100
            )
            self._ax_lib = app_svc
            self._cf_lib = cf
            self._proc_lib = proc
        except Exception as exc:
            logger.debug("Focus detector init fallback: %s", exc)

    def detect_focused_app_info(self, force: bool = False) -> Tuple[bool, str]:
        if not IS_MACOS:
            return (False, sys.platform)
        now = time.monotonic()
        if not force and (now - self._focused_cache_at) < 0.12:
            return (self._focused_is_remote, self._focused_app_name)

        app_label = ""
        try:
            if (
                self._ax_lib is not None
                and self._cf_lib is not None
                and self._proc_lib is not None
                and self._ax_sys_wide
                and self._ax_focused_attr
            ):
                import ctypes

                app_ref = ctypes.c_void_p()
                err = self._ax_lib.AXUIElementCopyAttributeValue(
                    self._ax_sys_wide, self._ax_focused_attr, ctypes.byref(app_ref)
                )
                if err == 0 and app_ref.value:
                    try:
                        pid = ctypes.c_int32(0)
                        if (
                            self._ax_lib.AXUIElementGetPid(
                                app_ref.value, ctypes.byref(pid)
                            )
                            == 0
                            and pid.value > 0
                        ):
                            buf = ctypes.create_string_buffer(4096)
                            n = self._proc_lib.proc_pidpath(pid.value, buf, 4096)
                            if n > 0:
                                app_label = buf.value.decode("utf-8", errors="ignore")
                    finally:
                        self._cf_lib.CFRelease(app_ref.value)
        except Exception:
            pass

        if not app_label and self._quartz is not None and self._objc is not None:
            try:
                q = self._quartz
                with self._objc.autorelease_pool():
                    win_list = q.CGWindowListCopyWindowInfo(
                        q.kCGWindowListOptionOnScreenOnly
                        | q.kCGWindowListExcludeDesktopElements,
                        q.kCGNullWindowID,
                    )
                    if win_list:
                        for w in win_list:
                            if int(w.get("kCGWindowLayer", -1)) == 0:
                                owner = str(w.get("kCGWindowOwnerName", "") or "")
                                if owner:
                                    app_label = owner
                                    break
            except Exception:
                pass

        lower_lbl = app_label.lower()
        is_remote = any(kw in lower_lbl for kw in REMOTE_PC_APP_KEYWORDS)
        self._focused_cache_at = now
        self._focused_is_remote = is_remote
        self._focused_app_name = app_label
        return (is_remote, app_label)

    def is_remote_pc_focused(self) -> bool:
        return self.detect_focused_app_info(force=False)[0]

    # -------------------- Quartz Native macOS Path --------------------
    def _compute_quartz_flags(self, extra_mods: Set[str] | None = None) -> int:
        q = self._quartz
        mods = set(self.held_modifiers)
        if extra_mods:
            mods.update(extra_mods)
        flags = 0
        # Bao gồm cả cờ mức cao (CGEventFlags) và cờ phần cứng thiết bị (NX_DEVICEL*KEYMASK trong IOLLEvent.h)
        # để WindowServer / SymbolicHotKeys (như Cmd+Shift+3, Cmd+Shift+4, Cmd+Space, Cmd+Tab) nhận diện 100% như bàn phím Mac thật.
        if "cmd" in mods:
            flags |= q.kCGEventFlagMaskCommand | 0x00000008
        if "shift" in mods:
            flags |= q.kCGEventFlagMaskShift | 0x00000002
        if "alt" in mods:
            flags |= q.kCGEventFlagMaskAlternate | 0x00000020
        if "ctrl" in mods:
            flags |= q.kCGEventFlagMaskControl | 0x00000001
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
            | 0x0000002B
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
                self._commit_telex_word_to_preview()
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
            if norm in ("cmd", "alt"):
                self._focused_cache_at = 0.0

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
        # Khi đang gõ trực tiếp trong Microsoft Remote Desktop / Windows App, giữ nguyên Ctrl gốc chuẩn Windows PC
        if self.is_remote_pc_focused():
            return False

        self._commit_telex_word_to_preview()
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
        active_set: Set[str] = set()
        for m in sorted(target_mods):
            if m in MAC_VK_MAP:
                active_set.add(m)
                self._quartz_post_vk(MAC_VK_MAP[m], True, override_mods=active_set)
        time.sleep(0.008)
        self._quartz_post_vk(vk, True, override_mods=target_mods)
        time.sleep(0.008)
        self._quartz_post_vk(vk, False, override_mods=target_mods)
        time.sleep(0.006)
        for m in reversed(sorted(target_mods)):
            if m in MAC_VK_MAP and m not in self.held_modifiers:
                active_set.discard(m)
                self._quartz_post_vk(MAC_VK_MAP[m], False, override_mods=active_set)
        if "ctrl" in self.held_modifiers:
            self._quartz_post_vk(
                MAC_VK_MAP["ctrl"], True, override_mods=self.held_modifiers
            )

    def get_live_preview_snapshot(self) -> dict:
        full_text = (self.preview_committed + self.telex.word)[-220:]
        # Giữ tối đa 4 dòng gần nhất để hiển thị thoáng sạch trên Trackpad
        lines = full_text.split("\n")
        if len(lines) > 4:
            full_text = "\n".join(lines[-4:])
        badge = self.last_badge
        self.last_badge = ""
        return {"type": "typed_preview", "text": full_text, "badge": badge}

    def clear_live_preview(self) -> None:
        self.preview_committed = ""
        self.telex.reset()
        self.last_badge = ""

    def _commit_telex_word_to_preview(self) -> None:
        if self.telex.word:
            self.preview_committed = (self.preview_committed + self.telex.word)[-260:]

    def press_key(
        self, raw_key: str, transient_mods: Optional[List[str]] = None
    ) -> None:
        self.last_activity_at = time.monotonic()
        added_mods: List[str] = []
        if transient_mods:
            for tm in transient_mods:
                m_norm, _ = self.normalize_key(str(tm))
                if (
                    m_norm in ("cmd", "shift", "alt", "ctrl")
                    and m_norm not in self.held_modifiers
                ):
                    added_mods.append(m_norm)
                    self.key_down(m_norm)
            if added_mods:
                time.sleep(0.006)
        try:
            self._press_key_inner(raw_key)
        finally:
            if added_mods:
                time.sleep(0.006)
                for m_norm in reversed(added_mods):
                    self.key_up(m_norm)

    def _press_key_inner(self, raw_key: str) -> None:
        norm, auto_shift = self.normalize_key(raw_key)
        if not norm:
            return

        if norm == "capslock":
            self.caps_locked = not self.caps_locked
            self._commit_telex_word_to_preview()
            self.telex.reset()
            self.last_badge = "CAPS" if self.caps_locked else "caps"

        # Kiểm tra ánh xạ phím tắt Ctrl chuẩn PC nếu đang ở giao diện Bàn phím dây Windows
        if self._handle_win_layout_shortcut(norm):
            self.last_badge = f"Ctrl+{norm.upper()}"
            if norm in ("backspace", "del", "delete"):
                self.preview_committed = self.preview_committed.rstrip(" ")
                idx = max(self.preview_committed.rfind(" "), self.preview_committed.rfind("\n"))
                self.preview_committed = self.preview_committed[: idx + 1] if idx >= 0 else ""
            return

        has_non_shift_mod = any(
            m in self.held_modifiers for m in ("cmd", "alt", "ctrl")
        )

        # Xử lý Backspace với bộ đệm Telex & bộ đệm hiển thị chữ đơn giản
        if norm == "backspace" and not has_non_shift_mod:
            if self.telex.word:
                self.telex.backspace()
            elif self.preview_committed:
                self.preview_committed = self.preview_committed[:-1]
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

            # Đồng nhất bộ gõ VN giữa Mac và Microsoft Remote Desktop / Windows App:
            # Khi cửa sổ đang active là Remote PC, truyền thẳng mã phím phần cứng nguyên bản (như ENG)
            # để UniKey/EVKey trên Windows PC ghép dấu mượt 100%, không bị xung đột hay nuốt chữ Unicode.
            if self.is_remote_pc_focused():
                self._send_raw_vk(norm, auto_shift)
                return

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

        # Mọi phím khác (Space, Enter, dấu câu, mũi tên, số...) -> chốt từ hiện tại vào bộ đệm hiển thị rồi reset Telex
        self._commit_telex_word_to_preview()
        self.telex.reset()

        if has_non_shift_mod:
            mod_prefix = "+".join(sorted(m.capitalize() for m in self.held_modifiers))
            self.last_badge = f"{mod_prefix}+{norm.upper()}"
        elif norm == "space":
            self.preview_committed = (self.preview_committed + " ")[-260:]
        elif norm in ("enter", "return"):
            if "shift" in self.held_modifiers:
                self.preview_committed = (self.preview_committed + "\n")[-260:]
            else:
                # Ấn Enter gửi chữ đi -> xóa sạch khung chữ nháp trên Trackpad
                self.preview_committed = ""
        elif norm == "tab":
            self.preview_committed = (self.preview_committed + "  ")[-260:]
        elif len(raw_key) == 1 and not has_non_shift_mod:
            is_shifted = auto_shift or ("shift" in self.held_modifiers)
            ch_out = raw_key
            if "a" <= norm <= "z":
                upper_en = is_shifted != self.caps_locked
                ch_out = norm.upper() if upper_en else norm
            self.preview_committed = (self.preview_committed + ch_out)[-260:]
        elif norm in ("up", "down", "left", "right", "esc", "del", "delete"):
            self.last_badge = norm.upper()

        self._send_raw_vk(norm, auto_shift)

    def _send_raw_vk(self, norm: str, auto_shift: bool) -> None:
        extra_mods: Set[str] = {"shift"} if auto_shift else set()

        if self._use_quartz and norm in MAC_VK_MAP:
            vk = MAC_VK_MAP[norm]
            need_temp_shift = auto_shift and "shift" not in self.held_modifiers
            has_any_mod = bool(self.held_modifiers or need_temp_shift)
            if need_temp_shift:
                self._quartz_post_vk(MAC_VK_MAP["shift"], True, extra_mods)
                time.sleep(0.004)
            self._quartz_post_vk(vk, True, extra_mods)
            if has_any_mod:
                time.sleep(0.008)
            self._quartz_post_vk(vk, False, extra_mods)
            if need_temp_shift:
                time.sleep(0.004)
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
        self._commit_telex_word_to_preview()
        self.telex.reset()
        lower_keys = [k.strip().lower() for k in keys]
        if "backspace" in lower_keys and ("cmd" in lower_keys or "ctrl" in lower_keys):
            last_nl = self.preview_committed.rfind("\n")
            self.preview_committed = self.preview_committed[: last_nl + 1] if last_nl >= 0 else ""
            self.last_badge = "⌘⌫"
        else:
            self.last_badge = "+".join(k.upper() for k in keys)
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
                mb = q.CGDisplayBounds(main_id)
                min_x, min_y = float(mb.origin.x), float(mb.origin.y)
                max_x = min_x + float(mb.size.width)
                max_y = min_y + float(mb.size.height)
        except Exception:
            main_id = q.CGMainDisplayID()
            min_x, min_y = 0.0, 0.0
            max_x = float(q.CGDisplayPixelsWide(main_id))
            max_y = float(q.CGDisplayPixelsHigh(main_id))

        self._mouse_x = max(min_x, min(max_x - 1.0, self._mouse_x + dx))
        self._mouse_y = max(min_y, min(max_y - 1.0, self._mouse_y + dy))

        is_drag = False
        if "left" in self._mouse_buttons_down:
            ev_type = q.kCGEventLeftMouseDragged
            btn = q.kCGMouseButtonLeft
            is_drag = True
        elif "right" in self._mouse_buttons_down:
            ev_type = q.kCGEventRightMouseDragged
            btn = q.kCGMouseButtonRight
            is_drag = True
        else:
            ev_type = q.kCGEventMouseMoved
            btn = q.kCGMouseButtonLeft

        ev = q.CGEventCreateMouseEvent(
            self._event_source, ev_type, (self._mouse_x, self._mouse_y), btn
        )
        if self.held_modifiers:
            q.CGEventSetFlags(ev, self._compute_quartz_flags())
        if is_drag:
            q.CGEventSetIntegerValueField(ev, q.kCGMouseEventClickState, 1)
        q.CGEventSetIntegerValueField(ev, q.kCGMouseEventDeltaX, int(round(dx)))
        q.CGEventSetIntegerValueField(ev, q.kCGMouseEventDeltaY, int(round(dy)))
        q.CGEventPost(q.kCGHIDEventTap, ev)

    def mouse_down(self, button: str = "left", is_drag_start: bool = False) -> None:
        self.last_activity_at = time.monotonic()
        self._focused_cache_at = 0.0
        self._commit_telex_word_to_preview()
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
            if is_drag_start:
                self._left_click_count = 1
            elif now - self._last_left_click_at < 0.32:
                self._left_click_count += 1
            else:
                self._left_click_count = 1
            self._last_left_click_at = now
            click_state = self._left_click_count

        ev = q.CGEventCreateMouseEvent(
            self._event_source, ev_type, (self._mouse_x, self._mouse_y), btn
        )
        if self.held_modifiers:
            q.CGEventSetFlags(ev, self._compute_quartz_flags())
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
            self._event_source, ev_type, (self._mouse_x, self._mouse_y), btn
        )
        if self.held_modifiers:
            q.CGEventSetFlags(ev, self._compute_quartz_flags())
        q.CGEventSetIntegerValueField(ev, q.kCGMouseEventClickState, click_state)
        q.CGEventPost(q.kCGHIDEventTap, ev)

    def mouse_click(self, button: str = "left", count: int = 1) -> None:
        self.last_activity_at = time.monotonic()
        self._focused_cache_at = 0.0
        self._commit_telex_word_to_preview()
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
            self._event_source, down_type, (self._mouse_x, self._mouse_y), btn
        )
        if self.held_modifiers:
            q.CGEventSetFlags(ev_d, self._compute_quartz_flags())
        q.CGEventSetIntegerValueField(ev_d, q.kCGMouseEventClickState, click_state)
        q.CGEventPost(q.kCGHIDEventTap, ev_d)

        ev_u = q.CGEventCreateMouseEvent(
            self._event_source, up_type, (self._mouse_x, self._mouse_y), btn
        )
        if self.held_modifiers:
            q.CGEventSetFlags(ev_u, self._compute_quartz_flags())
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
        iy = int(round(dy))
        ix = int(round(dx))
        if iy == 0 and ix == 0:
            return
        ev = q.CGEventCreateScrollWheelEvent(
            self._event_source,
            q.kCGScrollEventUnitPixel,
            2,
            iy,
            ix,
        )
        # kCGScrollWheelEventIsContinuous = 88: đánh dấu cuộn mượt từng pixel chuẩn Trackpad (tắt nhảy nấc 3 dòng của chuột cơ)
        q.CGEventSetIntegerValueField(ev, 88, 1)
        if self.held_modifiers:
            q.CGEventSetFlags(ev, self._compute_quartz_flags())
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
        self._foundation = None
        self._objc = None
        self._mss_mod = None
        self._pil_image = None
        self._prev_mouse: Tuple[float, float] = (0.0, 0.0)

        if IS_MACOS:
            try:
                import Foundation  # type: ignore
                import objc  # type: ignore
                import Quartz  # type: ignore

                self._quartz = Quartz
                self._foundation = Foundation
                self._objc = objc
            except Exception as exc:
                logger.warning("Không nạp được Quartz/Foundation cho Live Lens: %s", exc)

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
        return (
            self._quartz is not None
            and self._foundation is not None
            and self._objc is not None
        ) or (self._mss_mod is not None and self._pil_image is not None)

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
        safe_aspect = max(0.55, min(16.0, float(aspect or 1.85)))
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

        # 1. Đường dẫn phần cứng gốc trên macOS (Quartz + ImageIO CGImageDestination + autorelease_pool)
        if (
            self._quartz is not None
            and self._foundation is not None
            and self._objc is not None
        ):
            q = self._quartz
            fd = self._foundation
            with self._objc.autorelease_pool():
                mon_left, mon_top = 0.0, 0.0
                main_id = q.CGMainDisplayID()
                try:
                    mb = q.CGDisplayBounds(main_id)
                    mon_left, mon_top = float(mb.origin.x), float(mb.origin.y)
                    mon_w, mon_h = float(mb.size.width), float(mb.size.height)
                except Exception:
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

                mutable_data = fd.NSMutableData.data()
                dest = q.CGImageDestinationCreateWithData(
                    mutable_data, "public.jpeg", 1, None
                )
                if dest is None:
                    return None
                qual_key = getattr(
                    q,
                    "kCGImageDestinationLossyCompressionQuality",
                    "kCGImageDestinationLossyCompressionQuality",
                )
                q.CGImageDestinationAddImage(dest, cg_img, {qual_key: 0.68})
                if not q.CGImageDestinationFinalize(dest):
                    return None
                jpeg_bytes = bytes(mutable_data)

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


class MacKvmBridge:
    """
    Cầu nối chuột Bluetooth xuyên màn hình (Universal Control / KVM) giữa MacBook và tab Remote PC trên điện thoại:
    - Chỉ kích hoạt khi điện thoại đang mở tab `remote` (kvm_enabled = True).
    - Khi đẩy chuột vượt qua mép màn hình MacBook (mọi phía hoặc mép chọn), khóa & giấu con trỏ trên Mac
      (CGAssociateMouseAndMouseCursorPosition(False) + nuốt sự kiện chuột trên Mac) và truyền thẳng sang điện thoại.
    - Khi đẩy chuột ngược qua mép đối diện trên điện thoại (hoặc bấm Ctrl+Option+Cmd trên Mac / thoát tab Remote),
      nhả con trỏ về lại đúng vị trí mép tương ứng trên MacBook.
    """

    OPPOSITE_EDGE = {
        "bottom": "top",
        "top": "bottom",
        "right": "left",
        "left": "right",
    }

    def __init__(self) -> None:
        self.available: bool = False
        self.captured: bool = False
        self._kvm_enabled: bool = False
        self._edge_mode: str = "any"
        self._active_ws: Optional[WebSocket] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._send_queue: Optional[asyncio.Queue] = None
        self._mac_exit_edge: str = "bottom"
        self._saved_pos: Tuple[float, float] = (600.0, 400.0)
        self._edge_push: float = 0.0
        self._push_dir: str = ""
        self._last_return_at: float = 0.0
        self._bounds_cache: Tuple[float, float, float, float] = (0.0, 0.0, 1440.0, 900.0)
        self._bounds_at: float = 0.0
        self._quartz: Any = None
        self._tap: Any = None
        self._lock = threading.Lock()

        if IS_MACOS:
            self._start_tap_thread()

    def _get_desktop_bounds(self) -> Tuple[float, float, float, float]:
        now = time.monotonic()
        if now - self._bounds_at < 1.5:
            return self._bounds_cache
        self._bounds_at = now
        q = self._quartz
        if q is None:
            return self._bounds_cache
        try:
            err, active_ids, count = q.CGGetActiveDisplayList(8, None, None)
            if err == 0 and count > 0:
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
                self._bounds_cache = (min_x, min_y, max_x, max_y)
        except Exception:
            pass
        return self._bounds_cache

    def _enqueue_payload(self, payload: dict) -> None:
        loop = self._loop
        q_obj = self._send_queue
        if loop is None or q_obj is None:
            return
        try:
            msg_str = json.dumps(payload)
            loop.call_soon_threadsafe(q_obj.put_nowait, msg_str)
        except Exception:
            pass

    def attach_client(
        self,
        ws: WebSocket,
        loop: asyncio.AbstractEventLoop,
        send_queue: asyncio.Queue,
        enabled: bool,
        edge_mode: str = "any",
    ) -> None:
        with self._lock:
            self._active_ws = ws
            self._loop = loop
            self._send_queue = send_queue
            self._kvm_enabled = bool(enabled)
            if edge_mode in ("any", "bottom", "right", "left", "top"):
                self._edge_mode = edge_mode
            if not self._kvm_enabled and self.captured:
                self._release_mac_cursor_locked(None, None)

    def detach_client(self, ws: WebSocket) -> None:
        with self._lock:
            if self._active_ws is ws:
                self._kvm_enabled = False
                self._active_ws = None
                self._loop = None
                self._send_queue = None
                if self.captured:
                    self._release_mac_cursor_locked(None, None)

    def _enter_phone_locked(
        self,
        mac_edge: str,
        ratio: float,
        min_x: float,
        min_y: float,
        max_x: float,
        max_y: float,
        cur_x: float,
        cur_y: float,
    ) -> None:
        q = self._quartz
        if q is None or self.captured:
            return
        self._saved_pos = (cur_x, cur_y)
        self._mac_exit_edge = mac_edge
        self._edge_push = 0.0
        self._push_dir = ""
        self.captured = True
        try:
            src = q.CGEventSourceCreate(q.kCGEventSourceStateCombinedSessionState)
            if src is not None and hasattr(q, "CGEventSourceSetLocalEventsSuppressionInterval"):
                q.CGEventSourceSetLocalEventsSuppressionInterval(src, 0.0)
            q.CGWarpMouseCursorPosition((max_x - 1.0, max_y - 1.0))
            q.CGAssociateMouseAndMouseCursorPosition(False)
        except Exception as exc:
            logger.debug("KVM warp/disassociate error: %s", exc)
        phone_edge = self.OPPOSITE_EDGE.get(mac_edge, "top")
        self._enqueue_payload(
            {
                "type": "kvm_enter",
                "mac_edge": mac_edge,
                "phone_edge": phone_edge,
                "ratio": round(ratio, 4),
            }
        )

    def _release_mac_cursor_locked(
        self, mac_edge: Optional[str], ratio: Optional[float]
    ) -> None:
        q = self._quartz
        was_captured = self.captured
        self.captured = False
        self._edge_push = 0.0
        self._push_dir = ""
        self._last_return_at = time.monotonic()
        if q is None:
            return
        try:
            min_x, min_y, max_x, max_y = self._get_desktop_bounds()
            w = max(1.0, max_x - min_x)
            h = max(1.0, max_y - min_y)
            edge = mac_edge if mac_edge in ("bottom", "top", "left", "right") else self._mac_exit_edge
            r = max(0.02, min(0.98, float(ratio))) if ratio is not None else None
            if r is not None:
                if edge == "bottom":
                    rx, ry = min_x + r * w, max_y - 6.0
                elif edge == "top":
                    rx, ry = min_x + r * w, min_y + 6.0
                elif edge == "right":
                    rx, ry = max_x - 6.0, min_y + r * h
                else:
                    rx, ry = min_x + 6.0, min_y + r * h
            else:
                rx, ry = self._saved_pos
                rx = max(min_x + 8.0, min(max_x - 8.0, rx))
                ry = max(min_y + 8.0, min(max_y - 8.0, ry))

            q.CGAssociateMouseAndMouseCursorPosition(True)
            src = q.CGEventSourceCreate(q.kCGEventSourceStateCombinedSessionState)
            if src is not None and hasattr(q, "CGEventSourceSetLocalEventsSuppressionInterval"):
                q.CGEventSourceSetLocalEventsSuppressionInterval(src, 0.0)
            q.CGWarpMouseCursorPosition((rx, ry))
        except Exception as exc:
            logger.debug("KVM release error: %s", exc)
        if was_captured:
            self._enqueue_payload({"type": "kvm_released"})

    def release_to_mac(
        self, mac_edge: Optional[str] = None, ratio: Optional[float] = None
    ) -> None:
        with self._lock:
            self._release_mac_cursor_locked(mac_edge, ratio)

    def _start_tap_thread(self) -> None:
        def _runner() -> None:
            try:
                import Quartz  # type: ignore

                self._quartz = Quartz
                q = Quartz

                def _cb(proxy, event_type, event, refcon):
                    try:
                        if event_type in (
                            q.kCGEventTapDisabledByTimeout,
                            q.kCGEventTapDisabledByUserInput,
                        ):
                            if self._tap is not None:
                                q.CGEventTapEnable(self._tap, True)
                            return event

                        if event_type == q.kCGEventFlagsChanged:
                            if self.captured:
                                flags = int(q.CGEventGetFlags(event))
                                req = (
                                    int(q.kCGEventFlagMaskControl)
                                    | int(q.kCGEventFlagMaskAlternate)
                                    | int(q.kCGEventFlagMaskCommand)
                                )
                                if (flags & req) == req:
                                    self.release_to_mac()
                            return event

                        if not self._kvm_enabled or self._active_ws is None:
                            if self.captured:
                                self.release_to_mac()
                            return event

                        user_tag = int(
                            q.CGEventGetIntegerValueField(event, q.kCGEventSourceUserData)
                        )
                        if user_tag == 0x4D4B4231:
                            return event

                        dx = float(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaX))
                        dy = float(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaY))

                        if not self.captured:
                            if event_type not in (
                                q.kCGEventMouseMoved,
                                q.kCGEventLeftMouseDragged,
                            ):
                                return event
                            if time.monotonic() - self._last_return_at < 0.18:
                                return event

                            loc = q.CGEventGetLocation(event)
                            lx, ly = float(loc.x), float(loc.y)
                            min_x, min_y, max_x, max_y = self._get_desktop_bounds()
                            w = max(1.0, max_x - min_x)
                            h = max(1.0, max_y - min_y)

                            mode = self._edge_mode
                            allowed = (
                                ("bottom", "right", "left", "top")
                                if mode == "any"
                                else (mode,)
                            )

                            cand = ""
                            push = 0.0
                            ratio = 0.5
                            if "bottom" in allowed and ly >= max_y - 2.5 and dy > 0:
                                cand = "bottom"
                                push = dy
                                ratio = (lx - min_x) / w
                            elif "top" in allowed and ly <= min_y + 2.0 and dy < 0:
                                cand = "top"
                                push = -dy
                                ratio = (lx - min_x) / w
                            elif "right" in allowed and lx >= max_x - 2.5 and dx > 0:
                                cand = "right"
                                push = dx
                                ratio = (ly - min_y) / h
                            elif "left" in allowed and lx <= min_x + 2.0 and dx < 0:
                                cand = "left"
                                push = -dx
                                ratio = (ly - min_y) / h

                            if cand:
                                with self._lock:
                                    if self._push_dir == cand:
                                        self._edge_push += push
                                    else:
                                        self._push_dir = cand
                                        self._edge_push = push
                                    if self._edge_push >= 24.0:
                                        self._enter_phone_locked(
                                            cand,
                                            max(0.02, min(0.98, ratio)),
                                            min_x,
                                            min_y,
                                            max_x,
                                            max_y,
                                            lx,
                                            ly,
                                        )
                                        return None
                            elif (
                                min_x + 6.0 < lx < max_x - 6.0
                                and min_y + 6.0 < ly < max_y - 6.0
                            ):
                                self._edge_push = 0.0
                                self._push_dir = ""
                            return event

                        # Đang ở trên màn Remote PC của điện thoại -> nuốt sự kiện Mac & đẩy sang điện thoại
                        if event_type in (
                            q.kCGEventMouseMoved,
                            q.kCGEventLeftMouseDragged,
                            q.kCGEventRightMouseDragged,
                            q.kCGEventOtherMouseDragged,
                        ):
                            if dx != 0.0 or dy != 0.0:
                                self._enqueue_payload(
                                    {
                                        "type": "kvm_mouse",
                                        "ev": "move",
                                        "dx": dx,
                                        "dy": dy,
                                    }
                                )
                            return None

                        if event_type == q.kCGEventLeftMouseDown:
                            self._enqueue_payload({"type": "kvm_mouse", "ev": "down", "btn": 0})
                            return None
                        if event_type == q.kCGEventLeftMouseUp:
                            self._enqueue_payload({"type": "kvm_mouse", "ev": "up", "btn": 0})
                            return None
                        if event_type == q.kCGEventRightMouseDown:
                            self._enqueue_payload({"type": "kvm_mouse", "ev": "down", "btn": 2})
                            return None
                        if event_type == q.kCGEventRightMouseUp:
                            self._enqueue_payload({"type": "kvm_mouse", "ev": "up", "btn": 2})
                            return None
                        if event_type == q.kCGEventOtherMouseDown:
                            self._enqueue_payload({"type": "kvm_mouse", "ev": "down", "btn": 1})
                            return None
                        if event_type == q.kCGEventOtherMouseUp:
                            self._enqueue_payload({"type": "kvm_mouse", "ev": "up", "btn": 1})
                            return None

                        if event_type == q.kCGEventScrollWheel:
                            is_cont = int(
                                q.CGEventGetIntegerValueField(
                                    event, q.kCGScrollWheelEventIsContinuous
                                )
                            )
                            if is_cont != 0:
                                sy = int(
                                    q.CGEventGetIntegerValueField(
                                        event, q.kCGScrollWheelEventPointDeltaAxis1
                                    )
                                )
                                sx = int(
                                    q.CGEventGetIntegerValueField(
                                        event, q.kCGScrollWheelEventPointDeltaAxis2
                                    )
                                )
                                if sx != 0 or sy != 0:
                                    self._enqueue_payload(
                                        {
                                            "type": "kvm_mouse",
                                            "ev": "wheel",
                                            "unit": "px",
                                            "sx": sx,
                                            "sy": sy,
                                        }
                                    )
                            else:
                                sy = int(
                                    q.CGEventGetIntegerValueField(
                                        event, q.kCGScrollWheelEventDeltaAxis1
                                    )
                                )
                                sx = int(
                                    q.CGEventGetIntegerValueField(
                                        event, q.kCGScrollWheelEventDeltaAxis2
                                    )
                                )
                                if sx != 0 or sy != 0:
                                    self._enqueue_payload(
                                        {
                                            "type": "kvm_mouse",
                                            "ev": "wheel",
                                            "unit": "line",
                                            "sx": sx,
                                            "sy": sy,
                                        }
                                    )
                            return None

                        return event
                    except Exception:
                        return event

                mask = (
                    (1 << int(q.kCGEventMouseMoved))
                    | (1 << int(q.kCGEventLeftMouseDown))
                    | (1 << int(q.kCGEventLeftMouseUp))
                    | (1 << int(q.kCGEventLeftMouseDragged))
                    | (1 << int(q.kCGEventRightMouseDown))
                    | (1 << int(q.kCGEventRightMouseUp))
                    | (1 << int(q.kCGEventRightMouseDragged))
                    | (1 << int(q.kCGEventOtherMouseDown))
                    | (1 << int(q.kCGEventOtherMouseUp))
                    | (1 << int(q.kCGEventOtherMouseDragged))
                    | (1 << int(q.kCGEventScrollWheel))
                    | (1 << int(q.kCGEventFlagsChanged))
                )

                tap = q.CGEventTapCreate(
                    q.kCGHIDEventTap,
                    q.kCGHeadInsertEventTap,
                    q.kCGEventTapOptionDefault,
                    mask,
                    _cb,
                    None,
                )
                if tap is None:
                    logger.warning("KVM CGEventTapCreate trả về None (kiểm tra quyền Accessibility).")
                    return

                self._tap = tap
                self.available = True
                run_loop_src = q.CFMachPortCreateRunLoopSource(None, tap, 0)
                loop_ref = q.CFRunLoopGetCurrent()
                q.CFRunLoopAddSource(loop_ref, run_loop_src, q.kCFRunLoopCommonModes)
                q.CGEventTapEnable(tap, True)
                logger.info("Đã kích hoạt MacKvmBridge (Chuột Bluetooth xuyên màn hình Mac <-> Điện thoại).")
                q.CFRunLoopRun()
            except Exception as exc:
                logger.warning("Không thể khởi tạo MacKvmBridge: %s", exc)

        t = threading.Thread(target=_runner, daemon=True)
        t.start()


# ============================================================================
# RDCLEANPATH ASN.1 DER PROXY (CHO IRONRDP WASM REMOTE PC TRÊN MẠNG LAN)
# ============================================================================
_RDCLEANPATH_VERSION_1 = 3390


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    out = bytearray()
    tmp = n
    while tmp > 0:
        out.insert(0, tmp & 0xFF)
        tmp >>= 8
    return bytes([0x80 | len(out)]) + bytes(out)


def _der_wrap(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(content)) + content


def _der_int(val: int) -> bytes:
    if val == 0:
        return _der_wrap(0x02, b"\x00")
    out = bytearray()
    tmp = val
    while tmp > 0:
        out.insert(0, tmp & 0xFF)
        tmp >>= 8
    if out[0] & 0x80:
        out.insert(0, 0)
    return _der_wrap(0x02, bytes(out))


def _der_read_tlv(buf: bytes, offset: int) -> Tuple[int, bytes, int]:
    tag = buf[offset]
    first = buf[offset + 1]
    if first < 0x80:
        length = first
        hlen = 2
    else:
        nbytes = first & 0x7F
        length = int.from_bytes(buf[offset + 2 : offset + 2 + nbytes], "big")
        hlen = 2 + nbytes
    val = buf[offset + hlen : offset + hlen + length]
    return tag, val, hlen + length


def _parse_rdcleanpath_req(data: bytes) -> Tuple[str, bytes]:
    outer_tag, outer_val, _ = _der_read_tlv(data, 0)
    if outer_tag != 0x30:
        raise ValueError("Invalid RDCleanPath outer tag")
    off = 0
    ver = None
    dest = ""
    x224 = b""
    while off < len(outer_val):
        ctag, cval, clen = _der_read_tlv(outer_val, off)
        off += clen
        idx = ctag & 0x1F
        if idx == 0:
            _, iv, _ = _der_read_tlv(cval, 0)
            ver = int.from_bytes(iv, "big")
        elif idx == 2:
            _, sv, _ = _der_read_tlv(cval, 0)
            dest = sv.decode("utf-8", errors="replace")
        elif idx == 6:
            _, ov, _ = _der_read_tlv(cval, 0)
            x224 = bytes(ov)
    if ver != _RDCLEANPATH_VERSION_1 or not dest or not x224:
        raise ValueError("Incomplete RDCleanPath request")
    return dest, x224


def _build_rdcleanpath_resp(server_addr: str, x224_resp: bytes, certs: List[bytes]) -> bytes:
    cert_seq = _der_wrap(0x30, b"".join(_der_wrap(0x04, c) for c in certs))
    parts = (
        _der_wrap(0xA0, _der_int(_RDCLEANPATH_VERSION_1))
        + _der_wrap(0xA6, _der_wrap(0x04, x224_resp))
        + _der_wrap(0xA7, cert_seq)
        + _der_wrap(0xA9, _der_wrap(0x0C, server_addr.encode("utf-8")))
    )
    return _der_wrap(0x30, parts)


def _build_rdcleanpath_err(code: int = 1, http_status: int = 502) -> bytes:
    err_seq = _der_wrap(
        0x30,
        _der_wrap(0xA0, _der_int(code)) + _der_wrap(0xA1, _der_int(http_status)),
    )
    return _der_wrap(
        0x30,
        _der_wrap(0xA0, _der_int(_RDCLEANPATH_VERSION_1)) + _der_wrap(0xA1, err_seq),
    )


def _tcp_x224_exchange(host: str, port: int, x224_req: bytes) -> Tuple[socket.socket, bytes]:
    raw_sock = socket.create_connection((host, port), timeout=10.0)
    try:
        raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        raw_sock.sendall(x224_req)
        hdr = bytearray()
        while len(hdr) < 4:
            chunk = raw_sock.recv(4 - len(hdr))
            if not chunk:
                raise ConnectionError("RDP closed during X.224 header")
            hdr.extend(chunk)
        if hdr[0] == 0x03 and hdr[1] == 0x00:
            expected = (hdr[2] << 8) | hdr[3]
            while len(hdr) < expected:
                chunk = raw_sock.recv(expected - len(hdr))
                if not chunk:
                    raise ConnectionError("RDP closed during X.224 body")
                hdr.extend(chunk)
        raw_sock.settimeout(None)
        raw_sock.setblocking(False)
        return raw_sock, bytes(hdr)
    except Exception:
        try:
            raw_sock.close()
        except Exception:
            pass
        raise


injector = KeyboardInjector()
lens_capturer = LiveLensCapturer(injector)
kvm_bridge = MacKvmBridge()
app = FastAPI(title="Mac Web Virtual Keyboard", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/ironrdp/{filename}")
async def ironrdp_asset(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    target = STATIC_DIR / "ironrdp" / safe_name
    media = (
        "application/wasm"
        if safe_name.endswith(".wasm")
        else "application/javascript"
    )
    return FileResponse(
        target,
        media_type=media,
        headers={"Cache-Control": "public, max-age=86400"},
    )


_RDP_AUDIO_SESSIONS: Dict[str, "_RdpAudioSession"] = {}


def _encode_dvc_id(chan_id: int, cb_id: int) -> bytes:
    if cb_id == 0:
        return bytes([chan_id & 0xFF])
    if cb_id == 1:
        return struct.pack("<H", chan_id & 0xFFFF)
    return struct.pack("<I", chan_id & 0xFFFFFFFF)


def _decode_dvc_id(buf: bytes, offset: int, cb_id: int) -> Tuple[int, int]:
    if cb_id == 0:
        return buf[offset], 1
    if cb_id == 1:
        return struct.unpack_from("<H", buf, offset)[0], 2
    return struct.unpack_from("<I", buf, offset)[0], 4


class _RdpAudioSession:
    """
    Bộ giải mã & ghép kênh âm thanh RDP gốc ngay trên đường truyền RDCleanPath:
    - MS-RDPSND (kênh tĩnh `rdpsnd`): nhận PCM 16-bit Stereo từ Windows -> phát ra loa điện thoại.
    - MS-RDPEAI (kênh động `AUDIO_INPUT` trên `drdynvc`): tạo thiết bị thu âm thật `Microphone (Remote Audio)`
      trên Windows và bơm luồng PCM 16-bit trực tiếp từ Microphone điện thoại vào mọi ứng dụng trên PC.
    """

    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.writer: Optional[asyncio.StreamWriter] = None
        self.audio_ws: Optional[WebSocket] = None
        self.audio_tx_q: asyncio.Queue = asyncio.Queue()
        self.client_buf = bytearray()
        self.server_buf = bytearray()

        self.cs_net_names: List[str] = []
        self.rdpsnd_chan_id: Optional[int] = None
        self.drdynvc_chan_id: Optional[int] = None
        self.mcs_initiator: Optional[int] = None

        self.rdpsnd_vc_buf = bytearray()
        self.pending_legacy_wave: Optional[Tuple[int, int, bytes]] = None
        self.spk_format: Optional[Dict[str, int]] = None

        self.drdynvc_vc_buf = bytearray()
        self.drdynvc_raw_pkts: List[bytes] = []
        self.audin_dvc_id: Optional[int] = None
        self.audin_cb_id: int = 0
        self.audin_frag_buf = bytearray()
        self.audin_expected_len: int = 0
        self.audin_open: bool = False
        self.mic_spec: Optional[Dict[str, int]] = None

    def attach_writer(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer

    def enqueue_audio_ws(self, item: Any) -> None:
        if self.audio_ws is None:
            return
        if self.audio_tx_q.qsize() > 80:
            try:
                self.audio_tx_q.get_nowait()
            except Exception:
                pass
        try:
            self.audio_tx_q.put_nowait(item)
        except Exception:
            pass

    def destroy(self) -> None:
        _RDP_AUDIO_SESSIONS.pop(self.sid, None)
        self.enqueue_audio_ws(None)

    def send_to_tls_vc(self, channel_id: Optional[int], vc_payload: bytes) -> None:
        if self.writer is None or self.mcs_initiator is None or not channel_id:
            return
        chunk_max = 1600
        total_len = len(vc_payload)
        offset = 0
        while offset < total_len or (total_len == 0 and offset == 0):
            end = min(total_len, offset + chunk_max)
            chunk = vc_payload[offset:end]
            flags = 0
            if offset == 0:
                flags |= 0x01
            if end >= total_len:
                flags |= 0x02

            vc_pdu = struct.pack("<II", total_len, flags) + chunk
            vlen = len(vc_pdu)
            if vlen < 0x80:
                per_len = bytes([vlen])
            else:
                per_len = bytes([0x80 | (vlen >> 8), vlen & 0xFF])

            mcs_hdr = struct.pack(
                ">BHHB", 0x64, self.mcs_initiator, channel_id, 0x70
            )
            tpkt_len = 4 + 3 + len(mcs_hdr) + len(per_len) + vlen
            pkt = (
                struct.pack(">BBH", 0x03, 0x00, tpkt_len)
                + b"\x02\xf0\x80"
                + mcs_hdr
                + per_len
                + vc_pdu
            )
            try:
                self.writer.write(pkt)
            except Exception:
                pass
            offset = end
            if total_len == 0:
                break

    def send_audin_dvc_data(self, payload: bytes) -> None:
        if self.audin_dvc_id is None or not self.drdynvc_chan_id:
            return
        id_buf = _encode_dvc_id(self.audin_dvc_id, self.audin_cb_id)
        max_first = 1580
        if len(payload) <= max_first:
            hdr = bytes([(0x03 << 4) | (self.audin_cb_id & 0x03)])
            self.send_to_tls_vc(self.drdynvc_chan_id, hdr + id_buf + payload)
            return
        first_hdr = bytes([(0x02 << 4) | (0x01 << 2) | (self.audin_cb_id & 0x03)])
        len_buf = struct.pack("<H", len(payload))
        self.send_to_tls_vc(
            self.drdynvc_chan_id,
            first_hdr + id_buf + len_buf + payload[:max_first],
        )
        off = max_first
        while off < len(payload):
            nxt = payload[off : off + max_first]
            data_hdr = bytes([(0x03 << 4) | (self.audin_cb_id & 0x03)])
            self.send_to_tls_vc(self.drdynvc_chan_id, data_hdr + id_buf + nxt)
            off += len(nxt)

    def forward_mic_pcm_to_server(self, pcm_bytes: bytes) -> None:
        if not self.audin_open or self.audin_dvc_id is None or not pcm_bytes:
            return
        self.send_audin_dvc_data(b"\x05")
        self.send_audin_dvc_data(b"\x06" + pcm_bytes)

    @staticmethod
    def _extract_next_pdu(buf: bytearray) -> Optional[bytes]:
        blen = len(buf)
        if blen < 2:
            return None
        if buf[0] == 0x03:
            if blen < 4:
                return None
            plen = (buf[2] << 8) | buf[3]
            if plen < 4:
                out = bytes(buf)
                buf.clear()
                return out
            if blen < plen:
                return None
            out = bytes(buf[:plen])
            del buf[:plen]
            return out
        b1 = buf[1]
        if (b1 & 0x80) == 0:
            plen = b1
            if plen < 2:
                out = bytes(buf)
                buf.clear()
                return out
        else:
            if blen < 3:
                return None
            plen = ((b1 & 0x7F) << 8) | buf[2]
        if blen < plen:
            return None
        out = bytes(buf[:plen])
        del buf[:plen]
        return out

    def process_client_chunk(self, chunk: bytes) -> List[bytes]:
        self.client_buf.extend(chunk)
        out_pkts: List[bytes] = []
        while True:
            pkt = self._extract_next_pdu(self.client_buf)
            if pkt is None:
                break
            if (
                len(pkt) >= 14
                and pkt[0] == 0x03
                and pkt[4] == 0x02
                and pkt[5] == 0xF0
                and pkt[6] == 0x80
            ):
                if not self.cs_net_names and pkt[7] == 0x7F and pkt[8] == 0x65:
                    pkt = self._scan_cs_net_and_disable_comp(pkt)
                elif (pkt[7] >> 2) == 25 and len(pkt) >= 15:
                    self.mcs_initiator = (pkt[8] << 8) | pkt[9]
                    chan_id = (pkt[10] << 8) | pkt[11]
                    if self.rdpsnd_chan_id is not None and chan_id == self.rdpsnd_chan_id:
                        continue
            out_pkts.append(pkt)
        return out_pkts

    def process_server_chunk(self, chunk: bytes) -> List[bytes]:
        self.server_buf.extend(chunk)
        out_pkts: List[bytes] = []
        while True:
            pkt = self._extract_next_pdu(self.server_buf)
            if pkt is None:
                break
            if (
                len(pkt) >= 14
                and pkt[0] == 0x03
                and pkt[4] == 0x02
                and pkt[5] == 0xF0
                and pkt[6] == 0x80
            ):
                if (
                    self.cs_net_names
                    and self.rdpsnd_chan_id is None
                    and pkt[7] == 0x7F
                    and pkt[8] == 0x66
                ):
                    self._scan_sc_net(pkt)
                elif (pkt[7] >> 2) == 26 and len(pkt) >= 16:
                    chan_id = (pkt[10] << 8) | pkt[11]
                    if self.rdpsnd_chan_id is not None and chan_id == self.rdpsnd_chan_id:
                        self._handle_rdpsnd_pkt(pkt)
                        continue
                    if self.drdynvc_chan_id is not None and chan_id == self.drdynvc_chan_id:
                        out_pkts.extend(self._handle_drdynvc_pkt(pkt))
                        continue
            out_pkts.append(pkt)
        return out_pkts

    def _scan_cs_net_and_disable_comp(self, pkt: bytes) -> bytes:
        m = bytearray(pkt)
        plen = len(m)
        for pos in range(12, plen - 19):
            if m[pos] == 0x03 and m[pos + 1] == 0xC0:
                block_len = struct.unpack_from("<H", m, pos + 2)[0]
                count = struct.unpack_from("<I", m, pos + 4)[0]
                if 1 <= count <= 31 and block_len == 8 + count * 12 and pos + block_len <= plen:
                    names: List[str] = []
                    for i in range(count):
                        c_off = pos + 8 + i * 12
                        raw_name = (
                            bytes(m[c_off : c_off + 8])
                            .split(b"\x00", 1)[0]
                            .decode("ascii", errors="ignore")
                            .lower()
                        )
                        names.append(raw_name)
                        if raw_name in ("rdpsnd", "drdynvc"):
                            opts = struct.unpack_from("<I", m, c_off + 8)[0]
                            struct.pack_into("<I", m, c_off + 8, opts & ~0x00C00000)
                    self.cs_net_names = names
                    return bytes(m)
        return pkt

    def _scan_sc_net(self, pkt: bytes) -> None:
        n = len(self.cs_net_names)
        if n == 0:
            return
        expected_pad = 2 if (n % 2 == 1) else 0
        plen = len(pkt)
        for pos in range(12, plen - (8 + n * 2) + 1):
            if pkt[pos] == 0x03 and pkt[pos + 1] == 0x0C:
                block_len, io_chan, count = struct.unpack_from("<HHH", pkt, pos + 2)
                if (
                    count == n
                    and 1000 <= io_chan <= 1100
                    and block_len in (8 + n * 2 + expected_pad, 8 + n * 2)
                ):
                    for i in range(count):
                        cid = struct.unpack_from("<H", pkt, pos + 8 + i * 2)[0]
                        if self.cs_net_names[i] == "rdpsnd":
                            self.rdpsnd_chan_id = cid
                        elif self.cs_net_names[i] == "drdynvc":
                            self.drdynvc_chan_id = cid
                    return

    @staticmethod
    def _parse_vc_chunk(pkt: bytes) -> Optional[Tuple[int, bytes]]:
        vc_off = 15 if (pkt[13] & 0x80) != 0 else 14
        if len(pkt) < vc_off + 8:
            return None
        vc_flags = struct.unpack_from("<I", pkt, vc_off + 4)[0]
        return vc_flags, pkt[vc_off + 8 :]

    def _send_wave_confirm(self, ts: int, block_no: int) -> None:
        c = struct.pack("<BBHHBB", 0x05, 0, 4, ts & 0xFFFF, block_no & 0xFF, 0)
        self.send_to_tls_vc(self.rdpsnd_chan_id, c)

    def _push_speaker_pcm(self, pcm: bytes) -> None:
        if pcm:
            self.enqueue_audio_ws(b"\x01" + pcm)

    def _handle_rdpsnd_pkt(self, pkt: bytes) -> None:
        parsed = self._parse_vc_chunk(pkt)
        if parsed is None:
            return
        vc_flags, vc_chunk = parsed
        if vc_flags & 0x01:
            self.rdpsnd_vc_buf = bytearray(vc_chunk)
        else:
            self.rdpsnd_vc_buf.extend(vc_chunk)
        if not (vc_flags & 0x02):
            return

        pdu = bytes(self.rdpsnd_vc_buf)
        self.rdpsnd_vc_buf.clear()
        if len(pdu) < 4:
            return

        if self.pending_legacy_wave is not None:
            ts, block_no, first4 = self.pending_legacy_wave
            self.pending_legacy_wave = None
            pcm = first4 + pdu[min(4, len(pdu)) :]
            self._send_wave_confirm(ts, block_no)
            self._push_speaker_pcm(pcm)
            return

        msg_type = pdu[0]
        if msg_type == 0x07 and len(pdu) >= 24:
            num_fmt = struct.unpack_from("<H", pdu, 18)[0]
            srv_ver = struct.unpack_from("<H", pdu, 21)[0]
            off = 24
            chosen: Optional[Tuple[int, int]] = None
            for _ in range(num_fmt):
                if off + 18 > len(pdu):
                    break
                tag, ch, rate, _avg, _align, bits, cb_size = struct.unpack_from(
                    "<HHIIHHH", pdu, off
                )
                if tag == 1 and bits == 16 and ch in (1, 2):
                    if (
                        chosen is None
                        or (ch == 2 and chosen[0] < 2)
                        or (rate >= 44100 and chosen[1] < 44100)
                    ):
                        chosen = (ch, rate)
                off += 18 + cb_size
            sel_ch, sel_rate = chosen if chosen is not None else (2, 44100)
            self.spk_format = {"rate": sel_rate, "channels": sel_ch}

            fmt18 = struct.pack(
                "<HHIIHHH",
                1,
                sel_ch,
                sel_rate,
                sel_rate * sel_ch * 2,
                sel_ch * 2,
                16,
                0,
            )
            cli_ver = min(max(srv_ver, 2), 6)
            body = (
                struct.pack(
                    "<IIIHHBHB",
                    0x00000003,
                    0xFFFFFFFF,
                    0,
                    0,
                    1,
                    0,
                    cli_ver,
                    0,
                )
                + fmt18
            )
            hdr = struct.pack("<BBH", 0x07, 0, len(body))
            self.send_to_tls_vc(self.rdpsnd_chan_id, hdr + body)
            if srv_ver >= 6:
                self.send_to_tls_vc(
                    self.rdpsnd_chan_id, struct.pack("<BBHHH", 0x0C, 0, 4, 2, 0)
                )
            self.enqueue_audio_ws(
                json.dumps({"type": "spk_format", **self.spk_format})
            )
        elif msg_type == 0x06 and len(pdu) >= 8:
            self.send_to_tls_vc(self.rdpsnd_chan_id, b"\x06\x00\x04\x00" + pdu[4:8])
        elif msg_type == 0x0D and len(pdu) >= 16:
            ts = struct.unpack_from("<H", pdu, 4)[0]
            block_no = pdu[8]
            self._send_wave_confirm(ts, block_no)
            self._push_speaker_pcm(pdu[16:])
        elif msg_type == 0x02 and len(pdu) >= 16:
            ts = struct.unpack_from("<H", pdu, 4)[0]
            block_no = pdu[8]
            self.pending_legacy_wave = (ts, block_no, pdu[12:16])

    def _handle_drdynvc_pkt(self, pkt: bytes) -> List[bytes]:
        parsed = self._parse_vc_chunk(pkt)
        if parsed is None:
            return [pkt]
        vc_flags, vc_chunk = parsed
        if vc_flags & 0x01:
            self.drdynvc_vc_buf = bytearray(vc_chunk)
            self.drdynvc_raw_pkts = [pkt]
        else:
            self.drdynvc_vc_buf.extend(vc_chunk)
            self.drdynvc_raw_pkts.append(pkt)
        if not (vc_flags & 0x02):
            return []

        dvc = bytes(self.drdynvc_vc_buf)
        raw_pkts = list(self.drdynvc_raw_pkts)
        self.drdynvc_vc_buf.clear()
        self.drdynvc_raw_pkts.clear()

        if len(dvc) < 2:
            return raw_pkts
        cmd = (dvc[0] >> 4) & 0x0F
        sp_len = (dvc[0] >> 2) & 0x03
        cb_id = dvc[0] & 0x03
        if cb_id == 3:
            return raw_pkts
        id_len = 1 if cb_id == 0 else (2 if cb_id == 1 else 4)
        if len(dvc) < 1 + id_len:
            return raw_pkts
        dvc_chan_id, _ = _decode_dvc_id(dvc, 1, cb_id)

        if cmd == 0x01:
            ch_name = dvc[1 + id_len :].split(b"\x00", 1)[0].decode("ascii", errors="ignore")
            if ch_name == "AUDIO_INPUT":
                self.audin_dvc_id = dvc_chan_id
                self.audin_cb_id = cb_id
                self.audin_expected_len = 0
                self.audin_frag_buf.clear()
                rsp = (
                    bytes([(0x01 << 4) | cb_id])
                    + _encode_dvc_id(dvc_chan_id, cb_id)
                    + b"\x00\x00\x00\x00"
                )
                self.send_to_tls_vc(self.drdynvc_chan_id, rsp)
                return []
            return raw_pkts

        if self.audin_dvc_id is not None and dvc_chan_id == self.audin_dvc_id:
            if cmd == 0x04:
                cls = bytes([(0x04 << 4) | cb_id]) + _encode_dvc_id(dvc_chan_id, cb_id)
                self.send_to_tls_vc(self.drdynvc_chan_id, cls)
                self.audin_open = False
                self.audin_dvc_id = None
                self.enqueue_audio_ws('{"type":"mic_stop"}')
                return []
            if cmd == 0x02:
                lbytes = 1 if sp_len == 0 else (2 if sp_len == 1 else 4)
                if len(dvc) < 1 + id_len + lbytes:
                    return []
                if lbytes == 1:
                    tlen = dvc[1 + id_len]
                elif lbytes == 2:
                    tlen = struct.unpack_from("<H", dvc, 1 + id_len)[0]
                else:
                    tlen = struct.unpack_from("<I", dvc, 1 + id_len)[0]
                self.audin_expected_len = tlen
                self.audin_frag_buf = bytearray(dvc[1 + id_len + lbytes :])
                if len(self.audin_frag_buf) >= self.audin_expected_len:
                    full = bytes(self.audin_frag_buf[: self.audin_expected_len])
                    self.audin_expected_len = 0
                    self.audin_frag_buf.clear()
                    self._handle_audin_pdu(full)
                return []
            if cmd == 0x03:
                body = dvc[1 + id_len :]
                if self.audin_expected_len > 0:
                    self.audin_frag_buf.extend(body)
                    if len(self.audin_frag_buf) >= self.audin_expected_len:
                        full = bytes(self.audin_frag_buf[: self.audin_expected_len])
                        self.audin_expected_len = 0
                        self.audin_frag_buf.clear()
                        self._handle_audin_pdu(full)
                else:
                    self._handle_audin_pdu(body)
                return []
            return []

        return raw_pkts

    def _handle_audin_pdu(self, msg: bytes) -> None:
        if not msg:
            return
        msg_id = msg[0]
        if msg_id == 0x01 and len(msg) >= 5:
            srv_ver = struct.unpack_from("<I", msg, 1)[0]
            self.send_audin_dvc_data(struct.pack("<BI", 0x01, min(max(1, srv_ver), 2)))
        elif msg_id == 0x02 and len(msg) >= 9:
            num_fmt = struct.unpack_from("<I", msg, 1)[0]
            off = 9
            chosen: Optional[Tuple[int, int]] = None
            for _ in range(num_fmt):
                if off + 18 > len(msg):
                    break
                tag, ch, rate, _avg, _align, bits, cb_size = struct.unpack_from(
                    "<HHIIHHH", msg, off
                )
                if tag == 1 and bits == 16 and ch in (1, 2):
                    if (
                        chosen is None
                        or (ch == 1 and chosen[0] > 1)
                        or (rate >= 44100 and chosen[1] < 44100)
                    ):
                        chosen = (ch, rate)
                off += 18 + cb_size
            sel_ch, sel_rate = chosen if chosen is not None else (1, 44100)
            fmt18 = struct.pack(
                "<HHIIHHH",
                1,
                sel_ch,
                sel_rate,
                sel_rate * sel_ch * 2,
                sel_ch * 2,
                16,
                0,
            )
            self.send_audin_dvc_data(struct.pack("<BII", 0x02, 1, 9 + 18) + fmt18)
        elif msg_id == 0x03 and len(msg) >= 27:
            frames_pp = struct.unpack_from("<I", msg, 1)[0] or 480
            init_fmt = struct.unpack_from("<I", msg, 5)[0]
            ch = struct.unpack_from("<H", msg, 11)[0] or 1
            rate = struct.unpack_from("<I", msg, 13)[0] or 44100
            self.send_audin_dvc_data(struct.pack("<BI", 0x07, init_fmt))
            self.send_audin_dvc_data(b"\x04\x00\x00\x00\x00")
            self.audin_open = True
            self.mic_spec = {
                "rate": rate,
                "channels": ch,
                "framesPerPacket": frames_pp,
            }
            self.enqueue_audio_ws(json.dumps({"type": "mic_start", **self.mic_spec}))
        elif msg_id == 0x07 and len(msg) >= 5:
            self.send_audin_dvc_data(msg[:5])


@app.websocket("/rdp-audio-ws")
async def rdp_audio_ws(ws: WebSocket) -> None:
    await ws.accept()
    sid = ws.query_params.get("sid", "").strip()
    if not sid:
        await ws.close()
        return
    audio_sess = _RDP_AUDIO_SESSIONS.get(sid)
    if audio_sess is None:
        audio_sess = _RdpAudioSession(sid)
        _RDP_AUDIO_SESSIONS[sid] = audio_sess

    audio_sess.audio_ws = ws
    if audio_sess.spk_format:
        await ws.send_text(json.dumps({"type": "spk_format", **audio_sess.spk_format}))
    if audio_sess.audin_open and audio_sess.mic_spec:
        await ws.send_text(json.dumps({"type": "mic_start", **audio_sess.mic_spec}))

    async def _tx_loop() -> None:
        try:
            while True:
                item = await audio_sess.audio_tx_q.get()
                if item is None:
                    break
                if isinstance(item, bytes):
                    await ws.send_bytes(item)
                elif isinstance(item, str):
                    await ws.send_text(item)
        except Exception:
            pass

    tx_task = asyncio.create_task(_tx_loop())
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            bdata = msg.get("bytes")
            if bdata and len(bdata) >= 2 and bdata[0] == 0x02:
                audio_sess.forward_mic_pcm_to_server(bdata[1:])
                if audio_sess.writer is not None:
                    try:
                        await audio_sess.writer.drain()
                    except Exception:
                        pass
    except Exception:
        pass
    finally:
        tx_task.cancel()
        if audio_sess.audio_ws is ws:
            audio_sess.audio_ws = None
        try:
            await ws.close()
        except Exception:
            pass


@app.websocket("/rdp-ws")
async def rdp_cleanpath_ws(ws: WebSocket) -> None:
    subproto = None
    raw_proto = ws.headers.get("sec-websocket-protocol", "")
    if raw_proto:
        subproto = raw_proto.split(",")[0].strip() or None
    await ws.accept(subprotocol=subproto)

    sid = ws.query_params.get("sid", "").strip()
    audio_sess: Optional[_RdpAudioSession] = None
    if sid:
        audio_sess = _RDP_AUDIO_SESSIONS.get(sid)
        if audio_sess is None:
            audio_sess = _RdpAudioSession(sid)
            _RDP_AUDIO_SESSIONS[sid] = audio_sess

    writer: Optional[asyncio.StreamWriter] = None
    pump_task: Optional[asyncio.Task] = None
    try:
        first_pkt = await asyncio.wait_for(ws.receive_bytes(), timeout=12.0)
        dest, x224_req = _parse_rdcleanpath_req(first_pkt)
        host = "192.168.52.230"
        port = 3389
        clean = dest.strip()
        if clean:
            if ":" in clean:
                h_part, p_part = clean.rsplit(":", 1)
                host = h_part.strip() or host
                try:
                    port = int(p_part)
                except ValueError:
                    port = 3389
            else:
                host = clean

        raw_sock, x224_resp = await asyncio.to_thread(
            _tcp_x224_exchange, host, port, x224_req
        )
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(sock=raw_sock, ssl=ssl_ctx, server_hostname=host),
            timeout=10.0,
        )
        if audio_sess is not None:
            audio_sess.attach_writer(writer)
        ssl_obj = writer.get_extra_info("ssl_object")
        der_cert = ssl_obj.getpeercert(binary_form=True) if ssl_obj else None
        certs = [der_cert] if der_cert else []
        resp_pdu = _build_rdcleanpath_resp(f"{host}:{port}", x224_resp, certs)
        await ws.send_bytes(resp_pdu)

        async def _tls_to_ws() -> None:
            try:
                while True:
                    chunk = await reader.read(65536)
                    if not chunk:
                        break
                    if audio_sess is not None:
                        out_pkts = audio_sess.process_server_chunk(chunk)
                        for op in out_pkts:
                            await ws.send_bytes(op)
                        if writer is not None:
                            await writer.drain()
                    else:
                        await ws.send_bytes(chunk)
            except Exception:
                pass
            try:
                await ws.close()
            except Exception:
                pass

        pump_task = asyncio.create_task(_tls_to_ws())

        while True:
            msg = await ws.receive()
            mtype = msg.get("type")
            if mtype == "websocket.disconnect":
                break
            bdata = msg.get("bytes")
            if bdata and writer is not None:
                if audio_sess is not None:
                    for cp in audio_sess.process_client_chunk(bdata):
                        writer.write(cp)
                else:
                    writer.write(bdata)
                await writer.drain()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("RDP proxy handshake/relay error: %s", exc)
        try:
            await ws.send_bytes(_build_rdcleanpath_err(1, 502))
        except Exception:
            pass
    finally:
        if audio_sess is not None:
            audio_sess.destroy()
        if pump_task is not None:
            pump_task.cancel()
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
        try:
            await ws.close()
        except Exception:
            pass


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
    import os

    real_py = str(Path(sys.executable).resolve())
    py_app = real_py.split("/Python.app/")[0] + "/Python.app" if "/Python.app/" in real_py else real_py
    is_rem, foc_app = injector.detect_focused_app_info(force=True)
    return {
        "ok": True,
        "version": "2.1.4",
        "pid": os.getpid(),
        "platform": sys.platform,
        "vn_enabled": injector.vn_enabled,
        "kb_layout": injector.kb_layout,
        "lens_available": lens_capturer.available,
        "kvm_available": kvm_bridge.available,
        "kvm_captured": kvm_bridge.captured,
        "screen_recording_ok": check_macos_screen_recording(prompt=False),
        "remote_pc_focused": is_rem,
        "focused_app": Path(foc_app).name if "/" in foc_app else foc_app,
        "python_app": py_app,
    }


def _trigger_clean_respawn() -> None:
    import os

    if IS_MACOS and hasattr(os, "getuid"):
        try:
            subprocess.Popen(
                ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.nguyenhieu.macwebkeyboard"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    time.sleep(0.35)
    os._exit(0)


@app.post("/respawn")
@app.get("/respawn")
async def respawn_worker() -> dict:
    """Khởi chạy lại tiến trình mới sạch hoàn toàn qua launchd để nhận quyền Screen Recording vừa bật."""
    threading.Timer(0.2, _trigger_clean_respawn).start()
    return {"ok": True, "restarting": True}


@app.post("/open-screen-perm")
@app.get("/open-screen-perm")
async def open_screen_perm() -> dict:
    if not IS_MACOS:
        return {"ok": False}
    real_py = str(Path(sys.executable).resolve())
    py_app = real_py.split("/Python.app/")[0] + "/Python.app" if "/Python.app/" in real_py else real_py
    check_macos_screen_recording(prompt=True)
    subprocess.Popen(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if Path(py_app).exists():
        subprocess.Popen(
            ["open", "-R", py_app],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return {"ok": True, "python_app": py_app}


@app.websocket("/ws")
async def keyboard_ws(ws: WebSocket) -> None:
    await ws.accept()
    client_host = ws.client.host if ws.client else "unknown"
    trusted = check_macos_accessibility(prompt=True)
    screen_ok = check_macos_screen_recording(prompt=True)
    if injector.vn_enabled:
        ensure_macos_abc_input_source()
    logger.info(
        "Đã kết nối điện thoại từ: %s (Accessibility=%s, ScreenRec=%s, Lens=%s, Layout=%s, VN=%s)",
        client_host,
        trusted,
        screen_ok,
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
                "screen_ok": screen_ok,
            }
        )
    )
    await ws.send_text(
        json.dumps(injector.get_live_preview_snapshot(), ensure_ascii=False)
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
    kvm_queue: asyncio.Queue = asyncio.Queue()
    cur_loop = asyncio.get_running_loop()

    async def stream_kvm_loop() -> None:
        try:
            while lens_cfg["running"]:
                msg_str = await kvm_queue.get()
                await ws.send_text(msg_str)
        except Exception:
            pass

    kvm_task = asyncio.create_task(stream_kvm_loop())

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
                raw_mods = data.get("mods")
                t_mods = [str(m) for m in raw_mods] if isinstance(raw_mods, list) else None
                injector.press_key(key, t_mods)
                await ws.send_text(json.dumps(injector.get_live_preview_snapshot(), ensure_ascii=False))
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
                    await ws.send_text(json.dumps(injector.get_live_preview_snapshot(), ensure_ascii=False))
            elif msg_type == "clear_preview":
                injector.clear_live_preview()
                await ws.send_text(json.dumps(injector.get_live_preview_snapshot(), ensure_ascii=False))
            elif msg_type == "open_screen_perm":
                await open_screen_perm()
            elif msg_type == "respawn_server":
                threading.Timer(0.15, _trigger_clean_respawn).start()
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
                is_drag = bool(data.get("drag", False))
                injector.mouse_down(btn, is_drag_start=is_drag)
            elif msg_type == "mouse_up":
                btn = str(data.get("button", "left"))
                injector.mouse_up(btn)
            elif msg_type == "mouse_scroll":
                dx = float(data.get("dx", 0.0))
                dy = float(data.get("dy", 0.0))
                injector.mouse_scroll(dx, dy)
            elif msg_type == "config":
                if "vn" in data:
                    injector._commit_telex_word_to_preview()
                    injector.vn_enabled = bool(data["vn"])
                    injector.telex.reset()
                    if injector.vn_enabled:
                        ensure_macos_abc_input_source()
                if "layout" in data and data["layout"] in ("win", "mac", "pad", "remote"):
                    injector._commit_telex_word_to_preview()
                    injector.kb_layout = str(data["layout"])
                    injector.telex.reset()
                    if injector.kb_layout != "remote":
                        kvm_bridge.attach_client(ws, cur_loop, kvm_queue, False)
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "state",
                            "vn": injector.vn_enabled,
                            "layout": injector.kb_layout,
                        }
                    )
                )
            elif msg_type == "kvm_config":
                kvm_on = bool(data.get("enabled", False))
                edge_m = str(data.get("edge", "any"))
                kvm_bridge.attach_client(ws, cur_loop, kvm_queue, kvm_on, edge_m)
            elif msg_type == "kvm_return":
                r_edge = data.get("mac_edge")
                r_ratio = data.get("ratio")
                kvm_bridge.release_to_mac(
                    str(r_edge) if r_edge is not None else None,
                    float(r_ratio) if r_ratio is not None else None,
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
        kvm_task.cancel()
        kvm_bridge.detach_client(ws)
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


def start_clipboard_retina_normalizer(poll_sec: float = 0.25) -> None:
    """
    Chuẩn hóa ảnh chụp màn hình Retina (144 DPI @2x) trong Clipboard của macOS về tỷ lệ 1:1 pixel (72 DPI)
    để khi bấm Command+V trong Zalo, Antigravity, Chrome/Electron không bị giảm 50% độ phân giải (mờ).
    """
    if not IS_MACOS:
        return

    def _worker() -> None:
        try:
            import AppKit  # type: ignore
            import objc  # type: ignore

            pb = AppKit.NSPasteboard.generalPasteboard()
            last_count = int(pb.changeCount())
            while True:
                time.sleep(poll_sec)
                with objc.autorelease_pool():
                    cur_count = int(pb.changeCount())
                    if cur_count == last_count:
                        continue
                    last_count = cur_count
                    types = pb.types()
                    if not types or "public.png" not in types:
                        continue
                    # Chỉ chuẩn hóa khi là ảnh chụp trực tiếp trong RAM (không phải copy file từ Finder)
                    if "public.file-url" in types or "NSFilenamesPboardType" in types:
                        continue
                    data = pb.dataForType_("public.png")
                    if not data:
                        continue
                    rep = AppKit.NSBitmapImageRep.imageRepWithData_(data)
                    if not rep:
                        continue
                    pw, ph = int(rep.pixelsWide()), int(rep.pixelsHigh())
                    sw, sh = float(rep.size().width), float(rep.size().height)
                    if pw > sw + 1.0 or ph > sh + 1.0:
                        rep.setSize_((float(pw), float(ph)))
                        new_png = rep.representationUsingType_properties_(
                            AppKit.NSBitmapImageFileTypePNG, {}
                        )
                        if new_png:
                            pb.clearContents()
                            pb.setData_forType_(new_png, "public.png")
                            pb.setData_forType_(new_png, "Apple PNG pasteboard type")
                            last_count = int(pb.changeCount())
        except Exception as exc:
            logger.debug("Clipboard retina normalizer stopped: %s", exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def start_git_auto_updater(check_every_sec: float = 45.0) -> None:
    """Tự động kiểm tra GitHub định kỳ; nếu có bản server.py mới trên origin/main thì tự git pull và khởi động lại ngầm."""
    import os

    def _updater() -> None:
        while True:
            time.sleep(check_every_sec)
            try:
                if not (BASE_DIR / ".git").exists():
                    continue
                subprocess.run(
                    ["git", "fetch", "origin", "main", "--quiet"],
                    cwd=str(BASE_DIR),
                    timeout=10,
                    check=False,
                )
                local_sha = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=str(BASE_DIR), text=True, timeout=5
                ).strip()
                remote_sha = subprocess.check_output(
                    ["git", "rev-parse", "origin/main"], cwd=str(BASE_DIR), text=True, timeout=5
                ).strip()
                if local_sha and remote_sha and local_sha != remote_sha:
                    logger.info("Phát hiện bản mới trên GitHub (%s -> %s), tự động cập nhật server...", local_sha[:7], remote_sha[:7])
                    pull_res = subprocess.run(
                        ["git", "pull", "--ff-only", "origin", "main"],
                        cwd=str(BASE_DIR),
                        timeout=20,
                        check=False,
                    )
                    if pull_res.returncode == 0:
                        _trigger_clean_respawn()
            except Exception:
                pass

    t = threading.Thread(target=_updater, daemon=True)
    t.start()


if __name__ == "__main__":
    check_macos_accessibility()
    check_macos_screen_recording(prompt=True)
    start_notification_auto_dismisser(max_seconds=4.0)
    start_clipboard_retina_normalizer(poll_sec=0.25)
    start_git_auto_updater(check_every_sec=45.0)
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
