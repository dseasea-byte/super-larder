#!/bin/bash
# macOS / Linux 双击运行入口（Windows 用 setup.cmd）
cd "$(dirname "$0")" || exit 1

PY=""
command -v python3 >/dev/null 2>&1 && PY="python3"
if [ -z "$PY" ]; then
  command -v python >/dev/null 2>&1 && PY="python"
fi
if [ -z "$PY" ]; then
  echo ""
  echo "[!] 没找到 Python。请先安装 3.9 以上版本："
  echo "    https://www.python.org/downloads/"
  echo ""
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi

"$PY" setup.py "$@"

echo ""
read -n 1 -s -r -p "按任意键关闭…"
