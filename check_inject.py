'''检查微信进程是否被 NVDA 注入 helper DLL + UIA 树状态'''
import re
import psutil
import win32gui
from pywinauto import Desktop

# 1. 枚举微信进程加载的 NVDA 相关 DLL
print('=== 微信进程 NVDA DLL 注入检查 ===')
for p in psutil.process_iter(['pid', 'name']):
    if p.info['name'] and p.info['name'].lower() in ('weixin.exe', 'wechat.exe', 'wechatappex.exe'):
        try:
            dlls = [m.path for m in p.memory_maps() if 'nvda' in m.path.lower() or 'outhelper' in m.path.lower() or 'vbuf' in m.path.lower()]
            if dlls:
                print(f'PID {p.info["pid"]} ({p.info["name"]}): 已注入 {len(dlls)} 个 NVDA DLL:')
                for d in sorted(set(dlls)):
                    print(f'    {d}')
            else:
                print(f'PID {p.info["pid"]} ({p.info["name"]}): 无 NVDA DLL')
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            print(f'PID {p.info["pid"]}: 无法读取(权限)')

# 2. UIA 树状态
print('\n=== 微信窗口 UIA 状态 ===')
PATTERN = re.compile(r'Qt\d+QWindowIcon')
handles = []

def cb(hwnd, _):
    if PATTERN.match(win32gui.GetClassName(hwnd)) and win32gui.IsWindowVisible(hwnd):
        handles.append(hwnd)

win32gui.EnumDesktopWindows(0, cb, None)
print(f'顶层 Qt 窗口: {len(handles)} 个')
for hwnd in handles:
    try:
        w = Desktop(backend='uia').window(handle=hwnd)
        cn = w.class_name()
        kids = len(w.children())
        print(f'  hwnd={hwnd} uia_class={cn} 子元素={kids}')
    except Exception as e:
        print(f'  hwnd={hwnd} 读取失败: {e}')
