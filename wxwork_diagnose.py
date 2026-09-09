'''诊断:NVDA注入状态 + 全量窗口枚举(含子窗口,找Chromium特征)'''
import psutil
import win32gui
import win32process
import win32con
from pywinauto import Desktop

# 1. 注入状态
print('=== NVDA 注入状态 ===')
wx_pids = {}
for p in psutil.process_iter(['pid', 'name']):
    n = (p.info['name'] or '').lower()
    if n.startswith('wxwork'):
        wx_pids[p.info['pid']] = n
for pid, n in wx_pids.items():
    try:
        dlls = {m.path for m in psutil.Process(pid).memory_maps() if 'nvda' in m.path.lower()}
        print(f'PID {pid} ({n}): {"注入 " + str(len(dlls)) + " DLL: " + "; ".join(sorted(d.split(chr(92))[-1] for d in dlls)) if dlls else "无注入"}')
    except psutil.NoSuchProcess:
        pass

# 2. 全量顶层窗口(所有WXWork进程,含不可见)
print('\n=== 所有顶层窗口(含隐藏) ===')

def cb(hwnd, _):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in wx_pids:
            cls = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
            vis = 'V' if win32gui.IsWindowVisible(hwnd) else 'h'
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            child_of_desktop = True
            print(f'  [{vis}] hwnd={hwnd} pid={pid}({wx_pids[pid]}) class={cls!r} title={title!r} style={style:#x}')
    except Exception:
        pass

win32gui.EnumWindows(cb, None)

# 3. WeWorkWindow 的直接子窗口(一层)
print('\n=== 主窗口子 HWND ===')
def find_main():
    res = []

    def cb2(hwnd, _):
        if win32gui.GetClassName(hwnd) == 'WeWorkWindow' and win32gui.IsWindowVisible(hwnd):
            res.append(hwnd)

    win32gui.EnumWindows(cb2, None)
    return res[0] if res else None

main = find_main()
if main:
    def child_cb(hwnd, _):
        cls = win32gui.GetClassName(hwnd)
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        print(f'  child hwnd={hwnd} pid={pid} class={cls!r} title={title!r}')

    win32gui.EnumChildWindows(main, child_cb, None)
