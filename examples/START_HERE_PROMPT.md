# 给另一台电脑上的 AI Agent

复制以下内容，附上仓库链接，用于首次接入自己的设备。

```text
请帮我在这台电脑复刻 Android 设备的基础操作能力。
仓库：https://github.com/BoyangGuo1789/mi-pad-agent

1. 克隆为独立目录，先阅读 README.md、AGENTS.md、docs/SETUP.md。
2. 检查系统、Python 3.10+、Git、ADB、scrcpy；依赖只从官方或系统包管理器获取。
   Windows 请走 WSL2，解释 USB 转接步骤，由我完成系统权限确认。
3. 我会连接自己的 Android 设备，在设备上开启并授权 USB 调试。
   用仓库 devices 检查；有多台设备先让我选择，不猜设备号。
4. 执行 bootstrap.sh / setup，生成 .mi-pad.local.json，运行 doctor。
5. 在设备空闲、获得实际锁后运行 examples/smoke_test.py。
   它会唤醒、返回桌面并获取新截图和 XML；完成或失败均释放锁。
6. 核对截图、前台包名和释放结果，打开 observe 共享投屏，方便我随时协助。
7. 报告已通过的检查、证据文件和仍需我完成的步骤。

不要创建周期任务、购物、支付、发消息或打开考勤入口。
不要上传我的截图、设备配置、凭证或位置。后续具体操作由我另行布置。
```
