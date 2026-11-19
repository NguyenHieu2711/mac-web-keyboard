using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace MacWebKeyboard
{
    [ComImport]
    [Guid("302d8188-0052-4807-806a-362b628f9ac5")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMsRdpExtendedSettings
    {
        void put_Property(
            [In, MarshalAs(UnmanagedType.BStr)] string bstrPropertyName,
            [In, MarshalAs(UnmanagedType.Struct)] ref object pVariant);

        [return: MarshalAs(UnmanagedType.Struct)]
        object get_Property(
            [In, MarshalAs(UnmanagedType.BStr)] string bstrPropertyName);
    }

    [ComImport]
    [Guid("336d5562-efa8-482e-8cb3-c5c0fc7a7db6")]
    [InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    public interface IMsTscAxEvents
    {
        [DispId(1)] void OnConnecting();
        [DispId(2)] void OnConnected();
        [DispId(3)] void OnLoginComplete();
        [DispId(4)] void OnDisconnected([In] int discReason);
        [DispId(5)] void OnEnterFullScreenMode();
        [DispId(6)] void OnLeaveFullScreenMode();
        [DispId(7)] void OnChannelReceivedData([In, MarshalAs(UnmanagedType.BStr)] string chanName, [In, MarshalAs(UnmanagedType.BStr)] string data);
        [DispId(8)] void OnRequestGoFullScreen();
        [DispId(9)] void OnRequestLeaveFullScreen();
        [DispId(10)] void OnFatalError([In] int errorCode);
        [DispId(11)] void OnWarning([In] int warningCode);
        [DispId(12)] void OnRemoteDesktopSizeChange([In] int width, [In] int height);
        [DispId(13)] void OnIdleTimeoutNotification();
        [DispId(14)] void OnRequestContainerMinimize();
        [DispId(15)] void OnConfirmClose([Out] out bool pfAllowClose);
        [DispId(16)] void OnReceivedTSPublicKey([In, MarshalAs(UnmanagedType.BStr)] string publicKey, [Out] out bool pfContinueLogon);
        [DispId(17)] void OnAutoReconnecting([In] int disconnectReason, [In] int attemptCount, [Out] out int pArcContinueStatus);
        [DispId(18)] void OnAuthenticationWarningDisplayed();
        [DispId(19)] void OnAuthenticationWarningDismissed();
    }

    [ClassInterface(ClassInterfaceType.None)]
    public class RdpEventSink : IMsTscAxEvents
    {
        private readonly ChildHostForm _owner;
        public RdpEventSink(ChildHostForm owner) { _owner = owner; }
        public void OnConnecting() { _owner.OnRdpEvent("connecting", 0); }
        public void OnConnected() { _owner.OnRdpEvent("connected", 0); }
        public void OnLoginComplete() { _owner.OnRdpEvent("login_complete", 0); }
        public void OnDisconnected(int discReason) { _owner.OnRdpEvent("disconnected", discReason); }
        public void OnEnterFullScreenMode() {}
        public void OnLeaveFullScreenMode() {}
        public void OnChannelReceivedData(string chanName, string data) {}
        public void OnRequestGoFullScreen() {}
        public void OnRequestLeaveFullScreen() {}
        public void OnFatalError(int errorCode) { _owner.OnRdpEvent("fatal_error", errorCode); }
        public void OnWarning(int warningCode) { _owner.OnRdpEvent("warning", warningCode); }
        public void OnRemoteDesktopSizeChange(int width, int height) { _owner.OnRdpEvent("size_" + width + "x" + height, 0); }
        public void OnIdleTimeoutNotification() {}
        public void OnRequestContainerMinimize() {}
        public void OnConfirmClose(out bool pfAllowClose) { pfAllowClose = true; }
        public void OnReceivedTSPublicKey(string publicKey, out bool pfContinueLogon) { pfContinueLogon = true; }
        public void OnAutoReconnecting(int disconnectReason, int attemptCount, out int pArcContinueStatus) { pArcContinueStatus = 1; }
        public void OnAuthenticationWarningDisplayed() { _owner.OnRdpEvent("auth_warn", 0); }
        public void OnAuthenticationWarningDismissed() {}
    }

    internal class RdpChildAxHost : AxHost
    {
        private AxHost.ConnectionPointCookie _cookie;
        private readonly ChildHostForm _owner;
        public RdpChildAxHost(string clsid, ChildHostForm owner) : base(clsid) { _owner = owner; }

        protected override void CreateSink()
        {
            try
            {
                _cookie = new AxHost.ConnectionPointCookie(GetOcx(), new RdpEventSink(_owner), typeof(IMsTscAxEvents));
            }
            catch { }
        }

        protected override void DetachSink()
        {
            try { if (_cookie != null) _cookie.Disconnect(); } catch { }
            _cookie = null;
        }
    }

    public class ChildHostForm : Form
    {
        private const int WS_EX_TRANSPARENT = 0x00000020;
        private const int WS_EX_TOOLWINDOW = 0x00000080;
        private const int WS_EX_NOACTIVATE = 0x08000000;

        private static readonly string[] CandidateClsids = new string[]
        {
            "8b918b82-7985-4c24-89df-c33ad2bbfbcd", // MsRdpClient9NotSafeForScripting
            "a0c63c30-f08d-4ab4-907c-34905d770c7d", // MsRdpClient10NotSafeForScripting
            "1df7c823-b2d4-4b54-975a-f2ac5d7cf8b8", // MsRdpClient11NotSafeForScripting
        };

        private RdpChildAxHost _ax;
        private System.Windows.Forms.Timer _watchTimer;
        private int _targetW;
        private int _targetH;
        private uint _targetScale;
        public volatile bool IsConnected;
        public volatile short ConnState;
        public volatile string LastError = "";
        public volatile string LastEvent = "init";
        public volatile int LastDiscReason;
        public volatile string ActiveClsid = "";
        private int _reconnectCooldown = 0;

        public void OnRdpEvent(string evt, int code)
        {
            LastEvent = evt + (code != 0 ? ":" + code : "");
            if (evt == "connected" || evt == "login_complete")
            {
                IsConnected = true;
                ConnState = 1;
            }
            else if (evt == "disconnected")
            {
                IsConnected = false;
                ConnState = 0;
                LastDiscReason = code;
                _reconnectCooldown = 3; // Chờ ~10s trước khi thử lại để tránh vòng lặp nóng
            }
            else if (evt == "fatal_error")
            {
                IsConnected = false;
                LastError = "fatal_error:" + code;
            }
        }

        public ChildHostForm(int width, int height, uint scalePct)
        {
            _targetW = width;
            _targetH = height;
            _targetScale = scalePct;

            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            Location = new Point(-32000, -32000);
            ClientSize = new Size(1, 1);
            Opacity = 0.0;
            Enabled = false;
            Text = "MacWebKeyboard Child Session Host";

            Load += OnFormLoad;
        }

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams cp = base.CreateParams;
                cp.ExStyle |= WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
                return cp;
            }
        }

        protected override bool ShowWithoutActivation
        {
            get { return true; }
        }

        private void OnFormLoad(object sender, EventArgs e)
        {
            Location = new Point(-32000, -32000);
            InitAndConnect();

            _watchTimer = new System.Windows.Forms.Timer();
            _watchTimer.Interval = 3500;
            _watchTimer.Tick += (s, ev) => EnsureConnected();
            _watchTimer.Start();
        }

        private void InitAndConnect()
        {
            foreach (string clsid in CandidateClsids)
            {
                try
                {
                    var host = new RdpChildAxHost(clsid, this);
                    ((System.ComponentModel.ISupportInitialize)host).BeginInit();
                    host.Dock = DockStyle.Fill;
                    Controls.Add(host);
                    ((System.ComponentModel.ISupportInitialize)host).EndInit();
                    _ax = host;
                    ActiveClsid = clsid;
                    break;
                }
                catch (Exception ex)
                {
                    LastError = ex.Message;
                }
            }
            if (_ax != null)
            {
                ConnectInternal();
            }
        }

        private void EnsureConnected()
        {
            if (_ax == null) return;
            try
            {
                dynamic ocx = _ax.GetOcx();
                short state = (short)ocx.Connected;
                ConnState = state;
                IsConnected = (state == 1);
                if (state == 0)
                {
                    if (_reconnectCooldown > 0)
                    {
                        _reconnectCooldown--;
                        return;
                    }
                    ConnectInternal();
                }
            }
            catch (Exception ex)
            {
                IsConnected = false;
                LastError = ex.Message;
            }
        }

        private void ConnectInternal()
        {
            if (_ax == null) return;
            string step = "get_ocx";
            try
            {
                dynamic ocx = _ax.GetOcx();
                step = "check_connected";
                short curState = (short)ocx.Connected;
                ConnState = curState;
                if (curState != 0)
                {
                    IsConnected = (curState == 1);
                    return;
                }

                step = "set_server";
                ocx.Server = "localhost";
                step = "set_dims";
                ocx.DesktopWidth = _targetW;
                ocx.DesktopHeight = _targetH;
                ocx.ColorDepth = 32;
                try { ocx.AdvancedSettings2.SmartSizing = false; } catch { }
                try { ocx.AdvancedSettings2.AudioRedirectionMode = 0; } catch { }
                try { ocx.AdvancedSettings2.EnableAutoReconnect = true; } catch { }
                step = "set_auth_level";
                ocx.AdvancedSettings7.AuthenticationLevel = (uint)0;
                step = "set_credssp";
                ocx.AdvancedSettings7.EnableCredSspSupport = true;
                try { ocx.AdvancedSettings9.EnableCredSspSupport = true; } catch { }
                // Tuyệt đối không chiếm phím Win/Alt+Tab của phiên PC chính!
                try { ocx.AdvancedSettings9.EnableWindowsKey = 0; } catch { }
                try { ocx.AdvancedSettings9.AcceleratorPassthrough = 0; } catch { }
                try { ocx.SecuredSettings3.KeyboardHookMode = 0; } catch { }
                try { ocx.AdvancedSettings7.NegotiateSecurityLayer = true; } catch { }

                step = "set_child_prop";
                IMsRdpExtendedSettings ext = ocx as IMsRdpExtendedSettings;
                if (ext != null)
                {
                    object vTrue = true;
                    ext.put_Property("ConnectToChildSession", ref vTrue);
                    try
                    {
                        object vScale = _targetScale;
                        ext.put_Property("DesktopScaleFactor", ref vScale);
                        object vDevScale = (uint)100;
                        ext.put_Property("DeviceScaleFactor", ref vDevScale);
                    }
                    catch { }
                }

                step = "connect";
                ocx.Connect();
                ConnState = (short)ocx.Connected;
                LastError = "";
                IsConnected = (ConnState == 1);
            }
            catch (Exception ex)
            {
                IsConnected = false;
                LastError = step + ": " + ex.Message;
            }
        }
    }

    internal static class PcChildSessionHost
    {
        private const int STATUS_PORT = 5054;
        private static Mutex _singleInstanceMutex;

        [DllImport("shcore.dll")]
        private static extern int SetProcessDpiAwareness(int value);

        [DllImport("user32.dll")]
        private static extern bool SetProcessDPIAware();

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSEnableChildSessions(bool bEnable);

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSIsChildSessionsEnabled(out bool pbEnabled);

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSGetChildSessionId(out uint pSessionId);

        [DllImport("kernel32.dll")]
        private static extern bool AttachConsole(int dwProcessId);

        private static bool QueryChildEnabled()
        {
            bool en = false;
            try { WTSIsChildSessionsEnabled(out en); } catch { }
            return en;
        }

        private static int QueryChildSessionId()
        {
            uint sid = 0xFFFFFFFF;
            try
            {
                if (WTSGetChildSessionId(out sid) && sid != 0xFFFFFFFF)
                    return (int)sid;
            }
            catch { }
            return -1;
        }

        private static void StartStatusServer(ChildHostForm form)
        {
            var t = new Thread(() =>
            {
                try
                {
                    var listener = new TcpListener(IPAddress.Loopback, STATUS_PORT);
                    listener.Start();
                    while (true)
                    {
                        TcpClient cli = listener.AcceptTcpClient();
                        try
                        {
                            using (cli)
                            using (NetworkStream ns = cli.GetStream())
                            {
                                string safeErr = (form.LastError ?? "").Replace("\\", "\\\\").Replace("\"", "'").Replace("\r", " ").Replace("\n", " ");
                                string safeEvt = (form.LastEvent ?? "").Replace("\\", "\\\\").Replace("\"", "'");
                                string json = "{\"ok\":true,\"child_enabled\":" + (QueryChildEnabled() ? "true" : "false") +
                                              ",\"child_sid\":" + QueryChildSessionId() +
                                              ",\"connected\":" + (form.IsConnected ? "true" : "false") +
                                              ",\"state\":" + form.ConnState +
                                              ",\"last_event\":\"" + safeEvt + "\"" +
                                              ",\"disc_reason\":" + form.LastDiscReason +
                                              ",\"last_error\":\"" + safeErr + "\"}\n";
                                byte[] b = Encoding.UTF8.GetBytes(json);
                                ns.Write(b, 0, b.Length);
                                ns.Flush();
                            }
                        }
                        catch { }
                    }
                }
                catch { }
            });
            t.IsBackground = true;
            t.Start();
        }

        [STAThread]
        public static int Main(string[] args)
        {
            if (args != null && args.Length > 0)
            {
                string a = args[0].Trim().ToLowerInvariant();
                AttachConsole(-1);
                if (a == "--enable")
                {
                    bool ok = WTSEnableChildSessions(true);
                    int err = ok ? 0 : Marshal.GetLastWin32Error();
                    bool en = QueryChildEnabled();
                    Console.WriteLine("{\"ok\":" + (ok && en ? "true" : "false") + ",\"enabled\":" + (en ? "true" : "false") + ",\"err\":" + err + "}");
                    return (ok && en) ? 0 : 1;
                }
                if (a == "--disable")
                {
                    bool ok = WTSEnableChildSessions(false);
                    int err = ok ? 0 : Marshal.GetLastWin32Error();
                    bool en = QueryChildEnabled();
                    Console.WriteLine("{\"ok\":" + (ok && !en ? "true" : "false") + ",\"enabled\":" + (en ? "true" : "false") + ",\"err\":" + err + "}");
                    return (ok && !en) ? 0 : 1;
                }
                if (a == "--status")
                {
                    Console.WriteLine("{\"ok\":true,\"enabled\":" + (QueryChildEnabled() ? "true" : "false") + ",\"child_sid\":" + QueryChildSessionId() + "}");
                    return 0;
                }
            }

            try { SetProcessDpiAwareness(2); }
            catch { try { SetProcessDPIAware(); } catch { } }

            if (!QueryChildEnabled())
            {
                return 3;
            }

            // Tuyệt đối không tự tạo Child Session lồng bên trong chính Child Session!
            int mySid = Process.GetCurrentProcess().SessionId;
            int existingChildSid = QueryChildSessionId();
            if (existingChildSid > 0 && existingChildSid == mySid)
            {
                return 0;
            }

            bool createdNew = false;
            _singleInstanceMutex = new Mutex(true, "Global\\MacWebKeyboard_ChildHost_v1", out createdNew);
            if (!createdNew)
            {
                return 0;
            }

            Application.EnableVisualStyles();
            var form = new ChildHostForm(2248, 1080, 125);
            StartStatusServer(form);
            Application.Run(form);
            return 0;
        }
    }
}
