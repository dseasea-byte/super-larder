#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recall.py — 本地历史对话索引与关键词检索（零依赖，仅标准库）。

数据源：<WorkBuddyHome>/projects/<工作区slug>/<会话ID>.jsonl
缓存：  <WorkBuddyHome>/super-larder/index.json

子命令：
  index    增量刷新索引（按 mtime + size 判定，未变文件直接复用）
  search   关键词检索，默认在「标题 + 用户请求」上匹配；--full 追加全文
  show     展开某个会话的清洗后用户请求与助手结论
  stats    索引概览

设计原则：
  - 只用标准库，不联网，不依赖分词器；中文按子串匹配，避免分词误差
  - 索引只存轻量元数据，正文在 show 时按需回读原始 jsonl
  - 所有输出 UTF-8，Windows 控制台不乱码
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------- 环境与常量

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WB_HOME = Path(os.environ.get("WORKBUDDY_HOME") or (Path.home() / ".workbuddy"))

# Codex 版补丁：与 build.py 一致，支持 config.json / 环境变量指定数据源与缓存位置
_SKILL_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = Path(os.environ.get("CONVO_RECALL_CONFIG") or (_SKILL_DIR / "config.json"))


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8")) if _CONFIG_PATH.exists() else {}
    except Exception:
        return {}


CONFIG = _load_config()
PROJECTS = (Path(CONFIG["projects_root"]).expanduser() if CONFIG.get("projects_root")
            else (WB_HOME / "projects"))
CACHE_DIR = (Path(CONFIG["cache_dir"]).expanduser() if CONFIG.get("cache_dir")
             else (Path(CONFIG["kb_root"]).expanduser() / "_系统" if CONFIG.get("kb_root")
                   else WB_HOME / "super-larder"))
INDEX_PATH = CACHE_DIR / "recall-index.json"
GATE_PATH = CACHE_DIR / "gate.json"
INDEX_VERSION = 6

