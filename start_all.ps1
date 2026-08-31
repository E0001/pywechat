# start_all.ps1 - desktop one-click launcher for the whole wx chain
# ====================================================================
# Invoked from the desktop shortcut "微信链路一键启动.bat". Brings every
# component up in the RIGHT ORDER, skipping whatever already runs:
#   NVDA (UIA enabler, MUST precede WeChat)
#   -> WeChat (-autorun) -> frpc -> login button click (wx_login_click.py)
#   -> wx_sender (:15000) -> wx_listener
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

# 1) NVDA - must be alive BEFORE WeChat starts
if (-not (Get-Process nvda -ErrorAction SilentlyContinue)) {
    Start-Process "$env:USERPROFILE\nvda\portable\nvda.exe" -ArgumentList '--disable-speech','-m'
    Log "[1/6] NVDA 已启动, 等待 10s..."
    Start-Sleep -Seconds 10
} else {
    Log "[1/6] NVDA 已在运行"
}

# 2) WeChat
if (-not (Get-Process Weixin -ErrorAction SilentlyContinue)) {
    Start-Process 'C:\Program Files\Tencent\Weixin\Weixin.exe' -ArgumentList '-autorun'
    Log "[2/6] 微信已启动, 等待 15s..."
    Start-Sleep -Seconds 15
} else {
    Log "[2/6] 微信已在运行"
}

# 3) frpc - wx tunnel 15000
if (-not (Get-Process frpc -ErrorAction SilentlyContinue)) {
    Start-Process wscript.exe -ArgumentList '"C:\Users\kk\Desktop\frpc\frpc_hidden.vbs"'
    Log "[3/6] frpc 已启动"
} else {
    Log "[3/6] frpc 已在运行"
}

# 4) login click - auto-login still needs one button click; may take up
#    to ~4 min (waits for the login window, then waits for the main window)
Log "[4/6] 检查微信登录(可能自动点击登录按钮, 最长 4 分钟, 请稍候)..."
& $py "$dir\wx_login_click.py"
switch ($LASTEXITCODE) {
    0 { Log "[4/6] ✓ 微信已登录且 UIA 正常" }
    1 { Log "[4/6] ✗ 登录未完成(请看微信窗口, 必要时手动扫码)" }
    2 {
        Log "[4/6] ✗ 已登录但 UIA 树未激活"
        $ans = Read-Host "      尝试重启微信恢复 UIA? (y=是/N=否)"
        if ($ans -eq 'y' -or $ans -eq 'Y') {
            Log "      重启微信 (NVDA 保持运行)..."
            & taskkill /F /T /IM Weixin.exe 2>$null | Out-Null
            Start-Sleep -Seconds 5
            Start-Process 'C:\Program Files\Tencent\Weixin\Weixin.exe' -ArgumentList '-autorun'
            & $py "$dir\wx_login_click.py"
            if ($LASTEXITCODE -eq 0) { Log "      ✓ 重启后 UIA 恢复" }
            else { Log "      ✗ 重启后仍未激活(记录 start_all.log, 找 Claude 诊断)" }
        }
    }
}

# 5) wx_sender - HTTP :15000
if (-not (Get-PyScript 'wx_sender_server')) {
    Start-Process wscript.exe -ArgumentList "`"$dir\wx_sender_hidden.vbs`""
    Log "[5/6] wx_sender 已启动"
} else {
    Log "[5/6] wx_sender 已在运行"
}

# 6) wx_listener - friend messages -> server callback
if (-not (Get-PyScript 'wx_listener')) {
    Start-Process wscript.exe -ArgumentList "`"$dir\wx_listener_hidden.vbs`""
    Log "[6/6] wx_listener 已启动"
} else {
    Log "[6/6] wx_listener 已在运行"
}

Start-Sleep -Seconds 2
$healthy = Test-Path "$dir\wx_sender.log"
Log "=== 完成。端口 15000 监听: $((Get-NetTCPConnection -LocalPort 15000 -State Listen -ErrorAction SilentlyContinue) -ne $null); 详见 start_all.log ==="
