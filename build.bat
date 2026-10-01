@echo off
chcp 65001 >nul
title NightReign Overlay Helper Build Script
set "current_dir=%cd%"

:: 检查 uv 是否存在
where uv >nul 2>nul
if %errorlevel% equ 0 goto run_main

:: 安装 uv
echo 未检测到 uv，正在安装...
powershell -ExecutionPolicy Bypass -Command "irm https://gitee.com/wangnov/uv-custom/releases/download/latest/uv-installer-custom.ps1     | iex"

call :refresh_path
:: 验证 uv 是否可用
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo 安装 uv 后仍未找到，请检查安装路径
    pause
    exit /b 1
)
:: ===================================

:run_main
cd /d "%current_dir%"

uv sync
uv run pyinstaller --name "nightreign-overlay-helper" --windowed --onefile --distpath "dist\nightreign-overlay-helper" --icon="assets\icon.ico" --add-data "pyproject.toml;." --add-binary "native\MaaWin32Screencap.dll;native" src\app.py

xcopy /E /I /Y "assets" "dist\nightreign-overlay-helper\assets"
xcopy /E /I /Y "data" "dist\nightreign-overlay-helper\data"
copy "manual.txt" "dist\nightreign-overlay-helper\manual.txt"
copy "config.yaml" "dist\nightreign-overlay-helper\config.yaml"

echo 构建完成，输出目录：dist\nightreign-overlay-helper
pause

exit /b 0

:: 刷新当前命令行窗口的 PATH：刚安装的 uv 写入的是注册表中的用户 PATH，已打开的窗口看不到
:refresh_path
set "USER_PATH="
set "SYSTEM_PATH="
for /f "skip=2 tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USER_PATH=%%B"
for /f "skip=2 tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYSTEM_PATH=%%B"
if defined SYSTEM_PATH if defined USER_PATH call set "PATH=%SYSTEM_PATH%;%USER_PATH%"
set "PATH=%PATH%;%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin"
goto :eof