# 需从用户消息中剥离的注入块（这些不是用户真实诉求）
NOISE_BLOCKS = [
    "system-reminder", "task-notification", "cb_summary", "craft_mode",
    "user_info", "identity_context", "project_context", "connector-status",
    "current_time", "additional-data", "user_query_meta", "memory",
    "user_memory", "tone_and_style", "product_identity", "available_skills",
    "working_modes", "agent_loop", "result_presentation", "final_answer",
    "tool_usage_policy", "search_routing", "wecom_cli_routing",
]
_BLOCK_RE = re.compile(
    r"<(" + "|".join(re.escape(b) for b in NOISE_BLOCKS) + r")\b[^>]*>.*?</\1>",
    re.S | re.I,
)
_ORPHAN_TAG_RE = re.compile(
    r"</?(?:" + "|".join(re.escape(b) for b in NOISE_BLOCKS) + r")\b[^>]*>",
    re.I,
)
_USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.S | re.I)
_WS_RE = re.compile(r"[ \t\u3000]+")
_NL_RE = re.compile(r"\n{2,}")
# 剥块后残留的工具样板句，需一并清除，否则会污染检索
_BOILERPLATE_RES = [
    re.compile(r"Use the \w+ tool with .*?(?:act on it|the output)\.?", re.S | re.I),
    re.compile(r"IMPORTANT: Before responding,.*", re.S | re.I),
    re.compile(r"You can now use the \w+ tool.*", re.S | re.I),
    re.compile(r"For background shell tasks,.*", re.S | re.I),
    re.compile(r"\[SYSTEM NOTIFICATION[^\]]*\].*", re.S | re.I),
    re.compile(r"This is an automated background.*", re.S | re.I),
]
_BOILERPLATE_HEAD_RE = re.compile(
    r"^(Use the|IMPORTANT|Note:|The following|Tool result|System:|For background|\[SYSTEM|This is an automated)",
    re.I,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


# ---------------------------------------------------------------- 文本清洗

def clean_user_text(raw: str) -> str:
    """把一条用户消息清洗成可读的真实诉求；噪音返回空串。"""
    if not raw:
        return ""
    m = _USER_QUERY_RE.search(raw)
    if m:  # 有显式 user_query 标签时，它就是全部诉求
        return _norm(m.group(1))
    text = _BLOCK_RE.sub(" ", raw)
    text = _ORPHAN_TAG_RE.sub(" ", text)
    for pat in _BOILERPLATE_RES:
        text = pat.sub(" ", text)
    text = _norm(text)
    return "" if _is_noise_prompt(text) else text


def _is_noise_prompt(t: str) -> bool:
    """判定清洗后的文本是否仍属系统注入，不该被当作历史诉求。"""
    if not t:
        return True
    cjk = len(_CJK_RE.findall(t))
    if _BOILERPLATE_HEAD_RE.match(t[:40]) and cjk < 3:
        return True
    if len(t.strip(" .,:;!?-_=*#>|/\\\n")) < 2:
        return True
    return False


def _norm(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _WS_RE.sub(" ", s)
    s = _NL_RE.sub("\n", s)
    return s.strip()


def clip(s: str, n: int) -> str:
    s = s.replace("\n", " ⏎ ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def extract_content(msg: dict) -> str:
    """从 message 记录里取出纯文本（content 可能是 str 或块数组）。"""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for blk in c:
            if isinstance(blk, dict):
                if blk.get("type") in ("input_text", "output_text", "text"):
                    t = blk.get("text")
                    if isinstance(t, str):
                        parts.append(t)
            elif isinstance(blk, str):
                parts.append(blk)
        return "\n".join(parts)
    return ""


# ---------------------------------------------------------------- 单文件解析

def parse_session(path: Path) -> dict | None:
    """解析一个 jsonl 会话文件，返回轻量元数据。"""
    title = ""
    cwd = ""
    prompts: list[str] = []
    last_assistant = ""
    start = end = None
    n_msg = 0

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue

                ts = rec.get("timestamp")
                if isinstance(ts, (int, float)) and ts > 1e11:
                    ts = ts / 1000.0
                if isinstance(ts, (int, float)):
                    start = ts if start is None else min(start, ts)
                    end = ts if end is None else max(end, ts)

                rtype = rec.get("type")
                if rtype == "ai-title":
                    t = rec.get("aiTitle") or ""
                    if isinstance(t, str) and t.strip():
                        title = t.strip()
                elif rtype == "message":
                    role = (rec.get("role") or "").lower()
                    if not cwd:
                        c = rec.get("cwd")
                        if isinstance(c, str) and c:
                            cwd = c
                    n_msg += 1
                    if role == "user":
                        txt = clean_user_text(extract_content(rec))
                        # 连续重复的同一条请求（重试/回显）只记一次
                        if len(txt) >= 2 and (not prompts or prompts[-1] != txt):
                            prompts.append(txt)
                    elif role == "assistant":
                        txt = clean_user_text(extract_content(rec))
                        if len(txt) >= 20:
                            last_assistant = txt
    except Exception:
        return None

    if start is None:
        return None
    # 会话若无真实用户请求（纯系统会话），不入索引
    if not prompts and not title:
        return None

    return {
        "id": path.stem,
        "slug": path.parent.name,
        "path": str(path),
        "title": title,
        "cwd": cwd,
        "start": round(start, 3),
        "end": round(end or start, 3),
        "msgs": n_msg,
        "prompts": [clip(p, 600) for p in prompts[:8]],
        "tail": clip(last_assistant, 400),
        "mtime": int(path.stat().st_mtime),
        "size": path.stat().st_size,
    }


# ---------------------------------------------------------------- 索引

def load_index() -> dict:
    if INDEX_PATH.exists():
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if data.get("version") == INDEX_VERSION:
                return data
        except Exception:
            pass
    return {"version": INDEX_VERSION, "built": 0, "sessions": {}}


def cmd_index(args) -> int:
    """索引所有客户端来源。

    v5 起不再假设「只有一个 jsonl 目录」：走 adapters 自动发现，
    并顺带记录 raw 快照路径，`show` 时直接展开可读快照。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import adapters
    from redactlib import collect_secrets, redact, secrets_clear

    sources = adapters.discover(CONFIG.get("sources") or [],
                                use_defaults=not CONFIG.get("sources_only"))
    if not sources:
        print("未发现任何客户端的转录目录。", file=sys.stderr)
        print("已检查：" + "、".join(f"{a} {r}" for a, r in adapters.DEFAULT_ROOTS), file=sys.stderr)
        return 2

    idx = load_index()
    old = {} if getattr(args, "force", False) else idx["sessions"]
    new: dict[str, dict] = {}
    added = updated = kept = 0
    scanned = 0

    # 索引里同样不能留明文。先把全量文本过一遍收集口令值，再逐条脱敏写入。
    secrets_clear()
    for src in sources:
        for path in src["files"]:
            for raw in adapters.iter_sessions(path):
                collect_secrets("\n".join(raw.get("prompts", [])))
                collect_secrets("\n".join(raw.get("asst", [])))

    raw_dir = CACHE_DIR.parent / "raw"

    for src in sources:
        for path in src["files"]:
            for raw in adapters.iter_sessions(path):
                scanned += 1
                sid = raw["id"]
                fp = [int(raw.get("end") or 0), int(raw.get("msgs") or 0)]
                prev = old.get(sid)
                if prev and prev.get("_fp") == fp:
                    new[sid] = prev
                    kept += 1
                    continue

                first_seen = sid not in new

                # 长会话只取前 8 条会漏掉中段的决策，均匀采样最多 12 条
                src_prompts = raw.get("prompts", [])
                if len(src_prompts) <= 12:
                    picked = src_prompts
                else:
                    step = (len(src_prompts) - 1) / 11
                    picked = [src_prompts[round(i * step)] for i in range(12)]
                prompts = [clip(redact(clean_user_text(x)), 600) for x in picked]
                prompts = [x for x in prompts if x]

                # 末条助手消息常常是工具输出，清洗后为空；往前找第一条有内容的
                tail = ""
                for a in reversed(raw.get("asst", [])):
                    t = redact(clean_user_text(a))
                    if t:
                        tail = clip(t, 400)
                        break

                snapshot = raw_dir / time.strftime("%Y-%m", time.localtime(raw["end"])) / f"{sid}.md"

                # 同一 id 多来源时留消息数更多的那份（rollout 通常比 SQLite 更全）
                existing = new.get(sid)
                if existing:
                    if existing.get("msgs", 0) > raw.get("msgs", 0):
                        # 留更全的那份，但补上客户端给的真实标题
                        if raw.get("title_src") and not existing.get("title_src"):
                            existing["title"] = raw["title"]
                            existing["title_src"] = "agent"
                        if not existing.get("cwd") and raw.get("cwd"):
                            existing["cwd"] = raw["cwd"]
                        continue

                new[sid] = {
                    "id": sid,
                    "slug": src["agent"],
                    "path": str(snapshot if snapshot.exists() else Path(raw["path"])),
                    "title": redact(raw.get("title") or (prompts[0][:30] if prompts else "")),
                    "title_src": raw.get("title_src") or "",
                    "cwd": raw.get("cwd") or "",
                    "start": round(raw["start"], 3),
                    "end": round(raw["end"], 3),
                    "msgs": raw.get("msgs", 0),
                    "prompts": prompts,
                    "tail": tail,
                    "_fp": fp,
                }
                # 同一 id 可能来自多个来源（rollout + SQLite），只在第一次计入
                if prev:
                    updated += 1
                elif first_seen:
                    added += 1

    idx = {"version": INDEX_VERSION, "built": int(time.time()), "sessions": new}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(
        f"索引完成：共 {len(new)} 个会话"
        f"（新增 {added}，更新 {updated}，复用 {kept}，扫描 {scanned}）"
    )
    print("来源：" + "、".join(f"{x['agent']}×{len(x['files'])}" for x in sources))
    print(f"缓存：{INDEX_PATH}")
    return 0


# ---------------------------------------------------------------- 检索

def parse_since(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip().lower()
    m = re.fullmatch(r"(\d+)\s*([dhwm])", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        secs = {"h": 3600, "d": 86400, "w": 604800, "m": 2592000}[unit]
        return time.time() - n * secs
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    return None


def scan_full_text(entry: dict, terms: list[str]) -> str:
    """在原始 jsonl 上做全文匹配。优先返回用户消息片段，其次助手结论。"""
    p = Path(entry["path"])
    if not p.exists():
        return ""
    lowered = [t.lower() for t in terms]
    fallback = ""
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                low = line.lower()
                if not any(t in low for t in lowered):
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                rtype = rec.get("type")
                if rtype == "message":
                    txt = clean_user_text(extract_content(rec))
                    # 命中可能来自已剥离的注入块，必须在清洗后的正文里再验一次
                    if not txt or not any(t in txt.lower() for t in lowered):
                        continue
                    role = (rec.get("role") or "").lower()
                    if role == "user":
                        return clip(txt, 300)  # 用户原话最可信，命中即返回
                    if not fallback:
                        fallback = clip(txt, 300)
                elif isinstance(rec.get("rawContent"), str):
                    txt = clean_user_text(rec["rawContent"])
                    if txt and any(t in txt.lower() for t in lowered) and not fallback:
                        fallback = clip(txt, 300)
    except Exception:
        return fallback
    return fallback


def score_entry(entry: dict, terms: list[str], full: bool) -> tuple[int, list[str]]:
    """打分：标题命中权重最高，其次用户请求，最后全文。"""
    title = (entry.get("title") or "").lower()
    prompts = "\n".join(entry.get("prompts") or []).lower()
    tail = (entry.get("tail") or "").lower()
    score = 0
    hits: list[str] = []

    for t in terms:
        tl = t.lower()
        got = False
        if tl in title:
            score += 12
            got = True
        n = prompts.count(tl)
        if n:
            score += 6 + min(n, 4)
            got = True
        if tl in tail:
            score += 2
            got = True
        if got:
            hits.append(t)

    # 完整短语（多词连写）命中，额外加权
    phrase = " ".join(terms).lower()
    if len(terms) > 1 and phrase in title:
        score += 10

    if full and score == 0:
        snippet = scan_full_text(entry, terms)
        if snippet:
            score = 3
            hits = list(terms)
            entry["_full_hit"] = snippet

    # 覆盖度加成：命中的词越多越可信
    if terms and len(hits) == len(terms):
        score = int(score * 1.4)

    return score, hits


def cmd_search(args) -> int:
    if not gate_allows(args):
        return 3
    idx = load_index()
    sessions = list(idx["sessions"].values())
    if not sessions:
        # 第一次用：自动建一次索引，别让用户先学命令
        print("（首次检索，正在建立索引…）", file=sys.stderr)
        try:
            cmd_index(argparse.Namespace(force=False))
        except Exception as exc:
            print(f"[!] 索引失败：{exc}", file=sys.stderr)
            return 3
        idx = load_index()
        sessions = list(idx["sessions"].values())
    if not sessions:
        print("[!] 仍无可用会话，检查转录目录是否存在。", file=sys.stderr)
        return 3

    terms = [t for t in re.split(r"[\s,，、]+", (args.keywords or "").strip()) if t]
    # 中文单字（如「卡」「库」）几乎必然误命中，多词查询时自动剔除
    dropped: list[str] = []
    if len(terms) > 1:
        kept = [t for t in terms if not (len(t) == 1 and _CJK_RE.match(t))]
        if kept and len(kept) < len(terms):
            dropped = [t for t in terms if t not in kept]
            terms = kept
    since = parse_since(args.since)
    cwd_filter = (args.cwd or "").lower()

    results = []
    for e in sessions:
        if since and (e.get("end") or 0) < since:
            continue
        if cwd_filter:
            c = (e.get("cwd") or "").lower().replace("\\", "/")
            if cwd_filter.replace("\\", "/") not in c:
                continue
        if terms:
            probe = dict(e)  # 用副本，便于回填 _full_hit 而不污染索引
            sc, hits = score_entry(probe, terms, args.full)
            if sc <= 0:
                continue
            results.append((sc, hits, probe))
        else:
            results.append((0, [], e))

    results.sort(key=lambda x: (-x[0], -(x[2].get("end") or 0)))
    results = results[: args.limit]

    if args.json:
        out = [
            {
                "score": sc,
                "hits": hits,
                "id": e["id"],
                "title": e.get("title", ""),
                "cwd": e.get("cwd", ""),
                "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(e.get("end") or 0)),
                "prompts": e.get("prompts", []),
                "tail": e.get("tail", ""),
                "full_hit": e.get("_full_hit", ""),
            }
            for sc, hits, e in results
        ]
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    if not results:
        print("未命中。可放宽关键词、去掉 --since，或用 --full 检索全文。")
        return 0

    scope = f"近 {args.since}" if args.since else "全部时间"
    kw = "、".join(terms) if terms else "（无关键词，按时间倒序列出）"
    note = f"（已忽略单字：{'、'.join(dropped)}）" if dropped else ""
    print(f"命中 {len(results)} 个会话｜关键词：{kw}{note}｜范围：{scope}\n")

    for i, (sc, hits, e) in enumerate(results, 1):
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.get("end") or 0))
        print(f"{i}. [{sc:>3}分] {e.get('title') or '(无标题)'}")
        print(f"   {when}｜{e.get('msgs', 0)} 条消息｜{e.get('cwd') or e.get('slug', '')}")
        if hits:
            print(f"   命中：{'、'.join(hits)}")
        if e.get("_full_hit"):
            print(f"   全文片段：{e['_full_hit']}")
        for p in (e.get("prompts") or [])[:2]:
            print(f"   · {clip(p, 150)}")
        print(f"   id={e['id']}")
        print()

    print("复用：recall.py show <id> 展开该会话；或由模型吸收其结论后直接开工。")
    return 0


# ---------------------------------------------------------------- 展开

def cmd_show(args) -> int:
    if not gate_allows(args):
        return 3
    idx = load_index()
    entry = idx["sessions"].get(args.session_id)
    path = Path(entry["path"]) if entry else None
    if not path or not path.exists():
        hits = [e for k, e in idx["sessions"].items() if k.startswith(args.session_id)]
        if len(hits) == 1:
            entry = hits[0]
            path = Path(entry["path"])
        else:
            print(f"[!] 找不到会话：{args.session_id}", file=sys.stderr)
            return 4

    if path.suffix.lower() == ".md":
        # raw 快照：已经清洗、已脱敏，直接展开即可
        print(path.read_text(encoding="utf-8", errors="replace"))
        return 0

    users: list[str] = []
    assistants: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("type") != "message":
                continue
            role = (rec.get("role") or "").lower()
            txt = clean_user_text(extract_content(rec))
            if len(txt) < 2:
                continue
            if role == "user":
                users.append(txt)
            elif role == "assistant" and len(txt) > 40:
                assistants.append(txt)

    print(f"# {entry.get('title') or '(无标题)'}")
    print(f"id={entry['id']}｜{time.strftime('%Y-%m-%d %H:%M', time.localtime(entry.get('end') or 0))}"
          f"｜{entry.get('msgs', 0)} 条消息｜{entry.get('cwd') or ''}\n")

    print(f"## 用户请求（{len(users)} 条，展示前 {args.max_user} 条）")
    for i, u in enumerate(users[: args.max_user], 1):
        print(f"{i}. {clip(u, 260)}")
    print()

    print(f"## 助手结论（末 {args.max_asst} 条）")
    for a in assistants[-args.max_asst:]:
        print(f"- {clip(a, 600)}")
    print()
    return 0


# ---------------------------------------------------------------- 启动自检

def gate_allows(args) -> bool:
    """gate 为 dormant 时，检索/展开一律拒绝——防止模型忽略 SKILL.md 白花钱。

    只用 CPU 的建索引不受影响：语料必须在休眠期继续长大，否则永远醒不过来。
    """
    if getattr(args, "force_gate", False):
        return True
    try:
        g = json.loads(GATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return True
    if g.get("status") != "dormant":
        return True
    print(f"[休眠] {g.get('reason') or '语料还不够，暂不启用'}", file=sys.stderr)
    print("       继续正常对话即可；每次会话结束会自动积累，够本后自动启用。", file=sys.stderr)
    return False


# ---------------------------------------------------------------- 概览

def cmd_stats(args) -> int:
    idx = load_index()
    sessions = list(idx["sessions"].values())
    if not sessions:
        print("索引为空，请先运行：recall.py index")
        return 0
    built = idx.get("built", 0)
    spans = sorted(s.get("end") or 0 for s in sessions)
    cwds: dict[str, int] = {}
    for s in sessions:
        key = (s.get("cwd") or s.get("slug") or "?").replace("\\", "/")
        cwds[key] = cwds.get(key, 0) + 1
    print(f"会话总数：{len(sessions)}")
    print(f"索引构建：{time.strftime('%Y-%m-%d %H:%M', time.localtime(built))}")
    print(f"时间跨度：{time.strftime('%Y-%m-%d', time.localtime(spans[0]))} ~ "
          f"{time.strftime('%Y-%m-%d', time.localtime(spans[-1]))}")
    print("按工作区分布（前 8）：")
    for k, v in sorted(cwds.items(), key=lambda x: -x[1])[:8]:
        print(f"  {v:>3}  {k}")
    return 0


# ---------------------------------------------------------------- 入口

def main() -> int:
    ap = argparse.ArgumentParser(prog="recall.py", description="本地历史对话索引与检索")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="增量刷新索引")
    p.add_argument("--force", action="store_true", help="忽略缓存，全量重建")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("search", help="关键词检索")
    p.add_argument("keywords", nargs="?", default="", help="关键词，空格分隔，多词按覆盖度加权")
    p.add_argument("--since", help="时间下限，如 7d / 4w / 2026-10-01")
    p.add_argument("--cwd", help="限定工作区路径片段")
    p.add_argument("--limit", type=int, default=5, help="返回条数，默认 5")
    p.add_argument("--full", action="store_true", help="索引未命中时回扫全文（较慢）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--force-gate", action="store_true", help="跳过启动自检，强制检索")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("show", help="展开会话内容")
    p.add_argument("session_id")
    p.add_argument("--max-user", type=int, default=12)
    p.add_argument("--max-asst", type=int, default=2)
    p.add_argument("--force-gate", action="store_true", help="跳过启动自检，强制展开")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("stats", help="索引概览")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
