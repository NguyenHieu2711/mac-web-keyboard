"""
mac_virtual_display.py — Màn hình phụ #2 gốc macOS (CGVirtualDisplay) + Per-Monitor Dock
cho app bàn phím ảo mac-web-keyboard.

Tính năng:
- Mặc định TẮT hoàn toàn (0 màn ảo, 0 ảnh hưởng MacBook khi chưa bật).
- Khi bật từ Điện thoại: tự biên dịch (1 lần, cache trong ~/.cache) helper Objective-C
  sử dụng API CGVirtualDisplay gốc của macOS (không cần root/kext/app thứ 3),
  tạo màn hình phụ #2 chuẩn tỉ lệ Điện thoại (1798x864 @ 2x HiDPI = 2248:1080),
  đặt gọn bên TRÁI màn chính MacBook.
- Dock riêng cho Màn hình phụ #2 (cơ chế giống Windows 11 2 màn hình):
  + Màn chính MacBook giữ nguyên Dock macOS hiển thị đầy đủ app.
  + Màn phụ #2 hiện thanh Dock mờ kính riêng, CHỈ hiển thị các ứng dụng đang mở trên màn phụ #2;
    click icon để đưa cửa sổ lên/thu nhỏ, tự ẩn khi có ứng dụng toàn màn hình (như Windows App).
- Hoạt động độc lập 100% với Windows App / Remote PC (không đóng/kích cửa sổ app khác).
- Khi tắt (hoặc thoát server.py): hủy màn ảo & Dock phụ ngay lập tức, không bao giờ để lại màn ma.
"""

from __future__ import annotations

import atexit
import ctypes
import os
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

IS_MACOS = sys.platform == "darwin"

