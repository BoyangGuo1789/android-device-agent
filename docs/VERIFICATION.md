# 发布验证

记录通用发布版在 2026-10-28（Asia/Shanghai）的实际验证范围。

## 自动测试

已运行 `python3 -m unittest discover -s tests -v`，**37 项通过**。测试使用模拟设备与临时状态目录，不控制真实平板。

覆盖原有多进程争锁、过期租约、父进程异常、日志内容和共享投屏；新增本机配置、设备选择、路径、唤醒与证据采集回归测试，包括异步解除无密码锁屏时的状态变化。

## 发布内容检查

已运行 `python3 scripts/validate_package.py`，25 个允许发布的源码 / 文档文件通过检查，相对文档链接和文档索引有效。另检查实际设备标识、原本机绝对路径、私人账号与任务标识未进入发布文件。

`.mi-pad.local.json`、真实截图 / XML、诊断日志和 Python 缓存均由 Git 忽略。原项目控制与测试文件的 SHA-256 与派生前一致，未修改原件。

已通过不使用 GitHub 登录凭据的 HTTPS 全新克隆验证：不包含本机配置，首次 `status` 明确返回配置缺失（78），37 项测试和发布检查均通过。

## 真机与跨平台

已在本机使用新发布版完成 setup / doctor 与真机基础验收，环境为 macOS、Python 3.14.6、ADB 36.0.0、scrcpy 3.3.1：

- 初次唤醒检查遇到瞬时锁屏状态，按失败处理并释放锁；检查确认无密码锁屏已解除后，为异步状态变化增加了有限等待及回归测试。
- 随后持锁 `wake` 确认 `keyguard_showing=false`、前台桌面包名 `com.miui.home`。
- 新 PNG 已人工检查为桌面，XML 包名同为 `com.miui.home`，采集返回成功。
- 共享投屏启动后后端返回 `Renderer: metal`、`Texture: 856x1280`；测试窗口已关闭。未为验证主动注入用户点击，用户点击的实际效果不在本次验收范围。
- 最终锁状态 `locked=false`、`session=null`、`command_running=false`，无遗留 scrcpy 进程。

原始证据只保存在维护者本机被忽略的 `outputs/smoke/`，不公开设备界面。没有为本次验证主动打开业务 App、提交考勤、购物或发送消息。

此步骤成功不能证明其他电脑、所有 App 或 Windows 已实测通过。取得链接的使用者仍须在自己的设备上运行验收。

GitHub Actions 矩阵为 macOS / Ubuntu、Python 3.10 / 3.14；最新执行结果见 [GitHub Actions](https://github.com/BoyangGuo1789/android-device-agent/actions)。本文件记录的 37 项通过指本机实际执行，其他矩阵以 Actions 结果为准。

首次 CI 在 macOS / Python 3.10 暴露了原续租测试使用 0.2 秒 TTL 的计时敏感性；发布版将该测试改为受控单调时钟，直接验证“超过原到期点但尚未到续租到期点仍互斥”，避免磁盘同步耗时影响结论。
