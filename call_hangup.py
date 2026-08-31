'''
语音通话挂断脚本 —— 独立可随时运行
在微信所有可见的非主窗口里找红色挂断/取消圆钮并点击
用法: PYTHONUTF8=1 .venv/Scripts/python.exe call_hangup.py
'''
import ctypes
import datetime
import sys

ctypes.windll.user32.SetProcessDPIAware()

import pyautogui
import psutil
import win32gui
import win32process
from PIL import ImageGrab


def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def weixin_visible_windows():
    '''非主窗口在前(优先独立通话窗口),主窗口兜底放最后(通话界面可能内嵌其中)'''
    pids = {p.pid for p in psutil.process_iter(['name'])
            if (p.info.get('name') or '').lower() == 'weixin.exe'}
    out, main = [], []

    def cb(h, _):
        try:
            pid = win32process.GetWindowThreadProcessId(h)[1]
            if pid in pids and win32gui.IsWindowVisible(h):
                (main if win32gui.GetClassName(h) == 'Qt51514QWindowIcon' else out).append(h)
        except Exception:
            pass

    win32gui.EnumWindows(cb, None)
    return out + main


def red_button_center(hwnd):
    try:
        rect = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    img = ImageGrab.grab(bbox=rect)
    w, h = img.size
    px = img.load()
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b = px[x, y][:3]
            if r > 140 and g < 90 and b < 90:
                xs.append(x)
                ys.append(y)
    if len(xs) < 30:
        return None
    return int(rect[0] + sum(xs) / len(xs)), int(rect[1] + sum(ys) / len(ys))


def main():
    wins = weixin_visible_windows()
    log(f'候选通话窗口: {[hex(h) for h in wins]}')
    if not wins:
        log('没有可操作的通话窗口,无需挂断')
        return
    for h in wins:
        pos = red_button_center(h)
        if pos:
            log(f'窗口 {hex(h)} 找到红钮 @ {pos},点击')
            pyautogui.click(pos)
            log('已点击挂断')
            return
    log('!! 所有窗口均未找到红钮,未执行点击')
    sys.exit(1)


if __name__ == '__main__':
    main()
