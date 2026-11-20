#!/usr/bin/env python3
"""
Mac Web Virtual Keyboard Server (LAN / Tailscale -> macOS Hardware Key Events)
Lắng nghe tại 0.0.0.0:5050, phục vụ giao diện PWA / Android WebView với:
- 2 bộ bàn phím vật lý chuẩn: Bàn phím dây Windows (ANSI PC) & Bàn phím Mac.
- Bộ gõ Tiếng Việt Telex chuẩn PC (Unikey / EVKey) tích hợp trực tiếp trên Server.
"""

from __future__ import annotations

import asyncio
import atexit
import ctypes
import ctypes.util
import hashlib
import io
import json
import logging
import os
import plistlib
import re
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
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

    def mouse_scroll(self, dx: float, dy: float, phase: int = 2) -> None:
        now_s = time.monotonic()
        self.last_activity_at = now_s
        if not self._use_quartz:
            try:
                rem_x = getattr(self, "_win_scroll_rem_x", 0.0) + float(dx) / 14.0
                rem_y = getattr(self, "_win_scroll_rem_y", 0.0) + float(dy) / 14.0
                sx = int(rem_x)
                sy = int(rem_y)
                self._win_scroll_rem_x = rem_x - sx
                self._win_scroll_rem_y = rem_y - sy
                if sx != 0 or sy != 0:
                    self._pynput_mouse.scroll(sx, sy)
            except Exception:
                pass
            return
        q = self._quartz
        iy = int(round(dy))
        ix = int(round(dx))
        if iy == 0 and ix == 0 and phase != 4:
            return
        last_s = float(getattr(self, "_last_scroll_at", 0.0))
        if phase == 2 and (now_s - last_s) > 0.18:
            phase = 1
        self._last_scroll_at = now_s
        ev = q.CGEventCreateScrollWheelEvent(
            self._event_source,
            q.kCGScrollEventUnitPixel,
            2,
            iy,
            ix,
        )
        # Đầy đủ chữ ký Apple Magic Trackpad (IsContinuous=88, PointDelta=96/97, ScrollPhase=99, MomentumPhase=123)
        # + Post qua kCGAnnotatedSessionEventTap để đi sau CGEventTap của Mos (tránh bị Mos nuốt xung cuộn trên Trackpad & thanh cuộn dọc!).
        q.CGEventSetIntegerValueField(ev, 88, 1)
        q.CGEventSetIntegerValueField(ev, 96, iy)
        q.CGEventSetIntegerValueField(ev, 97, ix)
        if phase == 8:
            q.CGEventSetIntegerValueField(ev, 99, 0)
            q.CGEventSetIntegerValueField(ev, 123, 2)
        else:
            q.CGEventSetIntegerValueField(ev, 99, phase if phase in (1, 2, 4) else 2)
            q.CGEventSetIntegerValueField(ev, 123, 0)
        q.CGEventSetIntegerValueField(ev, q.kCGEventSourceUserData, 0x4D4B4231)
        if self.held_modifiers:
            q.CGEventSetFlags(ev, self._compute_quartz_flags())
        q.CGEventPost(getattr(q, "kCGAnnotatedSessionEventTap", q.kCGSessionEventTap), ev)


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


_CURSOR_SHIELD_OBJC = r"""
#import <Cocoa/Cocoa.h>
#import <CoreGraphics/CoreGraphics.h>
#include <dlfcn.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef uint32_t CGSConnectionID;
typedef CGSConnectionID (*CGSDefaultConnFn)(void);
typedef CGError (*CGSSetConnPropFn)(CGSConnectionID, CGSConnectionID, CFStringRef, CFTypeRef);

static NSCursor *g_blankCursor = nil;
static BOOL g_hidden = NO;
static int g_pin = 1;
static double g_qx = 756.0;
static double g_qy = 978.0;

static void EnableBgCursorProp(void) {
    CGSDefaultConnFn defFn = (CGSDefaultConnFn)dlsym(RTLD_DEFAULT, "_CGSDefaultConnection");
    if (!defFn) defFn = (CGSDefaultConnFn)dlsym(RTLD_DEFAULT, "CGSDefaultConnectionForThread");
    CGSSetConnPropFn setFn = (CGSSetConnPropFn)dlsym(RTLD_DEFAULT, "CGSSetConnectionProperty");
    if (defFn && setFn) {
        CGSConnectionID cid = defFn();
        if (cid) {
            setFn(cid, cid, CFSTR("SetsCursorInBackground"), kCFBooleanTrue);
        }
    }
}

static NSCursor *GetBlankCursor(void) {
    if (!g_blankCursor) {
        NSBitmapImageRep *rep = [[NSBitmapImageRep alloc]
            initWithBitmapDataPlanes:NULL
                          pixelsWide:16
                          pixelsHigh:16
                       bitsPerSample:8
                     samplesPerPixel:4
                            hasAlpha:YES
                            isPlanar:NO
                      colorSpaceName:NSCalibratedRGBColorSpace
                         bytesPerRow:64
                        bitsPerPixel:32];
        unsigned char *bmp = [rep bitmapData];
        if (bmp) memset(bmp, 0, 16 * 64);
        NSImage *img = [[NSImage alloc] initWithSize:NSMakeSize(16, 16)];
        [img addRepresentation:rep];
        g_blankCursor = [[NSCursor alloc] initWithImage:img hotSpot:NSMakePoint(8, 8)];
    }
    return g_blankCursor;
}

static void PostSilentMoveAt(double qx, double qy) {
    CGEventRef ev = CGEventCreateMouseEvent(NULL, kCGEventMouseMoved, CGPointMake(qx, qy), kCGMouseButtonLeft);
    if (ev) {
        CGEventSetIntegerValueField(ev, kCGEventSourceUserData, 0x4D4B4231);
        CGEventPost(kCGHIDEventTap, ev);
        CFRelease(ev);
    }
}

static void ForceHideMacCursorNow(void) {
    [GetBlankCursor() set];
    for (int i = 0; i < 10 && CGCursorIsVisible(); i++) {
        CGDisplayHideCursor(kCGNullDirectDisplay);
        CGDisplayHideCursor(CGMainDisplayID());
    }
}

static void ForceShowMacCursorNow(void) {
    [[NSCursor arrowCursor] set];
    for (int i = 0; i < 16 && !CGCursorIsVisible(); i++) {
        CGDisplayShowCursor(kCGNullDirectDisplay);
        CGDisplayShowCursor(CGMainDisplayID());
    }
}

@interface CursorShieldPanel : NSPanel
@end
@implementation CursorShieldPanel
- (BOOL)canBecomeKeyWindow { return NO; }
- (BOOL)canBecomeMainWindow { return NO; }
@end

@interface CursorShieldView : NSView
@end
@implementation CursorShieldView
- (void)updateTrackingAreas {
    [super updateTrackingAreas];
    for (NSTrackingArea *ta in [self.trackingAreas copy]) {
        [self removeTrackingArea:ta];
    }
    NSTrackingAreaOptions opts = (NSTrackingCursorUpdate |
                                  NSTrackingMouseEnteredAndExited |
                                  NSTrackingMouseMoved |
                                  NSTrackingActiveAlways |
                                  NSTrackingInVisibleRect);
    NSTrackingArea *ta = [[NSTrackingArea alloc] initWithRect:NSZeroRect
                                                      options:opts
                                                        owner:self
                                                     userInfo:nil];
    [self addTrackingArea:ta];
}
- (void)resetCursorRects {
    [super resetCursorRects];
    [self addCursorRect:self.bounds cursor:GetBlankCursor()];
}
- (void)cursorUpdate:(NSEvent *)event { [GetBlankCursor() set]; }
- (void)mouseEntered:(NSEvent *)event { [GetBlankCursor() set]; }
- (void)mouseMoved:(NSEvent *)event { [GetBlankCursor() set]; }
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [app finishLaunching];
        EnableBgCursorProp();
        CGSetLocalEventsSuppressionInterval(0.0);

        NSRect initRect = NSMakeRect(-200.0, -200.0, 36.0, 36.0);
        CursorShieldPanel *panel = [[CursorShieldPanel alloc]
            initWithContentRect:initRect
                      styleMask:(NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel)
                        backing:NSBackingStoreBuffered
                          defer:NO];
        panel.opaque = NO;
        panel.hasShadow = NO;
        panel.backgroundColor = [NSColor colorWithWhite:0.0 alpha:0.004];
        panel.ignoresMouseEvents = NO;
        panel.level = (NSWindowLevel)(CGShieldingWindowLevel() + 1);
        panel.collectionBehavior = (NSWindowCollectionBehaviorCanJoinAllSpaces |
                                    NSWindowCollectionBehaviorFullScreenAuxiliary |
                                    NSWindowCollectionBehaviorStationary |
                                    NSWindowCollectionBehaviorIgnoresCycle);
        CursorShieldView *sview = [[CursorShieldView alloc] initWithFrame:NSMakeRect(0, 0, 36.0, 36.0)];
        panel.contentView = sview;

        void (^applyHide)(double, double, int) = ^(double qx, double qy, int pin) {
            g_hidden = YES;
            g_qx = qx;
            g_qy = qy;
            g_pin = pin;
            CGRect mb = CGDisplayBounds(CGMainDisplayID());
            double cocoaY = mb.size.height - qy;
            [panel setFrame:NSMakeRect(qx - 18.0, cocoaY - 18.0, 36.0, 36.0) display:YES];
            [panel orderFrontRegardless];
            [panel invalidateCursorRectsForView:sview];
            if (pin) {
                CGSetLocalEventsSuppressionInterval(0.0);
                CGWarpMouseCursorPosition(CGPointMake(qx, qy));
                CGAssociateMouseAndMouseCursorPosition(false);
                PostSilentMoveAt(qx, qy);
            }
            ForceHideMacCursorNow();
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(30 * NSEC_PER_MSEC)), dispatch_get_main_queue(), ^{
                if (g_hidden) ForceHideMacCursorNow();
            });
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(90 * NSEC_PER_MSEC)), dispatch_get_main_queue(), ^{
                if (g_hidden) ForceHideMacCursorNow();
            });
        };

        void (^applyShow)(void) = ^{
            g_hidden = NO;
            g_pin = 0;
            [panel orderOut:nil];
            ForceShowMacCursorNow();
        };

        [NSTimer scheduledTimerWithTimeInterval:0.016
                                        repeats:YES
                                          block:^(NSTimer *t) {
            (void)t;
            if (!g_hidden) return;
            if (CGCursorIsVisible()) {
                ForceHideMacCursorNow();
            }
            if (g_pin) {
                CGEventRef ev = CGEventCreate(NULL);
                if (ev) {
                    CGPoint p = CGEventGetLocation(ev);
                    CFRelease(ev);
                    if (fabs(p.x - g_qx) > 3.0 || fabs(p.y - g_qy) > 3.0) {
                        CGSetLocalEventsSuppressionInterval(0.0);
                        CGWarpMouseCursorPosition(CGPointMake(g_qx, g_qy));
                        CGAssociateMouseAndMouseCursorPosition(false);
                        PostSilentMoveAt(g_qx, g_qy);
                        ForceHideMacCursorNow();
                    }
                }
            }
        }];

        dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_HIGH, 0), ^{
            char line[256];
            while (fgets(line, sizeof(line), stdin) != NULL) {
                if (line[0] == 'H') {
                    double qx = 756.0, qy = 978.0;
                    int pin = 1;
                    sscanf(line + 1, "%lf %lf %d", &qx, &qy, &pin);
                    dispatch_async(dispatch_get_main_queue(), ^{
                        applyHide(qx, qy, pin);
                    });
                } else if (line[0] == 'P') {
                    int pin = 1;
                    sscanf(line + 1, "%d", &pin);
                    dispatch_async(dispatch_get_main_queue(), ^{
                        g_pin = pin;
                        if (g_hidden) ForceHideMacCursorNow();
                    });
                } else if (line[0] == 'R') {
                    dispatch_async(dispatch_get_main_queue(), ^{
                        if (g_hidden) ForceHideMacCursorNow();
                    });
                } else if (line[0] == 'S') {
                    dispatch_async(dispatch_get_main_queue(), ^{
                        applyShow();
                    });
                } else if (line[0] == 'Q') {
                    break;
                }
            }
            dispatch_async(dispatch_get_main_queue(), ^{
                applyShow();
                [NSApp stop:nil];
                NSEvent *w = [NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                                location:NSZeroPoint
                                           modifierFlags:0
                                               timestamp:0
                                            windowNumber:0
                                                 context:nil
                                                 subtype:0
                                                   data1:0
                                                   data2:0];
                if (w) [NSApp postEvent:w atStart:YES];
            });
            usleep(120000);
            ForceShowMacCursorNow();
            _exit(0);
        });

        [NSApp run];
    }
    return 0;
}
"""