MAC_VDISP_HELPER_SRC = r"""
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#import <ApplicationServices/ApplicationServices.h>
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

static void select_best_hidpi_mode(CGDirectDisplayID vdispId, NSUInteger logicalW, NSUInteger logicalH, unsigned int wantHiDPI) {
    NSDictionary *opts = @{ (__bridge id)kCGDisplayShowDuplicateLowResolutionModes: @YES };
    CFArrayRef modes = CGDisplayCopyAllDisplayModes(vdispId, (__bridge CFDictionaryRef)opts);
    if (!modes) return;
    CGDisplayModeRef best = NULL;
    CFIndex cnt = CFArrayGetCount(modes);
    for (CFIndex i = 0; i < cnt; i++) {
        CGDisplayModeRef m = (CGDisplayModeRef)CFArrayGetValueAtIndex(modes, i);
        size_t w = CGDisplayModeGetWidth(m);
        size_t h = CGDisplayModeGetHeight(m);
        size_t pw = CGDisplayModeGetPixelWidth(m);
        size_t ph = CGDisplayModeGetPixelHeight(m);
        if (w == logicalW && h == logicalH) {
            if (wantHiDPI && pw == logicalW * 2 && ph == logicalH * 2) {
                best = m;
                break;
            }
            if (!best) best = m;
        }
    }
    if (best) {
        CGDisplaySetDisplayMode(vdispId, best, NULL);
    }
    CFRelease(modes);
}

static void position_display_left_of_main(CGDirectDisplayID vdispId) {
    CGDirectDisplayID mainId = CGMainDisplayID();
    if (vdispId == 0 || vdispId == mainId) return;
    CGRect mainBounds = CGDisplayBounds(mainId);
    CGRect vBounds = CGDisplayBounds(vdispId);
    if (vBounds.size.width < 64 || vBounds.size.height < 64) return;
    // Đặt màn hình phụ ở BÊN TRÁI màn chính MacBook (di chuột sang trái để sang Điện thoại), căn giữa chiều dọc
    int32_t targetX = (int32_t)(mainBounds.origin.x - vBounds.size.width);
    int32_t targetY = (int32_t)(mainBounds.origin.y + (mainBounds.size.height - vBounds.size.height) * 0.5);

    CGDisplayConfigRef cfg = NULL;
    if (CGBeginDisplayConfiguration(&cfg) == kCGErrorSuccess && cfg != NULL) {
        CGConfigureDisplayOrigin(cfg, vdispId, targetX, targetY);
        CGCompleteDisplayConfiguration(cfg, kCGConfigureForSession);
    }
}

static NSImage *make_pill_mask(CGFloat radius) {
    CGFloat dim = radius * 2.0 + 1.0;
    NSImage *img = [NSImage imageWithSize:NSMakeSize(dim, dim)
                                  flipped:NO
                           drawingHandler:^BOOL(NSRect dstRect) {
        [[NSColor blackColor] setFill];
        NSBezierPath *path = [NSBezierPath bezierPathWithRoundedRect:dstRect
                                                             xRadius:radius
                                                             yRadius:radius];
        [path fill];
        return YES;
    }];
    img.capInsets = NSEdgeInsetsMake(radius, radius, radius, radius);
    img.resizingMode = NSImageResizingModeStretch;
    return img;
}

static BOOL dock_is_dark_mode(void) {
    NSAppearance *app = [NSApp effectiveAppearance];
    if (!app) return NO;
    NSAppearanceName best = [app bestMatchFromAppearancesWithNames:@[NSAppearanceNameAqua, NSAppearanceNameDarkAqua]];
    return [best isEqualToString:NSAppearanceNameDarkAqua];
}

static BOOL ax_raise_app_on_vdisp(pid_t pid, CGRect vb) {
    if (pid <= 0) return YES;
    AXUIElementRef appAX = AXUIElementCreateApplication(pid);
    if (!appAX) return NO;
    AXError fErr = AXUIElementSetAttributeValue(appAX, kAXFrontmostAttribute, kCFBooleanTrue);
    if (fErr == kAXErrorAPIDisabled) {
        CFRelease(appAX);
        return NO;
    }
    CFTypeRef winsRef = NULL;
    if (AXUIElementCopyAttributeValue(appAX, kAXWindowsAttribute, &winsRef) == kAXErrorSuccess && winsRef) {
        CFIndex cnt = CFArrayGetCount((CFArrayRef)winsRef);
        NSMutableArray *vdispWins = [NSMutableArray array];
        NSMutableArray *minFallback = [NSMutableArray array];
        for (CFIndex i = 0; i < cnt; i++) {
            AXUIElementRef wAX = (AXUIElementRef)CFArrayGetValueAtIndex((CFArrayRef)winsRef, i);
            if (!wAX) continue;
            BOOL inVdisp = NO;
            CFTypeRef posRef = NULL, szRef = NULL;
            if (AXUIElementCopyAttributeValue(wAX, kAXPositionAttribute, &posRef) == kAXErrorSuccess && posRef &&
                AXUIElementCopyAttributeValue(wAX, kAXSizeAttribute, &szRef) == kAXErrorSuccess && szRef) {
                CGPoint pt = CGPointZero;
                CGSize sz = CGSizeZero;
                if (AXValueGetValue((AXValueRef)posRef, kAXValueCGPointType, &pt) &&
                    AXValueGetValue((AXValueRef)szRef, kAXValueCGSizeType, &sz) &&
                    sz.width >= 120.0 && sz.height >= 80.0) {
                    CGFloat cx = pt.x + sz.width * 0.5;
                    CGFloat cy = pt.y + sz.height * 0.5;
                    inVdisp = (cx >= vb.origin.x && cx < (vb.origin.x + vb.size.width) &&
                               cy >= vb.origin.y && cy < (vb.origin.y + vb.size.height));
                }
            }
            if (posRef) CFRelease(posRef);
            if (szRef) CFRelease(szRef);

            BOOL isMin = NO;
            CFTypeRef minRef = NULL;
            if (AXUIElementCopyAttributeValue(wAX, kAXMinimizedAttribute, &minRef) == kAXErrorSuccess && minRef) {
                isMin = (CFGetTypeID(minRef) == CFBooleanGetTypeID() && CFBooleanGetValue((CFBooleanRef)minRef));
                CFRelease(minRef);
            }
            if (inVdisp) {
                [vdispWins addObject:(__bridge id)wAX];
            } else if (isMin) {
                [minFallback addObject:(__bridge id)wAX];
            }
        }
        NSArray *targets = (vdispWins.count > 0) ? vdispWins : minFallback;
        for (id wObj in targets) {
            AXUIElementRef wAX = (__bridge AXUIElementRef)wObj;
            AXUIElementSetAttributeValue(wAX, kAXMinimizedAttribute, kCFBooleanFalse);
            AXUIElementSetAttributeValue(wAX, kAXMainAttribute, kCFBooleanTrue);
            AXUIElementSetAttributeValue(wAX, kAXFocusedAttribute, kCFBooleanTrue);
            AXUIElementPerformAction(wAX, kAXRaiseAction);
        }
        CFRelease(winsRef);
    }
    CFRelease(appAX);
    return YES;
}

static BOOL ax_minimize_app_on_vdisp(pid_t pid, CGRect vb) {
    if (pid <= 0) return YES;
    AXUIElementRef appAX = AXUIElementCreateApplication(pid);
    if (!appAX) return NO;
    CFTypeRef winsRef = NULL;
    AXError err = AXUIElementCopyAttributeValue(appAX, kAXWindowsAttribute, &winsRef);
    if (err == kAXErrorAPIDisabled) {
        CFRelease(appAX);
        return NO;
    }
    if (err == kAXErrorSuccess && winsRef) {
        CFIndex cnt = CFArrayGetCount((CFArrayRef)winsRef);
        for (CFIndex i = 0; i < cnt; i++) {
            AXUIElementRef wAX = (AXUIElementRef)CFArrayGetValueAtIndex((CFArrayRef)winsRef, i);
            if (!wAX) continue;
            BOOL inVdisp = NO;
            CFTypeRef posRef = NULL, szRef = NULL;
            if (AXUIElementCopyAttributeValue(wAX, kAXPositionAttribute, &posRef) == kAXErrorSuccess && posRef &&
                AXUIElementCopyAttributeValue(wAX, kAXSizeAttribute, &szRef) == kAXErrorSuccess && szRef) {
                CGPoint pt = CGPointZero;
                CGSize sz = CGSizeZero;
                if (AXValueGetValue((AXValueRef)posRef, kAXValueCGPointType, &pt) &&
                    AXValueGetValue((AXValueRef)szRef, kAXValueCGSizeType, &sz) &&
                    sz.width >= 120.0 && sz.height >= 80.0) {
                    CGFloat cx = pt.x + sz.width * 0.5;
                    CGFloat cy = pt.y + sz.height * 0.5;
                    inVdisp = (cx >= vb.origin.x && cx < (vb.origin.x + vb.size.width) &&
                               cy >= vb.origin.y && cy < (vb.origin.y + vb.size.height));
                }
            }
            if (posRef) CFRelease(posRef);
            if (szRef) CFRelease(szRef);
            if (!inVdisp) continue;

            BOOL isFs = NO;
            CFTypeRef fsRef = NULL;
            if (AXUIElementCopyAttributeValue(wAX, CFSTR("AXFullScreen"), &fsRef) == kAXErrorSuccess && fsRef) {
                isFs = (CFGetTypeID(fsRef) == CFBooleanGetTypeID() && CFBooleanGetValue((CFBooleanRef)fsRef));
                CFRelease(fsRef);
            }
            if (!isFs) {
                AXUIElementSetAttributeValue(wAX, kAXMinimizedAttribute, kCFBooleanTrue);
            }
        }
        CFRelease(winsRef);
    }
    CFRelease(appAX);
    return YES;
}

@interface DockPanel : NSPanel
@end
@implementation DockPanel
- (BOOL)canBecomeKeyWindow { return NO; }
- (BOOL)canBecomeMainWindow { return NO; }
@end

@interface DockGlassView : NSVisualEffectView
@end
@implementation DockGlassView
- (BOOL)acceptsFirstMouse:(NSEvent *)event { (void)event; return YES; }
@end

@interface DockItemView : NSView
@property (nonatomic) pid_t appPid;
@property (nonatomic, strong) NSImageView *iconView;
@property (nonatomic, strong) NSView *dotView;
@property (nonatomic, copy) void (^onClick)(pid_t pid);
@end
@implementation DockItemView
- (BOOL)acceptsFirstMouse:(NSEvent *)event { (void)event; return YES; }
- (void)mouseDown:(NSEvent *)event {
    (void)event;
    if (self.iconView) self.iconView.alphaValue = 0.58;
    if (self.onClick && self.appPid > 0) {
        self.onClick(self.appPid);
    }
}
@end

@interface SecondaryDockController : NSObject
@property (nonatomic) CGDirectDisplayID vdispId;
@property (nonatomic) pid_t selfPid;
@property (nonatomic, strong) DockPanel *panel;
@property (nonatomic, strong) DockGlassView *bgView;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *knownWins;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSNumber *> *hiddenPids;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, DockItemView *> *itemViews;
@property (nonatomic, strong) NSMutableArray<NSNumber *> *appOrder;
@property (nonatomic, strong) NSMutableDictionary<NSNumber *, NSDictionary *> *appState;
@property (nonatomic, copy) NSString *lastLayoutSig;
@property (nonatomic) CFAbsoluteTime lastRdpSyncAt;
- (instancetype)initWithDisplayID:(CGDirectDisplayID)did;
- (void)refresh;
- (void)syncFullscreenRdpOnVdispIfNeeded:(NSRunningApplication *)activatedApp;
- (void)shutdown;
@end

@implementation SecondaryDockController

- (instancetype)initWithDisplayID:(CGDirectDisplayID)did {
    self = [super init];
    if (!self) return nil;
    _vdispId = did;
    _selfPid = getpid();
    _knownWins = [NSMutableDictionary dictionary];
    _hiddenPids = [NSMutableDictionary dictionary];
    _itemViews = [NSMutableDictionary dictionary];
    _appOrder = [NSMutableArray array];
    _appState = [NSMutableDictionary dictionary];
    _lastLayoutSig = @"";

    NSRect initRect = NSMakeRect(0, 0, 42, 120);
    _panel = [[DockPanel alloc] initWithContentRect:initRect
                                          styleMask:(NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel)
                                            backing:NSBackingStoreBuffered
                                              defer:NO];
    // Ngang tầng Dock gốc / SmartRightDock (layer 20) + FullScreenAuxiliary để LUÔN nổi trên cả app Full Screen
    _panel.level = (NSWindowLevel)CGWindowLevelForKey(kCGDockWindowLevelKey);
    _panel.collectionBehavior = (NSWindowCollectionBehaviorCanJoinAllSpaces |
                                 NSWindowCollectionBehaviorFullScreenAuxiliary |
                                 NSWindowCollectionBehaviorStationary |
                                 NSWindowCollectionBehaviorIgnoresCycle);
    _panel.opaque = NO;
    _panel.backgroundColor = [NSColor clearColor];
    _panel.hasShadow = NO;
    _panel.ignoresMouseEvents = NO;
    _panel.hidesOnDeactivate = NO;
    _panel.becomesKeyOnlyIfNeeded = YES;
    _panel.releasedWhenClosed = NO;

    _bgView = [[DockGlassView alloc] initWithFrame:initRect];
    _bgView.material = NSVisualEffectMaterialPopover;
    _bgView.blendingMode = NSVisualEffectBlendingModeBehindWindow;
    _bgView.state = NSVisualEffectStateActive;
    _bgView.autoresizingMask = (NSViewWidthSizable | NSViewHeightSizable);
    _bgView.maskImage = make_pill_mask(13.0);
    _bgView.wantsLayer = YES;
    _bgView.layer.cornerRadius = 13.0;
    _bgView.layer.masksToBounds = YES;
    _bgView.layer.borderWidth = 0.75;
    _bgView.layer.borderColor = [[NSColor colorWithWhite:1.0 alpha:0.42] CGColor];
    _panel.contentView = _bgView;
    return self;
}

- (NSScreen *)targetScreen {
    for (NSScreen *scr in [NSScreen screens]) {
        NSNumber *num = scr.deviceDescription[@"NSScreenNumber"];
        if (num && (CGDirectDisplayID)[num unsignedIntValue] == self.vdispId) {
            return scr;
        }
    }
    return nil;
}

- (void)updateItemVisuals:(BOOL)isDark {
    for (NSNumber *pidNum in self.appOrder) {
        DockItemView *iv = self.itemViews[pidNum];
        NSDictionary *st = self.appState[pidNum];
        if (!iv || !st) continue;
        BOOL isVis = [st[@"visible"] boolValue];
        BOOL isTop = [st[@"top"] boolValue];
        iv.iconView.alphaValue = isVis ? 1.0 : 0.72;
        if (isDark) {
            CGFloat da = isVis ? (isTop ? 0.95 : 0.45) : 0.20;
            iv.dotView.layer.backgroundColor = [[NSColor colorWithWhite:1.0 alpha:da] CGColor];
        } else {
            CGFloat da = isVis ? (isTop ? 0.78 : 0.36) : 0.16;
            iv.dotView.layer.backgroundColor = [[NSColor colorWithWhite:0.12 alpha:da] CGColor];
        }
    }
}

- (void)handleClickForPid:(pid_t)pid {
    if (pid <= 0) return;
    NSDictionary *info = self.appState[@(pid)];
    BOOL isVis = info ? [info[@"visible"] boolValue] : NO;
    BOOL isTop = info ? [info[@"top"] boolValue] : NO;
    BOOL hasMain = info ? [info[@"hasMain"] boolValue] : NO;
    BOOL isFs = info ? [info[@"isFs"] boolValue] : NO;
    unsigned int winId = info ? [info[@"winId"] unsignedIntValue] : 0;
    NSRunningApplication *rapp = [NSRunningApplication runningApplicationWithProcessIdentifier:pid];
    CGRect vb = CGDisplayBounds(self.vdispId);

    // Logic tối giản 100% chuẩn taskbar 2 màn hình Windows:
    // - Đang ẩn hoặc bị cửa sổ khác đè -> MỞ LÊN TRÊN CÙNG tức thì (1ms native ObjC)
    // - Đang mở nằm trên cùng -> THU GỌN TỨC THÌ xuống khay Dock phụ (không vải lụa, không bay về MacBook)
    if (!isVis || !isTop) {
        [self.hiddenPids removeObjectForKey:@(pid)];
        if (winId > 0) self.knownWins[@(winId)] = @(pid);

        // Cập nhật trạng thái tức thì để click liên tiếp không bao giờ bị trễ
        NSMutableDictionary *nextSt = [NSMutableDictionary dictionaryWithDictionary:self.appState];
        for (NSNumber *k in [nextSt allKeys]) {
            NSMutableDictionary *m = [NSMutableDictionary dictionaryWithDictionary:nextSt[k]];
            BOOL same = ([k intValue] == (int)pid);
            if (same) {
                m[@"visible"] = @YES;
                m[@"top"] = @YES;
                m[@"active"] = @YES;
            } else {
                m[@"top"] = @NO;
                m[@"active"] = @NO;
            }
            nextSt[k] = m;
        }
        self.appState = nextSt;
        [self updateItemVisuals:dock_is_dark_mode()];

        if (rapp) {
            [rapp unhide];
            [rapp activateWithOptions:NSApplicationActivateIgnoringOtherApps];
        }
        BOOL okAX = ax_raise_app_on_vdisp(pid, vb);
        if (!okAX) {
            // Fallback sang tiến trình Python cha nếu macOS chưa kế thừa quyền Accessibility cho helper con
            fprintf(stdout, "DOCK_ACTIVATE %d %u\n", (int)pid, winId);
            fflush(stdout);
        } else {
            // Nhịp phụ 30ms sau khi unhide để bắt chắc cửa sổ Electron/Chromium (Edge/Obsidian)
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.03 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
                ax_raise_app_on_vdisp(pid, vb);
                if (rapp) [rapp activateWithOptions:NSApplicationActivateIgnoringOtherApps];
            });
        }
    } else if (isFs && hasMain) {
        // App Full Screen trải 2 màn (Remote Desktop): không ẩn để tránh mất màn MacBook
        [self updateItemVisuals:dock_is_dark_mode()];
        return;
    } else {
        if (winId > 0) self.knownWins[@(winId)] = @(pid);
        NSMutableDictionary *nextSt = [NSMutableDictionary dictionaryWithDictionary:self.appState];
        if (nextSt[@(pid)]) {
            NSMutableDictionary *m = [NSMutableDictionary dictionaryWithDictionary:nextSt[@(pid)]];
            m[@"visible"] = @NO;
            m[@"top"] = @NO;
            m[@"active"] = @NO;
            nextSt[@(pid)] = m;
        }
        self.appState = nextSt;
        [self updateItemVisuals:dock_is_dark_mode()];

        if (!hasMain && rapp) {
            self.hiddenPids[@(pid)] = @(winId);
            [rapp hide];
        } else {
            BOOL okAX = ax_minimize_app_on_vdisp(pid, vb);
            if (!okAX) {
                fprintf(stdout, "DOCK_MINIMIZE %d %u\n", (int)pid, winId);
                fflush(stdout);
            }
        }
    }

    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.12 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        [self refresh];
    });
}

- (void)refresh {
    if (self.vdispId == 0 || !self.panel) return;
    CGRect vb = CGDisplayBounds(self.vdispId);
    NSScreen *scr = [self targetScreen];
    if (!scr || vb.size.width < 64 || vb.size.height < 64) {
        [self.panel orderOut:nil];
        return;
    }

    CFArrayRef allList = CGWindowListCopyWindowInfo(
        kCGWindowListOptionAll | kCGWindowListExcludeDesktopElements,
        kCGNullWindowID
    );
    if (!allList) return;

    NSArray *wins = (__bridge_transfer NSArray *)allList;
    NSMutableSet<NSNumber *> *aliveWinIds = [NSMutableSet set];
    NSMutableSet<NSNumber *> *mainScreenPids = [NSMutableSet set];
    NSMutableDictionary<NSNumber *, NSMutableDictionary *> *appsByPid = [NSMutableDictionary dictionary];
    NSRunningApplication *frontApp = [[NSWorkspace sharedWorkspace] frontmostApplication];
    pid_t frontPid = frontApp ? frontApp.processIdentifier : 0;
    pid_t topVdispPid = 0;

    for (NSDictionary *w in wins) {
        NSInteger layer = [w[(id)kCGWindowLayer] integerValue];
        if (layer != 0) continue;
        pid_t pid = (pid_t)[w[(id)kCGWindowOwnerPID] intValue];
        if (pid <= 0 || pid == self.selfPid) continue;
        NSNumber *winIdNum = w[(id)kCGWindowNumber];
        if (!winIdNum) continue;
        [aliveWinIds addObject:winIdNum];

        NSDictionary *bDict = w[(id)kCGWindowBounds];
        if (!bDict) continue;
        CGRect wb = CGRectZero;
        if (!CGRectMakeWithDictionaryRepresentation((__bridge CFDictionaryRef)bDict, &wb)) continue;

        CGFloat cx = wb.origin.x + wb.size.width * 0.5;
        CGFloat cy = wb.origin.y + wb.size.height * 0.5;
        BOOL inVdisp = (cx >= vb.origin.x && cx < (vb.origin.x + vb.size.width) &&
                        cy >= vb.origin.y && cy < (vb.origin.y + vb.size.height));
        BOOL isBigWindow = (wb.size.width >= 140.0 && wb.size.height >= 90.0);
        BOOL isOnscreen = [w[(id)kCGWindowIsOnscreen] boolValue];
        double alpha = [w[(id)kCGWindowAlpha] doubleValue];

        BOOL isTrackedKnown = (self.knownWins[winIdNum] != nil);
        BOOL trackedVisible = (inVdisp && isBigWindow && isOnscreen && alpha > 0.05);
        BOOL movedAwayVisibly = (!inVdisp && isBigWindow && isOnscreen && alpha > 0.05);

        if (movedAwayVisibly) {
            [mainScreenPids addObject:@(pid)];
            if (isTrackedKnown) [self.knownWins removeObjectForKey:winIdNum];
            continue;
        }
        if (!trackedVisible && !isTrackedKnown) continue;

        NSRunningApplication *rapp = [NSRunningApplication runningApplicationWithProcessIdentifier:pid];
        if (!rapp || rapp.isTerminated || rapp.activationPolicy != NSApplicationActivationPolicyRegular) {
            if (isTrackedKnown) [self.knownWins removeObjectForKey:winIdNum];
            continue;
        }

        BOOL effectiveVisible = (trackedVisible && !rapp.isHidden);
        BOOL isFsWin = NO;
        if (trackedVisible) {
            self.knownWins[winIdNum] = @(pid);
            if (effectiveVisible) {
                [self.hiddenPids removeObjectForKey:@(pid)];
                if (topVdispPid == 0) topVdispPid = pid;
                if (wb.size.width >= vb.size.width - 4.0 && wb.size.height >= vb.size.height - 4.0) {
                    isFsWin = YES;
                }
            }
        }

        NSNumber *pidNum = @(pid);
        NSMutableDictionary *entry = appsByPid[pidNum];
        BOOL isTop = (effectiveVisible && pid == topVdispPid);
        BOOL isAct = (isTop && pid == frontPid);
        if (!entry) {
            entry = [NSMutableDictionary dictionaryWithDictionary:@{
                @"winId": winIdNum,
                @"visible": @(effectiveVisible),
                @"top": @(isTop),
                @"active": @(isAct),
                @"hasMain": @NO,
                @"isFs": @(isFsWin),
            }];
            appsByPid[pidNum] = entry;
        } else if (effectiveVisible && ![entry[@"visible"] boolValue]) {
            entry[@"winId"] = winIdNum;
            entry[@"visible"] = @YES;
            entry[@"top"] = @(isTop);
            entry[@"active"] = @(isAct);
            entry[@"isFs"] = @(isFsWin);
        }
    }

    // Giữ icon các app đang thu gọn xuống khay bằng [rapp hide]
    NSArray<NSNumber *> *hiddenKeys = [self.hiddenPids allKeys];
    for (NSNumber *pidNum in hiddenKeys) {
        pid_t hpid = (pid_t)[pidNum intValue];
        NSRunningApplication *rapp = [NSRunningApplication runningApplicationWithProcessIdentifier:hpid];
        if (!rapp || rapp.isTerminated || [mainScreenPids containsObject:pidNum]) {
            [self.hiddenPids removeObjectForKey:pidNum];
            continue;
        }
        if (rapp.isHidden) {
            if (!appsByPid[pidNum]) {
                appsByPid[pidNum] = [NSMutableDictionary dictionaryWithDictionary:@{
                    @"winId": self.hiddenPids[pidNum] ?: @(0),
                    @"visible": @NO,
                    @"top": @NO,
                    @"active": @NO,
                    @"hasMain": @NO,
                    @"isFs": @NO,
                }];
            }
        } else {
            [self.hiddenPids removeObjectForKey:pidNum];
        }
    }

    for (NSNumber *pidNum in appsByPid) {
        appsByPid[pidNum][@"hasMain"] = @([mainScreenPids containsObject:pidNum]);
    }

    NSArray<NSNumber *> *knownKeys = [self.knownWins allKeys];
    for (NSNumber *wid in knownKeys) {
        if (![aliveWinIds containsObject:wid]) {
            NSNumber *kpid = self.knownWins[wid];
            NSRunningApplication *krapp = kpid
                ? [NSRunningApplication runningApplicationWithProcessIdentifier:(pid_t)[kpid intValue]]
                : nil;
            if (krapp && !krapp.isTerminated && krapp.isHidden && ![mainScreenPids containsObject:kpid]) {
                self.hiddenPids[kpid] = wid;
                if (!appsByPid[kpid]) {
                    appsByPid[kpid] = [NSMutableDictionary dictionaryWithDictionary:@{
                        @"winId": wid,
                        @"visible": @NO,
                        @"top": @NO,
                        @"active": @NO,
                        @"hasMain": @NO,
                        @"isFs": @NO,
                    }];
                }
            }
            [self.knownWins removeObjectForKey:wid];
        }
    }

    NSMutableArray<NSNumber *> *nextOrder = [NSMutableArray array];
    for (NSNumber *pidNum in self.appOrder) {
        if (appsByPid[pidNum]) [nextOrder addObject:pidNum];
    }
    NSArray<NSNumber *> *sortedNew = [[appsByPid allKeys] sortedArrayUsingSelector:@selector(compare:)];
    for (NSNumber *pidNum in sortedNew) {
        if (![nextOrder containsObject:pidNum]) [nextOrder addObject:pidNum];
    }
    self.appOrder = nextOrder;
    self.appState = appsByPid;

    BOOL isDark = dock_is_dark_mode();
    // CHỈ dựng lại khung nút khi danh sách app / kích thước màn hình / Light-Dark thay đổi -> KHÔNG BAO GIỜ hủy nút lúc đang bấm!
    NSMutableString *layoutSig = [NSMutableString stringWithFormat:@"%.0f,%.0f,%.0f,%.0f:%d:",
                                  scr.frame.origin.x, scr.frame.origin.y, scr.frame.size.width, scr.frame.size.height, isDark ? 1 : 0];
    for (NSNumber *pidNum in self.appOrder) {
        [layoutSig appendFormat:@"%@,", pidNum];
    }

    if (![layoutSig isEqualToString:self.lastLayoutSig]) {
        self.lastLayoutSig = layoutSig;
        NSArray<NSView *> *oldSubs = [self.bgView.subviews copy];
        for (NSView *sv in oldSubs) [sv removeFromSuperview];
        [self.itemViews removeAllObjects];

        CGFloat dockW = 16.0;
        CGFloat dockH = 56.0;
        CGFloat radius = 7.0;
        if (self.appOrder.count == 0) {
            self.panel.alphaValue = 0.55;
            NSView *bar = [[NSView alloc] initWithFrame:NSMakeRect((dockW - 2.0) * 0.5, (dockH - 22.0) * 0.5, 2.0, 22.0)];
            bar.wantsLayer = YES;
            bar.layer.cornerRadius = 1.0;
            bar.layer.backgroundColor = isDark
                ? [[NSColor colorWithWhite:1.0 alpha:0.32] CGColor]
                : [[NSColor colorWithWhite:0.15 alpha:0.26] CGColor];
            [self.bgView addSubview:bar];
        } else {
            self.panel.alphaValue = 0.92;
            radius = 13.0;
            NSUInteger count = self.appOrder.count;
            CGFloat itemStep = 36.0;
            CGFloat maxH = MAX(120.0, scr.frame.size.height - 48.0);
            NSUInteger maxItems = (NSUInteger)MAX(1, floor((maxH - 14.0) / itemStep));
            if (count > maxItems) count = maxItems;
            dockW = 42.0;
            dockH = 14.0 + count * itemStep;

            __weak SecondaryDockController *weakSelf = self;
            for (NSUInteger i = 0; i < count; i++) {
                NSNumber *pidNum = self.appOrder[i];
                pid_t pid = (pid_t)[pidNum intValue];
                CGFloat by = dockH - 7.0 - (CGFloat)(i + 1) * itemStep;

                DockItemView *item = [[DockItemView alloc] initWithFrame:NSMakeRect(0.0, by, dockW, itemStep)];
                item.appPid = pid;
                item.onClick = ^(pid_t clickedPid) {
                    SecondaryDockController *strongSelf = weakSelf;
                    if (strongSelf) [strongSelf handleClickForPid:clickedPid];
                };

                NSImageView *iv = [[NSImageView alloc] initWithFrame:NSMakeRect(6.0, 5.0, 26.0, 26.0)];
                iv.imageScaling = NSImageScaleProportionallyUpOrDown;
                NSRunningApplication *rapp = [NSRunningApplication runningApplicationWithProcessIdentifier:pid];
                if (rapp && rapp.icon) {
                    NSImage *ico = [rapp.icon copy];
                    ico.size = NSMakeSize(26.0, 26.0);
                    iv.image = ico;
                }
                [item addSubview:iv];
                item.iconView = iv;

                NSView *dot = [[NSView alloc] initWithFrame:NSMakeRect(dockW - 5.5, (itemStep - 3.5) * 0.5, 3.5, 3.5)];
                dot.wantsLayer = YES;
                dot.layer.cornerRadius = 1.75;
                [item addSubview:dot];
                item.dotView = dot;

                [self.bgView addSubview:item];
                self.itemViews[pidNum] = item;
            }
        }

        CGFloat dockX = scr.frame.origin.x + scr.frame.size.width - dockW - 4.0;
        CGFloat dockY = scr.frame.origin.y + (scr.frame.size.height - dockH) * 0.5;
        self.bgView.maskImage = make_pill_mask(radius);
        self.bgView.layer.cornerRadius = radius;
        self.bgView.layer.borderColor = isDark
            ? [[NSColor colorWithWhite:1.0 alpha:0.20] CGColor]
            : [[NSColor colorWithWhite:1.0 alpha:0.48] CGColor];
        [self.panel setFrame:NSMakeRect(dockX, dockY, dockW, dockH) display:YES];
        self.bgView.frame = NSMakeRect(0, 0, dockW, dockH);
        [self.panel invalidateShadow];
    }

    [self updateItemVisuals:isDark];
    [self.panel orderFrontRegardless];
}

- (void)markPidMinimized:(pid_t)pid {
    if (pid <= 0) return;
    NSDictionary *st = self.appState[@(pid)];
    if (st && st[@"winId"]) {
        self.knownWins[st[@"winId"]] = @(pid);
        self.hiddenPids[@(pid)] = st[@"winId"];
    } else {
        self.hiddenPids[@(pid)] = @(0);
    }
}

- (void)unmarkPidMinimized:(pid_t)pid {
    if (pid <= 0) return;
    [self.hiddenPids removeObjectForKey:@(pid)];
}

- (void)syncFullscreenRdpOnVdispIfNeeded:(NSRunningApplication *)activatedApp {
    if (!activatedApp || self.vdispId == 0) return;
    NSString *bid = [[activatedApp bundleIdentifier] lowercaseString] ?: @"";
    NSString *lname = [[activatedApp localizedName] lowercaseString] ?: @"";
    BOOL isRdp = ([bid isEqualToString:@"com.microsoft.rdc.macos"] ||
                  [bid isEqualToString:@"com.microsoft.rdc.osx.beta"] ||
                  [lname isEqualToString:@"microsoft remote desktop"] ||
                  [lname isEqualToString:@"windows app"]);
    if (!isRdp) return;

    CFAbsoluteTime now = CFAbsoluteTimeGetCurrent();
    if ((now - self.lastRdpSyncAt) < 0.85) return;

    CGRect vb = CGDisplayBounds(self.vdispId);
    if (vb.size.width < 64 || vb.size.height < 64) return;
    pid_t rpid = activatedApp.processIdentifier;

    // Kiểm tra xem Microsoft Remote Desktop có cửa sổ Full Screen trên Màn phụ #2 đang bị che bởi Space/app Mac khác không
    CFArrayRef allList = CGWindowListCopyWindowInfo(
        kCGWindowListOptionAll | kCGWindowListExcludeDesktopElements,
        kCGNullWindowID
    );
    if (!allList) return;
    NSArray *wins = (__bridge_transfer NSArray *)allList;
    BOOL hasHiddenVdispFs = NO;
    for (NSDictionary *w in wins) {
        if ((pid_t)[w[(id)kCGWindowOwnerPID] intValue] != rpid) continue;
        if ([w[(id)kCGWindowLayer] integerValue] != 0) continue;
        NSDictionary *bDict = w[(id)kCGWindowBounds];
        if (!bDict) continue;
        CGRect wb = CGRectZero;
        if (!CGRectMakeWithDictionaryRepresentation((__bridge CFDictionaryRef)bDict, &wb)) continue;
        CGFloat cx = wb.origin.x + wb.size.width * 0.5;
        CGFloat cy = wb.origin.y + wb.size.height * 0.5;
        BOOL inVdisp = (cx >= vb.origin.x && cx < (vb.origin.x + vb.size.width) &&
                        cy >= vb.origin.y && cy < (vb.origin.y + vb.size.height));
        if (!inVdisp) continue;
        if (wb.size.width >= vb.size.width - 24.0 && wb.size.height >= vb.size.height - 80.0) {
            BOOL isOnscr = [w[(id)kCGWindowIsOnscreen] boolValue];
            if (!isOnscr) {
                hasHiddenVdispFs = YES;
                break;
            }
        }
    }
    if (!hasHiddenVdispFs) return;

    // Đồng bộ tức thì Space Màn phụ #2 quay lại đúng màn #2 của Remote Desktop (VD: Obsidian) khi bạn bấm về Remote trên MacBook!
    self.lastRdpSyncAt = now;
    [activatedApp activateWithOptions:(NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps)];
    ax_raise_app_on_vdisp(rpid, vb);
}

- (void)shutdown {
    if (self.panel) {
        [self.panel orderOut:nil];
        [self.panel close];
        self.panel = nil;
    }
}

@end

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
        select_best_hidpi_mode(did, logicalW, logicalH, wantHiDPI);
        usleep(120000);
        position_display_left_of_main(did);
        usleep(120000);

        CGRect b = CGDisplayBounds(did);
        fprintf(stdout, "READY %u %d %d %u %.0f %.0f %.0f %.0f\n",
                (unsigned int)did,
                (int)logicalW,
                (int)logicalH,
                wantHiDPI,
                b.origin.x, b.origin.y, b.size.width, b.size.height);
        fflush(stdout);

        // Khởi tạo AppKit Accessory + Dock riêng cho Màn hình phụ #2 (không hiện icon thừa trên Dock chính)
        SecondaryDockController *dockCtrl = nil;
        @try {
            NSApplication *app = [NSApplication sharedApplication];
            [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
            [app finishLaunching];
            dockCtrl = [[SecondaryDockController alloc] initWithDisplayID:did];
            [dockCtrl refresh];
        } @catch (NSException *ex) {
            (void)ex;
            dockCtrl = nil;
        }

        // Theo dõi stdin lệnh điều khiển (m <pid> / u <pid> / q) và EOF để tự hủy màn ảo
        __weak SecondaryDockController *weakDock = dockCtrl;
        void (^triggerStop)(void) = ^{
            g_should_exit = 1;
            dispatch_async(dispatch_get_main_queue(), ^{
                [NSApp stop:nil];
                NSEvent *wakeEv = [NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                                     location:NSZeroPoint
                                                modifierFlags:0
                                                    timestamp:0
                                                 windowNumber:0
                                                      context:nil
                                                      subtype:0
                                                        data1:0
                                                        data2:0];
                if (wakeEv) [NSApp postEvent:wakeEv atStart:YES];
            });
        };

        dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_LOW, 0), ^{
            char line[128];
            while (fgets(line, sizeof(line), stdin) != NULL) {
                if (line[0] == 'q' || line[0] == 'Q') break;
                if ((line[0] == 'm' || line[0] == 'u') && line[1] == ' ') {
                    pid_t tpid = (pid_t)atoi(line + 2);
                    BOOL isMin = (line[0] == 'm');
                    dispatch_async(dispatch_get_main_queue(), ^{
                        SecondaryDockController *d = weakDock;
                        if (!d) return;
                        if (isMin) [d markPidMinimized:tpid];
                        else [d unmarkPidMinimized:tpid];
                        [d refresh];
                    });
                }
            }
            triggerStop();
        });

        if (dockCtrl) {
            // Dùng vòng lặp sự kiện gốc [NSApp run] + NSWorkspace notifications (phản hồi click < 1ms, 0% lag!)
            NSNotificationCenter *wsnc = [[NSWorkspace sharedWorkspace] notificationCenter];
            NSArray<NSNotificationName> *evNames = @[
                NSWorkspaceDidActivateApplicationNotification,
                NSWorkspaceDidHideApplicationNotification,
                NSWorkspaceDidUnhideApplicationNotification,
                NSWorkspaceDidTerminateApplicationNotification,
                NSWorkspaceActiveSpaceDidChangeNotification
            ];
            NSMutableArray *obsTokens = [NSMutableArray array];
            for (NSNotificationName name in evNames) {
                id tok = [wsnc addObserverForName:name
                                           object:nil
                                            queue:[NSOperationQueue mainQueue]
                                       usingBlock:^(NSNotification *note) {
                    SecondaryDockController *d = weakDock;
                    if (d) {
                        @try {
                            if ([name isEqualToString:NSWorkspaceDidActivateApplicationNotification]) {
                                NSRunningApplication *actApp = note.userInfo[NSWorkspaceApplicationKey];
                                if (actApp) [d syncFullscreenRdpOnVdispIfNeeded:actApp];
                            }
                            [d refresh];
                        } @catch (NSException *ex) { (void)ex; }
                    }
                }];
                if (tok) [obsTokens addObject:tok];
            }

            NSTimer *pollTimer = [NSTimer scheduledTimerWithTimeInterval:0.45
                                                                 repeats:YES
                                                                   block:^(NSTimer *t) {
                if (g_should_exit) {
                    [t invalidate];
                    [NSApp stop:nil];
                    NSEvent *wakeEv = [NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                                         location:NSZeroPoint
                                                    modifierFlags:0
                                                        timestamp:0
                                                     windowNumber:0
                                                          context:nil
                                                          subtype:0
                                                            data1:0
                                                            data2:0];
                    if (wakeEv) [NSApp postEvent:wakeEv atStart:YES];
                    return;
                }
                SecondaryDockController *d = weakDock;
                if (d) {
                    @try { [d refresh]; } @catch (NSException *ex) { (void)ex; }
                }
            }];

            [NSApp run];

            [pollTimer invalidate];
            for (id tok in obsTokens) [wsnc removeObserver:tok];
            [dockCtrl shutdown];
            dockCtrl = nil;
        } else {
            while (!g_should_exit) {
                @autoreleasepool {
                    [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                             beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.2]];
                }
            }
        }
        vdisp = nil;
    }
    return 0;
}
"""


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("w", ctypes.c_double), ("h", ctypes.c_double)]


