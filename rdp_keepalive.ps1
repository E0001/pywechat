# rdp_keepalive.ps1 - RDP minimized/disconnected -> tscon session to physical console
# =====================================================================
# wx_sender mouse automation requires an interactive desktop. A minimized
# or disconnected RDP client leaves the session alive but its input desktop
# dead (SetCursorPos -> "no active desktop"); 2026-08-31 21:23 messages
# were received but replies all failed for exactly this reason.
#
# Every 15s probe the desktop; when not interactive and the session still
# sits on rdp-tcp*, run: tscon <sessionId> /dest:console  -> the session
# re-attaches to the physical console and stays interactive. Reconnecting
# via RDP moves it back; minimizing again makes this script switch again.
#
# Limit: a locked console (Win+L) cannot be auto-recovered.
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
            $name = Get-MySessionName
            if ($name -like 'rdp-tcp*') {
                $id = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
                Log "desktop dead (session=$name), tscon $id /dest:console"
                $r = & tscon $id /dest:console 2>&1
                Log "  tscon: $r"
            } elseif (((Get-Date) - $lastNoFix).TotalMinutes -ge 10) {
                # states we cannot auto-fix (e.g. locked console): log at most
                # once per 10 minutes to avoid flooding
                Log "desktop dead but session=$name (not RDP, maybe locked console)"
                $lastNoFix = Get-Date
            }
        }
    } catch { Log "error: $_" }
    Start-Sleep -Seconds 15
}
