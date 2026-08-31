'''
wx_sender_server.py —— 个人微信收发服务（发送 + 白名单监听回调）
================================================

发送链路（替代已停用的 15000 端口 huizai 个人微信机器人 API）:
    coinMarker(远程服务器 91.98.134.93)
        → POST http://127.0.0.1:15000/api/{robotWxId}/send_text
        → frpc 隧道 "wx" (frpc-wx.toml, 本地15000→远程15000)
        → 本服务(队列) → pyweixin UIA → 微信客户端发送

收消息链路（替代已停用的 StarBot 回调通道，listener.enabled=true 时开启）:
    微信客户端（白名单好友独立聊天窗口）
        → WhitelistListener（runtime_id 增量轮询，见 wx_listener.py）
        → CallbackWorker → POST {callback.url}（StarBot 兼容 event="10002"）
        → coinMarker 91.98.134.93:19600 /wcf/callback

收发两侧的 UIA 操作通过 wx_common.UIA_LOCK 全局互斥（微信 UIA 单线程）。

发送 API（coinMarker 服务器端零改动）:
    POST /api/{robotWxId}/send_text
    body: {"to_wxid": "48123779466@chatroom", "content": "消息内容"}
    可选: {"at_all": true}  覆盖配置文件中该目标的 at_all 设置

管理/调试接口:
    GET  /health      队列与 worker 运行状态（listener.enabled 时含监听/回调状态）
    GET  /targets     当前 wxid→群名 映射（脱敏）
    POST /send        按群名直接发送（本地测试用） body: {"name","content","at_all"}

前置条件（缺一不可）:
    1. NVDA 便携版静默运行（激活微信 UIA，见 memory: wechat-nvda-activation）
    2. 微信已登录且保持运行
    3. 发送期间不要人工操作键鼠（pyautogui 会接管输入）
    4. 监听模式下白名单好友的独立聊天窗口不要人工关闭（被关后 60s 自动重开）

映射配置: 同目录 wx_sender_config.json（首次运行自动生成模板）
    targets 内 name 留空的 wxid 会被拒绝发送并记日志，填好后无需重启
    （每条消息发送前重新读取配置）。
    listener.friends 为白名单好友 wxid→备注名映射（备注名必须完整精确）。
'''

import json
import logging
import os
import queue
import random
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pyweixin import Messages  # noqa: E402
from pyweixin.Config import GlobalConfig  # noqa: E402

from wx_common import UIA_LOCK, record_sent_intent, drop_sent_intent  # noqa: E402
from wx_listener import WhitelistListener, CallbackWorker, detect_robot_wxid  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'wx_sender_config.json')

# 任务结束绝不关闭微信（常驻服务）
GlobalConfig.close_weixin = False

