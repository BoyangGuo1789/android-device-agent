# 工作区与数据边界

说明可分享源码、每台电脑的本机状态及 Android 设备之间的关系。

| 位置 / 角色 | 内容与责任 | Git 边界 |
|---|---|---|
| GitHub `BoyangGuo1789/android-device-agent` | 通用源码、测试、文档与示例；默认分支 `main` | 公开可克隆 |
| 使用者电脑上的克隆 | AI Agent 执行 Python，调用本机 Linux / macOS 工具 | 修改后可自行评审、贡献 |
| `.mi-pad.local.json` | 使用者自己的 serial 和工具路径 | 忽略，不上传 |
| `~/.local/state/mi-pad/<serial>/` | 当前 Unix 用户共享的锁、租约与最小审计日志 | 仓库外，仅本机 |
| `outputs/` 等目录 | 截图、XML、任务产物 | 忽略，仅本机 |
| Android 设备 | 运行 App；用户负责调试授权、登录与认证 | 不迁移 App 数据或账号 |

```text
GitHub 通用代码 → 使用者电脑 → 本机锁入口 → 使用者自己的 Android 设备
设备界面 → 本机新证据 → Agent 读取与核验 → 用户收到结果
```

此发布副本由原项目两个控制 / 测试源文件派生，原工作区及历史材料不随仓库上传。源码血缘见 [PROVENANCE](PROVENANCE.md)。不存在服务器运行目录、远程控制隧道或后台模型服务。

维护流程为本机修改 → 隔离测试 → 检查 Git 差异和发布文件 → 提交；对外贡献通过分支与 Pull Request。不要上传自己的本机配置、设备证据和认证材料。

发布账号通过 GitHub 连接器及 SSH 核实为 `BoyangGuo1789`；提交作者使用该账号的 GitHub noreply 地址，不依赖其他项目的 Git 全局配置。各使用者贡献时自行设置作者身份。

## 名称兼容

2026-10-28 对外名称改为 **Android Device Agent**，仓库改为 `android-device-agent`。原始 Mi-pad 项目名称保留在源码来源记录中。为继续与已有控制任务共享同一把锁，本机 `.mi-pad.local.json`、`MI_PAD_LOCK_TOKEN`、`MI_PAD_CONFIG` 及 `~/.local/state/mi-pad/<serial>/` 暂保留兼容名称；重命名不能创建第二套锁状态。
