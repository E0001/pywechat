'''
微信 UIA 树激活流程（一次性操作）:
1. 关闭微信
2. 启动讲述人（微信 UIA 树只对屏幕阅读器暴露，且微信只在启动时检测一次）
3. 启动微信，等待扫码登录完成
4. 讲述人保持运行 5 分钟后自动关闭
5. 验证 UIA 树是否持续暴露
'''
import os
import re
import subprocess
import sys
import time
import win32gui
from pywinauto import Desktop

PATTERN = re.compile(r'Qt\d+QWindowIcon')


def find_wx_uia():
    '''枚举顶层窗口,返回第一个 mmui:: 类名的窗口(登录界面 or 主界面)'''
    handles = []

    def cb(hwnd, _):
        if PATTERN.match(win32gui.GetClassName(hwnd)):
            handles.append(hwnd)

    win32gui.EnumDesktopWindows(0, cb, None)
    for hwnd in handles:
        try:
            cn = Desktop(backend='uia').window(handle=hwnd).class_name()
            if cn.startswith('mmui::'):
                return cn, hwnd
        except Exception:
            pass
    return None, None


def step(title):
    print(f'\n=== {title} ===', flush=True)


# 1. 关闭微信
step('1/5 关闭微信')
subprocess.run(['taskkill', '/IM', 'Weixin.exe', '/F'], capture_output=True)
subprocess.run(['taskkill', '/IM', 'WeChatAppEx.exe', '/F'], capture_output=True)
time.sleep(3)

# 2. 启动讲述人
step('2/5 启动讲述人(会有语音,可调低音量)')
os.startfile('narrator.exe')
time.sleep(5)

# 3. 启动微信
step('3/5 启动微信,请在手机上扫码登录')
from pyweixin import Tools
weixin_path = Tools.where_weixin()
print(f'微信路径: {weixin_path}')
os.startfile(weixin_path)

# 等待登录完成(mmui::MainWindow 出现),最长 5 分钟
deadline = time.time() + 300
logged_in = False
while time.time() < deadline:
    cn, hwnd = find_wx_uia()
    if cn:
        print(f'UIA 树已暴露: class_name={cn} hwnd={hwnd}', flush=True)
        if cn == 'mmui::MainWindow':
            logged_in = True
            print('登录完成!')
            break
    time.sleep(5)

if not logged_in:
    cn, _ = find_wx_uia()
    if cn:
        print(f'微信 UIA 已暴露({cn})但尚未登录完成,继续等待...')
        deadline = time.time() + 300
        while time.time() < deadline:
            cn, hwnd = find_wx_uia()
            if cn == 'mmui::MainWindow':
                logged_in = True
                print('登录完成!')
                break
            time.sleep(5)

if not logged_in:
    print('!! 超时未检测到登录完成,请手动重新运行本脚本继续后续步骤')
    sys.exit(1)

# 4. 讲述人保持 5 分钟
step('4/5 讲述人保持运行 5 分钟(期间可正常使用电脑)')
for i in range(300, 0, -30):
    print(f'  剩余 {i}s ...', flush=True)
    time.sleep(30)

# 5. 关闭讲述人并验证
step('5/5 关闭讲述人并验证 UIA 树')
subprocess.run(['taskkill', '/IM', 'narrator.exe', '/F'], capture_output=True)
time.sleep(3)
cn, hwnd = find_wx_uia()
print(f'讲述人已关闭,微信 UIA class_name = {cn}')
if cn:
    w = Desktop(backend='uia').window(handle=hwnd)
    print(f'子元素数量: {len(w.children())} (大于 2 即控件树已暴露)')
    print('✅ UIA 树激活成功,可以进行 UI 自动化了!')
else:
    print('❌ UIA 树未暴露,可能需要重试或延长讲述人运行时间')
