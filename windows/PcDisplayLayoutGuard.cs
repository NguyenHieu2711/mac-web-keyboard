using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
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

        private static readonly object StateLock = new object();
        private static IntPtr _defaultDesktop = IntPtr.Zero;
        private static string _lastSeenSig = "";
        private static string _lastStable2MonSig = "";
        private static DateTime _lastSigChangedAt = DateTime.UtcNow;
        private static Dictionary<long, WindowSlot> _saved2MonLayout = new Dictionary<long, WindowSlot>();
        private static bool _restorePending = false;
        private static int _restoreGen = 0;
        private static string _lastRestoreSummary = "";
        private static string _lastDiag = "";
        private static DateTime _lastStatusWriteAt = DateTime.MinValue;

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

        private static bool MoveWindowToTargetScreen(WindowSlot slot, Screen targetScreen, Screen otherScreen)
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
                // Giữ nguyên trạng thái thu nhỏ nhưng cập nhật tọa độ mở lại về đúng màn đích
                wp.rcNormalPosition = new RECT { Left = nx, Top = ny, Right = nx + nw, Bottom = ny + nh };
                SetWindowPlacement(hWnd, ref wp);
                return true;
            }

            if (slot.IsMaximized || curMax)
            {
                ShowWindow(hWnd, SW_RESTORE);
                Thread.Sleep(35);
                int rx = wa.Left + Math.Max(0, (wa.Width - nw) / 2);
                int ry = wa.Top + Math.Max(0, (wa.Height - nh) / 2);
                SetWindowPos(hWnd, IntPtr.Zero, rx, ry, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
                Thread.Sleep(40);
                SetWindowPos(hWnd, IntPtr.Zero, rx, ry, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
                Thread.Sleep(35);
                ShowWindow(hWnd, SW_SHOWMAXIMIZED);
                return true;
            }

            // Gọi 2 lần để tự khóa chuẩn kích thước khi chuyển giữa 2 màn có DPI scale khác nhau (Per-Monitor DPI)
            SetWindowPos(hWnd, IntPtr.Zero, nx, ny, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
            Thread.Sleep(20);
            SetWindowPos(hWnd, IntPtr.Zero, nx, ny, nw, nh, SWP_NOZORDER | SWP_NOACTIVATE);
            return true;
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
                    int[] delaysMs = new int[] { 1050, 1250 };
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
                            Screen other = slot.IsSecondary ? pri : sec;
                            try
                            {
                                if (MoveWindowToTargetScreen(slot, target, other))
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
                            _restorePending = false;
                            _lastRestoreSummary = string.Format("restored={0} at {1:HH:mm:ss} sig={2}",
                                totalMoved, DateTime.Now, newSig);
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

        private static void CheckTopologyAndSnapshot(bool forceCheck, bool fromSessionEvent)
        {
            Screen pri, sec;
            Screen[] all = GetCurrentScreens(out pri, out sec);
            string sig = BuildTopologySig(all);
            DateTime now = DateTime.UtcNow;

            bool needRestore = false;
            int restoreGenLocal = 0;

            lock (StateLock)
            {
                if (!string.Equals(sig, _lastSeenSig, StringComparison.Ordinal) || fromSessionEvent)
                {
                    _lastSeenSig = sig;
                    _lastSigChangedAt = now;

                    if (all.Length >= 2 && pri != null && sec != null)
                    {
                        bool hasSavedSec = false;
                        foreach (var kv in _saved2MonLayout)
                        {
                            if (kv.Value.IsSecondary) { hasSavedSec = true; break; }
                        }

                        if (!string.IsNullOrEmpty(_lastStable2MonSig) &&
                            (fromSessionEvent || !string.Equals(sig, _lastStable2MonSig, StringComparison.Ordinal)) &&
                            hasSavedSec)
                        {
                            _restorePending = true;
                            _restoreGen++;
                            restoreGenLocal = _restoreGen;
                            needRestore = true;
                        }
                        else if (string.IsNullOrEmpty(_lastStable2MonSig))
                        {
                            _lastStable2MonSig = sig;
                            var initCur = CaptureCurrentLayout(pri, sec);
                            if (initCur.Count > 0)
                            {
                                _saved2MonLayout = initCur;
                            }
                        }
                    }
                    else
                    {
                        // Tạm tụt về 1 màn (ví dụ đang chuyển Console <-> RDP) -> đóng băng _saved2MonLayout!
                        _restorePending = false;
                        _restoreGen++;
                    }
                }
                else if (all.Length >= 2 && pri != null && sec != null && !_restorePending)
                {
                    // Chỉ cập nhật snapshot khi cấu hình 2 màn hình đã ổn định >= 2.8 giây
                    if ((now - _lastSigChangedAt).TotalSeconds >= 2.8 || _saved2MonLayout.Count == 0)
                    {
                        var cur = CaptureCurrentLayout(pri, sec);
                        if (cur.Count > 0)
                        {
                            _saved2MonLayout = cur;
                            _lastStable2MonSig = sig;
                        }
                    }
                }
            }

            if (needRestore)
            {
                WriteStatusFile(true);
                TriggerRestoreAsync(restoreGenLocal, sig);
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
            if (!force && (now - _lastStatusWriteAt).TotalSeconds < 6.0) return;
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

                // Luôn gắn trực tiếp vào desktop tương tác thật (WinSta0\Default) kể cả khi khởi chạy ngầm
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

                // Khởi tạo ngay snapshot ban đầu
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
