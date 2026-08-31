'''
wx_listener.py —— 白名单好友私聊消息监听 + 回调转发
================================================

配合 wx_sender_server.py 运行，替代已停用的 StarBot 回调通道：

    微信客户端（独立聊天窗口）
        → WhitelistListener（单线程轮询窗口尾部 ListItem 的 runtime_id 增量）
        → forward_queue → CallbackWorker
        → POST {callback.url}（StarBot 兼容格式 event="10002"）
        → coinMarker 91.98.134.93:19600 /wcf/callback

设计要点:
    1. 不用 Messages.check_new_messages()（红点徽标竞态 + pull 会拉到自己回复），
       改用独立窗口 + runtime_id 增量监听（同 Monitor.listen_on_chat 的机制，
       但自实现常驻轮询，单线程串行处理所有白名单窗口）。
    2. 自回环双层防护：runtime_id 增量 + wx_common.is_recently_sent
       （SendWorker 发送前登记，本服务发出的回复不会被子转发回 coinMarker）。
    3. 所有 pyweixin 调用（开窗/置底/读控件）持 wx_common.UIA_LOCK，
       与 SendWorker 的发送严格串行，避免 UIA 多线程死锁。
    4. burst 吸收：每轮检查尾部 TAIL_SCAN 个 item 的 runtime_id，
       两次轮询间连发的多条消息不会只识别到最后一条。
    5. 窗口被误关/微信重启 → watchdog 限频重开（REOPEN_COOLDOWN 秒），
       重开后把当前尾部消息记为已见（历史消息不转发）。

配置（wx_sender_config.json）:
    "listener": {"enabled": true, "poll_interval": 1.5,
                 "friends": {"<好友wxid>": "<好友备注/显示名，必须完整精确>"}}
    "callback": {"url": "http://91.98.134.93:19600/wcf/callback",
                 "token": "...", "robot_wxid": "", "timeout": 5, "max_retries": 3}
'''

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from collections import deque

from pyweixin import Navigator, Tools, SystemSettings  # noqa: E402
from pyweixin.Uielements import Lists  # noqa: E402

from wx_common import UIA_LOCK, is_recently_sent  # noqa: E402

logger = logging.getLogger('wx_sender')

# 微信文本消息 ListItem 的 UIA 类名
TEXT_ITEM_CLASS = 'mmui::ChatTextItemView'
# 每轮轮询检查尾部 item 数（burst 吸收：两次轮询间连发多条也能逐条识别）
TAIL_SCAN = 5
# 每窗口记住的最近 runtime_id 数量（超出即淘汰，防内存增长）
RID_MEMORY = 16
# 窗口失效（被关/微信重启）后的重开冷却秒数
REOPEN_COOLDOWN = 60
# 回调重试退避间隔（秒）
RETRY_BACKOFF = [2, 4, 8]


class ForwardMsg:
    '''一条待转发的白名单私聊消息'''

    __slots__ = ('wxid', 'name', 'text', 'msg_id', 'ts_ms')

    def __init__(self, wxid: str, name: str, text: str, ts_ms: int):
        self.wxid = wxid
        self.name = name
        self.text = text
        self.ts_ms = ts_ms
        self.msg_id = f'{wxid}-{ts_ms}-{hash(text) & 0xFFFFFF:x}'


class _FriendState:
    '''单个白名单好友的监听状态'''

    __slots__ = ('wxid', 'name', 'window', 'chatList', 'seen_rids',
                 'last_msg_at', 'reopen_at', 'last_error')

    def __init__(self, wxid: str, name: str):
        self.wxid = wxid
        self.name = name
        self.window = None       # pywinauto WindowSpecification，None 表示待（重）开
        self.chatList = None     # 消息列表控件（Lists.FriendChatList）
        self.seen_rids = deque(maxlen=RID_MEMORY)
        self.last_msg_at = 0.0
        self.reopen_at = 0.0     # time.time()，窗口失效后的最早重开时刻
        self.last_error = ''


