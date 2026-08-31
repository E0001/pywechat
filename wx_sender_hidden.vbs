' wx_sender 隐藏常驻启动（独立于任何终端会话）
' 用法: wscript.exe wx_sender_hidden.vbs
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\Users\kk\Desktop\xx\pywechat"
objShell.Run """C:\Users\kk\Desktop\xx\pywechat\.venv\Scripts\python.exe"" ""C:\Users\kk\Desktop\xx\pywechat\wx_sender_server.py""", 0, False
