using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
internal class MMDeviceEnumeratorComObj {}

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, int dwStateMask, out IntPtr ppDevices);
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppEndpoint);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMMDevice {
    int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
}

[Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IAudioClient {
    int Initialize(int ShareMode, uint StreamFlags, long hnsBufferDuration, long hnsPeriodicity, IntPtr pFormat, IntPtr AudioSessionGuid);
    int GetBufferSize(out uint pNumBufferFrames);
    int GetStreamLatency(out long phnsLatency);
    int GetCurrentPadding(out uint pNumPaddingFrames);
    int IsFormatSupported(int ShareMode, IntPtr pFormat, out IntPtr ppClosestMatch);
    int GetMixFormat(out IntPtr ppDeviceFormat);
    int GetDevicePeriod(out long phnsDefaultDevicePeriod, out long phnsMinimumDevicePeriod);
    int Start();
    int Stop();
    int Reset();
    int SetEventHandle(IntPtr eventHandle);
    int GetService(ref Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object ppv);
}

[Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IAudioCaptureClient {
    int GetBuffer(out IntPtr ppData, out uint pNumFramesToRead, out uint pdwFlags, out ulong pu64DevicePosition, out ulong pu64QPCPosition);
    int ReleaseBuffer(uint NumFramesRead);
    int GetNextPacketSize(out uint pNumFramesInNextPacket);
}

internal static class Program {
    private static Guid IID_IAudioClient = new Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2");
    private static Guid IID_IAudioCaptureClient = new Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317");

    public static int Main() {
        Stream stdout = Console.OpenStandardOutput();
        while (true) {
            IntPtr mixFmt = IntPtr.Zero;
            IAudioClient audioClient = null;
            try {
                var enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObj());
                IMMDevice dev;
                if (enumerator.GetDefaultAudioEndpoint(0, 0, out dev) != 0 || dev == null) {
                    Thread.Sleep(1000);
                    continue;
                }
                object objClient;
                if (dev.Activate(ref IID_IAudioClient, 23, IntPtr.Zero, out objClient) != 0 || objClient == null) {
                    Thread.Sleep(1000);
                    continue;
                }
                audioClient = (IAudioClient)objClient;
                if (audioClient.GetMixFormat(out mixFmt) != 0 || mixFmt == IntPtr.Zero) {
                    Thread.Sleep(1000);
                    continue;
                }

                ushort wFormatTag = (ushort)Marshal.ReadInt16(mixFmt, 0);
                ushort nChannels = (ushort)Marshal.ReadInt16(mixFmt, 2);
                int nSamplesPerSec = Marshal.ReadInt32(mixFmt, 4);
                ushort nBlockAlign = (ushort)Marshal.ReadInt16(mixFmt, 12);
                ushort wBitsPerSample = (ushort)Marshal.ReadInt16(mixFmt, 14);
                bool isFloat = (wFormatTag == 3);
                if (wFormatTag == 0xFFFE) {
                    ushort subTag = (ushort)Marshal.ReadInt16(mixFmt, 24);
                    isFloat = (subTag == 3);
                }

                ushort outCh = (ushort)(nChannels >= 2 ? 2 : 1);
                byte[] hdr = new byte[8];
                hdr[0] = (byte)'W'; hdr[1] = (byte)'A'; hdr[2] = (byte)'S'; hdr[3] = (byte)'P';
                hdr[4] = (byte)(nSamplesPerSec & 0xFF);
                hdr[5] = (byte)((nSamplesPerSec >> 8) & 0xFF);
                hdr[6] = (byte)(outCh & 0xFF);
                hdr[7] = 0;
                stdout.Write(hdr, 0, 8);
                stdout.Flush();

                if (audioClient.Initialize(0, 0x00020000, 400000, 0, mixFmt, IntPtr.Zero) != 0) {
                    Thread.Sleep(1000);
                    continue;
                }
                object objCap;
                if (audioClient.GetService(ref IID_IAudioCaptureClient, out objCap) != 0 || objCap == null) {
                    Thread.Sleep(1000);
                    continue;
                }
                var cap = (IAudioCaptureClient)objCap;
                audioClient.Start();

                byte[] rawBuf = new byte[65536];
                byte[] outBuf = new byte[32768];

                while (true) {
                    uint packetFrames = 0;
                    int hr = cap.GetNextPacketSize(out packetFrames);
                    if (hr != 0) break;
                    if (packetFrames == 0) {
                        Thread.Sleep(8);
                        continue;
                    }
                    while (packetFrames > 0) {
                        IntPtr pData;
                        uint numFrames, flags;
                        ulong devPos, qpcPos;
                        hr = cap.GetBuffer(out pData, out numFrames, out flags, out devPos, out qpcPos);
                        if (hr != 0) { packetFrames = 0; break; }

                        bool silent = (flags & 0x2) != 0;
                        if (!silent && numFrames > 0 && pData != IntPtr.Zero) {
                            int srcBytes = (int)numFrames * nBlockAlign;
                            if (rawBuf.Length < srcBytes) rawBuf = new byte[srcBytes];
                            Marshal.Copy(pData, rawBuf, 0, srcBytes);

                            int outBytes = (int)numFrames * outCh * 2;
                            if (outBuf.Length < 2 + outBytes) outBuf = new byte[2 + outBytes];
                            outBuf[0] = (byte)(outBytes & 0xFF);
                            outBuf[1] = (byte)((outBytes >> 8) & 0xFF);

                            int dstOff = 2;
                            bool nonZero = false;
                            for (int f = 0; f < (int)numFrames; f++) {
                                int fOff = f * nBlockAlign;
                                for (int c = 0; c < outCh; c++) {
                                    int chIdx = c < nChannels ? c : 0;
                                    short pcmVal = 0;
                                    if (isFloat && wBitsPerSample == 32) {
                                        float fv = BitConverter.ToSingle(rawBuf, fOff + chIdx * 4);
                                        if (fv > 1.0f) fv = 1.0f;
                                        else if (fv < -1.0f) fv = -1.0f;
                                        pcmVal = (short)(fv * 32767.0f);
                                    } else if (wBitsPerSample == 16) {
                                        pcmVal = BitConverter.ToInt16(rawBuf, fOff + chIdx * 2);
                                    }
                                    if (pcmVal > 3 || pcmVal < -3) nonZero = true;
                                    outBuf[dstOff] = (byte)(pcmVal & 0xFF);
                                    outBuf[dstOff + 1] = (byte)((pcmVal >> 8) & 0xFF);
                                    dstOff += 2;
                                }
                            }
                            if (nonZero) {
                                int offset = 0;
                                int rem = outBytes;
                                while (rem > 0) {
                                    int chunk = Math.Min(rem, 8192);
                                    byte[] lenHdr = new byte[] { (byte)(chunk & 0xFF), (byte)((chunk >> 8) & 0xFF) };
                                    stdout.Write(lenHdr, 0, 2);
                                    stdout.Write(outBuf, 2 + offset, chunk);
                                    offset += chunk;
                                    rem -= chunk;
                                }
                                stdout.Flush();
                            }
                        }
                        cap.ReleaseBuffer(numFrames);
                        if (cap.GetNextPacketSize(out packetFrames) != 0) break;
                    }
                }
            } catch (IOException) {
                return 0;
            } catch {
                Thread.Sleep(1000);
            } finally {
                if (audioClient != null) {
                    try { audioClient.Stop(); } catch {}
                }
                if (mixFmt != IntPtr.Zero) Marshal.FreeCoTaskMem(mixFmt);
            }
        }
    }
}
