'''补测1: MSAA 探测 + 补测2: 当前所有 WXWork 相关窗口的 MSAA/UIA 双通道对比'''
import time

import win32gui
import win32con
import win32process
import psutil
import comtypes
from ctypes import POINTER, byref
from comtypes import COMError

from pywxwork import Tools  # 复用 DPI 设置

# MSAA: IAccessible
import oleacc
from comtypes.gen.Accessibility import IAccessible

def try_msaa(hwnd, label):
    '''对窗口尝试 IAccessible(直接+WM_GETOBJECT)'''
    results = []
    # 方式1: AccessibleObjectFromWindow
    try:
        acc = oleacc.AccessibleObjectFromWindow(hwnd, 0, POINTER(IAccessible))  # OBJID_WINDOW
        if acc:
            results.append(('OBJID_WINDOW', acc))
    except COMError as e:
        pass
    # 方式2: OBJID_CLIENT
    try:
        acc = oleacc.AccessibleObjectFromWindow(hwnd, win32con.OBJID_CLIENT, POINTER(IAccessible))
        if acc:
            results.append(('OBJID_CLIENT', acc))
    except COMError:
        pass
    for tag, acc in results:
        try:
            name = acc.accName(0)
            role = acc.accRole(0)
            child_count = acc.accChildCount
            print(f'  [{label} {tag}] name={name!r} role={role} children={child_count}')
            if child_count:
                # 枚举直接子对象
                children = acc.accChildren
                n = 0
                for c in children if children else []:
                    try:
                        n += 1
                        if n > 15:
                            break
                        cn = c.accName(0) if hasattr(c, 'accName') else '?'
                        cr = c.accRole(0) if hasattr(c, 'accRole') else '?'
                        print(f'    child: role={cr} name={cn!r}')
                    except Exception:
                        pass
        except Exception as e:
            print(f'  [{label} {tag}] 读取失败: {e}')

wx_pids = {p.pid for p in psutil.process_iter(['name']) if p.info['name'] and p.info['name'].lower().startswith('wxwork')}

print('=== 所有可见 WXWork 窗口的 MSAA 探测 ===')

def cb(hwnd, _):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in wx_pids and win32gui.IsWindowVisible(hwnd):
            cls = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
            print(f'hwnd={hwnd} class={cls!r} title={title!r}')
            try_msaa(hwnd, cls)
    except Exception:
        pass

win32gui.EnumWindows(cb, None)
