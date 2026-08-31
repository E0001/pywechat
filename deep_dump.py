'''深度遍历微信主窗口 UIA 树'''
import re
import sys
import win32gui
from pywinauto import Desktop

PATTERN = re.compile(r'Qt\d+QWindowIcon')
handles = []

def cb(hwnd, _):
    if PATTERN.match(win32gui.GetClassName(hwnd)) and win32gui.IsWindowVisible(hwnd):
        handles.append(hwnd)

win32gui.EnumDesktopWindows(0, cb, None)
target = None
for hwnd in handles:
    try:
        if Desktop(backend='uia').window(handle=hwnd).class_name() == 'mmui::MainWindow':
            target = hwnd
            break
    except Exception:
        pass

if not target:
    print('未找到 mmui::MainWindow')
    sys.exit(1)

w = Desktop(backend='uia').window(handle=target)
print(f'主窗口 hwnd={target}, 深度遍历 descendants...')
try:
    desc = w.descendants()
    print(f'descendants 总数: {len(desc)}')
    def depth_ok(e, max_d=6):
        return True
    for i, e in enumerate(desc[:120]):
        try:
            info = e.element_info
            print(f'  [{i}] {info.control_type} "{info.name}" class={info.class_name} auto_id={info.automation_id}')
        except Exception as ex:
            print(f'  [{i}] 读取失败 {ex}')
except Exception as ex:
    print(f'遍历失败: {ex}')
