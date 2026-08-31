# -*- coding: utf-8 -*-
'''
wx_listener.py —— 个人微信消息监听转发器
================================================

接收侧组件（与 wx_sender_server.py 发送侧配套），打通 coinMarker 个人微信
通道的「收」链路:

    好友在手机/PC 发消息 → 本机微信(独立聊天小窗, 最小化)
        → UIA 轮询检测新消息(runtime_id 变化, 只读不写)
        → 回声过滤(wx_common: 刚由 wx_sender 发出的内容不算新消息)
        → POST http://91.98.134.93:19600/wcf/callback  (StarBot 兼容 JSON)
        → coinMarker starbot 包分发 → 命令处理 → 回复仍走 wx_sender 发送链路

协议(与 coin-marker/starbot/types.go 严格一致):
    event="10001" 登录成功  data:{robotId, nickname}
    event="10002" 私聊消息  data:{robotId, fromType:"private", fromWxId,
                              fromNickName, message, timeStamp(ms),
                              messageId:"{robot}-{ts}-{hash8}", messageType:1,
                              messageSource:0, toWxId, isPc:1}
    鉴权: Authorization: Bearer <token> (与 starbot/server.go 一致)

设计取舍(v1):
    - 只读 UIA: 不 activate_chatList(它内部是鼠标点击+END键, 会与 wx_sender
      的 pyautogui 抢输入), 不 restore 窗口, 不右键 is_my_bubble(侵入式)。
      自家消息识别改用 wx_common 发送记录匹配。
    - pyweixin 官方多好友示例即「最小化窗口监听」模式, 检测路径无需还原窗口。
    - 已知限制: 两次轮询间连发多条消息只能看到最后一条(poll 0.5s, 窗口很小);
      手机端登录本人账号给白名单好友发消息会被误认为对方消息(无法区分)。
    - 窗口关闭/微信重启: 线程内自动重开小窗并续传; robot_wxid 变化(换号登录)
      会重发 10001 重新注册。

配置: 同目录 wx_sender_config.json 的 listener + callback 块(见 README)。
运行: python wx_listener.py  (常驻; 建议用 wx_listener_hidden.vbs 隐藏启动)
'''

import hashlib
import json
import logging
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pyweixin import Navigator, Tools  # noqa: E402
from pyweixin.Config import GlobalConfig  # noqa: E402
from pyweixin.Uielements import Lists  # noqa: E402
from wx_common import is_recent_sent_echo, acquire_instance_lock  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'wx_sender_config.json')

# 常驻服务绝不关闭微信
GlobalConfig.close_weixin = False