class WhitelistListener(threading.Thread):
    '''白名单好友独立窗口消息监听（单线程串行轮询所有窗口）'''

    def __init__(self, friends_cfg: dict, forward_queue: queue.Queue,
                 poll_interval: float = 1.5):
        super().__init__(daemon=True, name='wx-listener')
        self.poll_interval = max(0.5, float(poll_interval or 1.5))
        self.forward_queue = forward_queue
        self.states = [_FriendState(wxid, name)
                       for wxid, name in (friends_cfg or {}).items()
                       if name]
        self.started_at = time.time()
        missing = [wxid for wxid, name in (friends_cfg or {}).items() if not name]
        if missing:
            logger.warning('listener.friends 中以下好友的备注名为空，已跳过监听: %s', missing)

    # ---------------- 主循环 ----------------
    def run(self):
        if not self.states:
            logger.warning('listener.friends 为空，监听线程直接退出（请检查 wx_sender_config.json）')
            return
        try:
            # 防息屏（SetThreadExecutionState，线程级）：部署机长期运行必须保持屏幕常亮
            SystemSettings.open_listening_mode(volume=False)
        except Exception as e:
            logger.warning('防息屏设置失败（不影响监听，但请关闭系统息屏/休眠）: %s', e)

        logger.info('白名单监听已启动: %d 个好友, 轮询间隔 %.1fs',
                    len(self.states), self.poll_interval)
        self._open_all()
        while True:
            for st in self.states:
                try:
                    self._poll_friend(st)
                except Exception as e:
                    # 单个好友异常不影响其他窗口；UIA 异常通常是窗口失效
                    self._mark_broken(st, f'{type(e).__name__}: {e}')
            time.sleep(self.poll_interval)

    # ---------------- 开窗 ----------------
    def _open_all(self):
        for st in self.states:
            self._open_one(st)

    def _open_one(self, st: _FriendState):
        '''打开（或重开）独立聊天窗口并建立 runtime_id 基准。

        历史/基准消息只记 seen_rids 不转发。开窗与置底有键鼠操作，持 UIA_LOCK。
        '''
        try:
            with UIA_LOCK:
                window = Navigator.open_seperate_dialog_window(
                    friend=st.name, is_maximize=False,
                    window_minimize=True, close_weixin=False)
                chatList = window.child_window(**Lists.FriendChatList)
                Tools.activate_chatList(chatList)  # 滚到底部（键鼠）
                items = chatList.children(control_type='ListItem')
            st.window = window
            st.chatList = chatList
            st.seen_rids.clear()
            # 当前尾部消息全部记为已见：重开窗口不能把历史消息当新消息转发
            for item in items[-TAIL_SCAN:]:
                st.seen_rids.append(item.element_info.runtime_id)
            st.last_error = ''
            logger.info('监听窗口已就绪 → %s (%s)，基准消息 %d 条',
                        st.name, st.wxid, min(len(items), TAIL_SCAN))
        except Exception as e:
            self._mark_broken(st, f'开窗失败 {type(e).__name__}: {e}')

    def _mark_broken(self, st: _FriendState, reason: str):
        st.window = None
        st.chatList = None
        st.reopen_at = time.time() + REOPEN_COOLDOWN
        st.last_error = reason
        logger.error('监听窗口失效 → %s (%s) | %s | %ds 后重开',
                     st.name, st.wxid, reason, REOPEN_COOLDOWN)

    # ---------------- 轮询 ----------------
    def _poll_friend(self, st: _FriendState):
        if st.window is None:
            if time.time() >= st.reopen_at:
                self._open_one(st)
            return

        with UIA_LOCK:
            items = st.chatList.children(control_type='ListItem')
        if not items:
            return

        # 尾部 TAIL_SCAN 个 item 逐个比对 runtime_id，未见过即新消息
        for item in items[-TAIL_SCAN:]:
            rid = item.element_info.runtime_id
            if rid in st.seen_rids:
                continue
            st.seen_rids.append(rid)
            # 只转发文本消息；时间戳/系统消息(ChatItemView)/图片文件等忽略
            if item.class_name() != TEXT_ITEM_CLASS:
                continue
            text = (item.window_text() or '').strip()
            if not text:
                continue
            if is_recently_sent(st.wxid, text):
                continue  # 本服务刚发出的回复，过滤自回环
            st.last_msg_at = time.time()
            self._enqueue(ForwardMsg(st.wxid, st.name, text, int(time.time() * 1000)))

    def _enqueue(self, msg: ForwardMsg):
        try:
            self.forward_queue.put_nowait(msg)
            preview = msg.text[:50].replace('\n', ' ')
            logger.info('新消息 → %s (%s): %s%s',
                        msg.name, msg.wxid, preview, '…' if len(msg.text) > 50 else '')
        except queue.Full:
            logger.error('转发队列已满，丢弃消息 ← %s: %s', msg.name, msg.text[:50])

    # ---------------- 状态 ----------------
    def status(self) -> dict:
        return {
            'running': self.is_alive(),
            'poll_interval': self.poll_interval,
            'friends': {
                st.wxid: {
                    'name': st.name,
                    'window_ok': st.window is not None,
                    'last_msg_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.last_msg_at))
                    if st.last_msg_at else '',
                    'last_error': st.last_error,
                } for st in self.states
            },
        }


