$ErrorActionPreference = 'Stop'
$gw = Join-Path $PSScriptRoot 'pc_rdp_gateway.js'
$nodeExe = (Get-Command node).Source
$startupDir = [Environment]::GetFolderPath('Startup')
$vbsPath = Join-Path $startupDir 'MacWebKeyboard_PC_Gateway.vbs'

$vbsContent = @(
    'Set WshShell = CreateObject("WScript.Shell")',
    ('WshShell.Run """' + $nodeExe + '"" ""' + $gw + '""", 0, False')
) -join "`r`n"

[System.IO.File]::WriteAllText($vbsPath, $vbsContent, [System.Text.Encoding]::Unicode)
Start-Process -FilePath 'wscript.exe' -ArgumentList ('"' + $vbsPath + '"')
Write-Host "PC RDP Gateway autostart enabled on port 5051: $vbsPath"
