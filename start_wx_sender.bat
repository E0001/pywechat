@echo off
chcp 65001 >nul
rem ============================================================
rem wx_sender 快讯发送服务一键启动
rem 首次部署请先阅读 DEPLOY_WX_SENDER.md
rem 前置: 微信已按 NVDA 激活流程重启并登录(见文档步骤3)
rem ============================================================

rem NVDA 便携版路径(按部署机实际路径修改)
set "NVDA_PATH=D:\VibeCoding\nvda\portable\nvda.exe"
rem Python: 优先用项目 venv, 不存在则用系统 python
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem ---- 1. NVDA 未运行则静默启动(NVDA 必须先于微信运行, 否则下次重启微信后 UIA 失活) ----
tasklist /FI "IMAGENAME eq nvda.exe" 2>nul | find /i "nvda.exe" >nul
if errorlevel 1 (
    if exist "%NVDA_PATH%" (
        echo [1/2] 启动 NVDA(静默)...
        start "" "%NVDA_PATH%" --no-speech -m
        timeout /t 3 /nobreak >nul
    ) else (
        echo [警告] NVDA 未运行且未找到 %NVDA_PATH%, 若微信是 NVDA 启动前打开的, 发送会失败
    )
) else (
    echo [1/2] NVDA 已在运行
)

rem ---- 2. 启动发送服务 ----
echo [2/2] 启动 wx_sender 服务(监听 127.0.0.1:15000)...
"%PY%" "%~dp0wx_sender_server.py"
pause
