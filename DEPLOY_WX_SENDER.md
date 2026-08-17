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

## 已知限制

- UIA 发送期间占用键鼠（pyautogui），部署机不要兼作他用
- 微信大版本升级可能改变控件结构，pyweixin 需跟进适配
- coinMarker 端 `SendWxMsgHuizai` 不检查 HTTP 响应体，本服务返回 404/503 时消息会被静默丢弃（有日志），排查以本服务日志为准
