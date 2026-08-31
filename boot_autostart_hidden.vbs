' wx_boot 隐藏常驻启动（独立于任何终端会话）
' 用法: wscript.exe boot_autostart_hidden.vbs
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\Users\kk\Desktop\xx\pywechat"
objShell.Run "powershell -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\kk\Desktop\xx\pywechat\boot_autostart.ps1""", 0, False
