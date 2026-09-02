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
import re
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pyweixin import Navigator, Tools  # noqa: E402
from pyweixin.Config import GlobalConfig  # noqa: E402
from pyweixin.Uielements import Lists  # noqa: E402
from pyweixin.WeChatTools import Main_window, SideBar  # noqa: E402  实例(非类)
from wx_common import (acquire_instance_lock, echo_fingerprints,  # noqa: E402
                       is_recent_inbound, is_recent_sent_echo, log_inbound,
                       search_terms, seen_fingerprints, set_chat_hwnd,
                       set_contact_name, wait_wechat_ready)

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
    aliases = {}          # {wxid: 微信号} —— 永不变化且可搜索的最稳寻址词
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
    Cfg.aliases = cfg.get('aliases') or {}
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

def _read_header_name(dw) -> str:
    '''读取聊天窗口头部的当前显示名（用户改备注后此值实时变化）。'''
    try:
        for c in dw.descendants(control_type='Text'):
            aid = c.element_info.automation_id or ''
            if aid.endswith('current_chat_name_label'):
                return c.window_text() or ''
    except Exception:
        pass
    return ''


def _discover_name_by_alias(alias: str) -> str:
    '''
    微信号两段式寻址·第一步: 搜索框输入微信号。微信号永不变化且可搜,
    但搜索结果条目显示的是备注名——pyweixin 原生按「显示名==搜索词」
    逐字匹配会误报 NoSuchFriendError(实测 litiantianss/crypto_kang 均如此,
    微信本身搜得到)。故这里只读结果不点击, 返回第一个联系人条目的
    显示名(=当前备注名), 交给调用方用它走原生开窗。失败返回 ''。
    '''
    try:
        main_window = Navigator.open_weixin(is_maximize=False)
        chat_button = main_window.child_window(**SideBar.Weixin)
        chat_button.click_input()
        search = main_window.descendants(**Main_window.Search)[0]
        search.click_input()
        search.set_text(alias)
        time.sleep(0.8)
        results = main_window.child_window(title='', control_type='List')
        for li in results.children(control_type='ListItem'):
            if li.class_name() == 'mmui::SearchContentCellView' and li.window_text():
                return li.window_text()
    except Exception as e:
        logger.warning('按微信号 %r 发现显示名失败: %s', alias, e)
    return ''


def _open_friend_window(wxid: str, remark: str):
    '''
    三级搜索词依次开窗, 命中即返回 (window, 实际生效的搜索词); 全败抛异常
    (由 listen_friend 的 backoff 重试兜底):
    1. 追踪名 —— wx_common 落盘的窗口头部显示名(listener 30s 实时刷新,
       用户改备注后自动跟进);
    2. 配置备注名 —— wx_sender_config.json listener.friends 里的名字;
    3. 微信号两段式 —— 前两者同时失效(改名后旧名全失联)时, 按微信号
       (aliases 配置, 永不变化)发现当前显示名并落盘, 再用它开窗。
       只要不删好友, 永远找得回来。
    '''
    alias = Cfg.aliases.get(wxid, '')
    last_err = None
    for term in search_terms(wxid, alias, remark)[:2]:  # 前两级可直搜
        try:
            dw = Navigator.open_seperate_dialog_window(friend=term, window_minimize=True)
            if term != remark:
                logger.info('[%s] 按追踪名开窗成功: %s', remark, term)
            return dw, term
        except Exception as e:
            last_err = e
            logger.warning('[%s] 搜索词 %r 开窗失败: %s', remark, term, e)
    if alias:
        logger.info('[%s] 旧名全部失效, 按微信号 %r 两段式寻址', remark, alias)
        discovered = _discover_name_by_alias(alias)
        if discovered:
            logger.info('[%s] 微信号 %r → 当前显示名 %r, 落盘后开窗',
                        remark, alias, discovered)
            set_contact_name(wxid, discovered)
            dw = Navigator.open_seperate_dialog_window(friend=discovered,
                                                       window_minimize=True)
            return dw, discovered
    raise last_err or RuntimeError(f'[{remark}] 无可用搜索词')


