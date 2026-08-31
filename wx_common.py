# -*- coding: utf-8 -*-
"""
wx_common — wx_sender 与 wx_listener 的共享工具。

提供两套记录，共用同构 JSONL 读写与自动截断：
- 「发送回声记录」：wx_sender 每次发送成功后记录 (to_wxid, content)，
  wx_listener 检测到聊天窗口新消息时先查记录——若该内容刚被本机发给对方，
  即为机器人自己的回声，跳过转发，避免 收到→回复→再收到 的死循环。
- 「入站转发去重」：wx_listener 转发成功后记录 (wxid, text)，60s 内相同
  组合不再转发——窗口重连时 runtime_id 集体变化会把历史消息误判为新消息。

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
import sys
import time

_BASE = os.path.dirname(os.path.abspath(__file__))
ECHO_FILE = os.path.join(_BASE, 'wx_sent_echo.jsonl')
_KEEP_LINES = 200      # 截断后保留的行数
_DEFAULT_WINDOW = 60   # 回声判定窗口（秒）：60 秒内发过同样内容视为回声


def acquire_instance_lock(name: str) -> None:
    '''单实例锁：同一脚本只允许一个进程存活，重复启动直接退出。

    背景: 本机 uv venv 的 python.exe 启动任何脚本都会产生成对的两个进程
    （trampoline 双生，间隔 ~20ms），不加锁会导致消息双发/回调双份。
    锁文件按脚本名区分（.lock-{name}），进程退出后 OS 自动释放（msvcrt.locking）。
    '''
    import msvcrt
    path = os.path.join(_BASE, f'.lock-{name}')
    try:
        f = open(path, 'a+')
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        f.seek(0)
        f.truncate()
        f.write(f'{os.getpid()}\n')
        f.flush()
    except (OSError, IOError):
        print(f'[wx_common] 已有 {name} 实例在运行，本进程退出', file=sys.stderr)
        sys.exit(0)


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


# ---- 入站转发去重 ----
# 窗口重连/重绘时 runtime_id 集体变化，会把历史消息误判为新消息重新转发
# （曾导致一条 btc>100 被转发三次、提醒反复重设）。转发成功后记录
# (wxid, text)，60s 内相同组合不再转发；不影响 60s 后的正常重发命令。
INBOUND_FILE = os.path.join(_BASE, 'wx_inbound_seen.jsonl')
_INBOUND_WINDOW = 60


def log_inbound(wxid: str, text: str) -> None:
    line = json.dumps({'wxid': wxid, 'content': text, 'ts': time.time()},
                      ensure_ascii=False)
    with open(INBOUND_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    _maybe_truncate(INBOUND_FILE)


def is_recent_inbound(wxid: str, text: str) -> bool:
    '''判断 (wxid, text) 是否在 _INBOUND_WINDOW 秒内已转发过。'''
    if not os.path.exists(INBOUND_FILE):
        return False
    cutoff = time.time() - _INBOUND_WINDOW
    try:
        with open(INBOUND_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return False
    for line in lines[-_KEEP_LINES:]:
        try:
            rec = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if rec.get('wxid') == wxid and rec.get('content') == text \
                and rec.get('ts', 0) >= cutoff:
            return True
    return False


def _maybe_truncate(path: str = ECHO_FILE) -> None:
    """超过上限时截断，只保留最近 _KEEP_LINES 行。失败静默（不影响发送）。"""
    try:
        size = os.path.getsize(path)
        if size < 256 * 1024:  # 256KB 以内不处理
            return
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(lines[-_KEEP_LINES:])
    except OSError:
        pass