# ---------------- 日志 ----------------
logger = logging.getLogger('wx_sender')
logger.setLevel(logging.INFO)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)
try:
    from logging.handlers import RotatingFileHandler
    _file = RotatingFileHandler(os.path.join(BASE_DIR, 'wx_sender.log'),
                                maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')
    _file.setFormatter(_fmt)
    logger.addHandler(_file)
except Exception:
    pass

# ---------------- 默认配置模板 ----------------
# wxid 常量来自 coinMarker/SendWxMsg/SendWxMsg_huizai.go 与 starbot 白名单(main.go)
# 群聊条目按需增删；VolumeBreakout 群推送需把服务器 PYWX_VOLUME_BREAKOUT_GROUP_ID
# 对应的 @chatroom id 加入 targets 并填群显示名。
DEFAULT_CONFIG = {
    'listen_host': '127.0.0.1',
    'listen_port': 15000,
    'queue_max': 200,        # 队列上限，满则丢弃（与 Go 端行为一致）
    'send_interval': [3, 6],  # 每条消息发送后的随机延迟秒数（模仿 Go 端 RandomDelay(3,6)）
    'fail_cooldown': 60,     # 连续失败 fail_threshold 次后的冷却秒数
    'fail_threshold': 5,
    'targets': {
        '48123779466@chatroom': {'name': '', 'at_all': True,  'desc': 'JSSZ 急速上涨'},
        '43846025020@chatroom': {'name': '', 'at_all': False, 'desc': 'KXZJ 快讯总结'},
        '43258695223@chatroom': {'name': '', 'at_all': False, 'desc': 'Thedefiant 交易所崩盘'},
        '44177931368@chatroom': {'name': '', 'at_all': False, 'desc': 'JYSZBJK 交易所指标监控'},
        '44456629368@chatroom': {'name': '', 'at_all': False, 'desc': 'Fangchengshi 方程式新闻'},
        '50587746113@chatroom': {'name': '', 'at_all': False, 'desc': 'Twitter 推特监控'},
        '18743464752@chatroom': {'name': '', 'at_all': False, 'desc': 'Aming 推特监控'},
        '49568875761@chatroom': {'name': '', 'at_all': False, 'desc': 'FLJXGJH 封狼居胥冠军侯'},
        'wxid_xerhivsxr9u6':    {'name': '', 'at_all': False, 'desc': 'Xiaokang 私聊（白名单）'},
        'litiantianss':         {'name': '', 'at_all': False, 'desc': '甜小米 私聊（白名单）'},
        'wxid_ahdz8pwq9dk312':  {'name': '', 'at_all': False, 'desc': 'Michelle 私聊（白名单）'},
    },
    # ---- 收消息监听 + 回调转发（替代 StarBot 回调通道）----
    'listener': {
        'enabled': False,     # 填好 friends 的备注名后再改为 true
        'poll_interval': 1.5, # 独立窗口轮询间隔（秒）
        # 白名单好友 wxid → 微信内显示/备注名（必须完整精确，搜索定位用）
        'friends': {
            'wxid_xerhivsxr9u622': '',
            'litiantianss': '',
            'wxid_ahdz8pwq9dk312': '',
        },
    },
    'callback': {
        'url': 'http://91.98.134.93:19600/wcf/callback',
        'token': '',          # 与服务器 PYWX_CALLBACK_TOKEN 一致（Authorization 裸 token）
        'robot_wxid': '',     # 本机登录微信的 wxid，留空自动探测（非 wxid_ 前缀账号须手填）
        'timeout': 5,
        'max_retries': 3,
    },
}


def load_config() -> dict:
    '''每次读取最新配置（name 映射可热更新，无需重启服务）'''
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def ensure_config() -> dict:
    '''配置文件不存在时生成模板'''
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        logger.info('已生成配置模板 %s，请填写 targets 内的 name（群聊显示名）后即可使用', CONFIG_PATH)
    return load_config()


# ---------------- 发送 worker（单线程，UIA 一次只能操作一个微信窗口） ----------------
class SendWorker(threading.Thread):
    def __init__(self, send_queue: queue.Queue):
        super().__init__(daemon=True, name='send-worker')
        self.send_queue = send_queue
        self.sent_total = 0
        self.failed_total = 0
        self.dropped_total = 0
        self.last_error = ''
        self.last_sent_at = ''
        self.consecutive_fails = 0

    def run(self):
        logger.info('发送 worker 已启动（单线程串行，与监听共享 UIA_LOCK）')
        while True:
            job = self.send_queue.get()
            sent_wxid = job.get('wxid', 'direct')
            try:
                # 先登记后发送：监听窗口会看到自己发出的消息，据此过滤自回环
                record_sent_intent(sent_wxid, job['content'])
                try:
                    with UIA_LOCK:  # 与 WhitelistListener 的 UIA 读操作互斥
                        Messages.send_messages_to_friend(
                            friend=job['name'],
                            messages=[job['content']],
                            at_all=job['at_all'],
                        )
                except Exception:
                    drop_sent_intent(sent_wxid, job['content'])  # 未发出，撤销登记
                    raise
                self.sent_total += 1
                self.consecutive_fails = 0
                self.last_sent_at = time.strftime('%Y-%m-%d %H:%M:%S')
                preview = job['content'][:50].replace('\n', ' ')
                logger.info('已发送 → %s: %s%s', job['name'], preview, '…' if len(job['content']) > 50 else '')
            except Exception as e:
                self.failed_total += 1
                self.consecutive_fails += 1
                self.last_error = f'{type(e).__name__}: {e}'
                logger.error('发送失败(%d 连败) → %s | %s', self.consecutive_fails, job['name'], self.last_error)
            finally:
                self.send_queue.task_done()
                interval = load_config().get('send_interval', [3, 6])
                time.sleep(random.randint(*interval))
                # 连续失败过多进入冷却，避免 UIA 异常时疯狂重试
                cfg = load_config()
                if self.consecutive_fails >= cfg.get('fail_threshold', 5):
                    logger.warning('连续失败 %d 次，冷却 %d 秒（请检查微信/NVDA 状态）',
                                   self.consecutive_fails, cfg.get('fail_cooldown', 60))
                    time.sleep(cfg.get('fail_cooldown', 60))
                    self.consecutive_fails = 0


# ---------------- HTTP 服务 ----------------
send_queue: queue.Queue = None  # type: ignore
worker: SendWorker = None  # type: ignore
listener: WhitelistListener = None  # type: ignore
callback_worker: CallbackWorker = None  # type: ignore


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 静默默认访问日志，由业务日志接管
        pass

    # ---- 工具 ----
    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # ---- GET ----
    def do_GET(self):
        if self.path == '/health':
            cfg = load_config()
            configured = sum(1 for t in cfg['targets'].values() if t.get('name'))
            payload = {
                'status': 'ok' if worker and worker.is_alive() else 'degraded',
                'queue_size': send_queue.qsize(),
                'queue_max': cfg.get('queue_max', 200),
                'sent_total': worker.sent_total,
                'failed_total': worker.failed_total,
                'dropped_total': worker.dropped_total,
                'last_sent_at': worker.last_sent_at,
                'last_error': worker.last_error,
                'targets_configured': f'{configured}/{len(cfg["targets"])}',
                'listener_enabled': bool((cfg.get('listener') or {}).get('enabled')),
            }
            if listener is not None:
                payload['listener_status'] = listener.status()
            if callback_worker is not None:
                payload['callback_status'] = callback_worker.status()
            self._json(200, payload)
        elif self.path == '/targets':
            targets = {wxid: {'name': t.get('name', ''), 'desc': t.get('desc', ''),
                              'at_all': t.get('at_all', False)}
                       for wxid, t in load_config()['targets'].items()}
            self._json(200, targets)
        else:
            self._json(404, {'error': 'not found'})

    # ---- POST ----
    def do_POST(self):
        # 旧 API: /api/{robotWxId}/send_text —— robotWxId 仅记录，不校验（当前登录账号即发送者）
        if self.path.startswith('/api/') and self.path.endswith('/send_text'):
            body = self._read_body()
            to_wxid = str(body.get('to_wxid', '')).strip()
            content = str(body.get('content', '')).strip()
            at_all_override = body.get('at_all')
            if not to_wxid or not content:
                self._json(400, {'error': 'to_wxid/content 不能为空'})
                return
            target = load_config()['targets'].get(to_wxid)
            if not target:
                worker.dropped_total += 1
                logger.warning('未配置的目标 wxid: %s，已丢弃', to_wxid)
                self._json(404, {'error': f'unknown to_wxid: {to_wxid}'})
                return
            name = target.get('name', '')
            if not name:
                worker.dropped_total += 1
                logger.warning('目标 %s (%s) 的 name 未配置，已丢弃', to_wxid, target.get('desc', ''))
                self._json(404, {'error': f'target {to_wxid} not configured name'})
                return
            at_all = bool(at_all_override) if at_all_override is not None else bool(target.get('at_all'))
            self._enqueue({'name': name, 'content': content, 'at_all': at_all}, to_wxid)
        # 调试接口: /send —— 按群名直接发（本地测试用，不查映射）
        elif self.path == '/send':
            body = self._read_body()
            name = str(body.get('name', '')).strip()
            content = str(body.get('content', '')).strip()
            at_all = bool(body.get('at_all', False))
            if not name or not content:
                self._json(400, {'error': 'name/content 不能为空'})
                return
            self._enqueue({'name': name, 'content': content, 'at_all': at_all}, 'direct')
        else:
            self._json(404, {'error': 'not found'})

    def _enqueue(self, job: dict, src: str):
        # src 即发送目标 wxid（/send 调试路径为 'direct'），供自回环过滤登记用
        job['wxid'] = src
        try:
            send_queue.put_nowait(job)
            logger.info('入队 ← %s → %s', src, job['name'])
            self._json(200, {'code': 0, 'queued': True, 'queue_size': send_queue.qsize()})
        except queue.Full:
            worker.dropped_total += 1
            logger.error('队列已满，丢弃消息 → %s', job['name'])
            self._json(503, {'code': 1, 'error': 'queue full'})


def check_prerequisites():
    '''启动前检查微信/NVDA 进程，只警告不阻止（NVDA 可后补启动）'''
    def find_process(name: str) -> bool:
        try:
            out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {name}'],
                                 capture_output=True, text=True, timeout=10).stdout
            return name.lower() in out.lower()
        except Exception:
            return False

    if not find_process('Weixin.exe'):
        logger.warning('⚠ 未检测到微信进程，请先登录微信')
    if not (find_process('nvda.exe') or find_process('nvda_slave.exe')):
        logger.warning('⚠ 未检测到 NVDA 进程，UIA 可能无法定位微信控件（见 memory: wechat-nvda-activation）')


