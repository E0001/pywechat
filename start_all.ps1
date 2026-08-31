# start_all.ps1 - desktop one-click launcher for the whole wx chain
# ====================================================================
# Invoked from the desktop shortcut "微信链路一键启动.bat". Brings every
# component up in the RIGHT ORDER, skipping whatever already runs:
#   WeChat (-autorun) -> frpc -> login button click (wx_login_click.py)
#   -> wx_sender (:15000) -> wx_listener
# NVDA RETIRED (2026-09-01): it never auto-started successfully during the
# 14 working days (--no-speech param bug) and proved irrelevant to the
# UIA tree. Do NOT add it back.
# Idempotent: safe to double-click any time. Log: start_all.log.

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = "$dir\start_all.log"
$py  = "$dir\.venv\Scripts\python.exe"

function Log($m) {
    Write-Host $m
    try { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Add-Content -Encoding UTF8 $log } catch {}
}

function Get-PyScript($pattern) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern }
}

Log "=== 一键启动开始 ==="

# 1) WeChat (if not running - normally its own Run entry handles logon)
if (-not (Get-Process Weixin -ErrorAction SilentlyContinue)) {
    # 微信不在跑: 若服务还活着必须先停——微信 UIA 树初始化期间有 UIA
    # 客户端在场会永久毒死树(2026-09-01 事故, 见 DEPLOY_WX_SENDER.md),
    # 顺序绝不可反。停掉的服务由步骤 4/5 在树活后重新拉起。
    $svc = Get-PyScript 'wx_sender_server|wx_listener'
    if ($svc) {
        Log "[1/5] 微信未运行, 先停 wx_sender/wx_listener (防 UIA 污染)..."
        $svc | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 3
    }
    Start-Process 'C:\Program Files\Tencent\Weixin\Weixin.exe' -ArgumentList '-autorun'
    Log "[1/5] 微信已启动, 等待 15s..."
    Start-Sleep -Seconds 15
} else {
    Log "[1/5] 微信已在运行"
}

# 2) frpc - wx tunnel 15000
if (-not (Get-Process frpc -ErrorAction SilentlyContinue)) {
    Start-Process wscript.exe -ArgumentList '"C:\Users\kk\Desktop\frpc\frpc_hidden.vbs"'
    Log "[2/5] frpc 已启动"
} else {
    Log "[2/5] frpc 已在运行"
}

# 3) login click - auto-login still needs one button click; may take up
#    to ~4 min (waits for the login window, then waits for the main window)
Log "[3/5] 检查微信登录(可能自动点击登录按钮, 最长 4 分钟, 请稍候)..."
& $py "$dir\wx_login_click.py"
switch ($LASTEXITCODE) {
    0 { Log "[3/5] ✓ 微信已登录且 UIA 正常" }
    1 { Log "[3/5] ✗ 登录未完成(请看微信窗口, 必要时手动扫码)" }
    2 {
        Log "[3/5] ✗ 已登录但 UIA 树未激活"
        $ans = Read-Host "      尝试重启微信恢复 UIA? (y=是/N=否)"
        if ($ans -eq 'y' -or $ans -eq 'Y') {
            # 2026-09-01 根因: 微信启动瞬间若有持有 UIA 连接/疯狂重试的
            # 客户端进程(wx_sender/wx_listener)在场, 微信拒绝加载完整 UIA 树。
            # 重启微信前必须先停服务, 树活之后才能放行, 顺序绝不可反!
            Log "      先停 wx_sender/wx_listener (防 UIA 污染)..."
            Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -match 'wx_sender_server|wx_listener' } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Start-Sleep -Seconds 3
            Log "      重启微信..."
            & taskkill /F /T /IM Weixin.exe 2>$null | Out-Null
            Start-Sleep -Seconds 5
            Start-Process 'C:\Program Files\Tencent\Weixin\Weixin.exe' -ArgumentList '-autorun'
            & $py "$dir\wx_login_click.py"
            if ($LASTEXITCODE -eq 0) {
                Log "      ✓ 重启后 UIA 恢复, 重新拉起服务..."
                Start-Process wscript.exe -ArgumentList "`"$dir\wx_sender_hidden.vbs`""
                Start-Sleep -Seconds 5
                Start-Process wscript.exe -ArgumentList "`"$dir\wx_listener_hidden.vbs`""
            }
            else { Log "      ✗ 重启后仍未激活(记录 start_all.log, 找 Claude 诊断)" }
        }
    }

# 4) wx_sender - HTTP :15000
if (-not (Get-PyScript 'wx_sender_server')) {
    Start-Process wscript.exe -ArgumentList "`"$dir\wx_sender_hidden.vbs`""
    Log "[4/5] wx_sender 已启动"
} else {
    Log "[4/5] wx_sender 已在运行"
}

# 5) wx_listener - friend messages -> server callback
if (-not (Get-PyScript 'wx_listener')) {
    Start-Process wscript.exe -ArgumentList "`"$dir\wx_listener_hidden.vbs`""
    Log "[5/5] wx_listener 已启动"
} else {
    Log "[5/5] wx_listener 已在运行"
}

Start-Sleep -Seconds 3
Log "=== 链路健康检查 ==="
& $py "$dir\wx_health.py"
Log "=== 一键启动完成 (健康检查 exit=$LASTEXITCODE; 0=链路正常) ==="
