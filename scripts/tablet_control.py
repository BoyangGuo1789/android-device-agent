#!/usr/bin/env python3
"""One host-local lease per tablet, with an OS mutex around every device command."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import math
import shlex
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

if __package__:
    from .config import ConfigError, config_path, doctor, ensure_platform, executable, list_devices, load_config, setup, validate_serial
else:
    from config import ConfigError, config_path, doctor, ensure_platform, executable, list_devices, load_config, setup, validate_serial

TOKEN_ENV = "MI_PAD_LOCK_TOKEN"
OBSERVER_OPTIONS = ["--no-audio", "--no-power-on", "--no-clipboard-autosync",
                    "--max-size=1280", "--always-on-top", "--window-title=Mi-pad Agent"]


class LockError(Exception):
    def __init__(self, code, message, exit_code=73):
        super().__init__(message)
        self.code, self.exit_code = code, exit_code


def boot_identity():
    if sys.platform == "darwin":
        return subprocess.check_output(["/usr/sbin/sysctl", "-n", "kern.boottime"], text=True).strip()
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


class Controller:
    def __init__(self, state_dir=None, adb=None, scrcpy=None, boot_id=None,
                 process_reader=None, serial=None):
        ensure_platform()
        cfg = load_config() if serial is None else {}
        self.serial = validate_serial(serial or cfg.get("serial"))
        self.directory = Path(state_dir) if state_dir is not None else Path.home() / ".local/state/mi-pad" / self.serial
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path = self.directory / "session.json"
        self.adb_bin = str(adb or cfg.get("adb") or executable("adb", required=False))
        self.scrcpy_bin = str(scrcpy or cfg.get("scrcpy") or executable("scrcpy", required=False))
        self.observer_args = ["--serial", self.serial, *OBSERVER_OPTIONS]
        self.boot_id = boot_id if boot_id is not None else boot_identity()
        self.process_reader = process_reader or self.read_processes

    @staticmethod
    def read_processes():
        try:
            output = subprocess.run(["/bin/ps", "-ww", "-axo", "pid=,command="], capture_output=True,
                                    text=True, check=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise LockError("PROCESS_CHECK_FAILED", "无法检查现有投屏，拒绝设备控制", 74) from exc
        result = []
        for line in output.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                result.append((int(parts[0]), parts[1]))
        return result

    def unguarded_scrcpy(self):
        """List other scrcpy processes for status; human input is permitted."""
        unsafe = []
        for pid, command in self.process_reader():
            executable = command.split(None, 1)[0] if command else ""
            if Path(executable).name != "scrcpy":
                continue
            try:
                args = shlex.split(command)
            except ValueError:
                unsafe.append(pid)
                continue
            if executable != self.scrcpy_bin or args[1:] != self.observer_args:
                unsafe.append(pid)
        return unsafe

    @contextmanager
    def mutex(self):
        # Never unlink this file: replacing the inode would create two independent locks.
        fd = os.open(self.directory / "execution.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise LockError("COMMAND_BUSY", "另一个设备命令仍在执行；不能抢占或释放它的锁")
            yield fd
        finally:
            # Do NOT LOCK_UN here. An inherited descriptor must retain the lock if
            # this process is killed while its adb/scrcpy child is still running.
            os.close(fd)

    def read_state(self):
        try:
            state = json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return None
        except (ValueError, OSError) as exc:
            raise LockError("STATE_INVALID", "锁状态不可读；拒绝设备操作，不能当作空闲") from exc
        required = {"token_hash", "owner", "purpose", "ttl", "boot_id", "expires_mono", "expires_at"}
        if not isinstance(state, dict) or not required.issubset(state):
            raise LockError("STATE_INVALID", "锁状态格式损坏；拒绝设备操作")
        if (not isinstance(state["token_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", state["token_hash"])
                or not all(isinstance(state[k], str) for k in ("owner", "purpose", "boot_id", "expires_at"))
                or any(not isinstance(state[k], (int, float)) or isinstance(state[k], bool)
                       or not math.isfinite(state[k]) for k in ("ttl", "expires_mono"))
                or not 0 < state["ttl"] <= 3600):
            raise LockError("STATE_INVALID", "锁状态字段损坏；拒绝设备操作")
        return state

    def write_state(self, state):
        fd, name = tempfile.mkstemp(prefix=".session-", dir=self.directory)
        try:
            with os.fdopen(fd, "w") as out:
                json.dump(state, out, ensure_ascii=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.state_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def audit(self, event, state=None):
        # Do not log tokens, raw commands, input text, screenshots or UI contents.
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event, "serial": self.serial,
                  "owner": (state or {}).get("owner")}
        fd = os.open(self.directory / "audit.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as out:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    def expired(self, state):
        return state["boot_id"] != self.boot_id or time.monotonic() >= state["expires_mono"]

    def touch(self, state):
        state["expires_mono"] = time.monotonic() + state["ttl"]
        state["expires_at"] = datetime.fromtimestamp(time.time() + state["ttl"], timezone.utc).isoformat()
        self.write_state(state)

    def public(self, state):
        return {k: v for k, v in state.items() if k not in {"token_hash", "boot_id", "expires_mono"}}

    def acquire(self, owner, purpose, ttl=900, wait=0):
        if (not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or not 0 < ttl <= 3600
                or not isinstance(wait, (int, float)) or not math.isfinite(wait) or not 0 <= wait <= 60):
            raise LockError("BAD_LEASE", "TTL 须为 0–3600 秒且大于 0；wait 须为 0–60 秒", 64)
        deadline = time.monotonic() + wait
        while True:
            try:
                with self.mutex():
                    old = self.read_state()
                    if old and not self.expired(old):
                        raise LockError("LOCK_BUSY", "设备已被占用: " + json.dumps(self.public(old), ensure_ascii=False))
                    if old:
                        self.audit("expired_lease_reclaimed", old)
                    token = secrets.token_urlsafe(32)
                    state = {"token_hash": hashlib.sha256(token.encode()).hexdigest(), "owner": owner,
                             "purpose": purpose, "ttl": ttl, "boot_id": self.boot_id,
                             "acquired_at": datetime.now(timezone.utc).isoformat()}
                    self.touch(state)
                    self.audit("acquire", state)
                    return {"ok": True, "token": token, "serial": self.serial, **self.public(state)}
            except LockError as exc:
                if exc.code not in {"LOCK_BUSY", "COMMAND_BUSY"} or time.monotonic() >= deadline:
                    raise
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    def require(self, token):
        if not token:
            raise LockError("TOKEN_REQUIRED", "先 acquire，并通过 --token 或 MI_PAD_LOCK_TOKEN 提供本次令牌")
        state = self.read_state()
        digest = hashlib.sha256(token.encode()).hexdigest()
        if not state or not secrets.compare_digest(state["token_hash"], digest):
            raise LockError("NOT_OWNER", "令牌不是当前设备锁持有者；拒绝操作")
        if self.expired(state):
            raise LockError("LEASE_EXPIRED", "租约已过期；重新 acquire 并重读设备页面，不能沿用旧坐标")
        return state

    def status(self):
        try:
            with self.mutex():
                state = self.read_state()
                return {"serial": self.serial, "command_running": False, "other_scrcpy_pids": self.unguarded_scrcpy(),
                        "locked": bool(state and not self.expired(state)),
                        "session": self.public(state) if state else None}
        except LockError as exc:
            if exc.code != "COMMAND_BUSY":
                raise
            state = self.read_state()
            return {"serial": self.serial, "command_running": True, "locked": True, "other_scrcpy_pids": self.unguarded_scrcpy(),
                    "session": self.public(state) if state else None}

    def renew(self, token):
        with self.mutex():
            state = self.require(token)
            self.touch(state)
            self.audit("renew", state)
            return {"ok": True, **self.public(state)}

    def release(self, token):
        with self.mutex():
            state = self.require(token)
            self.state_path.unlink()
            self.audit("release", state)
            return {"ok": True, "released": True}

    @contextmanager
    def command(self, token, action):
        with self.mutex() as fd:
            state = self.require(token)
            self.touch(state)
            self.audit(action + "_start", state)
            try:
                yield fd
            finally:
                # A running command never becomes stealable merely because its TTL elapsed.
                self.touch(state)
                self.audit(action + "_end", state)

    def raw_adb(self, args, fd, **kwargs):
        return subprocess.run([self.adb_bin, "-s", self.serial, *args], pass_fds=(fd,), **kwargs)

    def adb(self, token, args):
        # Accept an adb subcommand, never another device/server selector.
        allowed = {"shell", "exec-out", "get-state", "get-serialno", "get-devpath", "pull", "push",
                   "install", "install-multiple", "uninstall", "logcat", "bugreport", "forward", "reverse"}
        if not args or args[0] not in allowed:
            raise LockError("BAD_COMMAND", "仅接受指定设备的 ADB 子命令；不允许改变 serial 或 ADB server", 64)
        with self.command(token, "adb") as fd:
            return self.raw_adb(args, fd).returncode

    def scrcpy(self, token, args):
        if any(a.startswith(("-s", "--serial", "--tcpip", "--select-", "--otg")) for a in args):
            raise LockError("BAD_COMMAND", "scrcpy 设备选择由锁入口固定", 64)
        with self.command(token, "scrcpy") as fd:
            return subprocess.run([self.scrcpy_bin, "--serial", self.serial, *args], pass_fds=(fd,)).returncode

    def observe(self):
        # User may click/type in this shared viewer; it does not take the AI lock.
        # Agents must re-read the UI because a person can change it at any time.
        return subprocess.run([self.scrcpy_bin, *self.observer_args]).returncode

    @staticmethod
    def keyguard_showing(policy):
        values = re.findall(r"^\s*showing=(true|false)\s*$", policy, re.M)
        if len(values) != 1:
            raise LockError("KEYGUARD_UNKNOWN", "无法可靠识别锁屏状态；保留现场并报告", 74)
        return values[0] == "true"

    def wake(self, token):
        with self.command(token, "wake") as fd:
            def read(args):
                return self.raw_adb(args, fd, capture_output=True, text=True, check=True, timeout=30).stdout
            if read(["get-state"]).strip() != "device":
                raise LockError("DEVICE_OFFLINE", "设备未在线", 74)
            read(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
            read(["shell", "wm", "dismiss-keyguard"])
            # Dismissal is asynchronous: give the keyguard transition a bounded wait.
            for _ in range(10):
                policy = read(["shell", "dumpsys", "window", "policy"])
                if not self.keyguard_showing(policy):
                    break
                time.sleep(0.2)
            else:
                raise LockError("KEYGUARD_BLOCKED", "唤醒后仍有锁屏；请用户自行解锁，不尝试绕过认证", 74)
            read(["shell", "input", "keyevent", "KEYCODE_HOME"])
            expected = read(["shell", "cmd", "package", "resolve-activity", "--brief", "-a",
                             "android.intent.action.MAIN", "-c", "android.intent.category.HOME"])
            components = [line.strip() for line in expected.splitlines() if "/" in line and " " not in line.strip()]
            if not components:
                raise LockError("HOME_UNKNOWN", "已唤醒并发送 HOME，但无法确认桌面包名", 74)
            package = components[-1].split("/", 1)[0]
            for _ in range(6):
                activity = read(["shell", "dumpsys", "activity", "activities"])
                if re.search(r"(?:mResumedActivity|topResumedActivity).*\b" + re.escape(package) + r"/", activity):
                    return {"ok": True, "awake": True, "keyguard_showing": False, "home_package": package}
                time.sleep(0.3)
            raise LockError("HOME_UNCONFIRMED", "已唤醒并发送 HOME，但未确认桌面前台", 74)

    def capture(self, token, directory, name, with_image=True):
        if not re.fullmatch(r"[\w.-]+", name) or name in {".", ".."}:
            raise LockError("BAD_NAME", "证据名不能含路径分隔符", 64)
        with self.command(token, "capture") as fd:
            out = Path(directory)
            out.mkdir(parents=True, exist_ok=True)
            targets = [out / (name + ".xml")] + ([out / (name + ".png")] if with_image else [])
            if any(p.exists() for p in targets):
                raise LockError("EVIDENCE_EXISTS", "证据文件已存在；请使用新名称", 73)
            remote = "/sdcard/codex-locked-" + secrets.token_hex(12) + ".xml"
            try:
                self.raw_adb(["shell", "uiautomator", "dump", remote], fd, capture_output=True, check=True, timeout=45)
                with tempfile.TemporaryDirectory(prefix=".capture-", dir=out) as temp:
                    local = Path(temp) / "window.xml"
                    self.raw_adb(["pull", remote, str(local)], fd, capture_output=True, check=True, timeout=30)
                    root = ET.parse(local).getroot()
                    # Exclusive creation, including when another local writer races us.
                    with targets[0].open("xb") as file:
                        file.write(local.read_bytes())
                    if with_image:
                        result = self.raw_adb(["exec-out", "screencap", "-p"], fd, capture_output=True, check=True, timeout=30)
                        if not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
                            raise LockError("BAD_SCREENSHOT", "截图输出不是 PNG", 74)
                        with targets[1].open("xb") as file:
                            file.write(result.stdout)
                return {"ok": True, "files": [str(p.resolve()) for p in targets],
                        "packages": sorted({n.get("package") for n in root.iter("node") if n.get("package")})}
            finally:
                self.raw_adb(["shell", "rm", "-f", remote], fd, capture_output=True, timeout=15)


def main(argv=None, controller=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("devices", help="仅枚举连接设备，不唤醒或输入")
    configure = sub.add_parser("setup", help="选择本机设备并生成不入库的配置")
    configure.add_argument("--serial")
    configure.add_argument("--adb")
    configure.add_argument("--scrcpy")
    sub.add_parser("doctor", help="检查本机配置、工具及连接，不改变前台")
    sub.add_parser("status")
    sub.add_parser("observe", help="人机共用的可点击投屏，不占用 AI 控制锁")
    acquire = sub.add_parser("acquire")
    acquire.add_argument("--owner", required=True)
    acquire.add_argument("--purpose", required=True)
    acquire.add_argument("--ttl", type=int, default=900, choices=range(1, 3601), metavar="1..3600")
    acquire.add_argument("--wait", type=float, default=0)
    for action in ["release", "renew", "wake", "adb", "scrcpy", "capture"]:
        cmd = sub.add_parser(action)
        cmd.add_argument("--token", default=os.environ.get(TOKEN_ENV))
        if action in {"adb", "scrcpy"}:
            cmd.add_argument("args", nargs=argparse.REMAINDER)
        if action == "capture":
            cmd.add_argument("--dir", required=True)
            cmd.add_argument("--name", required=True)
            cmd.add_argument("--no-image", action="store_true")
    options = parser.parse_args(argv)
    try:
        ensure_platform()
        if options.action == "setup":
            print(json.dumps(setup(options.serial, options.adb, options.scrcpy), ensure_ascii=False))
            return 0
        if options.action == "devices":
            path = load_config()["adb"] if config_path().exists() else executable("adb")
            print(json.dumps({"devices": list_devices(path)}, ensure_ascii=False))
            return 0
        if options.action == "doctor":
            result = doctor()
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ok"] else 74
        c = controller or Controller()
        if options.action == "status":
            result = c.status()
        elif options.action == "observe":
            return c.observe()
        elif options.action == "acquire":
            if not 0 <= options.wait <= 60:
                raise LockError("BAD_WAIT", "单次等待限制为 0–60 秒", 64)
            result = c.acquire(options.owner, options.purpose, options.ttl, options.wait)
        elif options.action in {"adb", "scrcpy"}:
            args = options.args[1:] if options.args[:1] == ["--"] else options.args
            return getattr(c, options.action)(options.token, args)
        elif options.action == "capture":
            result = c.capture(options.token, options.dir, options.name, not options.no_image)
        else:
            result = getattr(c, options.action)(options.token)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ConfigError as exc:
        print(json.dumps({"ok": False, "error": "CONFIG_ERROR", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 78
    except LockError as exc:
        print(json.dumps({"ok": False, "error": exc.code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return exc.exit_code
    except (OSError, subprocess.SubprocessError, ET.ParseError) as exc:
        # CalledProcessError includes command arguments: avoid printing secrets entered via adb.
        print(json.dumps({"ok": False, "error": "DEVICE_OR_IO_ERROR", "type": type(exc).__name__}), file=sys.stderr)
        return 74


if __name__ == "__main__":
    sys.exit(main())
