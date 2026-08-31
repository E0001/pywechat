# 开机自启任务注册（当前用户登录触发，隐藏窗口）。幂等：重复执行先删旧再注册。
#
# ⚠️ 2026-09-01 架构变更（UIA 污染根因后）：
#   - wx_boot_autostart 是唯一的编排者：等微信自启+登录+树活之后，
#     由 boot_autostart.ps1 第 5 步拉起 wx_sender / wx_listener。
#   - 独立的 wx_sender_autostart / wx_listener_autostart 任务已废弃
#     （它们与微信并行抢跑是 2026-09-01 事故的帮凶，尽管服务自身已有
#     wait_wechat_ready 闸门，删除独立任务可消除双启动）。
#   - NVDA 已彻底退役（8/17 起 --no-speech 参数无效从未启动成功过，
#     与微信 UIA 树无关），勿再加回。
#   - 微信自身 HKCU Run 自启项必须保留（"Weixin -autorun"），
#     它是微信启动的正主，boot 链只等它、不抢它。
#
# 需提权运行（否则先删后建失败）。
$tasks = @(
    @{ Name = 'wx_boot_autostart'; Vbs = 'C:\Users\kk\Desktop\xx\pywechat\boot_autostart_hidden.vbs' }
)
# 废弃任务：存在即删除（提权后 schtasks /change /disable 失败也会被
# Delete /F 移除；此脚本本来就提权跑，删除比禁用干净）
$dead = @('wx_sender_autostart', 'wx_listener_autostart')
foreach ($n in $dead) {
    schtasks /Query /TN $n 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        schtasks /Delete /TN $n /F | Out-Null
        Write-Host "removed deprecated task: $n"
    }
}
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
