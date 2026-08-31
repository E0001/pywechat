'''把微信主窗口带到前台 → 等 NVDA 注入 → 复查 DLL 与 UIA 树'''
import time
import re
import psutil
import win32gui
from pywinauto import Desktop

hwnd = 3083634
print('把微信主窗口带到前台...')
w = Desktop(backend='uia').window(handle=hwnd)
try:
    w.set_focus()
except Exception as e:
    print(f'set_focus 失败: {e}')

time.sleep(10)  # 给 NVDA 时间响应焦点事件并注入

print('=== 注入复查(主进程 16220) ===')
found = False
for pid in (16220, 16940, 18424, 19096, 50572):
    try:
        p = psutil.Process(pid)
        dlls = {m.path for m in p.memory_maps() if 'nvda' in m.path.lower() or 'outhelper' in m.path.lower()}
        if dlls:
            print(f'PID {pid} ({p.name()}): 注入了 {len(dlls)} 个 DLL')
            for d in sorted(dlls):
                print(f'    {d}')
            found = True
    except psutil.NoSuchProcess:
        pass
if not found:
    print('仍未注入任何微信进程')

print('\n=== UIA 树复查 ===')
try:
    kids = w.children()
    print(f'hwnd={hwnd} class={w.class_name()} 子元素={len(kids)}')
    for k in kids[:10]:
        print(f'  - {k.element_info.control_type} "{k.element_info.name}" class={k.element_info.class_name}')
except Exception as e:
    print(f'读取失败: {e}')
