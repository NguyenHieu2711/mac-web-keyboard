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
            [In] ref object pVariant);

        void get_Property(
            [In, MarshalAs(UnmanagedType.BStr)] string bstrPropertyName,
            [Out] out object pVariant);
    }

    internal class RdpChildAxHost : AxHost
    {
        public RdpChildAxHost(string clsid) : base(clsid) { }
    }

    internal class ChildHostForm : Form
    {
        private const int WS_EX_TOOLWINDOW = 0x00000080;
        private const int WS_EX_NOACTIVATE = 0x08000000;

        private static readonly string[] CandidateClsids = new string[]
        {
            "1df7c823-b2d4-4b54-975a-f2ac5d7cf8b8", // MsRdpClient11NotSafeForScripting
            "a0c63c30-f08d-4ab4-907c-34905d770c7d", // MsRdpClient10NotSafeForScripting
            "8b918b82-7985-4c24-89df-c33ad2bbfbcd", // MsRdpClient9NotSafeForScripting
        };

        private RdpChildAxHost _ax;
        private System.Windows.Forms.Timer _watchTimer;
        private int _targetW;
        private int _targetH;
        private uint _targetScale;
        public volatile bool IsConnected;
        public volatile string LastError = "";

        public ChildHostForm(int width, int height, uint scalePct)
        {
            _targetW = width;
            _targetH = height;
            _targetScale = scalePct;

            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            Location = new Point(-32000, -32000);
            ClientSize = new Size(_targetW, _targetH);
            Opacity = 0.01;
            Text = "MacWebKeyboard Child Session Host";

            Load += OnFormLoad;
        }

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams cp = base.CreateParams;
                cp.ExStyle |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
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
                    var host = new RdpChildAxHost(clsid);
                    ((System.ComponentModel.ISupportInitialize)host).BeginInit();
                    host.Dock = DockStyle.Fill;
                    Controls.Add(host);
                    ((System.ComponentModel.ISupportInitialize)host).EndInit();
                    _ax = host;
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
                IsConnected = (state == 1);
                if (state == 0)
                {
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
            try
            {
                dynamic ocx = _ax.GetOcx();
                short curState = (short)ocx.Connected;
                if (curState != 0)
                {
                    IsConnected = (curState == 1);
                    return;
                }

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
                    try
                    {
                        object vCred = true;
                        ext.put_Property("EnableCredSspSupport", ref vCred);
                    }
                    catch { }
                }

                ocx.Server = "localhost";
                ocx.DesktopWidth = _targetW;
                ocx.DesktopHeight = _targetH;
                ocx.ColorDepth = 32;
                try { ocx.AdvancedSettings2.SmartSizing = false; } catch { }
                try { ocx.AdvancedSettings2.AudioRedirectionMode = 0; } catch { }
                try { ocx.AdvancedSettings2.EnableAutoReconnect = true; } catch { }

                ocx.Connect();
                LastError = "";
                IsConnected = true;
            }
            catch (Exception ex)
            {
                IsConnected = false;
                LastError = ex.Message;
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
                                string json = "{\"ok\":true,\"child_enabled\":" + (QueryChildEnabled() ? "true" : "false") +
                                              ",\"child_sid\":" + QueryChildSessionId() +
                                              ",\"connected\":" + (form.IsConnected ? "true" : "false") +
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
            _singleInstanceMutex = new Mutex(true, "Local\\MacWebKeyboard_ChildHost_v1", out createdNew);
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
