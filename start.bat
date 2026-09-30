@echo off
chcp 65001 >nul
title NightReign Overlay Helper
cd /d "%~dp0"

:: 不是管理员就自动请求提权（弹出 UAC 点“是”即可）
net session >nul 2>nul
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: 首次运行时安装依赖
if not exist ".venv\Scripts\pythonw.exe" (
    where uv >nul 2>nul
    if errorlevel 1 (
        echo 未检测到 uv，请先双击运行一次 build.bat 安装环境。
        pause
        exit /b 1
    )
    echo 正在安装依赖，首次运行需要一点时间...
    uv sync
    if errorlevel 1 (
        echo 依赖安装失败，请把上面的报错发给开发者。
        pause
        exit /b 1
    )
)

:: 用 pythonw 启动，不保留黑色命令行窗口
start "" ".venv\Scripts\pythonw.exe" -m src.app
