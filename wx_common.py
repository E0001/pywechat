'''
wx_common.py —— 发送服务与消息监听的共享基础设施
================================================

1. UIA_LOCK: pyweixin 所有 UIA 操作（读 + 键鼠）的全局互斥锁。
   微信 UIA 是单线程 COM 对象，跨线程并发操作会死锁/串扰，
   SendWorker（发送）与 WhitelistListener（监听轮询）必须串行使用。
   锁粒度 = 单次完整 UIA 操作（一次发送 / 一次控件读取），
   发送后的随机节流延迟在锁外，保持原有节流语义。

2. 自回环过滤: 监听窗口会看到本服务自己发出的消息（item 同样 append），
   SendWorker 发送【前】登记意图，监听侧据此过滤。
   先登记后发送可消除 "item append 早于登记" 的竞态窗口。
'''

import collections
import re
import threading
import time

# 所有 pyweixin 调用（UIA 读 + 键鼠操作）统一持此锁
UIA_LOCK = threading.RLock()

# 自回环记忆时长（秒）：发送成功后该内容在此窗口内被监听侧忽略
_ECHO_TTL = 15 * 60

# wxid -> deque[(content, ts)]，按时间升序，超量/超时淘汰
_echo_map: dict = {}
_echo_mu = threading.Lock()

# 每个 wxid 最多记忆条数（防长文本命令刷爆内存）
_ECHO_MAX_PER_WXID = 64

_WS_RE = re.compile(r'\s+')


def _normalize(text: str) -> str:
    '''归一化：去除所有空白字符后比较（监听取到的文本可能带换行/尾随空格）'''
    return _WS_RE.sub('', text or '')


def record_sent_intent(wxid: str, content: str):
    '''SendWorker 发送前登记意图（先登记后发送，消除竞态）。

    wxid 为 'direct'（/send 调试路径）时不登记——调试消息不参与自回环过滤。
    '''
    if not wxid or wxid == 'direct' or not content:
        return
    now = time.time()
    with _echo_mu:
        dq = _echo_map.setdefault(wxid, collections.deque())
        dq.append((_normalize(content), now))
        _evict(dq, now)


def drop_sent_intent(wxid: str, content: str):
    '''发送抛异常时撤销登记（该消息实际未发出，不应被过滤）'''
    if not wxid or wxid == 'direct' or not content:
        return
    key = _normalize(content)
    if not key:
        return
    with _echo_mu:
        dq = _echo_map.get(wxid)
        if not dq:
            return
        for item in dq:  # 只删最早一条匹配内容（同名内容多次发送时保留其余）
            if item[0] == key:
                dq.remove(item)
                break


def is_recently_sent(wxid: str, content: str) -> bool:
    '''判断该内容是否为近 _ECHO_TTL 内本服务向该 wxid 发出（需过滤的自回环）'''
    if not wxid or not content:
        return False
    key = _normalize(content)
    if not key:
        return False
    now = time.time()
    with _echo_mu:
        dq = _echo_map.get(wxid)
        if not dq:
            return False
        _evict(dq, now)
        return any(item[0] == key for item in dq)


def _evict(dq: collections.deque, now: float):
    '''淘汰过期与超量条目（调用方需已持有 _echo_mu）'''
    while dq and now - dq[0][1] > _ECHO_TTL:
        dq.popleft()
    while len(dq) > _ECHO_MAX_PER_WXID:
        dq.popleft()
