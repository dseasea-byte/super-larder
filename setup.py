#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""setup.py — 新用户一键初始化。

做四件事，全部在本机完成，不联网（除首次装 jieba）：
  1. 检查 Python 版本
  2. 确保 jieba 可用（缺则自动 pip 安装）
  3. 生成 config.json 并建好知识库目录
  4. 首次构建 + 校验 + 出审核报告

用法：
  python scripts/setup.py                    # 默认知识库 ~/.workbuddy/convo-kb
  python scripts/setup.py --kb D:/我的对话库   # 指定知识库位置
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SKILL = Path(__file__).resolve().parent          # 本文件就在技能根目录
BUILD = SKILL / "scripts" / "build.py"
CONFIG = Path(os.environ.get("CONVO_RECALL_CONFIG") or (SKILL / "config.json"))


def step(n: int, text: str) -> None:
    print(f"\n[{n}/4] {text}", flush=True)


def ensure_jieba() -> bool:
    def _can_import() -> bool:
        try:
            import jieba  # noqa: F401
            return True
        except ImportError:
            return False

    if _can_import():
        print("  jieba 已就绪")
        return True

    print("  缺少 jieba，正在安装……")
    # 依次尝试：直接装 → 装到用户目录（macOS / Linux 常见权限问题）
    attempts = [
        [sys.executable, "-m", "pip", "install", "-q", "jieba"],
        [sys.executable, "-m", "pip", "install", "-q", "--user", "jieba"],
    ]
    r = None
    for cmd in attempts:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            break
    if r is None or r.returncode != 0:
        print("  自动安装失败。请手动执行下面任意一条：")
        print(f"    {sys.executable} -m pip install --user jieba")
        print(f"    {sys.executable} -m pip install --break-system-packages jieba   # Homebrew Python")
        print("  网络受限时可加镜像：-i https://pypi.tuna.tsinghua.edu.cn/simple")
        return False

    # 关键修正：`--user` 装进的是「解释器启动时可能还不存在」的目录。
    # os.path 与导入器都缓存过目录状态，不清缓存、不补 sys.path，
    # 同一进程里再 import 仍会失败——macOS 上实测踩到，表现为
    # jieba 明明装好了却报「安装后仍无法导入」。
    import importlib
    import site as _site
    importlib.invalidate_caches()
    try:
        user_site = _site.getusersitepackages()
    except Exception:
        user_site = None
    if user_site and os.path.isdir(user_site) and user_site not in sys.path:
        sys.path.append(user_site)

    if _can_import():
        print("  安装完成")
        return True

    print("  安装后仍无法导入。诊断信息：")
    print(f"    当前解释器：{sys.executable}")
    show = subprocess.run([sys.executable, "-m", "pip", "show", "jieba"],
                          capture_output=True, text=True).stdout
    for line in show.splitlines():
        if line.startswith(("Name:", "Version:", "Location:")):
            print(f"    {line}")
    print("    若 Location 与解释器不是同一个环境，请用上面那个解释器重装：")
    print(f"    {sys.executable} -m pip install --user jieba")
    return False


def write_config(kb: Path) -> None:
    cfg = {}
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    cfg["kb_root"] = str(kb)
    cfg.setdefault("projects_root", None)
    if not cfg.get("projects_root"):
        cfg["projects_root"] = None
    cfg["_说明"] = "kb_root 是知识库落盘位置，可改成任意路径；projects_root 留空则用 ~/.workbuddy/projects"
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def run(*args: str) -> int:
    sys.stdout.flush()
    return subprocess.run([sys.executable, str(BUILD), *args]).returncode


def main() -> int:
    ap = argparse.ArgumentParser(prog="setup.py", description="super-larder 初始化")
    ap.add_argument("--kb", help="知识库目录，默认 ~/.workbuddy/convo-kb")
    ap.add_argument("--skip-build", action="store_true", help="只做环境准备，不建库")
    args = ap.parse_args()

    print("=" * 52)
    print("  super-larder · 对话知识库 初始化")
    print("  全部在本机运行，不调用任何线上模型")
    print("=" * 52)

    step(1, "检查 Python")
    if sys.version_info < (3, 9):
        print(f"  需要 Python 3.9 及以上，当前 {sys.version.split()[0]}")
        return 2
    print(f"  Python {sys.version.split()[0]} 可用")

    step(2, "检查分词库")
    if not ensure_jieba():
        return 2

    step(3, "准备知识库目录")
    kb = None
    if args.kb:
        kb = Path(args.kb).expanduser().resolve()
    elif os.environ.get("CONVO_KB"):
        kb = Path(os.environ["CONVO_KB"]).expanduser().resolve()
    elif CONFIG.exists():
        try:
            cfg_kb = json.loads(CONFIG.read_text(encoding="utf-8")).get("kb_root")
        except Exception:
            cfg_kb = None
        if cfg_kb:
            kb = Path(cfg_kb).expanduser().resolve()
    if kb is None:
        kb = Path.home() / ".workbuddy" / "convo-kb"
    for sub in ("raw", "wiki", "_系统"):
        (kb / sub).mkdir(parents=True, exist_ok=True)
    write_config(kb)
    print(f"  知识库：{kb}")
    print(f"  配置：  {CONFIG}")

    if args.skip_build:
        print("\n已跳过构建。随时可执行：python scripts/build.py build")
        return 0

    step(4, "首次构建")
    if run("build", "--force") != 0:
        print("\n构建失败，请把上面的报错发给我。")
        return 1
    run("lint")
    print()
    run("report")

    print("\n" + "=" * 52)
    print("  完成。以后每次想更新，二选一：")
    _launcher = "setup.command" if sys.platform == "darwin" else (
        "setup.cmd" if os.name == "nt" else "setup.py")
    print(f"    双击 SKILL 目录下的 {_launcher}")
    print(f"    或 python {BUILD} build")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    sys.exit(main())
