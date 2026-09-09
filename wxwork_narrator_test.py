'''最后实验:讲述人先运行 → 重启企业微信 → 验证 UIA'''
import subprocess
import time
import os
import win32gui
from pywinauto import Desktop

TARGET_CLASS = 'WeWorkWindow'
WXWORK = r'C:\Program Files (x86)\WXWork\WXWork.exe'

def find_main():
    res = []

    def cb(hwnd, _):
        if win32gui.GetClassName(hwnd) == TARGET_CLASS and win32gui.IsWindowVisible(hwnd):
            res.append(hwnd)

    win32gui.EnumDesktop(cb if False else 0, cb, None)
    return res[0] if res else None

print('[1/5] 启动讲述人(有语音,马上调低音量也没关系,很快关)...')
os.startfile('narrator.exe')
time.sleep(8)

print('[2/5] 关闭企业微信...')
subprocess.run(['taskkill', '/IM', 'WXWork.exe', '/F'], capture_output=True)
subprocess.run(['taskkill', '/IM', 'WXWorkWeb.exe', '/F'], capture_output=True)
time.sleep(3)

print('[3/5] 启动企业微信...')
os.startfile(WXWORK)
deadline = time.time() + 90
hwnd = None
while time.time() < deadline and not hwnd:
    hwnd = find_main()
    time.sleep(2)
print(f'  主窗口 hwnd={hwnd}')

print('[4/5] 等登录(最长3分钟)...')
deadline = time.time() + 180
last = -1
while time.time() < deadline:
    try:
        n = len(Desktop(backend='uia').window(handle=hwnd).descendants())
        if n != last:
            print(f'  descendants={n}')
            last = n
        if n > 5:
            break
    except Exception:
        pass
    time.sleep(5)

print('[5/5] 关闭讲述人,最终验证...')
subprocess.run(['taskkill', '/IM', 'narrator.exe', '/F'], capture_output=True)
time.sleep(3)
desc = Desktop(backend='uia').window(handle=hwnd).descendants()
print(f'descendants={len(desc)}')
for i, e in enumerate(desc[:40]):
    try:
        info = e.element_info
        print(f'  [{i}] {info.control_type} "{(info.name or "")[:45]}" class={info.class_name}')
    except Exception:
        pass
print('WXWORK_NARRATOR_ACTIVE' if len(desc) > 5 else 'WXWORK_NARRATOR_FAIL')
