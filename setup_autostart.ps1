# wx_sender + wx_listener + wx_boot 开机自启（当前用户登录时，隐藏窗口）
# 幂等：重复执行先删除旧任务再注册
# wx_boot_autostart 负责 NVDA→微信→frpc 的顺序启动（微信自身 Run 自启项
# 已删除，避免微信抢在 NVDA 前启动导致 UIA 失活——见 boot_autostart.ps1）
$tasks = @(
    @{ Name = 'wx_boot_autostart'; Vbs = 'C:\Users\kk\Desktop\xx\pywechat\boot_autostart_hidden.vbs' },
    @{ Name = 'wx_sender_autostart'; Vbs = 'C:\Users\kk\Desktop\xx\pywechat\wx_sender_hidden.vbs' },
    @{ Name = 'wx_listener_autostart'; Vbs = 'C:\Users\kk\Desktop\xx\pywechat\wx_listener_hidden.vbs' }
)
foreach ($t in $tasks) {
    schtasks /Query /TN $t.Name 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        schtasks /Delete /TN $t.Name /F | Out-Null
        Write-Host "removed old task: $($t.Name)"
    }
    schtasks /Create /TN $t.Name /TR "wscript.exe `"$($t.Vbs)`"" /SC ONLOGON /RL LIMITED /F | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host "created: $($t.Name) -> $($t.Vbs)" }
    else { Write-Host "FAILED: $($t.Name)" }
}
