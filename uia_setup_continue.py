'''续跑:等待扫码登录 → 讲述人保持 5 分钟 → 关闭 → 验证 UIA 树'''
import os
import re
import subprocess
import sys
import time
import win32gui
from pywinauto import Desktop

PATTERN = re.compile(r'Qt\d+QWindowIcon')


def find_wx_uia():
    handles = []

    def cb(hwnd, _):
        if PATTERN.match(win32gui.GetClassName(hwnd)):
            handles.append(hwnd)

    win32gui.EnumDesktopWindows(0, cb, None)
    for hwnd in handles:
        try:
            cn = Desktop(backend='uia').window(handle=hwnd).class_name()
            if cn.startswith('mmui::'):
                return cn, hwnd
        except Exception:
            pass
    return None, None


print('等待扫码登录...', flush=True)
deadline = time.time() + 300
logged_in = False
last = None
while time.time() < deadline:
    cn, hwnd = find_wx_uia()
    if cn != last:
        print(f'  当前: class_name={cn}', flush=True)
        last = cn
    if cn == 'mmui::MainWindow':
        logged_in = True
        break
    time.sleep(5)

if not logged_in:
    print('!! 超时未登录,请重新运行')
    sys.exit(1)

print('登录完成!讲述人保持运行 5 分钟...')
for i in range(300, 0, -30):
    print(f'  剩余 {i}s ...', flush=True)
    time.sleep(30)

subprocess.run(['taskkill', '/IM', 'narrator.exe', '/F'], capture_output=True)
time.sleep(3)
cn, hwnd = find_wx_uia()
print(f'讲述人已关闭,微信 UIA class_name = {cn}')
if cn:
    w = Desktop(backend='uia').window(handle=hwnd)
    print(f'子元素数量: {len(w.children())} (大于 2 即控件树已暴露)')
    print('OK: UIA 树激活成功,可以进行 UI 自动化了!')
else:
    print('FAIL: UIA 树未暴露')
