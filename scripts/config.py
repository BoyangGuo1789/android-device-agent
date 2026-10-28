"""Local configuration and dependency discovery. No third-party Python packages."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


class ConfigError(Exception):
    pass


def ensure_platform():
    if sys.platform not in {"darwin", "linux"}:
        raise ConfigError("本版本使用 POSIX 进程锁；Windows 请在 WSL2 内运行，参阅 docs/SETUP.md")


def config_path():
    return Path(os.environ.get("MI_PAD_CONFIG", str(ROOT / ".mi-pad.local.json"))).expanduser()


def validate_serial(serial):
    if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", serial):
        raise ConfigError("设备 serial 不能为空、不能包含路径或空格；请重新 setup")
    return serial


def executable(name, configured=None, required=True):
    value = configured or name
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{name} 路径必须为非空字符串")
    found = shutil.which(str(Path(value).expanduser()))
    if found:
        return str(Path(found).resolve())
    if required:
        raise ConfigError(f"找不到可执行的 {name}；安装方法见 docs/SETUP.md，或 setup --{name} /absolute/path")
    return value


def load_config():
    ensure_platform()
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError("尚未配置设备。先运行 python3 scripts/tablet_control.py setup") from exc
    except (OSError, ValueError) as exc:
        raise ConfigError("本机配置无法读取；保留原件并检查 JSON 格式") from exc
    if not isinstance(data, dict) or set(data) - {"serial", "adb", "scrcpy"}:
        raise ConfigError("配置只接受 serial、adb、scrcpy 三个字段")
    data["serial"] = validate_serial(data.get("serial"))
    data["adb"] = executable("adb", data.get("adb"))
    data["scrcpy"] = executable("scrcpy", data.get("scrcpy"), required=False)
    return data


def list_devices(adb):
    # Discovery is the only non-device-targeted ADB operation. Never wakes or inputs.
    result = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True,
                            check=True, timeout=15)
    devices = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and not line.startswith(("List of devices", "*")):
            devices.append({"serial": parts[0], "state": parts[1]})
    return devices


def setup(serial=None, adb=None, scrcpy=None):
    ensure_platform()
    path = config_path()
    if path.exists():
        raise ConfigError("配置已经存在，不覆盖。先检查原配置；换设备时将原件重命名备份后再 setup")
    adb = executable("adb", adb)
    scrcpy = executable("scrcpy", scrcpy, required=False)
    devices = list_devices(adb)
    online = [d["serial"] for d in devices if d["state"] == "device"]
    if serial is None:
        if len(devices) != 1 or len(online) != 1:
            raise ConfigError("需恰好一台已授权设备；运行 devices 查看状态，多设备时 setup --serial <设备号>")
        serial = online[0]
    validate_serial(serial)
    if serial not in online:
        raise ConfigError("选定设备未在线或尚未授权 USB 调试；请在设备上完成授权再运行 setup")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump({"serial": serial, "adb": adb, "scrcpy": scrcpy}, out, ensure_ascii=False, indent=2)
        out.write("\n")
    return {"ok": True, "configured": True, "config": str(path), "serial": serial,
            "scrcpy_available": shutil.which(scrcpy) is not None}


def doctor():
    data = load_config()
    devices = list_devices(data["adb"])
    state = next((d["state"] for d in devices if d["serial"] == data["serial"]), "missing")
    mirror = shutil.which(data["scrcpy"]) is not None
    return {"ok": state == "device", "platform": sys.platform, "python": sys.version.split()[0],
            "serial": data["serial"], "device_state": state, "adb": data["adb"],
            "scrcpy_available": mirror,
            "next": "运行 examples/smoke_test.py 验收基础链路" if state == "device"
                    else "检查 USB 数据线并在设备上授权 USB 调试"}
