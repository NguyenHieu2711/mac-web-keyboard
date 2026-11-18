@echo off
powershell -NoProfile -ExecutionPolicy Bypass -Command "$gw = Join-Path $PSScriptRoot 'pc_rdp_gateway.js'; $vbs = Join-Path ([Environment]::GetFolderPath('Startup')) 'MacWebKeyboard_PC_Gateway.vbs'; $code = 'Set WshShell = CreateObject(\"WScript.Shell\")' + [Environment]::NewLine + 'WshShell.Run \"node \"\"' + $gw + '\"\"\", 0, False'; [System.IO.File]::WriteAllText($vbs, $code, [System.Text.Encoding]::Unicode); Start-Process wscript.exe -ArgumentList ('\"' + $vbs + '\"')"
echo Da bat chay ngam tu dong cung Windows PC (cong 5051)!
