using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

namespace MacWebKeyboard
{
    internal static class PcDisplayLayoutGuard
    {
        private const int GWL_EXSTYLE = -20;
        private const int WS_EX_TOOLWINDOW = 0x00000080;
        private const int WS_EX_NOACTIVATE = 0x08000000;
        private const uint GW_OWNER = 4;
        private const int DWMWA_CLOAKED = 14;

        private const int SW_RESTORE = 9;
        private const int SW_SHOWMAXIMIZED = 3;
        private const int SW_SHOWMINIMIZED = 2;
        private const int WPF_RESTORETOMAXIMIZED = 2;

        private const uint SWP_NOZORDER = 0x0004;
        private const uint SWP_NOACTIVATE = 0x0010;

        private static readonly HashSet<string> SkipClasses = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Progman",
            "WorkerW",
            "Shell_TrayWnd",
            "Shell_SecondaryTrayWnd",
            "NotifyIconOverflowWindow",
            "ForegroundStaging",
            "MultitaskingViewFrame",
            "XamlExplorerHostIslandWindow",
            "Windows.UI.Core.CoreWindow",
            "EdgeUiInputTopWndClass",
            "DummyDwmListenerWindow",
            "TaskListThumbnailWnd",
            "tooltips_class32",
        };

        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("shcore.dll")]
        private static extern int SetProcessDpiAwareness(int value);

        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr OpenDesktop(string lpszDesktop, uint dwFlags, bool fInherit, uint dwDesiredAccess);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool SetThreadDesktop(IntPtr hDesktop);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool IsWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsIconic(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsHungAppWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);

        [DllImport("user32.dll", EntryPoint = "GetWindowLong")]
        private static extern int GetWindowLong32(IntPtr hWnd, int nIndex);

        [DllImport("user32.dll", EntryPoint = "GetWindowLongPtr")]
        private static extern IntPtr GetWindowLongPtr64(IntPtr hWnd, int nIndex);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowTextLength(IntPtr hWnd);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

        [DllImport("user32.dll")]
        private static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll")]
        private static extern bool GetWindowPlacement(IntPtr hWnd, ref WINDOWPLACEMENT lpwndpl);

        [DllImport("user32.dll")]
        private static extern bool SetWindowPlacement(IntPtr hWnd, [In] ref WINDOWPLACEMENT lpwndpl);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool SetWindowPos(
            IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

        [DllImport("dwmapi.dll")]
        private static extern int DwmGetWindowAttribute(IntPtr hWnd, int dwAttribute, out int pvAttribute, int cbAttribute);

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct POINT
        {
            public int X;
            public int Y;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct WINDOWPLACEMENT
        {
            public int length;
            public int flags;
            public int showCmd;
            public POINT ptMinPosition;
            public POINT ptMaxPosition;
            public RECT rcNormalPosition;
        }

        private sealed class WindowSlot
        {
            public long Hwnd;
            public string ProcName;
            public string Title;
            public bool IsSecondary;
            public bool IsMaximized;
            public bool IsMinimized;
            public double RelX;
            public double RelY;
            public double RelW;
            public double RelH;
        }

        private sealed class TimedSnapshot
        {
            public DateTime CapturedUtc;
            public string Sig;
            public int SecCount;
            public Dictionary<long, WindowSlot> Layout;
        }

        private static readonly object StateLock = new object();
        private static IntPtr _defaultDesktop = IntPtr.Zero;
        private static string _lastSeenSig = "";
        private static string _lastStable2MonSig = "";
        private static DateTime _lastSigChangedAt = DateTime.UtcNow;
        private static Dictionary<long, WindowSlot> _saved2MonLayout = new Dictionary<long, WindowSlot>();
        private static readonly List<TimedSnapshot> _history = new List<TimedSnapshot>();
        private static DateTime _dropQuarantineSince = DateTime.MinValue;
        private static int _dropQuarantineTargetSec = -1;
        private static bool _restorePending = false;
        private static bool _left2MonMode = false;
        private static int _restoreGen = 0;
        private static string _lastRestoreSummary = "";
        private static string _lastDiag = "";
        private static readonly List<string> _events = new List<string>();
        private static DateTime _lastStatusWriteAt = DateTime.MinValue;
        private static DateTime _lastSingleRescueAt = DateTime.MinValue;

        private static void AddEventLocked(string msg)
        {
            _events.Add(string.Format("{0:HH:mm:ss} {1}", DateTime.Now, msg));
            if (_events.Count > 12) _events.RemoveAt(0);
        }

        private static int CountSecondary(Dictionary<long, WindowSlot> map)
        {
            if (map == null) return 0;
            int n = 0;
            foreach (var kv in map)
            {
                if (kv.Value.IsSecondary) n++;
            }
            return n;
        }

        private static long GetExStyle(IntPtr hWnd)
        {
            if (IntPtr.Size == 8) return GetWindowLongPtr64(hWnd, GWL_EXSTYLE).ToInt64();
            return GetWindowLong32(hWnd, GWL_EXSTYLE);
        }

        private static Screen[] GetCurrentScreens(out Screen primary, out Screen secondary)
        {
            Screen[] all = Screen.AllScreens;
            primary = Screen.PrimaryScreen;
            secondary = null;
            if (all == null || all.Length == 0) return new Screen[0];

            if (primary == null) primary = all[0];
            long bestArea = -1;
            foreach (Screen sc in all)
            {
                if (sc.Primary)
                {
                    primary = sc;
                    continue;
                }
                long area = (long)sc.Bounds.Width * sc.Bounds.Height;
                if (area > bestArea)
                {
                    bestArea = area;
                    secondary = sc;
                }
            }
            return all;
        }

        private static string BuildTopologySig(Screen[] all)
        {
            if (all == null || all.Length == 0) return "0|";
            var parts = new List<string>(all.Length);
            var list = new List<Screen>(all);
            list.Sort((a, b) =>
            {
                if (a.Primary != b.Primary) return a.Primary ? -1 : 1;
                int cmpX = a.Bounds.X.CompareTo(b.Bounds.X);
                if (cmpX != 0) return cmpX;
                return a.Bounds.Y.CompareTo(b.Bounds.Y);
            });
            foreach (Screen sc in list)
            {
                parts.Add(string.Format("{0}:{1}@{2},{3},{4}x{5}",
                    sc.Primary ? "P" : "S",
                    sc.DeviceName,
                    sc.Bounds.X, sc.Bounds.Y, sc.Bounds.Width, sc.Bounds.Height));
            }
            return all.Length + "|" + string.Join(";", parts.ToArray());
        }

        private static bool IsEligibleUserWindow(IntPtr hWnd, out string cls, out string title, out string procName)
        {
            cls = "";
            title = "";
            procName = "";

            if (!IsWindow(hWnd) || !IsWindowVisible(hWnd)) return false;
            if (GetWindow(hWnd, GW_OWNER) != IntPtr.Zero) return false;

            long ex = GetExStyle(hWnd);
            if ((ex & WS_EX_TOOLWINDOW) != 0) return false;
            if ((ex & WS_EX_NOACTIVATE) != 0) return false;

            int cloaked = 0;
            if (DwmGetWindowAttribute(hWnd, DWMWA_CLOAKED, out cloaked, sizeof(int)) == 0 && cloaked != 0)
                return false;

            int tlen = GetWindowTextLength(hWnd);
            if (tlen <= 0) return false;

            var cb = new StringBuilder(96);
            GetClassName(hWnd, cb, cb.Capacity);
            cls = cb.ToString();
            if (string.IsNullOrEmpty(cls) || SkipClasses.Contains(cls)) return false;

            var tb = new StringBuilder(Math.Min(160, tlen + 2));
            GetWindowText(hWnd, tb, tb.Capacity);
            title = tb.ToString().Trim();
            if (string.IsNullOrEmpty(title)) return false;

            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if (pid == 0) return false;
            try
            {
                using (Process p = Process.GetProcessById((int)pid))
                {
                    procName = p.ProcessName ?? "";
                }
            }
            catch
            {
                procName = "";
            }
            if (string.Equals(procName, "TextInputHost", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(procName, "SearchHost", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(procName, "StartMenuExperienceHost", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(procName, "ShellExperienceHost", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
            return true;
        }

        private static Rectangle RectFromWin32(RECT r)
        {
            return Rectangle.FromLTRB(r.Left, r.Top, r.Right, r.Bottom);
        }

        private static bool IsPointCloserToSecondary(int cx, int cy, Screen pri, Screen sec)
        {
            if (sec == null) return false;
            if (sec.Bounds.Contains(cx, cy)) return true;
            if (pri.Bounds.Contains(cx, cy)) return false;

            int pcx = pri.Bounds.Left + pri.Bounds.Width / 2;
            int pcy = pri.Bounds.Top + pri.Bounds.Height / 2;
            int scx = sec.Bounds.Left + sec.Bounds.Width / 2;
            int scy = sec.Bounds.Top + sec.Bounds.Height / 2;
            long dPri = (long)(cx - pcx) * (cx - pcx) + (long)(cy - pcy) * (cy - pcy);
            long dSec = (long)(cx - scx) * (cx - scx) + (long)(cy - scy) * (cy - scy);
            return dSec < dPri;
        }

        private static Dictionary<long, WindowSlot> CaptureCurrentLayout(Screen pri, Screen sec)
        {
            var map = new Dictionary<long, WindowSlot>();
            if (pri == null || sec == null) return map;
            int cntAll = 0, cntVis = 0, cntCloaked = 0, cntOwner = 0, cntEx = 0, cntTitle = 0, cntSize = 0;

            EnumWindows((hWnd, lParam) =>
            {
                cntAll++;
                try
                {
                    if (!IsWindow(hWnd) || !IsWindowVisible(hWnd)) return true;
                    cntVis++;
                    if (GetWindow(hWnd, GW_OWNER) != IntPtr.Zero) { cntOwner++; return true; }
                    long ex = GetExStyle(hWnd);
                    if ((ex & WS_EX_TOOLWINDOW) != 0 || (ex & WS_EX_NOACTIVATE) != 0) { cntEx++; return true; }
                    int cloaked = 0;
                    if (DwmGetWindowAttribute(hWnd, DWMWA_CLOAKED, out cloaked, sizeof(int)) == 0 && cloaked != 0) { cntCloaked++; return true; }
                    if (GetWindowTextLength(hWnd) <= 0) { cntTitle++; return true; }

                    string cls, title, procName;
                    if (!IsEligibleUserWindow(hWnd, out cls, out title, out procName)) return true;

                    var wp = new WINDOWPLACEMENT();
                    wp.length = Marshal.SizeOf(typeof(WINDOWPLACEMENT));
                    if (!GetWindowPlacement(hWnd, ref wp)) return true;

                    bool isMin = IsIconic(hWnd) || wp.showCmd == SW_SHOWMINIMIZED;
                    bool isMax = wp.showCmd == SW_SHOWMAXIMIZED;

                    Rectangle r;
                    if (isMin)
                    {
                        r = RectFromWin32(wp.rcNormalPosition);
                    }
                    else
                    {
                        RECT wr;
                        if (!GetWindowRect(hWnd, out wr)) return true;
                        r = RectFromWin32(wr);
                    }

                    if (r.Width < 180 || r.Height < 100) { cntSize++; return true; }

                    int cx = r.Left + r.Width / 2;
                    int cy = r.Top + r.Height / 2;
                    bool isSec = IsPointCloserToSecondary(cx, cy, pri, sec);

                    Rectangle monWA = isSec ? sec.WorkingArea : pri.WorkingArea;
                    Rectangle normR = isMax ? RectFromWin32(wp.rcNormalPosition) : r;
                    double mw = Math.Max(1.0, monWA.Width);
                    double mh = Math.Max(1.0, monWA.Height);

                    var slot = new WindowSlot
                    {
                        Hwnd = hWnd.ToInt64(),
                        ProcName = procName,
                        Title = title.Length > 60 ? title.Substring(0, 60) : title,
                        IsSecondary = isSec,
                        IsMaximized = isMax,
                        IsMinimized = isMin,
                        RelX = Clamp((normR.Left - monWA.Left) / mw, 0.0, 0.85),
                        RelY = Clamp((normR.Top - monWA.Top) / mh, 0.0, 0.85),
                        RelW = Clamp(normR.Width / mw, 0.25, 1.0),
                        RelH = Clamp(normR.Height / mh, 0.25, 1.0),
                    };
                    map[slot.Hwnd] = slot;
                }
                catch
                {
                }
                return true;
            }, IntPtr.Zero);

            _lastDiag = string.Format("all={0} vis={1} own={2} ex={3} cloak={4} notitle={5} small={6} kept={7}",
                cntAll, cntVis, cntOwner, cntEx, cntCloaked, cntTitle, cntSize, map.Count);
            return map;
        }

        private static double Clamp(double v, double lo, double hi)
        {
            if (v < lo) return lo;
            if (v > hi) return hi;
            return v;
        }

        private static int ClampInt(int v, int lo, int hi)
        {
            if (v < lo) return lo;
            if (v > hi) return hi;
            return v;
        }

        private static bool MoveWindowToTargetScreen(WindowSlot slot, Screen targetScreen)
        {
            IntPtr hWnd = new IntPtr(slot.Hwnd);
            if (!IsWindow(hWnd) || !IsWindowVisible(hWnd) || IsHungAppWindow(hWnd)) return false;

            var wp = new WINDOWPLACEMENT();
            wp.length = Marshal.SizeOf(typeof(WINDOWPLACEMENT));
            if (!GetWindowPlacement(hWnd, ref wp)) return false;

            bool curMin = IsIconic(hWnd) || wp.showCmd == SW_SHOWMINIMIZED;
            bool curMax = wp.showCmd == SW_SHOWMAXIMIZED;

            Rectangle curRect;
            if (curMin)
            {
                curRect = RectFromWin32(wp.rcNormalPosition);
            }
            else
            {
                RECT wr;
                if (!GetWindowRect(hWnd, out wr)) return false;
                curRect = RectFromWin32(wr);
            }

            int cx = curRect.Left + curRect.Width / 2;
            int cy = curRect.Top + curRect.Height / 2;
            // Nếu cửa sổ đã nằm đúng màn hình đích rồi -> không đụng vào
            if (targetScreen.Bounds.Contains(cx, cy)) return false;

            Rectangle wa = targetScreen.WorkingArea;
            int minW = Math.Min(420, Math.Max(220, wa.Width - 20));
            int minH = Math.Min(300, Math.Max(180, wa.Height - 20));
            int nw = ClampInt((int)Math.Round(slot.RelW * wa.Width), minW, wa.Width);
            int nh = ClampInt((int)Math.Round(slot.RelH * wa.Height), minH, wa.Height);
            int nx = ClampInt(wa.Left + (int)Math.Round(slot.RelX * wa.Width), wa.Left, Math.Max(wa.Left, wa.Right - nw));
            int ny = ClampInt(wa.Top + (int)Math.Round(slot.RelY * wa.Height), wa.Top, Math.Max(wa.Top, wa.Bottom - nh));

            if (curMin)
            {
                wp.rcNormalPosition = new RECT { Left = nx, Top = ny, Right = nx + nw, Bottom = ny + nh };
                if (slot.IsMaximized) wp.flags |= WPF_RESTORETOMAXIMIZED;
                SetWindowPlacement(hWnd, ref wp);
                return true;
            }

            if (curMax || slot.IsMaximized)
            {
                if (curMax)
                {
                    ShowWindow(hWnd, SW_RESTORE);
                    Thread.Sleep(35);
                }
                int rx = slot.IsMaximized ? (wa.Left + Math.Max(0, (wa.Width - nw) / 2)) : nx;
                int ry = slot.IsMaximized ? (wa.Top + Math.Max(0, (wa.Height - nh) / 2)) : ny;
                SetWindowPos(hWnd, IntPtr.Zero, rx, ry, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
                Thread.Sleep(40);
                SetWindowPos(hWnd, IntPtr.Zero, rx, ry, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
                if (slot.IsMaximized)
                {
                    Thread.Sleep(35);
                    ShowWindow(hWnd, SW_SHOWMAXIMIZED);
                }
                return true;
            }

            SetWindowPos(hWnd, IntPtr.Zero, nx, ny, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
            Thread.Sleep(25);
            SetWindowPos(hWnd, IntPtr.Zero, nx, ny, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
            return true;
        }

        private static void RollbackToPreTeardownSnapshotLocked(DateTime nowUtc)
        {
            // Nếu trước lúc đổi màn/RDP <= 2.5s Windows kịp đẩy app sang màn chính,
            // lùi lại lấy đúng bản snapshot sạch trước khi Windows phá bố cục!
            TimedSnapshot best = null;
            for (int i = _history.Count - 1; i >= 0; i--)
            {
                TimedSnapshot snap = _history[i];
                if (snap.SecCount > 0 && (nowUtc - snap.CapturedUtc).TotalSeconds >= 2.2)
                {
                    best = snap;
                    break;
                }
            }
            if (best == null)
            {
                for (int i = _history.Count - 1; i >= 0; i--)
                {
                    if (_history[i].SecCount > 0)
                    {
                        best = _history[i];
                        break;
                    }
                }
            }
            if (best != null && best.SecCount > CountSecondary(_saved2MonLayout))
            {
                _saved2MonLayout = best.Layout;
                AddEventLocked("ROLLBACK sec=" + best.SecCount);
            }
        }

        private static void TriggerRestoreAsync(int gen, string newSig)
        {
            var th = new Thread(() =>
            {
                if (_defaultDesktop != IntPtr.Zero)
                {
                    try { SetThreadDesktop(_defaultDesktop); } catch { }
                }
                try
                {
                    int totalMoved = 0;
                    int[] delaysMs = new int[] { 1000, 1200, 1800 };
                    for (int pass = 0; pass < delaysMs.Length; pass++)
                    {
                        Thread.Sleep(delaysMs[pass]);
                        Dictionary<long, WindowSlot> snapshotCopy;
                        lock (StateLock)
                        {
                            if (gen != _restoreGen) return;
                            snapshotCopy = new Dictionary<long, WindowSlot>(_saved2MonLayout);
                        }

                        Screen pri, sec;
                        Screen[] all = GetCurrentScreens(out pri, out sec);
                        if (all.Length < 2 || pri == null || sec == null)
                        {
                            lock (StateLock)
                            {
                                if (gen == _restoreGen) _restorePending = false;
                            }
                            return;
                        }

                        int movedThisPass = 0;
                        foreach (var kv in snapshotCopy)
                        {
                            WindowSlot slot = kv.Value;
                            Screen target = slot.IsSecondary ? sec : pri;
                            try
                            {
                                if (MoveWindowToTargetScreen(slot, target))
                                    movedThisPass++;
                            }
                            catch
                            {
                            }
                        }
                        totalMoved += movedThisPass;
                    }

                    lock (StateLock)
                    {
                        if (gen == _restoreGen)
                        {
                            _lastStable2MonSig = newSig;
                            _lastSigChangedAt = DateTime.UtcNow;
                            _dropQuarantineSince = DateTime.MinValue;
                            _dropQuarantineTargetSec = -1;
                            _restorePending = false;
                            _left2MonMode = false;
                            _lastRestoreSummary = string.Format("restored={0} at {1:HH:mm:ss} sig={2}",
                                totalMoved, DateTime.Now, newSig);
                            AddEventLocked("RESTORE_DONE moved=" + totalMoved);
                        }
                    }
                    WriteStatusFile(true);
                }
                catch
                {
                    lock (StateLock)
                    {
                        if (gen == _restoreGen) _restorePending = false;
                    }
                }
            });
            th.IsBackground = true;
            th.Start();
        }

        private static int RescueOffscreenWindowsToPrimary(Screen pri)
        {
            if (pri == null) return 0;
            Rectangle wa = pri.WorkingArea;
            int rescued = 0;

            EnumWindows((hWnd, lParam) =>
            {
                try
                {
                    string cls, title, procName;
                    if (!IsEligibleUserWindow(hWnd, out cls, out title, out procName)) return true;
                    if (IsHungAppWindow(hWnd)) return true;

                    var wp = new WINDOWPLACEMENT();
                    wp.length = Marshal.SizeOf(typeof(WINDOWPLACEMENT));
                    if (!GetWindowPlacement(hWnd, ref wp)) return true;

                    bool curMin = IsIconic(hWnd) || wp.showCmd == SW_SHOWMINIMIZED;
                    bool curMax = wp.showCmd == SW_SHOWMAXIMIZED;

                    Rectangle curRect;
                    if (curMin)
                    {
                        curRect = RectFromWin32(wp.rcNormalPosition);
                    }
                    else
                    {
                        RECT wr;
                        if (!GetWindowRect(hWnd, out wr)) return true;
                        curRect = RectFromWin32(wr);
                    }
                    if (curRect.Width < 180 || curRect.Height < 100) return true;

                    int cx = curRect.Left + curRect.Width / 2;
                    int cy = curRect.Top + curRect.Height / 2;
                    // Nếu đã nằm gọn trong màn chính -> giữ nguyên, không chớp nháy
                    if (pri.Bounds.Contains(cx, cy)) return true;

                    int nw = ClampInt(curRect.Width, Math.Min(500, wa.Width), wa.Width);
                    int nh = ClampInt(curRect.Height, Math.Min(350, wa.Height), wa.Height);
                    int nx = wa.Left + Math.Max(0, (wa.Width - nw) / 2);
                    int ny = wa.Top + Math.Max(0, (wa.Height - nh) / 2);

                    if (curMin)
                    {
                        wp.rcNormalPosition = new RECT { Left = nx, Top = ny, Right = nx + nw, Bottom = ny + nh };
                        SetWindowPlacement(hWnd, ref wp);
                        rescued++;
                        return true;
                    }

                    if (curMax)
                    {
                        ShowWindow(hWnd, SW_RESTORE);
                        Thread.Sleep(30);
                        SetWindowPos(hWnd, IntPtr.Zero, nx, ny, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
                        Thread.Sleep(35);
                        SetWindowPos(hWnd, IntPtr.Zero, nx, ny, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
                        Thread.Sleep(30);
                        ShowWindow(hWnd, SW_SHOWMAXIMIZED);
                    }
                    else
                    {
                        SetWindowPos(hWnd, IntPtr.Zero, nx, ny, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
                        Thread.Sleep(25);
                        SetWindowPos(hWnd, IntPtr.Zero, nx, ny, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
                    }
                    rescued++;
                }
                catch
                {
                }
                return true;
            }, IntPtr.Zero);

            return rescued;
        }

        private static void TriggerSingleMonitorRescueAsync(int gen)
        {
            var th = new Thread(() =>
            {
                if (_defaultDesktop != IntPtr.Zero)
                {
                    try { SetThreadDesktop(_defaultDesktop); } catch { }
                }
                try
                {
                    int total = 0;
                    int[] delays = new int[] { 700, 1400 };
                    for (int i = 0; i < delays.Length; i++)
                    {
                        Thread.Sleep(delays[i]);
                        lock (StateLock)
                        {
                            if (gen != _restoreGen) return;
                        }
                        Screen pri, sec;
                        Screen[] all = GetCurrentScreens(out pri, out sec);
                        if (all.Length != 1 || pri == null) return;
                        total += RescueOffscreenWindowsToPrimary(pri);
                    }
                    if (total > 0)
                    {
                        lock (StateLock)
                        {
                            AddEventLocked("RESCUE_1MON moved=" + total);
                        }
                        WriteStatusFile(true);
                    }
                }
                catch
                {
                }
            });
            th.IsBackground = true;
            th.Start();
        }

        private static string GetSavedStatePath()
        {
            return Path.Combine(Path.GetTempPath(), "mwk_layout_guard_state.txt");
        }

        private static void SaveLayoutStateLocked()
        {
            try
            {
                if (_saved2MonLayout == null || CountSecondary(_saved2MonLayout) <= 0) return;
                var sb = new StringBuilder();
                sb.AppendLine(_lastStable2MonSig ?? "");
                foreach (var kv in _saved2MonLayout)
                {
                    WindowSlot s = kv.Value;
                    string safeProc = (s.ProcName ?? "").Replace("|", " ").Replace("\r", "").Replace("\n", "");
                    string safeTitle = (s.Title ?? "").Replace("|", " ").Replace("\r", "").Replace("\n", "");
                    sb.AppendFormat(CultureInfo.InvariantCulture,
                        "{0}|{1}|{2}|{3}|{4:F4}|{5:F4}|{6:F4}|{7:F4}|{8}\n",
                        s.Hwnd,
                        safeProc,
                        s.IsSecondary ? 1 : 0,
                        s.IsMaximized ? 1 : 0,
                        s.RelX, s.RelY, s.RelW, s.RelH,
                        safeTitle);
                }
                File.WriteAllText(GetSavedStatePath(), sb.ToString(), Encoding.UTF8);
            }
            catch
            {
            }
        }

        private static bool TryLoadLayoutStateLocked()
        {
            try
            {
                string path = GetSavedStatePath();
                if (!File.Exists(path)) return false;
                if ((DateTime.UtcNow - File.GetLastWriteTimeUtc(path)).TotalHours > 48.0) return false;
                string[] lines = File.ReadAllLines(path, Encoding.UTF8);
                if (lines.Length < 2) return false;
                string sigLine = (lines[0] ?? "").Trim();
                var loaded = new Dictionary<long, WindowSlot>();
                for (int i = 1; i < lines.Length; i++)
                {
                    string ln = lines[i];
                    if (string.IsNullOrWhiteSpace(ln)) continue;
                    string[] parts = ln.Split(new char[] { '|' }, 9);
                    if (parts.Length < 8) continue;
                    long hwnd;
                    double rx, ry, rw, rh;
                    if (!long.TryParse(parts[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out hwnd)) continue;
                    if (!double.TryParse(parts[4], NumberStyles.Float, CultureInfo.InvariantCulture, out rx)) continue;
                    if (!double.TryParse(parts[5], NumberStyles.Float, CultureInfo.InvariantCulture, out ry)) continue;
                    if (!double.TryParse(parts[6], NumberStyles.Float, CultureInfo.InvariantCulture, out rw)) continue;
                    if (!double.TryParse(parts[7], NumberStyles.Float, CultureInfo.InvariantCulture, out rh)) continue;
                    loaded[hwnd] = new WindowSlot
                    {
                        Hwnd = hwnd,
                        ProcName = parts[1],
                        IsSecondary = parts[2] == "1",
                        IsMaximized = parts[3] == "1",
                        IsMinimized = false,
                        RelX = Clamp(rx, 0.0, 0.85),
                        RelY = Clamp(ry, 0.0, 0.85),
                        RelW = Clamp(rw, 0.25, 1.0),
                        RelH = Clamp(rh, 0.25, 1.0),
                        Title = parts.Length >= 9 ? parts[8] : "",
                    };
                }
                if (CountSecondary(loaded) <= 0) return false;
                _saved2MonLayout = loaded;
                if (!string.IsNullOrEmpty(sigLine)) _lastStable2MonSig = sigLine;
                AddEventLocked("LOAD_SAVED sec=" + CountSecondary(loaded));
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static void CheckTopologyAndSnapshot(bool forceCheck, bool fromSessionEvent)
        {
            Screen pri, sec;
            Screen[] all = GetCurrentScreens(out pri, out sec);
            string sig = BuildTopologySig(all);
            DateTime now = DateTime.UtcNow;

            bool needRestore = false;
            bool needSingleRescue = false;
            int restoreGenLocal = 0;

            lock (StateLock)
            {
                bool sigChanged = !string.Equals(sig, _lastSeenSig, StringComparison.Ordinal);
                if (sigChanged || fromSessionEvent)
                {
                    if (sigChanged)
                    {
                        AddEventLocked("TOPO " + (_lastSeenSig.Length > 0 ? _lastSeenSig.Substring(0, 1) : "0") + "->" + all.Length);
                    }
                    else if (fromSessionEvent)
                    {
                        AddEventLocked("SESSION_REATTACH mon=" + all.Length);
                    }

                    // Trước khi đổi topo/session, đảm bảo không dùng bản snapshot bị Windows làm rỗng ngay trước đó
                    RollbackToPreTeardownSnapshotLocked(now);
                    _dropQuarantineSince = DateTime.MinValue;
                    _dropQuarantineTargetSec = -1;

                    _lastSeenSig = sig;
                    _lastSigChangedAt = now;

                    if (all.Length >= 2 && pri != null && sec != null)
                    {
                        int savedSec = CountSecondary(_saved2MonLayout);
                        // Khôi phục bố cục 2 màn khi:
                        // 1) Vừa quay lại từ chế độ 1 màn / cửa sổ thu nhỏ trên Mac (_left2MonMode == true) - KỂ CẢ khi sig PC 2 màn giống hệt _lastStable2MonSig!
                        // 2) Sự kiện reconnect RDP/Console (fromSessionEvent)
                        // 3) Chuyển giữa 2 cặp màn hình khác nhau (VD: PC 2 màn <-> MacBook+Phone 2 màn)
                        bool shouldRestore = savedSec > 0 && (
                            _left2MonMode ||
                            fromSessionEvent ||
                            (!string.IsNullOrEmpty(_lastStable2MonSig) && !string.Equals(sig, _lastStable2MonSig, StringComparison.Ordinal))
                        );

                        if (shouldRestore)
                        {
                            _restorePending = true;
                            _restoreGen++;
                            restoreGenLocal = _restoreGen;
                            needRestore = true;
                            AddEventLocked("SCHEDULE_RESTORE sec=" + savedSec + (_left2MonMode ? " from1m" : ""));
                        }
                        else if (string.IsNullOrEmpty(_lastStable2MonSig))
                        {
                            _lastStable2MonSig = sig;
                            var initCur = CaptureCurrentLayout(pri, sec);
                            if (initCur.Count > 0)
                            {
                                _saved2MonLayout = initCur;
                                int initSec = CountSecondary(initCur);
                                _history.Add(new TimedSnapshot { CapturedUtc = now, Sig = sig, SecCount = initSec, Layout = initCur });
                                if (initSec > 0) SaveLayoutStateLocked();
                            }
                        }
                        else if (savedSec > 0)
                        {
                            // Khởi động lại guard ngay lúc vừa trở về 2 màn (toàn bộ app vẫn đang bị dồn về màn 1)
                            var curCheck = CaptureCurrentLayout(pri, sec);
                            if (CountSecondary(curCheck) == 0)
                            {
                                bool anySavedSecAlive = false;
                                foreach (var kv in _saved2MonLayout)
                                {
                                    if (kv.Value.IsSecondary && IsWindow(new IntPtr(kv.Key)))
                                    {
                                        anySavedSecAlive = true;
                                        break;
                                    }
                                }
                                if (anySavedSecAlive)
                                {
                                    _restorePending = true;
                                    _restoreGen++;
                                    restoreGenLocal = _restoreGen;
                                    needRestore = true;
                                    AddEventLocked("SCHEDULE_RESTORE_BOOT sec=" + savedSec);
                                }
                            }
                        }
                    }
                    else
                    {
                        // Chuyển về 1 màn (chế độ cửa sổ thường trên Mac hoặc thu nhỏ Remote) ->
                        // ĐÁNH DẤU _left2MonMode = true & ĐÓNG BĂNG _saved2MonLayout (tuyệt đối không ghi đè!)
                        // để khi về lại PC 2 màn hoặc Full-Screen 2 màn sẽ tự động tách lại y hệt layout gốc!
                        _left2MonMode = true;
                        _restorePending = false;
                        _restoreGen++;
                        restoreGenLocal = _restoreGen;
                        if (all.Length == 1 && pri != null)
                        {
                            needSingleRescue = true;
                        }
                    }
                }
                else if (all.Length == 1 && pri != null)
                {
                    _left2MonMode = true;
                    // Định kỳ kéo cửa sổ vừa được bấm mở từ taskbar nếu vẫn còn lạc tọa độ ngoài màn #1 (giữ nguyên _saved2MonLayout!)
                    if ((now - _lastSingleRescueAt).TotalSeconds >= 1.5)
                    {
                        _lastSingleRescueAt = now;
                        int rMoved = RescueOffscreenWindowsToPrimary(pri);
                        if (rMoved > 0)
                        {
                            AddEventLocked("RESCUE_1MON_LIVE moved=" + rMoved);
                        }
                    }
                }
                else if (all.Length >= 2 && pri != null && sec != null && !_restorePending)
                {
                    if ((now - _lastSigChangedAt).TotalSeconds >= 2.8 || _saved2MonLayout.Count == 0)
                    {
                        var cur = CaptureCurrentLayout(pri, sec);
                        if (cur.Count > 0)
                        {
                            int curSec = CountSecondary(cur);
                            int savedSec = CountSecondary(_saved2MonLayout);

                            if (curSec > 0)
                            {
                                _history.Add(new TimedSnapshot
                                {
                                    CapturedUtc = now,
                                    Sig = sig,
                                    SecCount = curSec,
                                    Layout = cur,
                                });
                                while (_history.Count > 24) _history.RemoveAt(0);
                            }

                            // CHỐNG ĐÈ RÁC TRƯỚC KHI NGẮT MÀN HÌNH:
                            // Nếu số app ở Màn phụ tụt đột ngột về 0 -> giữ cách ly 10 giây ổn định mới chấp nhận!
                            // Nếu tụt một phần (ví dụ 2 -> 1) -> giữ cách ly 4 giây ổn định mới chấp nhận!
                            if (savedSec > 0 && curSec < savedSec)
                            {
                                double requiredSec = (curSec == 0) ? 10.0 : 4.0;
                                if (_dropQuarantineTargetSec != curSec || _dropQuarantineSince == DateTime.MinValue)
                                {
                                    _dropQuarantineTargetSec = curSec;
                                    _dropQuarantineSince = now;
                                }
                                else if ((now - _dropQuarantineSince).TotalSeconds >= requiredSec)
                                {
                                    _saved2MonLayout = cur;
                                    _lastStable2MonSig = sig;
                                    _dropQuarantineSince = DateTime.MinValue;
                                    _dropQuarantineTargetSec = -1;
                                    if (curSec > 0) SaveLayoutStateLocked();
                                }
                            }
                            else
                            {
                                _dropQuarantineSince = DateTime.MinValue;
                                _dropQuarantineTargetSec = -1;
                                _saved2MonLayout = cur;
                                _lastStable2MonSig = sig;
                                if (curSec > 0) SaveLayoutStateLocked();
                            }
                        }
                    }
                }
            }

            if (needRestore)
            {
                WriteStatusFile(true);
                TriggerRestoreAsync(restoreGenLocal, sig);
            }
            else if (needSingleRescue)
            {
                WriteStatusFile(true);
                TriggerSingleMonitorRescueAsync(restoreGenLocal);
            }
            else
            {
                WriteStatusFile(forceCheck);
            }
        }

        private static string EscapeJson(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", " ").Replace("\n", " ");
        }

        private static void WriteStatusFile(bool force)
        {
            DateTime now = DateTime.UtcNow;
            if (!force && (now - _lastStatusWriteAt).TotalSeconds < 4.0) return;
            _lastStatusWriteAt = now;
            try
            {
                string path = Path.Combine(Path.GetTempPath(), "mwk_layout_guard_status.json");
                var sb = new StringBuilder();
                lock (StateLock)
                {
                    int priCount = 0, secCount = 0;
                    var secNames = new List<string>();
                    var priNames = new List<string>();
                    foreach (var kv in _saved2MonLayout)
                    {
                        string label = kv.Value.ProcName + ":" + kv.Value.Title;
                        if (kv.Value.IsSecondary) { secCount++; secNames.Add(label); }
                        else { priCount++; priNames.Add(label); }
                    }
                    sb.Append("{\n");
                    sb.AppendFormat("  \"updated\": \"{0:yyyy-MM-dd HH:mm:ss}\",\n", DateTime.Now);
                    sb.AppendFormat("  \"pid\": {0},\n", Process.GetCurrentProcess().Id);
                    sb.AppendFormat("  \"session_id\": {0},\n", Process.GetCurrentProcess().SessionId);
                    sb.AppendFormat("  \"current_sig\": \"{0}\",\n", EscapeJson(_lastSeenSig));
                    sb.AppendFormat("  \"stable_2mon_sig\": \"{0}\",\n", EscapeJson(_lastStable2MonSig));
                    sb.AppendFormat("  \"restore_pending\": {0},\n", _restorePending ? "true" : "false");
                    sb.AppendFormat("  \"left_2mon_mode\": {0},\n", _left2MonMode ? "true" : "false");
                    sb.AppendFormat("  \"last_restore\": \"{0}\",\n", EscapeJson(_lastRestoreSummary));
                    sb.AppendFormat("  \"diag\": \"{0}\",\n", EscapeJson(_lastDiag));
                    sb.AppendFormat("  \"primary_count\": {0},\n", priCount);
                    sb.AppendFormat("  \"secondary_count\": {0},\n", secCount);
                    sb.Append("  \"primary_apps\": [");
                    for (int i = 0; i < priNames.Count; i++)
                    {
                        if (i > 0) sb.Append(", ");
                        sb.Append("\"").Append(EscapeJson(priNames[i])).Append("\"");
                    }
                    sb.Append("],\n  \"secondary_apps\": [");
                    for (int i = 0; i < secNames.Count; i++)
                    {
                        if (i > 0) sb.Append(", ");
                        sb.Append("\"").Append(EscapeJson(secNames[i])).Append("\"");
                    }
                    sb.Append("],\n  \"events\": [");
                    for (int i = 0; i < _events.Count; i++)
                    {
                        if (i > 0) sb.Append(", ");
                        sb.Append("\"").Append(EscapeJson(_events[i])).Append("\"");
                    }
                    sb.Append("]\n}\n");
                }
                File.WriteAllText(path, sb.ToString(), Encoding.UTF8);
            }
            catch
            {
            }
        }

        [STAThread]
        public static void Main()
        {
            bool createdNew;
            using (var mutex = new Mutex(true, "Local\\MacWebKeyboard_DisplayLayoutGuard_v1", out createdNew))
            {
                if (!createdNew) return;

                try
                {
                    IntPtr hDesk = OpenDesktop("Default", 0, false, 0x01FF);
                    if (hDesk != IntPtr.Zero)
                    {
                        _defaultDesktop = hDesk;
                        SetThreadDesktop(hDesk);
                    }
                }
                catch { }

                try { SetProcessDpiAwareness(2); }
                catch
                {
                    try { SetProcessDPIAware(); } catch { }
                }

                lock (StateLock)
                {
                    TryLoadLayoutStateLocked();
                }

                CheckTopologyAndSnapshot(true, false);

                SystemEvents.DisplaySettingsChanged += (s, e) => CheckTopologyAndSnapshot(true, false);
                SystemEvents.SessionSwitch += (s, e) =>
                {
                    bool isReattach = (e.Reason == SessionSwitchReason.RemoteConnect ||
                                       e.Reason == SessionSwitchReason.ConsoleConnect ||
                                       e.Reason == SessionSwitchReason.SessionUnlock);
                    CheckTopologyAndSnapshot(true, isReattach);
                };

                var timer = new System.Windows.Forms.Timer();
                timer.Interval = 650;
                timer.Tick += (s, e) => CheckTopologyAndSnapshot(false, false);
                timer.Start();

                Application.Run();
                GC.KeepAlive(mutex);
            }
        }
    }
}
