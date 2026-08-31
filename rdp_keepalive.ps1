# rdp_keepalive.ps1 - RDP minimized/disconnected -> tscon session to physical console
# =====================================================================
# wx_sender mouse automation requires an interactive desktop. A minimized
# or disconnected RDP client leaves the session alive but its input desktop
# dead (SetCursorPos -> "no active desktop"); 2026-08-31 21:23 messages
# were received but replies all failed for exactly this reason.
#
# Every 15s probe the desktop; when not interactive, unconditionally run:
#   tscon <sessionId> /dest:console
# -> the session re-attaches to the physical console and stays interactive.
# Reconnecting via RDP moves it back; minimizing again makes this script
# switch again. Do NOT gate on the session name: a DISCONNECTED session
# row in qwinsta has an EMPTY session-name column, so name-based matching
# missed it (2026-08-31 22:27 outage: dead desktop for 5+ min because the
# name resolved to the username 'kk' instead of 'rdp-tcp*').
#
# Limit: a locked console (Win+L) cannot be auto-recovered; tscon fails,
# throttled log every 10 min.
# Deploy: scheduled task rdp_keepalive (logon trigger, highest privileges,
# hidden, no execution time limit).

$log = "$PSScriptRoot\rdp_keepalive.log"

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class MouseProbe {
    [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int x, y; }
}
"@

function Test-Desktop {
    $p = New-Object 'MouseProbe+POINT'
    if (-not [MouseProbe]::GetCursorPos([ref]$p)) { return $false }
    # write back the same coordinates (cursor does not move), probing the
    # input desktop only
    return [MouseProbe]::SetCursorPos($p.x, $p.y)
}

function Get-MySessionName {
    $id = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
    $line = (qwinsta 2>$null | Where-Object { $_ -match ("\s$id(\s|$)") } | Select-Object -First 1)
    if ($line -match '^\s*>?\s*(\S+)') { return ($Matches[1] -replace '^>', '') }
    return ''
}

function Log($m) {
    try { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Add-Content -Encoding UTF8 $log } catch {}
}

Log "keepalive start pid=$PID"
$lastNoFix = [datetime]::MinValue
while ($true) {
    try {
        if (-not (Test-Desktop)) {
            $id = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
            $name = Get-MySessionName
            $r = & tscon $id /dest:console 2>&1
            Start-Sleep -Seconds 2
            if (Test-Desktop) {
                Log "desktop dead (session=$name), tscon $id /dest:console -> recovered"
            } elseif (((Get-Date) - $lastNoFix).TotalMinutes -ge 10) {
                # tscon could not fix it (e.g. locked console): keep retrying
                # silently every cycle, log at most once per 10 minutes
                Log "desktop still dead after tscon (session=$name): $r"
                $lastNoFix = Get-Date
            }
        }
    } catch { Log "error: $_" }
    Start-Sleep -Seconds 15
}
