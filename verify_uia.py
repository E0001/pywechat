'''验证微信主窗口 UIA 树 + NVDA 注入状态'''
import re
import psutil
import win32gui
from pywinauto import Desktop

PATTERN = re.compile(r'Qt\d+QWindowIcon')
handles = []

def cb(hwnd, _):
    if PATTERN.match(win32gui.GetClassName(hwnd)) and win32gui.IsWindowVisible(hwnd):
        handles.append(hwnd)

win32gui.EnumDesktopWindows(0, cb, None)
print(f'顶层 Qt 窗口 {len(handles)} 个:')
for hwnd in handles:
    try:
        w = Desktop(backend='uia').window(handle=hwnd)
        cn = w.class_name()
        kids = w.children()
        print(f'hwnd={hwnd} class={cn} 子元素={len(kids)}')
        if cn == 'mmui::MainWindow':
            for k in kids[:20]:
                try:
                    print(f'    - {k.element_info.control_type} "{k.element_info.name}"')
                except Exception:
                    pass
    except Exception as e:
        print(f'hwnd={hwnd} 读取失败: {e}')

print('\nNVDA 注入状态:')
for p in psutil.process_iter(['pid', 'name']):
    if p.info['name'] and p.info['name'].lower() == 'weixin.exe':
        try:
            dlls = {m.path for m in p.memory_maps() if 'nvda' in m.path.lower()}
            mark = f'注入 {len(dlls)} DLL' if dlls else '无注入'
            print(f'  PID {p.info["pid"]}: {mark}')
        except psutil.AccessDenied:
            pass
