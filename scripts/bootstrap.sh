#!/usr/bin/env bash
# Does not run remote scripts, install packages, or change global configuration.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
if ! command -v python3 >/dev/null 2>&1; then
  echo '需要 Python 3.10+；安装方法见 docs/SETUP.md' >&2
  exit 78
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 78)'
if [ -f .mi-pad.local.json ]; then
  python3 scripts/tablet_control.py doctor
else
  python3 scripts/tablet_control.py setup "$@"
  python3 scripts/tablet_control.py doctor
fi
echo '连接检查完成。验收：python3 examples/smoke_test.py（会唤醒设备并返回桌面）'
