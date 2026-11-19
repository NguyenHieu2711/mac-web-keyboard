@echo off
chcp 65001 >nul
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo [!] Vui long bam CHUOT PHAI vao file nay va chon "Run as administrator"!
  pause
  exit /b 1
)
echo Dang tat Windows Child Sessions ve mac dinh...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class WtsDis { [DllImport(\"wtsapi32.dll\", SetLastError=true)] public static extern bool WTSEnableChildSessions(bool b); [DllImport(\"wtsapi32.dll\", SetLastError=true)] public static extern bool WTSIsChildSessionsEnabled(out bool b); }'; [void][WtsDis]::WTSEnableChildSessions($false); $en = $true; [void][WtsDis]::WTSIsChildSessionsEnabled([ref]$en); Write-Host ('Enabled=' + $en)"
echo [OK] Da tat va hoan tac ve mac dinh ban dau.
pause
