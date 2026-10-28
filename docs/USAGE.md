# 控制接口与设备锁

说明实际执行入口；首次连接先完成 [SETUP](SETUP.md)。

## 一次 CLI 会话

```bash
python3 scripts/tablet_control.py status
python3 scripts/tablet_control.py acquire --owner my-task --purpose '查看系统设置' --ttl 900 --wait 20
```

领取成功的 JSON 包含一次性 token。由 Agent 在当前进程保存，不写入代码、文档、聊天总结或日志。后续用 `--token` 或环境变量 `MI_PAD_LOCK_TOKEN`：

```bash
export MI_PAD_LOCK_TOKEN='<仅在本机会话中填入实际 token>'
python3 scripts/tablet_control.py wake
python3 scripts/tablet_control.py capture --dir outputs/session --name 001-home
python3 scripts/tablet_control.py adb -- shell dumpsys window windows
python3 scripts/tablet_control.py adb -- shell am start -a android.settings.SETTINGS
python3 scripts/tablet_control.py capture --dir outputs/session --name 002-settings
python3 scripts/tablet_control.py release
python3 scripts/tablet_control.py status
unset MI_PAD_LOCK_TOKEN
```

手工使用时注意 shell 历史可能记录 export；程序集成优先使用下节 Python 接口，不把 token 输出给第三方。启动设置页后需读新截图才能决定点击位置。点击、滑动、按键格式为：

```text
adb -- shell input tap X Y
adb -- shell input swipe X1 Y1 X2 Y2 DURATION_MS
adb -- shell input keyevent KEYCODE_BACK
```

这里的 `adb` 指 `python3 scripts/tablet_control.py adb` 子命令，不能直接调用原生命令。坐标须来自当前屏幕，不能把示例值作为实际目标。

## Python 会话（建议用于脚本）

从仓库根目录执行，或将仓库根目录加入脚本的模块搜索路径：

```python
from scripts.tablet_control import Controller

c = Controller()
token = c.acquire('my-task', '用户授权的任务', wait=20)['token']
try:
    c.wake(token)
    evidence = c.capture(token, 'outputs/my-task', '001-home')
    # 读取 evidence['files'] 中的新图 / XML，然后决定下一步。
    # c.adb(token, ['shell', 'input', 'tap', str(x), str(y)])
    # 每次关键动作后重新 capture；耗时等待前可 c.renew(token)。
finally:
    c.release(token)
```

`Controller` 的 `serial`、`state_dir`、`boot_id` 和后端注入参数用于测试；业务代码应使用无参数构造，统一读取本机配置及标准锁目录。不要借助这些参数隔离出第二个操作锁。

## 命令与返回值

| 子命令 | 用途 | 需要 token |
|---|---|---|
| `devices` | 枚举 serial 与连接状态 | 否，只做发现 |
| `setup` | 自动或显式选择设备、创建本机配置 | 否，只做发现 |
| `doctor` | 检查配置、可执行路径与连接 | 否，只做发现 |
| `status` | 查看当前持有者、过期时间和命令是否运行 | 否，不读取 App |
| `acquire` | 领取 TTL 租约（1–3600 秒） | 否 |
| `renew` / `release` | 续租 / 释放 | 是 |
| `wake` | 唤醒、普通解除无密码锁屏、进入桌面并核验 | 是 |
| `adb -- …` | 对选定 serial 执行子命令 | 是 |
| `capture --dir … --name …` | 新 XML 与 PNG；`--no-image` 只采 XML | 是 |
| `observe` | 用户可交互的共享投屏 | 否，AI 不得从此输入 |
| `scrcpy -- …` | AI 持锁的独占镜像会话 | 是，退出才可运行其他命令 |

`adb` 保留后端原始输出和退出码，支持二进制；其他控制命令一般输出 JSON。若 XML 采集失败，可持锁取得新截图：

```bash
python3 scripts/tablet_control.py adb -- exec-out screencap -p > outputs/fresh-screen.png
```

重定向前确保目录存在并使用全新文件名。该低层接口不替调用者检查覆盖或 PNG 有效性；`capture` 会检查。

退出码：64 参数不允许；73 锁、令牌、证据名冲突；74 设备 / I/O / 核验失败；78 配置或平台不支持。错误 JSON 写 stderr；上层必须检查退出码。

## 锁的范围

状态目录为 `~/.local/state/mi-pad/<serial>/`，包含不可替换的 `execution.lock`、原子更新的 `session.json` 与省略 token / 输入 / 画面内容的 `audit.jsonl`。

- 同一用户、同一主机的多个仓库副本使用同一 serial 时共享锁。
- 每次设备操作持有 OS 锁。子进程继承锁描述符，因此父进程异常退出不让仍在运行的 ADB / scrcpy 失去互斥。
- 正在执行的命令不会仅因 TTL 到期被另一个 Agent 抢占。命令结束刷新 TTL；系统重启使旧租约失效。
- 锁是协作机制，不是 Android 安全边界，也不阻止用户直接触屏或其他主机操作。共享投屏与 AI 可能同时改变界面，必须重读后再动作。
- `adb shell` 仍拥有 Android shell 权限。命令允许列表只约束设备选择，不负责审核每条业务操作；不提供自动付款等策略保证。

截图、XML 先后采集，不能视为同一帧原子快照；用户操作或页面自动刷新时须核对包名和画面是否一致。若 PNG 采集失败，已保存的 XML 可能留在原目录；该次仍返回失败，重试须换文件名。
