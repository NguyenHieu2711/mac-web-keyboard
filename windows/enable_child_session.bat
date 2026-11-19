@echo off
chcp 65001 >nul
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo [!] Vui long bam chuot phai vao file nay va chon "Run as administrator" 1 lan duy nhat!
  pause
  exit /b 1
)
echo [1/3] Dang bat Windows Child Sessions chinh chu (WTSEnableChildSessions)...
"%~dp0pc_child_host.exe" --enable
if %errorlevel% neq 0 (
  echo [!] Khong bat duoc Child Sessions. Kiem tra quyen Administrator.
  pause
  exit /b 1
)
echo [2/3] Dang cap nhat tu khoi dong (Startup) cho Child Session + Gateway...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_autostart_pc.ps1"
echo [3/3] Dang khoi chay Desktop con doc lap 2248x1080 @ 125%% cho Dien thoai...
explorer.exe "%~dp0start_pc_gateway_hidden.vbs"
timeout /t 3 /nobreak >nul
echo.
echo [OK] HOAN TAT! Dien thoai gio chay Desktop con doc lap 100%% (2248x1080 @ 125%%), khong chung tuong tac voi MacBook hay PC chinh!
pause
