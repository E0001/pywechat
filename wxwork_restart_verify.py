'''重启企业微信(NVDA 保持运行) → 前台化 → 等登录 → 验证 UIA 树'''
import subprocess
import time
import os
import win32gui
from pywinauto import Desktop

WXWORK = r'C:\Program Files (x86)\WXWork\WXWork.exe'
TARGET_CLASS = 'WeWorkWindow'

def find_main():
    res = []

    def cb(hwnd, _):
        if win32gui.GetClassName(hwnd) == TARGET_CLASS and win32gui.IsWindowVisible(hwnd):
            res.append(hwnd)

    win32gui.EnumDesktopWindows(0, cb, None)
    return res[0] if res else None

print('[1/4] 关闭企业微信...')
subprocess.run(['taskkill', '/IM', 'WXWork.exe', '/F'], capture_output=True)
subprocess.run(['taskkill', '/IM', 'WXWorkWeb.exe', '/F'], capture_output=True)
time.sleep(3)

print('[2/4] 启动企业微信...')
os.startfile(WXWORK)

# 等主窗口出现并前台化(NVDA 注入需要窗口成为前台焦点)
hwnd = None
deadline = time.time() + 60
while time.time() < deadline:
    hwnd = find_main()
    if hwnd:
        break
    time.sleep(2)
assert hwnd, '主窗口未出现'
print(f'  主窗口 hwnd={hwnd}, 前台化(NVDA 注入)...')
try:
    Desktop(backend='uia').window(handle=hwnd).set_focus()
except Exception as e:
    print(f'  set_focus: {e}')
time.sleep(15)

print('[3/4] 等待登录(自动登录或扫码,最长3分钟)...')
deadline = time.time() + 180
last = -1
while time.time() < deadline:
    try:
        w = Desktop(backend='uia').window(handle=hwnd)
        n = len(w.descendants())
        if n != last:
            print(f'  descendants={n}')
            last = n
        if n > 5:
            break
    except Exception:
        pass
    time.sleep(5)

print('[4/4] 最终验证:')
w = Desktop(backend='uia').window(handle=hwnd)
desc = w.descendants()
print(f'descendants={len(desc)}')
for i, e in enumerate(desc[:80]):
    try:
        info = e.element_info
        print(f'  [{i}] {info.control_type} "{(info.name or "")[:45]}" class={info.class_name}')
    except Exception:
        pass
print('WXWORK_ACTIVE' if len(desc) > 5 else 'WXWORK_NOT_ACTIVE')
