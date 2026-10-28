#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
python3 scripts/tablet_control.py observe
