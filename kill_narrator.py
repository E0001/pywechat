'''用系统快捷键 Win+Ctrl+Enter 关闭讲述人(无需提权)'''
import time

import pyautogui

time.sleep(0.5)
pyautogui.hotkey('winctrl', 'ctrl', 'enter') if False else None
pyautogui.keyDown('win')
pyautogui.keyDown('ctrl')
pyautogui.press('enter')
pyautogui.keyUp('ctrl')
pyautogui.keyUp('win')
time.sleep(3)

import subprocess
r = subprocess.run(['tasklist'], capture_output=True)
out = r.stdout.decode('gbk', errors='ignore')
print('讲述人仍在运行' if 'Narrator' in out else '讲述人已关闭')
