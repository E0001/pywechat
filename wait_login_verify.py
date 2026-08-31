'''启动微信 → 等扫码登录 → 前台化触发 NVDA 注入 → 验证主窗口'''
import re
import time
import os
import win32gui
from pywinauto import Desktop

PATTERN = re.compile(r'Qt\d+QWindowIcon')

def find_wx():
    handles = []
    def cb(hwnd, _):
        if PATTERN.match(win32gui.GetClassName(hwnd)) and win32gui.IsWindowVisible(hwnd):
            handles.append(hwnd)
    win32gui.EnumDesktopWindows(0, cb, None)
    out = []
    for hwnd in handles:
        try:
            out.append((hwnd, Desktop(backend='uia').window(handle=hwnd).class_name()))
        except Exception:
            out.append((hwnd, '?'))
    return out

from pyweixin import Tools
os.startfile(Tools.where_weixin())
print('微信已启动,请在手机上扫码登录...', flush=True)

# 登录窗口出现后带到前台(触发 NVDA 注入)
time.sleep(12)
for hwnd, cn in find_wx():
    try:
        Desktop(backend='uia').window(handle=hwnd).set_focus()
        print(f'登录窗口 hwnd={hwnd} ({cn}) 已前台化,NVDA 将注入', flush=True)
        break
    except Exception as e:
        print(f'set_focus: {e}', flush=True)

deadline = time.time() + 420
logged = False
last = None
while time.time() < deadline:
    wins = find_wx()
    if wins != last:
        print(f'窗口状态: {wins}', flush=True)
        last = wins
    if any(c == 'mmui::MainWindow' for _, c in wins):
        logged = True
        break
    time.sleep(5)

if not logged:
    print('TIMEOUT 未检测到主窗口', flush=True)
    raise SystemExit(1)

print('登录完成!等待 30s 让主窗口稳定...', flush=True)
time.sleep(30)
for hwnd, cn in find_wx():
    if cn == 'mmui::MainWindow':
        w = Desktop(backend='uia').window(handle=hwnd)
        kids = w.children()
        print(f'主窗口 hwnd={hwnd} 子元素={len(kids)}', flush=True)
        for k in kids[:25]:
            try:
                print(f'  - {k.element_info.control_type} "{k.element_info.name}"', flush=True)
            except Exception:
                pass
        print('UIA_ACTIVE' if len(kids) > 2 else 'UIA_NOT_ACTIVE', flush=True)
        break
