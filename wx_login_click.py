# -*- coding: utf-8 -*-
'''
wx_login_click —— 开机链「进入微信」按钮点击 + UIA 激活验证
================================================================
boot_autostart.ps1 启动微信后调用本脚本完成自动登录的最后一步
（免扫码，但「进入微信」按钮必须点一次）。

⚠️ 单轮设计（2026-08-31 复盘定案）：
    - 绝不杀微信、绝不自动重启循环（账号安全优先）
    - UIA 树是否激活由系统级 a11y 状态决定：NVDA 存活、SPI 屏幕阅读器
      标志、DLL 注入全部满足时树仍可能空心（进程级重启救不回），此时
      退出码 2 留待下次开机/人工处理，脚本不自愈

流程：
    1. 已登录且 UIA 健康(主窗口子元素>5) → 退出 0
    2. 等登录窗「进入微信」(≤120s, 开机慢) → set_focus → dwell 8s → 点击
       (找不到按钮时对微信窗口置前后发 Enter 兜底一次)
    3. 等主窗口(≤90s) → 验证子元素
    退出码: 0=登录+UIA 健康; 1=未完成登录; 2=已登录但 UIA 未激活
'''
import sys
import time

for _s in (sys.stdout, sys.stderr):
    if not _s.isatty() and hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8')

import psutil
import pywinauto

DWELL = 8            # 聚焦后停留秒数(NVDA 读取登录窗的关键窗口)
WAIT_LOGIN = 120     # 登录窗出现上限(开机慢)
WAIT_MAIN = 90       # 点击后主窗口出现上限


def weixin_pids():
    return [p.pid for p in psutil.process_iter(['name'])
            if (p.info.get('name') or '').lower() == 'weixin.exe']


def uia_state(desktop):
    '''返回 (主窗口存在, 子元素数)。空心时子元素恰好 2: Pane+Group。'''
    for w in desktop.windows():
        if (w.element_info.class_name or '') == 'mmui::MainWindow':
            try:
                return True, len(w.children())
            except Exception:
                return True, -1
    return False, None


def find_login_button(desktop):
    for w in desktop.windows():
        try:
            for b in w.descendants(control_type='Button'):
                if b.window_text() == '进入微信' and b.is_visible():
                    return w, b
        except Exception:
            continue
    return None, None


def click_login(desktop) -> bool:
    deadline = time.time() + WAIT_LOGIN
    while time.time() < deadline:
        w, btn = find_login_button(desktop)
        if btn is not None:
            try:
                w.set_focus()
                time.sleep(DWELL)   # ⚠️ 勿删: NVDA 需要时间读取前台登录窗
                btn.click_input()
                print(f'已点击「进入微信」(聚焦停留 {DWELL}s)')
                return True
            except Exception as e:
                print(f'点击失败: {e}')
                return False
        if weixin_pids() and uia_state(desktop)[0]:
            print('未见登录窗但主窗口已存在(可能已直接登录)')
            return True
        time.sleep(2)
    # 兜底: 按钮未被 UIA 暴露时, 对微信窗口置前后发 Enter(默认按钮)
    try:
        import pyautogui
        import win32gui
        for w in desktop.windows():
            if w.element_info.process_id in set(weixin_pids()):
                win32gui.SetForegroundWindow(w.handle)
                time.sleep(DWELL)
                pyautogui.press('enter')
                print(f'未找到按钮, 已置前后发 Enter(停留 {DWELL}s)')
                return True
    except Exception as e:
        print(f'Enter 兜底失败: {e}')
    print(f'{WAIT_LOGIN}s 内未见「进入微信」按钮', file=sys.stderr)
    return False


def main() -> int:
    desktop = pywinauto.Desktop(backend='uia')
    found, n = uia_state(desktop)
    if found and n > 5:
        print('已登录且 UIA 正常(主窗口子元素>5), 无需操作')
        return 0

    if not click_login(desktop):
        return 1

    deadline = time.time() + WAIT_MAIN
    while time.time() < deadline:
        found, n = uia_state(desktop)
        if found and n > 5:
            print(f'登录完成, UIA 激活(子元素={n})')
            return 0
        if found:
            print(f'主窗口已出现, 等待 UIA... (子元素={n})')
        time.sleep(3)
    print(f'登录完成但 UIA 未激活(子元素={n}; 系统 a11y 状态异常, 需重启系统)',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
