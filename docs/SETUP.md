# 安装与首次连接

在自己的电脑上连接自己的 Android 设备；本指南不包含账号迁移或业务自动化部署。

## 要求与支持范围

- Python 3.10+、Git、ADB（Android SDK Platform Tools）。Python 代码只使用标准库，无需 pip 安装。
- 使用共享投屏需要 scrcpy 3.3.1 或更新版本；旧版本可能不支持本项目的启动参数。
- macOS、Linux 使用 POSIX `flock`。Windows 原生 Python 不支持，使用 WSL2。
- Android 设备需允许 USB 调试、截图和输入。原始控制方法曾用于 Android 16 小米平板；不代表所有品牌、系统和 App 已实测兼容。
- 第三方 Agent 需能执行本地命令、读取文件和图片。没有 Agent 也能手工使用 CLI；代码本身不会调用模型。

## macOS

安装 [Homebrew](https://brew.sh/) 后：

```bash
brew install python git scrcpy
brew install --cask android-platform-tools
```

已有工具也可使用，不需要原项目使用的其他桌面应用。依据：[scrcpy 官方 macOS 安装文档](https://github.com/Genymobile/scrcpy/blob/master/doc/macos.md)、[Android 官方 Platform Tools](https://developer.android.com/tools/releases/platform-tools)。

## Linux

在 Debian / Ubuntu 系统安装基础工具：

```bash
sudo apt update
sudo apt install python3 git adb
```

再依照 [scrcpy 官方 Linux 安装指南](https://github.com/Genymobile/scrcpy/blob/master/doc/linux.md) 安装当前版本。部分发行版的软件源版本较旧；不要假定 `apt install scrcpy` 得到的版本支持所有参数。普通 CLI 和截图不依赖 scrcpy。

遇到 USB 权限不足，按 [Android 官方真机设置指南](https://developer.android.com/studio/run/device) 配置 `plugdev` / udev 后重新连接；不要以 root 身份启动整套 Agent。桌面投屏需要可用的图形会话。

## Windows：通过 WSL2（未做本项目真机验收）

1. 按 [Microsoft WSL 安装文档](https://learn.microsoft.com/en-us/windows/wsl/install) 准备 WSL2 Ubuntu。
2. 按 [Microsoft USB 转接文档](https://learn.microsoft.com/en-us/windows/wsl/connect-usb) 安装 `usbipd-win`，由使用者在 PowerShell 中识别自己的设备并完成绑定 / attach。需要管理员权限的步骤由使用者确认，不把所有 USB 设备一并绑定。
3. 在 WSL2 内按 Linux 步骤安装 **Linux 版** Python、ADB、scrcpy，并克隆仓库到 Linux 家目录。不要在 WSL 中使用 Windows 版 `adb.exe` 作为本项目后端，进程锁继承语义未验证。
4. 投屏需要 WSLg 或其他可用 Linux 图形会话。没有图形会话时先验收 CLI、XML 与截图。
5. 每次 USB 断开或电脑重启后，可能需要重新 attach。Windows 与 WSL 不得各运行一个 AI 控制同一设备。

本项目锁只协调同一 Linux / macOS 用户下的进程，不覆盖 Windows 主机上的其他程序。

## 设备端与生成配置

1. 使用自己的设备和可传数据的 USB 线。打开开发者选项、USB 调试；USB 授权由用户在设备上完成。
2. 不要求取消屏幕密码；有密码时在需要唤醒验收前自行解锁。
3. 小米等系统可能另有“USB 调试（安全设置）”控制输入。仅连接成功不代表输入权限完整；按系统提示由设备主人决定是否授权。

```bash
git clone https://github.com/BoyangGuo1789/mi-pad-agent.git
cd mi-pad-agent
python3 scripts/tablet_control.py devices
bash scripts/bootstrap.sh
```

只连接一台且已授权时自动选定。多设备时：

```bash
python3 scripts/tablet_control.py setup --serial YOUR_DEVICE_SERIAL
```

工具不在 PATH 时传入实际可执行路径：

```bash
python3 scripts/tablet_control.py setup --serial YOUR_DEVICE_SERIAL \
  --adb /absolute/path/to/adb --scrcpy /absolute/path/to/scrcpy
```

配置写入 `.mi-pad.local.json`，权限为仅本机用户读写；不覆盖已有配置，不提交 Git。换设备前保留原配置副本，再重新 setup。`MI_PAD_CONFIG` 可指定本地配置文件路径；不可用来改变设备锁目录。

## 验收与开始使用

```bash
python3 scripts/tablet_control.py doctor
python3 examples/smoke_test.py
python3 scripts/tablet_control.py status
python3 scripts/tablet_control.py observe
```

`doctor` 检查工具可执行文件和设备连接；它不证明已进入桌面或 App 已登录。`smoke_test` 将设备返回桌面并采集证据，实际通过后再报告基础控制成功。投屏能打开只证明镜像连接，用户点击和 AI 业务流程仍需按任务核验。

## 排查

| 输出 / 现象 | 处理 |
|---|---|
| `CONFIG_ERROR` | 先 setup；确认 Python 和工具路径、平台及配置 JSON |
| `unauthorized` | 在自己设备上确认 USB 授权弹窗，再运行 devices |
| `offline` / `missing` | 检查 USB 数据线、端口、WSL attach 与设备状态；不反复提交业务动作 |
| `LOCK_BUSY` / `COMMAND_BUSY` | 有其他 AI 操作；等待或检查其任务，不删锁或杀进程 |
| `LEASE_EXPIRED` | 重新领锁并读取新页面；旧坐标与 token 均不可继续使用 |
| `KEYGUARD_BLOCKED` / `KEYGUARD_UNKNOWN` | 用户自行解锁；不同系统输出不兼容时保留现场，报告失败 |
| `HOME_UNCONFIRMED` | 返回桌面核验未通过，不假定已可操作 App |
| `uiautomator` 超时 / 空 XML | 使用持锁截图辅助；屏幕保护或无可访问节点时交由用户判断 |
| scrcpy 参数不支持 | 更新官方版本，检查 `scrcpy --version`；不要去掉设备选择限制 |
| 中文输入失败 | 用户在共享投屏输入，随后读取界面核对文本 |

更新日期：2026-10-28。外部依赖安装方式以链接中的官方文档为准。