class MacKvmBridge:
    """
    Quản lý 3 chế độ Con chuột vật lý độc lập, rõ ràng (không bao giờ chạy trùng trên cả 2 màn hình):
    1) `mac`    : Con chuột chỉ dùng riêng trên MacBook 100%.
    2) `phone`  : Con chuột khóa tách sang riêng màn hình Remote PC trên điện thoại 100% (tắt trên Mac).
    3) `bridge` : Kết nối 2 cửa sổ (Điện thoại đặt bên trái MacBook) — di chuột chạm mép TRÁI của Mac
                  sẽ sang mép PHẢI của điện thoại; di chuột chạm mép PHẢI của điện thoại sẽ về mép TRÁI của Mac.
    (Nhấn `Ctrl + Option` trên bàn phím MacBook bất cứ lúc nào để trả chuột về lại Mac ngay lập tức).
    """

    def __init__(self) -> None:
        self.available: bool = False
        self.captured: bool = False
        self.mode: str = "mac"
        self._kvm_enabled: bool = False
        self._active_ws: Optional[WebSocket] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._send_queue: Optional[asyncio.Queue] = None
        self._saved_pos: Tuple[float, float] = (600.0, 400.0)
        self._park_pos: Tuple[float, float] = (756.0, 978.0)
        self._left_edge_push: float = 0.0
        self._right_edge_push: float = 0.0
        self._last_cross_at: float = 0.0
        self._last_rehide_at: float = 0.0
        self._bounds_cache: Tuple[float, float, float, float] = (0.0, 0.0, 1440.0, 900.0)
        self._bounds_at: float = 0.0
        self._quartz: Any = None
        self._tap: Any = None
        self._cursor_hidden: bool = False
        self._bg_cursor_ready: bool = False
        self._shield_proc: Optional[subprocess.Popen] = None
        self._shield_lock = threading.Lock()
        self._lock = threading.Lock()

        if IS_MACOS:
            self._enable_background_cursor_control()
            threading.Thread(target=self._ensure_shield_helper, daemon=True).start()
            self._start_tap_thread()
            atexit.register(self._restore_cursor_on_exit)

    def _ensure_shield_helper(self) -> Optional[subprocess.Popen]:
        if not IS_MACOS:
            return None
        with self._shield_lock:
            if self._shield_proc is not None and self._shield_proc.poll() is None:
                return self._shield_proc
            try:
                cache_dir = Path.home() / ".cache" / "mac-web-keyboard"
                cache_dir.mkdir(parents=True, exist_ok=True)
                src_p = cache_dir / "mac_cursor_shield_v1.m"
                bin_p = cache_dir / "mac_cursor_shield_v1"
                need_build = not bin_p.exists()
                if not src_p.exists() or src_p.read_text(encoding="utf-8", errors="ignore") != _CURSOR_SHIELD_OBJC:
                    src_p.write_text(_CURSOR_SHIELD_OBJC, encoding="utf-8")
                    need_build = True
                if need_build:
                    subprocess.run(
                        [
                            "clang", "-fobjc-arc", "-O2",
                            "-framework", "Cocoa",
                            "-framework", "CoreGraphics",
                            "-framework", "ApplicationServices",
                            str(src_p), "-o", str(bin_p),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=20,
                        check=True,
                    )
                self._shield_proc = subprocess.Popen(
                    [str(bin_p)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                return self._shield_proc
            except Exception as exc:
                logger.debug("CursorShield helper init error: %s", exc)
                self._shield_proc = None
                return None

    def _send_shield_cmd(self, cmd: str) -> None:
        if not IS_MACOS:
            return
        proc = self._ensure_shield_helper()
        if proc is None or proc.stdin is None:
            return
        with self._shield_lock:
            try:
                proc.stdin.write(cmd + "\n")
                proc.stdin.flush()
            except Exception:
                self._shield_proc = None

    def _get_main_park_point(self) -> Tuple[float, float]:
        q = self._quartz
        if q is not None:
            try:
                mb = q.CGDisplayBounds(q.CGMainDisplayID())
                # Đỗ tại tâm cạnh đáy (cách xa SmartRightDock bên phải, cạnh trái, Menu Bar trên và 4 góc Hot Corners!)
                px = float(mb.origin.x) + float(mb.size.width) * 0.5
                py = float(mb.origin.y) + max(40.0, float(mb.size.height) - 4.0)
                self._park_pos = (px, py)
                return self._park_pos
            except Exception:
                pass
        return self._park_pos

    def _enable_background_cursor_control(self) -> None:
        if not IS_MACOS:
            return
        try:
            app_svc_path = ctypes.util.find_library("ApplicationServices")
            cf_path = ctypes.util.find_library("CoreFoundation")
            if not app_svc_path or not cf_path:
                return
            app_svc = ctypes.cdll.LoadLibrary(app_svc_path)
            cf = ctypes.cdll.LoadLibrary(cf_path)
            cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            cf.CFRelease.restype = None
            set_prop = getattr(app_svc, "CGSSetConnectionProperty", None)
            if set_prop is None:
                return
            set_prop.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            set_prop.restype = ctypes.c_int32
            k_true_val = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue").value
            cf_key = cf.CFStringCreateWithCString(None, b"SetsCursorInBackground", 0x08000100)
            if not cf_key or not k_true_val:
                return
            try:
                for fn_name in ("_CGSDefaultConnection", "CGSDefaultConnectionForThread"):
                    cgs_fn = getattr(app_svc, fn_name, None)
                    if cgs_fn is not None:
                        cgs_fn.argtypes = []
                        cgs_fn.restype = ctypes.c_uint32
                        cid = cgs_fn()
                        if cid:
                            set_prop(cid, cid, cf_key, k_true_val)
                self._bg_cursor_ready = True
            finally:
                cf.CFRelease(cf_key)
        except Exception as exc:
            logger.debug("SetsCursorInBackground init skipped: %s", exc)

    def _set_mac_cursor_hidden(self, hide: bool) -> None:
        q = self._quartz
        if q is None or not IS_MACOS:
            return
        try:
            self._enable_background_cursor_control()
            disp_id = q.CGMainDisplayID()
            null_id = getattr(q, "kCGNullDirectDisplay", 0)
            is_vis_fn = getattr(q, "CGCursorIsVisible", None)
            if hide:
                px, py = self._get_main_park_point()
                pin_flag = 0 if int(globals().get("_ACTIVE_RDP_WS_COUNT", 0) or 0) > 0 else 1
                self._send_shield_cmd(f"H {px:.1f} {py:.1f} {pin_flag}")
                if callable(is_vis_fn):
                    for _ in range(8):
                        if not is_vis_fn():
                            break
                        q.CGDisplayHideCursor(null_id)
                        q.CGDisplayHideCursor(disp_id)
                elif not self._cursor_hidden:
                    q.CGDisplayHideCursor(null_id)
                    q.CGDisplayHideCursor(disp_id)
                self._cursor_hidden = True
            else:
                self._send_shield_cmd("S")
                if callable(is_vis_fn):
                    for _ in range(16):
                        if is_vis_fn():
                            break
                        q.CGDisplayShowCursor(null_id)
                        q.CGDisplayShowCursor(disp_id)
                elif self._cursor_hidden:
                    q.CGDisplayShowCursor(null_id)
                    q.CGDisplayShowCursor(disp_id)
                self._cursor_hidden = False
        except Exception as exc:
            logger.debug("Cursor visibility toggle error: %s", exc)

    def reassert_cursor_hidden(self, pin: Optional[bool] = None, force: bool = False) -> None:
        if not self.captured or not IS_MACOS:
            return
        now = time.monotonic()
        if pin is not None:
            self._send_shield_cmd(f"P {1 if pin else 0}")
        elif force:
            self._send_shield_cmd("R")
        if not force and (now - self._last_rehide_at) < 0.08 and pin is None:
            return
        self._last_rehide_at = now
        q = self._quartz
        if q is not None:
            try:
                is_vis_fn = getattr(q, "CGCursorIsVisible", None)
                if callable(is_vis_fn) and is_vis_fn():
                    q.CGDisplayHideCursor(getattr(q, "kCGNullDirectDisplay", 0))
                    q.CGDisplayHideCursor(q.CGMainDisplayID())
            except Exception:
                pass

    def _restore_cursor_on_exit(self) -> None:
        try:
            self._send_shield_cmd("S")
            self._send_shield_cmd("Q")
        except Exception:
            pass
        try:
            q = self._quartz
            if q is not None:
                q.CGAssociateMouseAndMouseCursorPosition(True)
                is_vis_fn = getattr(q, "CGCursorIsVisible", None)
                if callable(is_vis_fn):
                    for _ in range(16):
                        if is_vis_fn():
                            break
                        q.CGDisplayShowCursor(getattr(q, "kCGNullDirectDisplay", 0))
                        q.CGDisplayShowCursor(q.CGMainDisplayID())
                elif self._cursor_hidden:
                    q.CGDisplayShowCursor(q.CGMainDisplayID())
                self._cursor_hidden = False
        except Exception:
            pass

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

    def _disable_warp_suppression(self) -> None:
        q = self._quartz
        if q is None:
            return
        try:
            if hasattr(q, "CGSetLocalEventsSuppressionInterval"):
                q.CGSetLocalEventsSuppressionInterval(0.0)
        except Exception:
            pass
        try:
            if hasattr(q, "CGEventSourceSetLocalEventsSuppressionInterval"):
                q.CGEventSourceSetLocalEventsSuppressionInterval(None, 0.0)
        except Exception:
            pass

    def attach_client(
        self,
        ws: WebSocket,
        loop: asyncio.AbstractEventLoop,
        send_queue: asyncio.Queue,
        enabled: bool,
        mode: str = "mac",
    ) -> None:
        clean_mode = mode if mode in ("mac", "phone", "bridge") else "mac"
        with self._lock:
            self._active_ws = ws
            self._loop = loop
            self._send_queue = send_queue
            self._kvm_enabled = bool(enabled)
            self._left_edge_push = 0.0
            if not self._kvm_enabled:
                self.mode = clean_mode
                if self.captured:
                    self._set_captured_locked(False)
                else:
                    self._enqueue_payload(
                        {
                            "type": "kvm_state",
                            "mode": self.mode,
                            "captured": False,
                        }
                    )
                return

            prev_mode = self.mode
            self.mode = clean_mode
            if clean_mode == "mac":
                self._set_captured_locked(False)
            elif clean_mode == "phone":
                self._set_captured_locked(True, enter_edge="center", y_ratio=0.5)
            else:
                # Chế độ `bridge` (Nối 2 màn): nếu trước đó đang khóa cứng `phone` thì nhả về Mac để bắt đầu di tự nhiên
                if prev_mode == "phone" and self.captured:
                    self._set_captured_locked(False)
                else:
                    self._enqueue_payload(
                        {
                            "type": "kvm_state",
                            "mode": self.mode,
                            "captured": self.captured,
                        }
                    )

    def detach_client(self, ws: WebSocket) -> None:
        with self._lock:
            if self._active_ws is ws:
                self._kvm_enabled = False
                self._active_ws = None
                self._loop = None
                self._send_queue = None
                self._left_edge_push = 0.0
                if self.captured:
                    self._set_captured_locked(False)

    def _set_captured_locked(
        self,
        target: bool,
        enter_edge: str = "center",
        y_ratio: float = 0.5,
        save_cur_pos: bool = True,
    ) -> None:
        q = self._quartz
        if target and (not self._kvm_enabled or self._active_ws is None):
            target = False
        if self.captured == target:
            self._enqueue_payload(
                {
                    "type": "kvm_state",
                    "mode": self.mode,
                    "captured": self.captured,
                    "enter_edge": enter_edge,
                    "y_ratio": round(y_ratio, 4),
                }
            )
            return

        self.captured = target
        if q is not None:
            try:
                min_x, min_y, max_x, max_y = self._get_desktop_bounds()
                self._disable_warp_suppression()
                if target:
                    if save_cur_pos:
                        try:
                            loc = q.CGEventGetLocation(q.CGEventCreate(None))
                            self._saved_pos = (float(loc.x), float(loc.y))
                        except Exception:
                            pass
                    pk_x, pk_y = self._get_main_park_point()
                    q.CGWarpMouseCursorPosition((pk_x, pk_y))
                    q.CGAssociateMouseAndMouseCursorPosition(False)
                    self._set_mac_cursor_hidden(True)
                else:
                    self._set_mac_cursor_hidden(False)
                    q.CGAssociateMouseAndMouseCursorPosition(True)
                    rx, ry = self._saved_pos
                    rx = max(min_x + 3.0, min(max_x - 8.0, rx))
                    ry = max(min_y + 8.0, min(max_y - 8.0, ry))
                    q.CGWarpMouseCursorPosition((rx, ry))
            except Exception as exc:
                logger.debug("KVM switch error: %s", exc)

        self._enqueue_payload(
            {
                "type": "kvm_state",
                "mode": self.mode,
                "captured": self.captured,
                "enter_edge": enter_edge,
                "y_ratio": round(y_ratio, 4),
            }
        )

    def bridge_return_to_mac(
        self, y_ratio: float = 0.5, return_edge: str = "left"
    ) -> None:
        with self._lock:
            min_x, min_y, max_x, max_y = self._get_desktop_bounds()
            clamped_r = max(0.02, min(0.98, float(y_ratio)))
            ry = min_y + clamped_r * max(1.0, max_y - min_y)
            if return_edge == "right":
                self._saved_pos = (max_x - 6.0, ry)
            else:
                self._saved_pos = (min_x + 5.0, ry)
            self._last_cross_at = time.monotonic()
            self._left_edge_push = 0.0
            self._right_edge_push = 0.0
            self._set_captured_locked(False, save_cur_pos=False)

    def emergency_release_to_mac(self) -> None:
        with self._lock:
            if self.mode == "phone":
                self.mode = "mac"
            self._last_cross_at = time.monotonic()
            self._left_edge_push = 0.0
            self._right_edge_push = 0.0
            self._set_captured_locked(False, save_cur_pos=False)

    def set_captured(self, target: bool) -> None:
        with self._lock:
            self._set_captured_locked(bool(target))

    def _start_tap_thread(self) -> None:
        def _runner() -> None:
            try:
                import Quartz  # type: ignore

                self._quartz = Quartz
                q = Quartz
                self._enable_background_cursor_control()
                self._disable_warp_suppression()

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
                                req = int(q.kCGEventFlagMaskControl) | int(
                                    q.kCGEventFlagMaskAlternate
                                )
                                if (flags & req) == req:
                                    self.emergency_release_to_mac()
                            return event

                        if (
                            not self._kvm_enabled
                            or self._active_ws is None
                            or self.mode == "mac"
                        ):
                            if self.captured:
                                self.set_captured(False)
                            return event

                        user_tag = int(
                            q.CGEventGetIntegerValueField(event, q.kCGEventSourceUserData)
                        )
                        if user_tag == 0x4D4B4231:
                            return event

                        dx = float(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaX))
                        dy = float(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaY))

                        # Chế độ 3 (`bridge`): đang ở màn Mac, di chuột chạm mép TRÁI hoặc PHẢI của Mac -> sang màn Điện thoại và ẩn hẳn chuột trên Mac!
                        if not self.captured:
                            if (
                                self.mode == "bridge"
                                and event_type == q.kCGEventMouseMoved
                            ):
                                loc = q.CGEventGetLocation(event)
                                cur_x = float(loc.x)
                                cur_y = float(loc.y)
                                min_x, min_y, max_x, max_y = self._get_desktop_bounds()
                                cooldown_ok = (time.monotonic() - self._last_cross_at) > 0.12
                                if cur_x <= min_x + 2.0 and dx < 0.0 and cooldown_ok:
                                    self._left_edge_push += -dx
                                    self._right_edge_push = 0.0
                                    if self._left_edge_push >= 4.0:
                                        y_r = max(
                                            0.02,
                                            min(
                                                0.98,
                                                (cur_y - min_y)
                                                / max(1.0, max_y - min_y),
                                            ),
                                        )
                                        with self._lock:
                                            self._left_edge_push = 0.0
                                            self._saved_pos = (min_x + 6.0, cur_y)
                                            self._last_cross_at = time.monotonic()
                                            self._set_captured_locked(
                                                True,
                                                enter_edge="right",
                                                y_ratio=y_r,
                                                save_cur_pos=False,
                                            )
                                        return None
                                elif cur_x >= max_x - 2.0 and dx > 0.0 and cooldown_ok:
                                    self._right_edge_push += dx
                                    self._left_edge_push = 0.0
                                    if self._right_edge_push >= 4.0:
                                        y_r = max(
                                            0.02,
                                            min(
                                                0.98,
                                                (cur_y - min_y)
                                                / max(1.0, max_y - min_y),
                                            ),
                                        )
                                        with self._lock:
                                            self._right_edge_push = 0.0
                                            self._saved_pos = (max_x - 6.0, cur_y)
                                            self._last_cross_at = time.monotonic()
                                            self._set_captured_locked(
                                                True,
                                                enter_edge="left",
                                                y_ratio=y_r,
                                                save_cur_pos=False,
                                            )
                                        return None
                                else:
                                    if cur_x > min_x + 10.0:
                                        self._left_edge_push = 0.0
                                    if cur_x < max_x - 10.0:
                                        self._right_edge_push = 0.0
                            return event

                        if event_type in (
                            q.kCGEventMouseMoved,
                            q.kCGEventLeftMouseDragged,
                            q.kCGEventRightMouseDragged,
                            q.kCGEventOtherMouseDragged,
                        ):
                            self.reassert_cursor_hidden()
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
                logger.info("Đã kích hoạt MacKvmBridge v3 (3 chế độ Chuột: Mac / Điện thoại / Nối 2 màn).")
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


@app.middleware("http")
async def _add_private_network_cors_header(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


_CACHED_WEB_BUNDLE: Optional[Dict[str, Any]] = None
_CACHED_WEB_MTIMES: str = ""


def _get_live_web_bundle() -> Dict[str, Any]:
    global _CACHED_WEB_BUNDLE, _CACHED_WEB_MTIMES
    idx_p = STATIC_DIR / "index.html"
    css_p = STATIC_DIR / "style.css"
    js_p = STATIC_DIR / "app.js"
    mkey = f"{idx_p.stat().st_mtime_ns}:{css_p.stat().st_mtime_ns}:{js_p.stat().st_mtime_ns}"
    if _CACHED_WEB_BUNDLE is not None and _CACHED_WEB_MTIMES == mkey:
        return _CACHED_WEB_BUNDLE
    idx_txt = idx_p.read_text(encoding="utf-8")
    css_txt = css_p.read_text(encoding="utf-8")
    js_txt = js_p.read_text(encoding="utf-8")
    m_ver = re.search(r'const\s+BUNDLED_WEB_VERSION\s*=\s*"([^"]+)"', js_txt)
    web_ver = m_ver.group(1) if m_ver else "2.2.4"
    etag = hashlib.sha1(
        (idx_txt + "\n" + css_txt + "\n" + js_txt).encode("utf-8")
    ).hexdigest()[:12]
    m_body = re.search(r"<body[^>]*>([\s\S]*?)</body>", idx_txt, flags=re.IGNORECASE)
    raw_body = m_body.group(1) if m_body else idx_txt
    body_html = re.sub(
        r'<script[^>]*src=["\'][^"\']*app\.js[^"\']*["\'][^>]*>\s*</script>',
        "",
        raw_body,
        flags=re.IGNORECASE,
    ).strip()
    _CACHED_WEB_MTIMES = mkey
    _CACHED_WEB_BUNDLE = {
        "ok": True,
        "web_version": web_ver,
        "etag": etag,
        "body_html": body_html,
        "style_css": css_txt,
        "app_js": js_txt,
    }
    return _CACHED_WEB_BUNDLE


@app.get("/web-manifest")
async def web_manifest() -> dict:
    b = _get_live_web_bundle()
    tag_name = "v2.1.4"
    try:
        lj = json.loads((BASE_DIR / "releases" / "latest.json").read_text(encoding="utf-8"))
        if isinstance(lj, dict) and lj.get("tag_name"):
            tag_name = str(lj["tag_name"])
    except Exception:
        pass
    return {
        "ok": True,
        "tag_name": tag_name,
        "web_version": b["web_version"],
        "etag": b["etag"],
    }


@app.get("/web-bundle")
async def web_bundle() -> dict:
    return _get_live_web_bundle()


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
        self.io_chan_id: Optional[int] = None
        self.rdpsnd_chan_id: Optional[int] = None
        self.drdynvc_chan_id: Optional[int] = None
        self.mcs_initiator: Optional[int] = None
        self.patched_client_info: bool = False
        self.got_rdpsnd_wave: bool = False

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
    def _extract_next_pdu(buf: bytearray, pre_mcs: bool = False) -> Optional[bytes]:
        blen = len(buf)
        if blen < 2:
            return None
        if (buf[0] & 0x03) == 0x03 and buf[0] == 0x03:
            if blen < 4:
                return None
            if buf[1] == 0x00:
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

        # Giai đoạn xác thực CredSSP / NLA (trước MCS Connect Initial): khung tin là ASN.1 DER TSRequest (0x30)
        if pre_mcs:
            if buf[0] == 0x30:
                b1 = buf[1]
                if (b1 & 0x80) == 0:
                    plen = 2 + b1
                else:
                    num_oct = b1 & 0x7F
                    if num_oct == 0 or num_oct > 4:
                        out = bytes(buf)
                        buf.clear()
                        return out
                    if blen < 2 + num_oct:
                        return None
                    body_len = int.from_bytes(buf[2 : 2 + num_oct], "big")
                    plen = 2 + num_oct + body_len
                if blen < plen:
                    return None
                out = bytes(buf[:plen])
                del buf[:plen]
                return out
            out = bytes(buf)
            buf.clear()
            return out

        # Sau MCS Connect Initial: chỉ còn Fast-Path PDU (action bits 0..1 == 0)
        if (buf[0] & 0x03) != 0x00:
            out = bytes(buf)
            buf.clear()
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
            if plen < 3:
                out = bytes(buf)
                buf.clear()
                return out
        if blen < plen:
            return None
        out = bytes(buf[:plen])
        del buf[:plen]
        return out

    def process_client_chunk(self, chunk: bytes) -> List[bytes]:
        self.client_buf.extend(chunk)
        out_pkts: List[bytes] = []
        while True:
            pkt = self._extract_next_pdu(
                self.client_buf, pre_mcs=(not self.cs_net_names)
            )
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
                    if not self.patched_client_info and (
                        self.io_chan_id is None or chan_id == self.io_chan_id
                    ):
                        sec_off = 15 if (pkt[13] & 0x80) != 0 else 14
                        if len(pkt) >= sec_off + 12:
                            sec_flags = struct.unpack_from("<H", pkt, sec_off)[0]
                            if (sec_flags & 0x0040) != 0 and (sec_flags & 0x0080) == 0:
                                old_flags = struct.unpack_from("<I", pkt, sec_off + 8)[0]
                                if (old_flags & 0x00000011) != 0:
                                    new_flags = (old_flags & ~0x00080000) | 0x00200000
                                    mp = bytearray(pkt)
                                    struct.pack_into("<I", mp, sec_off + 8, new_flags)
                                    pkt = bytes(mp)
                                    self.patched_client_info = True
            out_pkts.append(pkt)
        return out_pkts

    def process_server_chunk(self, chunk: bytes) -> List[bytes]:
        self.server_buf.extend(chunk)
        out_pkts: List[bytes] = []
        while True:
            pkt = self._extract_next_pdu(
                self.server_buf, pre_mcs=(not self.cs_net_names)
            )
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
                    self.io_chan_id = io_chan
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
            self.got_rdpsnd_wave = True
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
    _notify_wasapi_demand_changed()
    if audio_sess.spk_format:
        await ws.send_text(json.dumps({"type": "spk_format", **audio_sess.spk_format}))
    elif _PC_WASAPI_FMT:
        await ws.send_text(json.dumps({"type": "spk_format", **_PC_WASAPI_FMT}))
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
        _notify_wasapi_demand_changed()
        try:
            await ws.close()
        except Exception:
            pass


_ACTIVE_RDP_WS_COUNT: int = 0


@app.websocket("/rdp-ws")
async def rdp_cleanpath_ws(ws: WebSocket) -> None:
    global _ACTIVE_RDP_WS_COUNT
    subproto = None
    raw_proto = ws.headers.get("sec-websocket-protocol", "")
    if raw_proto:
        subproto = raw_proto.split(",")[0].strip() or None
    await ws.accept(subprotocol=subproto)
    _ACTIVE_RDP_WS_COUNT += 1

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
        try:
            raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass
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
        _ACTIVE_RDP_WS_COUNT = max(0, _ACTIVE_RDP_WS_COUNT - 1)
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


# ============================================================================
# CẦU NỐI ÂM THANH WASAPI LOOPBACK & CHẾ ĐỘ REMOTE PC SONG SONG (MAC + ĐIỆN THOẠI)
# ============================================================================
_PC_BRIDGE_WS: Optional[WebSocket] = None
_PC_WASAPI_CLIENTS: Set[asyncio.Queue] = set()
_PC_WASAPI_FMT: Dict[str, int] = {"rate": 44100, "channels": 2}
_PC_WASAPI_ACTIVE_WANT: bool = False
_RDP_PID_TCP_CACHE: Dict[int, Tuple[float, bool]] = {}
_RDP_LAUNCHER_TITLES = {
    "pcs",
    "workspaces",
    "devices",
    "apps",
    "microsoft remote desktop",
    "windows app",
    "preferences",
    "settings",
}


async def _push_pc_bridge_cmd() -> None:
    global _PC_WASAPI_ACTIVE_WANT
    want = (len(_PC_WASAPI_CLIENTS) > 0) or any(
        (s.audio_ws is not None and not s.got_rdpsnd_wave)
        for s in list(_RDP_AUDIO_SESSIONS.values())
    )
    _PC_WASAPI_ACTIVE_WANT = want
    ws = _PC_BRIDGE_WS
    if ws is not None:
        try:
            await ws.send_text(
                json.dumps({"cmd": "wasapi_start" if want else "wasapi_stop"})
            )
        except Exception:
            pass


def _notify_wasapi_demand_changed() -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_push_pc_bridge_cmd())
    except Exception:
        pass


@app.websocket("/pc-bridge-ws")
async def pc_bridge_ws(ws: WebSocket) -> None:
    global _PC_BRIDGE_WS, _PC_WASAPI_FMT
    await ws.accept()
    _PC_BRIDGE_WS = ws
    await _push_pc_bridge_cmd()
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            tdata = msg.get("text")
            if tdata:
                try:
                    j = json.loads(tdata)
                    if j.get("type") == "spk_format":
                        _PC_WASAPI_FMT = {
                            "rate": int(j.get("rate", 44100)),
                            "channels": int(j.get("channels", 2)),
                        }
                        fmt_str = json.dumps({"type": "spk_format", **_PC_WASAPI_FMT})
                        for q in list(_PC_WASAPI_CLIENTS):
                            try:
                                q.put_nowait(fmt_str)
                            except Exception:
                                pass
                        for s in list(_RDP_AUDIO_SESSIONS.values()):
                            if s.audio_ws is not None and not s.got_rdpsnd_wave:
                                s.enqueue_audio_ws(fmt_str)
                except Exception:
                    pass
                continue

            bdata = msg.get("bytes")
            if bdata and len(bdata) > 1 and bdata[0] == 0x01:
                for q in list(_PC_WASAPI_CLIENTS):
                    if q.qsize() > 60:
                        try:
                            q.get_nowait()
                        except Exception:
                            pass
                    try:
                        q.put_nowait(bdata)
                    except Exception:
                        pass
                any_fallback = False
                for s in list(_RDP_AUDIO_SESSIONS.values()):
                    if s.audio_ws is not None and not s.got_rdpsnd_wave:
                        any_fallback = True
                        s.enqueue_audio_ws(bdata)
                if not _PC_WASAPI_CLIENTS and not any_fallback and _PC_WASAPI_ACTIVE_WANT:
                    await _push_pc_bridge_cmd()
    except Exception:
        pass
    finally:
        if _PC_BRIDGE_WS is ws:
            _PC_BRIDGE_WS = None
        try:
            await ws.close()
        except Exception:
            pass


_ACTIVE_RDP_3389_PIDS: Set[int] = set()
_ACTIVE_RDP_PEER_IPS: Set[str] = set()
_RDP_WATCHER_STARTED: bool = False
_RDP_WATCHER_READY: bool = False
_RDP_EMPTY_STREAK: int = 0


def _refresh_active_rdp_pids_once() -> None:
    global _ACTIVE_RDP_3389_PIDS, _ACTIVE_RDP_PEER_IPS, _RDP_WATCHER_READY, _RDP_EMPTY_STREAK
    if not IS_MACOS:
        return
    my_pid = None
    try:
        import os

        my_pid = os.getpid()
    except Exception:
        pass
    found_pids: Set[int] = set()
    found_ips: Set[str] = set()
    cur_pid = 0
    for lsof_bin in ("/usr/sbin/lsof", "lsof"):
        try:
            out = subprocess.check_output(
                [lsof_bin, "-Pan", "-iTCP:3389", "-sTCP:ESTABLISHED", "-Fpn"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.8,
            )
            for line in out.splitlines():
                if line.startswith("p"):
                    try:
                        p_val = int(line[1:].strip())
                        cur_pid = p_val
                        if p_val > 0 and p_val != my_pid:
                            found_pids.add(p_val)
                    except ValueError:
                        cur_pid = 0
                elif line.startswith("n") and cur_pid > 0 and cur_pid != my_pid and "->" in line:
                    rhs = line.split("->", 1)[1].strip()
                    host_part = rhs.rsplit(":", 1)[0].strip("[]").strip()
                    if host_part and host_part not in ("127.0.0.1", "::1", "localhost"):
                        found_ips.add(host_part)
            break
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError:
            break
        except Exception:
            return
    if found_pids:
        _RDP_EMPTY_STREAK = 0
        _ACTIVE_RDP_3389_PIDS = found_pids
        if found_ips:
            _ACTIVE_RDP_PEER_IPS = found_ips
    else:
        # Chống tụt đột ngột khi lsof chậm/giật 1-2 nhịp trên macOS: chỉ xóa sau 3 nhịp trống liên tiếp (~2.7s)
        _RDP_EMPTY_STREAK += 1
        if _RDP_EMPTY_STREAK >= 3:
            _ACTIVE_RDP_3389_PIDS = set()
            _ACTIVE_RDP_PEER_IPS = set()
    _RDP_WATCHER_READY = True


def _ensure_rdp_socket_watcher() -> None:
    global _RDP_WATCHER_STARTED
    if _RDP_WATCHER_STARTED or not IS_MACOS:
        return
    _RDP_WATCHER_STARTED = True

    def _loop() -> None:
        while True:
            _refresh_active_rdp_pids_once()
            time.sleep(0.9)

    threading.Thread(target=_loop, daemon=True).start()


_ensure_rdp_socket_watcher()


def _pid_has_established_rdp_socket(pid: int) -> bool:
    if not IS_MACOS or pid <= 0:
        return False
    _ensure_rdp_socket_watcher()
    if not _RDP_WATCHER_READY:
        _refresh_active_rdp_pids_once()
    return pid in _ACTIVE_RDP_3389_PIDS


_EVKEY_SENSITIVE_VKS: Set[int] = set(list(range(0, 52)) + [53])


class MacRdpEvkeySyncBridge:
    """
    Đồng bộ 1:1 chế độ Tiếng Việt [V] / Tiếng Anh [E] giữa MacBook (EVKey / OpenKey / Bộ gõ Mac)
    và máy tính Windows từ xa (UniKeyNT) khi gõ trong Microsoft Remote Desktop / Windows App:
    1) Khi cửa sổ phiên Remote PC đang active trên Mac: chuyển thẳng phím gõ chữ nguyên bản tới
       tiến trình RDP qua `CGEventPostToPid` (bỏ qua hook `vk=0` gây lỗi font của EVKey trên Mac
       nhưng vẫn giữ nguyên biểu tượng [V] / [E] trên thanh Menu Bar của MacBook).
    2) Theo dõi thời gian thực trạng thái [V] / [E] (hoặc thoát EVKey) trên MacBook và đồng bộ tức thì
       sang `UniKeyHookSharedMem` trên Windows PC qua cổng `:5051/sync-ime`.
    """

    def __init__(self) -> None:
        self.available: bool = False
        self.active_rdp_pid: int = 0
        self.mac_vn_mode: bool = True
        self.ime_pid: int = 0
        self._last_rdp_pid: int = 0
        self._bypassed_vks: Set[int] = set()
        self._tap_loop_ref: Any = None
        self._tap_gen: int = 0
        self._last_pushed_vn: Optional[bool] = None
        self._last_push_at: float = 0.0
        self._ax_win_attr: Any = None
        self._ax_title_attr: Any = None
        self._ax_extras_attr: Any = None
        self._ax_children_attr: Any = None
        self._ax_value_attr: Any = None
        self._ax_desc_attr: Any = None
        self._carbon_lib: Any = None

        if IS_MACOS:
            self._init_ax_attrs()
            self._start_tap_worker()
            self._start_sync_watcher()

    def _init_ax_attrs(self) -> None:
        cf = injector._cf_lib
        if cf is None:
            return
        try:
            self._ax_win_attr = cf.CFStringCreateWithCString(None, b"AXFocusedWindow", 0x08000100)
            self._ax_title_attr = cf.CFStringCreateWithCString(None, b"AXTitle", 0x08000100)
            self._ax_extras_attr = cf.CFStringCreateWithCString(None, b"AXExtrasMenuBar", 0x08000100)
            self._ax_children_attr = cf.CFStringCreateWithCString(None, b"AXChildren", 0x08000100)
            self._ax_value_attr = cf.CFStringCreateWithCString(None, b"AXValue", 0x08000100)
            self._ax_desc_attr = cf.CFStringCreateWithCString(None, b"AXDescription", 0x08000100)
            ax = injector._ax_lib
            if ax is not None:
                ax.AXUIElementCreateApplication.restype = ctypes.c_void_p
                ax.AXUIElementCreateApplication.argtypes = [ctypes.c_int32]
        except Exception:
            pass
        try:
            carbon = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
            carbon.TISCopyCurrentKeyboardInputSource.restype = ctypes.c_void_p
            carbon.TISCopyCurrentKeyboardInputSource.argtypes = []
            carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
            carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self._carbon_lib = carbon
        except Exception:
            self._carbon_lib = None

    def _start_tap_worker(self) -> None:
        self._tap_gen += 1
        my_gen = self._tap_gen

        def _run_tap() -> None:
            try:
                import Quartz  # type: ignore

                q = Quartz
                mod_chord_mask = (
                    int(q.kCGEventFlagMaskCommand)
                    | int(q.kCGEventFlagMaskControl)
                    | int(q.kCGEventFlagMaskAlternate)
                )
                tap_holder: List[Any] = [None]

                def _key_cb(proxy, event_type, event, refcon):
                    try:
                        if event_type in (
                            q.kCGEventTapDisabledByTimeout,
                            q.kCGEventTapDisabledByUserInput,
                        ):
                            if tap_holder[0] is not None:
                                q.CGEventTapEnable(tap_holder[0], True)
                            return event

                        user_tag = int(
                            q.CGEventGetIntegerValueField(event, q.kCGEventSourceUserData)
                        )
                        if user_tag == 0x4D4B4232:
                            return event

                        vk = int(
                            q.CGEventGetIntegerValueField(event, q.kCGKeyboardEventKeycode)
                        )

                        if event_type == q.kCGEventKeyUp:
                            if vk in self._bypassed_vks:
                                self._bypassed_vks.discard(vk)
                                t_pid = self.active_rdp_pid or self._last_rdp_pid
                                if t_pid > 0:
                                    ev_cp = q.CGEventCreateCopy(event)
                                    if ev_cp is not None:
                                        q.CGEventSetIntegerValueField(
                                            ev_cp, q.kCGEventSourceUserData, 0x4D4B4232
                                        )
                                        q.CGEventPostToPid(t_pid, ev_cp)
                                        return None
                            return event

                        if event_type == q.kCGEventKeyDown:
                            t_pid = self.active_rdp_pid
                            if t_pid <= 0 or vk not in _EVKEY_SENSITIVE_VKS:
                                return event
                            flags = int(q.CGEventGetFlags(event))
                            if (flags & mod_chord_mask) != 0:
                                return event
                            ev_cp = q.CGEventCreateCopy(event)
                            if ev_cp is not None:
                                q.CGEventSetIntegerValueField(
                                    ev_cp, q.kCGEventSourceUserData, 0x4D4B4232
                                )
                                q.CGEventPostToPid(t_pid, ev_cp)
                                self._bypassed_vks.add(vk)
                                return None
                        return event
                    except Exception:
                        return event

                mask = (1 << int(q.kCGEventKeyDown)) | (1 << int(q.kCGEventKeyUp))
                tap = q.CGEventTapCreate(
                    q.kCGHIDEventTap,
                    q.kCGHeadInsertEventTap,
                    q.kCGEventTapOptionDefault,
                    mask,
                    _key_cb,
                    None,
                )
                if tap is None:
                    return
                tap_holder[0] = tap
                self.available = True
                src = q.CFMachPortCreateRunLoopSource(None, tap, 0)
                loop_ref = q.CFRunLoopGetCurrent()
                if my_gen == self._tap_gen:
                    self._tap_loop_ref = loop_ref
                q.CFRunLoopAddSource(loop_ref, src, q.kCFRunLoopCommonModes)
                q.CGEventTapEnable(tap, True)
                q.CFRunLoopRun()
                try:
                    q.CGEventTapEnable(tap, False)
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("MacRdpEvkeySyncBridge tap error: %s", exc)

        threading.Thread(target=_run_tap, daemon=True).start()

    def _reinsert_tap_ahead_of_ime(self) -> None:
        try:
            import Quartz  # type: ignore

            old_loop = self._tap_loop_ref
            self._tap_loop_ref = None
            if old_loop is not None:
                Quartz.CFRunLoopStop(old_loop)
        except Exception:
            pass
        self._start_tap_worker()

    def _cf_str_to_py(self, ptr_val: int) -> str:
        if not ptr_val or injector._objc is None:
            return ""
        try:
            return str(injector._objc.objc_object(c_void_p=ptr_val) or "")
        except Exception:
            return ""

    def _detect_frontmost_rdp_pid(self) -> int:
        ax = injector._ax_lib
        cf = injector._cf_lib
        proc = injector._proc_lib
        if (
            ax is None
            or cf is None
            or proc is None
            or not injector._ax_sys_wide
            or not injector._ax_focused_attr
        ):
            return 0
        app_ref = ctypes.c_void_p()
        err = ax.AXUIElementCopyAttributeValue(
            injector._ax_sys_wide, injector._ax_focused_attr, ctypes.byref(app_ref)
        )
        if err != 0 or not app_ref.value:
            return 0
        try:
            pid_c = ctypes.c_int32(0)
            if ax.AXUIElementGetPid(app_ref.value, ctypes.byref(pid_c)) != 0 or pid_c.value <= 0:
                return 0
            pid = int(pid_c.value)
            buf = ctypes.create_string_buffer(4096)
            n = proc.proc_pidpath(pid, buf, 4096)
            app_path = buf.value.decode("utf-8", errors="ignore").lower() if n > 0 else ""
            if not (
                "microsoft remote desktop" in app_path
                or "windows app" in app_path
                or "com.microsoft.rdc" in app_path
            ):
                return 0
            if not _pid_has_established_rdp_socket(pid):
                return 0
            if self._ax_win_attr and self._ax_title_attr:
                win_ref = ctypes.c_void_p()
                if (
                    ax.AXUIElementCopyAttributeValue(
                        app_ref.value, self._ax_win_attr, ctypes.byref(win_ref)
                    )
                    == 0
                    and win_ref.value
                ):
                    try:
                        title_ref = ctypes.c_void_p()
                        if (
                            ax.AXUIElementCopyAttributeValue(
                                win_ref.value, self._ax_title_attr, ctypes.byref(title_ref)
                            )
                            == 0
                            and title_ref.value
                        ):
                            try:
                                w_title = self._cf_str_to_py(title_ref.value).strip().lower()
                                if w_title and w_title in _RDP_LAUNCHER_TITLES:
                                    return 0
                            finally:
                                cf.CFRelease(title_ref.value)
                    finally:
                        cf.CFRelease(win_ref.value)
            return pid
        except Exception:
            return 0
        finally:
            cf.CFRelease(app_ref.value)

    def _read_ime_ax_status(self, ime_pid: int) -> Optional[bool]:
        ax = injector._ax_lib
        cf = injector._cf_lib
        if (
            ax is None
            or cf is None
            or injector._objc is None
            or not self._ax_extras_attr
            or not self._ax_children_attr
        ):
            return None
        app_ax = ax.AXUIElementCreateApplication(ime_pid)
        if not app_ax:
            return None
        try:
            bar_ref = ctypes.c_void_p()
            if (
                ax.AXUIElementCopyAttributeValue(
                    app_ax, self._ax_extras_attr, ctypes.byref(bar_ref)
                )
                != 0
                or not bar_ref.value
            ):
                return None
            try:
                return self._scan_ax_node_for_ve(bar_ref.value, 0)
            finally:
                cf.CFRelease(bar_ref.value)
        except Exception:
            return None
        finally:
            cf.CFRelease(app_ax)

    def _scan_ax_node_for_ve(self, elem_ptr: int, depth: int) -> Optional[bool]:
        if depth > 3 or not elem_ptr:
            return None
        ax = injector._ax_lib
        cf = injector._cf_lib
        for attr in (self._ax_title_attr, self._ax_value_attr, self._ax_desc_attr):
            if not attr:
                continue
            val_ref = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(elem_ptr, attr, ctypes.byref(val_ref)) == 0 and val_ref.value:
                try:
                    txt = self._cf_str_to_py(val_ref.value).strip()
                    low = txt.lower()
                    if txt in ("V", "VN", "VI") or "tiếng việt" in low or "vietnamese" in low:
                        return True
                    if txt in ("E", "EN") or "tiếng anh" in low or "english" in low:
                        return False
                finally:
                    cf.CFRelease(val_ref.value)
        ch_ref = ctypes.c_void_p()
        if (
            ax.AXUIElementCopyAttributeValue(elem_ptr, self._ax_children_attr, ctypes.byref(ch_ref))
            == 0
            and ch_ref.value
        ):
            try:
                arr = injector._objc.objc_object(c_void_p=ch_ref.value)
                for item in arr:
                    res = self._scan_ax_node_for_ve(item.__c_void_p__(), depth + 1)
                    if res is not None:
                        return res
            except Exception:
                pass
            finally:
                cf.CFRelease(ch_ref.value)
        return None

    def _classify_ime_status_icon(self, ime_pid: int) -> Optional[bool]:
        q = lens_capturer._quartz
        objc_mod = lens_capturer._objc
        if q is None or objc_mod is None:
            return None
        try:
            with objc_mod.autorelease_pool():
                win_list = q.CGWindowListCopyWindowInfo(
                    q.kCGWindowListOptionAll, q.kCGNullWindowID
                )
                if not win_list:
                    return None
                target_wid = 0
                for w in win_list:
                    if int(w.get("kCGWindowOwnerPID", 0) or 0) != ime_pid:
                        continue
                    layer = int(w.get("kCGWindowLayer", 0) or 0)
                    if layer < 20:
                        continue
                    b = w.get("kCGWindowBounds") or {}
                    ww = float(b.get("Width", 0.0) or 0.0)
                    wh = float(b.get("Height", 0.0) or 0.0)
                    if 12.0 <= ww <= 96.0 and 12.0 <= wh <= 52.0:
                        target_wid = int(w.get("kCGWindowNumber", 0) or 0)
                        break
                if target_wid <= 0:
                    return None

                cg_img = q.CGWindowListCreateImage(
                    q.CGRectNull,
                    q.kCGWindowListOptionIncludingWindow,
                    target_wid,
                    q.kCGWindowImageBoundsIgnoreFraming,
                )
                if cg_img is None:
                    return None
                iw = int(q.CGImageGetWidth(cg_img))
                ih = int(q.CGImageGetHeight(cg_img))
                bpr = int(q.CGImageGetBytesPerRow(cg_img))
                bpp = int(q.CGImageGetBitsPerPixel(cg_img)) // 8
                if iw < 12 or ih < 12 or bpp < 4:
                    return None
                prov = q.CGImageGetDataProvider(cg_img)
                if prov is None:
                    return None
                cf_data = q.CGDataProviderCopyData(prov)
                if cf_data is None:
                    return None
                buf = bytes(cf_data)

                x0, x1 = int(iw * 0.16), max(int(iw * 0.16) + 4, int(iw * 0.84))
                y0, y1 = int(ih * 0.14), max(int(ih * 0.14) + 4, int(ih * 0.86))
                alphas: List[int] = []
                lums: List[int] = []
                for yy in range(y0, y1):
                    r_off = yy * bpr
                    for xx in range(x0, x1):
                        p = r_off + xx * bpp
                        if p + 3 < len(buf):
                            alphas.append(buf[p + 3])
                            lums.append(buf[p] + buf[p + 1] + buf[p + 2])
                if not alphas:
                    return None
                alphas_sorted = sorted(alphas)
                med_alpha = alphas_sorted[len(alphas_sorted) // 2]

                fg_coords: List[Tuple[int, int]] = []
                if med_alpha < 55:
                    for yy in range(y0, y1):
                        r_off = yy * bpr
                        for xx in range(x0, x1):
                            p = r_off + xx * bpp
                            if p + 3 < len(buf) and buf[p + 3] >= 105:
                                fg_coords.append((xx, yy))
                else:
                    lums_sorted = sorted(lums)
                    med_lum = lums_sorted[len(lums_sorted) // 2]
                    hi_lum = lums_sorted[-1]
                    lo_lum = lums_sorted[0]
                    if (hi_lum - med_lum) >= (med_lum - lo_lum):
                        contrast = hi_lum - med_lum
                        if contrast < 85:
                            return None
                        thresh = med_lum + int(contrast * 0.56)
                        for yy in range(y0, y1):
                            r_off = yy * bpr
                            for xx in range(x0, x1):
                                p = r_off + xx * bpp
                                if p + 3 < len(buf) and (buf[p] + buf[p + 1] + buf[p + 2]) >= thresh:
                                    fg_coords.append((xx, yy))
                    else:
                        contrast = med_lum - lo_lum
                        if contrast < 85:
                            return None
                        thresh = med_lum - int(contrast * 0.56)
                        for yy in range(y0, y1):
                            r_off = yy * bpr
                            for xx in range(x0, x1):
                                p = r_off + xx * bpp
                                if p + 3 < len(buf) and (buf[p] + buf[p + 1] + buf[p + 2]) <= thresh:
                                    fg_coords.append((xx, yy))

                if len(fg_coords) < 12:
                    return None
                gy0 = min(pt[1] for pt in fg_coords)
                gy1 = max(pt[1] for pt in fg_coords)
                gx0 = min(pt[0] for pt in fg_coords)
                gx1 = max(pt[0] for pt in fg_coords)
                gh = gy1 - gy0 + 1
                gw = gx1 - gx0 + 1
                if gh < 6 or gw < 4:
                    return None

                rows_map: Dict[int, List[int]] = {}
                for xx, yy in fg_coords:
                    rows_map.setdefault(yy, []).append(xx)

                top_y_start = gy0 + int(gh * 0.10)
                top_y_end = max(top_y_start + 1, gy0 + int(gh * 0.34))
                top_spans = [
                    max(rows_map[ry]) - min(rows_map[ry]) + 1
                    for ry in range(top_y_start, top_y_end + 1)
                    if ry in rows_map
                ]

                bot_y_start = gy0 + int(gh * 0.76)
                bot_y_end = max(bot_y_start + 1, gy0 + int(gh * 0.94))
                bot_spans = [
                    max(rows_map[ry]) - min(rows_map[ry]) + 1
                    for ry in range(bot_y_start, bot_y_end + 1)
                    if ry in rows_map
                ]

                if not top_spans or not bot_spans:
                    return None
                top_w = float(max(top_spans))
                bot_w = sum(bot_spans) / float(len(bot_spans))
                ratio = bot_w / max(1.0, top_w)
                if ratio < 0.60:
                    return True
                if ratio > 0.70:
                    return False
                return None
        except Exception:
            return None

    def _read_ime_plist_mode(self, bundle_id: str) -> Optional[bool]:
        if not bundle_id:
            return None
        try:
            plist_path = Path.home() / "Library" / "Preferences" / f"{bundle_id}.plist"
            if not plist_path.exists():
                return None
            data = plistlib.loads(plist_path.read_bytes())
            if isinstance(data, dict):
                for key in ("vLanguage", "Language", "Vietnamese", "InputLanguage"):
                    if key in data:
                        return bool(int(data[key]))
        except Exception:
            pass
        return None

    def _read_macos_native_vn_input(self) -> bool:
        if self._carbon_lib is None or injector._objc is None or injector._cf_lib is None:
            return False
        src_ptr = self._carbon_lib.TISCopyCurrentKeyboardInputSource()
        if not src_ptr:
            return False
        try:
            k_id = ctypes.c_void_p.in_dll(self._carbon_lib, "kTISPropertyInputSourceID")
            prop = self._carbon_lib.TISGetInputSourceProperty(src_ptr, k_id)
            src_id = self._cf_str_to_py(prop).lower()
            return any(k in src_id for k in ("vietnamese", "telex", "vni", "viqr"))
        except Exception:
            return False
        finally:
            injector._cf_lib.CFRelease(src_ptr)

    def _detect_mac_ime_state(self) -> Tuple[int, bool]:
        objc_mod = lens_capturer._objc
        if objc_mod is None:
            return (0, self._read_macos_native_vn_input())
        ime_pid = 0
        ime_bundle = ""
        try:
            import AppKit  # type: ignore

            with objc_mod.autorelease_pool():
                apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications()
                for app_item in apps:
                    bid = str(app_item.bundleIdentifier() or "")
                    name = str(app_item.localizedName() or "")
                    low = f"{bid} {name}".lower()
                    if "evkey" in low or "openkey" in low:
                        ime_pid = int(app_item.processIdentifier())
                        ime_bundle = bid or "com.lamquangminh.evkey"
                        break
        except Exception:
            pass

        if ime_pid <= 0:
            return (0, self._read_macos_native_vn_input())

        mode = self._read_ime_ax_status(ime_pid)
        if mode is None:
            mode = self._classify_ime_status_icon(ime_pid)
        if mode is None:
            mode = self._read_ime_plist_mode(ime_bundle)
        if mode is None:
            mode = self.mac_vn_mode
        return (ime_pid, bool(mode))

    def _push_vn_to_pc(self, want_vn: bool) -> None:
        targets: List[str] = []
        for ip in sorted(_ACTIVE_RDP_PEER_IPS):
            if ip not in targets:
                targets.append(ip)
        if "192.168.52.230" not in targets:
            targets.append("192.168.52.230")

        vn_flag = 1 if want_vn else 0
        pushed_ok = False
        for ip in targets:
            url = f"http://{ip}:5051/sync-ime?vn={vn_flag}"
            try:
                with urllib.request.urlopen(url, timeout=0.55) as resp:
                    if resp.status == 200:
                        pushed_ok = True
                        break
            except Exception:
                continue
        if pushed_ok:
            self._last_pushed_vn = want_vn
            self._last_push_at = time.monotonic()

    def _start_sync_watcher(self) -> None:
        def _watcher() -> None:
            last_ime_check_at = 0.0
            prev_ime_pid = 0
            while True:
                time.sleep(0.09)
                try:
                    now = time.monotonic()
                    prev_rdp = self.active_rdp_pid
                    cur_rdp = self._detect_frontmost_rdp_pid()
                    self.active_rdp_pid = cur_rdp
                    if cur_rdp > 0:
                        self._last_rdp_pid = cur_rdp

                    has_any_rdp = cur_rdp > 0 or bool(_ACTIVE_RDP_3389_PIDS)
                    ime_interval = 0.16 if has_any_rdp else 0.90
                    if (cur_rdp > 0 and prev_rdp == 0) or (now - last_ime_check_at >= ime_interval):
                        last_ime_check_at = now
                        ime_pid, want_vn = self._detect_mac_ime_state()
                        self.ime_pid = ime_pid
                        self.mac_vn_mode = want_vn

                        if ime_pid > 0 and ime_pid != prev_ime_pid:
                            prev_ime_pid = ime_pid
                            time.sleep(0.35)
                            self._reinsert_tap_ahead_of_ime()
                        elif ime_pid == 0:
                            prev_ime_pid = 0

                        if has_any_rdp:
                            just_focused = cur_rdp > 0 and prev_rdp == 0
                            vn_changed = want_vn != self._last_pushed_vn
                            heartbeat_due = cur_rdp > 0 and (now - self._last_push_at >= 2.5)
                            if just_focused or vn_changed or heartbeat_due:
                                self._push_vn_to_pc(want_vn)
                except Exception:
                    pass

        threading.Thread(target=_watcher, daemon=True).start()


rdp_evkey_sync = MacRdpEvkeySyncBridge()


def find_mac_rdp_window() -> Optional[Dict[str, Any]]:
    if not IS_MACOS or lens_capturer._quartz is None or lens_capturer._objc is None:
        return None
    q = lens_capturer._quartz
    try:
        with lens_capturer._objc.autorelease_pool():
            win_list = q.CGWindowListCopyWindowInfo(
                q.kCGWindowListOptionAll, q.kCGNullWindowID
            )
            if not win_list:
                return None

            best_score: Optional[Tuple[int, int, float]] = None
            best_win: Optional[Dict[str, Any]] = None

            for w in win_list:
                if int(w.get("kCGWindowLayer", -1)) != 0:
                    continue
                owner = str(w.get("kCGWindowOwnerName", "") or "")
                low_owner = owner.lower()
                if not (
                    "microsoft remote desktop" in low_owner
                    or "windows app" in low_owner
                    or "com.microsoft.rdc" in low_owner
                ):
                    continue
                alpha = float(w.get("kCGWindowAlpha", 1.0) or 0.0)
                if alpha <= 0.05:
                    continue
                bounds = w.get("kCGWindowBounds")
                if not bounds:
                    continue
                wx = float(bounds.get("X", 0.0))
                wy = float(bounds.get("Y", 0.0))
                ww = float(bounds.get("Width", 0.0))
                wh = float(bounds.get("Height", 0.0))
                if ww < 480.0 or wh < 320.0:
                    continue
                pid = int(w.get("kCGWindowOwnerPID", 0) or 0)
                if pid <= 0:
                    continue
                w_name = str(w.get("kCGWindowName", "") or "").strip()
                low_name = w_name.lower()
                is_launcher = (
                    (low_name in _RDP_LAUNCHER_TITLES or low_name in ("edit pc", "settings", "preferences", "add pc"))
                    if low_name
                    else False
                )
                has_tcp = _pid_has_established_rdp_socket(pid)
                # Nếu lsof giật 1 nhịp chưa kịp bắt TCP :3389, vẫn nhận cửa sổ phiên lớn có tên thật (VD: "PC Hieu")
                if not has_tcp and (is_launcher or not w_name or ww < 600.0 or wh < 360.0):
                    continue
                on_screen = bool(w.get("kCGWindowIsOnscreen", False))
                score = (
                    1 if has_tcp else 0,
                    0 if is_launcher else 1,
                    1 if on_screen else 0,
                    ww * wh,
                )
                if best_score is None or score > best_score:
                    best_score = score
                    best_win = {
                        "win_id": int(w.get("kCGWindowNumber", 0)),
                        "pid": pid,
                        "owner": owner,
                        "title": w_name,
                        "win_x": wx,
                        "win_y": wy,
                        "win_w": ww,
                        "win_h": wh,
                    }

            if best_win is None or best_win["win_id"] <= 0:
                return None

            wx = best_win["win_x"]
            wy = best_win["win_y"]
            ww = best_win["win_w"]
            wh = best_win["win_h"]
            mid_x = wx + ww * 0.5
            mid_y = wy + wh * 0.5

            main_id = q.CGMainDisplayID()
            mb = q.CGDisplayBounds(main_id)
            mon_x, mon_y = float(mb.origin.x), float(mb.origin.y)
            mon_w, mon_h = float(mb.size.width), float(mb.size.height)
            try:
                err, active_ids, count = q.CGGetActiveDisplayList(8, None, None)
                if err == 0 and count > 0:
                    for did in active_ids[:count]:
                        b = q.CGDisplayBounds(did)
                        bx, by = float(b.origin.x), float(b.origin.y)
                        bw, bh = float(b.size.width), float(b.size.height)
                        if bx <= mid_x < bx + bw and by <= mid_y < by + bh:
                            mon_x, mon_y, mon_w, mon_h = bx, by, bw, bh
                            break
            except Exception:
                pass

            is_fullscreen = (wh >= mon_h - 48.0 and wy <= mon_y + 48.0) or (
                ww >= mon_w - 8.0 and wh >= mon_h - 80.0
            )
            titlebar_h = 0.0 if (is_fullscreen or wh <= 420.0) else 28.0
            best_win["fullscreen"] = is_fullscreen
            best_win["content_x"] = wx
            best_win["content_y"] = wy + titlebar_h
            best_win["content_w"] = ww
            best_win["content_h"] = max(240.0, wh - titlebar_h)
            return best_win
    except Exception:
        return None


def _capture_mac_rdp_jpeg_packet(win_info: Dict[str, Any]) -> Optional[bytes]:
    if (
        lens_capturer._quartz is None
        or lens_capturer._foundation is None
        or lens_capturer._objc is None
    ):
        return None
    q = lens_capturer._quartz
    fd = lens_capturer._foundation
    try:
        with lens_capturer._objc.autorelease_pool():
            win_id = int(win_info["win_id"])
            cx = float(win_info["content_x"])
            cy = float(win_info["content_y"])
            cw = float(win_info["content_w"])
            ch = float(win_info["content_h"])

            incl_win = getattr(q, "kCGWindowListOptionIncludingWindow", 8)
            ignore_framing = getattr(q, "kCGWindowImageBoundsIgnoreFraming", 1)
            # Chụp thẳng độ phân giải gốc Retina 2x (BestResolution) để chữ sắc nét căng mịn trên màn OLED điện thoại
            img_opts = ignore_framing

            rect = q.CGRectMake(cx, cy, cw, ch)
            cg_img = q.CGWindowListCreateImage(rect, incl_win, win_id, img_opts)
            if (
                cg_img is None
                or int(q.CGImageGetWidth(cg_img)) < 64
                or int(q.CGImageGetHeight(cg_img)) < 64
            ):
                cg_img = q.CGWindowListCreateImage(
                    q.CGRectNull, incl_win, win_id, img_opts
                )
            if cg_img is None:
                return None

            img_w = int(q.CGImageGetWidth(cg_img))
            img_h = int(q.CGImageGetHeight(cg_img))
            if img_w < 32 or img_h < 32:
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
            max_px_key = getattr(
                q,
                "kCGImageDestinationImageMaxPixelSize",
                "kCGImageDestinationImageMaxPixelSize",
            )
            # Giữ nguyên 100% độ phân giải Retina gốc (3024x1888, không hạ xuống 2400) + JPEG 0.92 nét căng không vỡ màu chữ
            enc_opts = {qual_key: 0.92}
            out_w, out_h = img_w, img_h
            if img_w > 3400:
                enc_opts[max_px_key] = 3200
                out_w = 3200
                out_h = max(1, int(round(img_h * 3200.0 / img_w)))
            q.CGImageDestinationAddImage(dest, cg_img, enc_opts)
            if not q.CGImageDestinationFinalize(dest):
                return None
            jpeg_bytes = bytes(mutable_data)
            if not jpeg_bytes:
                return None
            return (
                b"\x10"
                + struct.pack(">HH", min(65535, out_w), min(65535, out_h))
                + jpeg_bytes
            )
    except Exception:
        return None


def _activate_mac_pid_if_needed(pid: int) -> None:
    if not IS_MACOS or pid <= 0:
        return
    try:
        import AppKit  # type: ignore

        ws_shared = AppKit.NSWorkspace.sharedWorkspace()
        front = ws_shared.frontmostApplication()
        if front is not None and int(front.processIdentifier()) == pid:
            return
        app_obj = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app_obj is not None:
            app_obj.activateWithOptions_(2)
            time.sleep(0.012)
    except Exception:
        pass


def _dispatch_parallel_rdp_input(
    win_info: Dict[str, Any], data: Dict[str, Any], state: Dict[str, Any]
) -> None:
    if not IS_MACOS or injector._quartz is None:
        return
    q = injector._quartz
    mtype = str(data.get("type", ""))
    pid = int(win_info.get("pid", 0))
    cx = float(win_info["content_x"])
    cy = float(win_info["content_y"])
    cw = float(win_info["content_w"])
    ch = float(win_info["content_h"])

    if mtype in ("ptr_move", "ptr_down", "ptr_up", "ptr_wheel"):
        rx = max(0.0, min(1.0, float(data.get("rx", 0.5))))
        ry = max(0.0, min(1.0, float(data.get("ry", 0.5))))
        sx = cx + rx * cw
        sy = cy + ry * ch
        prev_x = float(state.get("last_sx", sx))
        prev_y = float(state.get("last_sy", sy))
        dx = sx - prev_x
        dy = sy - prev_y
        state["last_sx"] = sx
        state["last_sy"] = sy
        injector._mouse_x = sx
        injector._mouse_y = sy

        kvm_on_phone = bool(kvm_bridge.captured)
        if mtype == "ptr_down":
            if kvm_on_phone:
                kvm_bridge.reassert_cursor_hidden(pin=False, force=True)
            _activate_mac_pid_if_needed(pid)
            btn_idx = int(data.get("btn", 0))
            cnt = max(1, int(data.get("count", 1)))
            state["held_btn"] = btn_idx
            if not kvm_on_phone:
                q.CGWarpMouseCursorPosition((sx, sy))
            if btn_idx == 2:
                ev_t, cg_b = q.kCGEventRightMouseDown, q.kCGMouseButtonRight
            elif btn_idx == 1:
                ev_t, cg_b = q.kCGEventOtherMouseDown, q.kCGMouseButtonCenter
            else:
                ev_t, cg_b = q.kCGEventLeftMouseDown, q.kCGMouseButtonLeft
            ev = q.CGEventCreateMouseEvent(injector._event_source, ev_t, (sx, sy), cg_b)
            q.CGEventSetIntegerValueField(ev, q.kCGMouseEventClickState, cnt)
            q.CGEventSetIntegerValueField(ev, q.kCGEventSourceUserData, 0x4D4B4231)
            q.CGEventPost(q.kCGHIDEventTap, ev)
            if kvm_on_phone:
                kvm_bridge.reassert_cursor_hidden(force=True)
        elif mtype == "ptr_up":
            btn_idx = int(data.get("btn", 0))
            cnt = max(1, int(data.get("count", 1)))
            if state.get("held_btn") == btn_idx:
                state["held_btn"] = -1
            if btn_idx == 2:
                ev_t, cg_b = q.kCGEventRightMouseUp, q.kCGMouseButtonRight
            elif btn_idx == 1:
                ev_t, cg_b = q.kCGEventOtherMouseUp, q.kCGMouseButtonCenter
            else:
                ev_t, cg_b = q.kCGEventLeftMouseUp, q.kCGMouseButtonLeft
            ev = q.CGEventCreateMouseEvent(injector._event_source, ev_t, (sx, sy), cg_b)
            q.CGEventSetIntegerValueField(ev, q.kCGMouseEventClickState, cnt)
            q.CGEventSetIntegerValueField(ev, q.kCGEventSourceUserData, 0x4D4B4231)
            q.CGEventPost(q.kCGHIDEventTap, ev)
            if kvm_on_phone:
                kvm_bridge.reassert_cursor_hidden(pin=(int(state.get("held_btn", -1)) < 0), force=True)
        elif mtype == "ptr_move":
            held = int(state.get("held_btn", -1))
            # Khi chuột đã di sang màn hình Điện thoại (kvm_on_phone=True): KHÔNG gọi CGWarpMouseCursorPosition trên MacBook
            # để con trỏ MacBook tuyệt đối không bị kéo hiện lại trên màn hình MacBook!
            if not kvm_on_phone:
                q.CGWarpMouseCursorPosition((sx, sy))
            if held == 0:
                ev_t, cg_b = q.kCGEventLeftMouseDragged, q.kCGMouseButtonLeft
            elif held == 2:
                ev_t, cg_b = q.kCGEventRightMouseDragged, q.kCGMouseButtonRight
            elif held == 1:
                ev_t, cg_b = q.kCGEventOtherMouseDragged, q.kCGMouseButtonCenter
            else:
                ev_t, cg_b = q.kCGEventMouseMoved, q.kCGMouseButtonLeft
            ev = q.CGEventCreateMouseEvent(injector._event_source, ev_t, (sx, sy), cg_b)
            if held >= 0:
                q.CGEventSetIntegerValueField(ev, q.kCGMouseEventClickState, 1)
            q.CGEventSetIntegerValueField(ev, q.kCGMouseEventDeltaX, int(round(dx)))
            q.CGEventSetIntegerValueField(ev, q.kCGMouseEventDeltaY, int(round(dy)))
            q.CGEventSetIntegerValueField(ev, q.kCGEventSourceUserData, 0x4D4B4231)
            q.CGEventPost(q.kCGHIDEventTap, ev)
            if kvm_on_phone:
                kvm_bridge.reassert_cursor_hidden(force=True)
        elif mtype == "ptr_wheel":
            if kvm_on_phone:
                kvm_bridge.reassert_cursor_hidden(pin=False, force=True)
            _activate_mac_pid_if_needed(pid)
            if not kvm_on_phone:
                q.CGWarpMouseCursorPosition((sx, sy))
            phase = int(data.get("phase", 2) or 2)
            now_w = time.monotonic()
            last_wx = float(state.get("last_wheel_sx", -9999.0))
            last_wy = float(state.get("last_wheel_sy", -9999.0))
            last_wt = float(state.get("last_wheel_ev_at", 0.0))
            if phase == 1 or (now_w - last_wt) > 0.12 or abs(sx - last_wx) > 2.0 or abs(sy - last_wy) > 2.0:
                state["last_wheel_sx"] = sx
                state["last_wheel_sy"] = sy
                mv = q.CGEventCreateMouseEvent(
                    injector._event_source, q.kCGEventMouseMoved, (sx, sy), q.kCGMouseButtonLeft
                )
                q.CGEventSetIntegerValueField(mv, q.kCGEventSourceUserData, 0x4D4B4231)
                q.CGEventPost(q.kCGHIDEventTap, mv)
            state["last_wheel_ev_at"] = now_w

            acc_x = float(state.get("wheel_rem_x", 0.0)) + float(data.get("dx", 0.0))
            acc_y = float(state.get("wheel_rem_y", 0.0)) + float(data.get("dy", 0.0))
            wx_d = int(round(acc_x)) if abs(acc_x) >= 1.0 else 0
            wy_d = int(round(acc_y)) if abs(acc_y) >= 1.0 else 0
            state["wheel_rem_x"] = acc_x - wx_d
            state["wheel_rem_y"] = acc_y - wy_d
            if wx_d == 0 and wy_d == 0 and phase != 4:
                if kvm_on_phone:
                    kvm_bridge.reassert_cursor_hidden(pin=(int(state.get("held_btn", -1)) < 0), force=True)
                return

            ev = q.CGEventCreateScrollWheelEvent(
                injector._event_source, q.kCGScrollEventUnitPixel, 2, wy_d, wx_d
            )
            # Đầy đủ chữ ký Apple Magic Trackpad (IsContinuous=88, PointDelta=96/97, ScrollPhase=99, MomentumPhase=123)
            # để Mos (PID 775) nhận diện đúng là Trackpad thật (không triệt tiêu xung nhỏ) và Microsoft Remote Desktop cuộn mượt tức thì!
            q.CGEventSetIntegerValueField(ev, 88, 1)
            q.CGEventSetIntegerValueField(ev, 96, wy_d)
            q.CGEventSetIntegerValueField(ev, 97, wx_d)
            if phase == 8:
                q.CGEventSetIntegerValueField(ev, 99, 0)
                q.CGEventSetIntegerValueField(ev, 123, 2)
            else:
                q.CGEventSetIntegerValueField(ev, 99, phase if phase in (1, 2, 4) else 2)
                q.CGEventSetIntegerValueField(ev, 123, 0)
            try:
                q.CGEventSetLocation(ev, (sx, sy))
            except Exception:
                pass
            q.CGEventSetIntegerValueField(ev, q.kCGEventSourceUserData, 0x4D4B4231)
            # Post qua kCGAnnotatedSessionEventTap để đi sau CGEventTap của Mos (PID 775), tránh bị Mos đảo ngược chiều cuộn hoặc nuốt xung nhỏ!
            q.CGEventPost(getattr(q, "kCGAnnotatedSessionEventTap", q.kCGSessionEventTap), ev)
            if kvm_on_phone:
                kvm_bridge.reassert_cursor_hidden(pin=(int(state.get("held_btn", -1)) < 0), force=True)
        return

    if mtype == "key_tap":
        _activate_mac_pid_if_needed(pid)
        key = str(data.get("key", ""))
        raw_mods = data.get("mods")
        t_mods = [str(m) for m in raw_mods] if isinstance(raw_mods, list) else None
        injector.press_key(key, t_mods)
    elif mtype == "combo":
        _activate_mac_pid_if_needed(pid)
        keys = data.get("keys")
        if isinstance(keys, list):
            injector.press_combo([str(k) for k in keys])
    elif mtype == "unicode_text":
        _activate_mac_pid_if_needed(pid)
        txt = str(data.get("text", ""))
        if txt:
            injector._quartz_post_unicode(txt)


@app.get("/rdp-mode-check")
async def rdp_mode_check() -> dict:
    def _probe():
        win = find_mac_rdp_window()
        if win is None and IS_MACOS:
            _refresh_active_rdp_pids_once()
            win = find_mac_rdp_window()
        return win

    win = await asyncio.to_thread(_probe)
    return {
        "ok": True,
        "parallel_available": win is not None,
        "pc_bridge_connected": _PC_BRIDGE_WS is not None,
        "window": win,
    }


@app.websocket("/rdp-parallel-ws")
async def rdp_parallel_ws(ws: WebSocket) -> None:
    global _ACTIVE_RDP_WS_COUNT
    await ws.accept()
    _ACTIVE_RDP_WS_COUNT += 1
    audio_q: asyncio.Queue = asyncio.Queue()
    _PC_WASAPI_CLIENTS.add(audio_q)
    await _push_pc_bridge_cmd()

    if _PC_WASAPI_FMT:
        try:
            await ws.send_text(json.dumps({"type": "spk_format", **_PC_WASAPI_FMT}))
        except Exception:
            pass

    running = True
    cur_win: Dict[str, Any] = {}
    input_state: Dict[str, Any] = {"held_btn": -1}

    async def _audio_sender() -> None:
        try:
            while running:
                item = await audio_q.get()
                if item is None:
                    break
                if isinstance(item, bytes):
                    await ws.send_bytes(item)
                elif isinstance(item, str):
                    await ws.send_text(item)
        except Exception:
            pass

    async def _video_sender() -> None:
        nonlocal cur_win
        missing_since: Optional[float] = None
        last_win_refresh = 0.0
        prev_pkt: Optional[bytes] = None
        last_sent_at = 0.0
        try:
            while running:
                now = time.monotonic()
                if not cur_win or (now - last_win_refresh) >= 0.45:
                    last_win_refresh = now
                    found = await asyncio.to_thread(find_mac_rdp_window)
                    if found is not None:
                        cur_win = found
                        missing_since = None
                    else:
                        if missing_since is None:
                            missing_since = now
                        elif (now - missing_since) >= 8.0:
                            await ws.send_text('{"type":"parallel_ended"}')
                            break
                        await asyncio.sleep(0.15)
                        continue

                pkt = await asyncio.to_thread(_capture_mac_rdp_jpeg_packet, cur_win)
                if pkt is not None:
                    if pkt != prev_pkt or (now - last_sent_at) >= 1.5:
                        prev_pkt = pkt
                        last_sent_at = now
                        await ws.send_bytes(pkt)
                    await asyncio.sleep(0.042)
                else:
                    cur_win = {}
                    await asyncio.sleep(0.1)
        except Exception:
            pass

    a_task = asyncio.create_task(_audio_sender())
    v_task = asyncio.create_task(_video_sender())
    try:
        while True:
            raw_msg = await ws.receive_text()
            try:
                data = json.loads(raw_msg)
            except Exception:
                continue
            if cur_win:
                await asyncio.to_thread(
                    _dispatch_parallel_rdp_input, cur_win, data, input_state
                )
    except Exception:
        pass
    finally:
        _ACTIVE_RDP_WS_COUNT = max(0, _ACTIVE_RDP_WS_COUNT - 1)
        running = False
        _PC_WASAPI_CLIENTS.discard(audio_q)
        try:
            audio_q.put_nowait(None)
        except Exception:
            pass
        a_task.cancel()
        v_task.cancel()
        await _push_pc_bridge_cmd()
        try:
            await ws.close()
        except Exception:
            pass


try:
    from mac_virtual_display import MacVirtualDisplayManager

    mac_vdisp = MacVirtualDisplayManager()
except Exception:
    mac_vdisp = None  # type: ignore


@app.get("/mac-virtual-display/status")
async def mac_virtual_display_status() -> dict:
    if mac_vdisp is None:
        return {"ok": False, "supported": False, "active": False, "error": "Module màn phụ chưa sẵn sàng."}
    return await asyncio.to_thread(mac_vdisp.status, injector._quartz)


@app.get("/mac-virtual-display/diag")
async def mac_virtual_display_diag() -> dict:
    if not IS_MACOS:
        return {"ok": False}

    def _read_diag() -> dict:
        out: Dict[str, Any] = {
            "ok": True,
            "boot_sha": _SERVER_BOOT_SHA,
            "rdp_closer": dict(_RDP_CLOSER_DIAG),
        }
        for key, cmd in [
            ("spans_displays", ["defaults", "read", "com.apple.spaces", "spans-displays"]),
            ("dock_orientation", ["defaults", "read", "com.apple.dock", "orientation"]),
            ("dock_autohide", ["defaults", "read", "com.apple.dock", "autohide"]),
            ("mac_zoom", ["defaults", "read", "com.apple.universalaccess", "closeViewZoomedIn"]),
            ("rdp_app_ver", ["defaults", "read", "/Applications/Microsoft Remote Desktop.app/Contents/Info.plist", "CFBundleShortVersionString"]),
            ("win_app_ver", ["defaults", "read", "/Applications/Windows App.app/Contents/Info.plist", "CFBundleShortVersionString"]),
            ("rdp_prefs", ["defaults", "read", "com.microsoft.rdc.macos"]),
        ]:
            try:
                r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2.0)
                out[key] = (r.stdout or "").strip()[:1200] if r.returncode == 0 else f"ERR:{(r.stderr or '').strip()[:120]}"
            except Exception as e:
                out[key] = f"EXC:{e}"
        try:
            q = injector._quartz
            if q is not None:
                err, ids, cnt = q.CGGetActiveDisplayList(8, None, None)
                disps = []
                if err == 0 and cnt > 0:
                    for did in ids[:cnt]:
                        b = q.CGDisplayBounds(did)
                        disps.append({
                            "id": int(did),
                            "main": bool(q.CGDisplayIsMain(did)),
                            "x": float(b.origin.x),
                            "y": float(b.origin.y),
                            "w": float(b.size.width),
                            "h": float(b.size.height),
                            "px_w": int(q.CGDisplayPixelsWide(did)),
                            "px_h": int(q.CGDisplayPixelsHigh(did)),
                        })
                try:
                    mrd_bin = "/Applications/Microsoft Remote Desktop.app/Contents/MacOS/Microsoft Remote Desktop"
                    if not Path(mrd_bin).exists():
                        mrd_bin = "/Applications/Windows App.app/Contents/MacOS/Windows App"
                    if Path(mrd_bin).exists():
                        rc_cli = subprocess.run(
                            [mrd_bin, "--script", "bookmark", "list"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1.2,
                        )
                        list_txt = ((rc_cli.stdout or "") + "\n" + (rc_cli.stderr or "")).strip()
                        m_u = re.search(r'"[^"]+",\s*([0-9A-Fa-f-]{36})', list_txt)
                        if m_u:
                            rc_ex = subprocess.run(
                                [mrd_bin, "--script", "bookmark", "export", m_u.group(1).strip()],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1.2,
                            )
                            ex_s = ((rc_ex.stdout or "") + "\n" + (rc_ex.stderr or "")).strip()
                            out["mrd_cli_list"] = (list_txt + "\n---\n" + ex_s)[:1800]
                        else:
                            out["mrd_cli_list"] = list_txt[:800]
                except Exception as me:
                    out["mrd_bookmarks_err"] = str(me)[:120]
                out["displays"] = disps
                ov_wins = []
                rdp_wins = []
                srd_pid = 0
                wlist = q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionOnScreenOnly, q.kCGNullWindowID) or []
                for w in wlist:
                    ly = int(w.get("kCGWindowLayer", 0))
                    owner = str(w.get("kCGWindowOwnerName", "") or "")
                    pid_w = int(w.get("kCGWindowOwnerPID", 0) or 0)
                    wb = w.get("kCGWindowBounds") or {}
                    ww = float(wb.get("Width", 0))
                    wh = float(wb.get("Height", 0))
                    ol = owner.lower()
                    if "smartrightdock" in ol or "alwaysdock" in ol or "docky" in ol:
                        srd_pid = pid_w
                    if ("remote desktop" in ol or "windows app" in ol) and ww >= 80 and wh >= 30:
                        rdp_wins.append({
                            "owner": owner,
                            "pid": pid_w,
                            "layer": ly,
                            "name": str(w.get("kCGWindowName", "") or "")[:40],
                            "x": float(wb.get("X", 0)),
                            "y": float(wb.get("Y", 0)),
                            "w": ww,
                            "h": wh,
                        })
                    if ly >= 15 or "dock" in ol or "sidebar" in ol or "menubar" in ol:
                        if ww >= 20 and wh >= 20:
                            ov_wins.append({
                                "owner": owner,
                                "pid": pid_w,
                                "layer": ly,
                                "name": str(w.get("kCGWindowName", "") or "")[:40],
                                "x": float(wb.get("X", 0)),
                                "y": float(wb.get("Y", 0)),
                                "w": ww,
                                "h": wh,
                            })
                out["overlay_windows"] = ov_wins[:40]
                out["rdp_windows"] = rdp_wins[:20]
                rdp_all_wins = []
                all_wlist = q.CGWindowListCopyWindowInfo(
                    q.kCGWindowListOptionAll | q.kCGWindowListExcludeDesktopElements,
                    q.kCGNullWindowID,
                ) or []
                for w in all_wlist:
                    owner = str(w.get("kCGWindowOwnerName", "") or "")
                    ol = owner.lower()
                    if "remote desktop" not in ol and "windows app" not in ol:
                        continue
                    ly = int(w.get("kCGWindowLayer", 0))
                    wb = w.get("kCGWindowBounds") or {}
                    ww = float(wb.get("Width", 0))
                    wh = float(wb.get("Height", 0))
                    if ly == 0 and ww >= 80 and wh >= 30:
                        rdp_all_wins.append({
                            "pid": int(w.get("kCGWindowOwnerPID", 0) or 0),
                            "name": str(w.get("kCGWindowName", "") or "")[:60],
                            "onscreen": bool(w.get("kCGWindowIsOnscreen", False)),
                            "x": float(wb.get("X", 0)),
                            "y": float(wb.get("Y", 0)),
                            "w": ww,
                            "h": wh,
                        })
                out["rdp_all_windows"] = rdp_all_wins[:25]
                if srd_pid > 0 and mac_vdisp is not None and mac_vdisp._init_ax_libs():
                    import ctypes
                    import objc  # type: ignore
                    from mac_virtual_display import _CGPoint, _CGSize

                    ax = mac_vdisp._ax_lib
                    cf = mac_vdisp._cf_lib
                    _s = lambda st: cf.CFStringCreateWithCString(None, st.encode("utf-8"), 0x08000100)
                    _p = lambda pv: str(objc.objc_object(c_void_p=pv) or "") if pv else ""
                    s_wins, s_ch, s_role, s_title, s_desc, s_help, s_ident, s_pos, s_size = (
                        _s("AXWindows"), _s("AXChildren"), _s("AXRole"), _s("AXTitle"),
                        _s("AXDescription"), _s("AXHelp"), _s("AXIdentifier"), _s("AXPosition"), _s("AXSize"),
                    )
                    srd_items = []
                    def _walk(el, depth=0):
                        if not el or depth > 5 or len(srd_items) >= 40:
                            return
                        def _gs(attr):
                            r = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(el, attr, ctypes.byref(r)) == 0 and r.value:
                                val = _p(r.value)
                                cf.CFRelease(r.value)
                                return val
                            return ""
                        role = _gs(s_role)
                        title = _gs(s_title)
                        desc = _gs(s_desc)
                        hlp = _gs(s_help)
                        ident = _gs(s_ident)
                        pr, sr = ctypes.c_void_p(), ctypes.c_void_p()
                        px = py = pw = ph = 0.0
                        if (
                            ax.AXUIElementCopyAttributeValue(el, s_pos, ctypes.byref(pr)) == 0 and pr.value
                            and ax.AXUIElementCopyAttributeValue(el, s_size, ctypes.byref(sr)) == 0 and sr.value
                        ):
                            pt, sz = _CGPoint(), _CGSize()
                            if ax.AXValueGetValue(pr.value, 1, ctypes.byref(pt)):
                                px, py = pt.x, pt.y
                            if ax.AXValueGetValue(sr.value, 2, ctypes.byref(sz)):
                                pw, ph = sz.w, sz.h
                        if pr.value:
                            cf.CFRelease(pr.value)
                        if sr.value:
                            cf.CFRelease(sr.value)
                        if depth > 0:
                            srd_items.append({
                                "d": depth, "role": role, "title": title[:40],
                                "desc": desc[:40], "help": hlp[:40], "ident": ident[:40],
                                "x": round(px, 1), "y": round(py, 1), "w": round(pw, 1), "h": round(ph, 1),
                            })
                        cr = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el, s_ch, ctypes.byref(cr)) == 0 and cr.value:
                            try:
                                for idx in range(min(30, cf.CFArrayGetCount(cr.value))):
                                    _walk(cf.CFArrayGetValueAtIndex(cr.value, idx), depth + 1)
                            finally:
                                cf.CFRelease(cr.value)
                    app_ax = ax.AXUIElementCreateApplication(srd_pid)
                    if app_ax:
                        try:
                            wr = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wr)) == 0 and wr.value:
                                try:
                                    for idx in range(min(4, cf.CFArrayGetCount(wr.value))):
                                        _walk(cf.CFArrayGetValueAtIndex(wr.value, idx), 0)
                                finally:
                                    cf.CFRelease(wr.value)
                        finally:
                            cf.CFRelease(app_ax)
                    for sr_k in (s_wins, s_ch, s_role, s_title, s_desc, s_help, s_ident, s_pos, s_size):
                        if sr_k:
                            cf.CFRelease(sr_k)
                    out["smart_dock_ax"] = srd_items
        except Exception as e:
            out["displays_err"] = str(e)
        return out

    return await asyncio.to_thread(_read_diag)


