'''验证讲述人运行期间启动的企业微信 UIA 状态'''
import subprocess
import time
import win32gui
from pywinauto import Desktop

def find_main():
    res = []

    def cb(hwnd, _):
        if win32gui.GetClassName(hwnd) == 'WeWorkWindow' and win32gui.IsWindowVisible(hwnd):
            res.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return res[0] if res else None

hwnd = find_main()
if not hwnd:
    print('主窗口未找到(可能还在登录界面,枚举所有窗口:)')

    def cb(hwnd, _):
        import win32process
        import psutil
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            if psutil.Process(pid).name().lower().startswith('wxwork') and win32gui.IsWindowVisible(hwnd):
                print(f'  hwnd={hwnd} class={win32gui.GetClassName(hwnd)!r} title={win32gui.GetWindowText(hwnd)!r}')
        except Exception:
            pass

    win32gui.EnumWindows(cb, None)
    raise SystemExit(1)

w = Desktop(backend='uia').window(handle=hwnd)
desc = w.descendants()
print(f'主窗口 hwnd={hwnd} descendants={len(desc)}')
for i, e in enumerate(desc[:50]):
    try:
        info = e.element_info
        print(f'  [{i}] {info.control_type} "{(info.name or "")[:45]}" class={info.class_name}')
    except Exception:
        pass

print('关闭讲述人,3s后复查(检验持续性)...')
subprocess.run(['taskkill', '/IM', 'narrator.exe', '/F'], capture_output=True)
time.sleep(5)
desc2 = w.descendants()
print(f'讲述人关闭后 descendants={len(desc2)}')
print('RESULT_ACTIVE' if len(desc) > 5 else 'RESULT_FAIL')
