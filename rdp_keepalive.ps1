# rdp_keepalive.ps1 - revive the interactive desktop AFTER the RDP session
# is truly disconnected (WTSConnectState check, NOT just a dead probe)
# =====================================================================
# wx_sender mouse automation requires an interactive desktop. A minimized
# or disconnected RDP client leaves the session alive but its input desktop
# dead (SetCursorPos -> "no active desktop"); 2026-08-31 21:23 messages
# were received but replies all failed for exactly this reason.
#
# ⚠️ 2026-09-01 v3 regression fix: v2 ran `tscon /dest:console` on ANY dead
# probe - but tscon DETACHES the live RDP connection as a side effect.
# A minimized RDP window or a UAC secure-desktop prompt also makes the
# probe fail transiently, so v2 kept kicking the user off their own RDP
# session every 15s ("RDP 总是自动断开"), and each reconnect re-enumerated
# the remote audio device (user's muted volume kept coming back).
#
# v3 gate: probe failure only counts when the session is REALLY
# disconnected (WTSConnectState == Disconnected). Active sessions are left
# alone no matter what the probe says - transient failures (minimized
# client, secure desktop) resolve on their own, and send failures already
# have the 3x60s retry as a safety net.
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
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int x; public int y; }
}
public static class WtsState {
    [DllImport("wtsapi32.dll")] public static extern bool WTSQuerySessionInformation(
        IntPtr hServer, int sessionId, int infoClass, out IntPtr pBuffer, out int bytesReturned);
    [DllImport("wtsapi32.dll")] public static extern void WTSFreeMemory(IntPtr pBuffer);
    // WTS_CONNECTSTATE_CLASS: 0 Active, 4 Disconnected
    public static int GetConnectState(int sessionId) {
        IntPtr buf; int len;
        if (WTSQuerySessionInformation(IntPtr.Zero, sessionId, 8, out buf, out len)) {
            int state = Marshal.ReadInt32(buf);
            WTSFreeMemory(buf);
            return state;
        }
        return -1;  // query failed
    }
}
"@

function Test-Desktop {
    $p = New-Object 'MouseProbe+POINT'
    if (-not [MouseProbe]::GetCursorPos([ref]$p)) { return $false }
    # write back the same coordinates (cursor does not move), probing the
    # input desktop only
    return [MouseProbe]::SetCursorPos($p.x, $p.y)
}

function Log($m) {
    try { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Add-Content -Encoding UTF8 $log } catch {}
}

Log "keepalive start pid=$PID"
$deadSince = 0
while ($true) {
    try {
        if (-not (Test-Desktop)) {
            $id = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
            $state = [WtsState]::GetConnectState($id)
            if ($state -eq 4) {   # Disconnected -> safe to take over console
                $r = & tscon $id /dest:console 2>&1
                Start-Sleep -Seconds 2
                if (Test-Desktop) {
                    Log "session $id disconnected + dead desktop, tscon -> recovered"
                }
            } elseif ($state -eq 0 -or $state -eq 1) {
                # v4 (2026-09-01 晚): RDP 客户端长时间最小化 = 会话 Active 但
                # 输入桌面死, 键鼠自动化持续失败(当晚 22:40 listener 开窗
                # 失败实例)。持续 >30s 才接管——UAC 安全桌面等瞬态几秒即过。
                # 代价: 用户客户端被断开, 回来重连一次; 优于挂机期间
                # 发送重试耗尽丢消息。用户侧建议: 离开时直接点 x 断开。
                if ($deadSince -eq 0) {
                    $deadSince = Get-Date
                } elseif (((Get-Date) - $deadSince).TotalSeconds -ge 30) {
                    $r = & tscon $id /dest:console 2>&1
                    Start-Sleep -Seconds 2
                    if (Test-Desktop) {
                        Log "session $id active-but-dead $($deadSince.ToString('HH:mm:ss')) (minimized RDP?), tscon -> recovered"
                        $deadSince = 0
                    }
                }
                Start-Sleep -Seconds 5
            } else {
                Log "probe failed, unexpected session state $state (id=$id)"
            }
        } else {
            $deadSince = 0
        }
    } catch { Log "error: $_" }
    # 1s 轮询(2026-09-01 15→3→1): 断开→tscon 接管空窗 ≤1s,
    # 配合 wx_sender RETRY_DELAY=15s, RDP 断开后消息最坏 ~17s 送达。
    # 探针=SetCursorPos 原坐标写回, 零开销, 高频无妨。
    Start-Sleep -Seconds 1
}
