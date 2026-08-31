'''
wx_sender_server.py —— 个人微信快讯发送服务
================================================

替代已停用的 15000 端口 huizai 个人微信机器人 API（家庭端服务停用导致
coinMarker 的 JSSZ 急速上涨/KXZJ 快讯总结推送断链）。

链路: coinMarker(远程服务器 91.98.134.93)
        → POST http://127.0.0.1:15000/api/{robotWxId}/send_text
        → frpc 隧道 "wx" (frpc.toml, 本地15000→远程15000)
        → 本服务(队列) → pyweixin UIA → 微信客户端发送

兼容旧 API（coinMarker/SendWxMsg/SendWxMsg_huizai.go 默认 127.0.0.1:15000，
服务器端零改动）:
    POST /api/{robotWxId}/send_text
    body: {"to_wxid": "48123779466@chatroom", "content": "消息内容"}
    可选: {"at_all": true}  覆盖配置文件中该目标的 at_all 设置

管理/调试接口:
    GET  /health      队列与 worker 运行状态
    GET  /targets     当前 wxid→群名 映射（脱敏）
    POST /send        按群名直接发送（本地测试用） body: {"name","content","at_all"}

前置条件（缺一不可）:
    1. NVDA 便携版静默运行（激活微信 UIA，见 memory: wechat-nvda-activation）
    2. 微信已登录且保持运行
    3. 发送期间不要人工操作键鼠（pyautogui 会接管输入）

映射配置: 同目录 wx_sender_config.json（首次运行自动生成模板）
    targets 内 name 留空的 wxid 会被拒绝发送并记日志，填好后无需重启
    （每条消息发送前重新读取配置）。
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

from pyweixin import Messages, Navigator  # noqa: E402
from pyweixin.Config import GlobalConfig  # noqa: E402
import pywinauto  # noqa: E402  语音拨号的飞出菜单/VOIPWindow 检测
import wx_common  # noqa: E402  发送回声记录(与 wx_listener 共享)

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
# wxid 常量来自 coinMarker/SendWxMsg/SendWxMsg_huizai.go
DEFAULT_CONFIG = {
    'listen_host': '127.0.0.1',
    'listen_port': 15000,
    'queue_max': 200,        # 队列上限，满则丢弃（与 Go 端行为一致）
    'send_interval': [3, 6],  # 每条消息发送后的随机延迟秒数（模仿 Go 端 RandomDelay(3,6)）
    'fail_cooldown': 60,     # 连续失败 fail_threshold 次后的冷却秒数
    'fail_threshold': 5,
    'voice_cooldown': 300,   # 同一目标语音通话冷却秒数（防提醒连发时夺命连环call）
    'targets': {
        '48123779466@chatroom': {'name': '', 'at_all': True,  'desc': 'JSSZ 急速上涨'},
        '43846025020@chatroom': {'name': '', 'at_all': False, 'desc': 'KXZJ 快讯总结'},
        '43258695223@chatroom': {'name': '', 'at_all': False, 'desc': 'Thedefiant 交易所崩盘'},
        '44177931368@chatroom': {'name': '', 'at_all': False, 'desc': 'JYSZBJK 交易所指标监控'},
        '44456629368@chatroom': {'name': '', 'at_all': False, 'desc': 'Fangchengshi 方程式新闻'},
        '50587746113@chatroom': {'name': '', 'at_all': False, 'desc': 'Twitter 推特监控'},
        '18743464752@chatroom': {'name': '', 'at_all': False, 'desc': 'Aming 推特监控'},
        '49568875761@chatroom': {'name': '', 'at_all': False, 'desc': 'FLJXGJH 封狼居胥冠军侯'},
        'wxid_xerhivsxr9u6':    {'name': '', 'at_all': False, 'desc': 'Xiaokang 私聊'},
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
    RETRY_MAX = 3     # 任务失败重试次数（防桌面抖动/UIA 偶发冲突时消息永久丢失）
    RETRY_DELAY = 60  # 重试间隔（秒）。2026-08-31 21:23 事故: 桌面失效期间
                      # 3 条消息一次性丢弃, 提醒被"先删后发"语义消耗后再无重发

    def __init__(self, send_queue: queue.Queue):
        super().__init__(daemon=True, name='send-worker')
        self.send_queue = send_queue
        self.sent_total = 0
        self.failed_total = 0
        self.dropped_total = 0
        self.last_error = ''
        self.last_sent_at = ''
        self.consecutive_fails = 0
        self.voice_calls = 0        # 成功拨打的语音通话数
        self.voice_skipped = 0      # 冷却内被跳过的拨号数
        self.last_voice_at = {}     # to_wxid -> 上次成功拨号时间戳

    def voice_cooldown_left(self, to_wxid: str) -> int:
        '''返回该目标语音冷却剩余秒数（0=可拨）'''
        cooldown = load_config().get('voice_cooldown', 300)
        elapsed = time.time() - self.last_voice_at.get(to_wxid, 0)
        return max(0, int(cooldown - elapsed))

    def run(self):
        logger.info('发送 worker 已启动（单线程串行）')
        while True:
            job = self.send_queue.get()
            try:
                if job.get('kind') == 'voice':
                    # 双重冷却检查：入队时已查过，排队期间可能已拨过（防连拨）
                    left = self.voice_cooldown_left(job['to'])
                    if left > 0:
                        self.voice_skipped += 1
                        logger.info('语音冷却中(%ds) → %s，跳过', left, job['name'])
                    else:
                        self._dial_voice(job)
                        self.voice_calls += 1
                        self.last_voice_at[job['to']] = time.time()
                        logger.info('已拨打语音 → %s (通话窗口已确认)', job['name'])
                else:
                    self._send_text(job)
            except Exception as e:
                self.failed_total += 1
                self.last_error = f'{type(e).__name__}: {e}'
                retry_no = job.get('_retry', 0)
                if retry_no < self.RETRY_MAX:
                    job['_retry'] = retry_no + 1
                    logger.warning('任务失败(第 %d/%d 次), %ds 后重试 → %s | %s',
                                   retry_no + 1, self.RETRY_MAX, self.RETRY_DELAY,
                                   job['name'], self.last_error)
                    self._requeue_later(job)
                else:
                    # 重试耗尽才算最终失败，计入连败冷却
                    self.consecutive_fails += 1
                    logger.error('任务重试 %d 次仍失败, 放弃 → %s | %s',
                                 self.RETRY_MAX, job['name'], self.last_error)
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

    def _requeue_later(self, job):
        '''RETRY_DELAY 秒后把失败任务重新入队（独立线程等待，不阻塞队列）。'''
        def _go():
            time.sleep(self.RETRY_DELAY)
            try:
                self.send_queue.put_nowait(job)
                logger.info('重试入队(第 %d 次) → %s', job.get('_retry', 0), job['name'])
            except queue.Full:
                logger.error('重试入队失败(队列已满), 放弃 → %s', job['name'])
        threading.Thread(target=_go, daemon=True,
                         name=f'retry-{job.get("name", "?")}').start()

    def _dial_voice(self, job):
        '''
        语音拨号(两步): 点 voip_button 只会弹出「语音通话/视频通话」飞出菜单
        (微信 4.1.2.17 实测, diag_voice8.py 探明——此前只点按钮导致 4 次假拨号),
        必须再点菜单里的「语音通话」MenuItem 才真正发起; 最后以 VOIPWindow
        出现为准, 未出现视为失败(计连续失败, 不进冷却)。
        '''
        desktop = pywinauto.Desktop(backend='uia')

        # 优先复用 listener 常驻的独立聊天小窗(免搜索导航, 少抢键鼠);
        # 找不到再走主窗口导航。小窗标题不可靠(多为 'Weixin'), 靠窗内
        # 「好友备注名」文本识别。
        chat = None
        for w in desktop.windows(class_name='mmui::ChatSingleWindow'):
            try:
                for c in w.descendants():
                    try:
                        if c.window_text() == job['name']:
                            chat = w
                            break
                    except Exception:
                        pass
                if chat:
                    break
            except Exception:
                pass
        if chat:
            spec = desktop.window(handle=chat.handle)
        else:
            spec = Navigator.open_dialog_window(friend=job['name'])

        spec.set_focus()
        time.sleep(0.3)
        btn = spec.child_window(control_type='Button', auto_id='voip_button')
        btn.click_input()

        # 第二步: 在微信(mmui*)窗口里找飞出菜单的「语音通话」MenuItem
        item = None
        deadline = time.time() + 3
        while time.time() < deadline and item is None:
            for w in desktop.windows():
                if not (w.element_info.class_name or '').startswith('mmui'):
                    continue
                try:
                    for mi in w.descendants(control_type='MenuItem'):
                        if mi.window_text() == '语音通话' and mi.is_visible():
                            item = mi
                            break
                except Exception:
                    pass
                if item:
                    break
            if item is None:
                time.sleep(0.3)
        if item is None:
            raise RuntimeError('语音飞出菜单 3s 内未出现(voip_button 点击未生效?)')
        item.click_input()

        # 以 VOIPWindow 出现为成功判据(「等待对方接受邀请」面板)
        deadline = time.time() + 5
        while time.time() < deadline:
            for w in desktop.windows():
                if (w.element_info.class_name or '') == 'mmui::VOIPWindow':
                    return
            time.sleep(0.5)
        raise RuntimeError('点击菜单项后 5s 内未出现通话窗口(VOIPWindow)')

    def _send_text(self, job):
        Messages.send_messages_to_friend(
            friend=job['name'],
            messages=[job['content']],
            at_all=job['at_all'],
        )
        self.sent_total += 1
        self.consecutive_fails = 0
        self.last_sent_at = time.strftime('%Y-%m-%d %H:%M:%S')
        preview = job['content'][:50].replace('\n', ' ')
        logger.info('已发送 → %s: %s%s', job['name'], preview, '…' if len(job['content']) > 50 else '')
        # 记录发送回声(wx_listener 据此跳过自家消息, 避免收发死循环)
        if job.get('to'):
            try:
                wx_common.log_sent(job['to'], job['content'])
            except Exception as e:
                logger.warning('回声记录失败(不影响发送): %s', e)


# ---------------- HTTP 服务 ----------------
send_queue: queue.Queue = None  # type: ignore
worker: SendWorker = None  # type: ignore


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
            configured = sum(1 for t in load_config()['targets'].values() if t.get('name'))
            self._json(200, {
                'status': 'ok' if worker and worker.is_alive() else 'degraded',
                'queue_size': send_queue.qsize(),
                'queue_max': load_config().get('queue_max', 200),
                'sent_total': worker.sent_total,
                'failed_total': worker.failed_total,
                'dropped_total': worker.dropped_total,
                'last_sent_at': worker.last_sent_at,
                'last_error': worker.last_error,
                'voice_calls': worker.voice_calls,
                'voice_skipped': worker.voice_skipped,
                'targets_configured': f'{configured}/{len(load_config()["targets"])}',
            })
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
            self._enqueue({'name': name, 'content': content, 'at_all': at_all, 'to': to_wxid}, to_wxid)
        # 语音通话: /api/{robotWxId}/voice_call —— 强提醒通道（价格到点打电话）
        # body: {"to_wxid": "..."}；与文本共用队列串行（键鼠互斥），同目标冷却 voice_cooldown
        elif self.path.startswith('/api/') and self.path.endswith('/voice_call'):
            body = self._read_body()
            to_wxid = str(body.get('to_wxid', '')).strip()
            if not to_wxid:
                self._json(400, {'error': 'to_wxid 不能为空'})
                return
            target = load_config()['targets'].get(to_wxid)
            if not target or not target.get('name', ''):
                worker.dropped_total += 1
                logger.warning('语音目标未配置: %s，已丢弃', to_wxid)
                self._json(404, {'error': f'unknown to_wxid: {to_wxid}'})
                return
            left = worker.voice_cooldown_left(to_wxid)
            if left > 0:
                worker.voice_skipped += 1
                logger.info('语音冷却中(%ds) → %s，不入队', left, target['name'])
                self._json(200, {'code': 0, 'queued': False, 'skipped': 'cooldown', 'retry_after': left})
                return
            self._enqueue({'name': target['name'], 'to': to_wxid, 'kind': 'voice'}, to_wxid)
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
    global send_queue, worker
    wx_common.acquire_instance_lock('wx_sender')  # 双生进程第二个在此退出
    # 重定向到文件时才切 UTF-8（logging.StreamHandler 默认绑 stderr，两个流都要处理）
    for _stream in (sys.stdout, sys.stderr):
        if _stream and not _stream.isatty() and hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8')

    cfg = ensure_config()
    check_prerequisites()

    send_queue = queue.Queue(maxsize=cfg.get('queue_max', 200))
    worker = SendWorker(send_queue)
    worker.start()

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