class MacVirtualDisplayManager:
    """Quản lý vòng đời Màn hình phụ #2 gốc macOS + Per-Monitor Dock (độc lập với Remote PC / Windows App)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen] = None
        self._display_id: int = 0
        self._logical_w: int = 1798
        self._logical_h: int = 864
        self._hidpi: bool = True
        self._last_error: str = ""
        self._cache_dir = Path.home() / ".cache" / "mac-web-keyboard"
        self._bin_path = self._cache_dir / "mac_vdisp_helper_v3"
        self._src_path = self._cache_dir / "mac_vdisp_helper_v3.m"
        self._ax_lib: Any = None
        self._cf_lib: Any = None
        self._ax_ready: bool = False
        self._dock_icons: list = []
        self._vdisp_only_apps: Dict[str, int] = {}
        self._min_vdisp_pids: set = set()
        self._vdisp_seen_pids: set = set()
        self._custom_dock_pid: int = 0
        self._custom_dock_anchor: Optional[Tuple[float, float]] = None
        self._vdisp_bounds_cache: Optional[Dict[str, float]] = None
        self._vdisp_has_fullscreen: bool = False
        self._tap_loop_ref: Any = None
        self._tap_gen: int = 0
        atexit.register(self.stop)

    def _init_ax_libs(self) -> bool:
        if self._ax_ready or not IS_MACOS:
            return self._ax_ready
        try:
            ax = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
            )
            cf = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )
            cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            cf.CFRelease.restype = None
            cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
            cf.CFArrayGetCount.restype = ctypes.c_long
            cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
            cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
            cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
            cf.CFBooleanGetValue.restype = ctypes.c_bool

            ax.AXUIElementCreateApplication.argtypes = [ctypes.c_int32]
            ax.AXUIElementCreateApplication.restype = ctypes.c_void_p
            ax.AXUIElementCopyAttributeValue.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            ax.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
            ax.AXUIElementSetAttributeValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
            ax.AXUIElementSetAttributeValue.restype = ctypes.c_int32
            ax.AXUIElementPerformAction.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            ax.AXUIElementPerformAction.restype = ctypes.c_int32
            ax.AXValueGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p]
            ax.AXValueGetValue.restype = ctypes.c_bool
            ax.AXValueCreate.argtypes = [ctypes.c_int32, ctypes.c_void_p]
            ax.AXValueCreate.restype = ctypes.c_void_p

            self._ax_lib = ax
            self._cf_lib = cf
            self._ax_ready = True
        except Exception:
            self._ax_ready = False
        return self._ax_ready

    def _ax_handle_dock_action(self, action: str, pid: int) -> None:
        if pid <= 0 or not self._init_ax_libs():
            return
        bounds = self.get_bounds()
        if not bounds:
            return
        bx, by, bw, bh = bounds["x"], bounds["y"], bounds["w"], bounds["h"]
        ax = self._ax_lib
        cf = self._cf_lib
        kCFStringEncodingUTF8 = 0x08000100

        def _cfstr(s: str) -> ctypes.c_void_p:
            return cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)

        app_ax = ax.AXUIElementCreateApplication(int(pid))
        if not app_ax:
            return
        s_wins = _cfstr("AXWindows")
        s_pos = _cfstr("AXPosition")
        s_size = _cfstr("AXSize")
        s_min = _cfstr("AXMinimized")
        s_fs = _cfstr("AXFullScreen")
        s_main = _cfstr("AXMain")
        s_focused = _cfstr("AXFocused")
        s_frontmost = _cfstr("AXFrontmost")
        s_raise = _cfstr("AXRaise")
        try:
            kTrue = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue").value
            kFalse = ctypes.c_void_p.in_dll(cf, "kCFBooleanFalse").value

            rapp = None
            try:
                import AppKit  # type: ignore

                rapp = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
            except Exception:
                rapp = None

            # Nếu kích hoạt app đang bị ẩn (rapp.hide()), phải unhide + đẩy AXFrontmost TRƯỚC khi đọc AXWindows!
            if action == "activate":
                self._min_vdisp_pids.discard(pid)
                was_hidden = False
                if rapp is not None:
                    try:
                        was_hidden = bool(rapp.isHidden())
                        rapp.unhide()
                    except Exception:
                        pass
                ax.AXUIElementSetAttributeValue(app_ax, s_frontmost, kTrue)
                if rapp is not None:
                    try:
                        rapp.activateWithOptions_(2)
                    except Exception:
                        pass
                if was_hidden:
                    time.sleep(0.035)

            wins_ref = ctypes.c_void_p()
            if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wins_ref)) != 0 or not wins_ref.value:
                return
            try:
                cnt = cf.CFArrayGetCount(wins_ref.value)
                vdisp_matches = []
                min_fallback = []
                for i in range(cnt):
                    w_ax = cf.CFArrayGetValueAtIndex(wins_ref.value, i)
                    if not w_ax:
                        continue
                    pos_ref = ctypes.c_void_p()
                    size_ref = ctypes.c_void_p()
                    in_vdisp = False
                    if (
                        ax.AXUIElementCopyAttributeValue(w_ax, s_pos, ctypes.byref(pos_ref)) == 0
                        and pos_ref.value
                        and ax.AXUIElementCopyAttributeValue(w_ax, s_size, ctypes.byref(size_ref)) == 0
                        and size_ref.value
                    ):
                        pt = _CGPoint()
                        sz = _CGSize()
                        ok_p = ax.AXValueGetValue(pos_ref.value, 1, ctypes.byref(pt))
                        ok_s = ax.AXValueGetValue(size_ref.value, 2, ctypes.byref(sz))
                        cf.CFRelease(pos_ref.value)
                        cf.CFRelease(size_ref.value)
                        if ok_p and ok_s and sz.w >= 120 and sz.h >= 80:
                            cx = pt.x + sz.w * 0.5
                            cy = pt.y + sz.h * 0.5
                            in_vdisp = (bx <= cx < bx + bw) and (by <= cy < by + bh)
                    else:
                        if pos_ref.value:
                            cf.CFRelease(pos_ref.value)
                        if size_ref.value:
                            cf.CFRelease(size_ref.value)

                    min_ref = ctypes.c_void_p()
                    is_min = False
                    if ax.AXUIElementCopyAttributeValue(w_ax, s_min, ctypes.byref(min_ref)) == 0 and min_ref.value:
                        is_min = bool(cf.CFBooleanGetValue(min_ref.value))
                        cf.CFRelease(min_ref.value)

                    fs_ref = ctypes.c_void_p()
                    is_fs = False
                    if ax.AXUIElementCopyAttributeValue(w_ax, s_fs, ctypes.byref(fs_ref)) == 0 and fs_ref.value:
                        is_fs = bool(cf.CFBooleanGetValue(fs_ref.value))
                        cf.CFRelease(fs_ref.value)

                    if in_vdisp:
                        vdisp_matches.append((w_ax, is_min, is_fs))
                    elif is_min:
                        min_fallback.append((w_ax, is_min, is_fs))

                if action == "activate":
                    targets = vdisp_matches if vdisp_matches else min_fallback
                    for _pass in range(2):
                        ax.AXUIElementSetAttributeValue(app_ax, s_frontmost, kTrue)
                        for w_ax, is_min, _ in targets:
                            if is_min:
                                ax.AXUIElementSetAttributeValue(w_ax, s_min, kFalse)
                            ax.AXUIElementSetAttributeValue(w_ax, s_main, kTrue)
                            ax.AXUIElementSetAttributeValue(w_ax, s_focused, kTrue)
                            ax.AXUIElementPerformAction(w_ax, s_raise)
                        if rapp is not None:
                            try:
                                rapp.activateWithOptions_(2)
                            except Exception:
                                pass
                        if _pass == 0 and targets:
                            time.sleep(0.04)
                elif action == "minimize":
                    self._min_vdisp_pids.add(pid)
                    for w_ax, is_min, is_fs in vdisp_matches:
                        if not is_min and not is_fs:
                            ax.AXUIElementSetAttributeValue(w_ax, s_min, kTrue)
            finally:
                cf.CFRelease(wins_ref.value)
        except Exception:
            pass
        finally:
            cf.CFRelease(app_ax)
            for s_ref in (s_wins, s_pos, s_size, s_min, s_fs, s_main, s_focused, s_frontmost, s_raise):
                if s_ref:
                    cf.CFRelease(s_ref)

    def _stdout_reader_loop(self, proc: subprocess.Popen) -> None:
        try:
            if proc.stdout is None:
                return
            for raw in proc.stdout:
                line = (raw or "").strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] in ("DOCK_ACTIVATE", "DOCK_MINIMIZE"):
                    try:
                        pid = int(parts[1])
                    except Exception:
                        continue
                    act = "activate" if parts[0] == "DOCK_ACTIVATE" else "minimize"
                    threading.Thread(
                        target=self._ax_handle_dock_action,
                        args=(act, pid),
                        daemon=True,
                    ).start()
        except Exception:
            pass

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
                "-framework",
                "AppKit",
                "-framework",
                "QuartzCore",
                "-framework",
                "ApplicationServices",
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
            threading.Thread(target=self._stdout_reader_loop, args=(proc,), daemon=True).start()
            self._start_dock_interceptor()
            return self.status()

    def _send_helper_cmd(self, cmd_line: str) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        try:
            proc.stdin.write(cmd_line.rstrip("\n") + "\n")
            proc.stdin.flush()
        except Exception:
            pass

    def _toggle_vdisp_app_from_mac_dock(self, pid: int) -> None:
        """Khi ấn icon trên Dock MacBook của một app đang nằm trên Màn phụ #2:
        Thu nhỏ / mở lại trực tiếp cửa sổ ngay trên Màn phụ #2 mà KHÔNG làm mất Dock MacBook!"""
        if pid <= 0 or not self._init_ax_libs():
            return
        bounds = self.get_bounds()
        if not bounds:
            return
        bx, by, bw, bh = bounds["x"], bounds["y"], bounds["w"], bounds["h"]
        ax = self._ax_lib
        cf = self._cf_lib
        kCFStringEncodingUTF8 = 0x08000100

        def _cfstr(s: str) -> ctypes.c_void_p:
            return cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)

        try:
            import AppKit  # type: ignore

            ws_shared = AppKit.NSWorkspace.sharedWorkspace()
            front = ws_shared.frontmostApplication()
            front_pid = int(front.processIdentifier()) if front is not None else 0
            rapp = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            if rapp is None:
                return
            is_hidden = bool(rapp.isHidden())
            if is_hidden:
                self._min_vdisp_pids.discard(pid)
                self._send_helper_cmd(f"u {pid}")
                rapp.unhide()
                rapp.activateWithOptions_(2)
                return

            app_ax = ax.AXUIElementCreateApplication(int(pid))
            if not app_ax:
                return
            s_wins = _cfstr("AXWindows")
            s_pos = _cfstr("AXPosition")
            s_size = _cfstr("AXSize")
            s_min = _cfstr("AXMinimized")
            s_fs = _cfstr("AXFullScreen")
            s_raise = _cfstr("AXRaise")
            try:
                wins_ref = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wins_ref)) != 0 or not wins_ref.value:
                    return
                try:
                    cnt = cf.CFArrayGetCount(wins_ref.value)
                    kTrue = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue").value
                    kFalse = ctypes.c_void_p.in_dll(cf, "kCFBooleanFalse").value
                    vdisp_wins = []
                    for i in range(cnt):
                        w_ax = cf.CFArrayGetValueAtIndex(wins_ref.value, i)
                        if not w_ax:
                            continue
                        pos_ref = ctypes.c_void_p()
                        size_ref = ctypes.c_void_p()
                        in_vdisp = False
                        if (
                            ax.AXUIElementCopyAttributeValue(w_ax, s_pos, ctypes.byref(pos_ref)) == 0
                            and pos_ref.value
                            and ax.AXUIElementCopyAttributeValue(w_ax, s_size, ctypes.byref(size_ref)) == 0
                            and size_ref.value
                        ):
                            pt = _CGPoint()
                            sz = _CGSize()
                            ok_p = ax.AXValueGetValue(pos_ref.value, 1, ctypes.byref(pt))
                            ok_s = ax.AXValueGetValue(size_ref.value, 2, ctypes.byref(sz))
                            cf.CFRelease(pos_ref.value)
                            cf.CFRelease(size_ref.value)
                            if ok_p and ok_s and sz.w >= 120 and sz.h >= 80:
                                cx = pt.x + sz.w * 0.5
                                cy = pt.y + sz.h * 0.5
                                in_vdisp = (bx <= cx < bx + bw) and (by <= cy < by + bh)
                        else:
                            if pos_ref.value:
                                cf.CFRelease(pos_ref.value)
                            if size_ref.value:
                                cf.CFRelease(size_ref.value)
                        if not in_vdisp:
                            continue
                        min_ref = ctypes.c_void_p()
                        is_min = False
                        if ax.AXUIElementCopyAttributeValue(w_ax, s_min, ctypes.byref(min_ref)) == 0 and min_ref.value:
                            is_min = bool(cf.CFBooleanGetValue(min_ref.value))
                            cf.CFRelease(min_ref.value)
                        fs_ref = ctypes.c_void_p()
                        is_fs = False
                        if ax.AXUIElementCopyAttributeValue(w_ax, s_fs, ctypes.byref(fs_ref)) == 0 and fs_ref.value:
                            is_fs = bool(cf.CFBooleanGetValue(fs_ref.value))
                            cf.CFRelease(fs_ref.value)
                        vdisp_wins.append((w_ax, is_min, is_fs))

                    if not vdisp_wins:
                        if bool(rapp.isHidden()):
                            self._min_vdisp_pids.discard(pid)
                            self._send_helper_cmd(f"u {pid}")
                            rapp.unhide()
                            rapp.activateWithOptions_(2)
                        return
                    any_visible = (not bool(rapp.isHidden())) and any(not m for _, m, _ in vdisp_wins)
                    if any_visible and front_pid == pid:
                        # Ẩn tức thì ngay trên Màn phụ bằng rapp.hide() (KHÔNG hiệu ứng uốn vải lụa Genie, KHÔNG bay về Dock MacBook!)
                        self._min_vdisp_pids.add(pid)
                        self._send_helper_cmd(f"m {pid}")
                        rapp.hide()
                    else:
                        # Đang ẩn/thu nhỏ hoặc bị che -> mở tức thì ngay trên Màn phụ!
                        self._min_vdisp_pids.discard(pid)
                        self._send_helper_cmd(f"u {pid}")
                        rapp.unhide()
                        for w_ax, is_min, _ in vdisp_wins:
                            if is_min:
                                ax.AXUIElementSetAttributeValue(w_ax, s_min, kFalse)
                            ax.AXUIElementPerformAction(w_ax, s_raise)
                        rapp.activateWithOptions_(2)
                    # Giữ SmartRightDock / Docky khóa chặt ở mép phải MacBook, không để nhảy sang Màn phụ
                    for delay_s in (0.06, 0.22):
                        threading.Timer(delay_s, self._pin_custom_dock_to_main).start()
                finally:
                    cf.CFRelease(wins_ref.value)
            finally:
                cf.CFRelease(app_ax)
                for s_ref in (s_wins, s_pos, s_size, s_min, s_fs, s_raise):
                    if s_ref:
                        cf.CFRelease(s_ref)
        except Exception:
            pass

    def _pin_custom_dock_to_main(self, quartz: Any = None) -> None:
        """Giữ thanh Dock dọc bên phải (SmartRightDock / AlwaysDock / Docky) luôn neo trên màn chính MacBook,
        tự động kéo về vị trí cũ nếu nó nhảy sang Màn phụ #2 khi kích hoạt app trên Màn phụ."""
        if not IS_MACOS or not self._init_ax_libs() or not self.is_active():
            return
        try:
            q = quartz
            if q is None:
                import Quartz as q  # type: ignore
            import objc  # type: ignore

            bounds = self._vdisp_bounds_cache or self.get_bounds(q)
            if not bounds:
                return
            bx, by, bw, bh = bounds["x"], bounds["y"], bounds["w"], bounds["h"]
            mb = q.CGDisplayBounds(q.CGMainDisplayID())
            mw, mh = float(mb.size.width), float(mb.size.height)

            cd_pid = 0
            drifted = False
            win_w = 48.0
            win_h = 340.0
            with objc.autorelease_pool():
                wlist = q.CGWindowListCopyWindowInfo(
                    q.kCGWindowListOptionOnScreenOnly,
                    q.kCGNullWindowID,
                ) or []
                for w in wlist:
                    owner = str(w.get("kCGWindowOwnerName", "") or "").lower()
                    if "smartrightdock" not in owner and "alwaysdock" not in owner and "docky" not in owner:
                        continue
                    wb = w.get("kCGWindowBounds") or {}
                    ww = float(wb.get("Width", 0))
                    wh = float(wb.get("Height", 0))
                    if ww < 20.0 or wh < 40.0:
                        continue
                    wx = float(wb.get("X", 0))
                    wy = float(wb.get("Y", 0))
                    cd_pid = int(w.get("kCGWindowOwnerPID", 0) or 0)
                    win_w, win_h = ww, wh
                    cx = wx + ww * 0.5
                    cy = wy + wh * 0.5
                    if (0.0 <= cx < mw) and (0.0 <= cy < mh):
                        self._custom_dock_anchor = (wx, wy)
                        self._custom_dock_pid = cd_pid
                    elif (wx < 0.0) or ((bx <= cx < bx + bw) and (by <= cy < by + bh)):
                        drifted = True
                        self._custom_dock_pid = cd_pid
                        break

            if not drifted or cd_pid <= 0:
                return

            ax = self._ax_lib
            cf = self._cf_lib
            s_wins = cf.CFStringCreateWithCString(None, b"AXWindows", 0x08000100)
            s_pos = cf.CFStringCreateWithCString(None, b"AXPosition", 0x08000100)
            app_ax = ax.AXUIElementCreateApplication(cd_pid)
            try:
                if not app_ax:
                    return
                wr = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wr)) != 0 or not wr.value:
                    return
                try:
                    anchor = self._custom_dock_anchor or (
                        max(0.0, mw - win_w - 3.0),
                        max(40.0, (mh - win_h) * 0.5),
                    )
                    pt = _CGPoint(float(anchor[0]), float(anchor[1]))
                    pv = ax.AXValueCreate(1, ctypes.byref(pt))
                    if pv:
                        try:
                            n_w = cf.CFArrayGetCount(wr.value)
                            for i in range(min(4, n_w)):
                                w_ax = cf.CFArrayGetValueAtIndex(wr.value, i)
                                if w_ax:
                                    ax.AXUIElementSetAttributeValue(w_ax, s_pos, pv)
                        finally:
                            cf.CFRelease(pv)
                finally:
                    cf.CFRelease(wr.value)
            finally:
                if app_ax:
                    cf.CFRelease(app_ax)
                if s_wins:
                    cf.CFRelease(s_wins)
                if s_pos:
                    cf.CFRelease(s_pos)
        except Exception:
            pass

    def _refresh_dock_intercept_cache(self) -> None:
        if not IS_MACOS or not self._init_ax_libs():
            return
        try:
            import Quartz as q  # type: ignore
            import AppKit  # type: ignore
            import objc  # type: ignore

            bounds = self.get_bounds(q)
            self._vdisp_bounds_cache = bounds
            if not bounds:
                self._dock_icons = []
                self._vdisp_only_apps = {}
                self._vdisp_has_fullscreen = False
                return
            bx, by, bw, bh = bounds["x"], bounds["y"], bounds["w"], bounds["h"]
            mb = q.CGDisplayBounds(q.CGMainDisplayID())
            mw, mh = float(mb.size.width), float(mb.size.height)

            ax = self._ax_lib
            cf = self._cf_lib
            kCFStringEncodingUTF8 = 0x08000100

            def _cfstr(s: str) -> ctypes.c_void_p:
                return cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)

            def _cf_to_py(ptr_val: int) -> str:
                if not ptr_val:
                    return ""
                try:
                    return str(objc.objc_object(c_void_p=ptr_val) or "")
                except Exception:
                    return ""

            # 1. Xác định các app đang nằm RIÊNG trên Màn phụ #2 + vị trí SmartRightDock/Docky trên MacBook
            custom_dock_pid = 0
            custom_dock_drifted = False
            with objc.autorelease_pool():
                wins = q.CGWindowListCopyWindowInfo(
                    q.kCGWindowListOptionAll | q.kCGWindowListExcludeDesktopElements,
                    q.kCGNullWindowID,
                ) or []
                vdisp_pids: set = set(self._min_vdisp_pids)
                vdisp_onscreen_pids: set = set()
                main_pids: set = set()
                has_fs = False
                for w in wins:
                    ly = int(w.get("kCGWindowLayer", -1))
                    owner_l = str(w.get("kCGWindowOwnerName", "") or "").lower()
                    pid = int(w.get("kCGWindowOwnerPID", 0) or 0)
                    if pid <= 0 or pid == os.getpid():
                        continue
                    wb = w.get("kCGWindowBounds") or {}
                    ww = float(wb.get("Width", 0))
                    wh = float(wb.get("Height", 0))
                    wx = float(wb.get("X", 0))
                    wy = float(wb.get("Y", 0))
                    onscr = bool(w.get("kCGWindowIsOnscreen", False))
                    alpha = float(w.get("kCGWindowAlpha", 1.0) or 0.0)

                    # Theo dõi thanh Dock dọc bên phải (SmartRightDock / AlwaysDock / Docky)
                    if ("smartrightdock" in owner_l or "alwaysdock" in owner_l or "docky" in owner_l):
                        if onscr and ww >= 20.0 and wh >= 40.0:
                            custom_dock_pid = pid
                            self._custom_dock_pid = pid
                            cx_d = wx + ww * 0.5
                            cy_d = wy + wh * 0.5
                            if (0.0 <= cx_d < mw) and (0.0 <= cy_d < mh):
                                self._custom_dock_anchor = (wx, wy)
                            elif (wx < 0.0) or ((bx <= cx_d < bx + bw) and (by <= cy_d < by + bh)):
                                custom_dock_drifted = True
                        continue

                    if ly != 0:
                        continue
                    if ww < 140 or wh < 90:
                        continue
                    cx = wx + ww * 0.5
                    cy = wy + wh * 0.5
                    if (bx <= cx < bx + bw) and (by <= cy < by + bh):
                        if onscr and alpha > 0.05:
                            vdisp_pids.add(pid)
                            vdisp_onscreen_pids.add(pid)
                            if ww >= bw - 4.0 and wh >= bh - 4.0:
                                has_fs = True
                        elif (not onscr) and (pid in self._vdisp_seen_pids):
                            # Giữ theo dõi app bị thu nhỏ bằng nút vàng trên Màn phụ #2
                            vdisp_pids.add(pid)
                    elif (0.0 <= cx < mw) and (0.0 <= cy < mh):
                        if onscr and alpha > 0.05:
                            main_pids.add(pid)
                self._vdisp_has_fullscreen = has_fs
                self._vdisp_seen_pids = (self._vdisp_seen_pids | vdisp_onscreen_pids) - main_pids

                only_vdisp_pids = vdisp_pids - main_pids
                vdisp_name_map: Dict[str, int] = {}
                dock_pid = 0
                apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications() or []
                alive_pids = set()
                for rapp in apps:
                    try:
                        bid = str(rapp.bundleIdentifier() or "")
                        rpid = int(rapp.processIdentifier())
                        alive_pids.add(rpid)
                        if bid == "com.apple.dock":
                            dock_pid = rpid
                            continue
                        if rpid in only_vdisp_pids and int(rapp.activationPolicy()) == 0:
                            lname = str(rapp.localizedName() or "").strip().lower()
                            if lname:
                                vdisp_name_map[lname] = rpid
                            if bid:
                                vdisp_name_map[bid.strip().lower()] = rpid
                            burl = rapp.bundleURL()
                            if burl is not None:
                                bpath = str(burl.path() or "")
                                bstem = Path(bpath).stem.strip().lower()
                                if bstem:
                                    vdisp_name_map[bstem] = rpid
                    except Exception:
                        continue
                self._vdisp_seen_pids &= alive_pids
                self._min_vdisp_pids &= alive_pids
                self._vdisp_only_apps = vdisp_name_map

            if custom_dock_drifted:
                self._pin_custom_dock_to_main(q)

            # 2. Đọc tọa độ các icon trên CẢ Dock gốc macOS LẪN SmartRightDock/Docky (cache trong RAM)
            if (dock_pid <= 0 and custom_dock_pid <= 0) or not self._vdisp_only_apps:
                self._dock_icons = []
                return

            s_wins = _cfstr("AXWindows")
            s_ch = _cfstr("AXChildren")
            s_role = _cfstr("AXRole")
            s_sub = _cfstr("AXSubrole")
            s_title = _cfstr("AXTitle")
            s_desc = _cfstr("AXDescription")
            s_help = _cfstr("AXHelp")
            s_ident = _cfstr("AXIdentifier")
            s_pos = _cfstr("AXPosition")
            s_size = _cfstr("AXSize")
            new_icons = []

            def _match_vdisp_label(*labels: str) -> str:
                for raw in labels:
                    s = (raw or "").strip().lower()
                    if not s:
                        continue
                    if s in self._vdisp_only_apps:
                        return s
                for raw in labels:
                    s = (raw or "").strip().lower()
                    if len(s) < 3:
                        continue
                    for k in self._vdisp_only_apps:
                        if len(k) >= 4 and (k in s or s in k):
                            return k
                return ""

            def _get_ax_str(el_ref: Any, attr_ref: Any) -> str:
                r = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(el_ref, attr_ref, ctypes.byref(r)) == 0 and r.value:
                    val = _cf_to_py(r.value)
                    cf.CFRelease(r.value)
                    return val
                return ""

            def _get_ax_rect(el_ref: Any) -> Optional[Tuple[float, float, float, float]]:
                p_ref = ctypes.c_void_p()
                sz_ref = ctypes.c_void_p()
                ok_all = False
                pt = _CGPoint()
                sz = _CGSize()
                if (
                    ax.AXUIElementCopyAttributeValue(el_ref, s_pos, ctypes.byref(p_ref)) == 0
                    and p_ref.value
                    and ax.AXUIElementCopyAttributeValue(el_ref, s_size, ctypes.byref(sz_ref)) == 0
                    and sz_ref.value
                ):
                    ok_all = bool(
                        ax.AXValueGetValue(p_ref.value, 1, ctypes.byref(pt))
                        and ax.AXValueGetValue(sz_ref.value, 2, ctypes.byref(sz))
                    )
                if p_ref.value:
                    cf.CFRelease(p_ref.value)
                if sz_ref.value:
                    cf.CFRelease(sz_ref.value)
                if ok_all and sz.w > 8 and sz.h > 8:
                    return (pt.x, pt.y, sz.w, sz.h)
                return None

            try:
                # 2A. Quét Dock gốc macOS (com.apple.dock)
                if dock_pid > 0:
                    dock_ax = ax.AXUIElementCreateApplication(dock_pid)
                    if dock_ax:
                        try:
                            ch_ref = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(dock_ax, s_ch, ctypes.byref(ch_ref)) == 0 and ch_ref.value:
                                try:
                                    n_top = cf.CFArrayGetCount(ch_ref.value)
                                    for i in range(n_top):
                                        el = cf.CFArrayGetValueAtIndex(ch_ref.value, i)
                                        if not el or _get_ax_str(el, s_role) != "AXList":
                                            continue
                                        items_ref = ctypes.c_void_p()
                                        if ax.AXUIElementCopyAttributeValue(el, s_ch, ctypes.byref(items_ref)) != 0 or not items_ref.value:
                                            continue
                                        try:
                                            n_items = cf.CFArrayGetCount(items_ref.value)
                                            for j in range(n_items):
                                                item = cf.CFArrayGetValueAtIndex(items_ref.value, j)
                                                if not item or _get_ax_str(item, s_sub) != "AXApplicationDockItem":
                                                    continue
                                                mkey = _match_vdisp_label(_get_ax_str(item, s_title))
                                                if not mkey:
                                                    continue
                                                rc = _get_ax_rect(item)
                                                if rc:
                                                    new_icons.append((rc[0], rc[1], rc[2], rc[3], mkey))
                                        finally:
                                            cf.CFRelease(items_ref.value)
                                finally:
                                    cf.CFRelease(ch_ref.value)
                        finally:
                            cf.CFRelease(dock_ax)

                # 2B. Quét thanh Dock dọc bên phải (SmartRightDock / AlwaysDock / Docky)
                if custom_dock_pid > 0:
                    cd_ax = ax.AXUIElementCreateApplication(custom_dock_pid)
                    if cd_ax:
                        try:
                            def _walk_custom_dock(el_ref: Any, depth: int = 0) -> None:
                                if not el_ref or depth > 5:
                                    return
                                if depth > 0:
                                    mkey = _match_vdisp_label(
                                        _get_ax_str(el_ref, s_title),
                                        _get_ax_str(el_ref, s_desc),
                                        _get_ax_str(el_ref, s_help),
                                        _get_ax_str(el_ref, s_ident),
                                    )
                                    if mkey:
                                        rc = _get_ax_rect(el_ref)
                                        if rc and 14.0 <= rc[2] <= 96.0 and 14.0 <= rc[3] <= 96.0:
                                            new_icons.append((rc[0], rc[1], rc[2], rc[3], mkey))
                                            return
                                ch_r = ctypes.c_void_p()
                                if ax.AXUIElementCopyAttributeValue(el_ref, s_ch, ctypes.byref(ch_r)) == 0 and ch_r.value:
                                    try:
                                        cnt_c = cf.CFArrayGetCount(ch_r.value)
                                        for k in range(min(40, cnt_c)):
                                            _walk_custom_dock(cf.CFArrayGetValueAtIndex(ch_r.value, k), depth + 1)
                                    finally:
                                        cf.CFRelease(ch_r.value)

                            wr = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(cd_ax, s_wins, ctypes.byref(wr)) == 0 and wr.value:
                                try:
                                    for wi in range(min(4, cf.CFArrayGetCount(wr.value))):
                                        _walk_custom_dock(cf.CFArrayGetValueAtIndex(wr.value, wi), 0)
                                finally:
                                    cf.CFRelease(wr.value)
                        finally:
                            cf.CFRelease(cd_ax)
            finally:
                for s_ref in (s_wins, s_ch, s_role, s_sub, s_title, s_desc, s_help, s_ident, s_pos, s_size):
                    if s_ref:
                        cf.CFRelease(s_ref)
            self._dock_icons = new_icons
        except Exception:
            pass

    def _start_dock_interceptor(self) -> None:
        if not IS_MACOS:
            return
        self._stop_dock_interceptor()
        self._tap_gen += 1
        my_gen = self._tap_gen
        wake_evt = threading.Event()
        main_sz = [1512.0, 982.0]

        def _cache_worker() -> None:
            while self._tap_gen == my_gen and self.is_active():
                self._refresh_dock_intercept_cache()
                try:
                    import Quartz as q  # type: ignore

                    mb = q.CGDisplayBounds(q.CGMainDisplayID())
                    if mb.size.width >= 640 and mb.size.height >= 400:
                        main_sz[0] = float(mb.size.width)
                        main_sz[1] = float(mb.size.height)
                except Exception:
                    pass
                wake_evt.wait(timeout=0.35)
                wake_evt.clear()

        def _tap_worker() -> None:
            try:
                import Quartz as q  # type: ignore

                tap_holder: list = [None]
                swallow_up_until = [0.0]
                last_edge_wake = [0.0]

                def _cb(_proxy, event_type, event, _refcon):
                    try:
                        if event_type in (q.kCGEventTapDisabledByTimeout, q.kCGEventTapDisabledByUserInput):
                            if tap_holder[0] is not None:
                                q.CGEventTapEnable(tap_holder[0], True)
                            return event
                        if int(q.CGEventGetIntegerValueField(event, q.kCGEventSourceUserData)) == 0x4D4B4231:
                            return event

                        if event_type == q.kCGEventMouseMoved:
                            loc = q.CGEventGetLocation(event)
                            mx, my = float(loc.x), float(loc.y)
                            # 1. Chống Dock macOS (khi đặt đáy) nhảy từ MacBook sang Màn phụ #2
                            b = self._vdisp_bounds_cache
                            if b and not self._vdisp_has_fullscreen:
                                bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]
                                if (bx <= mx < bx + bw) and (my >= by + bh - 4.0):
                                    q.CGEventSetLocation(event, (mx, by + bh - 5.0))
                                    return event
                            # 2. Khi chuột tiến sát vùng Dock MacBook (kể cả lúc bật tự ẩn autohide=1) -> làm mới tọa độ icon tức thì!
                            mw, mh = main_sz[0], main_sz[1]
                            if (0.0 <= mx <= mw) and (0.0 <= my <= mh):
                                if my >= mh - 95.0 or mx >= mw - 95.0 or mx <= 95.0:
                                    now_t = time.monotonic()
                                    if (now_t - last_edge_wake[0]) >= 0.09:
                                        last_edge_wake[0] = now_t
                                        wake_evt.set()
                            return event

                        if event_type == q.kCGEventLeftMouseUp:
                            if swallow_up_until[0] > time.monotonic():
                                swallow_up_until[0] = 0.0
                                return None
                            return event

                        if event_type == q.kCGEventLeftMouseDown:
                            icons = self._dock_icons
                            if not icons:
                                return event
                            loc = q.CGEventGetLocation(event)
                            mx, my = float(loc.x), float(loc.y)
                            for rx, ry, rw, rh, title_s in icons:
                                if (rx - 4.0 <= mx <= rx + rw + 4.0) and (ry - 4.0 <= my <= ry + rh + 4.0):
                                    tpid = self._vdisp_only_apps.get(title_s, 0)
                                    if tpid > 0:
                                        swallow_up_until[0] = time.monotonic() + 0.5
                                        threading.Thread(
                                            target=self._toggle_vdisp_app_from_mac_dock,
                                            args=(tpid,),
                                            daemon=True,
                                        ).start()
                                        return None
                                    break
                        return event
                    except Exception:
                        return event

                mask = (
                    (1 << int(q.kCGEventLeftMouseDown))
                    | (1 << int(q.kCGEventLeftMouseUp))
                    | (1 << int(q.kCGEventMouseMoved))
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
                    return
                tap_holder[0] = tap
                src = q.CFMachPortCreateRunLoopSource(None, tap, 0)
                loop_ref = q.CFRunLoopGetCurrent()
                if self._tap_gen == my_gen:
                    self._tap_loop_ref = loop_ref
                q.CFRunLoopAddSource(loop_ref, src, q.kCFRunLoopCommonModes)
                q.CGEventTapEnable(tap, True)
                q.CFRunLoopRun()
                try:
                    q.CGEventTapEnable(tap, False)
                except Exception:
                    pass
            except Exception:
                pass

        threading.Thread(target=_cache_worker, daemon=True).start()
        threading.Thread(target=_tap_worker, daemon=True).start()

    def _stop_dock_interceptor(self) -> None:
        self._tap_gen += 1
        self._dock_icons = []
        self._vdisp_only_apps = {}
        self._min_vdisp_pids.clear()
        self._vdisp_seen_pids.clear()
        self._vdisp_bounds_cache = None
        self._vdisp_has_fullscreen = False
        loop_ref = self._tap_loop_ref
        self._tap_loop_ref = None
        if loop_ref is not None and IS_MACOS:
            try:
                import Quartz as q  # type: ignore

                q.CFRunLoopStop(loop_ref)
            except Exception:
                pass

    def rescue_windows_to_main_display(self, quartz: Any = None) -> int:
        """Kéo toàn bộ cửa sổ đang nằm ngoài màn chính MacBook (x < 0 hoặc lạc ngoài vùng hiển thị)
        về giữa màn chính MacBook để không bao giờ xảy ra tình trạng bật app mà không thấy đâu."""
        if not IS_MACOS or not self._init_ax_libs():
            return 0
        try:
            q = quartz
            if q is None:
                import Quartz as q  # type: ignore
            import AppKit  # type: ignore

            mb = q.CGDisplayBounds(q.CGMainDisplayID())
            mw = max(800.0, float(mb.size.width))
            mh = max(600.0, float(mb.size.height))
            ax = self._ax_lib
            cf = self._cf_lib
            kCFStringEncodingUTF8 = 0x08000100

            def _cfstr(s: str) -> ctypes.c_void_p:
                return cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)

            s_wins = _cfstr("AXWindows")
            s_pos = _cfstr("AXPosition")
            s_size = _cfstr("AXSize")
            rescued = 0
            try:
                apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications() or []
                for rapp in apps:
                    try:
                        if int(rapp.activationPolicy()) != 0:
                            continue
                        pid = int(rapp.processIdentifier())
                        if pid <= 0 or pid == os.getpid():
                            continue
                    except Exception:
                        continue
                    app_ax = ax.AXUIElementCreateApplication(pid)
                    if not app_ax:
                        continue
                    try:
                        wins_ref = ctypes.c_void_p()
                        if (
                            ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wins_ref)) != 0
                            or not wins_ref.value
                        ):
                            continue
                        try:
                            cnt = cf.CFArrayGetCount(wins_ref.value)
                            for i in range(cnt):
                                w_ax = cf.CFArrayGetValueAtIndex(wins_ref.value, i)
                                if not w_ax:
                                    continue
                                pos_ref = ctypes.c_void_p()
                                size_ref = ctypes.c_void_p()
                                if (
                                    ax.AXUIElementCopyAttributeValue(w_ax, s_pos, ctypes.byref(pos_ref)) == 0
                                    and pos_ref.value
                                    and ax.AXUIElementCopyAttributeValue(w_ax, s_size, ctypes.byref(size_ref)) == 0
                                    and size_ref.value
                                ):
                                    pt = _CGPoint()
                                    sz = _CGSize()
                                    ok_p = ax.AXValueGetValue(pos_ref.value, 1, ctypes.byref(pt))
                                    ok_s = ax.AXValueGetValue(size_ref.value, 2, ctypes.byref(sz))
                                    cf.CFRelease(pos_ref.value)
                                    cf.CFRelease(size_ref.value)
                                    if ok_p and ok_s and sz.w >= 120 and sz.h >= 80:
                                        cx = pt.x + sz.w * 0.5
                                        cy = pt.y + sz.h * 0.5
                                        off_main = (cx < 0.0) or (cx >= mw) or (cy < 0.0) or (cy >= mh)
                                        if off_main:
                                            new_w = min(sz.w, mw - 80.0)
                                            new_h = min(sz.h, mh - 100.0)
                                            new_x = max(24.0, (mw - new_w) * 0.5)
                                            new_y = max(36.0, (mh - new_h) * 0.5)
                                            new_pt = _CGPoint(new_x, new_y)
                                            v_pt = ax.AXValueCreate(1, ctypes.byref(new_pt))
                                            if v_pt:
                                                ax.AXUIElementSetAttributeValue(w_ax, s_pos, v_pt)
                                                cf.CFRelease(v_pt)
                                            if new_w < sz.w - 4.0 or new_h < sz.h - 4.0:
                                                new_sz = _CGSize(new_w, new_h)
                                                v_sz = ax.AXValueCreate(2, ctypes.byref(new_sz))
                                                if v_sz:
                                                    ax.AXUIElementSetAttributeValue(w_ax, s_size, v_sz)
                                                    cf.CFRelease(v_sz)
                                            rescued += 1
                                else:
                                    if pos_ref.value:
                                        cf.CFRelease(pos_ref.value)
                                    if size_ref.value:
                                        cf.CFRelease(size_ref.value)
                        finally:
                            cf.CFRelease(wins_ref.value)
                    finally:
                        cf.CFRelease(app_ax)
            finally:
                for s_ref in (s_wins, s_pos, s_size):
                    if s_ref:
                        cf.CFRelease(s_ref)
            return rescued
        except Exception:
            return 0

    def _exit_rdp_fullscreen_before_stop(self) -> bool:
        """Nếu Microsoft Remote Desktop / Windows App đang ở Full-Screen khi người dùng tắt Màn phụ Mac,
        tự động thoát Full-Screen (AXFullScreen=False) để thu về cửa sổ thường trước khi hủy màn ảo."""
        if not IS_MACOS or not self._init_ax_libs():
            return False
        try:
            import AppKit  # type: ignore
            import objc  # type: ignore

            rdp_pid = 0
            with objc.autorelease_pool():
                apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications() or []
                for rapp in apps:
                    try:
                        bid = str(rapp.bundleIdentifier() or "").strip().lower()
                        lname = str(rapp.localizedName() or "").strip().lower()
                        if bid in ("com.microsoft.rdc.macos", "com.microsoft.rdc.osx.beta") or lname in (
                            "microsoft remote desktop",
                            "windows app",
                        ):
                            rdp_pid = int(rapp.processIdentifier())
                            break
                    except Exception:
                        continue
            if rdp_pid <= 0:
                return False

            ax = self._ax_lib
            cf = self._cf_lib
            kCFStringEncodingUTF8 = 0x08000100

            def _cfstr(s: str) -> ctypes.c_void_p:
                return cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)

            def _get_str(el_ref: Any, attr_ref: Any) -> str:
                r = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(el_ref, attr_ref, ctypes.byref(r)) == 0 and r.value:
                    try:
                        with objc.autorelease_pool():
                            return str(objc.objc_object(c_void_p=r.value) or "")
                    finally:
                        cf.CFRelease(r.value)
                return ""

            app_ax = ax.AXUIElementCreateApplication(rdp_pid)
            if not app_ax:
                return False

            s_wins = _cfstr("AXWindows")
            s_fs = _cfstr("AXFullScreen")
            s_menubar = _cfstr("AXMenuBar")
            s_children = _cfstr("AXChildren")
            s_title = _cfstr("AXTitle")
            s_press = _cfstr("AXPress")
            kFalse = ctypes.c_void_p.in_dll(cf, "kCFBooleanFalse").value
            exited_any = False
            try:
                wins_ref = ctypes.c_void_p()
                if ax.AXUIElementCopyAttributeValue(app_ax, s_wins, ctypes.byref(wins_ref)) == 0 and wins_ref.value:
                    try:
                        cnt = cf.CFArrayGetCount(wins_ref.value)
                        for i in range(cnt):
                            w_ax = cf.CFArrayGetValueAtIndex(wins_ref.value, i)
                            if not w_ax:
                                continue
                            fs_ref = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(w_ax, s_fs, ctypes.byref(fs_ref)) == 0 and fs_ref.value:
                                is_fs = bool(cf.CFBooleanGetValue(fs_ref.value))
                                cf.CFRelease(fs_ref.value)
                                if is_fs:
                                    if ax.AXUIElementSetAttributeValue(w_ax, s_fs, kFalse) == 0:
                                        exited_any = True
                    finally:
                        cf.CFRelease(wins_ref.value)

                # Fallback qua Menu Bar -> View/Window -> Exit Full Screen nếu phiên đang nằm ở Space nền
                if not exited_any:
                    mb_ref = ctypes.c_void_p()
                    if ax.AXUIElementCopyAttributeValue(app_ax, s_menubar, ctypes.byref(mb_ref)) == 0 and mb_ref.value:
                        try:
                            bars_ref = ctypes.c_void_p()
                            if ax.AXUIElementCopyAttributeValue(mb_ref.value, s_children, ctypes.byref(bars_ref)) == 0 and bars_ref.value:
                                try:
                                    n_bar = cf.CFArrayGetCount(bars_ref.value)
                                    for bi in range(n_bar):
                                        b_el = cf.CFArrayGetValueAtIndex(bars_ref.value, bi)
                                        if not b_el:
                                            continue
                                        bt = _get_str(b_el, s_title).strip().lower()
                                        if bt not in ("window", "view", "cửa sổ", "xem"):
                                            continue
                                        sub_arr = ctypes.c_void_p()
                                        if ax.AXUIElementCopyAttributeValue(b_el, s_children, ctypes.byref(sub_arr)) != 0 or not sub_arr.value:
                                            continue
                                        try:
                                            if cf.CFArrayGetCount(sub_arr.value) <= 0:
                                                continue
                                            m_el = cf.CFArrayGetValueAtIndex(sub_arr.value, 0)
                                            items_arr = ctypes.c_void_p()
                                            if m_el and ax.AXUIElementCopyAttributeValue(m_el, s_children, ctypes.byref(items_arr)) == 0 and items_arr.value:
                                                try:
                                                    n_it = cf.CFArrayGetCount(items_arr.value)
                                                    for mi in range(n_it):
                                                        it_el = cf.CFArrayGetValueAtIndex(items_arr.value, mi)
                                                        if not it_el:
                                                            continue
                                                        mt = _get_str(it_el, s_title).strip().lower()
                                                        if "exit full screen" in mt or "thoát khỏi toàn màn hình" in mt:
                                                            if ax.AXUIElementPerformAction(it_el, s_press) == 0:
                                                                exited_any = True
                                                                break
                                                finally:
                                                    cf.CFRelease(items_arr.value)
                                        finally:
                                            cf.CFRelease(sub_arr.value)
                                        if exited_any:
                                            break
                                finally:
                                    cf.CFRelease(bars_ref.value)
                        finally:
                            cf.CFRelease(mb_ref.value)
            finally:
                cf.CFRelease(app_ax)
                for s_ref in (s_wins, s_fs, s_menubar, s_children, s_title, s_press):
                    if s_ref:
                        cf.CFRelease(s_ref)

            if exited_any:
                time.sleep(0.55)
            return exited_any
        except Exception:
            return False

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            self._stop_dock_interceptor()
            # Nếu Microsoft Remote Desktop đang Full-Screen 2 màn -> tự thoát Full-Screen về cửa sổ thường trước khi hủy màn phụ!
            if self._display_id > 0:
                try:
                    self._exit_rdp_fullscreen_before_stop()
                except Exception:
                    pass
                # Trước khi hủy màn ảo, kéo toàn bộ cửa sổ đang ở màn phụ về màn chính MacBook để không bao giờ bị mất tích!
                try:
                    self.rescue_windows_to_main_display()
                except Exception:
                    pass
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
