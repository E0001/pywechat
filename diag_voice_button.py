'''
诊断脚本: 恢复微信主窗口(隐藏在托盘) -> 打开「小康」聊天窗口 -> 枚举按钮标题
只读不点(除导航打开聊天窗口),用于定位语音通话按钮的真实控件标题
'''
import re
import time

import win32gui

from pywinauto import Desktop

from pyweixin.WeChatTools import Navigator

desktop = Desktop(backend='uia')
qt_pattern = re.compile(r'Qt\d+QWindowIcon')

handles = []


def enum_cb(hwnd, param):
    if qt_pattern.match(win32gui.GetClassName(hwnd)):
        handles.append(hwnd)


win32gui.EnumDesktopWindows(0, enum_cb, None)
print(f'找到 {len(handles)} 个 Qt 顶层窗口句柄')
main_hwnd = None
for h in handles:
    try:
        cn = desktop.window(handle=h).class_name()
    except Exception as exc:
        print(hex(h), '读取类名失败:', exc)
        continue
    print(hex(h), cn, 'visible=', bool(win32gui.IsWindowVisible(h)))
    if 'mmui::MainWindow' in cn:
        main_hwnd = h
if main_hwnd is None:
    print('!! 未找到 mmui::MainWindow')
    raise SystemExit(1)

# 恢复显示主窗口
win32gui.ShowWindow(main_hwnd, 9)  # SW_RESTORE
time.sleep(1)
print('主窗口已恢复')

main_window = Navigator.open_dialog_window(friend='小康')
print('聊天窗口已打开「小康」')

btns = main_window.descendants(control_type='Button')
print(f'主窗口内按钮数: {len(btns)}')
for b in btns:
    t = (b.window_text() or '').strip()
    if t:
        print('  Button:', repr(t))

print('--- 含「语音/视频/通话」关键词的所有元素 ---')
for elem in main_window.descendants():
    try:
        t = (elem.window_text() or '').strip()
        ct = elem.control_type()
    except Exception:
        continue
    if t and any(k in t for k in ('语音', '视频', '通话')):
        print(f'  [{ct}] {t!r}')