_TAIL = 15  # 轮询比对的尾部消息条数(快照 diff 窗口, 覆盖突发连发)

# ---- 消息条目识别与重试(2026-09-02 连发漏消息修复) ----
# 实锤(2026-09-02 13:24:36): 连发时前面一条的 ListItem class 是
# mmui::ChatItemView/ChatBubbleItemView 而非 ChatTextItemView, 被旧白名单
# 误判"非文本"忽略且 rid 已进 seen → 永久丢失。放宽为「mmui::Chat 系
# class(排除系统条目) + 非空且非时间样文本」即认文本消息; 暂读不出文本的
# (渲染早期/树重排竞态)不进 seen, 下轮重读, 超过 _RETRY_MAX 轮放弃。
_SYS_CLASS = 'mmui::ChatSystemInfoItemView'
_TIME_TEXT_RE = re.compile(
    r'^(?:[上下]午\s*)?\d{1,2}:\d{2}(?::\d{2})?$'
    r'|^星期[一二三四五六日天]$'
    r'|^\d{4}年\d{1,2}月\d{1,2}日$'
    r'|^以下为新消息$')
_RETRY_MAX = 10  # 同一 rid 最多重试轮数(~5s), 防图片类永久空文本死循环
_retry_counts = {}  # rid -> 已重试轮数(渲染竞态/上报失败共用)


def listen_friend(wxid: str, remark: str, robot_wxid_holder: dict) -> None:
    '''
    打开该好友独立聊天小窗(最小化)并持续轮询:
    尾部消息列表的 runtime_id 快照 diff, 新增 rid 逐条处理
    (同一轮询周期内连发多条也不漏)。
    窗口丢失/微信重启时自动重开; 重开后 robot_wxid 若变化则重发 10001。

    开窗搜索词三级自愈(见 _open_friend_window): 追踪名 → 配置备注名 →
    微信号两段式发现。用户改备注/关小窗后无需改配置即可自动找回。
    '''
    backoff = 5
    while True:
        try:
            dw, term = _open_friend_window(wxid, remark)
            try:
                set_chat_hwnd(wxid, dw.handle)
            except Exception:
                pass
            chatList = dw.child_window(**LISTS.FriendChatList)

            # 等待消息列表就绪且基线稳定。窗口(重)开时列表渐进渲染——旧消息
            # 逐条补齐, 直接取首见列表当基线会把渲染补齐的历史消息误判为
            # 新消息重复转发(一条命令被转 3 次的事故根因)。要求尾部 rid 快照
            # 连续 2s 不变才算稳定; 渲染通常 1-3s 完成。
            initial_snap = None
            stable_since = None
            deadline = time.time() + 15
            while time.time() < deadline:
                items = chatList.children(control_type='ListItem')
                snap = tuple(it.element_info.runtime_id for it in items[-_TAIL:])
                if snap:
                    if snap == initial_snap:
                        if time.time() - stable_since >= 2.0:
                            break  # 列表已稳定
                    else:
                        initial_snap = snap
                        stable_since = time.time()
                time.sleep(0.5)
            if not initial_snap:
                raise RuntimeError('消息列表 15s 内未出现稳定基线')
            seen = set(initial_snap)

            # 基线 ≠ 已处理: 对账补推中断/重启期间漏掉的消息(见 _reconcile_missed)
            try:
                _reconcile_missed(robot_wxid_holder.get('wxid', ''),
                                  wxid, remark, chatList, seen)
            except Exception as e:
                logger.warning('[%s] 对账补推异常(不影响监听): %s', remark, e)

            logger.info('[%s] 监听就绪 (wxid=%s, 寻址词=%s)', remark, wxid, term)
            header = _read_header_name(dw)
            if header:
                set_contact_name(wxid, header)
                term = header
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

            poll_count = 0
            while True:
                items = chatList.children(control_type='ListItem')
                if items:
                    # 尾部快照 diff: 同一轮询周期内连发多条(0.5s 内 2 条曾
                    # 只见最后一条, 漏掉前一条)也能逐条按序处理。
                    tail = items[-_TAIL:]
                    tail_rids = {it.element_info.runtime_id for it in tail}
                    fresh = [it for it in tail
                             if it.element_info.runtime_id not in seen]
                    for it in fresh:
                        rid = it.element_info.runtime_id
                        st = _handle_new_item(robot_wxid_holder.get('wxid', ''),
                                              wxid, remark, it)
                        if st == 'ok':
                            seen.add(rid)
                            _retry_counts.pop(rid, None)
                            continue
                        # retry: rid 不进 seen, 下轮重读文本/重报; 超限放弃
                        # 防图片类永久空文本死循环(见 _RETRY_MAX 注释)。
                        n = _retry_counts.get(rid, 0) + 1
                        if n >= _RETRY_MAX:
                            logger.warning('[%s] 重试 %d 轮仍失败, 放弃该条',
                                           remark, n)
                            seen.add(rid)
                            _retry_counts.pop(rid, None)
                        else:
                            _retry_counts[rid] = n
                    seen &= tail_rids  # seen 有界: 只保留当前尾部窗口
                    for rid in list(_retry_counts):
                        if rid not in tail_rids:
                            del _retry_counts[rid]
                poll_count += 1
                if poll_count % 60 == 0:  # ~30s 刷新一次显示名(改备注自愈的关键)
                    header = _read_header_name(dw)
                    if header and header != term:
                        logger.info('[%s] 检测到备注名变化: %s → %s', remark, term, header)
                        set_contact_name(wxid, header)
                        term = header
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


