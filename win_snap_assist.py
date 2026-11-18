#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 11 Snap Assist + Linked Split Group + Live Cooperative Divider Resize cho macOS.
Chạy nền qua Python.app (đã có quyền Accessibility & Screen Recording).
"""

import ctypes
import ctypes.util
import math
import os
import time
from typing import Dict, List, Optional, Tuple

import AppKit  # type: ignore
import Foundation  # type: ignore
import objc  # type: ignore
import Quartz  # type: ignore

# ============================================================================
# CẤU HÌNH CẦU NỐI ACCESSIBILITY (AXUIElement) CẤP THẤP
# ============================================================================
app_services = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


kAXValueCGPointType = 1
kAXValueCGSizeType = 2
kCFStringEncodingUTF8 = 0x08000100

cf.CFStringCreateWithCString.restype = ctypes.c_void_p
cf.CFStringCreateWithCString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_uint32,
]
cf.CFRelease.restype = None
cf.CFRelease.argtypes = [ctypes.c_void_p]

app_services.AXUIElementCreateApplication.restype = ctypes.c_void_p
app_services.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
app_services.AXUIElementCopyAttributeValue.restype = ctypes.c_int
app_services.AXUIElementCopyAttributeValue.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]
app_services.AXUIElementSetAttributeValue.restype = ctypes.c_int
app_services.AXUIElementSetAttributeValue.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
app_services.AXUIElementPerformAction.restype = ctypes.c_int
app_services.AXUIElementPerformAction.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
app_services.AXValueCreate.restype = ctypes.c_void_p
app_services.AXValueCreate.argtypes = [ctypes.c_int, ctypes.c_void_p]
app_services.AXValueGetValue.restype = ctypes.c_bool
app_services.AXValueGetValue.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
]

_CFSTR_CACHE: Dict[str, int] = {}


def cfstr(s: str) -> int:
    if s not in _CFSTR_CACHE:
        _CFSTR_CACHE[s] = cf.CFStringCreateWithCString(
            None, s.encode("utf-8"), kCFStringEncodingUTF8
        )
    return _CFSTR_CACHE[s]


def ax_get_obj(elem_ptr: int, attr: str):
    if not elem_ptr:
        return None
    out = ctypes.c_void_p()
    err = app_services.AXUIElementCopyAttributeValue(
        elem_ptr, cfstr(attr), ctypes.byref(out)
    )
    if err == 0 and out.value:
        return objc.objc_object(c_void_p=out.value)
    return None


def ax_get_frame(elem_ptr: int) -> Optional[Tuple[float, float, float, float]]:
    if not elem_ptr:
        return None
    pos_out = ctypes.c_void_p()
    sz_out = ctypes.c_void_p()
    e1 = app_services.AXUIElementCopyAttributeValue(
        elem_ptr, cfstr("AXPosition"), ctypes.byref(pos_out)
    )
    e2 = app_services.AXUIElementCopyAttributeValue(
        elem_ptr, cfstr("AXSize"), ctypes.byref(sz_out)
    )
    if e1 != 0 or e2 != 0 or not pos_out.value or not sz_out.value:
        if pos_out.value:
            cf.CFRelease(pos_out.value)
        if sz_out.value:
            cf.CFRelease(sz_out.value)
        return None
    pt = CGPoint()
    sz = CGSize()
    ok1 = app_services.AXValueGetValue(pos_out.value, kAXValueCGPointType, ctypes.byref(pt))
    ok2 = app_services.AXValueGetValue(sz_out.value, kAXValueCGSizeType, ctypes.byref(sz))
    cf.CFRelease(pos_out.value)
    cf.CFRelease(sz_out.value)
    if not ok1 or not ok2:
        return None
    return (float(pt.x), float(pt.y), float(sz.width), float(sz.height))


def ax_set_frame(
    elem_ptr: int, x: float, y: float, w: float, h: float, size_first: bool = False
) -> None:
    if not elem_ptr:
        return
    pt = CGPoint(float(x), float(y))
    sz = CGSize(max(220.0, float(w)), max(160.0, float(h)))
    pos_val = app_services.AXValueCreate(kAXValueCGPointType, ctypes.byref(pt))
    sz_val = app_services.AXValueCreate(kAXValueCGSizeType, ctypes.byref(sz))
    if size_first:
        if sz_val:
            app_services.AXUIElementSetAttributeValue(elem_ptr, cfstr("AXSize"), sz_val)
        if pos_val:
            app_services.AXUIElementSetAttributeValue(
                elem_ptr, cfstr("AXPosition"), pos_val
            )
    else:
        if pos_val:
            app_services.AXUIElementSetAttributeValue(
                elem_ptr, cfstr("AXPosition"), pos_val
            )
        if sz_val:
            app_services.AXUIElementSetAttributeValue(elem_ptr, cfstr("AXSize"), sz_val)
        if pos_val:
            app_services.AXUIElementSetAttributeValue(
                elem_ptr, cfstr("AXPosition"), pos_val
            )
    if pos_val:
        cf.CFRelease(pos_val)
    if sz_val:
        cf.CFRelease(sz_val)


def ax_unminimize_and_raise(elem_ptr: int) -> None:
    if not elem_ptr:
        return
    try:
        k_false = ctypes.c_void_p.in_dll(cf, "kCFBooleanFalse")
        app_services.AXUIElementSetAttributeValue(
            elem_ptr, cfstr("AXMinimized"), k_false
        )
    except Exception:
        pass
    app_services.AXUIElementPerformAction(elem_ptr, cfstr("AXRaise"))


def get_screen_usable_bounds() -> Tuple[float, float, float, float]:
    """Trả về (sx, sy, sw, sh) theo hệ tọa độ Quartz (gốc (0,0) ở góc trên-trái màn hình)."""
    scr = AppKit.NSScreen.mainScreen()
    if not scr:
        return (0.0, 38.0, 1512.0, 944.0)
    full = scr.frame()
    vis = scr.visibleFrame()
    total_h = float(full.size.height)
    sx = float(vis.origin.x)
    sw = float(vis.size.width)
    sh = float(vis.size.height)
    sy = total_h - float(vis.origin.y + vis.size.height)
    return (sx, sy, sw, sh)


def quartz_to_cocoa_rect(
    qx: float, qy: float, qw: float, qh: float
) -> Foundation.NSRect:
    scr = AppKit.NSScreen.mainScreen()
    total_h = float(scr.frame().size.height) if scr else 982.0
    cy = total_h - qy - qh
    return Foundation.NSMakeRect(qx, cy, qw, qh)


# ============================================================================
# QUẢN LÝ NHÓM SPLIT & SNAP ASSIST
# ============================================================================
class WindowRef:
    def __init__(
        self,
        pid: int,
        app_name: str,
        bundle_id: str,
        title: str,
        ax_win_obj,
        icon: Optional[AppKit.NSImage],
        slot: str,
        expected_frame: Tuple[float, float, float, float],
    ) -> None:
        self.pid = pid
        self.app_name = app_name
        self.bundle_id = bundle_id
        self.title = title
        self.ax_win_obj = ax_win_obj
        self.icon = icon
        self.slot = slot  # "left", "right", "top", "bottom", "tl", "bl", "tr", "br"
        self.expected_frame = expected_frame

    @property
    def ptr(self) -> int:
        return self.ax_win_obj.__c_void_p__() if self.ax_win_obj is not None else 0


class SplitDividerView(AppKit.NSView):
    def initWithFrame_controller_vertical_(self, frame, ctrl, is_vert: bool):
        self = objc.super(SplitDividerView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.ctrl = ctrl
        self.is_vert = is_vert
        self.hovered = False
        self.dragging = False
        area = AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            AppKit.NSTrackingMouseEnteredAndExited
            | AppKit.NSTrackingActiveAlways
            | AppKit.NSTrackingInVisibleRect,
            self,
            None,
        )
        self.addTrackingArea_(area)
        return self

    def acceptsFirstMouse_(self, event):
        return True

    def resetCursorRects(self):
        cursor = (
            AppKit.NSCursor.resizeLeftRightCursor()
            if self.is_vert
            else AppKit.NSCursor.resizeUpDownCursor()
        )
        self.addCursorRect_cursor_(self.bounds(), cursor)

    def mouseEntered_(self, event):
        self.hovered = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        if not self.dragging:
            self.hovered = False
            self.setNeedsDisplay_(True)

    def mouseDown_(self, event):
        self.dragging = True
        self.hovered = True
        self.setNeedsDisplay_(True)

    def mouseDragged_(self, event):
        loc = AppKit.NSEvent.mouseLocation()
        scr = AppKit.NSScreen.mainScreen()
        total_h = float(scr.frame().size.height) if scr else 982.0
        qx = float(loc.x)
        qy = total_h - float(loc.y)
        self.ctrl.on_divider_drag(qx, qy, self.is_vert)

    def mouseUp_(self, event):
        self.dragging = False
        self.hovered = False
        self.setNeedsDisplay_(True)
        self.ctrl.on_divider_drag_end()

    def drawRect_(self, rect):
        AppKit.NSColor.clearColor().set()
        AppKit.NSBezierPath.fillRect_(self.bounds())
        if not self.hovered and not self.dragging:
            return
        b = self.bounds()
        # Vẽ thanh dọc mờ + viên thuốc (pill) ở giữa giống hệt Windows 11
        bg_alpha = 0.55 if self.dragging else 0.35
        AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.15, bg_alpha).set()
        line_rect = (
            Foundation.NSInsetRect(b, 2.0, 0.0)
            if self.is_vert
            else Foundation.NSInsetRect(b, 0.0, 2.0)
        )
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            line_rect, 3.0, 3.0
        ).fill()

        AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.92, 0.95).set()
        if self.is_vert:
            pill = Foundation.NSMakeRect(
                b.size.width / 2.0 - 2.0, b.size.height / 2.0 - 22.0, 4.0, 44.0
            )
        else:
            pill = Foundation.NSMakeRect(
                b.size.width / 2.0 - 22.0, b.size.height / 2.0 - 2.0, 44.0, 4.0
            )
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            pill, 2.0, 2.0
        ).fill()


class SnapAssistCardView(AppKit.NSView):
    def initWithFrame_candidate_callback_(self, frame, cand: dict, cb):
        self = objc.super(SnapAssistCardView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.cand = cand
        self.cb = cb
        self.hovered = False
        area = AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            AppKit.NSTrackingMouseEnteredAndExited
            | AppKit.NSTrackingActiveAlways
            | AppKit.NSTrackingInVisibleRect,
            self,
            None,
        )
        self.addTrackingArea_(area)
        return self

    def acceptsFirstMouse_(self, event):
        return True

    def mouseEntered_(self, event):
        self.hovered = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self.hovered = False
        self.setNeedsDisplay_(True)

    def mouseDown_(self, event):
        if self.cb:
            self.cb(self.cand)

    def drawRect_(self, rect):
        b = self.bounds()
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            Foundation.NSInsetRect(b, 1.5, 1.5), 12.0, 12.0
        )
        if self.hovered:
            AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
                0.22, 0.52, 0.96, 0.34
            ).setFill()
            AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
                0.38, 0.68, 1.0, 0.90
            ).setStroke()
            path.setLineWidth_(2.0)
        else:
            AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.10).setFill()
            AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.22).setStroke()
            path.setLineWidth_(1.0)
        path.fill()
        path.stroke()

        icon = self.cand.get("icon")
        if icon:
            ico_size = 44.0
            ico_rect = Foundation.NSMakeRect(
                (b.size.width - ico_size) / 2.0,
                b.size.height - ico_size - 16.0,
                ico_size,
                ico_size,
            )
            icon.drawInRect_fromRect_operation_fraction_(
                ico_rect,
                Foundation.NSZeroRect,
                AppKit.NSCompositingOperationSourceOver,
                1.0,
            )

        app_name = str(self.cand.get("app_name") or "Ứng dụng")
        title = str(self.cand.get("title") or app_name)
        if len(title) > 30:
            title = title[:28] + "…"

        para = AppKit.NSMutableParagraphStyle.alloc().init()
        para.setAlignment_(AppKit.NSTextAlignmentCenter)
        para.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)

        title_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(12.5),
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
            AppKit.NSParagraphStyleAttributeName: para,
        }
        sub_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(11.0),
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.colorWithCalibratedWhite_alpha_(
                0.82, 0.9
            ),
            AppKit.NSParagraphStyleAttributeName: para,
        }

        Foundation.NSString.stringWithString_(app_name).drawInRect_withAttributes_(
            Foundation.NSMakeRect(8.0, 28.0, b.size.width - 16.0, 18.0), title_attrs
        )
        Foundation.NSString.stringWithString_(title).drawInRect_withAttributes_(
            Foundation.NSMakeRect(8.0, 10.0, b.size.width - 16.0, 16.0), sub_attrs
        )


class CloseBtnView(AppKit.NSView):
    def initWithFrame_callback_(self, frame, cb):
        self = objc.super(CloseBtnView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.cb = cb
        return self

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        if self.cb:
            self.cb()

    def drawRect_(self, rect):
        b = self.bounds()
        p = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(b, 8.0, 8.0)
        AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.14).setFill()
        p.fill()
        para = AppKit.NSMutableParagraphStyle.alloc().init()
        para.setAlignment_(AppKit.NSTextAlignmentCenter)
        attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(12.0),
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
            AppKit.NSParagraphStyleAttributeName: para,
        }
        Foundation.NSString.stringWithString_("✕ Đóng").drawInRect_withAttributes_(
            Foundation.NSMakeRect(0, 4, b.size.width, 18), attrs
        )


class WinSnapAssistController(Foundation.NSObject):
    def init(self):
        self = objc.super(WinSnapAssistController, self).init()
        if self is None:
            return None
        self.group = []
        self.picker_panel = None
        self.divider_panel = None
        self.picker_target_slot = None
        self.picker_target_rect = None
        self.anchor_ref = None
        self.last_drag_time = 0.0
        self.was_dragging = False
        self.suppress_until = 0.0
        self.raising_lock = False

        # Bắt sự kiện chuyển đổi ứng dụng để kéo cả cặp Split lên cùng lúc
        nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserverForName_object_queue_usingBlock_(
            AppKit.NSWorkspaceDidActivateApplicationNotification,
            None,
            None,
            self._on_app_activated,
        )

        # Bắt sự kiện click ra ngoài bảng chọn Snap Assist hoặc bấm phím Esc để đóng bảng chọn
        def _on_global_mouse_down(event):
            if self.picker_panel is not None:
                loc = AppKit.NSEvent.mouseLocation()
                pf = self.picker_panel.frame()
                if not Foundation.NSPointInRect(loc, pf):
                    self.close_picker()

        self._mouse_mon = (
            AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                AppKit.NSEventMaskLeftMouseDown | AppKit.NSEventMaskRightMouseDown,
                _on_global_mouse_down,
            )
        )

        # Timer 25Hz theo dõi kéo-thả cửa sổ, đồng bộ kích thước cặp Split & hiện Snap Assist
        self.timer = Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.04, self, "tick:", None, True
        )
        return self

    def _on_app_activated(self, note) -> None:
        if self.raising_lock or time.monotonic() < self.suppress_until:
            return
        if len(self.group) < 2:
            return
        user_info = note.userInfo()
        if not user_info:
            return
        act_app = user_info.get(AppKit.NSWorkspaceApplicationKey)
        if not act_app:
            return
        act_pid = int(act_app.processIdentifier())

        # Nếu có bảng chọn Snap Assist đang mở mà người dùng bấm ra ngoài thì đóng bảng
        if self.picker_panel is not None and act_pid != os.getpid():
            pass

        matched = [w for w in self.group if w.pid == act_pid]
        if not matched:
            self._update_divider_visibility()
            return

        # Kiểm tra xem cửa sổ vừa kích hoạt có còn nằm trong vị trí Split không
        primary = matched[0]
        cur_f = ax_get_frame(primary.ptr)
        if not cur_f or not self._is_still_in_split(primary, cur_f):
            self.clear_group()
            return

        # Đưa tất cả các cửa sổ đồng hành trong cặp Split nổi lên cùng lúc
        self._raise_partners_for(primary)
        self._update_divider_visibility()

    def _is_still_in_split(
        self, wref: WindowRef, cur_f: Tuple[float, float, float, float]
    ) -> bool:
        ex, ey, ew, eh = wref.expected_frame
        cx, cy, cw, ch = cur_f
        # Nếu người dùng đã kéo cửa sổ rời hẳn khỏi vị trí split (> 90px lệch tâm) thì hủy ghép cặp
        if abs(cx - ex) > 95 and abs((cx + cw) - (ex + ew)) > 95:
            return False
        if abs(cy - ey) > 95 and abs((cy + ch) - (ey + eh)) > 95:
            return False
        return True

    def _raise_partners_for(self, primary: WindowRef) -> None:
        if self.raising_lock or len(self.group) < 2:
            return
        # Kiểm tra thứ tự Z-order hiện tại trên màn hình xem partner đã nằm ngay dưới primary chưa
        wins_info = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        layer0_pids: List[int] = []
        if wins_info:
            for info in wins_info:
                if info.get("kCGWindowLayer", 0) == 0:
                    p = int(info.get("kCGWindowOwnerPID", 0))
                    if p not in layer0_pids:
                        layer0_pids.append(p)

        group_pids = {w.pid for w in self.group}
        top_pids = set(layer0_pids[: len(group_pids)])
        # Nếu toàn bộ các app trong cặp Split đã nằm trên cùng của màn hình và không bị thu nhỏ thì không cần nháy focus
        all_visible = True
        for w in self.group:
            mini = ax_get_obj(w.ptr, "AXMinimized")
            if mini and bool(mini):
                all_visible = False
                break
        if all_visible and group_pids.issubset(top_pids):
            return

        self.raising_lock = True
        self.suppress_until = time.monotonic() + 0.45
        try:
            running_by_pid = {
                int(a.processIdentifier()): a
                for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
            }
            for partner in self.group:
                if partner is primary:
                    continue
                p_app = running_by_pid.get(partner.pid)
                if p_app:
                    if p_app.isHidden():
                        p_app.unhide()
                    p_app.activateWithOptions_(
                        AppKit.NSApplicationActivateIgnoringOtherApps
                    )
                ax_unminimize_and_raise(partner.ptr)
                if partner.expected_frame:
                    ex, ey, ew, eh = partner.expected_frame
                    ax_set_frame(partner.ptr, ex, ey, ew, eh)

            # Trả lại tiêu điểm bàn phím cho cửa sổ người dùng vừa bấm
            prim_app = running_by_pid.get(primary.pid)
            if prim_app:
                prim_app.activateWithOptions_(
                    AppKit.NSApplicationActivateIgnoringOtherApps
                )
            ax_unminimize_and_raise(primary.ptr)
        finally:
            Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.35, self, "unlockRaise:", None, False
            )

    def unlockRaise_(self, timer) -> None:
        self.raising_lock = False

    def clear_group(self) -> None:
        self.group.clear()
        self.hide_divider()

    def close_picker(self) -> None:
        if self.picker_panel is not None:
            self.picker_panel.orderOut_(None)
            self.picker_panel = None
        self.picker_target_slot = None
        self.picker_target_rect = None

    def hide_divider(self) -> None:
        if self.divider_panel is not None:
            self.divider_panel.orderOut_(None)
            self.divider_panel = None

    def _update_divider_visibility(self) -> None:
        if len(self.group) < 2:
            self.hide_divider()
            return
        # Chỉ hiện thanh kéo giữa khi 2 cửa sổ của cặp Split đang hiển thị trên cùng
        wins_info = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        layer0_pids: List[int] = []
        if wins_info:
            for info in wins_info:
                if info.get("kCGWindowLayer", 0) == 0:
                    p = int(info.get("kCGWindowOwnerPID", 0))
                    if p not in layer0_pids:
                        layer0_pids.append(p)
        group_pids = {w.pid for w in self.group}
        if not group_pids.issubset(set(layer0_pids[: max(2, len(group_pids))])):
            self.hide_divider()
            return

        sx, sy, sw, sh = get_screen_usable_bounds()
        left_wins = [w for w in self.group if w.slot in ("left", "tl", "bl")]
        right_wins = [w for w in self.group if w.slot in ("right", "tr", "br")]
        top_wins = [w for w in self.group if w.slot == "top"]
        bot_wins = [w for w in self.group if w.slot == "bottom"]

        if left_wins and right_wins:
            lf = ax_get_frame(left_wins[0].ptr)
            if not lf:
                return
            seam_x = lf[0] + lf[2]
            cocoa_r = quartz_to_cocoa_rect(seam_x - 5.0, sy, 10.0, sh)
            self._ensure_divider_panel(cocoa_r, is_vert=True)
        elif top_wins and bot_wins:
            tf = ax_get_frame(top_wins[0].ptr)
            if not tf:
                return
            seam_y = tf[1] + tf[3]
            cocoa_r = quartz_to_cocoa_rect(sx, seam_y - 5.0, sw, 10.0)
            self._ensure_divider_panel(cocoa_r, is_vert=False)
        else:
            self.hide_divider()

    def _ensure_divider_panel(
        self, cocoa_rect: Foundation.NSRect, is_vert: bool
    ) -> None:
        if self.divider_panel is None:
            panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                cocoa_rect,
                AppKit.NSWindowStyleMaskBorderless
                | AppKit.NSWindowStyleMaskNonactivatingPanel,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            panel.setLevel_(AppKit.NSFloatingWindowLevel)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(AppKit.NSColor.clearColor())
            panel.setHasShadow_(False)
            panel.setIgnoresMouseEvents_(False)
            panel.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            view = SplitDividerView.alloc().initWithFrame_controller_vertical_(
                Foundation.NSMakeRect(
                    0, 0, cocoa_rect.size.width, cocoa_rect.size.height
                ),
                self,
                is_vert,
            )
            panel.setContentView_(view)
            panel.orderFrontRegardless()
            self.divider_panel = panel
        else:
            self.divider_panel.setFrame_display_(cocoa_rect, True)
            self.divider_panel.orderFrontRegardless()

    def on_divider_drag(self, qx: float, qy: float, is_vert: bool) -> None:
        sx, sy, sw, sh = get_screen_usable_bounds()
        self.suppress_until = time.monotonic() + 0.3
        if is_vert:
            seam_x = max(sx + 280.0, min(sx + sw - 280.0, round(qx)))
            for w in self.group:
                ex, ey, ew, eh = w.expected_frame
                if w.slot in ("left", "tl", "bl"):
                    nf = (sx, ey, seam_x - sx, eh)
                    w.expected_frame = nf
                    ax_set_frame(w.ptr, *nf, size_first=True)
                elif w.slot in ("right", "tr", "br"):
                    nf = (seam_x, ey, (sx + sw) - seam_x, eh)
                    w.expected_frame = nf
                    ax_set_frame(w.ptr, *nf, size_first=False)
            if self.divider_panel is not None:
                cocoa_r = quartz_to_cocoa_rect(seam_x - 5.0, sy, 10.0, sh)
                self.divider_panel.setFrame_display_(cocoa_r, True)
        else:
            seam_y = max(sy + 200.0, min(sy + sh - 200.0, round(qy)))
            for w in self.group:
                ex, ey, ew, eh = w.expected_frame
                if w.slot == "top":
                    nf = (ex, sy, ew, seam_y - sy)
                    w.expected_frame = nf
                    ax_set_frame(w.ptr, *nf, size_first=True)
                elif w.slot == "bottom":
                    nf = (ex, seam_y, ew, (sy + sh) - seam_y)
                    w.expected_frame = nf
                    ax_set_frame(w.ptr, *nf, size_first=False)
            if self.divider_panel is not None:
                cocoa_r = quartz_to_cocoa_rect(sx, seam_y - 5.0, sw, 10.0)
                self.divider_panel.setFrame_display_(cocoa_r, True)

    def on_divider_drag_end(self) -> None:
        self._update_divider_visibility()

    def _sync_live_edge_resize(self) -> None:
        """
        Nếu người dùng nắm trực tiếp cạnh giữa của cửa sổ bên Trái hoặc bên Phải để kéo to/nhỏ,
        tự động co giãn cửa sổ bên kia theo thời gian thực!
        """
        if len(self.group) < 2 or time.monotonic() < self.suppress_until:
            return
        sx, sy, sw, sh = get_screen_usable_bounds()

        for w in list(self.group):
            cur = ax_get_frame(w.ptr)
            if not cur:
                continue
            cx, cy, cw, ch = cur
            ex, ey, ew, eh = w.expected_frame

            # 1. Cửa sổ bên Trái được kéo cạnh phải (cx giữ nguyên ở mép trái, cw thay đổi)
            if (
                w.slot in ("left", "tl", "bl")
                and abs(cx - sx) < 20.0
                and abs(cw - ew) > 4.0
            ):
                seam_x = max(sx + 260.0, min(sx + sw - 260.0, cx + cw))
                w.expected_frame = (sx, ey, seam_x - sx, eh)
                for other in self.group:
                    if other is w:
                        continue
                    oex, oey, oew, oeh = other.expected_frame
                    if other.slot in ("left", "tl", "bl"):
                        nf = (sx, oey, seam_x - sx, oeh)
                        other.expected_frame = nf
                        ax_set_frame(other.ptr, *nf, size_first=True)
                    elif other.slot in ("right", "tr", "br"):
                        nf = (seam_x, oey, (sx + sw) - seam_x, oeh)
                        other.expected_frame = nf
                        ax_set_frame(other.ptr, *nf, size_first=False)
                self._update_divider_visibility()
                return

            # 2. Cửa sổ bên Phải được kéo cạnh trái (cạnh phải giữ nguyên ở mép phải, cx thay đổi)
            if (
                w.slot in ("right", "tr", "br")
                and abs((cx + cw) - (sx + sw)) < 25.0
                and abs(cx - ex) > 4.0
            ):
                seam_x = max(sx + 260.0, min(sx + sw - 260.0, cx))
                w.expected_frame = (seam_x, ey, (sx + sw) - seam_x, eh)
                for other in self.group:
                    if other is w:
                        continue
                    oex, oey, oew, oeh = other.expected_frame
                    if other.slot in ("left", "tl", "bl"):
                        nf = (sx, oey, seam_x - sx, oeh)
                        other.expected_frame = nf
                        ax_set_frame(other.ptr, *nf, size_first=True)
                    elif other.slot in ("right", "tr", "br"):
                        nf = (seam_x, oey, (sx + sw) - seam_x, oeh)
                        other.expected_frame = nf
                        ax_set_frame(other.ptr, *nf, size_first=False)
                self._update_divider_visibility()
                return

            # 3. Cửa sổ Nửa Trên hoặc Góc Trên được kéo cạnh dưới
            if (
                w.slot in ("top", "tl", "tr")
                and abs(cy - sy) < 20.0
                and abs(ch - eh) > 4.0
            ):
                seam_y = max(sy + 180.0, min(sy + sh - 180.0, cy + ch))
                w.expected_frame = (ex, sy, ew, seam_y - sy)
                partner_slot = (
                    "bottom"
                    if w.slot == "top"
                    else ("bl" if w.slot == "tl" else "br")
                )
                for other in self.group:
                    if other.slot == partner_slot:
                        oex, oey, oew, oeh = other.expected_frame
                        nf = (oex, seam_y, oew, (sy + sh) - seam_y)
                        other.expected_frame = nf
                        ax_set_frame(other.ptr, *nf, size_first=False)
                self._update_divider_visibility()
                return

            # 4. Cửa sổ Nửa Dưới hoặc Góc Dưới được kéo cạnh trên
            if (
                w.slot in ("bottom", "bl", "br")
                and abs((cy + ch) - (sy + sh)) < 25.0
                and abs(cy - ey) > 4.0
            ):
                seam_y = max(sy + 180.0, min(sy + sh - 180.0, cy))
                w.expected_frame = (ex, seam_y, ew, (sy + sh) - seam_y)
                partner_slot = (
                    "top"
                    if w.slot == "bottom"
                    else ("tl" if w.slot == "bl" else "tr")
                )
                for other in self.group:
                    if other.slot == partner_slot:
                        oex, oey, oew, oeh = other.expected_frame
                        nf = (oex, sy, oew, seam_y - sy)
                        other.expected_frame = nf
                        ax_set_frame(other.ptr, *nf, size_first=True)
                self._update_divider_visibility()
                return

    def tick_(self, timer) -> None:
        is_down = bool(
            Quartz.CGEventSourceButtonState(
                Quartz.kCGEventSourceStateCombinedSessionState, 0
            )
        )
        secs_drag = float(
            Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateCombinedSessionState,
                Quartz.kCGEventLeftMouseDragged,
            )
        )

        if is_down and secs_drag < 0.25:
            self.was_dragging = True
            if len(self.group) >= 2:
                self._sync_live_edge_resize()
            return

        if self.was_dragging and not is_down:
            self.was_dragging = False
            # Chờ 0.14s để Rectangle hoàn tất snap cửa sổ rồi kiểm tra
            Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.15, self, "checkAfterDrop:", None, False
            )

    def checkAfterDrop_(self, timer) -> None:
        if time.monotonic() < self.suppress_until:
            return
        # Trước tiên kiểm tra xem có phải vừa kéo cạnh giữa của cặp Split hiện có không
        if len(self.group) >= 2:
            self._sync_live_edge_resize()
            # Nếu một cửa sổ trong cặp bị kéo ra khỏi vị trí split (ví dụ kéo ra giữa màn hình hoặc phóng to)
            for w in list(self.group):
                f = ax_get_frame(w.ptr)
                if not f or not self._is_still_in_split(w, f):
                    self.group.remove(w)
            if len(self.group) < 2:
                self.hide_divider()

        # Tìm cửa sổ đang active vừa được kéo-thả
        front_win = self._get_frontmost_standard_window()
        if not front_win:
            return

        slot, snapped_rect, comp_slot, comp_rect = self._classify_snap_slot(
            front_win["frame"]
        )
        if not slot or not comp_slot or not comp_rect:
            return

        # Nếu cửa sổ này đã nằm trong group ở đúng slot đó và slot đối diện đã có cửa sổ rồi thì không bật lại bảng chọn
        if any(w.slot == comp_slot for w in self.group):
            return

        wref = WindowRef(
            pid=front_win["pid"],
            app_name=front_win["app_name"],
            bundle_id=front_win["bundle_id"],
            title=front_win["title"],
            ax_win_obj=front_win["ax_win"],
            icon=front_win["icon"],
            slot=slot,
            expected_frame=snapped_rect,
        )
        # Giữ lại các cửa sổ không trùng slot trong group (hỗ trợ ghép 3 hoặc 4 cửa sổ 1/4)
        self.group = [
            w
            for w in self.group
            if w.slot != slot and w.ptr != wref.ptr
        ]
        self.group.append(wref)
        self.anchor_ref = wref

        candidates = self._collect_other_window_candidates(
            exclude_ptrs={w.ptr for w in self.group}
        )
        if candidates:
            self.show_snap_assist_picker(comp_slot, comp_rect, candidates)

    def _get_frontmost_standard_window(self) -> Optional[dict]:
        wins_info = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        if not wins_info:
            return None
        own_pid = os.getpid()
        front_pid = 0
        for info in wins_info:
            if info.get("kCGWindowLayer", 0) != 0:
                continue
            p = int(info.get("kCGWindowOwnerPID", 0))
            b = info.get("kCGWindowBounds", {})
            if p != own_pid and float(b.get("Width", 0)) > 180:
                front_pid = p
                break
        if not front_pid:
            return None

        running_by_pid = {
            int(a.processIdentifier()): a
            for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
        }
        app = running_by_pid.get(front_pid)
        if not app or app.bundleIdentifier() == "com.custom.SmartRightDock":
            return None

        ax_app = app_services.AXUIElementCreateApplication(front_pid)
        ax_win = ax_get_obj(ax_app, "AXFocusedWindow")
        if ax_win is None:
            wins = ax_get_obj(ax_app, "AXWindows")
            if wins and len(wins) > 0:
                ax_win = wins[0]
        if ax_win is None:
            return None

        w_ptr = ax_win.__c_void_p__()
        frame = ax_get_frame(w_ptr)
        if not frame:
            return None
        title = str(ax_get_obj(w_ptr, "AXTitle") or app.localizedName() or "")
        return {
            "pid": front_pid,
            "app_name": str(app.localizedName() or "Ứng dụng"),
            "bundle_id": str(app.bundleIdentifier() or ""),
            "title": title,
            "ax_win": ax_win,
            "icon": app.icon(),
            "frame": frame,
        }

    def _classify_snap_slot(
        self, frame: Tuple[float, float, float, float]
    ) -> Tuple[
        Optional[str],
        Optional[Tuple[float, float, float, float]],
        Optional[str],
        Optional[Tuple[float, float, float, float]],
    ]:
        x, y, w, h = frame
        sx, sy, sw, sh = get_screen_usable_bounds()
        tol = 28.0

        near_left = abs(x - sx) <= tol
        near_right = abs((x + w) - (sx + sw)) <= tol
        near_top = abs(y - sy) <= tol
        near_bot = abs((y + h) - (sy + sh)) <= tol

        is_half_w = 0.32 * sw <= w <= 0.68 * sw
        is_full_w = w >= 0.88 * sw
        is_half_h = 0.32 * sh <= h <= 0.68 * sh
        is_full_h = h >= 0.88 * sh

        # 1. Nửa Trái -> cần chọn cửa sổ cho Nửa Phải
        if near_left and is_half_w and is_full_h:
            return (
                "left",
                (sx, sy, w, sh),
                "right",
                (sx + w, sy, sw - w, sh),
            )
        # 2. Nửa Phải -> cần chọn cửa sổ cho Nửa Trái
        if near_right and is_half_w and is_full_h:
            return (
                "right",
                (x, sy, w, sh),
                "left",
                (sx, sy, x - sx, sh),
            )
        # 3. Nửa Trên -> cần chọn cửa sổ cho Nửa Dưới
        if near_top and is_full_w and is_half_h:
            return (
                "top",
                (sx, sy, sw, h),
                "bottom",
                (sx, sy + h, sw, sh - h),
            )
        # 4. Nửa Dưới -> cần chọn cửa sổ cho Nửa Trên
        if near_bot and is_full_w and is_half_h:
            return (
                "bottom",
                (sx, y, sw, h),
                "top",
                (sx, sy, sw, y - sy),
            )
        # 5. Góc 1/4 Trên-Trái -> ưu tiên ghép Góc Dưới-Trái (hoặc Nửa Phải nếu Dưới-Trái đã có)
        if near_left and near_top and is_half_w and is_half_h:
            if any(g.slot == "bl" for g in self.group):
                return ("tl", (sx, sy, w, h), "right", (sx + w, sy, sw - w, sh))
            return ("tl", (sx, sy, w, h), "bl", (sx, sy + h, w, sh - h))
        # 6. Góc 1/4 Dưới-Trái
        if near_left and near_bot and is_half_w and is_half_h:
            if any(g.slot == "tl" for g in self.group):
                return ("bl", (sx, y, w, h), "right", (sx + w, sy, sw - w, sh))
            return ("bl", (sx, y, w, h), "tl", (sx, sy, w, y - sy))
        # 7. Góc 1/4 Trên-Phải
        if near_right and near_top and is_half_w and is_half_h:
            if any(g.slot == "br" for g in self.group):
                return ("tr", (x, sy, w, h), "left", (sx, sy, x - sx, sh))
            return ("tr", (x, sy, w, h), "br", (x, sy + h, w, sh - h))
        # 8. Góc 1/4 Dưới-Phải
        if near_right and near_bot and is_half_w and is_half_h:
            if any(g.slot == "tr" for g in self.group):
                return ("br", (x, y, w, h), "left", (sx, sy, x - sx, sh))
            return ("br", (x, y, w, h), "tr", (x, sy, w, y - sy))

        return (None, None, None, None)

    def _collect_other_window_candidates(self, exclude_ptrs: set) -> List[dict]:
        candidates: List[dict] = []
        own_pid = os.getpid()
        for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
            if app.activationPolicy() != AppKit.NSApplicationActivationPolicyRegular:
                continue
            pid = int(app.processIdentifier())
            if pid == own_pid:
                continue
            bid = str(app.bundleIdentifier() or "")
            if bid in ("com.custom.SmartRightDock", "com.knollsoft.Rectangle"):
                continue
            app_name = str(app.localizedName() or "Ứng dụng")
            icon = app.icon()
            ax_app = app_services.AXUIElementCreateApplication(pid)
            wins = ax_get_obj(ax_app, "AXWindows")
            if wins and len(wins) > 0:
                for w in wins:
                    w_ptr = w.__c_void_p__()
                    if w_ptr in exclude_ptrs:
                        continue
                    role = str(ax_get_obj(w_ptr, "AXSubrole") or "")
                    title = str(ax_get_obj(w_ptr, "AXTitle") or app_name)
                    if bid == "com.apple.finder" and not title:
                        continue
                    if role in ("AXStandardWindow", "") or len(wins) == 1:
                        candidates.append(
                            {
                                "pid": pid,
                                "app": app,
                                "app_name": app_name,
                                "bundle_id": bid,
                                "title": title or app_name,
                                "ax_win": w,
                                "icon": icon,
                            }
                        )
        return candidates

    def show_snap_assist_picker(
        self,
        target_slot: str,
        target_rect: Tuple[float, float, float, float],
        candidates: List[dict],
    ) -> None:
        self.close_picker()
        self.picker_target_slot = target_slot
        self.picker_target_rect = target_rect

        tx, ty, tw, th = target_rect
        pad = 24.0
        px, py, pw, ph = tx + pad, ty + pad, tw - pad * 2.0, th - pad * 2.0
        cocoa_rect = quartz_to_cocoa_rect(px, py, pw, ph)

        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            cocoa_rect,
            AppKit.NSWindowStyleMaskBorderless
            | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(AppKit.NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(True)

        vev = AppKit.NSVisualEffectView.alloc().initWithFrame_(
            Foundation.NSMakeRect(0, 0, pw, ph)
        )
        vev.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        vev.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        vev.setState_(AppKit.NSVisualEffectStateActive)
        vev.setWantsLayer_(True)
        vev.layer().setCornerRadius_(18.0)
        vev.layer().setMasksToBounds_(True)
        vev.layer().setBorderWidth_(1.2)
        vev.layer().setBorderColor_(
            AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.22).CGColor()
        )

        # Tiêu đề hướng dẫn kiểu Windows 11 Snap Assist
        hdr = AppKit.NSTextField.labelWithString_(
            "Chọn ứng dụng để ghép đôi Split (Snap Assist)"
        )
        hdr.setFont_(AppKit.NSFont.boldSystemFontOfSize_(15.0))
        hdr.setTextColor_(AppKit.NSColor.whiteColor())
        hdr.setFrame_(Foundation.NSMakeRect(22.0, ph - 46.0, pw - 120.0, 24.0))
        vev.addSubview_(hdr)

        close_btn = CloseBtnView.alloc().initWithFrame_callback_(
            Foundation.NSMakeRect(pw - 86.0, ph - 46.0, 66.0, 26.0),
            self.close_picker,
        )
        vev.addSubview_(close_btn)

        # Bố cục lưới thẻ ứng dụng
        n = min(len(candidates), 12)
        cols = 2 if pw < 620 else 3
        rows = max(1, int(math.ceil(n / float(cols))))
        grid_w = pw - 44.0
        grid_h = ph - 78.0
        gap = 14.0
        card_w = min(230.0, (grid_w - gap * (cols - 1)) / float(cols))
        card_h = min(118.0, (grid_h - gap * (rows - 1)) / float(rows))

        total_w = cols * card_w + (cols - 1) * gap
        total_h = rows * card_h + (rows - 1) * gap
        start_x = (pw - total_w) / 2.0
        start_y = (ph - 56.0 - total_h) / 2.0 + total_h - card_h

        for idx, cand in enumerate(candidates[:n]):
            r = idx // cols
            c = idx % cols
            cx = start_x + c * (card_w + gap)
            cy = start_y - r * (card_h + gap)
            card = SnapAssistCardView.alloc().initWithFrame_candidate_callback_(
                Foundation.NSMakeRect(cx, cy, card_w, card_h),
                cand,
                self._on_candidate_selected,
            )
            vev.addSubview_(card)

        panel.setContentView_(vev)
        panel.orderFrontRegardless()
        self.picker_panel = panel

    def _on_candidate_selected(self, cand: dict) -> None:
        slot = self.picker_target_slot
        rect = self.picker_target_rect
        self.close_picker()
        if not slot or not rect:
            return

        self.suppress_until = time.monotonic() + 0.5
        app = cand["app"]
        ax_win = cand["ax_win"]
        w_ptr = ax_win.__c_void_p__()

        if app.isHidden():
            app.unhide()
        app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
        ax_unminimize_and_raise(w_ptr)

        tx, ty, tw, th = rect
        ax_set_frame(w_ptr, tx, ty, tw, th)

        actual = ax_get_frame(w_ptr) or rect
        wref = WindowRef(
            pid=cand["pid"],
            app_name=cand["app_name"],
            bundle_id=cand["bundle_id"],
            title=cand["title"],
            ax_win_obj=ax_win,
            icon=cand["icon"],
            slot=slot,
            expected_frame=actual,
        )
        self.group = [
            w for w in self.group if w.slot != slot and w.ptr != wref.ptr
        ]
        self.group.append(wref)

        # Đưa tất cả cửa sổ trong nhóm Split nổi lên cùng nhau
        self._raise_partners_for(wref)
        self._update_divider_visibility()

        # Nếu vừa ghép đủ 2 góc 1/4 ở 1 bên mà nửa bên kia vẫn trống -> hỏi tiếp cho nửa bên kia!
        sx, sy, sw, sh = get_screen_usable_bounds()
        slots_present = {w.slot for w in self.group}
        if {"tl", "bl"}.issubset(slots_present) and not (
            {"right", "tr", "br"} & slots_present
        ):
            rem = self._collect_other_window_candidates(
                exclude_ptrs={w.ptr for w in self.group}
            )
            if rem:
                tl_w = next(w for w in self.group if w.slot == "tl")
                lw = tl_w.expected_frame[2]
                self.show_snap_assist_picker(
                    "right", (sx + lw, sy, sw - lw, sh), rem
                )
        elif {"tr", "br"}.issubset(slots_present) and not (
            {"left", "tl", "bl"} & slots_present
        ):
            rem = self._collect_other_window_candidates(
                exclude_ptrs={w.ptr for w in self.group}
            )
            if rem:
                tr_w = next(w for w in self.group if w.slot == "tr")
                rx = tr_w.expected_frame[0]
                self.show_snap_assist_picker("left", (sx, sy, rx - sx, sh), rem)


class DesktopSlotPreviewView(AppKit.NSView):
    def drawRect_(self, rect):
        b = self.bounds()
        p = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            Foundation.NSInsetRect(b, 1.5, 1.5), 10.0, 10.0
        )
        AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
            0.35, 0.68, 1.0, 0.22
        ).setFill()
        AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
            0.55, 0.82, 1.0, 0.78
        ).setStroke()
        p.setLineWidth_(1.8)
        p.fill()
        p.stroke()


class DesktopGridController(Foundation.NSObject):
    """
    Quản lý lưới icon Desktop kiểu Windows chạy trực tiếp trên Main RunLoop:
    - Hiển thị khung mờ dự đoán ô lưới (Ghost Preview Box) ngay khi đang kéo icon trên Desktop.
    - Ngay khoảnh khắc nhả chuột (LeftMouseUp), hút icon vào đúng tâm ô lưới (51 + c*68, 71 + r*84)
      và tự động hoán đổi nếu thả đè lên icon khác.
    """

    ORIGIN_X = 51
    STEP_X = 68
    MAX_COL = 20
    ORIGIN_Y = 71
    STEP_Y = 84
    MAX_ROW = 10

    def init(self):
        self = objc.super(DesktopGridController, self).init()
        if self is None:
            return None
        self.last_cells: Dict[str, Tuple[int, int]] = {}
        self.last_px: Dict[str, Tuple[int, int]] = {}
        self.preview_panel: Optional[AppKit.NSPanel] = None
        self.dragging_desktop = False
        self.drag_start_pt: Optional[Tuple[float, float]] = None

        self.read_script = Foundation.NSAppleScript.alloc().initWithSource_(
            'tell application "Finder"\n'
            "  try\n"
            "    if arrangement of icon view options of window of desktop is not not arranged then\n"
            "      set arrangement of icon view options of window of desktop to not arranged\n"
            "    end if\n"
            "    repeat with w in Finder windows\n"
            "      if current view of w is icon view and arrangement of icon view options of w is not arranged then\n"
            "        set arrangement of icon view options of w to snap to grid\n"
            "      end if\n"
            "    end repeat\n"
            "  end try\n"
            "  return {name, desktop position} of items of desktop\n"
            "end tell"
        )

        # Khởi tạo vị trí ban đầu
        self.snap_desktop_now()

        AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskLeftMouseDown, self._on_mouse_down
        )
        AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskLeftMouseDragged, self._on_mouse_dragged
        )
        AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            AppKit.NSEventMaskLeftMouseUp, self._on_mouse_up
        )
        return self

    def to_cell(self, x: float, y: float) -> Tuple[int, int]:
        c = max(
            0,
            min(
                self.MAX_COL,
                int(round((x - self.ORIGIN_X) / float(self.STEP_X))),
            ),
        )
        r = max(
            0,
            min(
                self.MAX_ROW,
                int(round((y - self.ORIGIN_Y) / float(self.STEP_Y))),
            ),
        )
        return (c, r)

    def to_px(self, c: int, r: int) -> Tuple[int, int]:
        return (self.ORIGIN_X + c * self.STEP_X, self.ORIGIN_Y + r * self.STEP_Y)

    def _is_clicking_desktop(self, qx: float, qy: float) -> bool:
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front or front.bundleIdentifier() != "com.apple.finder":
            return False
        # Kiểm tra xem tại (qx, qy) có cửa sổ Finder nào đang che không
        wins = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        if wins:
            for info in wins:
                if info.get("kCGWindowLayer", 0) != 0:
                    continue
                b = info.get("kCGWindowBounds", {})
                wx = float(b.get("X", 0))
                wy = float(b.get("Y", 0))
                ww = float(b.get("Width", 0))
                wh = float(b.get("Height", 0))
                if wx <= qx <= wx + ww and wy <= qy <= wy + wh:
                    return False
        return True

    def _mouse_quartz_pos(self) -> Tuple[float, float]:
        loc = AppKit.NSEvent.mouseLocation()
        scr = AppKit.NSScreen.mainScreen()
        total_h = float(scr.frame().size.height) if scr else 982.0
        return (float(loc.x), total_h - float(loc.y))

    def _on_mouse_down(self, event) -> None:
        qx, qy = self._mouse_quartz_pos()
        if self._is_clicking_desktop(qx, qy):
            self.drag_start_pt = (qx, qy)
            self.dragging_desktop = True
            self.hit_icon_on_down = any(
                abs(qx - ix) <= 42 and abs(qy - iy) <= 52
                for _, (ix, iy) in self.last_px.items()
            )
        else:
            self.dragging_desktop = False
            self.hit_icon_on_down = False
            self.drag_start_pt = None

    def _on_mouse_dragged(self, event) -> None:
        if not self.dragging_desktop or not self.drag_start_pt:
            return
        qx, qy = self._mouse_quartz_pos()
        if (
            abs(qx - self.drag_start_pt[0]) < 6.0
            and abs(qy - self.drag_start_pt[1]) < 6.0
        ):
            return
        if self.hit_icon_on_down:
            c, r = self.to_cell(qx, qy)
            gx, gy = self.to_px(c, r)
            self._show_preview_at(gx, gy)

    def _on_mouse_up(self, event) -> None:
        was_drag = self.dragging_desktop
        self.dragging_desktop = False
        self.drag_start_pt = None
        self._hide_preview()
        if was_drag:
            Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.03, self, "snapTimer:", None, False
            )

    def snapTimer_(self, timer) -> None:
        self.snap_desktop_now()

    def _show_preview_at(self, gx: int, gy: int) -> None:
        w, h = 62.0, 74.0
        cocoa_r = quartz_to_cocoa_rect(gx - w / 2.0, gy - h / 2.0 + 6.0, w, h)
        if self.preview_panel is None:
            panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                cocoa_r,
                AppKit.NSWindowStyleMaskBorderless
                | AppKit.NSWindowStyleMaskNonactivatingPanel,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            panel.setLevel_(AppKit.NSFloatingWindowLevel)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(AppKit.NSColor.clearColor())
            panel.setHasShadow_(False)
            panel.setIgnoresMouseEvents_(True)
            v = DesktopSlotPreviewView.alloc().initWithFrame_(
                Foundation.NSMakeRect(0, 0, w, h)
            )
            panel.setContentView_(v)
            panel.orderFrontRegardless()
            self.preview_panel = panel
        else:
            self.preview_panel.setFrame_display_(cocoa_r, True)
            self.preview_panel.orderFrontRegardless()

    def _hide_preview(self) -> None:
        if self.preview_panel is not None:
            self.preview_panel.orderOut_(None)

    def snap_desktop_now(self) -> None:
        res, err = self.read_script.executeAndReturnError_(None)
        if err or not res or res.numberOfItems() < 2:
            return
        names_desc = res.descriptorAtIndex_(1)
        pos_desc = res.descriptorAtIndex_(2)
        n = names_desc.numberOfItems()
        if n == 0:
            return

        current_items: List[Tuple[str, int, int]] = []
        for i in range(1, n + 1):
            nm = names_desc.descriptorAtIndex_(i).stringValue()
            pt = pos_desc.descriptorAtIndex_(i)
            if nm and pt and pt.numberOfItems() >= 2:
                x = int(pt.descriptorAtIndex_(1).int32Value())
                y = int(pt.descriptorAtIndex_(2).int32Value())
                current_items.append((nm, x, y))

        stationary: List[Tuple[str, int, int, Tuple[int, int]]] = []
        moved: List[Tuple[str, int, int]] = []
        occupied: Dict[Tuple[int, int], str] = {}

        for nm, x, y in current_items:
            c, r = self.to_cell(x, y)
            gx, gy = self.to_px(c, r)
            if (
                nm in self.last_px
                and self.last_px[nm] == (x, y)
                and (x, y) == (gx, gy)
                and (c, r) not in occupied
            ):
                stationary.append((nm, x, y, (c, r)))
                occupied[(c, r)] = nm
            else:
                moved.append((nm, x, y))

        if not moved:
            return

        new_cells: Dict[str, Tuple[int, int]] = {
            nm: cell for nm, _, _, cell in stationary
        }

        for nm, x, y in moved:
            tc, tr = self.to_cell(x, y)
            target = (tc, tr)
            prev_cell = self.last_cells.get(nm)
            if target not in occupied:
                occupied[target] = nm
                new_cells[nm] = target
            elif target in occupied and occupied[target] in self.last_cells:
                other_nm = occupied[target]
                if (
                    prev_cell is not None
                    and prev_cell not in occupied
                    and other_nm != nm
                ):
                    occupied[target] = nm
                    new_cells[nm] = target
                    occupied[prev_cell] = other_nm
                    new_cells[other_nm] = prev_cell
                else:
                    free_c = self._nearest_free(tc, tr, set(occupied.keys()), x, y)
                    occupied[free_c] = nm
                    new_cells[nm] = free_c
            else:
                free_c = self._nearest_free(tc, tr, set(occupied.keys()), x, y)
                occupied[free_c] = nm
                new_cells[nm] = free_c

        cmds: List[str] = []
        cur_map = {nm: (x, y) for nm, x, y in current_items}
        for nm, cell in new_cells.items():
            gx, gy = self.to_px(cell[0], cell[1])
            self.last_cells[nm] = cell
            self.last_px[nm] = (gx, gy)
            if cur_map.get(nm) != (gx, gy):
                safe_nm = nm.replace("\\", "\\\\").replace('"', '\\"')
                cmds.append(
                    f'set desktop position of item "{safe_nm}" of desktop to {{{gx}, {gy}}}'
                )

        if cmds:
            src = (
                'tell application "Finder"\n  try\n    '
                + "\n    ".join(cmds)
                + "\n  end try\nend tell"
            )
            ws = Foundation.NSAppleScript.alloc().initWithSource_(src)
            ws.executeAndReturnError_(None)

    def _nearest_free(
        self, target_c: int, target_r: int, occupied: set, px: int, py: int
    ) -> Tuple[int, int]:
        if (target_c, target_r) not in occupied:
            return (target_c, target_r)
        best_cell = (target_c, target_r)
        best_dist = 1e18
        for c in range(self.MAX_COL + 1):
            for r in range(self.MAX_ROW + 1):
                if (c, r) in occupied:
                    continue
                gx, gy = self.to_px(c, r)
                d = (gx - px) ** 2 + (gy - py) ** 2 + (
                    abs(c - target_c) + abs(r - target_r)
                ) * 400
                if d < best_dist:
                    best_dist = d
                    best_cell = (c, r)
        return best_cell


def main() -> None:
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    ctrl = WinSnapAssistController.alloc().init()
    _ = ctrl
    app.run()


if __name__ == "__main__":
    main()
