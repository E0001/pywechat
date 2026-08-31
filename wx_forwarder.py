# -*- coding: utf-8 -*-
"""
wx_forwarder.py — chatlog webhook → coinMarker starbot 回调转发器（收信链路）

架构（2026-08-31，替代原计划的 wx_listener.py UIA 监听方案）:
  微信落库(SQLCipher) → chatlog server(:5030, --auto-decrypt, webhook 增量推送)
    → POST 本服务 :5031/webhook
    → 过滤(白名单私聊 / 文本 / 非本人发送) → 组装 StarBot 兼容 10002 JSON
    → POST {callback_url}（coinMarker starbot 包, :19600/wcf/callback）
  启动时上报 10001 登录事件（会话注册，服务器 /wcf/health sessions=1）。

与 wx_sender(:15000) 完全解耦：收信走本地数据库解密，发送走 UIA，无锁竞争。
回调 JSON 契约见 coin-marker starbot/types.go（StarBot 兼容格式）。
"""

import hashlib
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
import shutil
import subprocess

BASE = Path(__file__).resolve().parent
CONF_PATH = BASE / "wx_forwarder_config.json"
SENDER_CONF_PATH = BASE / "wx_sender_config.json"

log = logging.getLogger("wx_forwarder")


def setup_logging():
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(BASE / "wx_forwarder.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[fh, sh])


class Forwarder:
    def __init__(self, conf: dict):
        self.conf = conf
        self.robot_wxid = conf["robot_wxid"]
        self.callback_url = conf["callback_url"]
        self.callback_token = conf.get("callback_token", "")
        self.whitelist = set(conf.get("whitelist", []))
        # 备注名映射：优先 wx_sender_config.json targets（回复寻址依赖同一份备注名）
        self.nicknames = {}
        try:
            sender_conf = json.loads(SENDER_CONF_PATH.read_text(encoding="utf-8"))
            for wxid, item in (sender_conf.get("targets") or {}).items():
                if isinstance(item, dict) and item.get("name"):
                    self.nicknames[wxid] = item["name"]
        except Exception as e:
            log.warning("读取 wx_sender_config.json 备注名失败: %s", e)
        # (talker, seq) 去重，chatlog 侧重启不重放，此处为双保险
        self._seen = set()
        self._seen_order = deque(maxlen=10000)
        self.stats = {"received": 0, "forwarded": 0, "dropped": 0, "login_ok": False}
        self._lock = threading.Lock()

    # ---------------- 出站 ----------------

    def _post_callback(self, payload: dict, retries: int = 2):
        headers = {"Content-Type": "application/json"}
        if self.callback_token:
            headers["Authorization"] = self.callback_token
        last_err = None
        for i in range(retries + 1):
            try:
                r = requests.post(self.callback_url, json=payload,
                                  headers=headers, timeout=10)
                if r.status_code == 200:
                    return True
                log.warning("回调非 200: %s %s", r.status_code, r.text[:200])
                return False
            except Exception as e:
                last_err = e
                if i < retries:
                    time.sleep(1 + i)
        log.error("回调失败(已重试): %s", last_err)
        return False

    def report_login(self):
        """上报 10001 登录事件（幂等注册会话），失败则周期重试。"""
        payload = {
            "event": "10001",
            "description": "登录成功",
            "time": int(time.time() * 1000),
            "robotId": self.robot_wxid,
            "data": {
                "instanceId": "",
                "robotId": self.robot_wxid,
                "wxNum": "",
                "nickname": self.conf.get("robot_nickname", ""),
                "device": "",
                "phone": "",
                "avatarUrl": "",
                "country": "",
                "province": "",
                "sign": "",
            },
        }
        while not self.stats["login_ok"]:
            if self._post_callback(payload, retries=1):
                self.stats["login_ok"] = True
                log.info("10001 登录事件上报成功: %s", self.robot_wxid)
                return
            log.warning("10001 上报失败，60s 后重试")
            time.sleep(60)

    # ---------------- 入站 ----------------

    def _dedup(self, key) -> bool:
        with self._lock:
            if key in self._seen:
                return False
            self._seen.add(key)
            self._seen_order.append(key)
            if len(self._seen_order) == self._seen_order.maxlen:
                self._seen.discard(self._seen_order[0])
            return True

    def handle_messages(self, messages: list):
        for m in messages:
            self.stats["received"] += 1
            talker = m.get("talker") or ""
            if not self._dedup((talker, m.get("seq"))):
                continue
            if m.get("isSelf"):
                continue
            if m.get("isChatRoom"):
                continue
            if m.get("type") != 1:
                continue  # 仅文本
            if talker not in self.whitelist:
                self.stats["dropped"] += 1
                continue
            content = (m.get("content") or "").strip()
            if not content:
                continue
            ts_ms = self._parse_time_ms(m.get("time"))
            nickname = (m.get("senderName") or m.get("talkerName")
                        or self.nicknames.get(talker, ""))
            message_id = "{}-{}-{}".format(
                self.robot_wxid, ts_ms,
                hashlib.sha1(
                    (self.robot_wxid + talker + content + str(ts_ms)).encode("utf-8")
                ).hexdigest()[:8])
            payload = {
                "event": "10002",
                "description": "私聊消息事件",
                "time": ts_ms,
                "robotId": self.robot_wxid,
                "data": {
                    "instanceId": "",
                    "robotId": self.robot_wxid,
                    "timeStamp": ts_ms,
                    "messageId": message_id,
                    "messageType": 1,
                    "fromType": "private",
                    "messageSource": 0,
                    "fromWxId": talker,
                    "fromNickName": nickname,
                    "message": content,
                    "toWxId": self.robot_wxid,
                    "isPc": 1,
                },
            }
            log.info("转发私聊: %s(%s) -> %r", talker, nickname, content[:50])
            if self._post_callback(payload):
                self.stats["forwarded"] += 1
            else:
                self.stats["dropped"] += 1

    @staticmethod
    def _parse_time_ms(t) -> int:
        try:
            if isinstance(t, (int, float)):
                return int(t if t > 1e12 else t * 1000)
            dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            return int(time.time() * 1000)



    # ---------------- work_dir 24h 清理 ----------------

    def maintenance_loop(self):
        """周期检查：距上次清理超过 20h 则清空 chatlog work_dir 并重启 chatlog。

        work_dir 是解密后的明文聊天库，只服务于增量 webhook，无需长期保留；
        清空后 chatlog 重启会全量重解当前加密库（稳态=最近数据）。
        """
        while True:
            try:
                self._maybe_cleanup()
            except Exception as e:
                log.error("maintenance error: %s", e)
            time.sleep(3600)

    def _maybe_cleanup(self):
        import os as _os
        marker = BASE / "cleanup_marker"
        now = time.time()
        last = marker.stat().st_mtime if marker.exists() else 0
        if now - last < 20 * 3600:
            return
        log.info("开始清理 chatlog work_dir（24h 保留策略）")
        subprocess.run(["taskkill", "/F", "/IM", "chatlog.exe"],
                       capture_output=True)
        time.sleep(3)
        shutil.rmtree(self.conf.get("chatlog_work_dir", ""), ignore_errors=True)
        marker.touch()
        vbs = self.conf.get("chatlog_server_vbs", "")
        if vbs:
            subprocess.Popen(["wscript.exe", vbs])
            log.info("work_dir 已清空，chatlog 重启中: %s", vbs)


def make_handler(fwd: Forwarder):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # 静默默认访问日志，业务日志走 forwarder

        def do_POST(self):
            if self.path.split("?")[0] != "/webhook":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                msgs = body.get("messages") or []
            except Exception as e:
                self._json(400, {"error": str(e)})
                return
            threading.Thread(target=fwd.handle_messages, args=(msgs,),
                             daemon=True).start()
            self._json(200, {"ok": True, "count": len(msgs)})

        def do_GET(self):
            if self.path.split("?")[0] == "/health":
                self._json(200, {"status": "ok",
                                 "robot": fwd.robot_wxid,
                                 "whitelist": sorted(fwd.whitelist),
                                 "stats": fwd.stats})
            else:
                self._json(404, {"error": "not found"})

        def _json(self, code, obj):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main():
    setup_logging()
    conf = json.loads(CONF_PATH.read_text(encoding="utf-8"))
    fwd = Forwarder(conf)
    threading.Thread(target=fwd.report_login, daemon=True).start()
    threading.Thread(target=fwd.maintenance_loop, daemon=True).start()
    addr = (conf.get("listen_host", "127.0.0.1"), int(conf.get("listen_port", 5031)))
    srv = ThreadingHTTPServer(addr, make_handler(fwd))
    log.info("wx_forwarder 监听 %s:%s robot=%s 白名单=%s callback=%s",
             addr[0], addr[1], fwd.robot_wxid, sorted(fwd.whitelist),
             fwd.callback_url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