class CallbackWorker(threading.Thread):
    '''把转发队列中的消息以 StarBot 兼容格式 POST 到 coinMarker 回调端点'''

    def __init__(self, callback_cfg: dict, robot_wxid: str, forward_queue: queue.Queue):
        super().__init__(daemon=True, name='wx-callback')
        self.url = callback_cfg.get('url', '')
        self.token = callback_cfg.get('token', '')
        self.robot_wxid = robot_wxid or ''
        self.timeout = callback_cfg.get('timeout', 5)
        self.max_retries = callback_cfg.get('max_retries', 3)
        self.forward_queue = forward_queue
        self.forwarded_total = 0
        self.dropped_total = 0
        self.last_forward_at = ''
        self.last_error = ''

    # ---------------- 主循环 ----------------
    def run(self):
        if not self.url:
            logger.warning('callback.url 为空，回调转发线程退出（仅监听不转发）')
            return
        self._send_login_event()
        logger.info('回调转发已启动 → %s', self.url)
        while True:
            msg = self.forward_queue.get()
            try:
                self._post_message(msg)
            finally:
                self.forward_queue.task_done()

    # ---------------- 事件构造 ----------------
    def _post_message(self, msg: ForwardMsg):
        payload = {
            'event': '10002',
            'description': '私聊消息事件',
            'time': msg.ts_ms,
            'robotId': self.robot_wxid,
            'data': {
                'robotId': self.robot_wxid,
                'fromType': 'private',
                'fromWxId': msg.wxid,
                'fromNickName': msg.name,
                'message': msg.text,
                'timeStamp': msg.ts_ms,
                'messageId': msg.msg_id,
                'messageType': 1,
                'messageSource': 0,
                'toWxId': self.robot_wxid,
                'isPc': 1,
            },
        }
        if self._post_json(payload, what=f'消息 ← {msg.name}'):
            self.forwarded_total += 1

    def _send_login_event(self):
        '''启动时发送 event=10001，coinMarker 侧自动注册机器人 session。

        失败仅告警不阻塞：命令回复走 15000 发送 API 与 session 无关，
        session 可由 coinMarker 侧 PYWX_ROBOT_WXID 环境变量兜底注册。
        '''
        payload = {
            'event': '10001',
            'description': '微信登录成功',
            'time': int(time.time() * 1000),
            'robotId': self.robot_wxid,
            'data': {'robotId': self.robot_wxid, 'nickname': self.robot_wxid},
        }
        ok = self._post_json(payload, what='登录事件', retries=3, backoff=10)
        if not ok:
            logger.warning('登录事件发送失败（不影响消息转发，coinMarker 侧可用 PYWX_ROBOT_WXID 兜底）')

    # ---------------- HTTP ----------------
    def _post_json(self, payload: dict, what: str, retries: int = None, backoff: int = None) -> bool:
        '''POST JSON 到回调端点。连接错误/超时/5xx 按退避重试，4xx 不重试。

        at-least-once 语义：coinMarker 侧 SaveAlert 的 Redis field 确定性
        （幂等覆盖），重复投递安全；重试耗尽后丢弃并记日志。
        '''
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        attempts = self.max_retries if retries is None else retries
        delays = [backoff] * attempts if backoff else RETRY_BACKOFF
        for i in range(attempts + 1):
            try:
                req = urllib.request.Request(
                    self.url, data=body, method='POST',
                    headers={'Content-Type': 'application/json; charset=utf-8',
                             'Authorization': self.token})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if 200 <= resp.status < 300:
                        self.last_forward_at = time.strftime('%Y-%m-%d %H:%M:%S')
                        self.last_error = ''
                        return True
                    err = f'HTTP {resp.status}'
            except urllib.error.HTTPError as e:
                err = f'HTTP {e.code}'
                if 400 <= e.code < 500:
                    break  # 4xx（如 token 错误）重试无意义
            except Exception as e:
                err = f'{type(e).__name__}: {e}'

            if i < attempts:
                delay = delays[min(i, len(delays) - 1)]
                logger.warning('%s 发送失败(%s)，%ds 后重试(%d/%d)',
                               what, err, delay, i + 1, attempts)
                time.sleep(delay)

        self.dropped_total += 1
        self.last_error = err
        logger.error('%s 发送最终失败，已丢弃 | %s', what, err)
        return False

    # ---------------- 状态 ----------------
    def status(self) -> dict:
        return {
            'url': self.url,
            'robot_wxid': self.robot_wxid,
            'forward_queue_size': self.forward_queue.qsize(),
            'forwarded_total': self.forwarded_total,
            'dropped_total': self.dropped_total,
            'last_forward_at': self.last_forward_at,
            'last_error': self.last_error,
        }


def detect_robot_wxid(callback_cfg: dict) -> str:
    '''回调配置的 robot_wxid 优先，为空则从微信数据目录探测当前登录 wxid。

    纯文件系统操作（不涉及 UIA），探测失败返回空串由调用方告警。
    '''
    wxid = str(callback_cfg.get('robot_wxid', '') or '').strip()
    if wxid:
        return wxid
    try:
        return Tools.get_current_wxid()
    except Exception as e:
        logger.warning('get_current_wxid 探测失败（非 wxid_ 前缀账号或未登录?）: %s', e)
        return ''
