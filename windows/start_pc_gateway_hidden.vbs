Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
GatewayJs = ScriptDir & "\pc_rdp_gateway.js"
WshShell.Run "node """ & GatewayJs & """", 0, False