@app.post("/mac-virtual-display/rescue")
@app.get("/mac-virtual-display/rescue")
async def mac_virtual_display_rescue() -> dict:
    if mac_vdisp is None or not IS_MACOS:
        return {"ok": False, "rescued": 0}
    moved = await asyncio.to_thread(mac_vdisp.rescue_windows_to_main_display, injector._quartz)
    return {"ok": True, "rescued": moved}


_MANUAL_WINDOWED_OPEN_UNTIL: float = 0.0


@app.post("/mac-virtual-display/open-rdp")
@app.get("/mac-virtual-display/open-rdp")
async def mac_virtual_display_open_rdp(windowed: int = 0) -> dict:
    if not IS_MACOS:
        return {"ok": False}

    def _do_open() -> dict:
        global _RDP_RECONNECT_UNTIL, _MANUAL_WINDOWED_OPEN_UNTIL
        with _SMART_MULTIMON_LOCK:
            # Nguyên tắc bắt buộc: CHỈ mở Remote Mac lên đúng nguyên trạng cài đặt sẵn có của người dùng
            # (Full-Screen hay cửa sổ thường, tỉ lệ, độ phân giải giữ nguyên 100% — TUYỆT ĐỐI không mở Edit PC hay tự chỉnh bất kỳ thứ gì!).
            rpid_cur, sess_cur, _ = _rdp_probe_vdisp_state()
            if rpid_cur > 0 and sess_cur:
                return {"ok": True, "session": sess_cur[0], "already_open": True}
            bmks = _list_mrd_bookmarks()
            tsess = bmks[0][0] if bmks else "PC Hieu"
            _MANUAL_WINDOWED_OPEN_UNTIL = time.monotonic() + 10.0
            _RDP_RECONNECT_UNTIL = time.monotonic() + 14.0
            try:
                _restart_mrd_and_connect(enable_multimon=False, target_sess=tsess, reload_only=True)
                _RDP_CLOSER_DIAG["last_reconnect"] = f"manual_open_as_is:{tsess}@{time.strftime('%H:%M:%S')}"
            finally:
                _RDP_RECONNECT_UNTIL = time.monotonic() + 4.0
            return {"ok": True, "session": tsess, "reload_only": True}

    return await asyncio.to_thread(_do_open)


@app.post("/mac-virtual-display/toggle")
async def mac_virtual_display_toggle(req: Request) -> dict:
    if mac_vdisp is None or not IS_MACOS:
        return {"ok": False, "supported": False, "active": False, "error": "Chỉ hỗ trợ trên macOS."}
    try:
        body = await req.json()
    except Exception:
        body = {}
    want_enable = bool(body.get("enable", not mac_vdisp.is_active()))
    logical_w = int(body.get("logical_w", 1798) or 1798)
    logical_h = int(body.get("logical_h", 864) or 864)
    hidpi = bool(body.get("hidpi", True))

    def _run_toggle() -> dict:
        _cancel_orphan_vdisp_shutdown()
        if want_enable:
            mac_vdisp.start(logical_w=logical_w, logical_h=logical_h, hidpi=hidpi)
        else:
            mac_vdisp.stop()
        return mac_vdisp.status(injector._quartz)

    return await asyncio.to_thread(_run_toggle)


_ACTIVE_MAC_EXT_WS_COUNT = 0
_ORPHAN_VDISP_TIMER: Optional[threading.Timer] = None
_ORPHAN_VDISP_LOCK = threading.Lock()


def _cancel_orphan_vdisp_shutdown() -> None:
    global _ORPHAN_VDISP_TIMER
    with _ORPHAN_VDISP_LOCK:
        if _ORPHAN_VDISP_TIMER is not None:
            try:
                _ORPHAN_VDISP_TIMER.cancel()
            except Exception:
                pass
            _ORPHAN_VDISP_TIMER = None


def _schedule_orphan_vdisp_shutdown(delay_sec: float = 15.0) -> None:
    """Nếu điện thoại ngắt kết nối (đóng app, xóa dữ liệu, khóa máy...) quá 15 giây mà không nối lại,
    tự động tắt màn hình ảo macOS & kéo toàn bộ app (Chrome, Settings...) về màn chính MacBook."""
    global _ORPHAN_VDISP_TIMER
    if mac_vdisp is None or not IS_MACOS:
        return

    def _fire() -> None:
        global _ORPHAN_VDISP_TIMER
        with _ORPHAN_VDISP_LOCK:
            _ORPHAN_VDISP_TIMER = None
        if _ACTIVE_MAC_EXT_WS_COUNT <= 0 and mac_vdisp is not None and mac_vdisp.is_active():
            try:
                logger.info("Không còn điện thoại kết nối Màn phụ Mac sau %.0fs -> tự hủy màn ảo & kéo app về MacBook.", delay_sec)
                mac_vdisp.stop()
            except Exception:
                pass

    with _ORPHAN_VDISP_LOCK:
        if _ORPHAN_VDISP_TIMER is not None:
            try:
                _ORPHAN_VDISP_TIMER.cancel()
            except Exception:
                pass
        t = threading.Timer(delay_sec, _fire)
        t.daemon = True
        t.start()
        _ORPHAN_VDISP_TIMER = t