def main():
    global send_queue, worker, listener, callback_worker
    # 重定向到文件时才切 UTF-8（logging.StreamHandler 默认绑 stderr，两个流都要处理）
    for _stream in (sys.stdout, sys.stderr):
        if _stream and not _stream.isatty() and hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8')

    cfg = ensure_config()
    check_prerequisites()

    send_queue = queue.Queue(maxsize=cfg.get('queue_max', 200))
    worker = SendWorker(send_queue)
    worker.start()

    # ---- 收消息监听 + 回调转发（listener.enabled 时开启）----
    listener_cfg = cfg.get('listener') or {}
    if listener_cfg.get('enabled'):
        callback_cfg = cfg.get('callback') or {}
        robot_wxid = detect_robot_wxid(callback_cfg)
        if robot_wxid:
            logger.info('当前机器人 wxid: %s', robot_wxid)
        else:
            logger.warning('robot_wxid 未配置且探测失败，回调事件 robotId 将为空'
                           '（coinMarker 侧需配 PYWX_ROBOT_WXID 兜底注册 session）')
        forward_queue = queue.Queue(maxsize=100)
        listener = WhitelistListener(listener_cfg.get('friends') or {},
                                     forward_queue,
                                     poll_interval=listener_cfg.get('poll_interval', 1.5))
        callback_worker = CallbackWorker(callback_cfg, robot_wxid, forward_queue)
        listener.start()
        callback_worker.start()
    else:
        logger.info('listener.enabled=false，收消息监听未开启（纯发送模式）')

    host, port = cfg.get('listen_host', '127.0.0.1'), cfg.get('listen_port', 15000)
    server = ThreadingHTTPServer((host, port), Handler)
    logger.info('wx_sender 服务已启动 http://%s:%d （Ctrl+C 退出）', host, port)
    logger.info('待配置映射: GET /targets 可查看，填好 wx_sender_config.json 的 name 后无需重启')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info('服务退出')


if __name__ == '__main__':
    main()
