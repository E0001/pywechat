# wx_sender 个人微信收发服务 — 部署指南

coinMarker 的**个人微信双向通道**：快讯/提醒推送到群（发送方向）+ 白名单好友私聊
命令接收（`btc<80000` 价格提醒等，收方向，替代已停用的 StarBot 回调）。

## 架构

```
远程服务器 91.98.134.93 (coinMarker)
  ├─ 发送: starbot/client.go → POST http://127.0.0.1:15000/api/{wxid}/send_text
  │    ↓ frps (端口 17777) ↓ frpc 隧道 "wx" (frpc-wx.toml, 本地15000 → 远程15000)
  └─ 接收: :19600/wcf/callback ← wx_listener.py (StarBot 兼容 event="10002")
       ↑ 公网直连 POST（token 鉴权, 服务器 ufw 放行 19600）
部署机 (Windows, 常驻)
  ├─ NVDA 便携版 (静默运行, 激活微信 UIA)
  ├─ 微信 4.1.x (保持登录)
  ├─ wx_sender_server.py (标准库 HTTP, :15000)
  │    ├─ SendWorker: 单线程队列 → pyweixin 发送（UIA_LOCK 互斥）
  │    └─ listener.enabled 时: WhitelistListener 白名单窗口轮询
  │         → CallbackWorker → POST coinMarker 回调
  └─ start_wx_sender.bat (一键启动)
```

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

### ⚠️ 先让家庭端让位（切换前置，必做）

frps 远程端口 15000 同一时刻只能被一个 frpc 隧道绑定。家庭端（111.85.70.232）
跑着的旧 frpc（coinMarker 仓库 frpc.toml 副本）有一个同名 `wx` 代理一直占着这个坑，
本机的 frpc 起来也注册不上。操作（在**家庭电脑**上）：

1. 找到家庭端 frpc 使用的配置文件（coinMarker 仓库 `frpc.toml` 的副本）
2. 注释或删除 `wx` 代理块（`[[proxies]]` name="wx" 到 `remotePort = 15000` 共 6 行；
   最新版 frpc.toml 已删掉该块并留了说明注释，同步最新文件即可）
3. 重启家庭端 frpc（按其实际运行方式：计划任务/服务/手动进程）

验证（任何机器，走 WSL）——坑是否已空出：

```bash
wsl ssh root@91.98.134.93 "curl -s -m 3 http://127.0.0.1:15000/health"
# 连接被拒/无响应 = 已让位 ✅（部署机 frpc 起来后应返回 wx_sender 的 JSON）
# 仍返回内容 = 家庭端还没停干净 ❌
```

完整切换顺序（服务器 PYWX_* 配置 → 部署 coinMarker → 端到端验证 → 回滚预案）
见 coinMarker 仓库 **`docs/pywechat-switch.md`**。

## 步骤 7：开启收消息监听（可选，替代 StarBot 回调通道）

白名单好友私聊发命令（`btc<80000` / `st<doge` / `列表` 等），coinMarker 处理后
经发送通道回复。配置 `wx_sender_config.json`：

```jsonc
"listener": {
  "enabled": true,              // 填好 friends 备注名后再开
  "poll_interval": 1.5,
  "friends": {                  // coinMarker main.go 白名单对应的 3 人
    "wxid_xerhivsxr9u622": "<小康的备注名，必须完整精确>",
    "litiantianss": "<甜小米的备注名>",
    "wxid_ahdz8pwq9dk312": "<Michelle的备注名>"
  }
},
"callback": {
  "url": "http://91.98.134.93:19600/wcf/callback",
  "token": "<与服务器 PYWX_CALLBACK_TOKEN 一致>",
  "robot_wxid": "",             // 留空自动探测（非 wxid_ 前缀账号须手填）
  "timeout": 5, "max_retries": 3
}
```

要点：

1. **备注名必须完整精确**（pyweixin 按显示名搜索定位独立聊天窗口），
   targets 里同名 wxid 也要填同样的 name（回复走 targets 映射）
2. 服务启动后会为每个白名单好友打开**独立聊天窗口并最小化**——
   不要人工关闭，被关后 60s 自动重开
3. 服务器端需配 `PYWX_CALLBACK_TOKEN`（同值）并 `ufw allow 19600/tcp`
4. 自回环防护：本服务发出的回复不会被当作新消息转回（发送前登记 + runtime_id 增量）

验证：白名单手机给机器人发 `帮助`，应收到命令说明；
`curl http://127.0.0.1:15000/health` 的 `listener_status`/`callback_status` 可观测状态。

## 步骤 8：服务器端验证

```bash
wsl ssh root@91.98.134.93 "curl -s http://127.0.0.1:15000/health"
# 期望返回 status:ok（listener 开启时含 listener_status/callback_status）
wsl ssh root@91.98.134.93 "curl -s http://127.0.0.1:19600/wcf/health"
# 期望 {"status":"ok","sessions":1}（pywechat 登录事件注册后）
wsl ssh root@91.98.134.93 "tail -f /opt/1panel/tools/supervisord/log/coinMarker.out.log"
# 观察发送/回调是否正常
```

## 常驻与开机自启（建议）

用任务计划程序设置开机任务，顺序必须是 **NVDA → 微信(人工扫码) → 服务**：

1. `start_wx_sender.bat` 已处理 NVDA 自动拉起与服务启动
2. 微信需人工扫码登录一次（登录状态一般可保持数天）
3. frpc 可加一条计划任务：`frpc.exe -c <项目目录>\frpc-wx.toml`

## 运维说明

| 事项 | 说明 |
|------|------|
| 发送速率 | 单线程串行 + 每条 3-6 秒随机延迟（`send_interval` 可调），高峰会排队 |
| 队列上限 | `queue_max`=200，满则丢弃并记日志（与 Go 端行为一致） |
| 失败冷却 | 连续失败 5 次冷却 60 秒（`fail_threshold`/`fail_cooldown`），多为微信掉线/弹窗遮挡 |
| 日志 | 控制台 + `wx_sender.log`（2MB 轮转×3），含每条消息目标与前 50 字 |
| @所有人 | targets 里 `at_all:true` 的目标（JSSZ 已配）发送时自动 @所有人 |
| 长消息 | 超过 2000 字自动转 txt 文件发送（pyweixin 内置） |
| 机器不可锁屏 | 锁屏/休眠/远程断开都会导致 UIA 发送失败，务必配置电源计划 |
| 收发互斥 | 发送与监听轮询共享 UIA_LOCK（微信 UIA 单线程），不会互相干扰 |
| 监听窗口 | 白名单好友的独立聊天窗口被关后 60s 自动重开；`/health` 的 `listener_status` 可查 |
| 回调重试 | 连接错误/5xx 退避 2/4/8s 重试 3 次，仍失败丢弃（coinMarker 侧命令幂等安全） |
| robot_wxid | 配置留空则从微信数据目录探测；非 `wxid_` 前缀账号探测不到，须手填 |

## 已知限制

- UIA 发送期间占用键鼠（pyautogui），部署机不要兼作他用
- 微信大版本升级可能改变控件结构，pyweixin 需跟进适配
- coinMarker 端 `SendWxMsgHuizai` 不检查 HTTP 响应体，本服务返回 404/503 时消息会被静默丢弃（有日志），排查以本服务日志为准