def _reconcile_missed(robot_wxid: str, wxid: str, remark: str,
                      chat_list, seen: set) -> None:
    '''
    中断/重启对账兜底(2026-09-02): 基线里查找空窗期间漏转发的消息并补推。

    原基线机制(下方 initial_snap 稳定逻辑)把重开窗口时的全部消息当哑基线
    跳过——防渲染补齐误报的同时, 也把中断期间到达的消息静默丢弃了(昨晚
    no active desktop 一整晚的事故)。这里用 48h 落盘指纹定位水位: 从列表
    尾部往前扫, 第一条命中「已转发 ∪ 自家回声」指纹的消息即水位, 其后
    (更新)收集到的未见过消息按时间正序补推。中断段内不会有自家回复
    (收不到命令就无回复), 水位不会截断漏网段; 一条水位都没有(新好友/
    指纹过期)则保守放弃, 防历史消息整体重放。补推的 rid 计入 seen 防重复。
    '''
    try:
        items = chat_list.children(control_type='ListItem')
    except Exception as e:
        logger.warning('[%s] 对账读取列表失败(跳过补推): %s', remark, e)
        return
    if not items:
        return
    fps = seen_fingerprints(wxid) | echo_fingerprints(wxid)
    missed = []  # (rid, text), 逆序收集(新→旧)
    for it in reversed(items):
        try:
            cls = it.class_name() or ''
            text = (it.window_text() or '').strip()
            rid = it.element_info.runtime_id
        except Exception:
            continue  # 读不出的条目既不算漏网也不算水位
        if text and text in fps:
            break  # 水位: 此条已处理过, 收集到的 missed 即空窗漏网段
        if not text or cls == _SYS_CLASS or _TIME_TEXT_RE.match(text):
            continue  # 系统/时间/空条目: 跳过但继续往前找水位
        missed.append((rid, text))
    if not missed:
        return
    if not fps:
        logger.warning('[%s] 无历史指纹(新会话或指纹过期), 保守放弃补推 %d 条',
                       remark, len(missed))
        return
    missed.reverse()  # 时间正序(旧→新)补推
    logger.info('[%s] 对账: 补推中断期间漏掉的 %d 条消息', remark, len(missed))
    for rid, text in missed:
        seen.add(rid)
        if is_recent_sent_echo(wxid, text):  # echo 48h 指纹外的双保险
            logger.info('[%s] 补推跳过自家回声: %.30s', remark, text)
            continue
        payload = build_private_message(robot_wxid, wxid, remark, text)
        if post_event(payload):
            try:
                log_inbound(wxid, text)
            except OSError:
                pass
            logger.info('[%s] 补推成功: %.50s', remark, text)
        else:
            logger.error('[%s] 补推上报失败(不重试, 防重复): %.50s', remark, text)


