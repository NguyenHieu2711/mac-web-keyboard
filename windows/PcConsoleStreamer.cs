using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

namespace MacWebKeyboard
{
    internal static class PcConsoleStreamer
    {
        private const int CONSOLE_LISTEN_PORT = 5052;
        private const int INPUT_MOUSE = 0;
        private const int INPUT_KEYBOARD = 1;

        private const uint MOUSEEVENTF_MOVE = 0x0001;
        private const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        private const uint MOUSEEVENTF_LEFTUP = 0x0004;
        private const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
        private const uint MOUSEEVENTF_RIGHTUP = 0x0010;
        private const uint MOUSEEVENTF_MIDDLEDOWN = 0x0020;
        private const uint MOUSEEVENTF_MIDDLEUP = 0x0040;
        private const uint MOUSEEVENTF_WHEEL = 0x0800;
        private const uint MOUSEEVENTF_HWHEEL = 0x1000;
        private const uint MOUSEEVENTF_VIRTUALDESK = 0x4000;
        private const uint MOUSEEVENTF_ABSOLUTE = 0x8000;

        private const uint KEYEVENTF_EXTENDEDKEY = 0x0001;
        private const uint KEYEVENTF_KEYUP = 0x0002;
        private const uint KEYEVENTF_UNICODE = 0x0004;

        private const uint PW_RENDERFULLCONTENT = 0x00000002;
        private const int DWMWA_EXTENDED_FRAME_BOUNDS = 9;
        private const int DWMWA_CLOAKED = 14;
        private const int GWL_EXSTYLE = -20;
        private const int WS_EX_TOOLWINDOW = 0x00000080;
        private const uint GW_OWNER = 4;
        private const int SW_SHOWNOACTIVATE = 4;
        private const int SW_RESTORE = 9;
        private const uint SWP_NOZORDER = 0x0004;
        private const uint SWP_NOACTIVATE = 0x0010;

        private static readonly object _pinLock = new object();
        private static IntPtr _pinnedHwnd = IntPtr.Zero;
        private static volatile int _pinVersion = 0;

        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
            public int Width { get { return Right - Left; } }
            public int Height { get { return Bottom - Top; } }
        }

        [DllImport("shcore.dll")]
        private static extern int SetProcessDpiAwareness(int value);

        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [DllImport("user32.dll")]
        private static extern int GetSystemMetrics(int nIndex);

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSQuerySessionInformationW(
            IntPtr hServer, uint sessionId, int infoClass, out IntPtr ppBuffer, out int pBytesReturned);

        [DllImport("wtsapi32.dll")]
        private static extern void WTSFreeMemory(IntPtr pMemory);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

