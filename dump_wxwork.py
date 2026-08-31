'''侦察企业微信:窗口枚举 + UIA 树结构 + NVDA 注入状态'''
import psutil
import win32gui
from pywinauto import Desktop

# 1. 进程与安装路径
print('=== WXWork 进程 ===')
wx_pids = []
for p in psutil.process_iter(['pid', 'name', 'exe']):
    n = (p.info['name'] or '').lower()
    if n.startswith('wxwork'):
        wx_pids.append(p.info['pid'])
        if n == 'wxwork.exe':
            print(f"PID {p.info['pid']} path={p.info['exe']}")

# 2. 顶层窗口
print('\n=== WXWork 顶层窗口 ===')
wins = []

def cb(hwnd, _):
    if win32gui.IsWindowVisible(hwnd):
        # 找属于 WXWork 进程的窗口
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in wx_pids:
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)
            wins.append((hwnd, pid, cls, title))

win32gui.EnumDesktopWindows(0, cb, None)
for hwnd, pid, cls, title in wins:
    print(f'hwnd={hwnd} pid={pid} class={cls!r} title={title!r}')

# 3. 对每个顶层窗口做 UIA 深度遍历(限量)
print('\n=== UIA 树(depth<=6, 每窗口最多60元素) ===')
for hwnd, pid, cls, title in wins:
    try:
        w = Desktop(backend='uia').window(handle=hwnd)
        uia_class = w.class_name()
        desc = w.descendants()
        print(f'\n--- hwnd={hwnd} uia_class={uia_class} title={title!r} descendants={len(desc)} ---')
        for i, e in enumerate(desc[:60]):
            try:
                info = e.element_info
                print(f'  [{i}] {info.control_type} "{(info.name or "")[:40]}" class={info.class_name}')
            except Exception:
                pass
    except Exception as ex:
        print(f'hwnd={hwnd} UIA 失败: {ex}')

# 4. NVDA 注入状态
print('\n=== NVDA 注入 ===')
for pid in wx_pids:
    try:
        p = psutil.Process(pid)
        dlls = {m.path for m in p.memory_maps() if 'nvda' in m.path.lower()}
        print(f'PID {pid} ({p.name()}): {"注入 " + str(len(dlls)) + " DLL" if dlls else "无"}')
    except psutil.NoSuchProcess:
        pass
