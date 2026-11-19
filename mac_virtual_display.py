"""
mac_virtual_display.py — Màn hình phụ #2 gốc macOS (CGVirtualDisplay) bật/tắt theo yêu cầu
cho app bàn phím ảo mac-web-keyboard.

Tính năng:
- Mặc định TẮT hoàn toàn (0 màn ảo, 0 ảnh hưởng MacBook khi chưa bật).
- Khi bật từ Điện thoại: tự biên dịch (1 lần, cache trong ~/.cache) helper Objective-C
  sử dụng API CGVirtualDisplay gốc của macOS (không cần root/kext/app thứ 3),
  tạo màn hình phụ #2 chuẩn tỉ lệ Điện thoại (1798x864 @ 2x HiDPI = 2248:1080),
  đặt gọn bên phải màn chính MacBook.
- Tự động đóng & kết nối lại phiên Windows App / Microsoft Remote Desktop đang chạy
  để Windows tự bung ra đúng 2 màn (Màn 1 = MacBook, Màn 2 = Điện thoại) không cần bấm tay.
- Khi tắt (hoặc thoát server.py): hủy màn ảo ngay lập tức, không bao giờ để lại màn ma.
"""

from __future__ import annotations

import atexit
import os
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

IS_MACOS = sys.platform == "darwin"

