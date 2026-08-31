'''
NVDA 激活微信 UIA 树流程:
前提: NVDA 已运行(--no-speech 静音)
1. 确认 NVDA 运行中
2. 关闭微信
3. 启动微信 → 把登录窗口带到前台(NVDA 注入 helper DLL)
4. 等待扫码登录(mmui::MainWindow 出现)
5. 验证主窗口子元素数量
'''
import os
import re
import subprocess
import sys
import time
import psutil
import win32gui
from pywinauto import Desktop

PATTERN = re.compile(r'Qt\d+QWindowIcon')


def find_wx_windows():
    '''返回 [(hwnd, uia_class_name)] 列表'''
    handles = []

    def cb(hwnd, _):
        if PATTERN.match(win32gui.GetClassName(hwnd)) and win32gui.IsWindowVisible(hwnd):
            handles.append(hwnd)

    win32gui.EnumDesktopWindows(0, cb, None)
    result = []
    for hwnd in handles:
        try:
            result.append((hwnd, Desktop(backend='uia').window(handle=hwnd).class_name()))
        except Exception:
            result.append((hwnd, '?'))
    return result


def nvda_running():
    return any(p.info['name'] and p.info['name'].lower() == 'nvda.exe'
               for p in psutil.process_iter(['name']))


# 1. NVDA 必须在运行
if not nvda_running():
    print('!! NVDA 未运行,先启动(静音)')
    os.startfile(r'D:\VibeCoding\nvda\portable\nvda.exe --no-speech -m')
    time.sleep(8)
    assert nvda_running(), 'NVDA 启动失败'
print('[1/5] NVDA 运行中 OK')

# 2. 关闭微信
subprocess.run(['taskkill', '/IM', 'Weixin.exe', '/F'], capture_output=True)
subprocess.run(['taskkill', '/IM', 'WeChatAppEx.exe', '/F'], capture_output=True)
time.sleep(3)
print('[2/5] 微信已关闭')

# 3. 启动微信
from pyweixin import Tools
weixin_path = Tools.where_weixin()
print(f'[3/5] 启动微信: {weixin_path}')
os.startfile(weixin_path)

# 登录窗口出现后把它带到前台,确保 NVDA 注入发生在登录之前
time.sleep(10)
for hwnd, cn in find_wx_windows():
    if cn != '?':
        try:
            Desktop(backend='uia').window(handle=hwnd).set_focus()
            print(f'  已把窗口 hwnd={hwnd} ({cn}) 带到前台,等待 NVDA 注入...')
            break
        except Exception as e:
            print(f'  set_focus 失败: {e}')
time.sleep(10)

# 4. 等待扫码登录
print('[4/5] 等待扫码登录(最长 5 分钟,请在手机上确认)...')
deadline = time.time() + 300
logged_in = False
last_state = None
while time.time() < deadline:
    wins = find_wx_windows()
    state = [(h, c) for h, c in wins]
    if state != last_state:
        print(f'  当前窗口: {state}')
        last_state = state
    for h, c in wins:
        if c == 'mmui::MainWindow':
            logged_in = True
            break
    if logged_in:
        break
    time.sleep(5)

if not logged_in:
    print('!! 超时未登录,请重新运行本脚本')
    sys.exit(1)

print('  登录完成!等待主窗口加载...')
time.sleep(30)

# 5. 验证
print('[5/5] 验证主窗口 UIA 树:')
for h, c in find_wx_windows():
    if c == 'mmui::MainWindow':
        w = Desktop(backend='uia').window(handle=h)
        kids = w.children()
        print(f'  hwnd={h} class={c} 子元素={len(kids)}')
        for k in kids[:15]:
            try:
                print(f'    - {k.element_info.control_type} "{k.element_info.name}"')
            except Exception:
                pass
        if len(kids) > 2:
            print('\nOK: UIA 树激活成功!')
        else:
            print('\nFAIL: 窗口类名已暴露但子元素仍少,需要进一步调查')
        break
