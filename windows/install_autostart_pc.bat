@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$gw = Join-Path $env:SCRIPT_DIR 'pc_rdp_gateway.js'; $nodeExe = (Get-Command node).Source; $vbs = Join-Path ([Environment]::GetFolderPath('Startup')) 'MacWebKeyboard_PC_Gateway.vbs'; $code = 'Set WshShell = CreateObject(\"WScript.Shell\")' + [Environment]::NewLine + 'WshShell.Run \"\"\"' + $nodeExe + '\"\" \"\"' + $gw + '\"\"\", 0, False'; [System.IO.File]::WriteAllText($vbs, $code, [System.Text.Encoding]::Unicode); Start-Process wscript.exe -ArgumentList ('\"' + $vbs + '\"')"
echo Đã bật chạy ngầm tự động cùng Windows PC (cổng 5051)!
