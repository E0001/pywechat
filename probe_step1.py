'''校准步骤1:窗口定位 + 前台化 + Ctrl+F 搜索 + 截图存档'''
import time

import pyautogui

from pywxwork import Tools

hwnd, rect = Tools.find_wxwork_window()
assert hwnd, '未找到企业微信主窗口,请确认已登录'
print(f'主窗口 hwnd={hwnd} rect={rect} (left,top,right,bottom)')

Tools.activate_window(hwnd)
left, top, right, bottom = rect
w, h = right - left, bottom - top
print(f'窗口尺寸 {w}x{h}')
print(f'输入框点击点将为: ({int(left + w * 0.55)}, {bottom - 70})')

pyautogui.hotkey('ctrl', 'f')
time.sleep(0.8)
shot = pyautogui.screenshot(region=(left, top, w, h))
out = r'D:\VibeCoding\pywechat\debug_step1_search.png'
shot.save(out)
print(f'已按 Ctrl+F 并截图: {out}')
print('>>> 请看屏幕:左上角搜索框是否已聚焦(有光标/输入状态)?')