@app.websocket("/mac-virtual-display-ws")
async def mac_virtual_display_ws(ws: WebSocket) -> None:
    global _ACTIVE_MAC_EXT_WS_COUNT
    await ws.accept()
    if mac_vdisp is None or not IS_MACOS:
        try:
            await ws.send_text('{"type":"vdisp_ended","reason":"unsupported"}')
            await ws.close()
        except Exception:
            pass
        return

    _ACTIVE_MAC_EXT_WS_COUNT += 1
    _cancel_orphan_vdisp_shutdown()
    running = True
    cur_bounds: Dict[str, Any] = {}
    input_state: Dict[str, Any] = {"held_btn": -1}
    ws_send_lock = asyncio.Lock()

    async def _safe_send_bytes(data: bytes) -> None:
        async with ws_send_lock:
            await ws.send_bytes(data)

    async def _safe_send_text(text: str) -> None:
        async with ws_send_lock:
            await ws.send_text(text)

    def _get_mac_cursor_xy() -> Optional[Tuple[float, float]]:
        q = injector._quartz
        if q is None:
            return None
        objc_mod = getattr(lens_capturer, "_objc", None)
        try:
            if objc_mod is not None:
                with objc_mod.autorelease_pool():
                    ev = q.CGEventCreate(None)
                    if ev is None:
                        return None
                    loc = q.CGEventGetLocation(ev)
                    return (float(loc.x), float(loc.y))
            ev = q.CGEventCreate(None)
            if ev is None:
                return None
            loc = q.CGEventGetLocation(ev)
            return (float(loc.x), float(loc.y))
        except Exception:
            return None

    def _is_inside_vdisp(px: float, py: float, b: Dict[str, Any]) -> bool:
        bx = float(b["content_x"])
        by = float(b["content_y"])
        bw = float(b["content_w"])
        bh = float(b["content_h"])
        return (bx <= px < bx + bw) and (by <= py < by + bh)

    def _resolve_vdisp_top_pid(px: float, py: float, b: Dict[str, Any], state: Dict[str, Any]) -> int:
        q = injector._quartz
        if q is None:
            return 0
        now_p = time.monotonic()
        if (now_p - float(state.get("hit_pid_at", 0.0))) < 0.35 and int(state.get("hit_pid", 0)) > 0:
            return int(state["hit_pid"])
        found_pid = 0
        found_is_mrd = False
        try:
            import objc  # type: ignore
            with objc.autorelease_pool():
                wlist = q.CGWindowListCopyWindowInfo(
                    q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements,
                    q.kCGNullWindowID,
                ) or []
                for w in wlist:
                    if int(w.get("kCGWindowLayer", -1)) != 0:
                        continue
                    wb = w.get("kCGWindowBounds") or {}
                    wx = float(wb.get("X", 0))
                    wy = float(wb.get("Y", 0))
                    ww = float(wb.get("Width", 0))
                    wh = float(wb.get("Height", 0))
                    if ww >= 120.0 and wh >= 80.0 and (wx <= px < wx + ww) and (wy <= py < wy + wh):
                        found_pid = int(w.get("kCGWindowOwnerPID", 0) or 0)
                        own_l = str(w.get("kCGWindowOwnerName", "") or "").strip().lower()
                        found_is_mrd = (
                            "microsoft remote desktop" in own_l
                            or "windows app" in own_l
                            or "com.microsoft.rdc" in own_l
                        )
                        break
        except Exception:
            found_pid = 0
            found_is_mrd = False
        state["hit_pid"] = found_pid
        state["hit_is_mrd"] = found_is_mrd
        state["hit_pid_at"] = now_p
        return found_pid

    def _focus_vdisp_window_for_scroll(target_pid: int, b: Dict[str, Any]) -> None:
        """Cấp focus cửa sổ Màn phụ #2 qua AXMain/AXFocused (không click chuột giả) để Microsoft Remote Desktop nhận sự kiện cuộn ngay cả khi trước đó đang gõ trên MacBook."""
        if target_pid <= 0 or mac_vdisp is None or not mac_vdisp._init_ax_libs():
            return
        try:
            import ctypes
            from mac_virtual_display import _CGPoint, _CGSize
            ax = mac_vdisp._ax_lib
            cf = mac_vdisp._cf_lib
            app_ax = ax.AXUIElementCreateApplication(target_pid)
            if not app_ax:
                return
            bx, by, bw, bh = float(b["content_x"]), float(b["content_y"]), float(b["content_w"]), float(b["content_h"])
            sw_k = cf.CFStringCreateWithCString(None, b"AXWindows", 0x08000100)
            sp_k = cf.CFStringCreateWithCString(None, b"AXPosition", 0x08000100)
            ss_k = cf.CFStringCreateWithCString(None, b"AXSize", 0x08000100)
            sm_k = cf.CFStringCreateWithCString(None, b"AXMain", 0x08000100)
            sf_k = cf.CFStringCreateWithCString(None, b"AXFocused", 0x08000100)
            kTrue = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue").value
            try:
                wr = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(app_ax, sw_k, ctypes.byref(wr)) == 0 and wr.value:
                    try:
                        for wi in range(cf.CFArrayGetCount(wr.value)):
                            wel = cf.CFArrayGetValueAtIndex(wr.value, wi)
                            if not wel:
                                continue
                            pr, sr = ctypes.c_void_p(), ctypes.c_void_p()
                            in_v = False
                            if (
                                ax.AXUIElementCopyAttributeValue(wel, sp_k, ctypes.byref(pr)) == 0 and pr.value
                                and ax.AXUIElementCopyAttributeValue(wel, ss_k, ctypes.byref(sr)) == 0 and sr.value
                            ):
                                pt, sz = _CGPoint(), _CGSize()
                                if ax.AXValueGetValue(pr.value, 1, ctypes.byref(pt)) and ax.AXValueGetValue(sr.value, 2, ctypes.byref(sz)):
                                    cx_w, cy_w = pt.x + sz.w * 0.5, pt.y + sz.h * 0.5
                                    in_v = (bx <= cx_w < bx + bw) and (by <= cy_w < by + bh)
                            if pr.value:
                                cf.CFRelease(pr.value)
                            if sr.value:
                                cf.CFRelease(sr.value)
                            if in_v:
                                ax.AXUIElementSetAttributeValue(wel, sm_k, kTrue)
                                ax.AXUIElementSetAttributeValue(wel, sf_k, kTrue)
                                break
                    finally:
                        cf.CFRelease(wr.value)
            finally:
                cf.CFRelease(app_ax)
                for kr in (sw_k, sp_k, ss_k, sm_k, sf_k):
                    if kr:
                        cf.CFRelease(kr)
        except Exception:
            pass

    def _dispatch_mac_ext_touch(b: Dict[str, Any], data: Dict[str, Any], state: Dict[str, Any]) -> None:
        """Tách biệt cảm ứng trên Màn phụ với con trỏ chuột MacBook:
        Nếu chuột vật lý đang ở màn chính MacBook, chạm/cuộn trên điện thoại xong sẽ tự trả
        con trỏ về đúng vị trí cũ trên MacBook để không bao giờ bị cướp chuột."""
        q = injector._quartz
        mtype = str(data.get("type", ""))
        target_b = b
        if q is not None and mtype in ("ptr_down", "ptr_wheel"):
            rx_h = max(0.0, min(1.0, float(data.get("rx", 0.5))))
            ry_h = max(0.0, min(1.0, float(data.get("ry", 0.5))))
            hx = float(b["content_x"]) + rx_h * float(b["content_w"])
            hy = float(b["content_y"]) + ry_h * float(b["content_h"])
            hit_pid = _resolve_vdisp_top_pid(hx, hy, b, state)
            if hit_pid > 0:
                target_b = dict(b)
                target_b["pid"] = hit_pid
                if mtype == "ptr_wheel" and (int(data.get("phase", 2) or 2) == 1 or state.get("focused_scroll_pid") != hit_pid):
                    state["focused_scroll_pid"] = hit_pid
                    _activate_mac_pid_if_needed(hit_pid)
                    _focus_vdisp_window_for_scroll(hit_pid, b)
                elif mtype == "ptr_down":
                    state["focused_scroll_pid"] = hit_pid

        if q is not None and mtype == "ptr_down":
            cur_xy = _get_mac_cursor_xy()
            if cur_xy is not None and not _is_inside_vdisp(cur_xy[0], cur_xy[1], b):
                state["restore_pos"] = cur_xy
                state["touch_busy"] = True
            else:
                state["restore_pos"] = None
        elif q is not None and mtype == "ptr_wheel":
            if not state.get("wheel_restore_pos"):
                cur_xy = _get_mac_cursor_xy()
                if cur_xy is not None and not _is_inside_vdisp(cur_xy[0], cur_xy[1], b):
                    state["wheel_restore_pos"] = cur_xy
                    state["touch_busy"] = True
            state["last_wheel_at"] = time.monotonic()

        _dispatch_parallel_rdp_input(target_b, data, state)

        if q is not None and mtype == "ptr_up":
            rpos = state.pop("restore_pos", None)
            if rpos is not None:
                time.sleep(0.015)
                try:
                    q.CGWarpMouseCursorPosition(rpos)
                except Exception:
                    pass
                state.pop("last_wheel_sx", None)
                state.pop("last_wheel_sy", None)
                state["touch_busy"] = False

    async def _cursor_sender() -> None:
        q = injector._quartz
        if q is None:
            return
        last_vis: Optional[bool] = None
        last_rx = -1.0
        last_ry = -1.0
        try:
            while running:
                # Tự trả con trỏ về MacBook sau khi ngón tay dừng cuộn trên màn phụ (~450ms để không cắt giữa chừng quán tính)
                wpos = input_state.get("wheel_restore_pos")
                if wpos is not None and (time.monotonic() - float(input_state.get("last_wheel_at", 0.0))) >= 0.45:
                    input_state.pop("wheel_restore_pos", None)
                    input_state.pop("last_wheel_sx", None)
                    input_state.pop("last_wheel_sy", None)
                    try:
                        q.CGWarpMouseCursorPosition(wpos)
                    except Exception:
                        pass
                    if not input_state.get("restore_pos"):
                        input_state["touch_busy"] = False

                b = cur_bounds
                if b and b.get("content_w", 0) > 0 and b.get("content_h", 0) > 0:
                    if input_state.get("touch_busy"):
                        if last_vis is not False:
                            last_vis = False
                            await _safe_send_text('{"type":"cursor","vis":false}')
                    else:
                        cur_xy = _get_mac_cursor_xy()
                        if cur_xy is not None:
                            mx, my = cur_xy
                            bx = float(b["content_x"])
                            by = float(b["content_y"])
                            bw = float(b["content_w"])
                            bh = float(b["content_h"])
                            inside = (bx <= mx < bx + bw) and (by <= my < by + bh)
                            if inside:
                                rx = max(0.0, min(1.0, (mx - bx) / bw))
                                ry = max(0.0, min(1.0, (my - by) / bh))
                                if (
                                    last_vis is not True
                                    or abs(rx - last_rx) >= 0.0005
                                    or abs(ry - last_ry) >= 0.0005
                                ):
                                    last_vis = True
                                    last_rx = rx
                                    last_ry = ry
                                    await _safe_send_text(
                                        f'{{"type":"cursor","vis":true,"rx":{rx:.4f},"ry":{ry:.4f}}}'
                                    )
                            elif last_vis is not False:
                                last_vis = False
                                await _safe_send_text('{"type":"cursor","vis":false}')
                await asyncio.sleep(0.016)
        except Exception:
            pass

    async def _video_sender() -> None:
        nonlocal cur_bounds
        missing_since: Optional[float] = None
        last_bounds_at = 0.0
        prev_pkt: Optional[bytes] = None
        last_sent_at = 0.0
        try:
            while running:
                now = time.monotonic()
                if not cur_bounds or (now - last_bounds_at) >= 0.5:
                    last_bounds_at = now
                    b = await asyncio.to_thread(mac_vdisp.get_bounds, injector._quartz)
                    if b is not None:
                        cur_bounds = {
                            "pid": 0,
                            "content_x": b["x"],
                            "content_y": b["y"],
                            "content_w": b["w"],
                            "content_h": b["h"],
                        }
                        missing_since = None
                    else:
                        if missing_since is None:
                            missing_since = now
                        elif (now - missing_since) >= 2.5:
                            await _safe_send_text('{"type":"vdisp_ended","reason":"disabled"}')
                            break
                        await asyncio.sleep(0.12)
                        continue

                pkt = await asyncio.to_thread(
                    mac_vdisp.capture_jpeg_packet,
                    lens_capturer._quartz,
                    lens_capturer._foundation,
                    lens_capturer._objc,
                    0.82,
                    2248,
                )
                if pkt is not None:
                    if pkt != prev_pkt or (now - last_sent_at) >= 1.4:
                        prev_pkt = pkt
                        last_sent_at = now
                        await _safe_send_bytes(pkt)
                    await asyncio.sleep(0.045)
                else:
                    await asyncio.sleep(0.1)
        except Exception:
            pass

    c_task = asyncio.create_task(_cursor_sender())
    v_task = asyncio.create_task(_video_sender())
    try:
        while True:
            raw_msg = await ws.receive_text()
            try:
                data = json.loads(raw_msg)
            except Exception:
                continue
            if cur_bounds:
                pc_ws = _PC_BRIDGE_WS
                if pc_ws is not None:
                    mtype_in = str(data.get("type", ""))
                    if mtype_in in ("ptr_down", "ptr_wheel") or (time.monotonic() - float(input_state.get("hit_pid_at", 0.0))) >= 0.35:
                        rx_c = max(0.0, min(1.0, float(data.get("rx", 0.5))))
                        ry_c = max(0.0, min(1.0, float(data.get("ry", 0.5))))
                        hx_c = float(cur_bounds["content_x"]) + rx_c * float(cur_bounds["content_w"])
                        hy_c = float(cur_bounds["content_y"]) + ry_c * float(cur_bounds["content_h"])
                        await asyncio.to_thread(_resolve_vdisp_top_pid, hx_c, hy_c, cur_bounds, input_state)
                    if bool(input_state.get("hit_is_mrd", False)):
                        try:
                            await pc_ws.send_text(
                                json.dumps({"cmd": "sec_input", "payload": {**data, "mon": "sec"}})
                            )
                            continue
                        except Exception:
                            pass
                await asyncio.to_thread(
                    _dispatch_mac_ext_touch, cur_bounds, data, input_state
                )
    except Exception:
        pass
    finally:
        _ACTIVE_MAC_EXT_WS_COUNT = max(0, _ACTIVE_MAC_EXT_WS_COUNT - 1)
        if _ACTIVE_MAC_EXT_WS_COUNT <= 0 and mac_vdisp is not None and mac_vdisp.is_active():
            _schedule_orphan_vdisp_shutdown(delay_sec=15.0)
        running = False
        c_task.cancel()
        v_task.cancel()
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
        "version": "2.3.16",
        "pid": os.getpid(),
        "platform": sys.platform,
        "vn_enabled": injector.vn_enabled,
        "mac_evkey_vn": rdp_evkey_sync.mac_vn_mode,
        "rdp_evkey_bypass_pid": rdp_evkey_sync.active_rdp_pid,
        "kb_layout": injector.kb_layout,
        "lens_available": lens_capturer.available,
        "kvm_available": kvm_bridge.available,
        "kvm_mode": kvm_bridge.mode,
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
async def respawn_worker(pull: int = 0) -> dict:
    """Khởi chạy lại tiến trình mới sạch hoàn toàn qua launchd để nhận quyền Screen Recording hoặc code mới."""
    pulled = False
    if pull and (BASE_DIR / ".git").exists():
        try:
            subprocess.run(["git", "fetch", "origin", "main", "--quiet"], cwd=str(BASE_DIR), timeout=10, check=False)
            pr = subprocess.run(["git", "pull", "--ff-only", "origin", "main"], cwd=str(BASE_DIR), timeout=15, check=False)
            pulled = (pr.returncode == 0)
            if pulled:
                chk = subprocess.run([sys.executable, "-m", "py_compile", str(BASE_DIR / "server.py")], cwd=str(BASE_DIR), timeout=8, check=False)
                if chk.returncode != 0:
                    return {"ok": False, "restarting": False, "pulled": True, "error": "py_compile_failed"}
        except Exception:
            pulled = False
    threading.Timer(0.2, _trigger_clean_respawn).start()
    return {"ok": True, "restarting": True, "pulled": pulled}


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
                phase = int(data.get("phase", 2))
                injector.mouse_scroll(dx, dy, phase=phase)
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
                kvm_mode = str(data.get("mode", "mac"))
                kvm_bridge.attach_client(ws, cur_loop, kvm_queue, kvm_on, kvm_mode)
            elif msg_type == "kvm_bridge_return":
                kvm_bridge.bridge_return_to_mac(
                    float(data.get("y_ratio", 0.5)),
                    str(data.get("return_edge", "left")),
                )
            elif msg_type == "kvm_set":
                kvm_bridge.set_captured(bool(data.get("captured", False)))
            elif msg_type == "kvm_return":
                kvm_bridge.emergency_release_to_mac()
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

    def _is_live_session_busy() -> bool:
        if _ACTIVE_RDP_WS_COUNT > 0 or _ACTIVE_MAC_EXT_WS_COUNT > 0:
            return True
        try:
            if mac_vdisp is not None and mac_vdisp.is_active():
                return True
        except Exception:
            pass
        return False

    def _updater() -> None:
        pending_respawn = False
        last_git_check = 0.0
        while True:
            time.sleep(1.5 if pending_respawn else check_every_sec)
            try:
                if pending_respawn and not _is_live_session_busy():
                    pending_respawn = False
                    _trigger_clean_respawn()
                    continue
                now_u = time.monotonic()
                if pending_respawn and (now_u - last_git_check) < check_every_sec:
                    continue
                last_git_check = now_u
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
                        chk_u = subprocess.run(
                            [sys.executable, "-m", "py_compile", str(BASE_DIR / "server.py")],
                            cwd=str(BASE_DIR),
                            timeout=8,
                            check=False,
                        )
                        if chk_u.returncode == 0:
                            if _is_live_session_busy():
                                pending_respawn = True
                            else:
                                _trigger_clean_respawn()
            except Exception:
                pass

    t = threading.Thread(target=_updater, daemon=True)
    t.start()


def _detect_boot_git_sha() -> str:
    try:
        if (BASE_DIR / ".git").exists():
            return subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(BASE_DIR),
                text=True,
                timeout=3,
            ).strip()
    except Exception:
        pass
    return "unknown"


_SERVER_BOOT_SHA: str = _detect_boot_git_sha()
_RDP_RECONNECT_UNTIL: float = 0.0
_LAST_2MON_SYNC_AT: float = -100.0
_LAST_1MON_SYNC_AT: float = -100.0
_LAST_DOWNGRADED_1MON_PID: int = 0
_LAST_APPLIED_BOOKMARK_MODE: Optional[bool] = None
_RESTORE_1MON_BOUNDS_UNTIL: float = 0.0
_USER_1MON_BOUNDS_PATH = BASE_DIR / ".user_rdp_1mon_bounds.json"
_SAVED_USER_1MON_BOUNDS: Optional[Dict[str, float]] = None
_SMART_MULTIMON_LOCK = threading.Lock()


def _is_mrd_tiny_default_box(w: float, h: float) -> bool:
    """MRD 10.9.10 tự ép cửa sổ mới về ô 756x500 (50% màn MacBook) ngay sau khi bắt tay RDP."""
    return (740.0 <= w <= 772.0) and (485.0 <= h <= 515.0)


def _is_clamped_1467_box(w: float, h: float) -> bool:
    """Khung 1467x944 bị hụt 45px bên phải do tỷ lệ 3024:1888 cũ, hoặc khung 1024x796 lỗi tạm."""
    if (1455.0 <= w <= 1482.0) and (h >= 925.0):
        return True
    if (1012.0 <= w <= 1036.0) and (780.0 <= h <= 812.0):
        return True
    return False


def _get_mac_menubar_height(quartz: Any = None) -> float:
    q = quartz if quartz is not None else injector._quartz
    if q is None:
        return 37.0
    try:
        import objc  # type: ignore
        with objc.autorelease_pool():
            wlist = q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionOnScreenOnly, q.kCGNullWindowID) or []
            for w in wlist:
                if int(w.get("kCGWindowLayer", 0)) == 24 and str(w.get("kCGWindowName", "")) == "Menubar":
                    wb = w.get("kCGWindowBounds") or {}
                    mh_b = float(wb.get("Height", 0.0))
                    if 20.0 <= mh_b <= 52.0:
                        return mh_b
    except Exception:
        pass
    return 37.0


def _compute_exact_1mon_retina_res(quartz: Any = None) -> Tuple[int, int, float, float, float, float]:
    """Tính độ phân giải chuẩn 1:1 kích thước thật của Windows cho khung cửa sổ MacBook (trừ đúng Menubar 38px + Titlebar 28px = 1512x916 tỷ lệ thật 100%, không bị bé 50% cũng không bị zoom 200%, khít 0px khe hở!)."""
    q = quartz if quartz is not None else injector._quartz
    if q is None:
        try:
            import Quartz as q  # type: ignore
        except Exception:
            return 1512, 916, 0.0, 38.0, 1512.0, 944.0
    mb = q.CGDisplayBounds(q.CGMainDisplayID())
    mx, my, mw, mh = float(mb.origin.x), float(mb.origin.y), float(mb.size.width), float(mb.size.height)
    mbar_h = max(38.0, _get_mac_menubar_height(q))
    win_h = max(600.0, mh - mbar_h)
    content_h = max(500.0, win_h - 28.0)
    rw = int(round(mw))
    rh = int(round(content_h))
    # Căn chẵn bội số của 4 cho chuẩn H.264 RDP (1512 = 378 * 4, 916 = 229 * 4)
    rw = rw - (rw % 4)
    rh = rh - (rh % 4)
    return rw, rh, mx, my + mbar_h, mw, win_h


def _load_saved_1mon_bounds() -> Optional[Dict[str, float]]:
    global _SAVED_USER_1MON_BOUNDS
    if _SAVED_USER_1MON_BOUNDS is not None:
        return _SAVED_USER_1MON_BOUNDS
    try:
        if _USER_1MON_BOUNDS_PATH.exists():
            raw = json.loads(_USER_1MON_BOUNDS_PATH.read_text(encoding="utf-8"))
            bw = float(raw.get("w", 0.0))
            bh = float(raw.get("h", 0.0))
            if bw >= 360.0 and bh >= 240.0 and not _is_mrd_tiny_default_box(bw, bh):
                _SAVED_USER_1MON_BOUNDS = {
                    "x": float(raw.get("x", 0.0)),
                    "y": float(raw.get("y", 38.0)),
                    "w": bw,
                    "h": bh,
                }
                return _SAVED_USER_1MON_BOUNDS
    except Exception:
        pass
    return None


def _save_user_1mon_bounds(bx: float, by: float, bw: float, bh: float) -> None:
    """Lưu lại đúng vị trí & kích thước cửa sổ thường mà người dùng tự đặt trên MacBook (mở bé hay mở to giữ nguyên y hệt!)."""
    global _SAVED_USER_1MON_BOUNDS
    if bw < 360.0 or bh < 240.0 or _is_mrd_tiny_default_box(bw, bh):
        return
    prev = _SAVED_USER_1MON_BOUNDS
    if (
        prev is not None
        and abs(prev["x"] - bx) < 4.0
        and abs(prev["y"] - by) < 4.0
        and abs(prev["w"] - bw) < 4.0
        and abs(prev["h"] - bh) < 4.0
    ):
        return
    _SAVED_USER_1MON_BOUNDS = {"x": round(bx, 1), "y": round(by, 1), "w": round(bw, 1), "h": round(bh, 1)}
    _RDP_CLOSER_DIAG["saved_1mon_bounds"] = dict(_SAVED_USER_1MON_BOUNDS)
    try:
        _USER_1MON_BOUNDS_PATH.write_text(json.dumps(_SAVED_USER_1MON_BOUNDS), encoding="utf-8")
    except Exception:
        pass
_RDP_CLOSER_DIAG: Dict[str, Any] = {
    "sessions": [],
    "on_screen_main": False,
    "launcher_seen": False,
    "sec_display_active": False,
    "closed_count": 0,
    "jumped_count": 0,
    "last_action": "",
    "last_reconnect": "",
    "multimon_bookmark": None,
    "last_ax_wins": [],
    "last_menu_items": [],
    "last_err": "",
}


def _get_mrd_cli_info() -> Tuple[str, str]:
    p1 = "/Applications/Microsoft Remote Desktop.app/Contents/MacOS/Microsoft Remote Desktop"
    if Path(p1).exists():
        return p1, "Microsoft Remote Desktop"
    p2 = "/Applications/Windows App.app/Contents/MacOS/Windows App"
    if Path(p2).exists():
        return p2, "Windows App"
    return "", ""


