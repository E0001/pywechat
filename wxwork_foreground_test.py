'''无损实验:企业微信前台化 → 等待 → 复查 UIA 树'''
import time
import win32gui
from pywinauto import Desktop

hwnd = 1052300
w = Desktop(backend='uia').window(handle=hwnd)
print('把企业微信主窗口带到前台...')
try:
    w.set_focus()
except Exception as e:
    print(f'set_focus: {e}')

for wait in (10, 20, 30):
    time.sleep(wait)
    try:
        desc = w.descendants()
        print(f'等待累计 {10+20+0 if wait==10 else (10+20 if wait==20 else 60)}s 后: descendants={len(desc)}')
        if len(desc) > 5:
            for i, e in enumerate(desc[:50]):
                try:
                    info = e.element_info
                    print(f'  [{i}] {info.control_type} "{(info.name or "")[:40]}" class={info.class_name}')
                except Exception:
                    pass
            break
    except Exception as ex:
        print(f'遍历失败: {ex}')
