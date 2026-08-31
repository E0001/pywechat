'''等待扫码登录 → 验证主窗口 UIA 树(不重复启动微信)'''
import re, time, sys
import win32gui
from pywinauto import Desktop

sys.stdout.reconfigure(encoding='utf-8')
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

deadline = time.time() + 600
while time.time() < deadline:
    if any(c == 'mmui::MainWindow' for _, c in find_wx()):
        break
    time.sleep(5)
else:
    print('TIMEOUT: 10 分钟内未登录', flush=True)
    raise SystemExit(1)

print('登录完成,等待 15s 让主窗口稳定...', flush=True)
time.sleep(15)
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