def _classify_item(item, remark: str):
    '''
    读消息条目, 返回 (状态, 文本):
      'ok'    —— 文本消息, 文本在返回值里
      'skip'  —— 确定忽略(系统条目/时间条目/非 Chat 系 class)
      'retry' —— 疑似文本但暂读不出(渲染早期/树重排竞态), 应下轮重读
    class 白名单见上方 _TIME_TEXT_RE 处注释(ChatItemView/ChatBubbleItemView
    实锤漏消息)。
    '''
    try:
        cls = item.class_name() or ''
        text = (item.window_text() or '').strip()
    except Exception:
        return 'retry', ''  # COM 引用失效/树重排中, 下轮 children() 重建引用后重读
    if cls == _SYS_CLASS:
        return 'skip', ''
    if cls.startswith('mmui::Chat'):
        if not text:
            return 'retry', ''
        if _TIME_TEXT_RE.match(text):
            return 'skip', ''
        return 'ok', text
    return 'skip', ''


def _handle_new_item(robot_wxid: str, wxid: str, remark: str, item) -> str:
    '''
    处理检测到的新消息气泡, 返回处理结果供调用方决定 seen 归集:
      'ok'    —— 已转发成功或明确忽略, rid 可计入 seen
      'retry' —— 暂时处理不了(读不出文本/上报失败), rid 不进 seen 下轮重试
    '''
    status, text = _classify_item(item, remark)
    if status != 'ok':
        return status
    if is_recent_sent_echo(wxid, text):
        logger.info('[%s] 自家回声, 忽略: %.30s', remark, text)
        return 'ok'
    # 窗口重连/重绘后 runtime_id 集体变化，历史消息会被误判为新消息重复转发
    # （曾导致一条命令被转发 3 次、提醒反复重设重触发）。60s 内相同
    # (wxid, text) 已转发过则跳过；60s 后正常重发命令不受影响。
    if is_recent_inbound(wxid, text):
        logger.info('[%s] 60s 内已转发过相同内容, 疑似重连误报, 忽略: %.30s',
                    remark, text)
        return 'ok'
    logger.info('[%s] 新消息: %.50s', remark, text)
    payload = build_private_message(robot_wxid, wxid, remark, text)
    if post_event(payload):
        try:
            log_inbound(wxid, text)
        except OSError as e:
            logger.warning('[%s] 转发去重记录失败(不影响上报): %s', remark, e)
        return 'ok'
    logger.error('[%s] 10002 上报失败(已重试), 本条下轮重试: %.50s', remark, text)
    return 'retry'


# ============================================================
# 入口
# ============================================================

def main() -> None:
    if not load_config():
        sys.exit(1)

    # UIA 客户端闸门(2026-09-01 根因): 微信树初始化期间本进程若发起
    # COM 连接会毒死微信 UIA, 必须等主窗口出现并稳定后才碰 UIA。
    if not wait_wechat_ready(logger, timeout=900, settle=15):
        logger.error('15 分钟内未见微信主窗口, 退出(勿在微信未就绪时初始化 UIA)')
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
