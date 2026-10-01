# native/

预编译的原生二进制。程序以管理员身份运行时会加载其中的 DLL，所以更换它时必须在这里留下记录。

## MaaWin32Screencap.dll

| 项目 | 内容 |
| --- | --- |
| 作用 | Windows 窗口截图（`src/screencap/maa_win32_screencap.py` 通过 ctypes 调用 `MaaWSManager*` / `MaaWSCustomScreencap*` 导出函数） |
| 架构 | PE32+ x86-64 DLL |
| 大小 | 773,632 字节 |
| SHA256 | `053e05efe3c0d243848d23511cd2ce2ec6bb4f47724ca7c72e3b9eeff37cffb3` |
| 引入提交 | `3c427af`（2026-08-29，`feat(screencap): 将截图实现从 mss 迁移至 MaaWin32Screencap`） |
| 上游仓库 / 版本 / 许可证 | **待维护者补充**：二进制本身不含版本号，只有仓库维护者知道它是从哪里取得的 |

`SHA256SUMS` 记录了本目录下所有二进制的哈希，CI 和发布流程会用 `scripts/verify_native.py` 校验。

## 更换 DLL 的步骤

1. 替换 `MaaWin32Screencap.dll`。
2. 运行 `python scripts/verify_native.py --update` 重新生成 `SHA256SUMS`。
3. 更新上表中的大小、SHA256、来源和版本。
4. 一并提交，评审时对照这三处是否一致。

## 加载路径

程序只会从以下位置加载该 DLL（见 `src/screencap/maa_win32_screencap.py`）：

1. 打包后的 PyInstaller 解包目录下的 `native/`（`--add-binary` 放入，`sys._MEIPASS/native`）；
2. 源码运行时仓库内的 `native/`。

指定了 DLL 目录后不会再回落到环境变量、相对路径或 `PATH`。
