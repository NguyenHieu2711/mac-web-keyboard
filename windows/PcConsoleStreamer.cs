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
        private const int CHILD_LISTEN_PORT = 5053;
        private static bool _isChildSession = false;
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
        private const uint MOUSEEVENTF_ABSOLUTE = 0x8000;

        private const uint KEYEVENTF_EXTENDEDKEY = 0x0001;
        private const uint KEYEVENTF_KEYUP = 0x0002;
        private const uint KEYEVENTF_UNICODE = 0x0004;

        [DllImport("shcore.dll")]
        private static extern int SetProcessDpiAwareness(int value);

        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [DllImport("user32.dll")]
        private static extern int GetSystemMetrics(int nIndex);

        [DllImport("kernel32.dll")]
        private static extern uint WTSGetActiveConsoleSessionId();

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSGetChildSessionId(out uint pSessionId);

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSQuerySessionInformationW(
            IntPtr hServer, uint sessionId, int infoClass, out IntPtr ppBuffer, out int pBytesReturned);

        [DllImport("wtsapi32.dll")]
        private static extern void WTSFreeMemory(IntPtr pMemory);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

        [DllImport("user32.dll")]
        private static extern uint MapVirtualKeyW(uint uCode, uint uMapType);

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
            _jpegParams.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 88L);
        }

        private static bool DetectIsChildSession()
        {
            try
            {
                int mySid = Process.GetCurrentProcess().SessionId;
                uint childSid = 0xFFFFFFFF;
                if (WTSGetChildSessionId(out childSid) && childSid != 0xFFFFFFFF && (int)childSid == mySid)
                {
                    return true;
                }
                // Fallback: nếu phiên hiện tại khác console session và là phiên RDP cục bộ từ ChildHost
                uint consoleSid = WTSGetActiveConsoleSessionId();
                if (consoleSid != 0xFFFFFFFF && mySid != (int)consoleSid)
                {
                    IntPtr buf;
                    int bytes;
                    // WTSClientName = 10 -> Child session loopback thường có client name là chính hostname
                    if (WTSQuerySessionInformationW(IntPtr.Zero, (uint)mySid, 10, out buf, out bytes) && buf != IntPtr.Zero)
                    {
                        string cliName = Marshal.PtrToStringUni(buf) ?? "";
                        WTSFreeMemory(buf);
                        if (string.Equals(cliName.Trim(), Environment.MachineName, StringComparison.OrdinalIgnoreCase))
                        {
                            return true;
                        }
                    }
                }
            }
            catch { }
            return false;
        }

        private static bool IsConsoleActiveAndUnlocked()
        {
            if (_isChildSession) return true;
            try
            {
                uint cid = WTSGetActiveConsoleSessionId();
                if (cid == 0xFFFFFFFF) return false;
                IntPtr buf;
                int bytes;
                int connState = -1;
                if (WTSQuerySessionInformationW(IntPtr.Zero, cid, 8, out buf, out bytes) && buf != IntPtr.Zero)
                {
                    connState = Marshal.ReadInt32(buf);
                    WTSFreeMemory(buf);
                }
                if (connState != 0) return false;

                int unlockFlag = 1;
                if (WTSQuerySessionInformationW(IntPtr.Zero, cid, 25, out buf, out bytes) && buf != IntPtr.Zero)
                {
                    if (bytes >= 20) unlockFlag = Marshal.ReadInt32(buf, 16);
                    WTSFreeMemory(buf);
                }
                return unlockFlag == 1;
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

        private static byte[] CaptureJpegFrame(out int outW, out int outH, out ulong sig)
        {
            outW = 0;
            outH = 0;
            sig = 0;
            Size scr = GetPrimaryScreenSize();
            int sw = scr.Width;
            int sh = scr.Height;

            int tw = sw;
            int th = sh;
            if (sw > 2560)
            {
                tw = 2560;
                th = Math.Max(1, (int)Math.Round(sh * 2560.0 / sw));
            }

            using (var rawBmp = new Bitmap(sw, sh, PixelFormat.Format24bppRgb))
            {
                using (var g = Graphics.FromImage(rawBmp))
                {
                    g.CopyFromScreen(0, 0, 0, 0, new Size(sw, sh), CopyPixelOperation.SourceCopy);
                }

                Bitmap targetBmp = rawBmp;
                Bitmap resized = null;
                try
                {
                    if (tw != sw || th != sh)
                    {
                        resized = new Bitmap(tw, th, PixelFormat.Format24bppRgb);
                        using (var gr = Graphics.FromImage(resized))
                        {
                            gr.InterpolationMode = InterpolationMode.HighQualityBilinear;
                            gr.DrawImage(rawBmp, 0, 0, tw, th);
                        }
                        targetBmp = resized;
                    }

                    // Fast 64-point visual signature to skip sending identical static frames
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
        }

        private static void SendMouseEvent(double rx, double ry, uint flags, uint mouseData)
        {
            int ax = (int)Math.Round(Math.Max(0.0, Math.Min(1.0, rx)) * 65535.0);
            int ay = (int)Math.Round(Math.Max(0.0, Math.Min(1.0, ry)) * 65535.0);
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
                        dwFlags = flags,
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

        private static void DispatchInputJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json)) return;
            string mtype = ExtractJsonString(json, "type");
            if (mtype == "ptr_move")
            {
                double rx = ExtractJsonDouble(json, "rx", 0.5);
                double ry = ExtractJsonDouble(json, "ry", 0.5);
                SendMouseEvent(rx, ry, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0);
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
                SendMouseEvent(rx, ry, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | btnFlag, 0);
            }
            else if (mtype == "ptr_wheel")
            {
                double rx = ExtractJsonDouble(json, "rx", 0.5);
                double ry = ExtractJsonDouble(json, "ry", 0.5);
                double dx = ExtractJsonDouble(json, "dx", 0.0);
                double dy = ExtractJsonDouble(json, "dy", 0.0);
                SendMouseEvent(rx, ry, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0);
                int wy = (int)Math.Round(dy * 3.0);
                int wx = (int)Math.Round(-dx * 3.0);
                if (wy != 0) SendMouseEvent(rx, ry, MOUSEEVENTF_WHEEL, unchecked((uint)wy));
                if (wx != 0) SendMouseEvent(rx, ry, MOUSEEVENTF_HWHEEL, unchecked((uint)wx));
            }
            else if (mtype == "key_tap")
            {
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
                string txt = ExtractJsonString(json, "text");
                if (!string.IsNullOrEmpty(txt)) SendUnicodeString(txt);
            }
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

        private static void HandleClient(TcpClient client)
        {
            try
            {
                client.NoDelay = true;
                using (NetworkStream ns = client.GetStream())
                using (var reader = new StreamReader(ns, Encoding.UTF8, false, 4096, true))
                {
                    string firstLine = reader.ReadLine();
                    if (firstLine == null) return;
                    string cmd = firstLine.Trim().ToUpperInvariant();

                    if (cmd == "PROBE")
                    {
                        bool active = IsConsoleActiveAndUnlocked();
                        Size sz = GetPrimaryScreenSize();
                        string reply = "{\"ok\":true,\"active\":" + (active ? "true" : "false") +
                                       ",\"child\":" + (_isChildSession ? "true" : "false") +
                                       ",\"width\":" + sz.Width + ",\"height\":" + sz.Height + "}\n";
                        byte[] rb = Encoding.UTF8.GetBytes(reply);
                        ns.Write(rb, 0, rb.Length);
                        ns.Flush();
                        return;
                    }

                    if (cmd != "STREAM") return;

                    bool running = true;
                    object writeLock = new object();

                    var inputThread = new Thread(() =>
                    {
                        try
                        {
                            string line;
                            while (running && (line = reader.ReadLine()) != null)
                            {
                                try { DispatchInputJson(line); } catch { }
                            }
                        }
                        catch { }
                        finally { running = false; }
                    });
                    inputThread.IsBackground = true;
                    inputThread.Start();

                    ulong prevSig = 0;
                    long lastSentTick = 0;
                    int lockedStreak = 0;

                    while (running)
                    {
                        if (!IsConsoleActiveAndUnlocked())
                        {
                            lockedStreak++;
                            if (lockedStreak >= 12)
                            {
                                byte[] ctrl = Encoding.UTF8.GetBytes("{\"type\":\"parallel_ended\",\"reason\":\"console_locked\"}");
                                byte[] pkt = new byte[1 + ctrl.Length];
                                pkt[0] = 0x20;
                                Buffer.BlockCopy(ctrl, 0, pkt, 1, ctrl.Length);
                                lock (writeLock) { WriteFramed(ns, pkt); }
                                break;
                            }
                            Thread.Sleep(80);
                            continue;
                        }
                        lockedStreak = 0;

                        try
                        {
                            int fw, fh;
                            ulong sig;
                            byte[] jpeg = CaptureJpegFrame(out fw, out fh, out sig);
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
                            Thread.Sleep(80);
                        }
                        Thread.Sleep(38);
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
            if (!CanCaptureInteractiveDesktop())
            {
                return 2;
            }

            _isChildSession = DetectIsChildSession();
            int bindPort = _isChildSession ? CHILD_LISTEN_PORT : CONSOLE_LISTEN_PORT;

            TcpListener listener = null;
            try
            {
                listener = new TcpListener(IPAddress.Loopback, bindPort);
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