def _list_mrd_bookmarks() -> List[Tuple[str, str]]:
    """Chỉ đọc danh sách bookmark (100% read-only, không ghi đè cấu hình)."""
    if not IS_MACOS:
        return []
    mrd_bin, _ = _get_mrd_cli_info()
    if not mrd_bin:
        return []
    found: List[Tuple[str, str]] = []
    try:
        rc = subprocess.run(
            [mrd_bin, "--script", "bookmark", "list"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=6.0,
        )
        out_txt = (rc.stdout or "") + "\n" + (rc.stderr or "")
        for m in re.finditer(r'"([^"]+)",\s*([0-9A-Fa-f-]{36})', out_txt):
            found.append((m.group(1).strip(), m.group(2).strip()))
    except Exception:
        pass
    return found


def _find_live_mrd_pids() -> List[int]:
    """Lấy danh sách PID thật của Microsoft Remote Desktop / Windows App từ OS (kể cả khi ẩn hết cửa sổ)."""
    if not IS_MACOS:
        return []
    pids: set = set()
    rpid_w, _, _ = _rdp_probe_vdisp_state(require_live_open=False)
    if rpid_w > 0:
        pids.add(rpid_w)
    try:
        rc = subprocess.run(
            ["pgrep", "-f", "Microsoft Remote Desktop.app/Contents/MacOS|Windows App.app/Contents/MacOS"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1.5,
        )
        for ln in (rc.stdout or "").splitlines():
            ln = ln.strip()
            if ln.isdigit():
                pv = int(ln)
                if pv > 0 and pv != os.getpid():
                    pids.add(pv)
    except Exception:
        pass
    return sorted(pids)


def _get_secondary_mac_display_bounds(quartz: Any = None) -> Optional[Dict[str, float]]:
    """Nhận diện MỌI màn hình phụ mở rộng đang kết nối với MacBook (Màn phụ Mac ảo hoặc màn phụ điện thoại/ngoài bất kỳ, bỏ qua Mirror)."""
    if not IS_MACOS:
        return None
    q = quartz if quartz is not None else injector._quartz
    if q is None:
        try:
            import Quartz as q  # type: ignore
        except Exception:
            return None
    if mac_vdisp is not None and mac_vdisp.is_active():
        vb = mac_vdisp.get_bounds(q)
        if vb is not None:
            return vb
    try:
        res = q.CGGetActiveDisplayList(8, None, None)
        if isinstance(res, tuple) and len(res) == 3:
            err, dlist, cnt = res
            if err == 0 and dlist and int(cnt) > 1:
                for did in list(dlist)[: int(cnt)]:
                    did_i = int(did)
                    if did_i <= 0 or bool(q.CGDisplayIsMain(did_i)):
                        continue
                    try:
                        if int(q.CGDisplayMirrorsDisplay(did_i)) != 0:
                            continue
                    except Exception:
                        pass
                    b = q.CGDisplayBounds(did_i)
                    w = float(b.size.width)
                    h = float(b.size.height)
                    if w >= 200.0 and h >= 200.0:
                        return {
                            "display_id": did_i,
                            "x": float(b.origin.x),
                            "y": float(b.origin.y),
                            "w": w,
                            "h": h,
                        }
    except Exception:
        pass
    return None


def _bookmark_needs_retina_or_dyn_repair(bookmarks: List[Tuple[str, str]]) -> bool:
    """Giữ nguyên 100% toàn bộ cài đặt độ phân giải / Retina / Fit mà người dùng đã tự cấu hình trong Remote Desktop."""
    return False


def _bookmark_already_matches(bookmarks: List[Tuple[str, str]], want_multimon: bool) -> bool:
    """Chỉ kiểm tra duy nhất 2 cờ 1 màn / 2 màn (use multimon & screen mode id); tuyệt đối không động vào độ phân giải hay tỉ lệ người dùng đã cài!"""
    if not IS_MACOS or not bookmarks:
        return False
    mrd_bin, _ = _get_mrd_cli_info()
    if not mrd_bin:
        return False
    try:
        _, buuid = bookmarks[0]
        rc_ex = subprocess.run(
            [mrd_bin, "--script", "bookmark", "export", buuid],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4.0,
        )
        ex_txt = (rc_ex.stdout or "") + "\n" + (rc_ex.stderr or "")
        if "full address:s:" not in ex_txt.lower():
            return False
        mm_val = 1 if want_multimon else 0
        sm_val = 2 if want_multimon else 1
        has_mm = bool(re.search(rf"use multimon:i:{mm_val}\b", ex_txt, re.IGNORECASE))
        has_sm = bool(re.search(rf"screen mode id:i:{sm_val}\b", ex_txt, re.IGNORECASE))
        return has_mm and has_sm
    except Exception:
        return False


def _ax_update_bookmark_display_mode(
    enable_multimon: bool,
    target_title: str,
    connect_after: bool,
) -> int:
    """Chuyển chế độ 1 màn <-> 2 màn trực tiếp trên bảng Edit PC -> Display -> Save của Microsoft Remote Desktop bằng AXUIElement:
    - TUYỆT ĐỐI KHÔNG BAO GIỜ gọi `--script bookmark write` (vì CLI của MRD làm mất mật khẩu Keychain bắt nhập lại mật khẩu!).
    - Giữ nguyên 100% User account + mật khẩu đã lưu trong Keychain.
    - Luôn khóa chuẩn: Optimize for Retina = ON, Fit session to window = ON, Update session resolution on resize = OFF (xóa vĩnh viễn lỗi zoom cận cảnh 200%)."""
    global _LAST_APPLIED_BOOKMARK_MODE
    if not IS_MACOS or mac_vdisp is None or not mac_vdisp._init_ax_libs():
        return 0
    import ctypes
    import AppKit  # type: ignore
    import objc  # type: ignore
    from mac_virtual_display import _CGPoint, _CGSize

    _, app_name = _get_mrd_cli_info()
    if not app_name:
        return 0

    q = injector._quartz
    if q is None:
        try:
            import Quartz as q  # type: ignore
        except Exception:
            q = None
    ax = mac_vdisp._ax_lib
    cf = mac_vdisp._cf_lib
    kCFStringEncodingUTF8 = 0x08000100

    def _cfstr(s: str) -> ctypes.c_void_p:
        return cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)

    _RDP_CLOSER_DIAG["ax_stage"] = "enter"
    # 0A) Nếu tiến trình MRD cũ đang kẹt hộp thoại modal "Untitled" (380x148) khi chưa mở phiên nào -> SIGKILL NGAY LẬP TỨC trước mọi lệnh AX!
    if q is not None:
        try:
            stuck_pids: List[int] = []
            with objc.autorelease_pool():
                for wu_chk in (q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionAll | q.kCGWindowListExcludeDesktopElements, q.kCGNullWindowID) or []):
                    if int(wu_chk.get("kCGWindowLayer", -1)) == 0 and str(wu_chk.get("kCGWindowName", "") or "").strip().lower() == "untitled":
                        wbu = wu_chk.get("kCGWindowBounds") or {}
                        if 320.0 <= float(wbu.get("Width", 0.0)) <= 430.0 and 110.0 <= float(wbu.get("Height", 0.0)) <= 200.0:
                            ol_u = str(wu_chk.get("kCGWindowOwnerName", "") or "").strip().lower()
                            if "microsoft remote desktop" in ol_u or "windows app" in ol_u:
                                spid = int(wu_chk.get("kCGWindowOwnerPID", 0) or 0)
                                if spid > 0 and spid not in stuck_pids:
                                    stuck_pids.append(spid)
            if stuck_pids and not _rdp_probe_vdisp_state()[1]:
                for spid in stuck_pids:
                    try:
                        os.kill(spid, signal.SIGKILL)
                    except Exception:
                        pass
                for _ in range(15):
                    time.sleep(0.10)
                    cur_live = _find_live_mrd_pids()
                    if all(sp not in cur_live for sp in stuck_pids):
                        break
                _RDP_CLOSER_DIAG["ax_stage"] = f"killed_stuck:{stuck_pids}"
        except Exception as exc_k:
            _RDP_CLOSER_DIAG["kill_stuck_err"] = str(exc_k)[:120]

    # Ghi nhận ứng dụng đang active qua NSWorkspace (0% phụ thuộc cổng Mach Accessibility!)
    orig_front_pid = 0
    try:
        with objc.autorelease_pool():
            fa = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            if fa is not None:
                orig_front_pid = int(fa.processIdentifier())
    except Exception:
        pass

    live_pids = _find_live_mrd_pids()
    rdp_pid = live_pids[0] if live_pids else 0
    if rdp_pid <= 0:
        # Khởi chạy ngầm ẩn hoàn toàn (-g background, -j hidden) để không bao giờ chớp cửa sổ trắng Connection Center!
        subprocess.Popen(["open", "-g", "-j", "-a", app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(0.16)
            live_pids = _find_live_mrd_pids()
            if live_pids:
                rdp_pid = live_pids[0]
                break
        time.sleep(0.45)
    if rdp_pid <= 0:
        return 0

    try:
        subprocess.Popen(["caffeinate", "-u", "-t", "8"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    app_ax = ax.AXUIElementCreateApplication(rdp_pid)
    if not app_ax:
        return rdp_pid
    try:
        ax.AXUIElementSetMessagingTimeout.argtypes = [ctypes.c_void_p, ctypes.c_float]
        ax.AXUIElementSetMessagingTimeout.restype = ctypes.c_int32
        ax.AXUIElementSetMessagingTimeout(app_ax, ctypes.c_float(0.75))
    except Exception:
        pass

    # Đẩy sẵn mọi cửa sổ Connection Center ra góc giấu ngầm (1510, 980) TRƯỚC KHI unhide/activate MRD (0.00s chớp hình!)
    _pk_x0, _pk_y0 = 1510.0, 980.0
    if q is not None:
        try:
            _mb0 = q.CGDisplayBounds(q.CGMainDisplayID())
            _pk_x0 = float(_mb0.origin.x) + float(_mb0.size.width) - 2.0
            _pk_y0 = float(_mb0.origin.y) + float(_mb0.size.height) - 2.0
        except Exception:
            pass
    _sw0 = _cfstr("AXWindows")
    _st0 = _cfstr("AXTitle")
    _sp0 = _cfstr("AXPosition")
    try:
        _w0 = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(app_ax, _sw0, ctypes.byref(_w0)) == 0 and _w0.value:
            try:
                for _wi0 in range(cf.CFArrayGetCount(_w0.value)):
                    _wel0 = cf.CFArrayGetValueAtIndex(_w0.value, _wi0)
                    if not _wel0:
                        continue
                    _wt0 = ""
                    _tr0 = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(_wel0, _st0, ctypes.byref(_tr0)) == 0 and _tr0.value:
                        with objc.autorelease_pool():
                            _wt0 = str(objc.objc_object(c_void_p=_tr0.value) or "").strip().lower()
                        cf.CFRelease(_tr0.value)
                    if not _wt0 or _wt0 in ("microsoft remote desktop", "windows app", "connection center", "pcs", "devices"):
                        _pt0 = _CGPoint(_pk_x0, _pk_y0)
                        _vp0 = ax.AXValueCreate(1, ctypes.byref(_pt0))
                        if _vp0:
                            ax.AXUIElementSetAttributeValue(_wel0, _sp0, _vp0)
                            cf.CFRelease(_vp0)
            finally:
                cf.CFRelease(_w0.value)
    finally:
        for _k0 in (_sw0, _st0, _sp0):
            if _k0:
                cf.CFRelease(_k0)

    try:
        with objc.autorelease_pool():
            rapp = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(rdp_pid)
            if rapp is not None:
                rapp.unhide()
                rapp.activateWithOptions_(3)
    except Exception:
        pass
    time.sleep(0.14)

    s_wins = _cfstr("AXWindows")
    s_role = _cfstr("AXRole")
    s_subrole = _cfstr("AXSubrole")
    s_title = _cfstr("AXTitle")
    s_desc = _cfstr("AXDescription")
    s_val = _cfstr("AXValue")
    s_pos = _cfstr("AXPosition")
    s_size = _cfstr("AXSize")
    s_close = _cfstr("AXCloseButton")
    s_press = _cfstr("AXPress")
    s_menubar = _cfstr("AXMenuBar")
    s_children = _cfstr("AXChildren")
    s_enabled = _cfstr("AXEnabled")
    s_fs = _cfstr("AXFullScreen")
    s_main = _cfstr("AXMain")
    s_focused = _cfstr("AXFocused")
    s_raise = _cfstr("AXRaise")
    s_parent_d = _cfstr("AXParent")
    s_sel_d = _cfstr("AXSelected")
    kTrue = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue").value
    kFalse = ctypes.c_void_p.in_dll(cf, "kCFBooleanFalse").value

    def _set_tmo(el: Any, sec: float = 0.50) -> None:
        if el:
            try:
                ax.AXUIElementSetMessagingTimeout(el, ctypes.c_float(sec))
            except Exception:
                pass

    def _gs(el: Any, attr: Any) -> str:
        _set_tmo(el, 0.50)
        r = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(el, attr, ctypes.byref(r)) == 0 and r.value:
            try:
                with objc.autorelease_pool():
                    return str(objc.objc_object(c_void_p=r.value) or "")
            finally:
                cf.CFRelease(r.value)
        return ""

    def _gb(el: Any, attr: Any) -> bool:
        _set_tmo(el, 0.50)
        r = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(el, attr, ctypes.byref(r)) == 0 and r.value:
            try:
                return bool(cf.CFBooleanGetValue(r.value))
            finally:
                cf.CFRelease(r.value)
        return False

    def _gi(el: Any, attr: Any) -> int:
        _set_tmo(el, 0.50)
        r = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(el, attr, ctypes.byref(r)) == 0 and r.value:
            try:
                with objc.autorelease_pool():
                    obj = objc.objc_object(c_void_p=r.value)
                    return int(bool(obj)) if obj is not None else 0
            finally:
                cf.CFRelease(r.value)
        return 0

    def _grect(el: Any) -> Optional[Tuple[float, float, float, float]]:
        _set_tmo(el, 0.50)
        rp = ctypes.c_void_p()
        rs = ctypes.c_void_p()
        ok = False
        pt = _CGPoint()
        sz = _CGSize()
        if ax.AXUIElementCopyAttributeValue(el, s_pos, ctypes.byref(rp)) == 0 and rp.value:
            if ax.AXUIElementCopyAttributeValue(el, s_size, ctypes.byref(rs)) == 0 and rs.value:
                ok = bool(ax.AXValueGetValue(rp.value, 1, ctypes.byref(pt)) and ax.AXValueGetValue(rs.value, 2, ctypes.byref(sz)))
        if rp.value:
            cf.CFRelease(rp.value)
        if rs.value:
            cf.CFRelease(rs.value)
        return (float(pt.x), float(pt.y), float(sz.w), float(sz.h)) if ok else None

    def _click_menu_item(bar_names: Tuple[str, ...], item_exact_set: Tuple[str, ...]) -> bool:
        _set_tmo(app_ax, 0.50)
        mb = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(app_ax, s_menubar, ctypes.byref(mb)) != 0 or not mb.value:
            return False
        try:
            _set_tmo(mb.value, 0.50)
            bars = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(mb.value, s_children, ctypes.byref(bars)) != 0 or not bars.value:
                return False
            try:
                nb = cf.CFArrayGetCount(bars.value)
                for bi in range(nb):
                    bel = cf.CFArrayGetValueAtIndex(bars.value, bi)
                    if not bel or _gs(bel, s_title).strip().lower() not in bar_names:
                        continue
                    sub = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(bel, s_children, ctypes.byref(sub)) != 0 or not sub.value:
                        continue
                    try:
                        if cf.CFArrayGetCount(sub.value) <= 0:
                            continue
                        mel = cf.CFArrayGetValueAtIndex(sub.value, 0)
                        _set_tmo(mel, 0.50)
                        its = ctypes.c_void_p()
                        if mel and ax.AXUIElementCopyAttributeValue(mel, s_children, ctypes.byref(its)) == 0 and its.value:
                            try:
                                ni = cf.CFArrayGetCount(its.value)
                                for mi in range(ni):
                                    iel = cf.CFArrayGetValueAtIndex(its.value, mi)
                                    if not iel:
                                        continue
                                    it_l = _gs(iel, s_title).strip().lower()
                                    if it_l in item_exact_set and _gb(iel, s_enabled):
                                        if _ax_press_fast(iel, 0.50) == 0:
                                            return True
                            finally:
                                cf.CFRelease(its.value)
                    finally:
                        cf.CFRelease(sub.value)
            finally:
                cf.CFRelease(bars.value)
        finally:
            cf.CFRelease(mb.value)
        return False

    def _cg_click_once(cx: float, cy: float) -> None:
        if q is None:
            return
        try:
            q.CGWarpMouseCursorPosition((float(cx), float(cy)))
        except Exception:
            pass
        mv = q.CGEventCreateMouseEvent(None, q.kCGEventMouseMoved, (cx, cy), q.kCGMouseButtonLeft)
        d1 = q.CGEventCreateMouseEvent(None, q.kCGEventLeftMouseDown, (cx, cy), q.kCGMouseButtonLeft)
        u1 = q.CGEventCreateMouseEvent(None, q.kCGEventLeftMouseUp, (cx, cy), q.kCGMouseButtonLeft)
        q.CGEventSetIntegerValueField(d1, q.kCGMouseEventClickState, 1)
        q.CGEventSetIntegerValueField(u1, q.kCGMouseEventClickState, 1)
        q.CGEventPost(q.kCGHIDEventTap, mv)
        q.CGEventPost(q.kCGHIDEventTap, d1)
        time.sleep(0.025)
        q.CGEventPost(q.kCGHIDEventTap, u1)

    orig_pt = None
    if q is not None:
        oev = q.CGEventCreate(None)
        if oev is not None:
            orig_pt = q.CGEventGetLocation(oev)

    def _ax_press_fast(target_el: Any, timeout_s: float = 0.65) -> int:
        if not target_el:
            return -1
        try:
            ax.AXUIElementSetMessagingTimeout(target_el, ctypes.c_float(timeout_s))
        except Exception:
            pass
        return int(ax.AXUIElementPerformAction(target_el, s_press))

    def _has_small_modal_dialog() -> Optional[Tuple[float, float, float, float]]:
        if q is None:
            return None
        try:
            with objc.autorelease_pool():
                wl_m = q.CGWindowListCopyWindowInfo(
                    q.kCGWindowListOptionAll | q.kCGWindowListExcludeDesktopElements,
                    q.kCGNullWindowID,
                ) or []
                for wm in wl_m:
                    if int(wm.get("kCGWindowOwnerPID", 0) or 0) != rdp_pid:
                        continue
                    if int(wm.get("kCGWindowLayer", -1)) != 0:
                        continue
                    if not bool(wm.get("kCGWindowIsOnscreen", False)):
                        continue
                    wbm = wm.get("kCGWindowBounds") or {}
                    mw_d = float(wbm.get("Width", 0.0))
                    mh_d = float(wbm.get("Height", 0.0))
                    mn_d = str(wm.get("kCGWindowName", "") or "").strip().lower()
                    if 160.0 <= mw_d <= 500.0 and 100.0 <= mh_d <= 400.0 and mn_d not in ("preferences", "settings", "connection center"):
                        return (float(wbm.get("X", 0.0)), float(wbm.get("Y", 0.0)), mw_d, mh_d)
        except Exception:
            pass
        return None

    def _dismiss_disconnect_modal() -> bool:
        hit_m = [False]

        def _walk_modal_btn(el: Any, depth: int) -> None:
            if not el or depth > 14 or hit_m[0]:
                return
            try:
                ax.AXUIElementSetMessagingTimeout(el, ctypes.c_float(0.50))
            except Exception:
                pass
            if _gs(el, s_role).strip() == "AXButton" and _gb(el, s_enabled):
                bt_m = _gs(el, s_title).strip().lower()
                if bt_m in ("disconnect", "continue", "close", "ok", "yes", "ngắt kết nối", "tiếp tục", "đóng"):
                    if _ax_press_fast(el, 0.55) == 0:
                        hit_m[0] = True
                        return
            ch = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                try:
                    for ci in range(min(cf.CFArrayGetCount(ch.value), 60)):
                        _walk_modal_btn(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                        if hit_m[0]:
                            break
                finally:
                    cf.CFRelease(ch.value)

        wm_arr = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wm_arr)) == 0 and wm_arr.value:
            try:
                for wi in range(cf.CFArrayGetCount(wm_arr.value)):
                    wel_m = cf.CFArrayGetValueAtIndex(wm_arr.value, wi)
                    if not wel_m:
                        continue
                    rc_m = _grect(wel_m)
                    if rc_m and rc_m[2] <= 520.0 and rc_m[3] <= 420.0:
                        _walk_modal_btn(wel_m, 0)
                    elif _gs(wel_m, s_subrole).strip() in ("AXDialog", "AXSystemDialog"):
                        _walk_modal_btn(wel_m, 0)
                    else:
                        # Bắt luôn hộp thoại AXSheet ("Your session ended" / "Disconnected") gắn bên trong cửa sổ PC Hieu!
                        ch_sh = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(wel_m, s_children, ctypes.byref(ch_sh)) == 0 and ch_sh.value:
                            try:
                                for si in range(min(cf.CFArrayGetCount(ch_sh.value), 30)):
                                    sel_m = cf.CFArrayGetValueAtIndex(ch_sh.value, si)
                                    if sel_m and _gs(sel_m, s_role).strip() == "AXSheet":
                                        _walk_modal_btn(sel_m, 0)
                            finally:
                                cf.CFRelease(ch_sh.value)
            finally:
                cf.CFRelease(wm_arr.value)
        if hit_m[0]:
            time.sleep(0.25)
            return True
        dlg_rc = _has_small_modal_dialog()
        if dlg_rc is not None and q is not None:
            kd_r = q.CGEventCreateKeyboardEvent(None, 36, True)
            ku_r = q.CGEventCreateKeyboardEvent(None, 36, False)
            q.CGEventSetFlags(kd_r, 0)
            q.CGEventSetFlags(ku_r, 0)
            q.CGEventPost(q.kCGHIDEventTap, kd_r)
            q.CGEventPost(q.kCGHIDEventTap, ku_r)
            time.sleep(0.25)
            dlg_rc2 = _has_small_modal_dialog()
            if dlg_rc2 is not None:
                dx_m, dy_m, dw_m, dh_m = dlg_rc2
                _cg_click_once(dx_m + dw_m * 0.5, dy_m + dh_m - 62.0)
                time.sleep(0.22)
            return True
        return False

    try:
        t_low = target_title.strip().lower()
        # 0) Dọn hộp thoại Untitled (380x148) / Preferences cũ & hộp thoại xác nhận Disconnect (260x272 NSAlert) nếu đang treo sẵn!
        w_pre_clean = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_pre_clean)) == 0 and w_pre_clean.value:
            try:
                for wi in range(cf.CFArrayGetCount(w_pre_clean.value)):
                    wel_cl = cf.CFArrayGetValueAtIndex(w_pre_clean.value, wi)
                    if not wel_cl:
                        continue
                    wt_cl = _gs(wel_cl, s_title).strip().lower()
                    rc_cl = _grect(wel_cl)
                    if wt_cl in ("untitled", "add resolution", "custom resolution") and rc_cl and rc_cl[2] <= 430.0 and rc_cl[3] <= 220.0:
                        if q is not None:
                            ed_u = q.CGEventCreateKeyboardEvent(None, 53, True)
                            eu_u = q.CGEventCreateKeyboardEvent(None, 53, False)
                            q.CGEventPost(q.kCGHIDEventTap, ed_u)
                            q.CGEventPost(q.kCGHIDEventTap, eu_u)
                            time.sleep(0.15)
                for wi in range(cf.CFArrayGetCount(w_pre_clean.value)):
                    wel_cl = cf.CFArrayGetValueAtIndex(w_pre_clean.value, wi)
                    if not wel_cl:
                        continue
                    wt_cl = _gs(wel_cl, s_title).strip().lower()
                    if wt_cl in ("preferences", "settings", "resolutions", "general"):
                        br_cl = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(wel_cl, s_close, ctypes.byref(br_cl)) == 0 and br_cl.value:
                            try:
                                _ax_press_fast(br_cl.value, 0.45)
                            finally:
                                cf.CFRelease(br_cl.value)
            finally:
                cf.CFRelease(w_pre_clean)
        _dismiss_disconnect_modal()

        # Tọa độ giấu ngầm ở góc viền dưới-phải màn MacBook (chỉ chừa 2x2px sát góc bo đen vật lý -> 0px lộ trên màn hình nhưng vẫn giữ responder chain!)
        mx_m, my_m, mw_m, mh_m = 0.0, 0.0, 1512.0, 982.0
        if q is not None:
            try:
                mb_m = q.CGDisplayBounds(q.CGMainDisplayID())
                mx_m, my_m, mw_m, mh_m = float(mb_m.origin.x), float(mb_m.origin.y), float(mb_m.size.width), float(mb_m.size.height)
            except Exception:
                pass
        park_x, park_y = mx_m + mw_m - 2.0, my_m + mh_m - 2.0

        def _park_cc_offscreen() -> bool:
            ex_fs = False
            w_pk = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_pk)) == 0 and w_pk.value:
                try:
                    for wi in range(cf.CFArrayGetCount(w_pk.value)):
                        wel_k = cf.CFArrayGetValueAtIndex(w_pk.value, wi)
                        if not wel_k:
                            continue
                        wt_k = _gs(wel_k, s_title).strip().lower()
                        if not wt_k or wt_k in ("microsoft remote desktop", "windows app", "connection center", "pcs", "devices"):
                            if _gb(wel_k, s_fs):
                                ax.AXUIElementSetAttributeValue(wel_k, s_fs, kFalse)
                                ex_fs = True
                            pt_pk = _CGPoint(park_x, park_y)
                            vp_pk = ax.AXValueCreate(1, ctypes.byref(pt_pk))
                            if vp_pk:
                                ax.AXUIElementSetAttributeValue(wel_k, s_pos, vp_pk)
                                cf.CFRelease(vp_pk)
                finally:
                    cf.CFRelease(w_pk)
            return ex_fs

        def _move_cc_pos(px_c: float, py_c: float) -> None:
            w_mv = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_mv)) == 0 and w_mv.value:
                try:
                    for wi in range(cf.CFArrayGetCount(w_mv.value)):
                        wel_v = cf.CFArrayGetValueAtIndex(w_mv.value, wi)
                        if not wel_v:
                            continue
                        wt_v = _gs(wel_v, s_title).strip().lower()
                        if not wt_v or wt_v in ("microsoft remote desktop", "windows app", "connection center", "pcs", "devices"):
                            pt_mv = _CGPoint(px_c, py_c)
                            vp_mv = ax.AXValueCreate(1, ctypes.byref(pt_mv))
                            if vp_mv:
                                ax.AXUIElementSetAttributeValue(wel_v, s_pos, vp_mv)
                                cf.CFRelease(vp_mv)
                finally:
                    cf.CFRelease(w_mv)

        # 0B) Giấu sẵn Connection Center ra ngoài góc dưới-phải TRƯỚC KHI đóng PC Hieu để không bao giờ lộ bảng chọn trắng!
        _park_cc_offscreen()

        # 1) Đóng cửa sổ phiên đang mở của target_title (timeout 0.65s chống treo runModal + tự bấm Disconnect!)
        closed_sess = False
        w_arr = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_arr)) == 0 and w_arr.value:
            try:
                for wi in range(cf.CFArrayGetCount(w_arr.value)):
                    wel = cf.CFArrayGetValueAtIndex(w_arr.value, wi)
                    if not wel:
                        continue
                    wt = _gs(wel, s_title).strip().lower()
                    if wt == t_low or (t_low and t_low in wt and wt not in ("microsoft remote desktop", "windows app", "connection center")):
                        if not _gb(wel, s_fs):
                            rc_prev = _grect(wel)
                            if rc_prev is not None:
                                _save_user_1mon_bounds(rc_prev[0], rc_prev[1], rc_prev[2], rc_prev[3])
                        else:
                            ax.AXUIElementSetAttributeValue(wel, s_fs, kFalse)
                        b_ref = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(wel, s_close, ctypes.byref(b_ref)) == 0 and b_ref.value:
                            try:
                                _ax_press_fast(b_ref.value, 0.65)
                                closed_sess = True
                            finally:
                                cf.CFRelease(b_ref.value)
            finally:
                cf.CFRelease(w_arr.value)
        if closed_sess:
            time.sleep(0.22)
            _dismiss_disconnect_modal()
            time.sleep(0.35)
        else:
            if _click_menu_item(("window", "cửa sổ"), (t_low,)):
                time.sleep(0.12)
                if _click_menu_item(("window", "cửa sổ"), ("close", "đóng")):
                    closed_sess = True
                    time.sleep(0.22)
                    _dismiss_disconnect_modal()
                    time.sleep(0.35)

        # 2) Mở Connection Center ở vị trí giấu ngầm (park_x, park_y = 1510, 980) để bảng Edit PC chạy ngầm 100% ngoài màn hình!
        try:
            with objc.autorelease_pool():
                rapp_cc = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(rdp_pid)
                if rapp_cc is not None:
                    rapp_cc.unhide()
                    rapp_cc.activateWithOptions_(3)
        except Exception:
            pass
        _click_menu_item(("window", "cửa sổ"), ("connection center", "pcs"))
        # Đẩy ngay Connection Center vào góc giấu ngầm trong vòng < 10ms (nhỏ hơn 1 khung hình 60Hz -> không lộ 1 frame nào!)
        exited_cc_fs = False
        cc_ready = False
        for _ in range(18):
            w_cc = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_cc)) == 0 and w_cc.value:
                try:
                    for wi in range(cf.CFArrayGetCount(w_cc.value)):
                        wel = cf.CFArrayGetValueAtIndex(w_cc.value, wi)
                        if not wel:
                            continue
                        wt = _gs(wel, s_title).strip().lower()
                        if not wt or wt in ("microsoft remote desktop", "windows app", "connection center", "pcs", "devices"):
                            if _gb(wel, s_fs):
                                ax.AXUIElementSetAttributeValue(wel, s_fs, kFalse)
                                exited_cc_fs = True
                            pt_cc = _CGPoint(park_x, park_y)
                            vp_cc = ax.AXValueCreate(1, ctypes.byref(pt_cc))
                            if vp_cc:
                                ax.AXUIElementSetAttributeValue(wel, s_pos, vp_cc)
                                cf.CFRelease(vp_cc)
                            ax.AXUIElementSetAttributeValue(wel, s_main, kTrue)
                            ax.AXUIElementSetAttributeValue(wel, s_focused, kTrue)
                            ax.AXUIElementPerformAction(wel, s_raise)

                            def _ensure_pcs_tab(el_t: Any, depth_t: int) -> None:
                                if not el_t or depth_t > 12:
                                    return
                                if _gs(el_t, s_role).strip() == "AXRadioButton":
                                    lbl_t = (_gs(el_t, s_title) or _gs(el_t, s_desc)).strip().lower()
                                    if lbl_t in ("pcs", "icon view"):
                                        if _gi(el_t, s_val) == 0 and _gb(el_t, s_enabled):
                                            _ax_press_fast(el_t, 0.45)
                                        return
                                ch_t = ctypes.c_void_p()
                                if ax.AXUIElementCopyAttributeValue(el_t, s_children, ctypes.byref(ch_t)) == 0 and ch_t.value:
                                    try:
                                        for ci_t in range(min(cf.CFArrayGetCount(ch_t.value), 60)):
                                            _ensure_pcs_tab(cf.CFArrayGetValueAtIndex(ch_t.value, ci_t), depth_t + 1)
                                    finally:
                                        cf.CFRelease(ch_t.value)

                            _ensure_pcs_tab(wel, 0)
                            cc_ready = True
                finally:
                    cf.CFRelease(w_cc.value)
            if cc_ready:
                break
            time.sleep(0.01)
        time.sleep(0.06)
        if exited_cc_fs:
            time.sleep(0.85)
            _park_cc_offscreen()

        opened_edit = _click_menu_item(("connections", "connection"), ("edit pc", "edit pc...", "edit"))
        # Nếu chưa có thẻ nào được chọn sẵn trong Connection Center: bấm phím mũi tên Phải (vk=124) chọn thẻ đầu tiên hoàn toàn ngầm!
        if not opened_edit and q is not None:
            ra_d = q.CGEventCreateKeyboardEvent(None, 124, True)
            ra_u = q.CGEventCreateKeyboardEvent(None, 124, False)
            q.CGEventSetFlags(ra_d, 0)
            q.CGEventSetFlags(ra_u, 0)
            q.CGEventPost(q.kCGHIDEventTap, ra_d)
            q.CGEventPost(q.kCGHIDEventTap, ra_u)
            time.sleep(0.10)
            opened_edit = _click_menu_item(("connections", "connection"), ("edit pc", "edit pc...", "edit"))

        cands: List[Tuple[float, float, float, float]] = []
        vis_c = [0]
        if not opened_edit:
            # Dự phòng hiếm: kéo nhẹ lên chọn thẻ trong 0.1s rồi lập tức giấu lại về (park_x, park_y)
            _move_cc_pos(40.0, 60.0)
            time.sleep(0.08)

            def _find_card(el: Any, depth: int) -> None:
                if not el or depth > 18 or vis_c[0] > 2500:
                    return
                vis_c[0] += 1
                tx = (_gs(el, s_title) + " " + _gs(el, s_val) + " " + _gs(el, s_desc)).strip().lower()
                if (t_low and t_low in tx) or "192.168.52.230" in tx:
                    rc_b = _grect(el)
                    if rc_b and rc_b[2] >= 20.0 and rc_b[3] >= 12.0:
                        cands.append(rc_b)
                ch = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                    try:
                        nc = cf.CFArrayGetCount(ch.value)
                        for ci in range(min(nc, 80)):
                            _find_card(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                    finally:
                        cf.CFRelease(ch.value)

            for _ in range(4):
                cands.clear()
                vis_c[0] = 0
                w_scan = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_scan)) == 0 and w_scan.value:
                    try:
                        for wi in range(cf.CFArrayGetCount(w_scan.value)):
                            wel_s = cf.CFArrayGetValueAtIndex(w_scan.value, wi)
                            if wel_s:
                                ax.AXUIElementSetAttributeValue(wel_s, s_main, kTrue)
                                ax.AXUIElementSetAttributeValue(wel_s, s_focused, kTrue)
                                ax.AXUIElementPerformAction(wel_s, s_raise)
                                _find_card(wel_s, 0)
                    finally:
                        cf.CFRelease(w_scan.value)
                if cands:
                    break
                time.sleep(0.18)

            if cands:
                bx, by, bw, bh = cands[0]
                cx = bx + bw * 0.5
                cy1 = (by - 36.0) if (bh < 32.0 and by > 120.0) else (by + min(32.0, bh * 0.4))
                cy2 = by + bh * 0.5
                for cy_try in (cy1, cy2):
                    _cg_click_once(cx, cy_try)
                    time.sleep(0.16)
                    opened_edit = _click_menu_item(("connections", "connection"), ("edit pc", "edit pc...", "edit"))
                    if opened_edit:
                        break
                cy = cy1
                # Dự phòng: Chuột phải trực tiếp lên thẻ PC Hieu -> bấm "Edit" trong menu ngữ cảnh
                if not opened_edit and q is not None:
                    rd = q.CGEventCreateMouseEvent(None, q.kCGEventRightMouseDown, (cx, cy), q.kCGMouseButtonRight)
                    ru = q.CGEventCreateMouseEvent(None, q.kCGEventRightMouseUp, (cx, cy), q.kCGMouseButtonRight)
                    q.CGEventPost(q.kCGHIDEventTap, rd)
                    q.CGEventPost(q.kCGHIDEventTap, ru)
                    time.sleep(0.20)
                    ctx_ok = [False]

                    def _click_ctx_edit(el: Any, depth: int) -> None:
                        if not el or depth > 10 or ctx_ok[0]:
                            return
                        if _gs(el, s_role).strip() == "AXMenuItem":
                            mt = _gs(el, s_title).strip().lower()
                            if mt in ("edit", "edit...", "edit pc", "edit pc...", "chỉnh sửa") and _gb(el, s_enabled):
                                if ax.AXUIElementPerformAction(el, s_press) == 0:
                                    ctx_ok[0] = True
                                    return
                        ch = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                            try:
                                nc = cf.CFArrayGetCount(ch.value)
                                for ci in range(min(nc, 60)):
                                    _click_ctx_edit(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                                    if ctx_ok[0]:
                                        break
                            finally:
                                cf.CFRelease(ch.value)

                    _click_ctx_edit(app_ax, 0)
                    if ctx_ok[0]:
                        opened_edit = True
                    else:
                        # Đóng menu chuột phải nếu không khớp bằng phím Esc
                        esc_d = q.CGEventCreateKeyboardEvent(None, 53, True)
                        esc_u = q.CGEventCreateKeyboardEvent(None, 53, False)
                        q.CGEventPost(q.kCGHIDEventTap, esc_d)
                        q.CGEventPost(q.kCGHIDEventTap, esc_u)
            _park_cc_offscreen()

        _RDP_CLOSER_DIAG["ax_edit_trace"] = f"cands={len(cands)},vis={vis_c[0]},open={int(opened_edit)}"

        if opened_edit:
            time.sleep(0.25)

            # 3) Bấm sang tab "Display" trong bảng Edit PC (hỗ trợ cả khi đang giấu ngầm ngoài màn hình qua AXParent + kiểm chứng thật!)
            disp_tab_rects: List[Tuple[float, float, float, float]] = []
            pressed_disp = [False]

            def _click_display_tab(el: Any, depth: int) -> None:
                if not el or depth > 14 or pressed_disp[0]:
                    return
                rl = _gs(el, s_role).strip()
                tl = (_gs(el, s_title) or _gs(el, s_desc) or _gs(el, s_val)).strip().lower()
                if tl in ("display", "hiển thị"):
                    rb = _grect(el)
                    if rb and rb[2] >= 24.0 and rb[3] >= 14.0:
                        disp_tab_rects.append(rb)
                    if rl in ("AXRadioButton", "AXButton", "AXTab"):
                        ax.AXUIElementSetAttributeValue(el, s_sel_d, kTrue)
                        if _ax_press_fast(el, 0.40) == 0:
                            pressed_disp[0] = True
                            return
                    # Nếu chữ "Display" nằm trên AXStaticText con -> leo ngược lên AXParent (AXRadioButton/AXTab) để bấm AXPress ngầm!
                    cur_p = el
                    to_rel: List[int] = []
                    try:
                        for _ in range(2):
                            pr_ref = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(cur_p, s_parent_d, ctypes.byref(pr_ref)) == 0 and pr_ref.value:
                                to_rel.append(pr_ref.value)
                                cur_p = pr_ref.value
                                pr_rl = _gs(cur_p, s_role).strip()
                                if pr_rl in ("AXRadioButton", "AXButton", "AXTab"):
                                    ax.AXUIElementSetAttributeValue(cur_p, s_sel_d, kTrue)
                                    if _ax_press_fast(cur_p, 0.40) == 0:
                                        pressed_disp[0] = True
                                        return
                            else:
                                break
                    finally:
                        for rv in to_rel:
                            cf.CFRelease(rv)
                ch = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                    try:
                        nc = cf.CFArrayGetCount(ch.value)
                        for ci in range(min(nc, 80)):
                            _click_display_tab(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                            if pressed_disp[0]:
                                break
                    finally:
                        cf.CFRelease(ch.value)

            def _has_display_checkboxes() -> bool:
                found_cb = [False]

                def _chk_cb(el_c: Any, d_c: int) -> None:
                    if not el_c or d_c > 16 or found_cb[0]:
                        return
                    if _gs(el_c, s_role).strip() == "AXCheckBox":
                        ctl_c = (_gs(el_c, s_title) or _gs(el_c, s_desc)).strip().lower()
                        if "use all monitors" in ctl_c or "full screen" in ctl_c or "fit session" in ctl_c:
                            found_cb[0] = True
                            return
                    ch_c = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(el_c, s_children, ctypes.byref(ch_c)) == 0 and ch_c.value:
                        try:
                            for ci_c in range(min(cf.CFArrayGetCount(ch_c.value), 80)):
                                _chk_cb(cf.CFArrayGetValueAtIndex(ch_c.value, ci_c), d_c + 1)
                                if found_cb[0]:
                                    break
                        finally:
                            cf.CFRelease(ch_c.value)

                w_ck = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_ck)) == 0 and w_ck.value:
                    try:
                        for wi_k in range(cf.CFArrayGetCount(w_ck.value)):
                            _chk_cb(cf.CFArrayGetValueAtIndex(w_ck.value, wi_k), 0)
                    finally:
                        cf.CFRelease(w_ck.value)
                return found_cb[0]

            def _ensure_display_tab_switched() -> None:
                pressed_disp[0] = False
                disp_tab_rects.clear()
                w_t = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_t)) == 0 and w_t.value:
                    try:
                        for wi in range(cf.CFArrayGetCount(w_t.value)):
                            _click_display_tab(cf.CFArrayGetValueAtIndex(w_t.value, wi), 0)
                    finally:
                        cf.CFRelease(w_t.value)
                time.sleep(0.14)
                if not _has_display_checkboxes():
                    # Dự phòng chắc chắn 100%: nhích vào click trúng tab Display trong 0.14s rồi lập tức giấu lại về (1510, 980)!
                    _move_cc_pos(40.0, 60.0)
                    time.sleep(0.16)
                    disp_tab_rects.clear()
                    w_t2 = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_t2)) == 0 and w_t2.value:
                        try:
                            for wi in range(cf.CFArrayGetCount(w_t2.value)):
                                _click_display_tab(cf.CFArrayGetValueAtIndex(w_t2.value, wi), 0)
                        finally:
                            cf.CFRelease(w_t2.value)
                    if disp_tab_rects:
                        rx, ry, rw, rh = disp_tab_rects[0]
                        _cg_click_once(rx + rw * 0.5, ry + rh * 0.5)
                        time.sleep(0.14)
                    _park_cc_offscreen()

            try:
                _ensure_display_tab_switched()
            finally:
                pass

            # 4) Chỉnh các ô tích trong tab Display theo đúng thứ tự mở khóa phụ thuộc
            cb_logs: List[str] = []

            def _apply_checkbox_pass(rules: List[Tuple[Tuple[str, ...], bool]]) -> int:
                toggled = [0]

                def _walk_cb(el: Any, depth: int) -> None:
                    if not el or depth > 16:
                        return
                    if _gs(el, s_role).strip() == "AXCheckBox":
                        ct = (_gs(el, s_title) or _gs(el, s_desc)).strip()
                        ctl = ct.lower()
                        en = _gb(el, s_enabled)
                        cv = _gi(el, s_val)
                        for kw_set, want_b in rules:
                            if any(k in ctl for k in kw_set):
                                if en and bool(cv) != bool(want_b):
                                    ax.AXUIElementPerformAction(el, s_press)
                                    toggled[0] += 1
                                    cb_logs.append(f"{ct}:{cv}->{int(want_b)}")
                                else:
                                    cb_logs.append(f"{ct}:ok={cv}(e={int(en)})")
                                break
                    ch = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                        try:
                            nc = cf.CFArrayGetCount(ch.value)
                            for ci in range(min(nc, 80)):
                                _walk_cb(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                        finally:
                            cf.CFRelease(ch.value)

                w_c = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_c)) == 0 and w_c.value:
                    try:
                        for wi in range(cf.CFArrayGetCount(w_c.value)):
                            _walk_cb(cf.CFArrayGetValueAtIndex(w_c.value, wi), 0)
                    finally:
                        cf.CFRelease(w_c.value)
                return toggled[0]

            # CHỈ bật/tắt đúng 2 cờ 1 màn <-> 2 màn; TUYỆT ĐỐI KHÔNG động vào độ phân giải, Retina, Fit hay Preferences mà người dùng đã tự cài!
            _apply_checkbox_pass([
                (("use all monitors",), bool(enable_multimon)),
            ])
            time.sleep(0.08)
            _apply_checkbox_pass([
                (("start session in full screen", "in full screen"), bool(enable_multimon)),
            ])
            _RDP_CLOSER_DIAG["edit_pc_checkboxes"] = cb_logs[-12:]

            if False and not enable_multimon:
                want_rw, want_rh, _, _, _, _ = _compute_exact_1mon_retina_res(q)
                alt_rh = want_rh - (want_rh % 8)
                w_str, h_str, alt_h_str = str(want_rw), str(want_rh), str(alt_rh)

                def _try_pick_resolution_popup() -> Tuple[bool, List[str]]:
                    pop_rects: List[Tuple[float, float, float, float]] = []
                    already_has = [False]
                    found_in_menu = [False]
                    item_rects: List[Tuple[float, float, float, float]] = []
                    seen_items: List[str] = []

                    def _is_res_pop_el(el: Any) -> Tuple[bool, str]:
                        if _gs(el, s_role).strip() not in ("AXPopUpButton", "AXComboBox") or not _gb(el, s_enabled):
                            return False, ""
                        cur_txt = (_gs(el, s_val) + " " + _gs(el, s_title)).strip()
                        cl = cur_txt.lower()
                        bad_p = (
                            "bit" in cl or "color" in cl or "gateway" in cl or "%" in cl
                            or "\\" in cl or "ask when" in cl or "add user" in cl or "never" in cl
                        )
                        return (not bad_p), cur_txt

                    def _read_res_pop_val() -> str:
                        out_v = [""]

                        def _w_val(el: Any, depth: int) -> None:
                            if not el or depth > 16 or out_v[0]:
                                return
                            ok_p, ct_p = _is_res_pop_el(el)
                            if ok_p:
                                out_v[0] = ct_p
                                return
                            ch = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                                try:
                                    for ci in range(min(cf.CFArrayGetCount(ch.value), 80)):
                                        _w_val(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                                        if out_v[0]:
                                            break
                                finally:
                                    cf.CFRelease(ch.value)

                        wv_w = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wv_w)) == 0 and wv_w.value:
                            try:
                                for wi in range(cf.CFArrayGetCount(wv_w.value)):
                                    _w_val(cf.CFArrayGetValueAtIndex(wv_w.value, wi), 0)
                            finally:
                                cf.CFRelease(wv_w.value)
                        return out_v[0]

                    def _scan_menu_items(el: Any, depth: int) -> None:
                        if not el or depth > 18 or found_in_menu[0]:
                            return
                        rl_i = _gs(el, s_role).strip()
                        if rl_i == "AXMenuBar":
                            return
                        if rl_i == "AXMenuItem":
                            mt = _gs(el, s_title).strip()
                            if mt and mt not in seen_items:
                                seen_items.append(mt)
                            if w_str in mt and (h_str in mt or alt_h_str in mt):
                                found_in_menu[0] = True
                                ir = _grect(el)
                                if ir and ir[2] >= 20.0 and 0.0 <= ir[1] <= 965.0:
                                    item_rects.append(ir)
                                return
                        ch = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                            try:
                                nc = cf.CFArrayGetCount(ch.value)
                                for ci in range(min(nc, 80)):
                                    _scan_menu_items(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                                    if found_in_menu[0]:
                                        break
                            finally:
                                cf.CFRelease(ch.value)

                    direct_pressed = [False]

                    def _try_silent_pop_item(el_m: Any, d_m: int) -> None:
                        if not el_m or d_m > 6 or direct_pressed[0]:
                            return
                        if _gs(el_m, s_role).strip() == "AXMenuItem":
                            mt_d = _gs(el_m, s_title).strip()
                            if w_str in mt_d and (h_str in mt_d or alt_h_str in mt_d):
                                if _ax_press_fast(el_m, 0.35) == 0:
                                    direct_pressed[0] = True
                                    return
                        ch_m = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el_m, s_children, ctypes.byref(ch_m)) == 0 and ch_m.value:
                            try:
                                for ci_m in range(min(cf.CFArrayGetCount(ch_m.value), 80)):
                                    _try_silent_pop_item(cf.CFArrayGetValueAtIndex(ch_m.value, ci_m), d_m + 1)
                                    if direct_pressed[0]:
                                        break
                            finally:
                                cf.CFRelease(ch_m.value)

                    def _find_res_pop_rect(el: Any, depth: int) -> None:
                        if not el or depth > 16 or already_has[0] or pop_rects:
                            return
                        ok_p, cur_txt = _is_res_pop_el(el)
                        if ok_p:
                            if w_str in cur_txt and (h_str in cur_txt or alt_h_str in cur_txt):
                                already_has[0] = True
                                return
                            # Ưu tiên bấm AXPress thẳng vào AXMenuItem con của NSPopUpButton mà KHÔNG bung popup menu lên màn hình!
                            _try_silent_pop_item(el, 0)
                            rc_p = _grect(el)
                            if rc_p:
                                pop_rects.append(rc_p)
                            return
                        ch = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                            try:
                                for ci in range(min(cf.CFArrayGetCount(ch.value), 80)):
                                    _find_res_pop_rect(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                                    if already_has[0] or pop_rects:
                                        break
                            finally:
                                cf.CFRelease(ch.value)

                    def _open_res_pop_offscreen_ax(el: Any, depth: int, opened_f: List[bool], s_sm: Any) -> None:
                        if not el or depth > 16 or opened_f[0]:
                            return
                        ok_p, _ = _is_res_pop_el(el)
                        if ok_p:
                            ax.AXUIElementSetAttributeValue(el, s_focused, kTrue)
                            _set_tmo(el, 0.30)
                            rc_sm = ax.AXUIElementPerformAction(el, s_sm) if s_sm else -1
                            if rc_sm != 0:
                                ax.AXUIElementPerformAction(el, s_press)
                            opened_f[0] = True
                            return
                        ch = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                            try:
                                for ci in range(min(cf.CFArrayGetCount(ch.value), 80)):
                                    _open_res_pop_offscreen_ax(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1, opened_f, s_sm)
                                    if opened_f[0]:
                                        break
                            finally:
                                cf.CFRelease(ch.value)

                    wp_w = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_w)) == 0 and wp_w.value:
                        try:
                            for wi in range(cf.CFArrayGetCount(wp_w.value)):
                                _find_res_pop_rect(cf.CFArrayGetValueAtIndex(wp_w.value, wi), 0)
                        finally:
                            cf.CFRelease(wp_w.value)
                    if already_has[0]:
                        return True, ["already"]
                    if direct_pressed[0]:
                        time.sleep(0.32)
                        v_dir = _read_res_pop_val()
                        if w_str in v_dir and (h_str in v_dir or alt_h_str in v_dir):
                            return True, ["silent_ax_item", f"val={v_dir}"]
                    if not pop_rects:
                        return False, ["no_popup"]

                    pr0 = pop_rects[0]
                    is_offscreen_pop = (pr0[0] >= mx_m + mw_m - 6.0) or (pr0[1] >= my_m + mh_m - 6.0)
                    s_sm_ref = _cfstr("AXShowMenu")
                    try:
                        if is_offscreen_pop:
                            op_f = [False]
                            wp_ax = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_ax)) == 0 and wp_ax.value:
                                try:
                                    for wi in range(cf.CFArrayGetCount(wp_ax.value)):
                                        _open_res_pop_offscreen_ax(cf.CFArrayGetValueAtIndex(wp_ax.value, wi), 0, op_f, s_sm_ref)
                                finally:
                                    cf.CFRelease(wp_ax.value)
                        else:
                            _cg_click_once(pr0[0] + pr0[2] * 0.5, pr0[1] + pr0[3] * 0.5)
                        time.sleep(0.16)
                        wp_m = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_m)) == 0 and wp_m.value:
                            try:
                                for wi in range(cf.CFArrayGetCount(wp_m.value)):
                                    _scan_menu_items(cf.CFArrayGetValueAtIndex(wp_m.value, wi), 0)
                            finally:
                                cf.CFRelease(wp_m.value)

                        # Nếu macOS không cho bung NSMenu khi cửa sổ đang giấu ngoài mép -> nhích nhẹ vào chọn trong 0.2s rồi giấu lại ngay lập tức!
                        slid_temp = False
                        if not found_in_menu[0] and is_offscreen_pop:
                            _move_cc_pos(40.0, 60.0)
                            slid_temp = True
                            time.sleep(0.22)
                            pop_rects.clear()
                            seen_items.clear()
                            item_rects.clear()
                            wp_w2 = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_w2)) == 0 and wp_w2.value:
                                try:
                                    for wi in range(cf.CFArrayGetCount(wp_w2.value)):
                                        _find_res_pop_rect(cf.CFArrayGetValueAtIndex(wp_w2.value, wi), 0)
                                finally:
                                    cf.CFRelease(wp_w2.value)
                            if pop_rects:
                                pr0 = pop_rects[0]
                                _cg_click_once(pr0[0] + pr0[2] * 0.5, pr0[1] + pr0[3] * 0.5)
                                time.sleep(0.18)
                                wp_m2 = ctypes.c_void_p()
                                if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_m2)) == 0 and wp_m2.value:
                                    try:
                                        for wi in range(cf.CFArrayGetCount(wp_m2.value)):
                                            _scan_menu_items(cf.CFArrayGetValueAtIndex(wp_m2.value, wi), 0)
                                    finally:
                                        cf.CFRelease(wp_m2.value)
                    finally:
                        if s_sm_ref:
                            cf.CFRelease(s_sm_ref)

                    if not found_in_menu[0]:
                        if q is not None:
                            esc_d = q.CGEventCreateKeyboardEvent(None, 53, True)
                            esc_u = q.CGEventCreateKeyboardEvent(None, 53, False)
                            q.CGEventPost(q.kCGHIDEventTap, esc_d)
                            q.CGEventPost(q.kCGHIDEventTap, esc_u)
                            time.sleep(0.08)
                        _park_cc_offscreen()
                        # CHỈ báo missing_item khi menu thực sự đã mở và liệt kê >= 3 độ phân giải mà chưa có 3024x1832!
                        if len(seen_items) >= 3:
                            return False, ["missing_item"] + seen_items[-6:]
                        return False, ["menu_not_opened"] + seen_items[-6:]

                    after_v = ""
                    # Cách 1: Click trực tiếp tâm dòng "3024 x 1832" ngay khi menu đang mở, giấu lại ngay và chờ 0.45s commit Cocoa Binding!
                    if item_rects:
                        ir0 = item_rects[0]
                        _cg_click_once(ir0[0] + ir0[2] * 0.5, ir0[1] + ir0[3] * 0.5)
                        if slid_temp:
                            _park_cc_offscreen()
                        time.sleep(0.45)
                        after_v = _read_res_pop_val()

                    # Cách 2: Option+Up về dòng đầu -> bấm Down đúng số dòng -> Enter!
                    if (w_str not in after_v or (h_str not in after_v and alt_h_str not in after_v)) and q is not None:
                        if not is_offscreen_pop or slid_temp:
                            _cg_click_once(pr0[0] + pr0[2] * 0.5, pr0[1] + pr0[3] * 0.5)
                            time.sleep(0.16)
                        up_d = q.CGEventCreateKeyboardEvent(None, 126, True)
                        up_u = q.CGEventCreateKeyboardEvent(None, 126, False)
                        q.CGEventSetFlags(up_d, q.kCGEventFlagMaskAlternate | 0x00000020)
                        q.CGEventSetFlags(up_u, q.kCGEventFlagMaskAlternate | 0x00000020)
                        q.CGEventPost(q.kCGHIDEventTap, up_d)
                        q.CGEventPost(q.kCGHIDEventTap, up_u)
                        time.sleep(0.05)
                        steps_down = max(0, len(seen_items) - 1)
                        for _ in range(steps_down):
                            dn_d = q.CGEventCreateKeyboardEvent(None, 125, True)
                            dn_u = q.CGEventCreateKeyboardEvent(None, 125, False)
                            q.CGEventSetFlags(dn_d, 0)
                            q.CGEventSetFlags(dn_u, 0)
                            q.CGEventPost(q.kCGHIDEventTap, dn_d)
                            q.CGEventPost(q.kCGHIDEventTap, dn_u)
                            time.sleep(0.012)
                        time.sleep(0.05)
                        ret_d = q.CGEventCreateKeyboardEvent(None, 36, True)
                        ret_u = q.CGEventCreateKeyboardEvent(None, 36, False)
                        q.CGEventSetFlags(ret_d, 0)
                        q.CGEventSetFlags(ret_u, 0)
                        q.CGEventPost(q.kCGHIDEventTap, ret_d)
                        q.CGEventPost(q.kCGHIDEventTap, ret_u)
                        _park_cc_offscreen()
                        time.sleep(0.42)
                        after_v = _read_res_pop_val()

                    _park_cc_offscreen()
                    ok_sel = (w_str in after_v and (h_str in after_v or alt_h_str in after_v))
                    if not ok_sel and q is not None:
                        esc_d2 = q.CGEventCreateKeyboardEvent(None, 53, True)
                        esc_u2 = q.CGEventCreateKeyboardEvent(None, 53, False)
                        q.CGEventPost(q.kCGHIDEventTap, esc_d2)
                        q.CGEventPost(q.kCGHIDEventTap, esc_u2)
                        time.sleep(0.10)
                    return ok_sel, seen_items[-5:] + [f"val={after_v}"]

                res_ok, res_items = _try_pick_resolution_popup()
                if not res_ok and ("missing_item" in res_items):
                    # Chưa có 3024 x 1834 trong danh sách -> mở Preferences -> Resolutions thêm tự động 1 lần duy nhất!
                    def _cancel_cur_sheet(el: Any, depth: int, done_f: List[bool]) -> None:
                        if not el or depth > 14 or done_f[0]:
                            return
                        if _gs(el, s_role).strip() == "AXButton" and _gs(el, s_title).strip().lower() in ("cancel", "hủy"):
                            if ax.AXUIElementPerformAction(el, s_press) == 0:
                                done_f[0] = True
                                return
                        ch = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                            try:
                                for ci in range(min(cf.CFArrayGetCount(ch.value), 80)):
                                    _cancel_cur_sheet(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1, done_f)
                                    if done_f[0]:
                                        break
                            finally:
                                cf.CFRelease(ch.value)

                    c_done = [False]
                    wc_tmp = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wc_tmp)) == 0 and wc_tmp.value:
                        try:
                            for wi in range(cf.CFArrayGetCount(wc_tmp.value)):
                                _cancel_cur_sheet(cf.CFArrayGetValueAtIndex(wc_tmp.value, wi), 0, c_done)
                        finally:
                            cf.CFRelease(wc_tmp.value)
                    time.sleep(0.18)

                    # Mở Preferences qua Menu Bar (dự phòng Cmd + ,) — độc lập hoàn toàn với bộ gõ Telex
                    _DIGIT_VK = {"0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25}
                    _PREF_WIN_TITLES = ("preferences", "settings", "general", "resolutions", "user accounts", "gateways")

                    def _cg_tap_vk(vk_code: int, cmd_flag: bool = False) -> None:
                        if q is None:
                            return
                        kd = q.CGEventCreateKeyboardEvent(None, vk_code, True)
                        ku = q.CGEventCreateKeyboardEvent(None, vk_code, False)
                        fl = (q.kCGEventFlagMaskCommand | 0x00000008) if cmd_flag else 0
                        q.CGEventSetFlags(kd, fl)
                        q.CGEventSetFlags(ku, fl)
                        q.CGEventPost(q.kCGHIDEventTap, kd)
                        q.CGEventPost(q.kCGHIDEventTap, ku)

                    opened_pref_menu = _click_menu_item(
                        ("microsoft remote desktop", "windows app"),
                        ("preferences...", "preferences\u2026", "settings...", "settings\u2026", "preferences", "settings"),
                    )
                    if not opened_pref_menu:
                        _cg_tap_vk(43, cmd_flag=True)
                    time.sleep(0.30)

                    # Bấm tab "Resolutions" trong cửa sổ Preferences/Settings
                    res_tab_ok = [False]
                    res_tab_rc: List[Tuple[float, float, float, float]] = []
                    pref_win_rc: List[Tuple[float, float, float, float]] = []

                    def _find_resolutions_tab(el: Any, depth: int) -> None:
                        if not el or depth > 12 or res_tab_ok[0]:
                            return
                        rl = _gs(el, s_role).strip()
                        tl = (_gs(el, s_title) or _gs(el, s_desc) or _gs(el, s_val)).strip().lower()
                        if "resolution" in tl:
                            rb = _grect(el)
                            if rb and rb[2] >= 20.0 and rb[3] >= 14.0:
                                res_tab_rc.append(rb)
                            if rl in ("AXButton", "AXRadioButton", "AXTab"):
                                if ax.AXUIElementPerformAction(el, s_press) == 0:
                                    res_tab_ok[0] = True
                                    return
                        ch = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                            try:
                                for ci in range(min(cf.CFArrayGetCount(ch.value), 80)):
                                    _find_resolutions_tab(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                                    if res_tab_ok[0]:
                                        break
                            finally:
                                cf.CFRelease(ch.value)

                    wp_p = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_p)) == 0 and wp_p.value:
                        try:
                            for wi in range(cf.CFArrayGetCount(wp_p.value)):
                                wel_p = cf.CFArrayGetValueAtIndex(wp_p.value, wi)
                                if wel_p and _gs(wel_p, s_title).strip().lower() in _PREF_WIN_TITLES:
                                    pt_pf = _CGPoint(200.0, 110.0)
                                    vp_pf = ax.AXValueCreate(1, ctypes.byref(pt_pf))
                                    if vp_pf:
                                        ax.AXUIElementSetAttributeValue(wel_p, s_pos, vp_pf)
                                        cf.CFRelease(vp_pf)
                                    ax.AXUIElementSetAttributeValue(wel_p, s_main, kTrue)
                                    ax.AXUIElementSetAttributeValue(wel_p, s_focused, kTrue)
                                    ax.AXUIElementPerformAction(wel_p, s_raise)
                                    prc = _grect(wel_p)
                                    if prc:
                                        pref_win_rc.append(prc)
                                    _find_resolutions_tab(wel_p, 0)
                        finally:
                            cf.CFRelease(wp_p.value)
                    if not res_tab_ok[0] and res_tab_rc:
                        rx, ry, rw_b, rh_b = res_tab_rc[0]
                        _cg_click_once(rx + rw_b * 0.5, ry + rh_b * 0.5)
                        res_tab_ok[0] = True
                    time.sleep(0.22)

                    # Bấm nút "+" thêm độ phân giải mới (ưu tiên khớp tên "+"/"add", dự phòng nút nhỏ bên trái nhất ở chân bảng)
                    # Bấm nút "+" BẰNG CLICK CHUỘT THẬT (_cg_click_once) — TUYỆT ĐỐI KHÔNG gọi AXPress lên "+" vì runModalForWindow: sẽ khóa cổng Mach Accessibility!
                    plus_ok = [False]
                    plus_exact_btns: List[Tuple[float, float, float, float]] = []
                    footer_small_btns: List[Tuple[float, float, float, float]] = []
                    py_min = (pref_win_rc[0][1] + pref_win_rc[0][3] * 0.55) if pref_win_rc else 420.0

                    def _find_plus_btn_rect(el: Any, depth: int) -> None:
                        if not el or depth > 14 or plus_exact_btns:
                            return
                        if _gs(el, s_role).strip() == "AXButton" and _gb(el, s_enabled):
                            bt = _gs(el, s_title).strip()
                            bd = _gs(el, s_desc).strip().lower()
                            rb = _grect(el)
                            if rb and (bt == "+" or bt.lower() == "add" or "add" in bd):
                                plus_exact_btns.append(rb)
                                return
                            if bt == "" and rb and 14.0 <= rb[2] <= 42.0 and 14.0 <= rb[3] <= 36.0 and rb[1] >= py_min:
                                footer_small_btns.append(rb)
                        ch = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                            try:
                                for ci in range(min(cf.CFArrayGetCount(ch.value), 80)):
                                    _find_plus_btn_rect(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                                    if plus_exact_btns:
                                        break
                            finally:
                                cf.CFRelease(ch.value)

                    wp_pl = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_pl)) == 0 and wp_pl.value:
                        try:
                            for wi in range(cf.CFArrayGetCount(wp_pl.value)):
                                wel_p = cf.CFArrayGetValueAtIndex(wp_pl.value, wi)
                                if wel_p and _gs(wel_p, s_title).strip().lower() in _PREF_WIN_TITLES:
                                    _find_plus_btn_rect(wel_p, 0)
                        finally:
                            cf.CFRelease(wp_pl.value)
                    chosen_plus = plus_exact_btns[0] if plus_exact_btns else None
                    if chosen_plus is None and footer_small_btns:
                        footer_small_btns.sort(key=lambda r: (round(r[1] / 20.0), r[0]))
                        chosen_plus = footer_small_btns[0]
                    if chosen_plus is not None:
                        try:
                            subprocess.run(["open", "-a", app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.5)
                        except Exception:
                            pass
                        time.sleep(0.10)
                        _cg_click_once(chosen_plus[0] + chosen_plus[2] * 0.5, chosen_plus[1] + chosen_plus[3] * 0.5)
                        plus_ok[0] = True
                    time.sleep(0.28)

                    # Cửa sổ nhập độ phân giải mới của MRD 10.9.10 là cửa sổ modal riêng tên "Untitled" (380x148)!
                    _MODAL_RES_TITLES = ("untitled", "add resolution", "custom resolution", "")
                    tf_rects: List[Tuple[float, float, float, float]] = []

                    def _collect_tfs(el: Any, depth: int) -> None:
                        if not el or depth > 16:
                            return
                        if _gs(el, s_role).strip() == "AXTextField":
                            rb = _grect(el)
                            if rb and rb[2] >= 30.0 and rb[3] >= 14.0:
                                tf_rects.append(rb)
                        ch = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                            try:
                                for ci in range(min(cf.CFArrayGetCount(ch.value), 80)):
                                    _collect_tfs(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                            finally:
                                cf.CFRelease(ch.value)

                    wp_tf = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_tf)) == 0 and wp_tf.value:
                        try:
                            for wi in range(cf.CFArrayGetCount(wp_tf.value)):
                                wel_u = cf.CFArrayGetValueAtIndex(wp_tf.value, wi)
                                if not wel_u:
                                    continue
                                wtu = _gs(wel_u, s_title).strip().lower()
                                rcu = _grect(wel_u)
                                if wtu in _MODAL_RES_TITLES and rcu and rcu[2] <= 540.0 and rcu[3] <= 340.0:
                                    ax.AXUIElementSetAttributeValue(wel_u, s_main, kTrue)
                                    ax.AXUIElementSetAttributeValue(wel_u, s_focused, kTrue)
                                    ax.AXUIElementPerformAction(wel_u, s_raise)
                                    _collect_tfs(wel_u, 0)
                            if len(tf_rects) < 2:
                                tf_rects.clear()
                                for wi in range(cf.CFArrayGetCount(wp_tf.value)):
                                    wel_p = cf.CFArrayGetValueAtIndex(wp_tf.value, wi)
                                    if wel_p and _gs(wel_p, s_title).strip().lower() in _PREF_WIN_TITLES:
                                        _collect_tfs(wel_p, 0)
                        finally:
                            cf.CFRelease(wp_tf.value)
                    tf_rects.sort(key=lambda r: (round(r[1] / 24.0), r[0]))
                    confirmed_add = [False]
                    pref_btns: List[str] = []

                    def _type_into_tf(tf_rc: Tuple[float, float, float, float], digits_txt: str) -> None:
                        _cg_click_once(tf_rc[0] + tf_rc[2] * 0.5, tf_rc[1] + tf_rc[3] * 0.5)
                        time.sleep(0.05)
                        _cg_tap_vk(0, cmd_flag=True)
                        _cg_tap_vk(51)
                        time.sleep(0.03)
                        injector._quartz_post_unicode(digits_txt)
                        time.sleep(0.04)
                        _cg_tap_vk(48)
                        time.sleep(0.07)

                    tf_cnt = len(tf_rects)
                    if tf_cnt >= 2:
                        r0, r1 = tf_rects[0], tf_rects[1]
                        for try_h in (h_str, alt_h_str):
                            pref_btns.clear()
                            _type_into_tf(r0, w_str)
                            _type_into_tf(r1, try_h)

                            def _click_confirm_add(el: Any, depth: int, allow_any_non_cancel: bool) -> None:
                                if not el or depth > 16 or confirmed_add[0]:
                                    return
                                if _gs(el, s_role).strip() == "AXButton":
                                    bt_raw = _gs(el, s_title).strip()
                                    bt_c = bt_raw.lower()
                                    en_c = _gb(el, s_enabled)
                                    rb_c = _grect(el)
                                    if bt_raw:
                                        pref_btns.append(f"{bt_raw}:{int(en_c)}")
                                    if en_c:
                                        if bt_c in ("add", "ok", "create", "save", "done", "confirm", "apply", "thêm"):
                                            if rb_c:
                                                _cg_click_once(rb_c[0] + rb_c[2] * 0.5, rb_c[1] + rb_c[3] * 0.5)
                                                confirmed_add[0] = True
                                                return
                                            if _ax_press_fast(el, 0.50) in (0, -25204):
                                                confirmed_add[0] = True
                                                return
                                        elif allow_any_non_cancel and bt_raw and bt_c not in ("cancel", "hủy", "close") and rb_c and rb_c[2] >= 45.0:
                                            _cg_click_once(rb_c[0] + rb_c[2] * 0.5, rb_c[1] + rb_c[3] * 0.5)
                                            confirmed_add[0] = True
                                            return
                                ch = ctypes.c_void_p()
                                if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                                    try:
                                        for ci in range(min(cf.CFArrayGetCount(ch.value), 80)):
                                            _click_confirm_add(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1, allow_any_non_cancel)
                                            if confirmed_add[0]:
                                                break
                                    finally:
                                        cf.CFRelease(ch.value)

                            wp_cf = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_cf)) == 0 and wp_cf.value:
                                try:
                                    for wi in range(cf.CFArrayGetCount(wp_cf.value)):
                                        wel_u = cf.CFArrayGetValueAtIndex(wp_cf.value, wi)
                                        if not wel_u:
                                            continue
                                        wtu = _gs(wel_u, s_title).strip().lower()
                                        rcu = _grect(wel_u)
                                        if wtu in _MODAL_RES_TITLES and rcu and rcu[2] <= 540.0 and rcu[3] <= 340.0:
                                            _click_confirm_add(wel_u, 0, True)
                                    # AXSheet thêm độ phân giải nằm bên trong AXChildren của cửa sổ Preferences!
                                    if not confirmed_add[0]:
                                        for wi in range(cf.CFArrayGetCount(wp_cf.value)):
                                            wel_p = cf.CFArrayGetValueAtIndex(wp_cf.value, wi)
                                            if wel_p and _gs(wel_p, s_title).strip().lower() in _PREF_WIN_TITLES:
                                                _click_confirm_add(wel_p, 0, False)
                                finally:
                                    cf.CFRelease(wp_cf.value)
                            if confirmed_add[0] or try_h == alt_h_str:
                                break
                        if not confirmed_add[0]:
                            _cg_tap_vk(53)
                            time.sleep(0.15)
                        time.sleep(0.20)
                    _RDP_CLOSER_DIAG["pref_btns_seen"] = pref_btns[-10:]

                    # Đóng cửa sổ Preferences
                    wp_cl = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wp_cl)) == 0 and wp_cl.value:
                        try:
                            for wi in range(cf.CFArrayGetCount(wp_cl.value)):
                                wel_p = cf.CFArrayGetValueAtIndex(wp_cl.value, wi)
                                if wel_p and _gs(wel_p, s_title).strip().lower() in _PREF_WIN_TITLES:
                                    br_p = ctypes.c_void_p()
                                    if ax.AXUIElementCopyAttributeValue(wel_p, s_close, ctypes.byref(br_p)) == 0 and br_p.value:
                                        try:
                                            ax.AXUIElementPerformAction(br_p.value, s_press)
                                        finally:
                                            cf.CFRelease(br_p.value)
                        finally:
                            cf.CFRelease(wp_cl.value)
                    time.sleep(0.18)

                    # Mở lại Edit PC -> Display -> chọn 3024 x 1834
                    _click_menu_item(("window", "cửa sổ"), ("connection center", "pcs"))
                    time.sleep(0.15)
                    reopened_edit = _click_menu_item(("connections", "connection"), ("edit pc", "edit pc...", "edit"))
                    if not reopened_edit:
                        re_cands: List[Tuple[float, float, float, float]] = list(cands)
                        if not re_cands:
                            def _find_card_re(el: Any, depth: int) -> None:
                                if not el or depth > 18 or len(re_cands) >= 2:
                                    return
                                tx = (_gs(el, s_title) + " " + _gs(el, s_val) + " " + _gs(el, s_desc)).strip().lower()
                                if (t_low and t_low in tx) or "192.168.52.230" in tx:
                                    rc_b = _grect(el)
                                    if rc_b and rc_b[2] >= 20.0 and rc_b[3] >= 12.0:
                                        re_cands.append(rc_b)
                                ch = ctypes.c_void_p()
                                if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                                    try:
                                        for ci in range(min(cf.CFArrayGetCount(ch.value), 80)):
                                            _find_card_re(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                                    finally:
                                        cf.CFRelease(ch.value)

                            ws_re = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(ws_re)) == 0 and ws_re.value:
                                try:
                                    for wi in range(cf.CFArrayGetCount(ws_re.value)):
                                        _find_card_re(cf.CFArrayGetValueAtIndex(ws_re.value, wi), 0)
                                finally:
                                    cf.CFRelease(ws_re.value)
                        if re_cands:
                            bx_r, by_r, bw_r, bh_r = re_cands[0]
                            cx_r = bx_r + bw_r * 0.5
                            cy_r = (by_r - 36.0) if (bh_r < 32.0 and by_r > 120.0) else (by_r + min(32.0, bh_r * 0.4))
                            _cg_click_once(cx_r, cy_r)
                            time.sleep(0.18)
                            reopened_edit = _click_menu_item(("connections", "connection"), ("edit pc", "edit pc...", "edit"))
                    if reopened_edit:
                        time.sleep(0.22)
                        _ensure_display_tab_switched()
                        _apply_checkbox_pass([
                            (("use all monitors",), False),
                            (("update session resolution", "on resize"), False),
                        ])
                        time.sleep(0.08)
                        _apply_checkbox_pass([
                            (("start session in full screen", "in full screen"), False),
                            (("optimize for retina", "retina"), False),
                        ])
                        time.sleep(0.08)
                        _apply_checkbox_pass([
                            (("fit session to window",), True),
                        ])
                        res_ok, res_items = _try_pick_resolution_popup()
                    _RDP_CLOSER_DIAG["pref_res_trace"] = f"pm={int(opened_pref_menu)},tab={int(res_tab_ok[0])},plus={int(plus_ok[0])},tf={tf_cnt},add={int(confirmed_add[0])}"

                _RDP_CLOSER_DIAG["res_sync_trace"] = f"want={w_str}x{h_str},ok={int(res_ok)},items={res_items[:6]}"

            # 5) Bấm nút Save (hoặc Cancel nếu Save không tồn tại để không bao giờ treo hộp thoại)
            time.sleep(0.20)
            saved_ok = [False]
            btn_seen: List[str] = []

            def _click_sheet_btn(want_names: Tuple[str, ...], el: Any, depth: int) -> None:
                if not el or depth > 14 or saved_ok[0]:
                    return
                if _gs(el, s_role).strip() == "AXButton":
                    bt = _gs(el, s_title).strip()
                    if bt:
                        btn_seen.append(bt)
                    if bt.lower() in want_names and _gb(el, s_enabled):
                        rb_s = _grect(el)
                        if rb_s and (0.0 <= rb_s[0] < mx_m + mw_m - 6.0) and (0.0 <= rb_s[1] < my_m + mh_m - 6.0):
                            _cg_click_once(rb_s[0] + rb_s[2] * 0.5, rb_s[1] + rb_s[3] * 0.5)
                            saved_ok[0] = True
                            return
                        if _ax_press_fast(el, 0.50) == 0:
                            saved_ok[0] = True
                            return
                ch = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                    try:
                        nc = cf.CFArrayGetCount(ch.value)
                        for ci in range(min(nc, 80)):
                            _click_sheet_btn(want_names, cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                            if saved_ok[0]:
                                break
                    finally:
                        cf.CFRelease(ch.value)

            w_s = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_s)) == 0 and w_s.value:
                try:
                    for wi in range(cf.CFArrayGetCount(w_s.value)):
                        _click_sheet_btn(("save", "lưu", "done"), cf.CFArrayGetValueAtIndex(w_s.value, wi), 0)
                finally:
                    cf.CFRelease(w_s.value)
            _RDP_CLOSER_DIAG["edit_pc_buttons"] = btn_seen[-10:]
            if saved_ok[0]:
                _LAST_APPLIED_BOOKMARK_MODE = bool(enable_multimon)
                _RDP_CLOSER_DIAG["multimon_bookmark"] = bool(enable_multimon)
                _RDP_CLOSER_DIAG["bmk_write_status"] = f"ax_saved:mm={int(enable_multimon)},fit=1,dyn=0,ret=1"
            else:
                w_can = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_can)) == 0 and w_can.value:
                    try:
                        for wi in range(cf.CFArrayGetCount(w_can.value)):
                            _click_sheet_btn(("cancel", "hủy"), cf.CFArrayGetValueAtIndex(w_can.value, wi), 0)
                    finally:
                        cf.CFRelease(w_can.value)
                _RDP_CLOSER_DIAG["bmk_write_status"] = f"ax_no_save:mm={int(enable_multimon)}"
            time.sleep(0.38)

        if connect_after:
            _park_cc_offscreen()
            connected_menu = _click_menu_item(("connections", "connection"), ("connect",))
            if not connected_menu and q is not None:
                # Bấm Enter (vk=36) trên thẻ PC Hieu đang chọn trong Connection Center ngầm!
                rk_d = q.CGEventCreateKeyboardEvent(None, 36, True)
                rk_u = q.CGEventCreateKeyboardEvent(None, 36, False)
                q.CGEventSetFlags(rk_d, 0)
                q.CGEventSetFlags(rk_u, 0)
                q.CGEventPost(q.kCGHIDEventTap, rk_d)
                q.CGEventPost(q.kCGHIDEventTap, rk_u)
            # Chờ hộp thoại Connecting / phiên Remote kịp bật lên (tránh bấm Connect lặp 2-3 lần!)
            started_conn = False
            for _ in range(7):
                time.sleep(0.10)
                if _has_rdp_session_or_connecting(rdp_pid, target_title):
                    started_conn = True
                    break
            if not started_conn:
                _ax_close_session_and_relaunch(rdp_pid, target_title, close_existing_session=False)
            # Ẩn ngay toàn bộ Microsoft Remote Desktop (giấu tiệt bảng Connecting... 540x340 & Connection Center) trong lúc chờ phiên kết nối xong!
            try:
                with objc.autorelease_pool():
                    rapp_hide = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(rdp_pid)
                    if rapp_hide is not None:
                        rapp_hide.hide()
                    if orig_front_pid > 0 and orig_front_pid != rdp_pid:
                        prev_app_c = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(orig_front_pid)
                        if prev_app_c is not None:
                            prev_app_c.activateWithOptions_(2)
            except Exception:
                pass
        else:
            # Nếu chỉ đồng bộ nền khi chưa mở phiên -> đóng Connection Center, ẩn MRD và trả lại focus cho app cũ
            w_cl = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_cl)) == 0 and w_cl.value:
                try:
                    for wi in range(cf.CFArrayGetCount(w_cl.value)):
                        wel = cf.CFArrayGetValueAtIndex(w_cl.value, wi)
                        if not wel:
                            continue
                        wt = _gs(wel, s_title).strip().lower()
                        if not wt or wt in ("microsoft remote desktop", "windows app", "connection center", "pcs", "devices"):
                            br = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(wel, s_close, ctypes.byref(br)) == 0 and br.value:
                                try:
                                    _ax_press_fast(br.value, 0.45)
                                finally:
                                    cf.CFRelease(br.value)
                finally:
                    cf.CFRelease(w_cl.value)
            try:
                with objc.autorelease_pool():
                    rapp_idle = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(rdp_pid)
                    if rapp_idle is not None:
                        rapp_idle.hide()
            except Exception:
                pass
            if orig_front_pid > 0 and orig_front_pid != rdp_pid:
                try:
                    with objc.autorelease_pool():
                         prev_app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(orig_front_pid)
                         if prev_app is not None:
                             prev_app.activateWithOptions_(2)
                except Exception:
                    pass
    finally:
        if orig_pt is not None and q is not None:
            try:
                q.CGWarpMouseCursorPosition((float(orig_pt.x), float(orig_pt.y)))
            except Exception:
                pass
        cf.CFRelease(app_ax)
        for sr in (
            s_wins, s_role, s_subrole, s_title, s_desc, s_val, s_pos, s_size,
            s_close, s_press, s_menubar, s_children, s_enabled, s_fs, s_main, s_focused, s_raise,
            s_parent_d, s_sel_d,
        ):
            if sr:
                cf.CFRelease(sr)
    return rdp_pid


