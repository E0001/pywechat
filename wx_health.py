# -*- coding: utf-8 -*-
'''
链路健康检查(一键诊断): 微信进程/主窗树/小窗 ListItem(链路死活真判据)/
sender 端口/listener 进程/frpc。输出中文摘要。

用法: .venv/Scripts/python.exe wx_health.py
注意: 本脚本自身是 UIA 客户端, 已用 wait_wechat_ready(settle=0) 保证
只在微信主窗口出现后才碰 UIA(微信初始化期间连它=毒树, 见
DEPLOY_WX_SENDER.md「微信 UIA 树加载时序」)。
'''
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    if not _s.isatty() and hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8')

import psutil

from wx_common import wait_wechat_ready


def main():
    ok_all = True

    # ---- 进程面(不碰 UIA) ----
    procs = {p.pid: (p.info['name'] or '').lower()
             for p in psutil.process_iter(['name'])}
    names = list(procs.values())
    wx_n = names.count('weixin.exe')
    frpc_n = names.count('frpc.exe')
    py_cmdlines = []
    for p in psutil.process_iter(['name', 'cmdline']):
        if (p.info['name'] or '').lower() == 'python.exe':
            py_cmdlines.append(' '.join(p.info['cmdline'] or []))
    sender_n = sum(1 for c in py_cmdlines if 'wx_sender_server' in c)
    listener_n = sum(1 for c in py_cmdlines if 'wx_listener' in c)

    print('进程: 微信=%d frpc=%s wx_sender=%d wx_listener=%d' %
          (wx_n, '有' if frpc_n else '无', sender_n, listener_n))
    if wx_n == 0:
        print('✗ 微信未运行 —— 修复: 双击桌面「微信链路一键启动」')
        return 1

    # ---- 端口 ----
    s = socket.socket()
    try:
        s.settimeout(2)
        s.connect(('127.0.0.1', 15000))
        port_ok = True
    except OSError:
        port_ok = False
    finally:
        s.close()
    print('端口: wx_sender :15000 %s' % ('✓' if port_ok else '✗'))

    # ---- UIA 面(微信主窗已在才碰) ----
    if not wait_wechat_ready(timeout=30, settle=0):
        print('✗ 微信主窗口未出现(未登录?) —— 修复: 双击桌面「微信链路一键启动」')
        return 1
    import pywinauto
    desk = pywinauto.Desktop(backend='uia')
    main_kids = None
    for w in desk.windows(class_name='mmui::MainWindow'):
        main_kids = len(w.children())
        break
    chat = []
    for w in desk.windows(class_name='mmui::ChatSingleWindow'):
        try:
            n_li = len(w.descendants(control_type='ListItem'))
        except Exception:
            n_li = -1
        chat.append((w.window_text() or '?', n_li))
    print('UIA: 主窗 children=%s, 聊天小窗=%s' %
          (main_kids, ', '.join('%s(%d条)' % c for c in chat) or '无'))

    # ---- 判定 ----
    chat_ok = [c for c in chat if c[1] > 0]
    if listener_n and chat_ok:
        print('=== ✓ 收发链路正常(小窗可读, listener 在岗) ===')
    elif not chat_ok:
        ok_all = False
        print('=== ✗ 小窗读不到 ListItem(链路死) —— 修复: 先停服务再重启微信,')
        print('    按顺序: 杀 python(wx_sender|wx_listener) → 杀微信 → 启动微信')
        print('    → wx_login_click exit=0 → 再起服务(或双击桌面一键启动,')
        print('    它已内置此顺序) ===')
    elif not listener_n:
        ok_all = False
        print('=== ✗ listener 未运行(小窗正常) —— 修复: 双击桌面「微信链路一键启动」===')
    if not port_ok:
        ok_all = False
        print('✗ wx_sender 端口 15000 不通')
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
