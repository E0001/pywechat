# wx_sender 快讯推送服务 — 部署指南

把 coinMarker 的快讯（JSSZ 急速上涨 / KXZJ 快讯总结等）推送到**个人微信群**的常驻发送服务。

## 架构

```
远程服务器 91.98.134.93 (coinMarker)
  └─ SendWxMsg_huizai.go → POST http://127.0.0.1:15000/api/{wxid}/send_text
       ↓ frps (端口 17777)
       ↓ frpc 隧道 "wx" (frpc-wx.toml, 本地15000 → 远程15000)
部署机 (Windows, 常驻)
  ├─ NVDA 便携版 (静默运行, 激活微信 UIA)
  ├─ 微信 4.1.x (保持登录, 前台)
  ├─ wx_sender_server.py (FastAPI-free, 标准库 HTTP, :15000)
  │    └─ 单线程队列 → pyweixin.Messages.send_messages_to_friend(群名, [消息])
  └─ start_wx_sender.bat (一键启动)
```

**coinMarker 服务器端零改动**：`SendWxMsg_huizai.go` 默认地址就是 `127.0.0.1:15000`，
frps 上的 wx 隧道（远程 15000）一直保留着，本服务跑起来链路即恢复。

## 部署机要求

- Windows 10/11，**长期开机、不锁屏、不休眠**（UIA 发送在锁屏下失效）
  - 电源设置：永不睡眠；个性化→锁屏界面→关闭"离开时显示锁屏"
- 微信 4.1.x 桌面版，一个专用微信号登录（即发送者账号）
- Python 3.10+
- 能访问外网（下载 NVDA、连接 frps）

## 步骤 1：安装项目与依赖

把整个 pywechat 项目目录拷贝到部署机（或 git clone 后拷入 `wx_sender_server.py` 等文件），然后：

```bat
cd <项目目录>
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## 步骤 2：安装 NVDA 便携版（激活 UIA 的必需组件）

微信 4.1.12 只在检测到读屏器时才暴露完整 UIA 树，NVDA DLL 注入方案已实测可行
（NVDA 必须在微信启动**之前**运行）。

1. 下载 NVDA 2026.1.1（GitHub release，国内可走代理）：
   `https://github.com/nvaccess/nvda/releases` → `nvda_2026.1.1.exe`
2. 制作便携版到 `D:\VibeCoding\nvda\portable`（与 `start_wx_sender.bat` 中 `NVDA_PATH` 一致）：
   ```bat
   nvda_2026.1.1.exe --create-portable-copy --portable-path=D:\VibeCoding\nvda\portable --minimal
   ```

## 步骤 3：激活流程（每次重启微信前执行一次）

1. 启动 NVDA（静默、无对话框）：`D:\VibeCoding\nvda\portable\nvda.exe --no-speech -m`
   （退出用 `nvda.exe -q`）
2. 关闭微信：`taskkill /F /IM Weixin.exe /T`（连同 `WeChatAppEx.exe`）
3. 启动微信 → 出现登录窗口后**把窗口带到前台**（NVDA 只注入前台焦点窗口）
4. 扫码登录。主窗口创建时已带注入状态 → UIA 完整暴露

验证（可选）：`python verify_uia.py` —— 主窗口 `mmui::MainWindow` 有大量子元素、
Weixin.exe 显示"注入 N DLL" 即成功（若 `主窗口只有 2 个子元素` = 未激活，从第 1 步重来）。

## 步骤 4：填写群名映射

```bat
.venv\Scripts\python list_groups.py        # 导出最近群聊名（会操作微信界面，勿动键鼠）
.venv\Scripts\python list_groups.py --all  # 群不在最近列表时用全量模式
```

首次运行 `wx_sender_server.py` 会生成 `wx_sender_config.json` 模板，把导出的群名填入
targets 对应 wxid 的 `name`（对照 desc 注释填写）。**改配置无需重启服务**（每条消息发送前重新读取）。

## 步骤 5：启动服务并本地验证

```bat
start_wx_sender.bat
```

验证（另开 cmd）：

```bat
curl http://127.0.0.1:15000/health
curl http://127.0.0.1:15000/targets

:: 调试接口直发文件传输助手（零风险，验证 UIA 发送链路）
curl -X POST http://127.0.0.1:15000/send -H "Content-Type: application/json" ^
  -d "{\"name\":\"文件传输助手\",\"content\":\"wx_sender 链路测试\"}"

:: 旧 API 格式（模拟 coinMarker 调用，需 targets 已配置该 wxid）
curl -X POST http://127.0.0.1:15000/api/wxid_u5li17q0pjeh22/send_text -H "Content-Type: application/json" ^
  -d "{\"to_wxid\":\"48123779466@chatroom\",\"content\":\"测试\"}"
```

## 步骤 6：frpc 隧道

编辑 `frpc-wx.toml`：把 `YOUR_FRPS_TOKEN` 替换为真实值（与 coinMarker/frpc.toml 一致），
然后启动 frpc：

```bat
D:\下载\frp_0.64.0_windows_amd64\frpc.exe -c <项目目录>\frpc-wx.toml
```

## 步骤 7：服务器端验证

```bash
wsl ssh root@91.98.134.93 "curl -s http://127.0.0.1:15000/health"
# 期望返回 status:ok
wsl ssh root@91.98.134.93 "tail -f /opt/1panel/tools/supervisord/log/coinMarker.out.log"
# 观察 SendWxMsgHuizai 是否不再报"发送失败"
```