def _mrd_has_active_rdp_tcp(rpid: int) -> Optional[bool]:
    """Kiểm tra trực tiếp socket TCP ESTABLISHED thật của tiến trình Microsoft Remote Desktop (cổng :3389 / LAN).
    - True: chắc chắn đang có phiên Remote thật kết nối tới Windows PC (kể cả đang Full-Screen Space khác hoặc kCGWindowName='Microsoft Remote Desktop').
    - False: chắc chắn KHÔNG có phiên Remote nào đang mở (người dùng đã đóng PC Hieu, kể cả khi Connection Center vẫn mở hoặc macOS cache cửa sổ ảo).
    - None: không chạy được lsof -> fallback sang kiểm tra AXWindows."""
    if not IS_MACOS or rpid <= 0:
        return None
    lsof_bin = "/usr/sbin/lsof" if Path("/usr/sbin/lsof").exists() else "lsof"
    try:
        rc = subprocess.run(
            [lsof_bin, "-nP", "-a", "-p", str(int(rpid)), "-iTCP"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=0.75,
        )
        out = rc.stdout or ""
        err = (rc.stderr or "").strip()
        if rc.returncode not in (0, 1) and not out:
            _RDP_CLOSER_DIAG["rdp_tcp_active"] = f"err:{rc.returncode}:{err[:40]}"
            return None
        for line in out.splitlines():
            if ("ESTABLISHED" not in line and "SYN_SENT" not in line) or "->" not in line:
                continue
            remote = line.split("->", 1)[1].split(" ", 1)[0].strip()
            if ":3389" in remote or re.search(r"^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.|100\.)", remote):
                _RDP_CLOSER_DIAG["rdp_tcp_active"] = f"yes:{remote}"
                return True
        _RDP_CLOSER_DIAG["rdp_tcp_active"] = "no"
        return False
    except Exception as exc_l:
        _RDP_CLOSER_DIAG["rdp_tcp_active"] = f"exc:{str(exc_l)[:40]}"
        return None


def _rdp_probe_vdisp_state(require_live_open: bool = True) -> Tuple[int, List[str], bool]:
    """Trả về (rdp_pid, session_titles, has_session_on_vdisp).
    Khi require_live_open=True (mặc định): xác thực bằng kết nối TCP RDP thật (:3389) + không bị ẩn (isHidden=False):
    - Đang mở phiên Remote thật (kể cả Full-Screen Space khác hoặc cửa sổ Full-Screen mang tên 'Microsoft Remote Desktop'): luôn nhận ra 100%!
    - Đã tắt phiên Remote (kể cả còn Connection Center hay cửa sổ cache onscreen=False): trả rỗng 100%, không bao giờ tự kích hoạt nhầm!"""
    if not IS_MACOS:
        return 0, [], False
    q = injector._quartz
    if q is None:
        try:
            import Quartz as q  # type: ignore
        except Exception:
            return 0, [], False
    import AppKit  # type: ignore
    import ctypes
    import objc  # type: ignore

    vb = _get_secondary_mac_display_bounds(q)
    launcher_set = {
        "microsoft remote desktop", "windows app", "connection center",
        "devices", "pcs", "workspaces", "remote desktop",
    }
    dialog_kw = ("edit pc", "add pc", "preferences", "settings", "certificate", "connecting", "password", "sign in")
    rpid = 0
    sessions: List[str] = []
    sess_low: set = set()
    onscreen_low: set = set()
    has_vdisp = False
    has_vdisp_any_big = False
    with objc.autorelease_pool():
        wlist = q.CGWindowListCopyWindowInfo(
            q.kCGWindowListOptionAll | q.kCGWindowListExcludeDesktopElements,
            q.kCGNullWindowID,
        ) or []
        for w in wlist:
            ol = str(w.get("kCGWindowOwnerName", "") or "").strip().lower()
            if "microsoft remote desktop" not in ol and "windows app" not in ol and "com.microsoft.rdc" not in ol:
                continue
            pw_pid = int(w.get("kCGWindowOwnerPID", 0) or 0)
            if pw_pid <= 0:
                continue
            if rpid <= 0:
                rpid = pw_pid
            if int(w.get("kCGWindowLayer", -1)) != 0:
                continue
            wb = w.get("kCGWindowBounds") or {}
            wx = float(wb.get("X", 0))
            wy = float(wb.get("Y", 0))
            ww = float(wb.get("Width", 0))
            wh = float(wb.get("Height", 0))
            wname = str(w.get("kCGWindowName", "") or "").strip()
            wl = wname.lower()
            if not wname or ww < 620.0 or wh < 200.0:
                continue
            if any(k in wl for k in dialog_kw):
                continue
            if vb is not None:
                cx = wx + ww * 0.5
                cy = wy + wh * 0.5
                if (vb["x"] <= cx < vb["x"] + vb["w"]) and (vb["y"] <= cy < vb["y"] + vb["h"]):
                    has_vdisp_any_big = True
            if wl in launcher_set:
                continue
            rpid = pw_pid
            if bool(w.get("kCGWindowIsOnscreen", False)):
                onscreen_low.add(wl)
            if wl not in sess_low:
                sess_low.add(wl)
                sessions.append(wname)
            if vb is not None:
                cx = wx + ww * 0.5
                cy = wy + wh * 0.5
                if (vb["x"] <= cx < vb["x"] + vb["w"]) and (vb["y"] <= cy < vb["y"] + vb["h"]):
                    has_vdisp = True

        if rpid <= 0:
            live_pids_fb = _find_live_mrd_pids()
            if live_pids_fb:
                rpid = live_pids_fb[0]

        if require_live_open and rpid > 0:
            # TUYỆT ĐỐI không đọc NSRunningApplication.isHidden() vì tiến trình Python không chạy NSRunLoop sẽ bị kẹt cache True sau lần hide() đầu tiên!
            # Xác thực trực tiếp qua bảng socket TCP kernel (:3389) — luôn chuẩn 100% ở mọi lần bật/tắt liên tục!
            tcp_live = _mrd_has_active_rdp_tcp(rpid)
            if tcp_live is False:
                return rpid, [], False
            if tcp_live is True:
                if not sessions:
                    bmks_live = _list_mrd_bookmarks()
                    sessions = [bmks_live[0][0] if bmks_live else "PC Hieu"]
                if has_vdisp_any_big:
                    has_vdisp = True
                return rpid, sessions, has_vdisp

        if require_live_open and sessions and rpid > 0:
            if mac_vdisp is not None and mac_vdisp._init_ax_libs():
                ax_l = mac_vdisp._ax_lib
                cf_l = mac_vdisp._cf_lib
                a_el = ax_l.AXUIElementCreateApplication(rpid)
                if a_el:
                    sw_s = cf_l.CFStringCreateWithCString(None, b"AXWindows", 0x08000100)
                    st_s = cf_l.CFStringCreateWithCString(None, b"AXTitle", 0x08000100)
                    sm_s = cf_l.CFStringCreateWithCString(None, b"AXMinimized", 0x08000100)
                    sf_s = cf_l.CFStringCreateWithCString(None, b"AXFullScreen", 0x08000100)
                    valid_ax_low: set = set()
                    try:
                        try:
                            ax_l.AXUIElementSetMessagingTimeout.argtypes = [ctypes.c_void_p, ctypes.c_float]
                            ax_l.AXUIElementSetMessagingTimeout.restype = ctypes.c_int32
                            ax_l.AXUIElementSetMessagingTimeout(a_el, ctypes.c_float(0.35))
                        except Exception:
                            pass
                        wr_p = ctypes.c_void_p()
                        if ax_l.AXUIElementCopyAttributeValue(a_el, sw_s, ctypes.byref(wr_p)) == 0 and wr_p.value:
                            try:
                                for wi_p in range(cf_l.CFArrayGetCount(wr_p.value)):
                                    wel_p = cf_l.CFArrayGetValueAtIndex(wr_p.value, wi_p)
                                    if not wel_p:
                                        continue
                                    t_p = ""
                                    tr_p = ctypes.c_void_p()
                                    if ax_l.AXUIElementCopyAttributeValue(wel_p, st_s, ctypes.byref(tr_p)) == 0 and tr_p.value:
                                        t_p = str(objc.objc_object(c_void_p=tr_p.value) or "").strip().lower()
                                        cf_l.CFRelease(tr_p.value)
                                    if not t_p:
                                        continue
                                    is_min_p = False
                                    mr_p = ctypes.c_void_p()
                                    if ax_l.AXUIElementCopyAttributeValue(wel_p, sm_s, ctypes.byref(mr_p)) == 0 and mr_p.value:
                                        is_min_p = bool(cf_l.CFBooleanGetValue(mr_p.value))
                                        cf_l.CFRelease(mr_p.value)
                                    if is_min_p:
                                        continue
                                    is_fs_p = False
                                    fr_p = ctypes.c_void_p()
                                    if ax_l.AXUIElementCopyAttributeValue(wel_p, sf_s, ctypes.byref(fr_p)) == 0 and fr_p.value:
                                        is_fs_p = bool(cf_l.CFBooleanGetValue(fr_p.value))
                                        cf_l.CFRelease(fr_p.value)
                                    if (t_p in onscreen_low) or is_fs_p:
                                        valid_ax_low.add(t_p)
                            finally:
                                cf_l.CFRelease(wr_p.value)
                        sessions = [sn for sn in sessions if sn.lower() in valid_ax_low]
                        if not sessions:
                            has_vdisp = False
                    finally:
                        cf_l.CFRelease(a_el)
                        for kr_p in (sw_s, st_s, sm_s, sf_s):
                            if kr_p:
                                cf_l.CFRelease(kr_p)
            else:
                sessions = [sn for sn in sessions if sn.lower() in onscreen_low]
                if not sessions:
                    has_vdisp = False
    return rpid, sessions, has_vdisp


def _ax_close_session_and_relaunch(rdp_pid: int, target_title: str, close_existing_session: bool) -> bool:
    """Mở Connection Center -> (nếu cần) đóng phiên 1 màn cũ -> kích kết nối lại phiên target_title sang 2 màn."""
    if not IS_MACOS or rdp_pid <= 0 or mac_vdisp is None or not mac_vdisp._init_ax_libs():
        return False
    import ctypes
    import AppKit  # type: ignore
    import objc  # type: ignore
    from mac_virtual_display import _CGPoint, _CGSize

    q = injector._quartz
    if q is None:
        try:
            import Quartz as q  # type: ignore
        except Exception:
            q = None
    ax = mac_vdisp._ax_lib
    cf = mac_vdisp._cf_lib
    kCFStringEncodingUTF8 = 0x08000100

    def _cfstr(s: str) -> ctypes.c_void_p:
        return cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)

    def _gs(el: Any, attr: Any) -> str:
        r = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(el, attr, ctypes.byref(r)) == 0 and r.value:
            try:
                with objc.autorelease_pool():
                    return str(objc.objc_object(c_void_p=r.value) or "")
            finally:
                cf.CFRelease(r.value)
        return ""

    def _gb(el: Any, attr: Any) -> bool:
        r = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(el, attr, ctypes.byref(r)) == 0 and r.value:
            try:
                return bool(cf.CFBooleanGetValue(r.value))
            finally:
                cf.CFRelease(r.value)
        return False

    def _grect(el: Any, sp: Any, ss: Any) -> Optional[Tuple[float, float, float, float]]:
        rp = ctypes.c_void_p()
        rs = ctypes.c_void_p()
        ok = False
        pt = _CGPoint()
        sz = _CGSize()
        if ax.AXUIElementCopyAttributeValue(el, sp, ctypes.byref(rp)) == 0 and rp.value:
            if ax.AXUIElementCopyAttributeValue(el, ss, ctypes.byref(rs)) == 0 and rs.value:
                ok = bool(ax.AXValueGetValue(rp.value, 1, ctypes.byref(pt)) and ax.AXValueGetValue(rs.value, 2, ctypes.byref(sz)))
        if rp.value:
            cf.CFRelease(rp.value)
        if rs.value:
            cf.CFRelease(rs.value)
        return (float(pt.x), float(pt.y), float(sz.w), float(sz.h)) if ok else None

    app_ax = ax.AXUIElementCreateApplication(rdp_pid)
    if not app_ax:
        return False

    s_wins = _cfstr("AXWindows")
    s_title = _cfstr("AXTitle")
    s_desc = _cfstr("AXDescription")
    s_val = _cfstr("AXValue")
    s_pos = _cfstr("AXPosition")
    s_size = _cfstr("AXSize")
    s_close = _cfstr("AXCloseButton")
    s_press = _cfstr("AXPress")
    s_open = _cfstr("AXOpen")
    s_menubar = _cfstr("AXMenuBar")
    s_children = _cfstr("AXChildren")
    s_enabled = _cfstr("AXEnabled")

    mx_r, my_r, mw_r, mh_r = 0.0, 0.0, 1512.0, 982.0
    if q is not None:
        try:
            mb_r = q.CGDisplayBounds(q.CGMainDisplayID())
            mx_r, my_r, mw_r, mh_r = float(mb_r.origin.x), float(mb_r.origin.y), float(mb_r.size.width), float(mb_r.size.height)
        except Exception:
            pass
    park_rx, park_ry = mx_r + mw_r - 2.0, my_r + mh_r - 2.0

    def _set_cc_pos_r(px_v: float, py_v: float) -> None:
        w_pr = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_pr)) == 0 and w_pr.value:
            try:
                for wi in range(cf.CFArrayGetCount(w_pr.value)):
                    wel_r = cf.CFArrayGetValueAtIndex(w_pr.value, wi)
                    if not wel_r:
                        continue
                    wt_r = _gs(wel_r, s_title).strip().lower()
                    if not wt_r or wt_r in ("microsoft remote desktop", "windows app", "connection center", "pcs", "devices"):
                        pt_r = _CGPoint(px_v, py_v)
                        vp_r = ax.AXValueCreate(1, ctypes.byref(pt_r))
                        if vp_r:
                            ax.AXUIElementSetAttributeValue(wel_r, s_pos, vp_r)
                            cf.CFRelease(vp_r)
            finally:
                cf.CFRelease(w_pr.value)

    # Đẩy sẵn Connection Center ra góc giấu ngầm TRƯỚC KHI unhide/activate!
    _set_cc_pos_r(park_rx, park_ry)
    try:
        with objc.autorelease_pool():
            rapp = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(rdp_pid)
            if rapp is not None:
                rapp.unhide()
                rapp.activateWithOptions_(3)
    except Exception:
        pass
    time.sleep(0.10)

    def _click_menu_item(bar_names: Tuple[str, ...], item_exact: str) -> bool:
        mb = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(app_ax, s_menubar, ctypes.byref(mb)) != 0 or not mb.value:
            return False
        try:
            bars = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(mb.value, s_children, ctypes.byref(bars)) != 0 or not bars.value:
                return False
            try:
                nb = cf.CFArrayGetCount(bars.value)
                for bi in range(nb):
                    bel = cf.CFArrayGetValueAtIndex(bars.value, bi)
                    if not bel:
                        continue
                    if _gs(bel, s_title).strip().lower() not in bar_names:
                        continue
                    sub = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(bel, s_children, ctypes.byref(sub)) != 0 or not sub.value:
                        continue
                    try:
                        if cf.CFArrayGetCount(sub.value) <= 0:
                            continue
                        mel = cf.CFArrayGetValueAtIndex(sub.value, 0)
                        its = ctypes.c_void_p()
                        if mel and ax.AXUIElementCopyAttributeValue(mel, s_children, ctypes.byref(its)) == 0 and its.value:
                            try:
                                ni = cf.CFArrayGetCount(its.value)
                                for mi in range(ni):
                                    iel = cf.CFArrayGetValueAtIndex(its.value, mi)
                                    if not iel:
                                        continue
                                    it_l = _gs(iel, s_title).strip().lower()
                                    # BẮT BUỘC khớp chính xác 100% (tránh "connect" khớp nhầm "pc quick connect"!)
                                    if it_l == item_exact and _gb(iel, s_enabled):
                                        if ax.AXUIElementPerformAction(iel, s_press) == 0:
                                            return True
                            finally:
                                cf.CFRelease(its.value)
                    finally:
                        cf.CFRelease(sub.value)
            finally:
                cf.CFRelease(bars.value)
        finally:
            cf.CFRelease(mb.value)
        return False

    launched = False
    s_fs = _cfstr("AXFullScreen")
    s_main = _cfstr("AXMain")
    s_focused = _cfstr("AXFocused")
    s_selected = _cfstr("AXSelected")
    s_raise = _cfstr("AXRaise")
    kTrue = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue").value
    kFalse = ctypes.c_void_p.in_dll(cf, "kCFBooleanFalse").value

    try:
        # 1) Bật Connection Center ở góc giấu ngầm (park_rx, park_ry) trong < 10ms + thoát Full-Screen nếu bị kẹt!
        _click_menu_item(("window", "cửa sổ"), "connection center")
        exited_cc_fs = False
        cc_parked_r = False
        for _ in range(18):
            w_cc = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_cc)) == 0 and w_cc.value:
                try:
                    for wi in range(cf.CFArrayGetCount(w_cc.value)):
                        wel = cf.CFArrayGetValueAtIndex(w_cc.value, wi)
                        if not wel:
                            continue
                        wt = _gs(wel, s_title).strip().lower()
                        if not wt or wt in ("microsoft remote desktop", "windows app", "connection center", "pcs", "devices"):
                            if _gb(wel, s_fs):
                                ax.AXUIElementSetAttributeValue(wel, s_fs, kFalse)
                                exited_cc_fs = True
                            pt_pk2 = _CGPoint(park_rx, park_ry)
                            vp_pk2 = ax.AXValueCreate(1, ctypes.byref(pt_pk2))
                            if vp_pk2:
                                ax.AXUIElementSetAttributeValue(wel, s_pos, vp_pk2)
                                cf.CFRelease(vp_pk2)
                            ax.AXUIElementSetAttributeValue(wel, s_main, kTrue)
                            ax.AXUIElementSetAttributeValue(wel, s_focused, kTrue)
                            ax.AXUIElementPerformAction(wel, s_raise)
                            cc_parked_r = True
                finally:
                    cf.CFRelease(w_cc.value)
            if cc_parked_r:
                break
            time.sleep(0.01)
        time.sleep(0.05)
        if not exited_cc_fs and not close_existing_session:
            if _click_menu_item(("window", "view", "cửa sổ", "xem"), "exit full screen"):
                exited_cc_fs = True
        if exited_cc_fs:
            time.sleep(0.95)
            _set_cc_pos_r(park_rx, park_ry)
            try:
                with objc.autorelease_pool():
                    rapp = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(rdp_pid)
                    if rapp is not None:
                        rapp.activateWithOptions_(3)
            except Exception:
                pass
            time.sleep(0.16)

        # 2) Đóng cửa sổ phiên 1 màn cũ (nếu có)
        if close_existing_session:
            t_low = target_title.strip().lower()
            w_arr = ctypes.c_void_p()
            closed_s = False
            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_arr)) == 0 and w_arr.value:
                try:
                    nw = cf.CFArrayGetCount(w_arr.value)
                    for wi in range(nw):
                        wel = cf.CFArrayGetValueAtIndex(w_arr.value, wi)
                        if not wel:
                            continue
                        wt = _gs(wel, s_title).strip().lower()
                        if wt == t_low or (t_low and t_low in wt and wt != "microsoft remote desktop") or (wt == "microsoft remote desktop" and _gb(wel, s_fs)):
                            b_ref = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(wel, s_close, ctypes.byref(b_ref)) == 0 and b_ref.value:
                                try:
                                    try:
                                        ax.AXUIElementSetMessagingTimeout.argtypes = [ctypes.c_void_p, ctypes.c_float]
                                        ax.AXUIElementSetMessagingTimeout.restype = ctypes.c_int32
                                        ax.AXUIElementSetMessagingTimeout(b_ref.value, ctypes.c_float(0.65))
                                    except Exception:
                                        pass
                                    ax.AXUIElementPerformAction(b_ref.value, s_press)
                                    closed_s = True
                                finally:
                                    cf.CFRelease(b_ref.value)
                finally:
                    cf.CFRelease(w_arr.value)
            if not closed_s:
                _click_menu_item(("window", "cửa sổ"), target_title.strip().lower())
                time.sleep(0.55)
                _click_menu_item(("window", "cửa sổ"), "close")
                closed_s = True
            if closed_s and q is not None:
                time.sleep(0.22)
                has_dlg_c = False
                with objc.autorelease_pool():
                    for wm_c in (q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionAll | q.kCGWindowListExcludeDesktopElements, q.kCGNullWindowID) or []):
                        if int(wm_c.get("kCGWindowOwnerPID", 0) or 0) == rdp_pid and int(wm_c.get("kCGWindowLayer", -1)) == 0 and bool(wm_c.get("kCGWindowIsOnscreen", False)):
                            wbc = wm_c.get("kCGWindowBounds") or {}
                            if 160.0 <= float(wbc.get("Width", 0.0)) <= 500.0 and 100.0 <= float(wbc.get("Height", 0.0)) <= 400.0:
                                has_dlg_c = True
                                break
                if has_dlg_c:
                    kd_c = q.CGEventCreateKeyboardEvent(None, 36, True)
                    ku_c = q.CGEventCreateKeyboardEvent(None, 36, False)
                    q.CGEventSetFlags(kd_c, 0)
                    q.CGEventSetFlags(ku_c, 0)
                    q.CGEventPost(q.kCGHIDEventTap, kd_c)
                    q.CGEventPost(q.kCGHIDEventTap, ku_c)
            time.sleep(0.38)
            _click_menu_item(("window", "cửa sổ"), "connection center")
            time.sleep(0.14)
            _set_cc_pos_r(park_rx, park_ry)

        # 3) Thử bấm Connections -> Connect hoàn toàn ngầm (hoặc mũi tên Phải chọn thẻ + Connect/Enter)
        if _click_menu_item(("connections", "connection"), "connect"):
            launched = True
        elif q is not None:
            ra_d2 = q.CGEventCreateKeyboardEvent(None, 124, True)
            ra_u2 = q.CGEventCreateKeyboardEvent(None, 124, False)
            q.CGEventSetFlags(ra_d2, 0)
            q.CGEventSetFlags(ra_u2, 0)
            q.CGEventPost(q.kCGHIDEventTap, ra_d2)
            q.CGEventPost(q.kCGHIDEventTap, ra_u2)
            time.sleep(0.08)
            if _click_menu_item(("connections", "connection"), "connect"):
                launched = True
            else:
                rk_d2 = q.CGEventCreateKeyboardEvent(None, 36, True)
                rk_u2 = q.CGEventCreateKeyboardEvent(None, 36, False)
                q.CGEventSetFlags(rk_d2, 0)
                q.CGEventSetFlags(rk_u2, 0)
                q.CGEventPost(q.kCGHIDEventTap, rk_d2)
                q.CGEventPost(q.kCGHIDEventTap, rk_u2)
                time.sleep(0.15)
                if _has_rdp_session_or_connecting(rdp_pid, target_title):
                    launched = True

        if not launched:
            # 4) Dự phòng hiếm: nhích nhẹ Connection Center lên chọn thẻ trong 0.1s rồi lập tức giấu lại!
            _set_cc_pos_r(40.0, 60.0)
            time.sleep(0.08)
            t_low = target_title.strip().lower()
            candidates: List[Tuple[float, float, float, float]] = []
            visited = [0]

            def _walk_cc(el: Any, depth: int) -> None:
                if not el or depth > 18 or visited[0] > 2500:
                    return
                visited[0] += 1
                tx = (_gs(el, s_title) + " " + _gs(el, s_val) + " " + _gs(el, s_desc)).strip().lower()
                if (t_low and t_low in tx) or "192.168.52.230" in tx:
                    rc_box = _grect(el, s_pos, s_size)
                    if rc_box and rc_box[2] >= 20.0 and rc_box[3] >= 12.0:
                        candidates.append((rc_box[0], rc_box[1], rc_box[2], rc_box[3]))
                ch = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(el, s_children, ctypes.byref(ch)) == 0 and ch.value:
                    try:
                        nc = cf.CFArrayGetCount(ch.value)
                        for ci in range(min(nc, 80)):
                            _walk_cc(cf.CFArrayGetValueAtIndex(ch.value, ci), depth + 1)
                    finally:
                        cf.CFRelease(ch.value)

            w_arr2 = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(w_arr2)) == 0 and w_arr2.value:
                try:
                    nw2 = cf.CFArrayGetCount(w_arr2.value)
                    for wi in range(nw2):
                        _walk_cc(cf.CFArrayGetValueAtIndex(w_arr2.value, wi), 0)
                finally:
                    cf.CFRelease(w_arr2.value)

            _RDP_CLOSER_DIAG["cc_walk"] = f"vis={visited[0]},cand={len(candidates)},ex_fs={int(exited_cc_fs)}"
            if candidates:
                bx, by, bw, bh = candidates[0]
                if q is not None:
                    cx = bx + bw * 0.5
                    cy = (by - 36.0) if (bh < 32.0 and by > 120.0) else (by + min(32.0, bh * 0.4))
                    orig_ev = q.CGEventCreate(None)
                    orig_pt = q.CGEventGetLocation(orig_ev) if orig_ev is not None else None
                    d1 = q.CGEventCreateMouseEvent(None, q.kCGEventLeftMouseDown, (cx, cy), q.kCGMouseButtonLeft)
                    u1 = q.CGEventCreateMouseEvent(None, q.kCGEventLeftMouseUp, (cx, cy), q.kCGMouseButtonLeft)
                    q.CGEventSetIntegerValueField(d1, q.kCGMouseEventClickState, 1)
                    q.CGEventSetIntegerValueField(u1, q.kCGMouseEventClickState, 1)
                    q.CGEventPost(q.kCGHIDEventTap, d1)
                    q.CGEventPost(q.kCGHIDEventTap, u1)
                    time.sleep(0.14)
                    if not _click_menu_item(("connections", "connection"), "connect"):
                        for clk in (1, 2):
                            de = q.CGEventCreateMouseEvent(None, q.kCGEventLeftMouseDown, (cx, cy), q.kCGMouseButtonLeft)
                            ue = q.CGEventCreateMouseEvent(None, q.kCGEventLeftMouseUp, (cx, cy), q.kCGMouseButtonLeft)
                            q.CGEventSetIntegerValueField(de, q.kCGMouseEventClickState, clk)
                            q.CGEventSetIntegerValueField(ue, q.kCGMouseEventClickState, clk)
                            q.CGEventPost(q.kCGHIDEventTap, de)
                            q.CGEventPost(q.kCGHIDEventTap, ue)
                            if clk == 1:
                                time.sleep(0.03)
                    if orig_pt is not None:
                        try:
                            q.CGWarpMouseCursorPosition((float(orig_pt.x), float(orig_pt.y)))
                        except Exception:
                            pass
                    launched = True
            _set_cc_pos_r(park_rx, park_ry)
    finally:
        cf.CFRelease(app_ax)
        for sr in (
            s_wins, s_title, s_desc, s_val, s_pos, s_size, s_close, s_press,
            s_open, s_menubar, s_children, s_enabled, s_fs, s_main, s_focused, s_selected, s_raise,
        ):
            if sr:
                cf.CFRelease(sr)
    return launched