# ---------------- 日志 ----------------
logger = logging.getLogger('wx_listener')
logger.setLevel(logging.INFO)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)
try:
    from logging.handlers import RotatingFileHandler
    _file = RotatingFileHandler(os.path.join(BASE_DIR, 'wx_listener.log'),
                                maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')
    _file.setFormatter(_fmt)
    logger.addHandler(_file)
except Exception:
    pass

LISTS = Lists()


# ============================================================
# 配置
# ============================================================

class Cfg:
    friends = {}          # {wxid: 备注名}
    poll_interval = 0.5   # 轮询间隔(秒)。用户要求 读取→通知 <5s, 0.5s 留足余量
    callback_url = ''
    callback_token = ''
    callback_timeout = 5
    callback_retries = 2
    robot_wxid = ''       # 固定 robot_wxid(配置优先)。文件夹探测正则对带后缀的
                          # 目录名会截出长短两种变体, 漂移会导致 session 双注册/
                          # 提醒 BotID 混乱, 故生产必须写死


def load_config() -> bool:
    '''读取 listener/callback 配置块; 返回是否可启动。'''
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        logger.error('读取配置失败: %s', e)
        return False
    acquire_instance_lock('wx_listener')  # 双生进程第二个在此退出
    listener = cfg.get('listener') or {}
    callback = cfg.get('callback') or {}
    Cfg.friends = listener.get('friends') or {}
    Cfg.poll_interval = float(listener.get('poll_interval', 0.5))
    Cfg.callback_url = callback.get('url', '')
    Cfg.callback_token = callback.get('token', '')
    Cfg.callback_timeout = int(callback.get('timeout', 5))
    Cfg.callback_retries = int(callback.get('max_retries', 2))
    Cfg.robot_wxid = str(callback.get('robot_wxid', '')).strip()
    if not Cfg.friends:
        logger.error('配置缺少 listener.friends(白名单 wxid→备注名), 退出')
        return False
    if not Cfg.callback_url or not Cfg.callback_token:
        logger.error('配置缺少 callback.url / callback.token, 退出')
        return False
    if not listener.get('enabled', True):
        logger.info('listener.enabled=false, 不启动监听')
        return False
    return True


# ============================================================
# 回调上报
# ============================================================

def post_event(payload: dict) -> bool:
    '''POST 事件到 coinMarker 回调接口, 带重试。网络错误/非2xx 返回 False。'''
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    headers = {'Content-Type': 'application/json; charset=utf-8',
               'Authorization': 'Bearer ' + Cfg.callback_token}
    for attempt in range(1 + Cfg.callback_retries):
        req = urllib.request.Request(Cfg.callback_url, data=body, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=Cfg.callback_timeout) as resp:
                if 200 <= resp.status < 300:
                    return True
                logger.warning('回调非 2xx: %s', resp.status)
        except Exception as e:
            logger.warning('回调失败(第 %d 次): %s', attempt + 1, e)
        if attempt < Cfg.callback_retries:
            time.sleep(1)
    return False


def build_private_message(robot_wxid: str, wxid: str, remark: str, text: str) -> dict:
    ts_ms = int(time.time() * 1000)
    digest = hashlib.md5(f'{wxid}|{text}'.encode('utf-8')).hexdigest()[:8]
    return {
        'event': '10002',
        'description': '私聊消息事件',
        'time': ts_ms,
        'robotId': robot_wxid,
        'data': {
            'robotId': robot_wxid,
            'fromType': 'private',
            'fromWxId': wxid,
            'fromNickName': remark,
            'message': text,
            'timeStamp': ts_ms,
            'messageId': f'{robot_wxid}-{ts_ms}-{digest}',
            'messageType': 1,
            'messageSource': 0,
            'toWxId': robot_wxid,
            'isPc': 1,
        },
    }


def post_login(robot_wxid: str, nickname: str = '') -> None:
    ts_ms = int(time.time() * 1000)
    payload = {
        'event': '10001',
        'description': '登录成功',
        'time': ts_ms,
        'robotId': robot_wxid,
        'data': {'robotId': robot_wxid, 'nickname': nickname},
    }
    if post_event(payload):
        logger.info('已上报 10001 登录事件 robotId=%s', robot_wxid)


# ============================================================
# robot_wxid 探测
# ============================================================

def detect_robot_wxid(timeout: float = 120) -> str:
    '''轮询 Tools.get_current_wxid() 直到拿到 wxid(微信登录后才可见)。'''
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            wxid = Tools.get_current_wxid()
            if wxid:
                return wxid
        except Exception as e:
            logger.warning('get_current_wxid 异常: %s', e)
        logger.info('尚未探测到登录 wxid(微信未登录?), 10s 后重试...')
        time.sleep(10)
    return ''


# ============================================================
# 单好友监听线程
# ============================================================

def listen_friend(wxid: str, remark: str, robot_wxid_holder: dict) -> None:
    '''
    打开该好友独立聊天小窗(最小化)并持续轮询:
    最后一条 ListItem 的 runtime_id 变化 = 新消息。
    窗口丢失/微信重启时自动重开; 重开后 robot_wxid 若变化则重发 10001。
    '''
    backoff = 5
    while True:
        try:
            dw = Navigator.open_seperate_dialog_window(friend=remark, window_minimize=True)
            chatList = dw.child_window(**LISTS.FriendChatList)

            # 等待消息列表就绪(刚打开窗口 UIA 树需要一点时间)
            initial_rid = None
            for _ in range(20):
                items = chatList.children(control_type='ListItem')
                if items:
                    initial_rid = items[-1].element_info.runtime_id
                    break
                time.sleep(0.5)
            if initial_rid is None:
                raise RuntimeError('消息列表 10s 内无 ListItem')

            logger.info('[%s] 监听就绪 (wxid=%s)', remark, wxid)
            backoff = 5

            # 换号重连后刷新会话注册（robot_wxid 由配置固定时跳过——
            # 文件夹探测的长短版漂移会被误判为换号，造成 session 双注册）
            if not Cfg.robot_wxid:
                robot_now = _safe_get_wxid()
                if robot_now and robot_now != robot_wxid_holder.get('wxid'):
                    logger.info('robot_wxid 变化: %s → %s, 重发 10001',
                                robot_wxid_holder.get('wxid'), robot_now)
                    robot_wxid_holder['wxid'] = robot_now
                    post_login(robot_now)

            while True:
                items = chatList.children(control_type='ListItem')
                if items:
                    last = items[-1]
                    rid = last.element_info.runtime_id
                    if rid != initial_rid:
                        initial_rid = rid
                        _handle_new_item(robot_wxid_holder.get('wxid', ''),
                                         wxid, remark, last)
                time.sleep(Cfg.poll_interval)

        except Exception as e:
            logger.warning('[%s] 监听中断: %s, %ds 后重开窗口', remark, e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


def _safe_get_wxid() -> str:
    try:
        return Tools.get_current_wxid()
    except Exception:
        return ''


def _handle_new_item(robot_wxid: str, wxid: str, remark: str, item) -> None:
    '''处理检测到的新消息气泡: 只认文本, 过滤自家回声, 组装 10002 上报。'''
    try:
        cls = item.class_name()
        text = item.window_text()
    except Exception as e:
        logger.warning('[%s] 读取消息项失败: %s', remark, e)
        return
    if cls != 'mmui::ChatTextItemView':  # 仅文本消息(链接/图片/文件无对应事件)
        logger.info('[%s] 非文本消息(%s), 忽略', remark, cls)
        return
    if not text:
        return
    if is_recent_sent_echo(wxid, text):
        logger.info('[%s] 自家回声, 忽略: %.30s', remark, text)
        return
    logger.info('[%s] 新消息: %.50s', remark, text)
    payload = build_private_message(robot_wxid, wxid, remark, text)
    if not post_event(payload):
        logger.error('[%s] 10002 上报失败(已重试): %.50s', remark, text)


# ============================================================
# 入口
# ============================================================

def main() -> None:
    if not load_config():
        sys.exit(1)

    # 防息屏(UIA 常驻依赖微信窗口树, 息屏/锁屏后不可靠)
    try:
        from pyweixin.WinSettings import SystemSettings
        SystemSettings.open_listening_mode(volume=False)
        logger.info('已开启防息屏模式')
    except Exception as e:
        logger.warning('防息屏设置失败(不影响启动): %s', e)

    # robot_wxid 配置优先（防文件夹正则的长短版漂移），未配置才探测
    robot_wxid = Cfg.robot_wxid or detect_robot_wxid()
    if robot_wxid:
        logger.info('robot_wxid = %s%s', robot_wxid,
                    ' (来自配置)' if Cfg.robot_wxid else ' (自动探测)')
        post_login(robot_wxid)
    else:
        logger.warning('120s 内未探测到 wxid, 先启动监听, 稍后窗口重连时补发 10001')
    holder = {'wxid': robot_wxid}

    for wxid, remark in Cfg.friends.items():
        t = threading.Thread(target=listen_friend, args=(wxid, remark, holder),
                             name=f'listen-{remark}', daemon=True)
        t.start()
        time.sleep(3)  # 逐个开窗, 避免搜索框操作相互踩踏
        logger.info('监听线程已启动: %s → %s', wxid, remark)

    logger.info('wx_listener 启动完成, 共 %d 个好友, poll=%.1fs, callback=%s',
                len(Cfg.friends), Cfg.poll_interval, Cfg.callback_url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info('收到 Ctrl+C, 退出(小窗保留, 不动微信)')


if __name__ == '__main__':
    main()
