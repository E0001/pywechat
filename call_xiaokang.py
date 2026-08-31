'''
语音电话拨打脚本 v5 —— 半自动流程的「拨出+监控」阶段
目标: 小康(备注名) —— 已获用户明确授权,仅限本次、仅限该联系人
v5 关键修正(2026-08-31 实测根因):
- 微信4.1点「语音通话」按钮后弹出的是【下拉菜单】(Qt51514QWindowToolSaveBits,
  含"语音通话/视频通话"两项),不是通话窗口!必须在菜单里再点一次才真正拨出
- 之前 v3/v4 都只点了按钮,从未真正拨出
- 接通检测不再依赖 UIA mm:ss(上次误匹配聊天时间戳 10:05),改为:
  每 POLL 秒截图 live_call.png,由主会话视觉判断是否接通,接通后跑 call_hangup.py
- 超时(150s)自动红钮取消,兜底微信自身 ~2 分钟自动结束
运行期间请不要动键盘鼠标
'''
import ctypes
import datetime
import hashlib
import time

ctypes.windll.user32.SetProcessDPIAware()

import pyautogui
import win32gui
import win32process
import psutil
from PIL import ImageGrab
from pywinauto import Desktop

from pyweixin.Config import GlobalConfig
from pyweixin.WeChatTools import Navigator

GlobalConfig.close_weixin = False  # wx_sender_server 常驻还要用微信,绝不能关

FRIEND = '小康'
VOICE_BUTTON_RE = '语音通话|语音聊天'
MENU_WAIT = 6                # 点按钮后等菜单出现
MENU_ITEM_REL = (0.5, 0.28)  # 菜单第一项「语音通话」的相对坐标(截图实测 330x145,两选项)
CALL_UI_WAIT = 8             # 点菜单项后等通话界面出现
POLL = 4
WAIT_ANSWER_TIMEOUT = 150
SHOT_DIR = 'debug_shots'
LIVE_SHOT = f'{SHOT_DIR}/live_call.png'

WEIXIN_PIDS = {p.pid for p in psutil.process_iter(['name'])
               if (p.info.get('name') or '').lower() == 'weixin.exe'}


def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def snapshot():
    out = {}

    def cb(h, _):
        try:
            pid = win32process.GetWindowThreadProcessId(h)[1]
            if pid in WEIXIN_PIDS:
                out[h] = (win32gui.GetClassName(h), win32gui.GetWindowText(h),
                          bool(win32gui.IsWindowVisible(h)))
        except Exception:
            pass

    win32gui.EnumWindows(cb, None)
    return out


def shot(tag, bbox='full'):
    if bbox == 'full':
        img = ImageGrab.grab()
    else:
        img = ImageGrab.grab(bbox=bbox)
    path = f"{SHOT_DIR}/{datetime.datetime.now():%H%M%S}_{tag}.png"
    img.save(path)
    return path, img


def red_button_center(hwnd):
    '''窗口截图里找红色挂断/取消圆钮,返回全局屏幕坐标或None'''
    try:
        rect = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    img = ImageGrab.grab(bbox=rect)
    w, h = img.size
    px = img.load()
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b = px[x, y][:3]
            if r > 140 and g < 90 and b < 90:
                xs.append(x)
                ys.append(y)
    if len(xs) < 30:
        return None
    return int(rect[0] + sum(xs) / len(xs)), int(rect[1] + sum(ys) / len(ys))


def find_candidate_call_windows(baseline):
    '''可见的、非基线、非主窗口的微信顶层窗口(菜单/通话界面)'''
    out = {}
    for h, (cn, t, vis) in snapshot().items():
        if vis and h not in baseline and cn != 'Qt51514QWindowIcon':
            out[h] = cn
    return out


def main():
    main_window = Desktop(backend='uia').window(class_name='mmui::MainWindow')
    baseline = snapshot()
    log(f'基线窗口数: {len(baseline)}')

    # ---- 1. 打开聊天窗口,点「语音通话」按钮,弹出下拉菜单 ----
    log(f'打开「{FRIEND}」聊天窗口...')
    Navigator.open_dialog_window(friend=FRIEND)
    voice_button = main_window.child_window(control_type='Button', title_re=VOICE_BUTTON_RE)
    voice_button.wait('visible ready', timeout=10)
    main_window.set_focus()
    time.sleep(0.5)
    log(f'点击「{voice_button.window_text()}」按钮(期望弹出下拉菜单)')
    voice_button.click_input()
    time.sleep(MENU_WAIT)

    menus = find_candidate_call_windows(baseline)
    if not menus:
        log('!! 未检测到下拉菜单,放弃')
        return
    menu_hwnd = next(iter(menus))
    mrect = win32gui.GetWindowRect(menu_hwnd)
    mpath, _ = shot('menu', mrect)
    log(f'菜单窗口 {hex(menu_hwnd)} rect={mrect} 截图: {mpath}')

    # ---- 2. 坐标点击菜单第一项「语音通话」 ----
    mx = int(mrect[0] + (mrect[2] - mrect[0]) * MENU_ITEM_REL[0])
    my = int(mrect[1] + (mrect[3] - mrect[1]) * MENU_ITEM_REL[1])
    log(f'点击菜单项「语音通话」 @ ({mx},{my})')
    pyautogui.click(mx, my)
    time.sleep(CALL_UI_WAIT)

    # ---- 3. 确认真正拨出:菜单消失后出现新窗口,截图验证 ----
    now = snapshot()
    new_wins = {h: cn for h, (cn, t, vis) in now.items()
                if h not in baseline and vis and cn != 'Qt51514QWindowIcon'}
    cpath, _ = shot('dialed')
    log(f'拨出后新窗口: {[(hex(h), c) for h, c in new_wins.items()]}  全屏截图: {cpath}')
    if menu_hwnd in new_wins:
        log('!! 菜单仍存在,可能点空了,中止(未拨出)')
        pyautogui.press('esc')
        return
    log('菜单已消失,通话界面应已弹出,开始监控...')

    # ---- 4. 监控循环:持续截图,超时自动取消 ----
    call_hwnds = set(new_wins)
    deadline = time.time() + WAIT_ANSWER_TIMEOUT
    last_hash = None
    still_count = 0
    while time.time() < deadline:
        alive = {h for h in call_hwnds if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h)}
        if not alive:
            log('通话窗口已全部消失(已结束或被拒),退出监控')
            break
        img = ImageGrab.grab()
        img.save(LIVE_SHOT)
        h = hashlib.md5(img.tobytes()).hexdigest()[:10]
        if h == last_hash:
            still_count += 1
        else:
            if last_hash is not None:
                log(f'界面发生变化 (hash {last_hash} -> {h})')
            still_count = 0
        last_hash = h
        log(f'监控中... 可见通话窗口 {[hex(x) for x in alive]} hash={h} 静止={still_count} 截图: {LIVE_SHOT}')
        time.sleep(POLL)
    else:
        alive = {h for h in call_hwnds if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h)}
        if alive:
            log(f'{WAIT_ANSWER_TIMEOUT}s 未确认接通,自动取消呼叫')
            for h in alive:
                pos = red_button_center(h)
                if pos:
                    log(f'点击红钮取消 @ {pos}')
                    pyautogui.click(pos)
                    break
            else:
                log('!! 未找到红钮,依赖微信自动超时,请人工确认')
    time.sleep(3)
    end_alive = {h for h in call_hwnds if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h)}
    shot('final')
    log(f'结束. 残留通话窗口: {[hex(x) for x in end_alive]}')


if __name__ == '__main__':
    main()