def _quit_mrd_cleanly() -> None:
    """Đóng êm các cửa sổ phiên đang mở rồi thoát sạch tiến trình MRD để giải phóng khóa CoreData SQLite."""
    import ctypes
    import AppKit  # type: ignore
    import objc  # type: ignore

    rpid_cur, _, _ = _rdp_probe_vdisp_state()
    if rpid_cur > 0 and mac_vdisp is not None and mac_vdisp._init_ax_libs():
        try:
            ax = mac_vdisp._ax_lib
            cf = mac_vdisp._cf_lib
            a_ax = ax.AXUIElementCreateApplication(rpid_cur)
            if a_ax:
                sw_k = cf.CFStringCreateWithCString(None, b"AXWindows", 0x08000100)
                st_k = cf.CFStringCreateWithCString(None, b"AXTitle", 0x08000100)
                sc_k = cf.CFStringCreateWithCString(None, b"AXCloseButton", 0x08000100)
                sp_k = cf.CFStringCreateWithCString(None, b"AXPress", 0x08000100)
                try:
                    wr = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(a_ax, sw_k, ctypes.byref(wr)) == 0 and wr.value:
                        try:
                            for wi in range(cf.CFArrayGetCount(wr.value)):
                                wel = cf.CFArrayGetValueAtIndex(wr.value, wi)
                                if not wel:
                                    continue
                                tr = ctypes.c_void_p()
                                wt = ""
                                if ax.AXUIElementCopyAttributeValue(wel, st_k, ctypes.byref(tr)) == 0 and tr.value:
                                    with objc.autorelease_pool():
                                        wt = str(objc.objc_object(c_void_p=tr.value) or "").strip().lower()
                                    cf.CFRelease(tr.value)
                                if wt and wt not in ("microsoft remote desktop", "windows app", "connection center"):
                                    br = ctypes.c_void_p()
                                    if ax.AXUIElementCopyAttributeValue(wel, sc_k, ctypes.byref(br)) == 0 and br.value:
                                        ax.AXUIElementPerformAction(br.value, sp_k)
                                        cf.CFRelease(br.value)
                        finally:
                            cf.CFRelease(wr.value)
                finally:
                    cf.CFRelease(a_ax)
                    for k_ref in (sw_k, st_k, sc_k, sp_k):
                        if k_ref:
                            cf.CFRelease(k_ref)
            time.sleep(0.25)
        except Exception:
            pass

    live_pids = _find_live_mrd_pids()
    if not live_pids:
        return
    for mp in live_pids:
        try:
            with objc.autorelease_pool():
                rapp = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(mp)
                if rapp is not None:
                    rapp.terminate()
        except Exception:
            pass
    for step_q in range(14):
        time.sleep(0.15)
        rem = _find_live_mrd_pids()
        if not rem:
            return
        if step_q == 5:
            for mp in rem:
                try:
                    os.kill(mp, signal.SIGTERM)
                except Exception:
                    pass


def _apply_full_mac_window_bounds(target_pid: int, target_sess: str) -> Tuple[bool, float, float]:
    """Khôi phục cửa sổ phiên 1 màn về đúng kích thước & vị trí ban đầu của người dùng (hoặc bung trọn màn MacBook nếu chưa lưu). Bỏ qua hộp Connecting 540x340."""
    import ctypes
    import objc  # type: ignore
    from mac_virtual_display import _CGPoint, _CGSize

    if not IS_MACOS or target_pid <= 0 or mac_vdisp is None or not mac_vdisp._init_ax_libs():
        return False, 0.0, 0.0
    q = injector._quartz
    if q is None:
        try:
            import Quartz as q  # type: ignore
        except Exception:
            return False, 0.0, 0.0
    _, _, def_x, def_y, def_w, def_h = _compute_exact_1mon_retina_res(q)
    mb = q.CGDisplayBounds(q.CGMainDisplayID())
    mx, my, mw, mh = float(mb.origin.x), float(mb.origin.y), float(mb.size.width), float(mb.size.height)
    saved_b = _load_saved_1mon_bounds()
    if saved_b is not None:
        tw = max(360.0, min(mw, float(saved_b["w"])))
        th = max(240.0, min(mh - 24.0, float(saved_b["h"])))
        tx = max(mx, min(mx + mw - tw, float(saved_b["x"])))
        ty = max(my + 24.0, min(my + mh - th, float(saved_b["y"])))
    else:
        tx, ty, tw, th = def_x, def_y, def_w, def_h

    ax = mac_vdisp._ax_lib
    cf = mac_vdisp._cf_lib
    t_low = target_sess.strip().lower()
    a_ax = ax.AXUIElementCreateApplication(target_pid)
    if not a_ax:
        return False, 0.0, 0.0
    sw_k = cf.CFStringCreateWithCString(None, b"AXWindows", 0x08000100)
    st_k = cf.CFStringCreateWithCString(None, b"AXTitle", 0x08000100)
    sp_k = cf.CFStringCreateWithCString(None, b"AXPosition", 0x08000100)
    ss_k = cf.CFStringCreateWithCString(None, b"AXSize", 0x08000100)
    sf_k = cf.CFStringCreateWithCString(None, b"AXFullScreen", 0x08000100)
    matched = False
    cur_w, cur_h = 0.0, 0.0
    try:
        wr = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(a_ax, sw_k, ctypes.byref(wr)) == 0 and wr.value:
            try:
                for wi in range(cf.CFArrayGetCount(wr.value)):
                    wel = cf.CFArrayGetValueAtIndex(wr.value, wi)
                    if not wel:
                        continue
                    tr = ctypes.c_void_p()
                    wt = ""
                    if ax.AXUIElementCopyAttributeValue(wel, st_k, ctypes.byref(tr)) == 0 and tr.value:
                        with objc.autorelease_pool():
                            wt = str(objc.objc_object(c_void_p=tr.value) or "").strip().lower()
                        cf.CFRelease(tr.value)
                    if wt == t_low or (t_low and t_low in wt and wt != "microsoft remote desktop"):
                        fr = ctypes.c_void_p()
                        is_fs = False
                        if ax.AXUIElementCopyAttributeValue(wel, sf_k, ctypes.byref(fr)) == 0 and fr.value:
                            is_fs = bool(cf.CFBooleanGetValue(fr.value))
                            cf.CFRelease(fr.value)
                        if is_fs:
                            break
                        # Bỏ qua hộp thoại đang kết nối (540x340 / 550x184) -> chờ cửa sổ phiên thật (756x500+) xuất hiện!
                        sr_pre = ctypes.c_void_p()
                        pre_w, pre_h = 0.0, 0.0
                        if ax.AXUIElementCopyAttributeValue(wel, ss_k, ctypes.byref(sr_pre)) == 0 and sr_pre.value:
                            sz_pre = _CGSize()
                            if ax.AXValueGetValue(sr_pre.value, 2, ctypes.byref(sz_pre)):
                                pre_w, pre_h = float(sz_pre.w), float(sz_pre.h)
                            cf.CFRelease(sr_pre.value)
                        if pre_w < 680.0 and pre_h < 420.0:
                            continue
                        npt = _CGPoint(tx, ty)
                        nsz = _CGSize(tw, th)
                        v_pt = ax.AXValueCreate(1, ctypes.byref(npt))
                        v_sz = ax.AXValueCreate(2, ctypes.byref(nsz))
                        if v_pt:
                            ax.AXUIElementSetAttributeValue(wel, sp_k, v_pt)
                            cf.CFRelease(v_pt)
                        if v_sz:
                            ax.AXUIElementSetAttributeValue(wel, ss_k, v_sz)
                            cf.CFRelease(v_sz)
                        time.sleep(0.10)
                        if v_pt := ax.AXValueCreate(1, ctypes.byref(npt)):
                            ax.AXUIElementSetAttributeValue(wel, sp_k, v_pt)
                            cf.CFRelease(v_pt)
                        sr_after = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(wel, ss_k, ctypes.byref(sr_after)) == 0 and sr_after.value:
                            sz_out = _CGSize()
                            if ax.AXValueGetValue(sr_after.value, 2, ctypes.byref(sz_out)):
                                cur_w, cur_h = float(sz_out.w), float(sz_out.h)
                            cf.CFRelease(sr_after.value)
                        matched = True
                        break
            finally:
                cf.CFRelease(wr.value)
    finally:
        cf.CFRelease(a_ax)
        for k_ref in (sw_k, st_k, sp_k, ss_k, sf_k):
            if k_ref:
                cf.CFRelease(k_ref)
    return matched, cur_w, cur_h


def _has_rdp_session_or_connecting(target_pid: int, target_sess: str) -> bool:
    """Kiểm tra xem cửa sổ phiên hoặc hộp thoại Đang kết nối / Nhập mật khẩu (VD: PC Hieu 550x184) đã mở chưa."""
    if not IS_MACOS or target_pid <= 0:
        return False
    q = injector._quartz
    if q is None:
        try:
            import Quartz as q  # type: ignore
        except Exception:
            return False
    import objc  # type: ignore

    t_low = target_sess.strip().lower()
    with objc.autorelease_pool():
        wlist = q.CGWindowListCopyWindowInfo(
            q.kCGWindowListOptionAll | q.kCGWindowListExcludeDesktopElements,
            q.kCGNullWindowID,
        ) or []
        for w in wlist:
            if int(w.get("kCGWindowOwnerPID", 0) or 0) != target_pid:
                continue
            if int(w.get("kCGWindowLayer", -1)) != 0:
                continue
            wb = w.get("kCGWindowBounds") or {}
            ww = float(wb.get("Width", 0))
            wh = float(wb.get("Height", 0))
            wn = str(w.get("kCGWindowName", "") or "").strip().lower()
            if ww >= 300.0 and wh >= 120.0 and wn and (
                "connecting" in wn
                or "authenticat" in wn
                or wn == t_low
                or (t_low and t_low in wn and wn not in ("microsoft remote desktop", "windows app", "connection center"))
            ):
                return True
    return False


def _has_real_rdp_session_window(target_pid: int, target_sess: str) -> Tuple[bool, float, float]:
    """Kiểm tra cửa sổ phiên Remote thật (đã qua bước Connecting 540x340, đạt cỡ >= 680x420) ngay cả khi MRD đang ẩn (isHidden=True)."""
    if not IS_MACOS or target_pid <= 0:
        return False, 0.0, 0.0
    q = injector._quartz
    if q is None:
        try:
            import Quartz as q  # type: ignore
        except Exception:
            return False, 0.0, 0.0
    import objc  # type: ignore

    t_low = target_sess.strip().lower()
    with objc.autorelease_pool():
        wlist = q.CGWindowListCopyWindowInfo(
            q.kCGWindowListOptionAll | q.kCGWindowListExcludeDesktopElements,
            q.kCGNullWindowID,
        ) or []
        for w in wlist:
            if int(w.get("kCGWindowOwnerPID", 0) or 0) != target_pid:
                continue
            if int(w.get("kCGWindowLayer", -1)) != 0:
                continue
            wb = w.get("kCGWindowBounds") or {}
            ww = float(wb.get("Width", 0.0))
            wh = float(wb.get("Height", 0.0))
            wn = str(w.get("kCGWindowName", "") or "").strip().lower()
            if ww >= 680.0 and wh >= 420.0 and wn and (wn == t_low or (t_low and t_low in wn and wn not in ("microsoft remote desktop", "windows app", "connection center"))):
                return True, ww, wh
    return False, 0.0, 0.0


def _close_cc_silently_while_hidden(target_pid: int) -> None:
    """Đóng sạch cửa sổ trắng Connection Center ngay trong lúc MRD vẫn đang ẩn (trước khi unhide hiện phiên Remote)."""
    if not IS_MACOS or target_pid <= 0 or mac_vdisp is None or not mac_vdisp._init_ax_libs():
        return
    import ctypes
    import objc  # type: ignore
    from mac_virtual_display import _CGPoint

    q = injector._quartz
    pk_x, pk_y = 1510.0, 980.0
    if q is not None:
        try:
            mb_c = q.CGDisplayBounds(q.CGMainDisplayID())
            pk_x = float(mb_c.origin.x) + float(mb_c.size.width) - 2.0
            pk_y = float(mb_c.origin.y) + float(mb_c.size.height) - 2.0
        except Exception:
            pass

    ax = mac_vdisp._ax_lib
    cf = mac_vdisp._cf_lib
    a_ax = ax.AXUIElementCreateApplication(target_pid)
    if not a_ax:
        return
    sw_k = cf.CFStringCreateWithCString(None, b"AXWindows", 0x08000100)
    st_k = cf.CFStringCreateWithCString(None, b"AXTitle", 0x08000100)
    spos_k = cf.CFStringCreateWithCString(None, b"AXPosition", 0x08000100)
    sc_k = cf.CFStringCreateWithCString(None, b"AXCloseButton", 0x08000100)
    sp_k = cf.CFStringCreateWithCString(None, b"AXPress", 0x08000100)
    try:
        try:
            ax.AXUIElementSetMessagingTimeout(a_ax, ctypes.c_float(0.45))
        except Exception:
            pass
        wr = ctypes.c_void_p()
        if ax.AXUIElementCopyAttributeValue(a_ax, sw_k, ctypes.byref(wr)) == 0 and wr.value:
            try:
                for wi in range(cf.CFArrayGetCount(wr.value)):
                    wel = cf.CFArrayGetValueAtIndex(wr.value, wi)
                    if not wel:
                        continue
                    wt = ""
                    tr = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(wel, st_k, ctypes.byref(tr)) == 0 and tr.value:
                        with objc.autorelease_pool():
                            wt = str(objc.objc_object(c_void_p=tr.value) or "").strip().lower()
                        cf.CFRelease(tr.value)
                    if not wt or wt in ("microsoft remote desktop", "windows app", "connection center", "pcs", "devices"):
                        # Lưu frame autosave của Connection Center ở góc (1510, 980) trước khi đóng để lần sau mở lại mặc định ở ngoài màn hình!
                        pt_k = _CGPoint(pk_x, pk_y)
                        vp_k = ax.AXValueCreate(1, ctypes.byref(pt_k))
                        if vp_k:
                            ax.AXUIElementSetAttributeValue(wel, spos_k, vp_k)
                            cf.CFRelease(vp_k)
                        br = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(wel, sc_k, ctypes.byref(br)) == 0 and br.value:
                            try:
                                try:
                                    ax.AXUIElementSetMessagingTimeout(br.value, ctypes.c_float(0.45))
                                except Exception:
                                    pass
                                ax.AXUIElementPerformAction(br.value, sp_k)
                            finally:
                                cf.CFRelease(br.value)
            finally:
                cf.CFRelease(wr.value)
    finally:
        cf.CFRelease(a_ax)
        for k_r in (sw_k, st_k, spos_k, sc_k, sp_k):
            if k_r:
                cf.CFRelease(k_r)


