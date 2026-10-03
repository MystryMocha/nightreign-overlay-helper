# Nightreign Overlay Helper

[中文README](#黑夜君临悬浮助手)

Nightreign Overlay Helper is a utility program developed with PyQt6, designed to display various useful information and features while playing the game, **currently supporting only the Chinese language**.

## Features

- Displays countdowns for night rain circle shrinking and fast damage of night rain, triggered by hotkeys or automatic detection.
- Map recognition and floating map information. The map seed (pattern) is recognized automatically when the full map is opened, and re-recognized automatically at the start of each expedition (Day 1) or when the last result looks unreliable.
- Great Hollow crystal layout: from Day 2 the game marks crystals on the map; the helper recognizes these markers each time the map is opened and automatically shows the matching crystal layout (or the remaining candidate layouts).
- Displays health percentage markers corresponding to "trigger when health is low" and "trigger when health is full" entries.
- Displays countdowns for art buffs of certain characters.
- Weapon info: recognizes the weapon name and affixes on the in-game weapon panel (OCR on a region you select) and shows the weapon's base attribute scaling and the concrete values of its affixes right behind each affix. Values come from unpacked game data; affixes without data in the dataset are marked as "no data".

## Build Instructions

#### Prerequisites
- Windows 10 or 11 (required by Python 3.13 and Qt 6)
- Python 3.13

#### Steps

1. Clone the repository and navigate to the project directory.

2. Build the executable using build script:

    ```bash
    .\build.bat
    ```

    You can find the built executable in the `dist/nightreign-overlay-helper` directory.

Run the tests with `uv run pytest tests` (the weapon detector tests run the bundled OCR models, so they take a few seconds).


## Development

```bash
uv sync --locked           # installs runtime, dev and build (PyInstaller) dependencies from uv.lock (Windows)
uv run ruff check src scripts tests
uv run pytest
uv run python scripts/verify_native.py   # checks native/*.dll against native/SHA256SUMS
```

`uv.lock` is committed and CI installs with `--locked`: after changing dependencies in `pyproject.toml`, run `uv lock` and commit the result. When replacing the prebuilt DLL in `native/`, follow [native/README.md](native/README.md).

## Usage
Double-click `nightreign-overlay-helper.exe` to run the program. Right-click the overlay window or the taskbar icon to open the menu and access the settings window. Refer to the help in the settings UI for configuration guidance.

To run from source without building, double-click `start.bat` in the repository root. It requests administrator privileges, installs dependencies on first run and starts the app without a console window.

## Safety
The program recognizes game information by capturing screenshots of the game screen, without modifying game data or reading/writing to game memory.

## Acknowledgements

- All image resources used in this program are copyrighted by their respective owners.
- The bundled font Source Han Sans SC is © Adobe and licensed under the SIL Open Font License 1.1; see `data/fonts/OFL.txt`.
- Thanks to [Fuwish](https://github.com/Fuwishx) for map data support.
- Thanks to [雀煊](https://space.bilibili.com/391379672) for sharing the Great Hollow crystal layout.
- Weapon attribute scaling and affix values are derived from the unpacked data organized by [sganggs/nightreign-relic-checker](https://github.com/sganggs/nightreign-relic-checker) (GPL-3.0); the game data itself is copyrighted by FromSoftware / Bandai Namco. `data/weapons.json` can be regenerated with `scripts/build_weapon_data.py`.
- Text recognition uses [RapidOCR](https://github.com/RapidAI/RapidOCR) (Apache-2.0).

---

# 黑夜君临悬浮助手

[English README](#Nightreign-Overlay-Helper)

基于PyQt6开发的用于在游戏中显示各种实用信息和功能的辅助程序，目前界面仅支持中文语言。

## 功能

- 显示缩圈和雨中冒险倒计时，支持快捷键触发或自动检测。
- 地图识别与地图信息悬浮。打开完整地图时自动识别地图种子，每局开始（DAY I）或上次识别结果不可靠时会自动重新识别。
- 大空洞水晶布局：破除水晶后游戏会在地图上显示灰色水晶图标，每次打开地图时自动识别这些图标，并切换到包含所有已破除水晶的布局（无法唯一确定时显示所有候选布局的合并点位），也可用快捷键手动切换。
- 显示“血量较低触发”与“满血时触发”的词条对应百分比血量位置标记。
- 显示部分角色的绝招buff倒计时。
- 武器信息：框选游戏里的武器信息面板，通过截屏文字识别（OCR）读取武器名、词条名、战技名和法术名，在对应文字的后面（或下方）显示武器的基础属性补正、词条的具体加成数值，以及战技和法术的伤害摘要。数值来自游戏参数解包数据，数据里没有数值的词条、没有伤害的战技和法术会标注“暂无数值数据”。

## 构建

#### 环境要求

- Windows 10 或 11（Python 3.13 与 Qt 6 的要求）
- Python 3.13

#### 构建步骤

1. 克隆代码库并进入项目目录。

2. 使用构建脚本生成可执行文件：

    ```bash
    .\build.bat
    ```

    构建完成的可执行文件位于 `dist/nightreign-overlay-helper` 目录下。

运行测试：`uv run pytest tests`（武器信息的检测测试会实际运行内置的 OCR 模型，需要几秒钟）。


## 开发

```bash
uv sync --locked           # 按 uv.lock 安装运行、开发和打包（PyInstaller）依赖（Windows）
uv run ruff check src scripts tests
uv run pytest
uv run python scripts/verify_native.py   # 校验 native/*.dll 与 native/SHA256SUMS 是否一致
```

`uv.lock` 已提交，CI 使用 `--locked` 安装：修改 `pyproject.toml` 里的依赖后请运行 `uv lock` 并一并提交。更换 `native/` 下的预编译 DLL 请按 [native/README.md](native/README.md) 操作。

## 使用方法

双击 nightreign-overlay-helper.exe 运行程序，直接右键悬浮窗或右键任务栏图标打开菜单打开设置窗口，参考设置界面中的帮助进行配置。

不想打包也可以直接双击仓库根目录的 `start.bat` 从源码运行：它会自动申请管理员权限，首次运行自动安装依赖，启动后不保留命令行窗口。

#### 武器信息

在设置的“武器信息”页勾选启用，设置“框选武器信息区域”的快捷键；在游戏里打开武器信息面板（要同时能看到武器名、词条、战技和法术文字）后按下快捷键，框选整块面板的文字区域即可。之后每次出现该面板，属性补正和词条数值会自动显示在对应文字旁边（可选择显示在词条下方或右侧，并调整字号）。

- 词条档位在游戏里看不出来时，会同时列出各档数值，如 `魔力伤害 +6%/+9%/+12%（档位1/2/3）`；识别到“＋2”这样的档位标记时只显示对应档。
- 属性补正是武器未强化时的基础值，评级参照艾尔登法环的常用划分（S≥175 / A≥140 / B≥90 / C≥60 / D≥25 / E），与游戏界面显示的字母可能因武器强化等级不同而有出入。
- 带“（条件触发）”的词条，数值只在满足条件时生效。
- 战技写出各段攻击的倍率与固定伤害，如 `圣 180+基础 / 65%`、`240%`，“+基础”表示再加上武器自身的攻击力，`×2` 表示连续两段相同；法术写出专注消耗和固定伤害，如 `FP 7 · 魔力 152`。蓄力版、专注不足的弱化版和不造成伤害的段不计入。
- 战技和法术可能同名（如“辉石魔砾”）：文字带“战技：”“魔法：”前缀时按前缀，否则按上方的武器是不是法杖 / 圣印记来选；找不到上方的武器时两个摘要都显示。同一个战技在不同武器上的动作不同时，按上方的武器选择。
- 目前数据里只有伤害、异常累积、消耗等部分词条有具体数值，血量/专注值上限、减伤、回复等词条会显示“暂无数值数据”。
- 识别在后台线程进行，约需 1 秒，画面变化后会先隐藏旧数值再显示新结果。相关参数（识别间隔、CPU 线程数等）见 `config.yaml` 中的 `weapon_*` 项。

## 安全性

本程序的游戏信息识别通过截屏游戏画面实现，不涉及对游戏数据的修改或对游戏内存的读写。

## 声明

- 本程序使用的图片资源所有版权归其合法所有者所有。
- 本程序随附的字体 Source Han Sans SC（思源黑体）© Adobe，依据 SIL Open Font License 1.1 授权，许可全文见 `data/fonts/OFL.txt`。
- 感谢来自 [Fuwish](https://github.com/Fuwishx) 的地图解包数据支持。
- 感谢来自 [雀煊](https://space.bilibili.com/391379672) 的大空洞水晶布局分享。
- 武器属性补正与词条数值整理自 [sganggs/nightreign-relic-checker](https://github.com/sganggs/nightreign-relic-checker)（GPL-3.0）提供的解包数据，游戏数据版权归 FromSoftware / Bandai Namco 所有。`data/weapons.json` 可用 `scripts/build_weapon_data.py` 重新生成。
- 文字识别使用 [RapidOCR](https://github.com/RapidAI/RapidOCR)（Apache-2.0）。
