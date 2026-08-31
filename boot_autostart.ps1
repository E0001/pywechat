# boot_autostart.ps1 - ordered boot chain for the wx automation stack
# ====================================================================
# Registered as scheduled task 'wx_boot_autostart' (ONLOGON, LIMITED,
# hidden via boot_autostart_hidden.vbs). Idempotent: safe to re-run.
#
# ORDER MATTERS: NVDA must be running BEFORE WeChat launches, because
# WeChat exposes its UIA tree only when its login window is created with
# a screen reader active (DEPLOY_WX_SENDER.md step 3). WeChat's own
# registry Run entry ("Weixin ... -autorun") was deleted so this script
# is the single launcher and there is no race at logon.
#
# Chain: NVDA -> 10s -> WeChat (auto-login, enabled on phone side)
#        -> 15s -> frpc tunnel (wx 15000).
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

# 1) NVDA - UIA enabler, must precede WeChat
if (-not (Get-Process -Name nvda -ErrorAction SilentlyContinue)) {
    Start-Process 'C:\Users\kk\nvda\portable\nvda.exe' -ArgumentList '--no-speech','-m'
    Log 'NVDA started, wait 10s before WeChat'
    Start-Sleep -Seconds 10
} else {
    Log 'NVDA already running'
}

# 2) WeChat - launched here (not via its own Run entry) so it never
#    races ahead of NVDA. Auto-login logs in without QR scan.
if (-not (Get-Process -Name Weixin -ErrorAction SilentlyContinue)) {
    Start-Process 'C:\Program Files\Tencent\Weixin\Weixin.exe' -ArgumentList '-autorun'
    Log 'WeChat launched (auto-login enabled)'
    Start-Sleep -Seconds 15
} else {
    Log 'WeChat already running'
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

Log 'boot chain done'
