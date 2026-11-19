using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using Microsoft.Win32;

namespace MacWebKeyboard
{
    internal static class PcUnikeySync
    {
        private const uint FILE_MAP_READ = 0x0004;
        private const uint FILE_MAP_WRITE = 0x0002;
        private const uint FILE_MAP_RDWR = FILE_MAP_READ | FILE_MAP_WRITE;

        private static readonly string[] SharedMemNames = new string[]
        {
            "UniKeyHookSharedMem 64 4.2 Release",
            "UniKeyHookSharedMem 32 4.2 Release",
            "UniKeyHookSharedMem 64 4.3 Release",
            "UniKeyHookSharedMem 32 4.3 Release",
            "UniKeyHookSharedMem 64 4.0 Release",
            "UniKeyHookSharedMem 32 4.0 Release",
            "UniKeyHookSharedMem 4.0"
        };

        private static readonly string[] CandidateUnikeyPaths = new string[]
        {
            @"C:\Program Files\UniKey\UniKeyNT.exe",
            @"C:\Program Files (x86)\UniKey\UniKeyNT.exe",
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Programs\UniKey\UniKeyNT.exe")
        };

        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
        private static extern IntPtr OpenFileMappingA(uint dwDesiredAccess, bool bInheritHandle, string lpName);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr MapViewOfFile(IntPtr hFileMappingObject, uint dwDesiredAccess, uint dwFileOffsetHigh, uint dwFileOffsetLow, UIntPtr dwNumberOfBytesToMap);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool UnmapViewOfFile(IntPtr lpBaseAddress);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr hObject);

        private static void EnsureUnikeyRunningIfNeeded(int wantVn)
        {
            if (wantVn == 0) return;
            try
            {
                Process[] procs = Process.GetProcessesByName("UniKeyNT");
                if (procs != null && procs.Length > 0) return;

                foreach (string exePath in CandidateUnikeyPaths)
                {
                    if (File.Exists(exePath))
                    {
                        ProcessStartInfo psi = new ProcessStartInfo(exePath)
                        {
                            UseShellExecute = false,
                            WorkingDirectory = Path.GetDirectoryName(exePath) ?? ""
                        };
                        Process.Start(psi);
                        for (int i = 0; i < 8; i++)
                        {
                            Thread.Sleep(50);
                            IntPtr h = OpenFileMappingA(FILE_MAP_READ, false, SharedMemNames[0]);
                            if (h != IntPtr.Zero)
                            {
                                CloseHandle(h);
                                break;
                            }
                        }
                        break;
                    }
                }
            }
            catch
            {
                // ignore
            }
        }

        private static void SaveRegistryVietnameseFlag(int wantVn)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\PkLong\UniKey"))
                {
                    if (key != null)
                    {
                        key.SetValue("Vietnamese", wantVn, RegistryValueKind.DWord);
                    }
                }
            }
            catch
            {
                // ignore
            }
        }

        private static string ApplyState(int wantVn)
        {
            int target = wantVn != 0 ? 1 : 0;
            SaveRegistryVietnameseFlag(target);
            EnsureUnikeyRunningIfNeeded(target);

            bool mappedAny = false;
            int prevVal = -1;

            foreach (string mapName in SharedMemNames)
            {
                IntPtr hMap = OpenFileMappingA(FILE_MAP_RDWR, false, mapName);
                if (hMap == IntPtr.Zero) continue;
                try
                {
                    IntPtr pView = MapViewOfFile(hMap, FILE_MAP_RDWR, 0, 0, (UIntPtr)16);
                    if (pView != IntPtr.Zero)
                    {
                        try
                        {
                            prevVal = Marshal.ReadInt32(pView, 4);
                            if (prevVal != target)
                            {
                                Marshal.WriteInt32(pView, 4, target);
                            }
                            mappedAny = true;
                        }
                        finally
                        {
                            UnmapViewOfFile(pView);
                        }
                    }
                }
                finally
                {
                    CloseHandle(hMap);
                }
            }

            return "{\"ok\":true,\"vn\":" + target + ",\"prev\":" + prevVal + ",\"mapped\":" + (mappedAny ? "true" : "false") + "}";
        }

        private static string ReadState()
        {
            foreach (string mapName in SharedMemNames)
            {
                IntPtr hMap = OpenFileMappingA(FILE_MAP_READ, false, mapName);
                if (hMap == IntPtr.Zero) continue;
                try
                {
                    IntPtr pView = MapViewOfFile(hMap, FILE_MAP_READ, 0, 0, (UIntPtr)16);
                    if (pView != IntPtr.Zero)
                    {
                        try
                        {
                            int cur = Marshal.ReadInt32(pView, 4);
                            return "{\"ok\":true,\"vn\":" + cur + ",\"mapped\":true}";
                        }
                        finally
                        {
                            UnmapViewOfFile(pView);
                        }
                    }
                }
                finally
                {
                    CloseHandle(hMap);
                }
            }
            return "{\"ok\":true,\"vn\":0,\"mapped\":false}";
        }

        public static int Main(string[] args)
        {
            if (args != null && args.Length > 0)
            {
                string a = args[0].Trim().ToLowerInvariant();
                if (a == "1" || a == "vn" || a == "true")
                {
                    Console.WriteLine(ApplyState(1));
                    return 0;
                }
                if (a == "0" || a == "en" || a == "false")
                {
                    Console.WriteLine(ApplyState(0));
                    return 0;
                }
                Console.WriteLine(ReadState());
                return 0;
            }

            string line;
            while ((line = Console.ReadLine()) != null)
            {
                string cmd = line.Trim().ToLowerInvariant();
                if (cmd.Length == 0) continue;
                if (cmd == "exit" || cmd == "quit") break;
                if (cmd == "1" || cmd == "vn" || cmd == "true")
                {
                    Console.WriteLine(ApplyState(1));
                }
                else if (cmd == "0" || cmd == "en" || cmd == "false")
                {
                    Console.WriteLine(ApplyState(0));
                }
                else
                {
                    Console.WriteLine(ReadState());
                }
                Console.Out.Flush();
            }
            return 0;
        }
    }
}
