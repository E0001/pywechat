'''关闭讲述人:先试 winleft 快捷键,失败则激活窗口后 Alt+F4'''
import subprocess
import time

import pyautogui
import win32gui


def narrator_running():
    out = subprocess.run(['tasklist'], capture_output=True).stdout.decode('gbk', errors='ignore')
    return 'Narrator' in out


def find_narrator_windows():
    res = []

    def cb(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if '讲述人' in title or 'Narrator' in title:
            res.append((hwnd, title))

    win32gui.EnumWindows(cb, None)
    return res


# 方式1: winleft 快捷键
pyautogui.hotkey('winleft', 'ctrl', 'enter')
time.sleep(3)
if not narrator_running():
    print('方式1(winleft快捷键)成功,讲述人已关闭')
    raise SystemExit(0)

# 方式2: 激活窗口 Alt+F4
wins = find_narrator_windows()
print(f'讲述人窗口: {wins}')
for hwnd, title in wins:
    if win32gui.IsWindowVisible(hwnd):
        try:
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.5)
            pyautogui.hotkey('alt', 'f4')
            time.sleep(3)
        except Exception as e:
            print(f'hwnd={hwnd}: {e}')
if not narrator_running():
    print('方式2(Alt+F4)成功,讲述人已关闭')
else:
    print('仍失败:请手动点击讲述人窗口按 Alt+F4,或在讲述人设置里退出')
