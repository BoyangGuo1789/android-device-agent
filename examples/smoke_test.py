#!/usr/bin/env python3
"""Hold one lease, wake to Home, capture fresh UI evidence, always release."""
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.config import ConfigError
from scripts.tablet_control import Controller, LockError


def main():
    controller = None
    token = None
    try:
        controller = Controller()
        token = controller.acquire(os.environ.get("MI_PAD_TASK_ID", "local-smoke-test"),
                                   "用户请求的基础链路验收", wait=20)["token"]
        wake = controller.wake(token)
        name = datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        evidence = controller.capture(token, Path(__file__).resolve().parents[1] / "outputs" / "smoke", name)
        print(json.dumps({"ok": True, "wake": wake, "evidence": evidence}, ensure_ascii=False))
        return 0
    except (LockError, ConfigError) as exc:
        print(json.dumps({"ok": False, "error": getattr(exc, "code", "CONFIG_ERROR"),
                          "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 74
    except (OSError, subprocess.SubprocessError, ET.ParseError) as exc:
        print(json.dumps({"ok": False, "error": "DEVICE_OR_IO_ERROR", "type": type(exc).__name__}), file=sys.stderr)
        return 74
    finally:
        if token is not None:
            try:
                controller.release(token)
                print(json.dumps({"lease_released": True}))
            except LockError as exc:
                print(json.dumps({"lease_released": False, "error": exc.code}), file=sys.stderr)
                raise SystemExit(73)


if __name__ == "__main__":
    sys.exit(main())