MAC_VDISP_HELPER_SRC = r"""
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <dispatch/dispatch.h>
#import <stdio.h>
#import <stdlib.h>
#import <unistd.h>
#import <signal.h>

@interface CGVirtualDisplayMode : NSObject
@property (readonly, nonatomic) CGFloat refreshRate;
@property (readonly, nonatomic) NSUInteger width;
@property (readonly, nonatomic) NSUInteger height;
- (instancetype)initWithWidth:(NSUInteger)width height:(NSUInteger)height refreshRate:(CGFloat)refreshRate;
@end

@interface CGVirtualDisplaySettings : NSObject
@property (retain, nonatomic) NSArray<CGVirtualDisplayMode *> *modes;
@property (nonatomic) unsigned int hiDPI;
- (instancetype)init;
@end

@interface CGVirtualDisplayDescriptor : NSObject
@property (retain, nonatomic) dispatch_queue_t queue;
@property (retain, nonatomic) NSString *name;
@property (nonatomic) unsigned int maxPixelsHigh;
@property (nonatomic) unsigned int maxPixelsWide;
@property (nonatomic) CGSize sizeInMillimeters;
@property (nonatomic) unsigned int serialNum;
@property (nonatomic) unsigned int productID;
@property (nonatomic) unsigned int vendorID;
@property (nonatomic) CGPoint redPrimary;
@property (nonatomic) CGPoint greenPrimary;
@property (nonatomic) CGPoint bluePrimary;
@property (nonatomic) CGPoint whitePoint;
@property (copy, nonatomic) void (^terminationHandler)(id, id);
- (instancetype)init;
@end

@interface CGVirtualDisplay : NSObject
@property (readonly, nonatomic) CGDirectDisplayID displayID;
- (instancetype)initWithDescriptor:(CGVirtualDisplayDescriptor *)descriptor;
- (BOOL)applySettings:(CGVirtualDisplaySettings *)settings;
@end

static volatile sig_atomic_t g_should_exit = 0;

static void handle_sig(int sig) {
    (void)sig;
    g_should_exit = 1;
}

static void position_display_right_of_main(CGDirectDisplayID vdispId) {
    CGDirectDisplayID mainId = CGMainDisplayID();
    if (vdispId == 0 || vdispId == mainId) return;
    CGRect mainBounds = CGDisplayBounds(mainId);
    int32_t targetX = (int32_t)(mainBounds.origin.x + mainBounds.size.width);
    int32_t targetY = (int32_t)(mainBounds.origin.y);

    CGDisplayConfigRef cfg = NULL;
    if (CGBeginDisplayConfiguration(&cfg) == kCGErrorSuccess && cfg != NULL) {
        CGConfigureDisplayOrigin(cfg, vdispId, targetX, targetY);
        CGCompleteDisplayConfiguration(cfg, kCGConfigureForSession);
    }
}

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        signal(SIGTERM, handle_sig);
        signal(SIGINT, handle_sig);
        signal(SIGHUP, handle_sig);

        NSUInteger logicalW = 1798;
        NSUInteger logicalH = 864;
        unsigned int wantHiDPI = 1;
        if (argc >= 3) {
            long w = atol(argv[1]);
            long h = atol(argv[2]);
            if (w >= 640 && w <= 4096) logicalW = (NSUInteger)w;
            if (h >= 360 && h <= 2400) logicalH = (NSUInteger)h;
        }
        if (argc >= 4) {
            wantHiDPI = (atoi(argv[3]) != 0) ? 1 : 0;
        }

        Class descCls = NSClassFromString(@"CGVirtualDisplayDescriptor");
        Class dispCls = NSClassFromString(@"CGVirtualDisplay");
        Class settCls = NSClassFromString(@"CGVirtualDisplaySettings");
        Class modeCls = NSClassFromString(@"CGVirtualDisplayMode");

        if (!descCls || !dispCls || !settCls || !modeCls) {
            fprintf(stdout, "ERR CGVirtualDisplay private API unavailable on this macOS\n");
            fflush(stdout);
            return 2;
        }

        NSUInteger maxW = wantHiDPI ? (logicalW * 2) : logicalW;
        NSUInteger maxH = wantHiDPI ? (logicalH * 2) : logicalH;

        CGVirtualDisplayDescriptor *desc = [[descCls alloc] init];
        dispatch_queue_t q = dispatch_queue_create("com.macwebkeyboard.vdisp", DISPATCH_QUEUE_SERIAL);
        desc.queue = q;
        desc.name = @"Phone Display";
        desc.maxPixelsWide = (unsigned int)maxW;
        desc.maxPixelsHigh = (unsigned int)maxH;
        // Kích thước vật lý tương đương màn OLED 6.7" tỉ lệ 2248:1080
        desc.sizeInMillimeters = CGSizeMake(154.0, 74.0);
        desc.vendorID = 0x1E6D;
        desc.productID = 0x5B21;
        desc.serialNum = 0x0002;
        desc.redPrimary = CGPointMake(0.6797, 0.3203);
        desc.greenPrimary = CGPointMake(0.2656, 0.6914);
        desc.bluePrimary = CGPointMake(0.1504, 0.0596);
        desc.whitePoint = CGPointMake(0.3127, 0.3290);
        desc.terminationHandler = ^(id disp, id err) {
            (void)disp; (void)err;
            g_should_exit = 1;
        };

        CGVirtualDisplay *vdisp = [[dispCls alloc] initWithDescriptor:desc];
        if (!vdisp) {
            fprintf(stdout, "ERR initWithDescriptor returned nil\n");
            fflush(stdout);
            return 3;
        }

        CGVirtualDisplayMode *mPrimary = [[modeCls alloc] initWithWidth:logicalW height:logicalH refreshRate:60.0];
        CGVirtualDisplayMode *mNative = [[modeCls alloc] initWithWidth:2248 height:1080 refreshRate:60.0];
        CGVirtualDisplaySettings *sett = [[settCls alloc] init];
        sett.hiDPI = wantHiDPI;
        sett.modes = (logicalW == 2248 && logicalH == 1080) ? @[mPrimary] : @[mPrimary, mNative];

        BOOL ok = [vdisp applySettings:sett];
        if (!ok && wantHiDPI) {
            // Fallback sang chế độ 1x 2248x1080 nếu macOS từ chối HiDPI
            wantHiDPI = 0;
            logicalW = 2248;
            logicalH = 1080;
            sett.hiDPI = 0;
            sett.modes = @[mNative];
            ok = [vdisp applySettings:sett];
        }
        if (!ok) {
            fprintf(stdout, "ERR applySettings failed\n");
            fflush(stdout);
            return 4;
        }

        CGDirectDisplayID did = vdisp.displayID;
        usleep(180000);
        position_display_right_of_main(did);
        usleep(120000);

        CGRect b = CGDisplayBounds(did);
        fprintf(stdout, "READY %u %d %d %u %.0f %.0f %.0f %.0f\n",
                (unsigned int)did,
                (int)logicalW,
                (int)logicalH,
                wantHiDPI,
                b.origin.x, b.origin.y, b.size.width, b.size.height);
        fflush(stdout);

        // Theo dõi stdin EOF để tự hủy màn ảo nếu server.py thoát đột ngột
        dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_LOW, 0), ^{
            char buf[64];
            while (read(STDIN_FILENO, buf, sizeof(buf)) > 0) {
                if (buf[0] == 'q' || buf[0] == 'Q') break;
            }
            g_should_exit = 1;
        });

        while (!g_should_exit) {
            @autoreleasepool {
                [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                         beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.2]];
            }
        }
        vdisp = nil;
    }
    return 0;
}
"""


