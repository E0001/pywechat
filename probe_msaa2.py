'''MSAA 快测:WM_GETOBJECT 响应(非零=有 MSAA/UIA Provider)'''
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
WM_GETOBJECT = 0x003D
OBJID_CLIENT = 0xFFFFFFFC
OBJID_WINDOW = 0x00000000

def probe(hwnd, name):
    for objid, tag in ((OBJID_WINDOW, 'WINDOW'), (OBJID_CLIENT, 'CLIENT')):
        res = wintypes.DWORD()
        ok = user32.SendMessageTimeoutW(hwnd, WM_GETOBJECT, 0, objid, 2, 1000, ctypes.byref(res))
        print(f'{name} OBJID_{tag}: call_ok={bool(ok)} lresult={res.value:#x}')

probe(1838902, 'WeWorkWindow(主窗口)')

import win32gui

def find_all():
    out = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            cls = win32gui.GetClassName(hwnd)
            if cls in ('TitleBarWindow', 'PerryShadowWnd'):
                out.append((hwnd, cls))

    win32gui.EnumWindows(cb, None)
    return out

for hwnd, cls in find_all():
    probe(hwnd, cls)
