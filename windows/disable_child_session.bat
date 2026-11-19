@echo off
chcp 65001 >nul
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo [!] Vui long bam chuot phai vao file nay va chon "Run as administrator"!
  pause
  exit /b 1
)
echo Dang tat Windows Child Sessions ve mac dinh...
"%~dp0pc_child_host.exe" --disable
echo [OK] Da tat va hoan tac ve mac dinh ban dau.
pause