class MacVirtualDisplayManager:
    """Quản lý vòng đời Màn hình phụ #2 trên macOS + tự refresh Windows App RDP."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._display_id: int = 0
        self._logical_w: int = 1798
        self._logical_h: int = 864
        self._hidpi: bool = True
        self._last_error: str = ""
        self._cache_dir = Path.home() / ".cache" / "mac-web-keyboard"
        self._bin_path = self._cache_dir / "mac_vdisp_helper_v1"
        self._src_path = self._cache_dir / "mac_vdisp_helper_v1.m"
        atexit.register(self.stop)

    def _ensure_helper_binary(self) -> Tuple[bool, str]:
        if not IS_MACOS:
            return False, "Chỉ hỗ trợ tạo màn hình phụ trên macOS."
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            need_build = True
            if self._bin_path.exists() and self._src_path.exists():
                try:
                    if self._src_path.read_text(encoding="utf-8") == MAC_VDISP_HELPER_SRC:
                        need_build = False
                except Exception:
                    need_build = True
            if not need_build:
                return True, ""

            clang = shutil.which("clang") or "/usr/bin/clang"
            if not clang or not os.path.exists(clang):
                return False, "Thiếu clang trên macOS (chạy xcode-select --install 1 lần)."

            self._src_path.write_text(MAC_VDISP_HELPER_SRC, encoding="utf-8")
            cmd = [
                clang,
                "-fobjc-arc",
                "-O2",
                "-framework",
                "Foundation",
                "-framework",
                "CoreGraphics",
                str(self._src_path),
                "-o",
                str(self._bin_path),
            ]
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=25,
            )
            if res.returncode != 0 or not self._bin_path.exists():
                err = (res.stderr or res.stdout or "clang build failed").strip()
                return False, f"Lỗi biên dịch helper màn ảo: {err[:220]}"
            os.chmod(self._bin_path, 0o755)
            return True, ""
        except Exception as exc:
            return False, f"Không khởi tạo được helper màn ảo: {exc}"

    def is_active(self) -> bool:
        with self._lock:
            if self._proc is None or self._display_id <= 0:
                return False
            if self._proc.poll() is not None:
                self._proc = None
                self._display_id = 0
                return False
            return True

    def get_display_id(self) -> int:
        with self._lock:
            return self._display_id if self.is_active() else 0

    def get_bounds(self, quartz: Any = None) -> Optional[Dict[str, float]]:
        did = self.get_display_id()
        if did <= 0 or not IS_MACOS:
            return None
        try:
            q = quartz
            if q is None:
                import Quartz as q  # type: ignore
            b = q.CGDisplayBounds(did)
            w = float(b.size.width)
            h = float(b.size.height)
            if w < 64 or h < 64:
                return None
            return {
                "display_id": did,
                "x": float(b.origin.x),
                "y": float(b.origin.y),
                "w": w,
                "h": h,
            }
        except Exception:
            return None

    def status(self, quartz: Any = None) -> Dict[str, Any]:
        active = self.is_active()
        bounds = self.get_bounds(quartz) if active else None
        return {
            "ok": True,
            "supported": IS_MACOS,
            "active": active and bounds is not None,
            "display_id": self._display_id if active else 0,
            "logical_w": self._logical_w,
            "logical_h": self._logical_h,
            "hidpi": self._hidpi,
            "bounds": bounds,
            "error": self._last_error,
        }

    def start(self, logical_w: int = 1798, logical_h: int = 864, hidpi: bool = True) -> Dict[str, Any]:
        with self._lock:
            if self.is_active():
                return self.status()

            ok_bin, err_msg = self._ensure_helper_binary()
            if not ok_bin:
                self._last_error = err_msg
                return {**self.status(), "ok": False, "error": err_msg}

            try:
                proc = subprocess.Popen(
                    [
                        str(self._bin_path),
                        str(int(logical_w)),
                        str(int(logical_h)),
                        "1" if hidpi else "0",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
            except Exception as exc:
                self._last_error = f"Không chạy được helper màn ảo: {exc}"
                return {**self.status(), "ok": False, "error": self._last_error}

            ready_line = ""
            deadline = time.monotonic() + 4.5
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                if proc.stdout is not None:
                    line = proc.stdout.readline()
                    if line:
                        ready_line = line.strip()
                        break
                time.sleep(0.05)

            if not ready_line.startswith("READY "):
                err_extra = ""
                try:
                    if proc.stderr is not None and proc.poll() is not None:
                        err_extra = proc.stderr.read().strip()
                except Exception:
                    pass
                try:
                    proc.terminate()
                except Exception:
                    pass
                self._last_error = ready_line or err_extra or "Không nhận được tín hiệu READY từ màn ảo."
                return {**self.status(), "ok": False, "error": self._last_error}

            parts = ready_line.split()
            try:
                did = int(parts[1])
                lw = int(parts[2]) if len(parts) > 2 else logical_w
                lh = int(parts[3]) if len(parts) > 3 else logical_h
                hd = (int(parts[4]) != 0) if len(parts) > 4 else hidpi
            except Exception:
                did, lw, lh, hd = 0, logical_w, logical_h, hidpi

            if did <= 0:
                try:
                    proc.terminate()
                except Exception:
                    pass
                self._last_error = f"DisplayID không hợp lệ: {ready_line}"
                return {**self.status(), "ok": False, "error": self._last_error}

            self._proc = proc
            self._display_id = did
            self._logical_w = lw
            self._logical_h = lh
            self._hidpi = hd
            self._last_error = ""
            return self.status()

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            proc = self._proc
            self._proc = None
            self._display_id = 0
            if proc is not None:
                try:
                    if proc.stdin is not None:
                        try:
                            proc.stdin.write("q\n")
                            proc.stdin.flush()
                            proc.stdin.close()
                        except Exception:
                            pass
                    proc.terminate()
                    try:
                        proc.wait(timeout=1.5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                except Exception:
                    pass
            self._last_error = ""
            return self.status()

    def capture_jpeg_packet(
        self,
        quartz: Any,
        foundation: Any,
        objc_mod: Any,
        quality: float = 0.82,
        max_px: int = 2248,
    ) -> Optional[bytes]:
        bounds = self.get_bounds(quartz)
        if bounds is None or quartz is None or foundation is None or objc_mod is None:
            return None
        did = int(bounds["display_id"])
        try:
            with objc_mod.autorelease_pool():
                cg_img = None
                try:
                    cg_img = quartz.CGDisplayCreateImage(did)
                except Exception:
                    cg_img = None
                if cg_img is None:
                    rect = quartz.CGRectMake(bounds["x"], bounds["y"], bounds["w"], bounds["h"])
                    opt_onscreen = getattr(quartz, "kCGWindowListOptionOnScreenOnly", 1)
                    cg_img = quartz.CGWindowListCreateImage(rect, opt_onscreen, 0, 0)
                if cg_img is None:
                    return None

                img_w = int(quartz.CGImageGetWidth(cg_img))
                img_h = int(quartz.CGImageGetHeight(cg_img))
                if img_w < 32 or img_h < 32:
                    return None

                mutable_data = foundation.NSMutableData.data()
                dest = quartz.CGImageDestinationCreateWithData(mutable_data, "public.jpeg", 1, None)
                if dest is None:
                    return None
                qual_key = getattr(
                    quartz,
                    "kCGImageDestinationLossyCompressionQuality",
                    "kCGImageDestinationLossyCompressionQuality",
                )
                max_px_key = getattr(
                    quartz,
                    "kCGImageDestinationImageMaxPixelSize",
                    "kCGImageDestinationImageMaxPixelSize",
                )
                enc_opts: Dict[str, Any] = {qual_key: float(quality)}
                out_w, out_h = img_w, img_h
                if max_px > 0 and max(img_w, img_h) > max_px:
                    enc_opts[max_px_key] = int(max_px)
                    if img_w >= img_h:
                        out_w = int(max_px)
                        out_h = max(1, int(round(img_h * float(max_px) / img_w)))
                    else:
                        out_h = int(max_px)
                        out_w = max(1, int(round(img_w * float(max_px) / img_h)))
                quartz.CGImageDestinationAddImage(dest, cg_img, enc_opts)
                if not quartz.CGImageDestinationFinalize(dest):
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

    def has_rdp_window_on_virtual_display(self, quartz: Any) -> bool:
        """Kiểm tra Windows App đã có cửa sổ phiên phủ lên màn hình phụ #2 chưa."""
        bounds = self.get_bounds(quartz)
        if bounds is None or quartz is None:
            return False
        vx, vy, vw, vh = bounds["x"], bounds["y"], bounds["w"], bounds["h"]
        try:
            opt = getattr(quartz, "kCGWindowListOptionOnScreenOnly", 1) | getattr(
                quartz, "kCGWindowListExcludeDesktopElements", 16
            )
            wins = quartz.CGWindowListCopyWindowInfo(opt, 0) or []
            for w in wins:
                owner = str(w.get("kCGWindowOwnerName", "") or "").lower()
                if "windows app" not in owner and "microsoft remote desktop" not in owner:
                    continue
                wb = w.get("kCGWindowBounds") or {}
                wx = float(wb.get("X", 0))
                wy = float(wb.get("Y", 0))
                ww = float(wb.get("Width", 0))
                wh = float(wb.get("Height", 0))
                if ww < 300 or wh < 200:
                    continue
                cx = wx + ww * 0.5
                cy = wy + wh * 0.5
                if vx <= cx <= (vx + vw) and vy <= cy <= (vy + vh):
                    return True
        except Exception:
            pass
        return False

    def auto_refresh_windows_app_session(
        self,
        was_rdp_info: Optional[Dict[str, Any]],
        find_rdp_fn: Callable[[], Optional[Dict[str, Any]]],
        quartz: Any = None,
        expect_second_monitor: bool = True,
    ) -> Dict[str, Any]:
        """
        Tự động đóng & kết nối lại phiên Windows App / Microsoft Remote Desktop
        nếu người dùng đang remote PC sẵn trên MacBook, để RDP tự nhận 2 màn (hoặc quay lại 1 màn)
        mà không phải tự đóng mở tay.
        """
        if not IS_MACOS or not was_rdp_info:
            return {"rdp_was_open": False, "rdp_reconnected": False}

        # Nếu vừa bật màn phụ và Windows App tự bung sang màn #2 luôn thì không cần reconnect!
        if expect_second_monitor:
            time.sleep(0.55)
            if self.has_rdp_window_on_virtual_display(quartz):
                return {"rdp_was_open": True, "rdp_reconnected": True, "dynamic": True}

        saved_title = str(was_rdp_info.get("title", "") or "").strip()
        safe_title = saved_title.replace("\\", "\\\\").replace('"', '\\"')

        # Bước 1: Đóng cửa sổ phiên đang mở (giữ nguyên cửa sổ chính Devices/PCs của Windows App)
        close_script = r'''
        tell application "System Events"
            repeat with procName in {"Windows App", "Microsoft Remote Desktop"}
                if exists process procName then
                    tell process procName
                        repeat with w in (every window)
                            try
                                set wName to (name of w as string)
                                if wName is not in {"PCs", "Workspaces", "Devices", "Apps", "Microsoft Remote Desktop", "Windows App"} then
                                    try
                                        if (value of attribute "AXFullScreen" of w) is true then
                                            set value of attribute "AXFullScreen" of w to false
                                            delay 0.38
                                        end if
                                    end try
                                    perform action "AXPress" of (first button of w whose subrole is "AXCloseButton")
                                end if
                            end try
                        end repeat
                    end tell
                end if
            end repeat
        end tell
        '''
        try:
            subprocess.run(
                ["osascript", "-e", close_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.5,
            )
        except Exception:
            pass

        # Chờ Windows App đóng phiên cũ & ổn định danh sách màn hình macOS
        time.sleep(0.85)

        # Bước 2: Tự kích hoạt lại kết nối PC đã lưu trong cửa sổ chính Windows App
        # Ưu tiên: bấm menu Connections -> Connect, hoặc nhấn double-click / Enter vào thẻ PC khớp tên
        reconnect_script = f'''
        set targetTitle to "{safe_title}"
        tell application "System Events"
            repeat with procName in {{"Windows App", "Microsoft Remote Desktop"}}
                if exists process procName then
                    tell process procName
                        set frontmost to true
                        delay 0.25
                        -- Đảm bảo cửa sổ chính Devices/PCs hiện lên
                        if (count of windows) is 0 then
                            try
                                keystroke "1" using command down
                                delay 0.35
                            end try
                        end if
                        -- Thử bấm qua Menu Bar (Connections -> Connect hoặc File -> Connect)
                        set didConnect to false
                        try
                            if exists menu "Connections" of menu bar 1 then
                                tell menu "Connections" of menu bar 1
                                    if exists menu item "Connect" then
                                        if enabled of menu item "Connect" is true then
                                            click menu item "Connect"
                                            set didConnect to true
                                        end if
                                    end if
                                end tell
                            end if
                        end try
                        if not didConnect then
                            -- Tìm thẻ PC trong cửa sổ chính và kích hoạt bằng Enter / AXConfirm / AXPress
                            try
                                set mainWin to window 1
                                set allElems to entire contents of mainWin
                                repeat with el in allElems
                                    try
                                        set elRole to (role of el as string)
                                        if elRole is in {{"AXGroup", "AXCell", "AXRow", "AXButton", "AXStaticText"}} then
                                            set elDesc to ""
                                            try
                                                set elDesc to (name of el as string)
                                            end try
                                            if elDesc is "" then
                                                try
                                                    set elDesc to (value of el as string)
                                                end try
                                            end if
                                            if elDesc is "" then
                                                try
                                                    set elDesc to (description of el as string)
                                                end try
                                            end if
                                            if (targetTitle is not "" and elDesc contains targetTitle) or (elDesc contains "192.168.") or (elDesc contains "DESKTOP-") then
                                                try
                                                    set p to position of el
                                                    set sz to size of el
                                                    set cx to ((item 1 of p) + ((item 1 of sz) / 2))
                                                    set cy to ((item 2 of p) + ((item 2 of sz) / 2))
                                                    if cx > 0 and cy > 0 then
                                                        return "CLICK " & (cx as integer) & " " & (cy as integer)
                                                    end if
                                                end try
                                                try
                                                    set focused of el to true
                                                end try
                                                try
                                                    perform action "AXPress" of el
                                                    delay 0.12
                                                    perform action "AXPress" of el
                                                    set didConnect to true
                                                    exit repeat
                                                end try
                                            end if
                                        end if
                                    end try
                                end repeat
                            end try
                        end if
                        if not didConnect then
                            -- Fallback cuối: nhấn Return trong cửa sổ Devices/PCs (nếu thẻ PC đang được chọn sẵn)
                            try
                                key code 36
                                delay 0.12
                                key code 36
                            end try
                        end if
                    end tell
                    exit repeat
                end if
            end repeat
        end tell
        '''
        try:
            proc_out = subprocess.run(
                ["osascript", "-e", reconnect_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=4.5,
            )
            out_txt = (proc_out.stdout or "").strip()
            if out_txt.startswith("CLICK ") and quartz is not None:
                cparts = out_txt.split()
                if len(cparts) >= 3:
                    cx, cy = float(cparts[1]), float(cparts[2])
                    quartz.CGWarpMouseCursorPosition((cx, cy))
                    time.sleep(0.05)
                    for click_idx in (1, 2):
                        ev_dn = quartz.CGEventCreateMouseEvent(
                            None, quartz.kCGEventLeftMouseDown, (cx, cy), quartz.kCGMouseButtonLeft
                        )
                        quartz.CGEventSetIntegerValueField(ev_dn, quartz.kCGMouseEventClickState, click_idx)
                        quartz.CGEventPost(quartz.kCGHIDEventTap, ev_dn)
                        ev_up = quartz.CGEventCreateMouseEvent(
                            None, quartz.kCGEventLeftMouseUp, (cx, cy), quartz.kCGMouseButtonLeft
                        )
                        quartz.CGEventSetIntegerValueField(ev_up, quartz.kCGMouseEventClickState, click_idx)
                        quartz.CGEventPost(quartz.kCGHIDEventTap, ev_up)
                        time.sleep(0.04)
        except Exception:
            pass

        # Chờ tối đa 3.2s xác nhận cửa sổ RDP mới đã mở lại
        reconnected = False
        deadline = time.monotonic() + 3.2
        while time.monotonic() < deadline:
            time.sleep(0.3)
            if find_rdp_fn() is not None:
                reconnected = True
                break

        return {
            "rdp_was_open": True,
            "rdp_reconnected": reconnected,
            "on_virtual_display": self.has_rdp_window_on_virtual_display(quartz)
            if expect_second_monitor
            else False,
        }
