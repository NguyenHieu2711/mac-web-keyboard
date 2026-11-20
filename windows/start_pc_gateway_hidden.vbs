Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
GuardExe = ScriptDir & "\pc_display_layout_guard.exe"
StreamerExe = ScriptDir & "\pc_console_streamer.exe"
GatewayJs = ScriptDir & "\pc_rdp_gateway.js"
If FSO.FileExists(GuardExe) Then
  WshShell.Run """" & GuardExe & """", 0, False
End If
If FSO.FileExists(StreamerExe) Then
  WshShell.Run """" & StreamerExe & """", 0, False
End If
WshShell.Run "node """ & GatewayJs & """", 0, False
