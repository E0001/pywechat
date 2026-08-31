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

## 步骤 2：~~安装 NVDA~~（已废弃，2026-09-01 退役）

**NVDA 与微信 UIA 树无关，不要再装/启动它。** 2026-08-17 部署时的"读屏器
必需"结论是误诊：所有启动脚本从第一天起用的 `--no-speech` 参数在 NVDA
2026.1.1 里不存在（正确写法 `--disable-speech`），带它启动只会弹错误框、
core 永不初始化——**即 NVDA 14 天来从未自动启动成功过，链路照样天天正常**，
与微信树死活无关。保留的教训：NVDA 错误参数弹的对话框曾干扰排查，装了
反而添乱。`C:\Users\kk\nvda\` 目录留着不碍事，所有脚本中的 NVDA 步骤已删除。

## ⚠️ 微信 UIA 树加载时序（2026-09-01 定案的真根因，最重要的一节）

**微信进程启动、登录窗口→主窗口的 UIA 树初始化期间，若系统里有任何 UIA
客户端进程（wx_sender/wx_listener 的 COM 连接或重试循环、任何 pywinauto
探针）向它发起连接，微信会拒绝加载完整 UIA 树**——此后主窗口空壳
（`mmui::MainWindow` 子元素=2）、小窗不可读，**且无论再怎么重启微信都救不回**
（毒源客户端进程还活着），表现为"微信 UIA 永久死亡"。

2026-09-01 事故复盘：链路 14 天正常（从未在服务运行时杀过微信）→ 21:19
首次杀微信做实验，wx_sender/wx_listener 的僵尸 COM 连接从此毒死每一个新
微信进程 → 通宵排查 NVDA 参数/扫码登录/console 会话/系统重启全部无效
（每轮重启微信时毒源都在场）→ 最终杀光全部 python 客户端、零客户端环境
重启微信，树立即恢复。

**铁律（违反=复现事故）：**

1. **永远不要在 wx_sender/wx_listener 运行时直接杀微信重启。** 顺序必须是：
   停服务（杀 python）→ 杀微信 → 启动微信 → 等登录+树活（`wx_login_click.py`
   exit=0）→ 再起服务。桌面一键入口 `start_all.ps1` 的 exit=2 分支已内置此顺序。
2. **服务进程自带闸门**：`wx_common.wait_wechat_ready()`（纯 Win32
   EnumWindows 探测"标题=微信且宽≥500 的可见窗口"=主窗口出现，不碰 COM），
   listener/sender 启动时先等微信就绪+15s 稳定期，再初始化自己的 UIA——
   开机自启时无论谁先启动都不会污染微信。改这两个服务时**必须保留闸门**。
3. **微信的 Win32 类名是 `Qt51514QWindowIcon`**（`mmui::*` 只是 UIA 层名字，
   `FindWindowW` 按类名找不到微信，必须按 标题+宽度+进程名 判定）。
4. 树死诊断口诀：**先问"微信启动时谁在场"**——杀光全部 python（含探针/
   watcher）再重启微信，活了=客户端污染；还死才考虑别的。NVDA/会话类型/
   登录路径/系统重启都与树死活无关（均已实验排除）。
5. 注意：**主窗口树空心但小窗树正常（能读到 ListItem）时链路功能是活的**——
   listener 只依赖小窗。判断链路死活看 `mmui::ChatSingleWindow` 能否读到
   ListItem，别只盯主窗口 children 数。

## 步骤 3：重启微信的正确流程（替代旧的"NVDA 激活流程"）

1. 停服务：杀掉所有 `wx_sender_server|wx_listener` 的 python 进程
   （以及任何还开着的 pywinauto 探针脚本）
2. 关微信：`taskkill /F /IM Weixin.exe /T`
3. 启动微信：`"C:\Program Files\Tencent\Weixin\Weixin.exe" -autorun`
4. 登录：自动登录生效时跑 `python wx_login_click.py`（等登录窗、点
   「进入微信」、验证主窗树，exit 0=好）；没开自动登录则手机扫码
5. 树活后再起服务：`wscript wx_sender_hidden.vbs` → 5s →
   `wscript wx_listener_hidden.vbs`

验证：`mmui::ChatSingleWindow` 窗口能读到 ListItem = 收发链路正常
（主窗口 `mmui::MainWindow` 子元素=2 且小窗正常**不算事故**，见上文第 5 条）。

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
- **拨号是两步操作**（2026-08-31 补，diag_voice8 实测）：点 `voip_button` 只会弹出
  「语音通话/视频通话」飞出菜单，必须再点菜单里的「语音通话」MenuItem 才真正发起
  （只点按钮=假拨号，日志会显示成功但对方收不到）。以 `mmui::VOIPWindow` 出现为
  成功判据，未出现视为失败、不进冷却。拨号优先按句柄注册表复用 listener 常驻的
  独立小窗（免搜索导航，1s 内拨出；失效则按当前可寻址名重开并回写句柄）。
- ⚠️ 键鼠自动化（含拨号和文本发送）依赖**交互式桌面**：RDP 断开/最小化会话锁屏时
  `SetCursorPos` 报 "no active desktop"，全部发送失败。**已由 rdp_keepalive 根治**（见下节）。
- 发送任务失败自动重试 3 次（间隔 60s，`_requeue_later`），桌面短暂抖动/UIA 偶发冲突
  不再永久丢消息（2026-08-31 21:23 事故教训：3 条回复一次性丢弃）
- 服务器开关：`.env` 的 `PYWX_VOICE_ALERT_WXIDS`（逗号分隔，空=全关），改后需重启 coinMarker

## 改备注/关小窗自愈（2026-08-31 上线）

微信搜索框**搜不到内部 wxid**（逐字匹配失败），开窗/拨号只能按显示名搜索——
用户一改备注，配置里的旧名字就失联。三层防线让改备注、关小窗都不需要改配置：

| 层 | 机制 | 失效场景 |
|----|------|---------|
| 1. 追踪名 | listener 每 30s 读小窗头部 `current_chat_name_label`，实时落盘当前备注名 | 窗口关闭期间被改名 |
| 2. 配置备注名 | `listener.friends` / `targets` 里的名字 | 名字被改后 |
| 3. 微信号两段式 | 按微信号搜索（**永不变化且可搜**），读结果条目的显示名（=当前备注名）落盘，再用它开窗 | 只有删好友才失效 |

- 微信号在 config 顶层 `aliases` 块维护：`{"wxid_xerhivsxr9u622": "crypto_kang", "litiantianss": "litiantianss"}`
- ⚠️ pyweixin 原生搜索要求「结果条目显示名 == 搜索词」，按微信号直搜会误报
  NoSuchFriendError（微信本身搜得到）——所以微信号必须走 wx_listener
  `_discover_name_by_alias` 的两段式，不能直接传给 `open_seperate_dialog_window`
- 落盘注册表：`wx_contact_names.json`（wxid→当前备注名）、`wx_chat_windows.json`
  （wxid→小窗句柄，拨号复用）。均为运行时缓存，删了会自动重建
- 发送/拨号侧取「追踪名 → 配置名」，配合 3×60s 重试等 listener 自愈；
  验证工具：`diag_alias_discovery.py`（确认 alias 能发现当前显示名）

## rdp_keepalive：无人值守运行（2026-08-31 上线）

本机经 RDP 运维，但 **RDP 客户端最小化或断开后输入桌面失效**，键鼠自动化全部失败
（会话在 qwinsta 里仍显示"运行中"，极具迷惑性）。`rdp_keepalive.ps1` + 计划任务
`rdp_keepalive`（登录触发、最高权限、无时限）：

- 每 15s 用 `SetCursorPos` 自检桌面；不可交互且会话在 rdp-tcp 上时执行
  `tscon <id> /dest:console` 把会话切到物理控制台，恢复交互
- 已验证：**RDP 完全断开时文本/语音发送照常工作**
- 用户重连 RDP 会话自动回到 rdp-tcp；再次最小化/断开后 15s 内被切回 console
- 局限：物理控制台被锁屏（Win+L）无法自动恢复——**别在这台机器上按 Win+L**，
  日志会以 10 分钟一次的频率提示
- 日志：`rdp_keepalive.log`（gitignore）

## 常驻与开机自启（2026-09-01 时序安全版）

开机链路由 `wx_boot_autostart` 计划任务（登录触发）编排，`boot_autostart.ps1`：

**微信（自身 HKCU Run 自启，"Weixin -autorun"）→ boot 链等它出现(45s,兜底
拉起) → frpc → wx_login_click.py（登录点击+树验证）→ 树活后才拉
wx_sender → wx_listener**

1. **前提：Windows 自动登录**——本机账户无密码，开机直入桌面。若将来加了
   密码需 `netplwiz` 取消"必须输入密码"，否则重启停在登录界面，所有登录
   触发任务（含 rdp_keepalive）都不会跑
2. **微信自身注册表 Run 自启项（HKCU ...Run 的 `Weixin` = `"...Weixin.exe"
   -autorun`）必须保留**——它是微信启动的正主（2026-08-31 曾误删过，
   09-01 恢复）
3. NVDA 已退役（见步骤 2）；独立的服务自启任务 `wx_sender_autostart`/
   `wx_listener_autostart` 已废弃，改由 boot 链在树活后统一拉起（服务自身
   另有 `wait_wechat_ready` 闸门双保险，旧任务残留也不会出事；提权跑一次
   `setup_autostart.ps1` 可清理）
4. 启动文件夹已清理：删 `wx_sender.lnk`（重复双启动）、`wx_forwarder.lnk`
   （chatlog 实验链，复活会与 wx_listener **双发消息**；脚本本体保留）
5. 日志：`boot_autostart.log`、手动一键入口 `start_all.log`（gitignore）

重启后验证：
- `type boot_autostart.log` —— login exit=0 后 sender/listener 两行 launched
- `mmui::ChatSingleWindow` 能读到 ListItem = 收发链路正常
- 服务器端 supervisor 各程序均 `autostart=true`，服务器重启自动恢复
  价格监控，无需人工干预

物理断电后自动开机需 BIOS 设 AC Power Loss → Power On（主板选项，远程改不了）。

## 运维说明

| 事项 | 说明 |
|------|------|
| 发送速率 | 单线程串行 + 每条 3-6 秒随机延迟（`send_interval` 可调），高峰会排队 |
| 队列上限 | `queue_max`=200，满则丢弃并记日志（与 Go 端行为一致） |
| 失败冷却 | 连续失败 5 次冷却 60 秒（`fail_threshold`/`fail_cooldown`），多为微信掉线/弹窗遮挡 |
| 日志 | 控制台 + `wx_sender.log`（2MB 轮转×3），含每条消息目标与前 50 字 |
| 监听时延 | listener 轮询 0.5s，消息检测→回调通知服务器 ~1s；回复发送另含 3-6s 防检测延迟 |
| 新增白名单 | 三处同步：config `listener.friends` 加 wxid→备注名、`aliases` 加 wxid→微信号（自愈兜底）+ coinMarker `main.go` switch 加 wxid |
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
