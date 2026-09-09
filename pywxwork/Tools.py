'''pywxwork 工具集:窗口定位/前台化/剪贴板/点击(坐标自动化基础)'''
import ctypes
import time

import pyautogui
import win32con
import win32gui
import win32process
import win32clipboard

# DPI 感知:保证 win32gui 窗口坐标与 pyautogui 物理像素一致(必须在截图/取矩形前设置)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

from .Config import globalConfig

MAIN_WINDOW_CLASS = 'WeWorkWindow'
MAIN_WINDOW_TITLE = '企业微信'


def find_wxwork_window():
    '''返回主窗口 (hwnd, rect);未找到返回 (None, None)'''
    result = []

    def callback(hwnd, _):
        if win32gui.GetClassName(hwnd) == MAIN_WINDOW_CLASS and win32gui.IsWindowVisible(hwnd):
            result.append(hwnd)

    win32gui.EnumWindows(callback, None)
    if not result:
        return None, None
    hwnd = result[0]
    return hwnd, win32gui.GetWindowRect(hwnd)


def activate_window(hwnd, wait=0.8):
    '''把窗口带到前台并还原(如最小化)'''
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.5)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except ctypes.WinError:
        # SetForegroundWindow 前台锁限制:用 ALT 键解法
        ctypes.windll.keybd_event(0x12, 0, 0, 0)
        ctypes.windll.keybd_event(0x12, 0, 2, 0)
        win32gui.SetForegroundWindow(hwnd)
    time.sleep(wait)
    if globalConfig.maximize_window:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        time.sleep(0.5)


def copy_to_clipboard(text: str):
    '''文本写入剪贴板(CF_UNICODETEXT)'''
    for _ in range(3):
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            win32clipboard.CloseClipboard()
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError('剪贴板写入失败')


def click_input_box(hwnd):
    '''点击聊天输入框区域(相对坐标:窗口右侧中部+底部偏上)'''
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    x = int(left + width * globalConfig.input_box_x_ratio)
    y = int(bottom - globalConfig.input_box_y_offset)
    pyautogui.click(x, y)
    time.sleep(0.4)
    return x, y
