@echo off
chcp 65001 >nul
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo [!] Vui long bam CHUOT PHAI vao file nay va chon "Run as administrator" 1 lan duy nhat!
  pause
  exit /b 1
)

echo [1/4] Dang bat Windows Child Sessions chinh chu (WTSEnableChildSessions)...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class WtsEn { [DllImport(\"wtsapi32.dll\", SetLastError=true)] public static extern bool WTSEnableChildSessions(bool b); [DllImport(\"wtsapi32.dll\", SetLastError=true)] public static extern bool WTSIsChildSessionsEnabled(out bool b); }'; $ok = [WtsEn]::WTSEnableChildSessions($true); $en = $false; [void][WtsEn]::WTSIsChildSessionsEnabled([ref]$en); Write-Host ('WTSEnable=' + $ok + ' Enabled=' + $en); if (-not $en) { exit 1 }"
if %errorlevel% neq 0 (
  echo [!] Khong bat duoc Child Sessions.
  pause
  exit /b 1
)

echo [2/4] Dang cap nhat tu khoi dong (Startup) cho Child Session + Streamer + Gateway...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_autostart_pc.ps1"

echo [3/4] Dang khoi chay Desktop con doc lap 2248x1080 @ 125%% cho Dien thoai...
explorer.exe "%~dp0start_pc_gateway_hidden.vbs"
timeout /t 5 /nobreak >nul

echo [4/4] Kiem tra trang thai truc tiep:
powershell.exe -NoProfile -Command "try { Invoke-RestMethod -Uri 'http://127.0.0.1:5051/rdp-mode-check' -TimeoutSec 3 | ConvertTo-Json -Compress } catch { $_.Exception.Message }"
echo.
echo [OK] DA BAT CHILD SESSIONS THANH CONG!
echo [!] LUU Y QUAN TRONG (chi can lam 1 lan duy nhat):
echo     Hay DANG XUAT (Sign out) Windows roi DANG NHAP LAI (hoac Restart PC 1 lan)
echo     de Windows cap quyen tu dang nhap cho Desktop con doc lap (khong hoi mat khau).
echo     Sau khi dang nhap lai, he thong se tu dong khoi chay va ket noi 2248x1080 @ 125%%!
pause