## 步骤 8：接收链路 wx_listener（2026-08-31 上线）

`wx_listener.py` 监听白名单好友私聊并转发 coinMarker（打通命令交互）：

```
好友消息 → 微信独立小窗(最小化) → UIA 轮询 runtime_id(0.5s)
        → 回声过滤(wx_sent_echo.jsonl) → POST :19600/wcf/callback(10002)
        → coinMarker 处理命令 → 回复仍走 wx_sender 发送链路
```

- 配置：`wx_sender_config.json` 的 `listener`（`friends`: wxid→备注名）+ `callback`
  （`url`/`token`，token 即服务器 `PYWX_CALLBACK_TOKEN`）块
- robot_wxid 自动探测（`Tools.get_current_wxid()`），启动/换号重连时上报 10001
- 回声过滤：wx_sender 发送成功后写 `wx_common.log_sent`，listener 60s 内
  同 (wxid, content) 的消息视为自家回声跳过——**不改 wx_sender 记录逻辑会收发死循环**
- 启动：`wscript wx_listener_hidden.vbs`；日志 `wx_listener.log`（2MB 轮转×3）
- 窗口/微信重启自愈：线程内自动重开小窗（指数退避 5→60s），换号自动重发 10001

## 语音强提醒（2026-08-31 上线）

价格/ST 提醒触发后，coinMarker 对 `PYWX_VOICE_ALERT_WXIDS` 白名单用户（当前仅小康）
在文本推送之外**补拨微信语音电话**：

- 端点：`POST /api/{robotWxId}/voice_call`，body `{"to_wxid": "..."}`（Go 侧 `starbot.Client.VoiceCall`）
- 与文本**共用发送队列**串行执行（键鼠互斥）；同目标 `voice_cooldown`（默认 300s）冷却，
  冷却内请求返回 `{"queued":false,"skipped":"cooldown","retry_after":n}`（Go 侧视为成功）
- 按钮定位用 `auto_id='voip_button'`——pyweixin 库 `Call.voice_call` 写死的
  title='语音聊天' 在微信 4.1.2.17 已改文案「语音通话」，故自实现（diag_voice2.py 探明）
- 服务器开关：`.env` 的 `PYWX_VOICE_ALERT_WXIDS`（逗号分隔，空=全关），改后需重启 coinMarker

## 常驻与开机自启（已配置）

用任务计划程序设置开机任务，顺序必须是 **NVDA → 微信(人工扫码) → 服务**：

1. `start_wx_sender.bat` 已处理 NVDA 自动拉起与服务启动
2. 微信需人工扫码登录一次（登录状态一般可保持数天）
3. 已注册计划任务（登录时触发，需提权执行一次 `setup_autostart.ps1`，幂等）：
   - `wx_sender_autostart` → `wx_sender_hidden.vbs`
   - `wx_listener_autostart` → `wx_listener_hidden.vbs`
4. frpc（部署机合一后由本机 `C:\Users\kk\Desktop\frpc\frpc_hidden.vbs` 承载 `wx` 代理）

## 运维说明

| 事项 | 说明 |
|------|------|
| 发送速率 | 单线程串行 + 每条 3-6 秒随机延迟（`send_interval` 可调），高峰会排队 |
| 队列上限 | `queue_max`=200，满则丢弃并记日志（与 Go 端行为一致） |
| 失败冷却 | 连续失败 5 次冷却 60 秒（`fail_threshold`/`fail_cooldown`），多为微信掉线/弹窗遮挡 |
| 日志 | 控制台 + `wx_sender.log`（2MB 轮转×3），含每条消息目标与前 50 字 |
| 监听时延 | listener 轮询 0.5s，消息检测→回调通知服务器 ~1s；回复发送另含 3-6s 防检测延迟 |
| 新增白名单 | 两处同步：config `listener.friends` 加 wxid→备注名 + coinMarker `main.go` switch 加 wxid |
| @所有人 | targets 里 `at_all:true` 的目标（JSSZ 已配）发送时自动 @所有人 |
| 长消息 | 超过 2000 字自动转 txt 文件发送（pyweixin 内置） |
| 机器不可锁屏 | 锁屏/休眠/远程断开都会导致 UIA 发送失败，务必配置电源计划 |

## 已知限制

- UIA 发送期间占用键鼠（pyautogui），部署机不要兼作他用
- 微信大版本升级可能改变控件结构，pyweixin 需跟进适配
- coinMarker 端 `SendWxMsgHuizai` 不检查 HTTP 响应体，本服务返回 404/503 时消息会被静默丢弃（有日志），排查以本服务日志为准

## 备选实现（未部署）

开发机（D:\VibeCoding\pywechat）存在另一套**单进程内嵌**实现（commit e468826，
`WhitelistListener` 类集成进 wx_sender_server.py + UIA_LOCK + TAIL_SCAN burst 吸收 +
自动挂断语音脚本）。生产采用本文档的双进程方案（2026-08-31 E2E 验证）；内嵌版的
burst 吸收/UIA_LOCK/自动挂断可作为后续融合方向，融合时注意两套的回声过滤接口不同
（`log_sent`/`is_recent_sent_echo` vs `record_sent_intent`/`is_recently_sent`）。