        [DllImport("user32.dll")]
        private static extern uint MapVirtualKeyW(uint uCode, uint uMapType);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool IsWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsIconic(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsZoomed(IntPtr hWnd);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowTextLengthW(IntPtr hWnd);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowTextW(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetClassNameW(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

        [DllImport("user32.dll")]
        private static extern int GetWindowLongW(IntPtr hWnd, int nIndex);

        [DllImport("user32.dll")]
        private static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

        [DllImport("user32.dll")]
        private static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        private static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll")]
        private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        [DllImport("user32.dll")]
        private static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);

        [DllImport("user32.dll")]
        private static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);

        [DllImport("kernel32.dll")]
        private static extern uint GetCurrentThreadId();

        [DllImport("dwmapi.dll")]
        private static extern int DwmGetWindowAttribute(IntPtr hwnd, int dwAttribute, out RECT pvAttribute, int cbAttribute);

        [DllImport("dwmapi.dll")]
        private static extern int DwmGetWindowAttribute(IntPtr hwnd, int dwAttribute, out int pvAttribute, int cbAttribute);

        [StructLayout(LayoutKind.Sequential)]
        private struct INPUT
        {
            public int type;
            public InputUnion U;
        }

        [StructLayout(LayoutKind.Explicit)]
        private struct InputUnion
        {
            [FieldOffset(0)] public MOUSEINPUT mi;
            [FieldOffset(0)] public KEYBDINPUT ki;
            [FieldOffset(0)] public HARDWAREINPUT hi;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct MOUSEINPUT
        {
            public int dx;
            public int dy;
            public uint mouseData;
            public uint dwFlags;
            public uint time;
            public IntPtr dwExtraInfo;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct KEYBDINPUT
        {
            public ushort wVk;
            public ushort wScan;
            public uint dwFlags;
            public uint time;
            public IntPtr dwExtraInfo;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct HARDWAREINPUT
        {
            public uint uMsg;
            public ushort wParamL;
            public ushort wParamH;
        }

        private static ImageCodecInfo _jpegCodec;
        private static EncoderParameters _jpegParams;
        private static readonly Dictionary<string, ushort> _vkMap = BuildVkMap();

        private static Dictionary<string, ushort> BuildVkMap()
        {
            var m = new Dictionary<string, ushort>(StringComparer.OrdinalIgnoreCase)
            {
                {"esc", 0x1B}, {"escape", 0x1B},
                {"tab", 0x09},
                {"backspace", 0x08}, {"bs", 0x08},
                {"enter", 0x0D}, {"return", 0x0D},
                {"space", 0x20}, {" ", 0x20},
                {"delete", 0x2E}, {"del", 0x2E},
                {"insert", 0x2D}, {"ins", 0x2D},
                {"home", 0x24}, {"end", 0x23},
                {"pageup", 0x21}, {"pagedown", 0x22},
                {"up", 0x26}, {"arrowup", 0x26},
                {"down", 0x28}, {"arrowdown", 0x28},
                {"left", 0x25}, {"arrowleft", 0x25},
                {"right", 0x27}, {"arrowright", 0x27},
                {"ctrl", 0x11}, {"control", 0x11},
                {"shift", 0x10},
                {"alt", 0x12}, {"option", 0x12},
                {"cmd", 0x5B}, {"win", 0x5B}, {"meta", 0x5B}, {"super", 0x5B},
                {"capslock", 0x14},
                {"-", 0xBD}, {"=", 0xBB}, {"[", 0xDB}, {"]", 0xDD}, {"\\", 0xDC},
                {";", 0xBA}, {"'", 0xDE}, {",", 0xBC}, {".", 0xBE}, {"/", 0xBF}, {"`", 0xC0},
            };
            for (char c = 'a'; c <= 'z'; c++) m[c.ToString()] = (ushort)('A' + (c - 'a'));
            for (char c = '0'; c <= '9'; c++) m[c.ToString()] = (ushort)c;
            for (int i = 1; i <= 12; i++) m["f" + i] = (ushort)(0x6F + i);
            return m;
        }

        private static bool IsExtendedVk(ushort vk)
        {
            return vk == 0x21 || vk == 0x22 || vk == 0x23 || vk == 0x24 ||
                   vk == 0x25 || vk == 0x26 || vk == 0x27 || vk == 0x28 ||
                   vk == 0x2D || vk == 0x2E || vk == 0x5B || vk == 0x5C;
        }

        private static void InitDpiAndCodec()
        {
            try { SetProcessDpiAwareness(2); }
            catch
            {
                try { SetProcessDPIAware(); } catch { }
            }

            foreach (ImageCodecInfo codec in ImageCodecInfo.GetImageEncoders())
            {
                if (string.Equals(codec.MimeType, "image/jpeg", StringComparison.OrdinalIgnoreCase))
                {
                    _jpegCodec = codec;
                    break;
                }
            }
            _jpegParams = new EncoderParameters(1);
            _jpegParams.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 74L);
        }

        private static string JsonEscape(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            var sb = new StringBuilder(s.Length + 16);
            foreach (char c in s)
            {
                if (c == '\\') sb.Append("\\\\");
                else if (c == '"') sb.Append("\\\"");
                else if (c == '\r' || c == '\n' || c == '\t') sb.Append(' ');
                else if (c < 0x20) continue;
                else sb.Append(c);
            }
            return sb.ToString();
        }

        private static bool IsSessionActiveAndUnlocked()
        {
            try
            {
                uint mySid = (uint)Process.GetCurrentProcess().SessionId;
                IntPtr buf;
                int bytes;
                int connState = -1;
                // WTSConnectState = 8 -> 0 (WTSActive) đúng cho cả PC trực tiếp lẫn khi MacBook đang RDP vào Session 1
                if (WTSQuerySessionInformationW(IntPtr.Zero, mySid, 8, out buf, out bytes) && buf != IntPtr.Zero)
                {
                    connState = Marshal.ReadInt32(buf);
                    WTSFreeMemory(buf);
                }
                if (connState != 0) return false;

                int unlockFlag = 1;
                if (WTSQuerySessionInformationW(IntPtr.Zero, mySid, 25, out buf, out bytes) && buf != IntPtr.Zero)
                {
                    if (bytes >= 20) unlockFlag = Marshal.ReadInt32(buf, 16);
                    WTSFreeMemory(buf);
                }
                // 0 = LOCKED, 1 = UNLOCKED, -1 (0xFFFFFFFF) = UNKNOWN (thường gặp trên RDP đang mở khóa)
                return unlockFlag != 0;
            }
            catch
            {
                return false;
            }
        }

        private static bool CanCaptureInteractiveDesktop()
        {
            try
            {
                using (var test = new Bitmap(2, 2, PixelFormat.Format24bppRgb))
                using (var g = Graphics.FromImage(test))
                {
                    g.CopyFromScreen(0, 0, 0, 0, new Size(2, 2), CopyPixelOperation.SourceCopy);
                }
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static Size GetPrimaryScreenSize()
        {
            int w = GetSystemMetrics(0);
            int h = GetSystemMetrics(1);
            if (w <= 0 || h <= 0)
            {
                Rectangle b = Screen.PrimaryScreen.Bounds;
                w = b.Width;
                h = b.Height;
            }
            return new Size(Math.Max(320, w), Math.Max(240, h));
        }

        private static bool GetVisibleWindowRect(IntPtr hwnd, out RECT visRect)
        {
            if (DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, out visRect, Marshal.SizeOf(typeof(RECT))) == 0 &&
                visRect.Width > 0 && visRect.Height > 0)
            {
                return true;
            }
            return GetWindowRect(hwnd, out visRect) && visRect.Width > 0 && visRect.Height > 0;
        }

        private static string GetWindowTitleSafe(IntPtr hwnd)
        {
            if (hwnd == IntPtr.Zero || !IsWindow(hwnd)) return "";
            int len = GetWindowTextLengthW(hwnd);
            if (len <= 0) return "";
            var sb = new StringBuilder(Math.Min(len + 1, 260));
            GetWindowTextW(hwnd, sb, sb.Capacity);
            return sb.ToString().Trim();
        }

        private static string GetFriendlyProcName(IntPtr hwnd)
        {
            try
            {
                uint pid = 0;
                GetWindowThreadProcessId(hwnd, out pid);
                if (pid == 0) return "";
                using (Process p = Process.GetProcessById((int)pid))
                {
                    string n = (p.ProcessName ?? "").Trim();
                    string low = n.ToLowerInvariant();
                    if (low == "msedge") return "Edge";
                    if (low == "chrome") return "Chrome";
                    if (low == "firefox") return "Firefox";
                    if (low == "code") return "VS Code";
                    if (low == "explorer") return "Explorer";
                    if (low == "obsidian") return "Obsidian";
                    if (low == "antigravity") return "Antigravity";
                    if (low == "zalo") return "Zalo";
                    if (low == "discord") return "Discord";
                    return n;
                }
            }
            catch
            {
                return "";
            }
        }

        private static bool IsCloakedWindow(IntPtr hwnd)
        {
            try
            {
                int cloaked = 0;
                if (DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, out cloaked, sizeof(int)) == 0 && cloaked != 0)
                    return true;
            }
            catch { }
            return false;
        }

        private static string EnumOpenWindowsJson()
        {
            IntPtr fg = GetForegroundWindow();
            IntPtr pinned;
            lock (_pinLock) { pinned = _pinnedHwnd; }
            if (pinned != IntPtr.Zero && !IsWindow(pinned))
            {
                lock (_pinLock) { _pinnedHwnd = IntPtr.Zero; pinned = IntPtr.Zero; }
            }

            var items = new List<string>();
            int myPid = Process.GetCurrentProcess().Id;

            EnumWindows((hwnd, lParam) =>
            {
                try
                {
                    if (!IsWindowVisible(hwnd)) return true;
                    if (IsCloakedWindow(hwnd)) return true;
                    int exStyle = GetWindowLongW(hwnd, GWL_EXSTYLE);
                    if ((exStyle & WS_EX_TOOLWINDOW) != 0) return true;
                    if (GetWindow(hwnd, GW_OWNER) != IntPtr.Zero) return true;

                    uint pid = 0;
                    GetWindowThreadProcessId(hwnd, out pid);
                    if ((int)pid == myPid) return true;

                    string title = GetWindowTitleSafe(hwnd);
                    if (string.IsNullOrEmpty(title)) return true;

                    var clsSb = new StringBuilder(128);
                    GetClassNameW(hwnd, clsSb, clsSb.Capacity);
                    string cls = clsSb.ToString();
                    if (cls == "Progman" || cls == "WorkerW" || cls == "Shell_TrayWnd" ||
                        cls == "Shell_SecondaryTrayWnd" || cls == "Windows.UI.Core.CoreWindow")
                        return true;

                    bool minimized = IsIconic(hwnd);
                    RECT r;
                    GetVisibleWindowRect(hwnd, out r);
                    if (!minimized && (r.Width < 180 || r.Height < 120)) return true;

                    string proc = GetFriendlyProcName(hwnd);
                    long hid = hwnd.ToInt64();
                    items.Add(
                        "{\"hwnd\":" + hid +
                        ",\"title\":\"" + JsonEscape(title) + "\"" +
                        ",\"proc\":\"" + JsonEscape(proc) + "\"" +
                        ",\"w\":" + Math.Max(0, r.Width) +
                        ",\"h\":" + Math.Max(0, r.Height) +
                        ",\"minimized\":" + (minimized ? "true" : "false") +
                        ",\"active\":" + (hwnd == fg ? "true" : "false") + "}"
                    );
                }
                catch { }
                return items.Count < 32;
            }, IntPtr.Zero);

            string pinnedTitle = pinned != IntPtr.Zero ? GetWindowTitleSafe(pinned) : "";
            string pinnedProc = pinned != IntPtr.Zero ? GetFriendlyProcName(pinned) : "";
            return "{\"ok\":true,\"pinned\":" + pinned.ToInt64() +
                   ",\"pinned_title\":\"" + JsonEscape(pinnedTitle) + "\"" +
                   ",\"pinned_proc\":\"" + JsonEscape(pinnedProc) + "\"" +
                   ",\"windows\":[" + string.Join(",", items.ToArray()) + "]}\n";
        }

        private static void FitWindowToPhoneAspect(IntPtr hwnd)
        {
            if (hwnd == IntPtr.Zero || !IsWindow(hwnd)) return;
            try
            {
                if (IsIconic(hwnd))
                {
                    ShowWindow(hwnd, SW_SHOWNOACTIVATE);
                    Thread.Sleep(60);
                }
                if (IsZoomed(hwnd))
                {
                    ShowWindow(hwnd, SW_RESTORE);
                    Thread.Sleep(60);
                }

                RECT winR, visR;
                if (!GetWindowRect(hwnd, out winR)) return;
                if (!GetVisibleWindowRect(hwnd, out visR)) visR = winR;

                int padL = Math.Max(0, visR.Left - winR.Left);
                int padT = Math.Max(0, visR.Top - winR.Top);
                int padR = Math.Max(0, winR.Right - visR.Right);
                int padB = Math.Max(0, winR.Bottom - visR.Bottom);

                Rectangle wa = Screen.FromHandle(hwnd).WorkingArea;
                if (wa.Width < 320 || wa.Height < 240) wa = Screen.PrimaryScreen.WorkingArea;

                const double PHONE_RATIO = 2248.0 / 1080.0;
                int targetVisW = Math.Min(wa.Width, 2248);
                int targetVisH = (int)Math.Round(targetVisW / PHONE_RATIO);
                if (targetVisH > wa.Height)
                {
                    targetVisH = wa.Height;
                    targetVisW = (int)Math.Round(targetVisH * PHONE_RATIO);
                }
                targetVisW = Math.Max(640, targetVisW & ~1);
                targetVisH = Math.Max(308, targetVisH & ~1);

                int finalW = targetVisW + padL + padR;
                int finalH = targetVisH + padT + padB;
                int finalX = wa.Left + Math.Max(0, (wa.Width - targetVisW) / 2) - padL;
                int finalY = wa.Top + Math.Max(0, (wa.Height - targetVisH) / 2) - padT;

                SetWindowPos(hwnd, IntPtr.Zero, finalX, finalY, finalW, finalH, SWP_NOZORDER | SWP_NOACTIVATE);
            }
            catch { }
        }

        private static string SetPinnedWindow(long hwndVal, bool fitPhone)
        {
            IntPtr next = IntPtr.Zero;
            if (hwndVal > 0)
            {
                IntPtr cand = new IntPtr(hwndVal);
                if (IsWindow(cand))
                {
                    next = cand;
                    if (fitPhone) FitWindowToPhoneAspect(cand);
                }
            }
            lock (_pinLock)
            {
                _pinnedHwnd = next;
                _pinVersion++;
            }
            string title = next != IntPtr.Zero ? GetWindowTitleSafe(next) : "";
            string proc = next != IntPtr.Zero ? GetFriendlyProcName(next) : "";
            return "{\"type\":\"pin_state\",\"hwnd\":" + next.ToInt64() +
                   ",\"title\":\"" + JsonEscape(title) + "\"" +
                   ",\"proc\":\"" + JsonEscape(proc) + "\"}";
        }

        private static void BringPinnedToFrontForInput(IntPtr hwnd)
        {
            if (hwnd == IntPtr.Zero || !IsWindow(hwnd)) return;
            try
            {
                if (IsIconic(hwnd))
                {
                    ShowWindow(hwnd, SW_RESTORE);
                    Thread.Sleep(30);
                }
                IntPtr fg = GetForegroundWindow();
                if (fg == hwnd) return;

                uint curTid = GetCurrentThreadId();
                uint fgPid;
                uint fgTid = fg != IntPtr.Zero ? GetWindowThreadProcessId(fg, out fgPid) : 0;
                bool attached = false;
                if (fgTid != 0 && fgTid != curTid)
                {
                    attached = AttachThreadInput(curTid, fgTid, true);
                }
                try
                {
                    SetForegroundWindow(hwnd);
                }
                finally
                {
                    if (attached) AttachThreadInput(curTid, fgTid, false);
                }
                Thread.Sleep(25);
            }
            catch { }
        }

        private static byte[] EncodeBitmapJpeg(Bitmap rawBmp, out int outW, out int outH, out ulong sig)
        {
            int sw = rawBmp.Width;
            int sh = rawBmp.Height;
            int tw = sw;
            int th = sh;
            if (sw > 2560)
            {
                tw = 2560;
                th = Math.Max(1, (int)Math.Round(sh * 2560.0 / sw));
            }

            Bitmap targetBmp = rawBmp;
            Bitmap resized = null;
            try
            {
                if (tw != sw || th != sh || rawBmp.PixelFormat != PixelFormat.Format24bppRgb)
                {
                    resized = new Bitmap(tw, th, PixelFormat.Format24bppRgb);
                    using (var gr = Graphics.FromImage(resized))
                    {
                        gr.InterpolationMode = InterpolationMode.HighQualityBilinear;
                        gr.DrawImage(rawBmp, 0, 0, tw, th);
                    }
                    targetBmp = resized;
                }

                ulong hash = 14695981039346656037UL;
                BitmapData bd = targetBmp.LockBits(
                    new Rectangle(0, 0, tw, th), ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
                try
                {
                    int stride = Math.Abs(bd.Stride);
                    int stepY = Math.Max(1, th / 16);
                    int stepX = Math.Max(1, tw / 16);
                    byte[] rowBuf = new byte[stride];
                    for (int y = stepY / 2; y < th; y += stepY)
                    {
                        Marshal.Copy(IntPtr.Add(bd.Scan0, y * bd.Stride), rowBuf, 0, stride);
                        for (int x = stepX / 2; x < tw; x += stepX)
                        {
                            int off = x * 3;
                            if (off + 2 < stride)
                            {
                                hash ^= rowBuf[off]; hash *= 1099511628211UL;
                                hash ^= rowBuf[off + 1]; hash *= 1099511628211UL;
                                hash ^= rowBuf[off + 2]; hash *= 1099511628211UL;
                            }
                        }
                    }
                }
                finally
                {
                    targetBmp.UnlockBits(bd);
                }
                sig = hash;
                outW = tw;
                outH = th;

                using (var ms = new MemoryStream(163840))
                {
                    if (_jpegCodec != null)
                        targetBmp.Save(ms, _jpegCodec, _jpegParams);
                    else
                        targetBmp.Save(ms, ImageFormat.Jpeg);
                    return ms.ToArray();
                }
            }
            finally
            {
                if (resized != null) resized.Dispose();
            }
        }

        private static byte[] CapturePinnedWindowFrame(IntPtr hwnd, out int outW, out int outH, out ulong sig)
        {
            outW = 0;
            outH = 0;
            sig = 0;
            if (IsIconic(hwnd)) return null;

            RECT winR, visR;
            if (!GetWindowRect(hwnd, out winR) || winR.Width < 32 || winR.Height < 32) return null;
            if (!GetVisibleWindowRect(hwnd, out visR)) visR = winR;

            int cropX = Math.Max(0, Math.Min(winR.Width - 1, visR.Left - winR.Left));
            int cropY = Math.Max(0, Math.Min(winR.Height - 1, visR.Top - winR.Top));
            int cropW = Math.Max(1, Math.Min(winR.Width - cropX, visR.Width));
            int cropH = Math.Max(1, Math.Min(winR.Height - cropY, visR.Height));

            using (var fullBmp = new Bitmap(winR.Width, winR.Height, PixelFormat.Format32bppArgb))
            {
                bool ok = false;
                using (var g = Graphics.FromImage(fullBmp))
                {
                    IntPtr hdc = g.GetHdc();
                    try
                    {
                        ok = PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT);
                        if (!ok) ok = PrintWindow(hwnd, hdc, 0);
                    }
                    finally
                    {
                        g.ReleaseHdc(hdc);
                    }
                }
                if (!ok) return null;

                using (var cropped = new Bitmap(cropW, cropH, PixelFormat.Format24bppRgb))
                {
                    using (var gc = Graphics.FromImage(cropped))
                    {
                        gc.DrawImage(fullBmp, new Rectangle(0, 0, cropW, cropH), new Rectangle(cropX, cropY, cropW, cropH), GraphicsUnit.Pixel);
                    }
                    return EncodeBitmapJpeg(cropped, out outW, out outH, out sig);
                }
            }
        }

        private static byte[] CaptureJpegFrame(out int outW, out int outH, out ulong sig, out bool pinnedClosed)
        {
            outW = 0;
            outH = 0;
            sig = 0;
            pinnedClosed = false;

            IntPtr pinned;
            lock (_pinLock) { pinned = _pinnedHwnd; }
            if (pinned != IntPtr.Zero)
            {
                if (!IsWindow(pinned))
                {
                    lock (_pinLock)
                    {
                        if (_pinnedHwnd == pinned) { _pinnedHwnd = IntPtr.Zero; _pinVersion++; }
                    }
                    pinnedClosed = true;
                }
                else
                {
                    return CapturePinnedWindowFrame(pinned, out outW, out outH, out sig);
                }
            }

            Size scr = GetPrimaryScreenSize();
            int sw = scr.Width;
            int sh = scr.Height;
            using (var rawBmp = new Bitmap(sw, sh, PixelFormat.Format24bppRgb))
            {
                using (var g = Graphics.FromImage(rawBmp))
                {
                    g.CopyFromScreen(0, 0, 0, 0, new Size(sw, sh), CopyPixelOperation.SourceCopy);
                }
                return EncodeBitmapJpeg(rawBmp, out outW, out outH, out sig);
            }
        }

        private static void SendMouseEvent(double rx, double ry, uint flags, uint mouseData, bool activatePinned)
        {
            double clampedX = Math.Max(0.0, Math.Min(1.0, rx));
            double clampedY = Math.Max(0.0, Math.Min(1.0, ry));

            IntPtr pinned;
            lock (_pinLock) { pinned = _pinnedHwnd; }

            int ax;
            int ay;
            uint finalFlags = flags;

            if (pinned != IntPtr.Zero && IsWindow(pinned))
            {
                if (activatePinned) BringPinnedToFrontForInput(pinned);
                RECT visR;
                if (GetVisibleWindowRect(pinned, out visR) && visR.Width > 0 && visR.Height > 0)
                {
                    double px = visR.Left + clampedX * visR.Width;
                    double py = visR.Top + clampedY * visR.Height;
                    int vx = GetSystemMetrics(76); // SM_XVIRTUALSCREEN
                    int vy = GetSystemMetrics(77); // SM_YVIRTUALSCREEN
                    int vw = Math.Max(1, GetSystemMetrics(78)); // SM_CXVIRTUALSCREEN
                    int vh = Math.Max(1, GetSystemMetrics(79)); // SM_CYVIRTUALSCREEN
                    ax = (int)Math.Round(Math.Max(0.0, Math.Min(1.0, (px - vx) / vw)) * 65535.0);
                    ay = (int)Math.Round(Math.Max(0.0, Math.Min(1.0, (py - vy) / vh)) * 65535.0);
                    finalFlags |= MOUSEEVENTF_VIRTUALDESK;
                }
                else
                {
                    ax = (int)Math.Round(clampedX * 65535.0);
                    ay = (int)Math.Round(clampedY * 65535.0);
                }
            }
            else
            {
                ax = (int)Math.Round(clampedX * 65535.0);
                ay = (int)Math.Round(clampedY * 65535.0);
            }

            var inp = new INPUT
            {
                type = INPUT_MOUSE,
                U = new InputUnion
                {
                    mi = new MOUSEINPUT
                    {
                        dx = ax,
                        dy = ay,
                        mouseData = mouseData,
                        dwFlags = finalFlags,
                        time = 0,
                        dwExtraInfo = IntPtr.Zero
                    }
                }
            };
            SendInput(1, new[] { inp }, Marshal.SizeOf(typeof(INPUT)));
        }

        private static void SendVk(ushort vk, bool isUp)
        {
            uint flags = isUp ? KEYEVENTF_KEYUP : 0;
            if (IsExtendedVk(vk)) flags |= KEYEVENTF_EXTENDEDKEY;
            ushort scan = (ushort)MapVirtualKeyW(vk, 0);
            var inp = new INPUT
            {
                type = INPUT_KEYBOARD,
                U = new InputUnion
                {
                    ki = new KEYBDINPUT
                    {
                        wVk = vk,
                        wScan = scan,
                        dwFlags = flags,
                        time = 0,
                        dwExtraInfo = IntPtr.Zero
                    }
                }
            };
            SendInput(1, new[] { inp }, Marshal.SizeOf(typeof(INPUT)));
        }

        private static void SendUnicodeString(string text)
        {
            if (string.IsNullOrEmpty(text)) return;
            var list = new List<INPUT>(text.Length * 2);
            foreach (char ch in text)
            {
                list.Add(new INPUT
                {
                    type = INPUT_KEYBOARD,
                    U = new InputUnion
                    {
                        ki = new KEYBDINPUT { wVk = 0, wScan = ch, dwFlags = KEYEVENTF_UNICODE }
                    }
                });
                list.Add(new INPUT
                {
                    type = INPUT_KEYBOARD,
                    U = new InputUnion
                    {
                        ki = new KEYBDINPUT { wVk = 0, wScan = ch, dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP }
                    }
                });
            }
            SendInput((uint)list.Count, list.ToArray(), Marshal.SizeOf(typeof(INPUT)));
        }

        private static string ExtractJsonString(string json, string key)
        {
            Match m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"((?:\\\\.|[^\"\\\\])*)\"");
            if (!m.Success) return "";
            try { return Regex.Unescape(m.Groups[1].Value); }
            catch { return m.Groups[1].Value; }
        }

        private static double ExtractJsonDouble(string json, string key, double defVal)
        {
            Match m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(-?[0-9]+(?:\\.[0-9]+)?)");
            double v;
            if (m.Success && double.TryParse(m.Groups[1].Value, System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out v))
            {
                return v;
            }
            return defVal;
        }

        private static int ExtractJsonInt(string json, string key, int defVal)
        {
            return (int)Math.Round(ExtractJsonDouble(json, key, defVal));
        }

        private static List<string> ExtractJsonStringArray(string json, string key)
        {
            var res = new List<string>();
            Match m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*\\[([^\\]]*)\\]");
            if (!m.Success) return res;
            foreach (Match item in Regex.Matches(m.Groups[1].Value, "\"((?:\\\\.|[^\"\\\\])*)\""))
            {
                res.Add(item.Groups[1].Value);
            }
            return res;
        }

        private static long ExtractJsonLong(string json, string key, long defVal)
        {
            Match m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(-?[0-9]+)");
            long v;
            if (m.Success && long.TryParse(m.Groups[1].Value, out v)) return v;
            return defVal;
        }

        private static bool ExtractJsonBool(string json, string key, bool defVal)
        {
            Match m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(true|false)", RegexOptions.IgnoreCase);
            if (!m.Success) return defVal;
            return string.Equals(m.Groups[1].Value, "true", StringComparison.OrdinalIgnoreCase);
        }

        private static void EnsurePinnedForegroundForKey()
        {
            IntPtr pinned;
            lock (_pinLock) { pinned = _pinnedHwnd; }
            if (pinned != IntPtr.Zero && IsWindow(pinned))
            {
                BringPinnedToFrontForInput(pinned);
            }
        }

        private static string DispatchInputJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json)) return null;
            string mtype = ExtractJsonString(json, "type");
            if (mtype == "pin_window")
            {
                long hwndVal = ExtractJsonLong(json, "hwnd", 0);
                bool fitPhone = ExtractJsonBool(json, "fit_phone", true);
                return SetPinnedWindow(hwndVal, fitPhone);
            }
            if (mtype == "ptr_move")
            {
                double rx = ExtractJsonDouble(json, "rx", 0.5);
                double ry = ExtractJsonDouble(json, "ry", 0.5);
                SendMouseEvent(rx, ry, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, false);
            }
            else if (mtype == "ptr_down" || mtype == "ptr_up")
            {
                double rx = ExtractJsonDouble(json, "rx", 0.5);
                double ry = ExtractJsonDouble(json, "ry", 0.5);
                int btn = ExtractJsonInt(json, "btn", 0);
                bool isDown = (mtype == "ptr_down");
                uint btnFlag;
                if (btn == 2) btnFlag = isDown ? MOUSEEVENTF_RIGHTDOWN : MOUSEEVENTF_RIGHTUP;
                else if (btn == 1) btnFlag = isDown ? MOUSEEVENTF_MIDDLEDOWN : MOUSEEVENTF_MIDDLEUP;
                else btnFlag = isDown ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP;
                SendMouseEvent(rx, ry, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | btnFlag, 0, isDown);
            }
            else if (mtype == "ptr_wheel")
            {
                double rx = ExtractJsonDouble(json, "rx", 0.5);
                double ry = ExtractJsonDouble(json, "ry", 0.5);
                double dx = ExtractJsonDouble(json, "dx", 0.0);
                double dy = ExtractJsonDouble(json, "dy", 0.0);
                SendMouseEvent(rx, ry, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, true);
                int wy = (int)Math.Round(dy * 3.0);
                int wx = (int)Math.Round(-dx * 3.0);
                if (wy != 0) SendMouseEvent(rx, ry, MOUSEEVENTF_WHEEL, unchecked((uint)wy), false);
                if (wx != 0) SendMouseEvent(rx, ry, MOUSEEVENTF_HWHEEL, unchecked((uint)wx), false);
            }
            else if (mtype == "key_tap")
            {
                EnsurePinnedForegroundForKey();
                string key = ExtractJsonString(json, "key");
                List<string> mods = ExtractJsonStringArray(json, "mods");
                var modVks = new List<ushort>();
                foreach (string mk in mods)
                {
                    ushort mvk;
                    if (_vkMap.TryGetValue(mk, out mvk)) modVks.Add(mvk);
                }
                ushort vk;
                if (_vkMap.TryGetValue(key, out vk))
                {
                    foreach (ushort mvk in modVks) SendVk(mvk, false);
                    SendVk(vk, false);
                    SendVk(vk, true);
                    for (int i = modVks.Count - 1; i >= 0; i--) SendVk(modVks[i], true);
                }
            }
            else if (mtype == "combo")
            {
                EnsurePinnedForegroundForKey();
                List<string> keys = ExtractJsonStringArray(json, "keys");
                var vks = new List<ushort>();
                foreach (string k in keys)
                {
                    ushort vk;
                    if (_vkMap.TryGetValue(k, out vk)) vks.Add(vk);
                }
                for (int i = 0; i < vks.Count; i++) SendVk(vks[i], false);
                for (int i = vks.Count - 1; i >= 0; i--) SendVk(vks[i], true);
            }
            else if (mtype == "unicode_text")
            {
                EnsurePinnedForegroundForKey();
                string txt = ExtractJsonString(json, "text");
                if (!string.IsNullOrEmpty(txt)) SendUnicodeString(txt);
            }
            return null;
        }

        private static void WriteFramed(Stream s, byte[] payload)
        {
            int len = payload.Length;
            byte[] hdr = new byte[4];
            hdr[0] = (byte)((len >> 24) & 0xFF);
            hdr[1] = (byte)((len >> 16) & 0xFF);
            hdr[2] = (byte)((len >> 8) & 0xFF);
            hdr[3] = (byte)(len & 0xFF);
            s.Write(hdr, 0, 4);
            s.Write(payload, 0, len);
            s.Flush();
        }

        private static void WriteControlJson(Stream ns, object writeLock, string json)
        {
            byte[] ctrl = Encoding.UTF8.GetBytes(json);
            byte[] pkt = new byte[1 + ctrl.Length];
            pkt[0] = 0x20;
            Buffer.BlockCopy(ctrl, 0, pkt, 1, ctrl.Length);
            lock (writeLock) { WriteFramed(ns, pkt); }
        }

        private static string CurrentPinStateJson()
        {
            IntPtr pinned;
            lock (_pinLock) { pinned = _pinnedHwnd; }
            if (pinned != IntPtr.Zero && !IsWindow(pinned))
            {
                lock (_pinLock) { _pinnedHwnd = IntPtr.Zero; pinned = IntPtr.Zero; }
            }
            string title = pinned != IntPtr.Zero ? GetWindowTitleSafe(pinned) : "";
            string proc = pinned != IntPtr.Zero ? GetFriendlyProcName(pinned) : "";
            return "{\"type\":\"pin_state\",\"hwnd\":" + pinned.ToInt64() +
                   ",\"title\":\"" + JsonEscape(title) + "\"" +
                   ",\"proc\":\"" + JsonEscape(proc) + "\"}";
        }

        private static void HandleClient(TcpClient client)
        {
            try
            {
                client.NoDelay = true;
                client.SendTimeout = 2000;
                using (NetworkStream ns = client.GetStream())
                using (var reader = new StreamReader(ns, Encoding.UTF8, false, 4096, true))
                {
                    string firstLine = reader.ReadLine();
                    if (firstLine == null) return;
                    string cmd = firstLine.Trim().ToUpperInvariant();

                    if (cmd == "PROBE")
                    {
                        bool active = IsSessionActiveAndUnlocked();
                        Size sz = GetPrimaryScreenSize();
                        IntPtr pinned;
                        lock (_pinLock) { pinned = _pinnedHwnd; }
                        if (pinned != IntPtr.Zero && IsWindow(pinned))
                        {
                            RECT pr;
                            if (GetVisibleWindowRect(pinned, out pr) && pr.Width > 0 && pr.Height > 0)
                            {
                                sz = new Size(pr.Width, pr.Height);
                            }
                        }
                        string reply = "{\"ok\":true,\"active\":" + (active ? "true" : "false") +
                                       ",\"pinned\":" + (pinned != IntPtr.Zero && IsWindow(pinned) ? pinned.ToInt64() : 0) +
                                       ",\"width\":" + sz.Width + ",\"height\":" + sz.Height + "}\n";
                        byte[] rb = Encoding.UTF8.GetBytes(reply);
                        ns.Write(rb, 0, rb.Length);
                        ns.Flush();
                        return;
                    }

                    if (cmd == "WINDOWS")
                    {
                        string reply = EnumOpenWindowsJson();
                        byte[] rb = Encoding.UTF8.GetBytes(reply);
                        ns.Write(rb, 0, rb.Length);
                        ns.Flush();
                        return;
                    }

                    if (cmd != "STREAM") return;

                    bool running = true;
                    object writeLock = new object();

                    try { WriteControlJson(ns, writeLock, CurrentPinStateJson()); } catch { }

                    var inputThread = new Thread(() =>
                    {
                        try
                        {
                            string line;
                            while (running && (line = reader.ReadLine()) != null)
                            {
                                try
                                {
                                    string ctrlReply = DispatchInputJson(line);
                                    if (!string.IsNullOrEmpty(ctrlReply))
                                    {
                                        WriteControlJson(ns, writeLock, ctrlReply);
                                    }
                                }
                                catch { }
                            }
                        }
                        catch { }
                        finally { running = false; }
                    });
                    inputThread.IsBackground = true;
                    inputThread.Start();

                    ulong prevSig = 0;
                    int lastPinVer = _pinVersion;
                    long lastSentTick = 0;
                    int lockedStreak = 0;

                    while (running)
                    {
                        if (!IsSessionActiveAndUnlocked())
                        {
                            lockedStreak++;
                            if (lockedStreak >= 12)
                            {
                                WriteControlJson(ns, writeLock, "{\"type\":\"parallel_ended\",\"reason\":\"console_locked\"}");
                                break;
                            }
                            Thread.Sleep(80);
                            continue;
                        }
                        lockedStreak = 0;

                        try
                        {
                            int curPinVer = _pinVersion;
                            if (curPinVer != lastPinVer)
                            {
                                lastPinVer = curPinVer;
                                prevSig = 0;
                            }
                            int fw, fh;
                            ulong sig;
                            bool pinnedClosed;
                            byte[] jpeg = CaptureJpegFrame(out fw, out fh, out sig, out pinnedClosed);
                            if (pinnedClosed)
                            {
                                prevSig = 0;
                                try { WriteControlJson(ns, writeLock, "{\"type\":\"pin_state\",\"hwnd\":0,\"title\":\"\",\"proc\":\"\"}"); } catch { }
                            }
                            long nowTick = Environment.TickCount;
                            bool changed = (sig != prevSig) || (unchecked(nowTick - lastSentTick) >= 1400);
                            if (jpeg != null && jpeg.Length > 0 && changed)
                            {
                                prevSig = sig;
                                lastSentTick = nowTick;
                                byte[] pkt = new byte[5 + jpeg.Length];
                                pkt[0] = 0x10;
                                pkt[1] = (byte)((fw >> 8) & 0xFF);
                                pkt[2] = (byte)(fw & 0xFF);
                                pkt[3] = (byte)((fh >> 8) & 0xFF);
                                pkt[4] = (byte)(fh & 0xFF);
                                Buffer.BlockCopy(jpeg, 0, pkt, 5, jpeg.Length);
                                lock (writeLock) { WriteFramed(ns, pkt); }
                            }
                        }
                        catch
                        {
                            if (!client.Connected) break;
                            Thread.Sleep(80);
                        }
                        Thread.Sleep(50);
                    }
                }
            }
            catch { }
            finally
            {
                try { client.Close(); } catch { }
            }
        }

        public static int Main()
        {
            InitDpiAndCodec();
            bool desktopReady = false;
            for (int attempt = 0; attempt < 12; attempt++)
            {
                if (CanCaptureInteractiveDesktop())
                {
                    desktopReady = true;
                    break;
                }
                Thread.Sleep(500);
            }
            if (!desktopReady)
            {
                return 2;
            }

            TcpListener listener = null;
            try
            {
                listener = new TcpListener(IPAddress.Loopback, CONSOLE_LISTEN_PORT);
                listener.Start();
            }
            catch
            {
                return 0;
            }

            while (true)
            {
                try
                {
                    TcpClient cli = listener.AcceptTcpClient();
                    var t = new Thread(() => HandleClient(cli));
                    t.IsBackground = true;
                    t.Start();
                }
                catch
                {
                    Thread.Sleep(200);
                }
            }
        }
    }
}
