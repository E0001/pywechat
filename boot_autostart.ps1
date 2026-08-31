# boot_autostart.ps1 - ordered boot chain for the wx automation stack
# ====================================================================
# Registered as scheduled task 'wx_boot_autostart' (ONLOGON, LIMITED,
# hidden via boot_autostart_hidden.vbs). Idempotent: safe to re-run.
#
# ORDER MATTERS (WRONG in 2026-08-31→09-01 incident, fixed 09-01):
# WeChat is launched by ITS OWN HKCU Run entry again ("Weixin -autorun"),
# restored after the "NVDA must precede WeChat" theory was disproven -
# NVDA's launch param was invalid (--no-speech) since 2026-08-17 day one,
# so NVDA never auto-started during the 14 days the chain worked fine.
# NVDA is RETIRED entirely: a running NVDA neither helps nor hurts the
# UIA tree, and its error dialogs (unknown param) were noise.
#
# Chain: WeChat (own Run entry, auto-login) -> this script waits for it
#        (45s, starts it as fallback) -> frpc tunnel (wx 15000)
#        -> wx_login_click.py
#        (login button click LAST: it blocks up to ~4 min waiting for the
#        login window, frpc must not wait behind it).
# wx_sender / wx_listener / rdp_keepalive have their own ONLOGON tasks
# and keep retrying until WeChat is ready, so they can start in any
# order relative to this chain.

$ErrorActionPreference = 'Continue'
$log = 'C:\Users\kk\Desktop\xx\pywechat\boot_autostart.log'

function Log([string]$m) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -FilePath $log -Append -Encoding utf8
}

try {
    if ((Get-Item $log -ErrorAction SilentlyContinue).Length -gt 100KB) {
        Remove-Item $log -Force
    }
} catch {}

# 1) WeChat - its own HKCU Run entry ("Weixin -autorun") fires at logon.
#    Wait for it; start as fallback only if it somehow did not run.
$deadline = (Get-Date).AddSeconds(45)
while (-not (Get-Process -Name Weixin -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
}
if (-not (Get-Process -Name Weixin -ErrorAction SilentlyContinue)) {
    Start-Process 'C:\Program Files\Tencent\Weixin\Weixin.exe' -ArgumentList '-autorun'
    Log 'WeChat not started by its Run entry, fallback start'
    Start-Sleep -Seconds 15
} else {
    Log 'WeChat started (own Run entry)'
}

# 3) frpc - wx tunnel 15000 (server 127.0.0.1:15000 -> this machine).
#    Independent of WeChat; started here because nothing else owns its
#    autostart (the legacy "port forward" scheduled tasks are dead).
if (-not (Get-Process -Name frpc -ErrorAction SilentlyContinue)) {
    Start-Process 'wscript.exe' -ArgumentList '"C:\Users\kk\Desktop\frpc\frpc_hidden.vbs"'
    Log 'frpc launched via frpc_hidden.vbs'
} else {
    Log 'frpc already running'
}

# 4) login click - auto-login still shows an "Enter WeChat" button that
#    must be clicked once. Single-pass, never kills WeChat (account
#    safety). Exit 2 = UIA tree dead: do NOT retry here (2026-09-01
#    incident: retrying WeChat restarts with UIA clients running
#    poisons the tree - see DEPLOY_WX_SENDER.md "UIA 树加载时序").
$py = 'C:\Users\kk\Desktop\xx\pywechat\.venv\Scripts\python.exe'
$clicker = 'C:\Users\kk\Desktop\xx\pywechat\wx_login_click.py'
$loginExit = 1
if ((Test-Path $py -PathType Leaf) -and (Test-Path $clicker -PathType Leaf)) {
    Log 'wx_login_click starting'
    $out = & $py $clicker 2>&1
    $out | ForEach-Object { Log "[login] $_" }
    $loginExit = $LASTEXITCODE
    Log "wx_login_click exit=$LASTEXITCODE"
} else {
    Log 'WARN: venv python or wx_login_click.py missing, login button not clicked'
}

# 5) wx_sender + wx_listener - ONLY after WeChat login/UIA is up.
#    2026-09-01 root cause: a UIA client (listener retry loop) alive at
#    WeChat's startup moment makes WeChat refuse to load its full UIA
#    tree. Services must never race WeChat at boot. Their legacy ONLOGON
#    tasks (wx_sender_autostart/wx_listener_autostart) are superseded
#    by this gate - disable them via setup_autostart.ps1.
function Get-PyScript([string]$pattern) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern }
}
if ($loginExit -eq 0) {
    if (-not (Get-PyScript 'wx_sender_server')) {
        Start-Process wscript.exe -ArgumentList '"C:\Users\kk\Desktop\xx\pywechat\wx_sender_hidden.vbs"'
        Log 'wx_sender launched (after WeChat UIA up)'
    } else { Log 'wx_sender already running' }
    Start-Sleep -Seconds 5
    if (-not (Get-PyScript 'wx_listener')) {
        Start-Process wscript.exe -ArgumentList '"C:\Users\kk\Desktop\xx\pywechat\wx_listener_hidden.vbs"'
        Log 'wx_listener launched (after WeChat UIA up)'
    } else { Log 'wx_listener already running' }
} else {
    Log "login exit=$loginExit, services NOT started (WeChat not ready; fix login first)"
}

Log 'boot chain done'
