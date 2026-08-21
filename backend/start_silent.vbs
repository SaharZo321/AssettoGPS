Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Coding\AssettoMiniMap"
WshShell.Run """C:\Coding\AssettoMiniMap\.venv\Scripts\python.exe"" ""C:\Coding\AssettoMiniMap\backend\server.py""", 0, False
