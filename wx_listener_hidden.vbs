Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\Users\kk\Desktop\xx\pywechat"
objShell.Run """C:\Users\kk\Desktop\xx\pywechat\.venv\Scripts\python.exe"" ""C:\Users\kk\Desktop\xx\pywechat\wx_listener.py""", 0, False
