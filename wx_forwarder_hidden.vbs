' wx_forwarder 隐藏常驻启动（chatlog webhook -> coinMarker 回调转发）
' 用法: wscript.exe wx_forwarder_hidden.vbs
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\Users\kk\Desktop\xx\pywechat"
objShell.Run """C:\Users\kk\Desktop\xx\pywechat\.venv\Scripts\python.exe"" ""C:\Users\kk\Desktop\xx\pywechat\wx_forwarder.py""", 0, False
