$ErrorActionPreference = 'Stop'
$gw = Join-Path $PSScriptRoot 'pc_rdp_gateway.js'
$streamer = Join-Path $PSScriptRoot 'pc_console_streamer.exe'
$childHost = Join-Path $PSScriptRoot 'pc_child_host.exe'
$nodeExe = (Get-Command node).Source
$startupDir = [Environment]::GetFolderPath('Startup')
$vbsPath = Join-Path $startupDir 'MacWebKeyboard_PC_Gateway.vbs'

$vbsContent = @(
    'Set WshShell = CreateObject("WScript.Shell")',
    ('WshShell.Run """' + $childHost + '""", 0, False'),
    ('WshShell.Run """' + $streamer + '""", 0, False'),
    ('WshShell.Run """' + $nodeExe + '"" ""' + $gw + '""", 0, False')
) -join "`r`n"

[System.IO.File]::WriteAllText($vbsPath, $vbsContent, [System.Text.Encoding]::Unicode)
Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $vbsPath + '"')
Write-Host "PC Gateway, Child Session Host & Streamer autostart enabled on ports 5051/5052/5053: $vbsPath"
