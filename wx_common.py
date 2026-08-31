# -*- coding: utf-8 -*-
"""
wx_common — wx_sender 与 wx_listener 的共享工具。

当前仅提供「发送回声记录」：wx_sender 每次发送成功后记录 (to_wxid, content)，
wx_listener 检测到聊天窗口新消息时先查记录——若该内容刚被本机发给对方，
即为机器人自己的回声，跳过转发，避免 收到→回复→再收到 的死循环。

设计取舍（v1）：
- listener 对 UIA 只读不写（不开窗点击、不输入、不右键），与 wx_sender 的
  键鼠/开窗操作并发面极小，故不做跨进程 UIA 锁；实测若仍冲突再加。
- 记录文件按 JSON Lines 追加，单行短小，Windows 下 append 近似原子；
  读取容忍半行（解析失败即跳过）。文件超上限自动截断，只留最近记录。

用法:
    from wx_common import log_sent, is_recent_sent_echo
    log_sent('wxid_xxx', '已设置提醒')
    if is_recent_sent_echo('wxid_xxx', '已设置提醒'):
        ...  # 自己的回声，忽略
"""
import json
import os
import time

_BASE = os.path.dirname(os.path.abspath(__file__))
ECHO_FILE = os.path.join(_BASE, 'wx_sent_echo.jsonl')
_KEEP_LINES = 200      # 截断后保留的行数
_DEFAULT_WINDOW = 60   # 回声判定窗口（秒）：60 秒内发过同样内容视为回声


def log_sent(to_wxid: str, content: str) -> None:
    """wx_sender 发送成功后调用，记录一条发送。失败抛异常由调用方处理。"""
    line = json.dumps({'to': to_wxid, 'content': content, 'ts': time.time()},
                      ensure_ascii=False)
    with open(ECHO_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    _maybe_truncate()


def is_recent_sent_echo(to_wxid: str, content: str, window: float = _DEFAULT_WINDOW) -> bool:
    """判断 (to_wxid, content) 是否在 window 秒内被本机发送过（即自己的回声）。"""
    if not os.path.exists(ECHO_FILE):
        return False
    cutoff = time.time() - window
    try:
        with open(ECHO_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return False
    for line in lines[-_KEEP_LINES:]:
        try:
            rec = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue  # 容忍写入竞争产生的半行
        if rec.get('to') == to_wxid and rec.get('content') == content \
                and rec.get('ts', 0) >= cutoff:
            return True
    return False


def _maybe_truncate() -> None:
    """超过上限时截断，只保留最近 _KEEP_LINES 行。失败静默（不影响发送）。"""
    try:
        size = os.path.getsize(ECHO_FILE)
        if size < 256 * 1024:  # 256KB 以内不处理
            return
        with open(ECHO_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(ECHO_FILE, 'w', encoding='utf-8') as f:
            f.writelines(lines[-_KEEP_LINES:])
    except OSError:
        pass