def _restart_mrd_and_connect(enable_multimon: bool, target_sess: str, reload_only: bool = False) -> None:
    """Chuyển đổi 1 màn <-> 2 màn CHẠY NGẦM 100%:
    - Giấu toàn bộ bảng Connection Center, Edit PC và hộp thoại Connecting... (540x340) ở chế độ ẩn nền.
    - Khi reload_only=True: CHỈ đóng phiên cũ và kết nối lại (reload), tuyệt đối không mở Edit PC, giữ nguyên 100% cài đặt Full-Screen / Use all monitors của người dùng!
    - CHỈ hiện duy nhất cửa sổ Remote Mac (PC Hieu) lên màn hình SAU KHI đã kết nối xong!"""
    global _LAST_DOWNGRADED_1MON_PID, _RESTORE_1MON_BOUNDS_UNTIL, _RDP_RECONNECT_UNTIL
    import AppKit  # type: ignore
    import objc  # type: ignore

    _RDP_RECONNECT_UNTIL = max(_RDP_RECONNECT_UNTIL, time.monotonic() + 14.0)
    pre_front_pid = 0
    try:
        with objc.autorelease_pool():
            fa_p = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            if fa_p is not None:
                pre_front_pid = int(fa_p.processIdentifier())
    except Exception:
        pass

    try:
        bmks_fast = _list_mrd_bookmarks()
        # Nếu reload_only=True hoặc bookmark ĐÃ KHỚP SẴN -> BỎ QUA 100% Edit PC, chỉ đóng phiên cũ và kết nối lại thẳng!
        if reload_only or _bookmark_already_matches(bmks_fast, want_multimon=enable_multimon):
            live_pids_f = _find_live_mrd_pids()
            if not live_pids_f:
                _, app_nm_c = _get_mrd_cli_info()
                if app_nm_c:
                    subprocess.Popen(["open", "-g", "-j", "-a", app_nm_c], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    for _ in range(20):
                        time.sleep(0.15)
                        live_pids_f = _find_live_mrd_pids()
                        if live_pids_f:
                            break
                    time.sleep(0.35)
            new_pid = live_pids_f[0] if live_pids_f else 0
            if new_pid > 0:
                has_open_s = bool(_rdp_probe_vdisp_state()[1])
                _ax_close_session_and_relaunch(new_pid, target_sess, close_existing_session=has_open_s)
        else:
            new_pid = _ax_update_bookmark_display_mode(
                enable_multimon=enable_multimon,
                target_title=target_sess,
                connect_after=True,
            )
        if new_pid <= 0:
            return
        if not enable_multimon and not reload_only:
            _LAST_DOWNGRADED_1MON_PID = new_pid
        else:
            _LAST_DOWNGRADED_1MON_PID = 0

        # Chờ tối đa 0.6s xem lệnh Connect trước đó đã bật Connecting.../PC Hieu chưa trước khi fallback
        conn_started = _has_rdp_session_or_connecting(new_pid, target_sess)
        if not conn_started:
            for _ in range(5):
                time.sleep(0.12)
                if _has_rdp_session_or_connecting(new_pid, target_sess):
                    conn_started = True
                    break
        if not conn_started:
            for _ in range(2):
                _ax_close_session_and_relaunch(new_pid, target_sess, close_existing_session=False)
                for _ in range(6):
                    time.sleep(0.14)
                    if _has_rdp_session_or_connecting(new_pid, target_sess):
                        conn_started = True
                        break
                if conn_started:
                    break

        # Giữ MRD ẩn hoàn toàn (rapp.hide) suốt quá trình hộp thoại Connecting... (540x340) đang bắt tay RDP!
        try:
            with objc.autorelease_pool():
                rapp_bg = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(new_pid)
                if rapp_bg is not None:
                    rapp_bg.hide()
                if pre_front_pid > 0 and pre_front_pid != new_pid:
                    prev_fg = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pre_front_pid)
                    if prev_fg is not None:
                        prev_fg.activateWithOptions_(2)
        except Exception:
            pass

        sess_ready = False
        fin_w, fin_h = 0.0, 0.0
        ready_tick = 0
        for tick_i in range(75):
            ok_real, rw_c, rh_c = _has_real_rdp_session_window(new_pid, target_sess)
            if ok_real:
                sess_ready = True
                fin_w, fin_h = rw_c, rh_c
                ready_tick = tick_i
                break
            try:
                with objc.autorelease_pool():
                    rapp_chk = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(new_pid)
                    if rapp_chk is not None:
                        rapp_chk.hide()
            except Exception:
                pass
            time.sleep(0.08)

        # Trong khi MRD vẫn đang ẩn: đóng sạch Connection Center; chỉ căn kích thước cửa sổ thường khi KHÔNG phải reload_only (giữ Full-Screen)
        _close_cc_silently_while_hidden(new_pid)
        if not enable_multimon and not reload_only:
            _RESTORE_1MON_BOUNDS_UNTIL = time.monotonic() + 12.0
            if sess_ready:
                time.sleep(0.14)
                _, bw_pre, bh_pre = _apply_full_mac_window_bounds(new_pid, target_sess)
                if bw_pre > 0.0:
                    fin_w, fin_h = bw_pre, bh_pre

        # Chạy xong 100% -> Bây giờ mới unhide & hiện duy nhất cửa sổ Remote Mac (PC Hieu) lên màn hình!
        _, app_nm_fin = _get_mrd_cli_info()
        try:
            with objc.autorelease_pool():
                rapp_show = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(new_pid)
                if rapp_show is not None:
                    rapp_show.unhide()
                    rapp_show.activateWithOptions_(3)
                elif app_nm_fin:
                    subprocess.run(["open", "-a", app_nm_fin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.5)
        except Exception:
            pass
        _close_cc_silently_while_hidden(new_pid)
        _RDP_CLOSER_DIAG["stealth_reveal"] = f"ready={int(sess_ready)},ticks={ready_tick},sz={int(fin_w)}x{int(fin_h)}"

        if not enable_multimon and not reload_only:
            for extra_wait in (0.12, 0.45, 0.85):
                time.sleep(extra_wait)
                _apply_full_mac_window_bounds(new_pid, target_sess)
    finally:
        _RDP_RECONNECT_UNTIL = time.monotonic() + 5.0


def trigger_smart_rdp_multimon_sync(
    enable_multimon: bool,
    upgrade_running: bool = False,
    downgrade_running: bool = False,
    repair_clamped: bool = False,
) -> None:
    """Điều phối thông minh 1 màn <-> 2 màn theo topology màn hình thật của MacBook (KHÔNG cần bật Full-Screen trước):
    - Kết nối điện thoại làm màn phụ (1 -> 2 màn): nếu Remote đang mở ở MacBook, tự động reload sang 2 màn để đẩy sang điện thoại.
    - Ngắt màn phụ điện thoại (2 -> 1 màn): nếu Remote đang mở, CHỈ reload lại phiên (giữ nguyên Full-Screen và toàn bộ cài đặt, dồn tất cả tab về lại MacBook)."""
    if not IS_MACOS:
        return

    def _worker() -> None:
        global _RDP_RECONNECT_UNTIL, _LAST_2MON_SYNC_AT, _LAST_1MON_SYNC_AT

        try:
            with _SMART_MULTIMON_LOCK:
                bookmarks = _list_mrd_bookmarks()
                default_title = bookmarks[0][0] if bookmarks else "PC Hieu"
                _RDP_CLOSER_DIAG["worker_trace"] = f"start:mm={int(enable_multimon)},up={int(upgrade_running)},dn={int(downgrade_running)},rep={int(repair_clamped)},bmk={len(bookmarks)}"

                if not enable_multimon:
                    # Nếu người dùng thao tác tắt/bật nhanh liên tục và màn phụ ĐÃ bật trở lại -> bỏ qua lượt ngắt cũ!
                    if _get_secondary_mac_display_bounds(None) is not None:
                        _RDP_CLOSER_DIAG["worker_trace"] += "|stale_1mon_sec_back_on"
                        return
                    rpid, sess, was_2mon_now = _rdp_probe_vdisp_state()
                    # NGUYÊN TẮC BẮT BUỘC: Nếu Remote Mac KHÔNG đang mở (not sess) -> MẶC KỆ 100%, tuyệt đối không tự bật hay đụng vào Microsoft Remote Desktop!
                    if not sess:
                        _RDP_CLOSER_DIAG["worker_trace"] += "|idle_no_sess_1mon"
                        return
                    # Khi vừa ngắt màn hình phụ điện thoại (downgrade_running=True) và Remote Mac đang mở:
                    # CHỈ reload lại đúng 1 lần (reload_only=True), KHÔNG mở Edit PC, KHÔNG tắt Full-Screen -> tất cả tab tự dồn về 1 màn MacBook!
                    need_downgrade = bool(downgrade_running)
                    _RDP_CLOSER_DIAG["worker_trace"] += f"|rpid={rpid},sess={len(sess)},w2={int(was_2mon_now)},nd={int(need_downgrade)}"

                    if need_downgrade:
                        now_d = time.monotonic()
                        if _LAST_1MON_SYNC_AT > 0.0 and (now_d - _LAST_1MON_SYNC_AT) < 4.0:
                            _RDP_CLOSER_DIAG["ax_stage"] = f"debounced:{now_d:.2f}"
                            return
                        _LAST_1MON_SYNC_AT = now_d
                        _LAST_2MON_SYNC_AT = 0.0
                        target_sess = sess[0] if sess else default_title
                        _RDP_RECONNECT_UNTIL = time.monotonic() + 14.0
                        _RDP_CLOSER_DIAG["ax_stage"] = f"calling_reload_1mon:{target_sess}"
                        try:
                            time.sleep(0.25)
                            if _get_secondary_mac_display_bounds(None) is not None:
                                _RDP_CLOSER_DIAG["worker_trace"] += "|abort_1mon_sec_back_on"
                                return
                            _restart_mrd_and_connect(enable_multimon=False, target_sess=target_sess, reload_only=True)
                            _RDP_CLOSER_DIAG["last_reconnect"] = f"reloaded_1mon_fs:{target_sess}@{time.strftime('%H:%M:%S')}"
                        finally:
                            _LAST_1MON_SYNC_AT = time.monotonic()
                            _LAST_2MON_SYNC_AT = 0.0
                            _RDP_RECONNECT_UNTIL = time.monotonic() + 5.0
                    return

                # Khi kết nối màn hình phụ (enable_multimon=True): kiểm tra ngay xem Remote Mac có đang bật không.
                # Nếu Remote Mac KHÔNG bật -> MẶC KỆ 100% (chỉ dùng màn hình phụ thuần cho MacBook, không tự mở hay kích hoạt MRD)!
                rpid_pre, sess_pre, _ = _rdp_probe_vdisp_state()
                if not upgrade_running or not sess_pre:
                    _RDP_CLOSER_DIAG["worker_trace"] += f"|idle_no_sess_2mon:up={int(upgrade_running)},sess={len(sess_pre)}"
                    return

                now_m = time.monotonic()
                if _LAST_2MON_SYNC_AT > 0.0 and (now_m - _LAST_2MON_SYNC_AT) < 4.0:
                    _RDP_CLOSER_DIAG["worker_trace"] += f"|debounced_2mon:{now_m - _LAST_2MON_SYNC_AT:.1f}s"
                    return

                # Chờ màn hình phụ (Màn phụ Mac hoặc màn phụ ĐT bất kỳ) đăng ký xong với WindowServer
                for _ in range(14):
                    if _get_secondary_mac_display_bounds(None) is not None:
                        break
                    time.sleep(0.15)
                time.sleep(0.45)
                if _get_secondary_mac_display_bounds(None) is None:
                    return

                rpid, sess, has_vdisp = _rdp_probe_vdisp_state()
                if not sess:
                    _RDP_CLOSER_DIAG["last_reconnect"] = f"skip_2mon_closed@{time.strftime('%H:%M:%S')}"
                    return
                if has_vdisp:
                    _RDP_CLOSER_DIAG["last_reconnect"] = f"already_2mon@{time.strftime('%H:%M:%S')}"
                    return

                _LAST_2MON_SYNC_AT = time.monotonic()
                _LAST_1MON_SYNC_AT = 0.0
                target_sess = sess[0] if sess else default_title
                _RDP_RECONNECT_UNTIL = time.monotonic() + 14.0
                try:
                    _restart_mrd_and_connect(enable_multimon=True, target_sess=target_sess)
                    _RDP_CLOSER_DIAG["last_reconnect"] = f"upgraded_2mon:{target_sess}@{time.strftime('%H:%M:%S')}"
                finally:
                    _LAST_2MON_SYNC_AT = time.monotonic()
                    _LAST_1MON_SYNC_AT = 0.0
                    _RDP_RECONNECT_UNTIL = time.monotonic() + 5.0
        except Exception as w_exc:
            _RDP_CLOSER_DIAG["last_err"] = f"smart_worker:{repr(w_exc)[:140]}"

    threading.Thread(target=_worker, daemon=True).start()


def start_rdp_launcher_auto_closer(poll_sec: float = 0.20) -> None:
    """Quét xuyên toàn bộ Space (CGWindowListOptionAll):
    1) Hễ Microsoft Remote Desktop / Windows App đang có phiên Remote thật (như PC Hieu) thì tự đóng
       cửa sổ chọn máy (Connection Center) thừa bằng AXCloseButton.
    2) Khi người dùng bấm quay lại Microsoft Remote Desktop (trên SmartRightDock / Dock / Cmd+Tab) mà
       PC Hieu đang nằm ở Full-Screen Space khác (hoặc bị thu nhỏ) không hiện trên màn chính MacBook,
       tự động bấm AXMenuBar -> Window -> <tên phiên Remote> (AXPress) để trượt thẳng vào PC Hieu!"""
    if not IS_MACOS:
        return

    def _watcher() -> None:
        global _LAST_DOWNGRADED_1MON_PID
        import ctypes
        import AppKit  # type: ignore
        import objc  # type: ignore
        from mac_virtual_display import _CGPoint, _CGSize

        launcher_titles = {
            "microsoft remote desktop",
            "windows app",
            "connection center",
            "devices",
            "pcs",
            "workspaces",
            "remote desktop",
        }
        menu_skip_words = (
            "minimize",
            "zoom",
            "close",
            "tile ",
            "move window",
            "bring all",
            "enter full",
            "exit full",
            "merge all",
            "show all tabs",
            "connection center",
            "microsoft remote desktop",
            "windows app",
        )
        dialog_keywords = (
            "edit pc",
            "add pc",
            "preferences",
            "settings",
            "about",
            "certificate",
            "user account",
            "import",
            "connecting",
            "authenticat",
            "sign in",
            "credentials",
            "enter your",
            "password",
        )
        session_first_seen_at = 0.0
        last_close_try_at = 0.0
        last_jump_try_at = 0.0
        last_fit_try_at = 0.0
        last_fs_poll_at = 0.0
        rdp_became_front_at = 0.0
        prev_front_pid = 0
        jump_attempt_idx = 0
        prev_had_sessions = False
        pending_open_topo_sync = False
        repaired_3024_once = False
        prev_sec_disp: Optional[bool] = None
        sec_disp_flip_at: float = 0.0

        while True:
            time.sleep(poll_sec)
            try:
                q = injector._quartz
                if q is not None:
                    # Bỏ qua lúc màn hình MacBook đang khóa (Display Shield -> CGGetActiveDisplayList trả 0 màn)
                    active_cnt = 1
                    try:
                        res_dl = q.CGGetActiveDisplayList(8, None, None)
                        if isinstance(res_dl, tuple) and len(res_dl) == 3 and res_dl[0] == 0:
                            active_cnt = int(res_dl[2])
                    except Exception:
                        active_cnt = 1
                    if active_cnt > 0 or (mac_vdisp is not None and mac_vdisp.is_active()):
                        cur_sec_disp = (_get_secondary_mac_display_bounds(q) is not None)
                        _RDP_CLOSER_DIAG["sec_display_active"] = cur_sec_disp
                        if prev_sec_disp is None:
                            prev_sec_disp = cur_sec_disp
                        elif cur_sec_disp != prev_sec_disp:
                            if sec_disp_flip_at <= 0.0:
                                sec_disp_flip_at = time.monotonic()
                            elif (time.monotonic() - sec_disp_flip_at) >= 0.30:
                                prev_sec_disp = cur_sec_disp
                                sec_disp_flip_at = 0.0
                                if cur_sec_disp:
                                    # Vừa kết nối điện thoại làm màn hình phụ (1 màn -> 2 màn) -> tự reload phiên Remote đang mở!
                                    trigger_smart_rdp_multimon_sync(enable_multimon=True, upgrade_running=True)
                                else:
                                    # Vừa ngắt màn hình phụ điện thoại (2 màn -> 1 màn) -> tự reload phiên Remote về lại 1 cửa sổ MacBook!
                                    trigger_smart_rdp_multimon_sync(
                                        enable_multimon=False,
                                        upgrade_running=False,
                                        downgrade_running=True,
                                    )
                        else:
                            sec_disp_flip_at = 0.0

                if time.monotonic() < _RDP_RECONNECT_UNTIL:
                    continue
                if q is None or mac_vdisp is None or not mac_vdisp._init_ax_libs():
                    continue

                # Lấy rdp_pid trực tiếp từ WindowServer (CGWindowListOptionAll) & front_pid từ AXFocusedApplication
                # (TUYỆT ĐỐI không dựa vào NSWorkspace.runningApplications() vì cache bị cũ trong tiến trình không chạy NSRunLoop!)
                ax = mac_vdisp._ax_lib
                cf = mac_vdisp._cf_lib
                kCFStringEncodingUTF8 = 0x08000100

                def _cfstr(s: str) -> ctypes.c_void_p:
                    return cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)

                front_pid = 0
                sys_ax = ax.AXUIElementCreateSystemWide()
                if sys_ax:
                    s_foc = _cfstr("AXFocusedApplication")
                    try:
                        foc_ref = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(sys_ax, s_foc, ctypes.byref(foc_ref)) == 0 and foc_ref.value:
                            try:
                                p_val = ctypes.c_int32(0)
                                if ax.AXUIElementGetPid(foc_ref.value, ctypes.byref(p_val)) == 0:
                                    front_pid = int(p_val.value)
                            finally:
                                cf.CFRelease(foc_ref.value)
                    finally:
                        cf.CFRelease(sys_ax)
                        if s_foc:
                            cf.CFRelease(s_foc)

                # Bước 1: Dùng CGWindowListOptionAll (thấy xuyên TẤT CẢ Space + luôn live PID mới nhất!)
                main_b = q.CGDisplayBounds(q.CGMainDisplayID())
                main_x = float(main_b.origin.x)
                main_w = float(main_b.size.width)
                main_h = float(main_b.size.height)

                rdp_pid = 0
                rdp_app = None
                session_titles: List[str] = []
                session_titles_lower: set = set()
                on_screen_session_main = False
                all_has_launcher = False
                all_has_unnamed_big = False
                all_has_dialog = False
                with objc.autorelease_pool():
                    wlist = q.CGWindowListCopyWindowInfo(
                        q.kCGWindowListOptionAll | q.kCGWindowListExcludeDesktopElements,
                        q.kCGNullWindowID,
                    ) or []
                    for w in wlist:
                        owner_l = str(w.get("kCGWindowOwnerName", "") or "").strip().lower()
                        if "microsoft remote desktop" not in owner_l and "windows app" not in owner_l and "com.microsoft.rdc" not in owner_l:
                            continue
                        pid_w = int(w.get("kCGWindowOwnerPID", 0) or 0)
                        if pid_w <= 0:
                            continue
                        if rdp_pid <= 0:
                            rdp_pid = pid_w
                        if int(w.get("kCGWindowLayer", -1)) != 0:
                            continue
                        wb = w.get("kCGWindowBounds") or {}
                        wx = float(wb.get("X", 0))
                        ww = float(wb.get("Width", 0))
                        wh = float(wb.get("Height", 0))
                        if ww < 120.0 or wh < 80.0:
                            continue
                        wname_raw = str(w.get("kCGWindowName", "") or "").strip()
                        wname_l = wname_raw.lower()
                        is_onscreen = bool(w.get("kCGWindowIsOnscreen", False))
                        in_main = (main_x <= (wx + ww * 0.5) < (main_x + main_w))
                        if wname_l and any(k in wname_l for k in dialog_keywords):
                            if is_onscreen:
                                all_has_dialog = True
                            continue
                        elif wname_l in launcher_titles:
                            all_has_launcher = True
                        elif wname_raw and ww >= 620.0 and wh >= 200.0:
                            rdp_pid = pid_w
                            if wname_l not in session_titles_lower:
                                session_titles_lower.add(wname_l)
                                session_titles.append(wname_raw)
                            if is_onscreen and in_main:
                                on_screen_session_main = True
                        elif not wname_raw and ww >= 600.0 and wh >= 380.0:
                            all_has_unnamed_big = True
                    if rdp_pid > 0:
                        try:
                            rdp_app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(rdp_pid)
                        except Exception:
                            rdp_app = None

                now_m = time.monotonic()
                just_activated_rdp = (rdp_pid > 0 and front_pid == rdp_pid and prev_front_pid != rdp_pid)
                if just_activated_rdp:
                    rdp_became_front_at = now_m
                    jump_attempt_idx = 0
                elif front_pid != rdp_pid:
                    rdp_became_front_at = 0.0
                    jump_attempt_idx = 0
                prev_front_pid = front_pid

                if rdp_pid <= 0:
                    prev_had_sessions = False
                    pending_open_topo_sync = False
                    session_first_seen_at = 0.0
                    _RDP_CLOSER_DIAG["sessions"] = []
                    _RDP_CLOSER_DIAG["on_screen_main"] = False
                    _RDP_CLOSER_DIAG["launcher_seen"] = False
                    continue

                _RDP_CLOSER_DIAG["rdp_pid"] = rdp_pid
                _RDP_CLOSER_DIAG["front_pid"] = front_pid
                _RDP_CLOSER_DIAG["sessions"] = list(session_titles)
                _RDP_CLOSER_DIAG["on_screen_main"] = bool(on_screen_session_main)
                _RDP_CLOSER_DIAG["launcher_seen"] = bool(all_has_launcher or all_has_unnamed_big)

                if not session_titles:
                    prev_had_sessions = False
                    pending_open_topo_sync = False
                    session_first_seen_at = 0.0
                    continue
                if not prev_had_sessions:
                    prev_had_sessions = True
                    pending_open_topo_sync = True
                if session_first_seen_at <= 0.0:
                    session_first_seen_at = now_m
                if all_has_dialog or (now_m - session_first_seen_at) < 0.35:
                    continue

                # Nếu người dùng VỪA CHỦ ĐỘNG MỞ Remote Mac lên trong khi màn hình phụ điện thoại đang kết nối sẵn ->
                # tự động nâng cấp phiên Remote vừa mở sang 2 màn hình để đẩy sang màn phụ (CHỈ 1 lần, không lặp)!
                if pending_open_topo_sync and (now_m - session_first_seen_at) >= 0.70:
                    pending_open_topo_sync = False
                    if now_m >= _MANUAL_WINDOWED_OPEN_UNTIL and (now_m - _LAST_2MON_SYNC_AT) >= 12.0:
                        has_sec_open = (_get_secondary_mac_display_bounds(q) is not None)
                        _, live_sess_o, live_vd_o = _rdp_probe_vdisp_state()
                        if has_sec_open and live_sess_o and not live_vd_o:
                            trigger_smart_rdp_multimon_sync(enable_multimon=True, upgrade_running=True)
                            continue

                want_check_close = (
                    (all_has_launcher or all_has_unnamed_big)
                    and (now_m - session_first_seen_at) >= 0.35
                    and (now_m - last_close_try_at) >= 0.45
                )
                want_check_jump = (
                    front_pid == rdp_pid
                    and not on_screen_session_main
                    and (
                        just_activated_rdp
                        or (
                            rdp_became_front_at > 0.0
                            and (now_m - rdp_became_front_at) < 2.2
                            and (now_m - last_jump_try_at) >= 0.55
                        )
                    )
                )
                # Giữ nguyên 100% tùy chọn Fit/tỉ lệ người dùng đã tự cài trong Remote Desktop
                want_check_fit = False
                want_check_fs_state = (
                    on_screen_session_main
                    and (now_m - last_fs_poll_at) >= 0.55
                )
                if not want_check_close and not want_check_jump and not want_check_fit and not want_check_fs_state:
                    continue
                if want_check_fs_state:
                    last_fs_poll_at = now_m

                # Bước 2: Dùng AXWindows đóng Connection Center thừa + AXMenuBar -> Window -> <session> để trượt thẳng vào PC Hieu!

                def _get_str(el_ref: Any, attr_ref: Any) -> str:
                    r = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(el_ref, attr_ref, ctypes.byref(r)) == 0 and r.value:
                        try:
                            with objc.autorelease_pool():
                                return str(objc.objc_object(c_void_p=r.value) or "")
                        finally:
                            cf.CFRelease(r.value)
                    return ""

                def _get_bool(el_ref: Any, attr_ref: Any) -> bool:
                    r = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(el_ref, attr_ref, ctypes.byref(r)) == 0 and r.value:
                        try:
                            return bool(cf.CFBooleanGetValue(r.value))
                        finally:
                            cf.CFRelease(r.value)
                    return False

                def _get_pos(el_ref: Any, attr_ref: Any) -> Tuple[float, float]:
                    r = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(el_ref, attr_ref, ctypes.byref(r)) == 0 and r.value:
                        try:
                            pt = _CGPoint()
                            if ax.AXValueGetValue(r.value, 1, ctypes.byref(pt)):
                                return float(pt.x), float(pt.y)
                        finally:
                            cf.CFRelease(r.value)
                    return 0.0, 38.0

                def _get_size(el_ref: Any, attr_ref: Any) -> Tuple[float, float]:
                    r = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(el_ref, attr_ref, ctypes.byref(r)) == 0 and r.value:
                        try:
                            sz = _CGSize()
                            if ax.AXValueGetValue(r.value, 2, ctypes.byref(sz)):
                                return float(sz.w), float(sz.h)
                        finally:
                            cf.CFRelease(r.value)
                    return 0.0, 0.0

                app_ax = ax.AXUIElementCreateApplication(rdp_pid)
                if not app_ax:
                    continue
                s_wins = _cfstr("AXWindows")
                s_title = _cfstr("AXTitle")
                s_subrole = _cfstr("AXSubrole")
                s_fullscreen = _cfstr("AXFullScreen")
                s_pos = _cfstr("AXPosition")
                s_size = _cfstr("AXSize")
                s_close_btn = _cfstr("AXCloseButton")
                s_press = _cfstr("AXPress")
                s_menubar = _cfstr("AXMenuBar")
                s_children = _cfstr("AXChildren")
                s_mark = _cfstr("AXMenuItemMarkChar")
                s_enabled = _cfstr("AXEnabled")

                def _ensure_fit_window_menu() -> bool:
                    mb_ref = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_menubar, ctypes.byref(mb_ref)) != 0 or not mb_ref.value:
                        return False
                    try:
                        bar_items_ref = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(mb_ref.value, s_children, ctypes.byref(bar_items_ref)) != 0 or not bar_items_ref.value:
                            return False
                        try:
                            n_bar = cf.CFArrayGetCount(bar_items_ref.value)
                            dbg = []
                            for bi in range(n_bar):
                                b_el = cf.CFArrayGetValueAtIndex(bar_items_ref.value, bi)
                                if not b_el:
                                    continue
                                bt = _get_str(b_el, s_title).strip().lower()
                                if bt not in ("window", "view", "connection", "connections", "cửa sổ", "xem"):
                                    continue
                                sub_arr = ctypes.c_void_p()
                                if ax.AXUIElementCopyAttributeValue(b_el, s_children, ctypes.byref(sub_arr)) != 0 or not sub_arr.value:
                                    continue
                                try:
                                    if cf.CFArrayGetCount(sub_arr.value) <= 0:
                                        continue
                                    menu_el = cf.CFArrayGetValueAtIndex(sub_arr.value, 0)
                                    if not menu_el:
                                        continue
                                    items_arr = ctypes.c_void_p()
                                    if ax.AXUIElementCopyAttributeValue(menu_el, s_children, ctypes.byref(items_arr)) != 0 or not items_arr.value:
                                        continue
                                    try:
                                        n_items = cf.CFArrayGetCount(items_arr.value)
                                        for mi in range(n_items):
                                            m_el = cf.CFArrayGetValueAtIndex(items_arr.value, mi)
                                            if not m_el:
                                                continue
                                            mt_raw = _get_str(m_el, s_title).strip()
                                            if not mt_raw:
                                                continue
                                            mt_l = mt_raw.lower()
                                            mk = _get_str(m_el, s_mark).strip()
                                            en = _get_bool(m_el, s_enabled)
                                            if len(dbg) < 40:
                                                dbg.append(f"{bt}:{mt_raw}[m={mk}|e={int(en)}]")
                                            if "fit" in mt_l and "window" in mt_l and en and not mk:
                                                if ax.AXUIElementPerformAction(m_el, s_press) == 0:
                                                    _RDP_CLOSER_DIAG["last_action"] = f"auto_fit_window@{time.strftime('%H:%M:%S')}"
                                                    return True
                                    finally:
                                        cf.CFRelease(items_arr.value)
                                finally:
                                    cf.CFRelease(sub_arr.value)
                            if dbg:
                                _RDP_CLOSER_DIAG["win_menu_debug"] = dbg
                        finally:
                            cf.CFRelease(bar_items_ref.value)
                    finally:
                        cf.CFRelease(mb_ref.value)
                    return False

                def _jump_via_window_menu(attempt_idx: int) -> bool:
                    mb_ref = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_menubar, ctypes.byref(mb_ref)) != 0 or not mb_ref.value:
                        return False
                    try:
                        bar_items_ref = ctypes.c_void_p()
                        if ax.AXUIElementCopyAttributeValue(mb_ref.value, s_children, ctypes.byref(bar_items_ref)) != 0 or not bar_items_ref.value:
                            return False
                        try:
                            n_bar = cf.CFArrayGetCount(bar_items_ref.value)
                            win_menu_items = []
                            fallback_menu_items = []
                            for bi in range(n_bar):
                                b_el = cf.CFArrayGetValueAtIndex(bar_items_ref.value, bi)
                                if not b_el:
                                    continue
                                bt = _get_str(b_el, s_title).strip().lower()
                                if bt in ("window", "cửa sổ"):
                                    win_menu_items.append(b_el)
                                elif bt not in ("apple", "", "help", "edit", "file"):
                                    fallback_menu_items.append(b_el)

                            scan_menus = win_menu_items if win_menu_items else fallback_menu_items[:2]
                            for b_el in scan_menus:
                                sub_arr = ctypes.c_void_p()
                                if ax.AXUIElementCopyAttributeValue(b_el, s_children, ctypes.byref(sub_arr)) != 0 or not sub_arr.value:
                                    continue
                                try:
                                    if cf.CFArrayGetCount(sub_arr.value) <= 0:
                                        continue
                                    menu_el = cf.CFArrayGetValueAtIndex(sub_arr.value, 0)
                                    if not menu_el:
                                        continue
                                    items_arr = ctypes.c_void_p()
                                    if ax.AXUIElementCopyAttributeValue(menu_el, s_children, ctypes.byref(items_arr)) != 0 or not items_arr.value:
                                        continue
                                    try:
                                        n_items = cf.CFArrayGetCount(items_arr.value)
                                        all_item_titles = []
                                        exact_matches = []
                                        partial_matches = []
                                        for mi in range(n_items):
                                            m_el = cf.CFArrayGetValueAtIndex(items_arr.value, mi)
                                            if not m_el:
                                                continue
                                            mt_raw = _get_str(m_el, s_title).strip()
                                            if not mt_raw:
                                                continue
                                            all_item_titles.append(mt_raw)
                                            mt_l = mt_raw.lower()
                                            if mt_l in session_titles_lower:
                                                exact_matches.append((m_el, mt_raw))
                                            elif not any(sw in mt_l for sw in menu_skip_words):
                                                if any(st_l in mt_l for st_l in session_titles_lower):
                                                    partial_matches.append((m_el, mt_raw))
                                        if all_item_titles:
                                            _RDP_CLOSER_DIAG["last_menu_items"] = all_item_titles[-15:]
                                        matches = exact_matches or partial_matches
                                        if matches:
                                            chosen_el, chosen_title = matches[attempt_idx % len(matches)]
                                            rc = ax.AXUIElementPerformAction(chosen_el, s_press)
                                            if rc == 0:
                                                _RDP_CLOSER_DIAG["jumped_count"] = int(_RDP_CLOSER_DIAG.get("jumped_count", 0)) + 1
                                                _RDP_CLOSER_DIAG["last_action"] = f"menu_jump:{chosen_title}@{time.strftime('%H:%M:%S')}"
                                                return True
                                            _RDP_CLOSER_DIAG["last_err"] = f"menu_press_rc={rc}"
                                    finally:
                                        cf.CFRelease(items_arr.value)
                                finally:
                                    cf.CFRelease(sub_arr.value)
                        finally:
                            cf.CFRelease(bar_items_ref.value)
                    finally:
                        cf.CFRelease(mb_ref.value)
                    return False

                try:
                    ax_has_dialog = False
                    closed_any = False
                    has_windowed_session = False
                    has_squished_2mon_window = False
                    has_fs_session = False
                    need_expand_tiny_title = ""
                    wins_ref = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wins_ref)) == 0 and wins_ref.value:
                        try:
                            cnt = cf.CFArrayGetCount(wins_ref.value)
                            ax_summary = []
                            parsed_wins = []
                            ax_confirmed_session = False
                            for i in range(cnt):
                                w_ax = cf.CFArrayGetValueAtIndex(wins_ref.value, i)
                                if not w_ax:
                                    continue
                                title_raw = _get_str(w_ax, s_title).strip()
                                title_l = title_raw.lower()
                                sub_s = _get_str(w_ax, s_subrole).strip()
                                is_fs = _get_bool(w_ax, s_fullscreen)
                                sw, sh = _get_size(w_ax, s_size)
                                ax_summary.append(f"{title_raw or '<empty>'}|{sub_s}|fs={int(is_fs)}|{int(sw)}x{int(sh)}")
                                if (sub_s in ("AXDialog", "AXSheet") and sw >= 240.0 and sh >= 110.0) or any(k in title_l for k in dialog_keywords):
                                    ax_has_dialog = True
                                    break
                                if title_l in session_titles_lower:
                                    ax_confirmed_session = True
                                    if is_fs:
                                        has_fs_session = True
                                    elif sub_s == "AXStandardWindow":
                                        has_windowed_session = True
                                        if _is_mrd_tiny_default_box(sw, sh):
                                            need_expand_tiny_title = title_raw
                                        elif not _RDP_CLOSER_DIAG.get("sec_display_active") and now_m > _RESTORE_1MON_BOUNDS_UNTIL:
                                            wx_p, wy_p = _get_pos(w_ax, s_pos)
                                            _save_user_1mon_bounds(wx_p, wy_p, sw, sh)
                                parsed_wins.append((w_ax, title_raw, title_l, sub_s, is_fs, sw, sh))

                            launcher_wins = []
                            for w_ax, title_raw, title_l, sub_s, is_fs, sw, sh in parsed_wins:
                                if (
                                    not is_fs
                                    and sub_s == "AXStandardWindow"
                                    and title_l not in session_titles_lower
                                    and (
                                        title_l in launcher_titles
                                        or (ax_confirmed_session and title_l == "" and sw >= 480.0 and sh >= 300.0)
                                    )
                                ):
                                    launcher_wins.append((w_ax, title_raw or "<empty>"))

                            _RDP_CLOSER_DIAG["last_ax_wins"] = ax_summary[:10]
                            if not ax_has_dialog and launcher_wins and (now_m - session_first_seen_at) >= 0.35 and (now_m - last_close_try_at) >= 0.45:
                                last_close_try_at = now_m
                                for lw, ltitle in launcher_wins:
                                    btn_ref = ctypes.c_void_p()
                                    if (
                                        ax.AXUIElementCopyAttributeValue(lw, s_close_btn, ctypes.byref(btn_ref)) == 0
                                        and btn_ref.value
                                    ):
                                        try:
                                            rc_c = ax.AXUIElementPerformAction(btn_ref.value, s_press)
                                            if rc_c == 0:
                                                closed_any = True
                                                _RDP_CLOSER_DIAG["closed_count"] = int(_RDP_CLOSER_DIAG.get("closed_count", 0)) + 1
                                                _RDP_CLOSER_DIAG["last_action"] = f"closed:{ltitle}@{time.strftime('%H:%M:%S')}"
                                            else:
                                                _RDP_CLOSER_DIAG["last_err"] = f"close_rc={rc_c}"
                                        finally:
                                            cf.CFRelease(btn_ref.value)
                        finally:
                            cf.CFRelease(wins_ref.value)

                    if has_fs_session:
                        _LAST_DOWNGRADED_1MON_PID = 0
                    if need_expand_tiny_title and not ax_has_dialog:
                        ok_exp, ew, eh = _apply_full_mac_window_bounds(rdp_pid, need_expand_tiny_title)
                        if ok_exp:
                            _RDP_CLOSER_DIAG["last_action"] = f"restored_bounds:{int(ew)}x{int(eh)}@{time.strftime('%H:%M:%S')}"

                    # Khi PC Hieu đang ở cửa sổ thường (fs=0): tự bật Fit Session to Window nếu bị bỏ tích để không bị phóng to 2x cắt màn hình!
                    if (
                        not ax_has_dialog
                        and has_windowed_session
                        and want_check_fit
                    ):
                        last_fit_try_at = now_m
                        _ensure_fit_window_menu()

                    # Khi bấm quay lại Microsoft Remote Desktop mà PC Hieu chưa hiện trên màn chính -> trượt thẳng vào PC Hieu!
                    if (
                        not ax_has_dialog
                        and front_pid == rdp_pid
                        and not on_screen_session_main
                        and (closed_any or want_check_jump)
                        and (now_m - last_jump_try_at) >= 0.45
                    ):
                        last_jump_try_at = now_m
                        if closed_any:
                            time.sleep(0.05)
                        if rdp_app is not None:
                            try:
                                with objc.autorelease_pool():
                                    if bool(rdp_app.isHidden()):
                                        rdp_app.unhide()
                            except Exception:
                                pass
                        jumped = _jump_via_window_menu(jump_attempt_idx)
                        if not jumped and rdp_app is not None:
                            try:
                                with objc.autorelease_pool():
                                    # Đảm bảo app active trở lại nếu vừa đóng Connection Center khiến macOS rơi focus, rồi bấm lại Window -> PC Hieu
                                    rdp_app.activateWithOptions_(3)
                                time.sleep(0.06)
                                jumped = _jump_via_window_menu(jump_attempt_idx)
                                if not jumped:
                                    _RDP_CLOSER_DIAG["last_action"] = f"activate_all@{time.strftime('%H:%M:%S')}"
                            except Exception:
                                pass
                        jump_attempt_idx += 1
                finally:
                    cf.CFRelease(app_ax)
                    for s_ref in (
                        s_wins, s_title, s_subrole, s_fullscreen, s_pos, s_size,
                        s_close_btn, s_press, s_menubar, s_children, s_mark, s_enabled,
                    ):
                        if s_ref:
                            cf.CFRelease(s_ref)
            except Exception as exc:
                _RDP_CLOSER_DIAG["last_err"] = str(exc)[:160]

    t = threading.Thread(target=_watcher, daemon=True)
    t.start()


if __name__ == "__main__":
    check_macos_accessibility()
    check_macos_screen_recording(prompt=True)
    start_notification_auto_dismisser(max_seconds=4.0)
    start_clipboard_retina_normalizer(poll_sec=0.25)
    start_rdp_launcher_auto_closer(poll_sec=0.15)
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
        ws_ping_timeout=60,
    )
