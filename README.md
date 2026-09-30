# Nightreign Overlay Helper

[中文README](#黑夜君临悬浮助手)

Nightreign Overlay Helper is a utility program developed with PyQt6, designed to display various useful information and features while playing the game, **currently supporting only the Chinese language**.

## Features

- Displays countdowns for night rain circle shrinking and fast damage of night rain, triggered by hotkeys or automatic detection.
- Map recognition and floating map information. The map seed (pattern) is recognized automatically when the full map is opened, and re-recognized automatically at the start of each expedition (Day 1) or when the last result looks unreliable.
- Great Hollow crystal layout: from Day 2 the game marks crystals on the map; the helper recognizes these markers each time the map is opened and automatically shows the matching crystal layout (or the remaining candidate layouts).
- Displays health percentage markers corresponding to "trigger when health is low" and "trigger when health is full" entries.
- Displays countdowns for art buffs of certain characters.

## Build Instructions

#### Prerequisites
- Windows 7, 8, 10, or 11
- Python 3.13

#### Steps

1. Clone the repository and navigate to the project directory.

2. Build the executable using build script:

    ```bash
    .\build.bat
    ```

    You can find the built executable in the `dist/nightreign-overlay-helper` directory.


## Usage
Double-click `nightreign-overlay-helper.exe` to run the program. Right-click the overlay window or the taskbar icon to open the menu and access the settings window. Refer to the help in the settings UI for configuration guidance.

To run from source without building, double-click `start.bat` in the repository root. It requests administrator privileges, installs dependencies on first run and starts the app without a console window.

## Safety
The program recognizes game information by capturing screenshots of the game screen, without modifying game data or reading/writing to game memory.

## Acknowledgements

- All image resources used in this program are copyrighted by their respective owners.
- Thanks to [Fuwish](https://github.com/Fuwishx) for map data support.
- Thanks to [雀煊](https://space.bilibili.com/391379672) for sharing the Great Hollow crystal layout.

---

# 黑夜君临悬浮助手

[English README](#Nightreign-Overlay-Helper)

基于PyQt6开发的用于在游戏中显示各种实用信息和功能的辅助程序，目前界面仅支持中文语言。

## 功能

- 显示缩圈和雨中冒险倒计时，支持快捷键触发或自动检测。
- 地图识别与地图信息悬浮。打开完整地图时自动识别地图种子，每局开始（DAY I）或上次识别结果不可靠时会自动重新识别。
- 大空洞水晶布局：默认显示所有水晶点位，可用快捷键切换具体布局。设置中可开启实验性的水晶布局自动识别（目前容易误识别，默认关闭）。
- 显示“血量较低触发”与“满血时触发”的词条对应百分比血量位置标记。
- 显示部分角色的绝招buff倒计时。

## 构建

#### 环境要求

- Windows 7、8、10 或 11
- Python 3.13

#### 构建步骤

1. 克隆代码库并进入项目目录。

2. 使用构建脚本生成可执行文件：

    ```bash
    .\build.bat
    ```

    构建完成的可执行文件位于 `dist/nightreign-overlay-helper` 目录下。


## 使用方法

双击 nightreign-overlay-helper.exe 运行程序，直接右键悬浮窗或右键任务栏图标打开菜单打开设置窗口，参考设置界面中的帮助进行配置。

不想打包也可以直接双击仓库根目录的 `start.bat` 从源码运行：它会自动申请管理员权限，首次运行自动安装依赖，启动后不保留命令行窗口。

## 安全性

本程序的游戏信息识别通过截屏游戏画面实现，不涉及对游戏数据的修改或对游戏内存的读写。

## 声明

- 本程序使用的图片资源所有版权归其合法所有者所有。
- 感谢来自 [Fuwish](https://github.com/Fuwishx) 的地图解包数据支持。
- 感谢来自 [雀煊](https://space.bilibili.com/391379672) 的大空洞水晶布局分享。
