#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adapters.py — 各 AI 客户端转录的解析适配层。

Super Larder 不绑定任何一家客户端。适配器只负责一件事：把各家的原始转录
翻成统一结构；清洗、抽词、脱敏、聚类全部留在 build.py，保证只有一处规则。

统一结构：
    {id, title, cwd, start, end, msgs, prompts[], asst[], agent, path, bytes}

显式适配（有专人维护）：
    codex      Codex CLI / Desktop         ~/.codex/sessions/**/rollout-*.jsonl
    codex_db   Codex Desktop 实时线程      ~/.codex/thread_history_1.sqlite
    claude     Claude Code                 ~/.claude/projects/<slug>/<uuid>.jsonl
    gemini     Gemini CLI                  ~/.gemini/tmp/<proj>/chats/*.json
    qwen       Qwen Code / iFlow CLI       ~/.qwen/tmp、~/.iflow/tmp（Gemini 格式）
    workbuddy  WorkBuddy / CodeBuddy       ~/.workbuddy|~/.codebuddy/projects/...
    copilot    GitHub Copilot Chat         .../User/workspaceStorage/*/chatSessions/*.json
    cline      Cline / Roo Code            .../tasks/*/api_conversation_history.json
    continue   Continue                    ~/.continue/sessions/*.json
    opencode   OpenCode                    ~/.local/share/opencode/storage/message/<sid>/*
    chatgpt    ChatGPT 官方导出            conversations.json
    aider      aider 历史                  .aider.chat.history.md

通用兜底（generic）：
    任何 JSONL/JSON，只要记录里带 role/content。认不出格式也不丢，按角色启发式抽取。

新增客户端：写一个 parse_xxx(path) 并登记到 ADAPTERS，其余不用动。

自检：直接运行本文件（python3 scripts/adapters.py）会列出本机识别到的
客户端、路径和会话数，不生成知识库、不调用模型。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

HOME = Path.home()

# ---------------------------------------------------------------- 时间

def _ts(v):
    """任意时间表示 → epoch 秒。失败返回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if abs(float(v)) > 1e11 else float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if s.isdigit():
            n = float(s)
            return n / 1000.0 if n > 1e11 else n
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    return None


# ---------------------------------------------------------------- 正文

_TOOL_BLOCK = {"tool_use", "tool_result", "function_call", "function_call_output",
               "reasoning", "thinking", "redacted_thinking", "image", "input_image"}


def blocks_text(content) -> str:
    """把各家五花八门的 content 结构压成纯文本。

    工具调用/工具输出一律丢弃——它们占原始体积九成，且是主题词的主要污染源。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    out: list[str] = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, str):
                out.append(b)
            elif isinstance(b, dict):
                t = b.get("type")
                if t in _TOOL_BLOCK:
                    continue
                v = b.get("text")
                if isinstance(v, str):
                    out.append(v)
    elif isinstance(content, dict):
        t = content.get("type")
        if t not in _TOOL_BLOCK:
            v = content.get("text") or content.get("content")
            if isinstance(v, str):
                out.append(v)
    return "\n".join(out)


def _mk(path: Path, agent: str, sid: str, title: str, cwd: str,
        prompts: list[str], asst: list[str], start, end, msgs: int) -> dict | None:
    if start is None and not prompts and not title:
        return None
    if start is None:
        start = end = path.stat().st_mtime
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "id": sid or path.stem,
        "title": (title or "").strip(),
        "title_src": "agent" if (title or "").strip() else "",
        "cwd": cwd or "",
        "start": float(start),
        "end": float(end or start),
        "msgs": msgs,
        "prompts": [p for p in prompts if isinstance(p, str) and p.strip()],
        "asst": [a for a in asst if isinstance(a, str) and a.strip()],
        "agent": agent,
        "path": str(path),
        "bytes": size,
    }


def _is_boiler(text: str) -> bool:
    """客户端注入的上下文块（不是用户说的话）。各家的标签不同，统一在这里挡掉。"""
    if not text:
        return True
    head = text.lstrip()[:200]
    marks = ("<app-context>", "<user_info>", "<identity_context>", "<project_context>",
             "<environment_context>", "<codex_apps_client_time_context>", "<permissions",
             "<collaboration_mode>", "# AGENTS.md instructions")
    return head.startswith(marks)


# ---------------------------------------------------------------- 各客户端

_CODEX_ID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


def parse_codex(path: Path) -> dict | None:
    sid = path.stem
    m = _CODEX_ID.search(path.name)
    if m:
        sid = m.group(1)
    title = cwd = ""
    prompts: list[str] = []
    asst: list[str] = []
    start = end = None
    n = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            # 预筛：九成是 token_count / function_call_output，不值得解析
            if ('"response_item"' not in line and '"session_meta"' not in line
                    and '"user_message"' not in line):
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            ts = _ts(rec.get("timestamp"))
            if ts is not None:
                start = ts if start is None else min(start, ts)
                end = ts if end is None else max(end, ts)
            t = rec.get("type")
            p = rec.get("payload") or {}
            if not isinstance(p, dict):
                continue
            if t == "session_meta":
                cwd = p.get("cwd") or cwd
                sid = p.get("session_id") or p.get("id") or sid
            elif t == "event_msg" and p.get("type") == "user_message":
                txt = p.get("message") or p.get("text") or ""
                if isinstance(txt, str) and txt.strip() and not _is_boiler(txt):
                    prompts.append(txt)
                    n += 1
            elif t == "response_item" and p.get("type") == "message":
                role = (p.get("role") or "").lower()
                if role not in ("user", "assistant"):
                    continue          # developer/system 注入块不算对话
                txt = blocks_text(p.get("content"))
                if not txt.strip() or _is_boiler(txt):
                    continue
                n += 1
                (prompts if role == "user" else asst).append(txt)
    return _mk(path, "codex", sid, title, cwd, prompts, asst, start, end, n)


def parse_claude(path: Path) -> dict | None:
    sid = path.stem
    title = cwd = ""
    prompts: list[str] = []
    asst: list[str] = []
    start = end = None
    n = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            t = rec.get("type")
            ts = _ts(rec.get("timestamp"))
            if ts is not None:
                start = ts if start is None else min(start, ts)
                end = ts if end is None else max(end, ts)
            sid = rec.get("sessionId") or sid
            cwd = rec.get("cwd") or cwd
            if t == "summary":
                if not title and isinstance(rec.get("summary"), str):
                    title = rec["summary"]
                continue
            if t not in ("user", "assistant"):
                continue
            if rec.get("isSidechain"):
                continue              # 子代理对话，不是主会话
            msg = rec.get("message") or {}
            if not isinstance(msg, dict):
                continue
            role = (msg.get("role") or t).lower()
            if role not in ("user", "assistant"):
                continue
            txt = blocks_text(msg.get("content"))
            if not txt.strip() or _is_boiler(txt):
                continue
            n += 1
            (prompts if role == "user" else asst).append(txt)
    return _mk(path, "claude", sid, title, cwd, prompts, asst, start, end, n)


def parse_gemini(path: Path) -> dict | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    msgs = obj.get("messages") or obj.get("history") or []
    if not isinstance(msgs, list):
        return None
    sid = obj.get("sessionId") or obj.get("session_id") or path.stem
    base = _ts(obj.get("startTime")) or _ts(obj.get("start_time"))
    prompts: list[str] = []
    asst: list[str] = []
    start = end = base
    n = 0
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = (m.get("type") or m.get("role") or "").lower()
        ts = _ts(m.get("timestamp")) or base
        if ts is not None:
            start = ts if start is None else min(start, ts)
            end = ts if end is None else max(end, ts)
        txt = blocks_text(m.get("content") or m.get("text"))
        if not txt.strip() or _is_boiler(txt):
            continue
        if role in ("user", "human"):
            prompts.append(txt)
            n += 1
        elif role in ("gemini", "model", "assistant"):
            asst.append(txt)
            n += 1
    return _mk(path, "gemini", sid, "", "", prompts, asst, start, end, n)


def parse_workbuddy(path: Path) -> dict | None:
    sid = path.stem
    title = cwd = ""
    prompts: list[str] = []
    asst: list[str] = []
    start = end = None
    n = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if ('"type":"message"' not in line and '"type": "message"' not in line
                    and '"ai-title"' not in line and '"session-meta"' not in line):
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            ts = _ts(rec.get("timestamp"))
            if ts is not None:
                start = ts if start is None else min(start, ts)
                end = ts if end is None else max(end, ts)
            sid = rec.get("sessionId") or sid
            t = rec.get("type")
            if t == "ai-title":
                v = rec.get("aiTitle")
                if isinstance(v, str) and v.strip():
                    title = v.strip()
                continue
            if t == "session-meta":
                meta = rec.get("meta") or {}
                if isinstance(meta, dict):
                    cwd = meta.get("cwd") or cwd
                continue
            if t != "message":
                continue
            role = (rec.get("role") or "").lower()
            if role not in ("user", "assistant"):
                continue
            cwd = rec.get("cwd") or cwd
            txt = blocks_text(rec.get("content") or rec.get("text"))
            if not txt.strip() or _is_boiler(txt):
                continue
            n += 1
            (prompts if role == "user" else asst).append(txt)
    return _mk(path, "workbuddy", sid, title, cwd, prompts, asst, start, end, n)


# ---------------------------------------------------------------- 更多原生格式

def _json_load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def parse_copilot(path: Path) -> dict | None:
    """VS Code / Cursor / Windsurf 的 Copilot Chat 会话。

    形状：{"version":3,"responderUsername":"GitHub Copilot",
           "requests":[{"message":{"text":...},"response":[{"value":...}]}]}
    """
    obj = _json_load(path)
    if not isinstance(obj, dict):
        return None
    reqs = obj.get("requests")
    if not isinstance(reqs, list):
        return None
    prompts: list[str] = []
    asst: list[str] = []
    start = end = None
    n = 0
    for r in reqs:
        if not isinstance(r, dict):
            continue
        ts = _ts(r.get("timestamp")) or _ts(r.get("creationDate"))
        if ts is not None:
            start = ts if start is None else min(start, ts)
            end = ts if end is None else max(end, ts)
        msg = r.get("message")
        text = msg.get("text") if isinstance(msg, dict) else None
        if isinstance(text, str) and text.strip() and not _is_boiler(text):
            prompts.append(text)
            n += 1
        resp = r.get("response")
        if isinstance(resp, list):
            buf = []
            for it in resp:
                if not isinstance(it, dict):
                    continue
                v = it.get("value")
                if not isinstance(v, str):
                    v = blocks_text(it.get("content"))
                if isinstance(v, str) and v.strip():
                    buf.append(v)
            if buf:
                asst.append("\n".join(buf))
                n += 1
    title = obj.get("customTitle") or obj.get("title") or ""
    return _mk(path, "copilot", str(obj.get("sessionId") or path.stem),
               title if isinstance(title, str) else "", "",
               prompts, asst, start, end, n)


def _chatgpt_conv(conv: dict, path: Path) -> dict | None:
    mapping = conv.get("mapping")
    if not isinstance(mapping, dict):
        return None
    nodes = [v for v in mapping.values() if isinstance(v, dict)]
    nodes.sort(key=lambda x: _ts((x.get("message") or {}).get("create_time")) or 0)
    prompts: list[str] = []
    asst: list[str] = []
    start = end = None
    n = 0
    for node in nodes:
        m = node.get("message")
        if not isinstance(m, dict):
            continue
        role = ((m.get("author") or {}).get("role") or "").lower()
        if role not in ("user", "assistant"):
            continue
        c = m.get("content")
        parts = c.get("parts") if isinstance(c, dict) else None
        if isinstance(parts, list):
            txt = "\n".join(p for p in parts if isinstance(p, str))
        else:
            txt = blocks_text(c)
        if not txt.strip() or _is_boiler(txt):
            continue
        ts = _ts(m.get("create_time"))
        if ts is not None:
            start = ts if start is None else min(start, ts)
            end = ts if end is None else max(end, ts)
        n += 1
        (prompts if role == "user" else asst).append(txt)
    title = conv.get("title")
    return _mk(path, "chatgpt", str(conv.get("id") or conv.get("conversation_id") or path.stem),
               title if isinstance(title, str) else "", "",
               prompts, asst, start, end, n)


def parse_chatgpt(path: Path) -> dict | None:
    obj = _json_load(path)
    if isinstance(obj, dict):
        return _chatgpt_conv(obj, path)
    return None


def parse_chatgpt_many(path: Path) -> list[dict]:
    """ChatGPT 官方导出是一个 conversations.json，里面装了几百个会话。"""
    obj = _json_load(path)
    out: list[dict] = []
    if isinstance(obj, list):
        for conv in obj:
            if isinstance(conv, dict):
                got = _chatgpt_conv(conv, path)
                if got:
                    out.append(got)
    elif isinstance(obj, dict):
        got = _chatgpt_conv(obj, path)
        if got:
            out.append(got)
    return out


_AIDER_HDR = re.compile(r"^####\s+(.*)$")


def parse_aider_md(path: Path) -> dict | None:
    """aider 的 .aider.chat.history.md：`#### 用户` 分块，块内首行是提问，其余是回答。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if "aider chat started" not in text[:400].lower():
        return None
    prompts: list[str] = []
    asst: list[str] = []
    n = 0
    cur = None
    buf: list[str] = []

    def flush():
        nonlocal cur, buf, n
        if cur is None:
            return
        body = "\n".join(buf).strip()
        if cur.strip() and not cur.lstrip().startswith("/"):
            prompts.append(cur.strip())
            n += 1
            if body:
                asst.append(body)
                n += 1
        cur, buf = None, []

    for line in text.splitlines():
        m = _AIDER_HDR.match(line)
        if m:
            flush()
            cur = m.group(1)
            continue
        if cur is not None:
            buf.append(line)
    flush()
    if not prompts:
        return None
    mtime = path.stat().st_mtime
    return _mk(path, "aider", path.stem, "", "", prompts, asst, mtime, mtime, n)


def parse_continue(path: Path) -> dict | None:
    """Continue 的 sessions/*.json：{sessionId,title,history:[{message:{role,content}}]}"""
    got = parse_generic(path)
    if not got:
        return None
    obj = _json_load(path)
    if isinstance(obj, dict):
        got["agent"] = "continue"
        if not got.get("title") and isinstance(obj.get("title"), str):
            got["title"] = obj["title"].strip()
            got["title_src"] = "agent" if got["title"] else ""
        got["id"] = str(obj.get("sessionId") or obj.get("id") or got["id"])
    return got


def parse_cline(path: Path) -> dict | None:
    """Cline / Roo Code 的 tasks/<id>/api_conversation_history.json"""
    got = parse_generic(path)
    if not got:
        return None
    got["agent"] = "cline"
    got["id"] = path.parent.name or got["id"]
    return got


def parse_opencode_dir(root: Path) -> list[dict]:
    """OpenCode：storage/message/<sessionID>/<msgID>.json，一个文件一条消息。

    root 传 storage/message；标题在 storage/session/**/<id>.json。
    """
    out: list[dict] = []
    if not root.is_dir():
        return out
    titles: dict[str, str] = {}
    sess_root = root.parent / "session"
    if sess_root.is_dir():
        for f in sess_root.rglob("*.json"):
            o = _json_load(f)
            if isinstance(o, dict) and o.get("id") and isinstance(o.get("title"), str):
                titles[str(o["id"])] = o["title"]
    for sd in sorted(p for p in root.iterdir() if p.is_dir()):
        prompts: list[str] = []
        asst: list[str] = []
        start = end = None
        n = 0
        cwd = ""
        for f in sorted(sd.glob("*.json")):
            o = _json_load(f)
            if not isinstance(o, dict):
                continue
            role = (o.get("role") or "").lower()
            if role not in ("user", "assistant"):
                continue
            txt = ""
            parts = o.get("parts")
            if isinstance(parts, list):
                txt = "\n".join(p.get("text", "") for p in parts
                                 if isinstance(p, dict) and p.get("type") == "text")
            if not txt.strip():
                txt = blocks_text(o.get("content"))
            if not txt.strip() or _is_boiler(txt):
                continue
            tm = o.get("time")
            ts = _ts(tm.get("created")) if isinstance(tm, dict) else None
            if ts is not None:
                start = ts if start is None else min(start, ts)
                end = ts if end is None else max(end, ts)
            path_meta = o.get("path")
            if isinstance(path_meta, dict) and path_meta.get("cwd"):
                cwd = str(path_meta["cwd"])
            n += 1
            (prompts if role == "user" else asst).append(txt)
        if n:
            rec = _mk(sd / "messages.jsonl", "opencode", sd.name,
                      titles.get(sd.name, ""), cwd, prompts, asst, start, end, n)
            if rec:
                rec["path"] = str(sd)
                out.append(rec)
    return out


# ---------------------------------------------------------------- 通用兜底

_ROLE_KEYS = ("role", "sender", "author", "from")
_TEXT_KEYS = ("content", "text", "message", "body", "value")
_USER_ROLES = {"user", "human", "me", "client"}
_AI_ROLES = {"assistant", "ai", "model", "gemini", "bot", "agent", "completion"}


def _generic_record(rec: dict):
    """从一条任意记录里抽出 (role, text, epoch)。返回 None 表示不是对话消息。"""
    # 嵌套一层是最常见的形态：{"message": {"role": "user", "content": "..."}}
    for holder in (rec, rec.get("message") if isinstance(rec.get("message"), dict) else None,
                   rec.get("payload") if isinstance(rec.get("payload"), dict) else None):
        if not isinstance(holder, dict):
            continue
        role = ""
        for k in _ROLE_KEYS:
            v = holder.get(k)
            if isinstance(v, str) and v.lower() in (_USER_ROLES | _AI_ROLES):
                role = v.lower()
                break
        if not role:
            continue
        text = ""
        for k in _TEXT_KEYS:
            if k in holder:
                text = blocks_text(holder.get(k))
                if text.strip():
                    break
        if not text.strip():
            continue
        ts = None
        for k in ("timestamp", "created_at", "createdAt", "time", "date"):
            ts = _ts(holder.get(k)) or _ts(rec.get(k))
            if ts is not None:
                break
        return role, text, ts
    return None


def parse_generic(path: Path) -> dict | None:
    prompts: list[str] = []
    asst: list[str] = []
    start = end = None
    n = 0
    if path.suffix.lower() == ".json":
        try:
            obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return None
        seq = obj if isinstance(obj, list) else (
            obj.get("messages") or obj.get("history") or obj.get("conversation") or [])
        if not isinstance(seq, list):
            return None
    else:
        seq = []
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    seq.append(rec)
    for rec in seq:
        if not isinstance(rec, dict):
            continue
        got = _generic_record(rec)
        if not got:
            continue
        role, text, ts = got
        if _is_boiler(text):
            continue
        if ts is not None:
            start = ts if start is None else min(start, ts)
            end = ts if end is None else max(end, ts)
        n += 1
        (prompts if role in _USER_ROLES else asst).append(text)
    return _mk(path, "generic", path.stem, "", "", prompts, asst, start, end, n)


# ---------------------------------------------------------------- Codex 实时库
# Codex Desktop 的进行中会话不落 rollout 文件，而在 SQLite 里：
#   ~/.codex/thread_history_1.sqlite   thread_items(item_json)  ← 正文
#   ~/.codex/sqlite/codex.db           local_thread_catalog     ← 标题/cwd
# 不接这个库，今天正在聊的内容就永远进不了知识库。

def _codex_catalog(db_path: Path) -> dict:
    import sqlite3
    cand = db_path.parent / "sqlite" / "codex.db"
    if not cand.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{cand}?mode=ro", uri=True, timeout=2)
        try:
            rows = con.execute(
                "select thread_id, display_title, cwd from local_thread_catalog").fetchall()
        finally:
            con.close()
    except Exception:
        return {}
    return {r[0]: {"title": r[1] or "", "cwd": r[2] or ""} for r in rows if r and r[0]}


def parse_codex_db(path: Path) -> list[dict]:
    import sqlite3
    out: list[dict] = []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    except Exception:
        return out
    catalog = _codex_catalog(path)
    try:
        rows = con.execute(
            "select thread_id, item_type, created_at_ms, item_json from thread_items "
            "where item_type in ('userMessage','agentMessage') "
            "order by thread_id, rollout_ordinal").fetchall()
    except Exception:
        con.close()
        return out
    con.close()

    acc: dict[str, dict] = {}
    for tid, itype, ts_ms, blob in rows:
        if not tid or not blob:
            continue
        try:
            item = json.loads(blob)
        except Exception:
            continue
        if not isinstance(item, dict):
            continue
        txt = blocks_text(item.get("content"))
        if not txt.strip() or _is_boiler(txt):
            continue
        a = acc.setdefault(tid, {"prompts": [], "asst": [], "start": None, "end": None, "n": 0})
        ts = _ts(ts_ms)
        if ts is not None:
            a["start"] = ts if a["start"] is None else min(a["start"], ts)
            a["end"] = ts if a["end"] is None else max(a["end"], ts)
        a["n"] += 1
        if itype == "userMessage":
            a["prompts"].append(txt)
        else:
            a["asst"].append(txt)

    for tid, a in acc.items():
        meta = catalog.get(tid, {})
        rec = _mk(path, "codex", tid, meta.get("title", ""), meta.get("cwd", ""),
                  a["prompts"], a["asst"], a["start"], a["end"], a["n"])
        if rec:
            rec["bytes"] = 0          # 数据库来源不按文件计大小
            out.append(rec)
    return out


# ---------------------------------------------------------------- 分发

ADAPTERS = {
    "codex": parse_codex,
    "claude": parse_claude,
    "gemini": parse_gemini,
    "qwen": parse_gemini,
    "workbuddy": parse_workbuddy,
    "copilot": parse_copilot,
    "chatgpt": parse_chatgpt,
    "aider": parse_aider_md,
    "continue": parse_continue,
    "cline": parse_cline,
    "generic": parse_generic,
}


def sniff(path: Path) -> str:
    """按内容判断格式，不依赖路径。判不出就 generic。"""
    if path.suffix.lower() in (".sqlite", ".db"):
        return "codex"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(65536)
    except OSError:
        return "generic"
    if path.suffix.lower() in (".md", ".markdown"):
        if "aider" in path.name.lower() or "aider chat started" in head[:400].lower():
            return "aider"
        return "generic"
    if path.name == "api_conversation_history.json":
        return "cline"
    if path.name == "session.json" and ".continue" in str(path):
        return "continue"
    if path.suffix.lower() == ".json":
        if '"responderUsername"' in head or ('"requests"' in head and '"response"' in head):
            return "copilot"
        if '"mapping"' in head and '"create_time"' in head:
            return "chatgpt"
        if '"sessionId"' in head and '"history"' in head:
            return "continue"
        if '"messages"' in head or '"history"' in head:
            return "gemini"
        return "generic"
    if '"session_meta"' in head or '"response_item"' in head:
        return "codex"
    if '"ai-title"' in head or '"session-meta"' in head:
        return "workbuddy"
    if re.search(r'"type"\s*:\s*"(user|assistant|summary|system)"', head) and '"sessionId"' in head:
        return "claude"
    if '"type":"message"' in head or '"type": "message"' in head:
        return "workbuddy"
    return "generic"


def agent_of(path: Path) -> str:
    """文件看内容，目录当 OpenCode 消息库。"""
    if path.is_dir():
        return "opencode"
    return sniff(path)


def iter_sessions(path: Path) -> list[dict]:
    """一个路径可能承载多个会话（SQLite / 目录 / 导出包），统一从这进。"""
    if path.is_dir():
        return parse_opencode_dir(path)
    if path.suffix.lower() in (".sqlite", ".db"):
        if "thread_history" in path.name:
            return parse_codex_db(path)
        return []
    if path.suffix.lower() == ".json" and agent_of(path) == "chatgpt":
        return parse_chatgpt_many(path)
    s = parse(path)
    return [s] if s else []


def parse(path: Path) -> dict | None:
    agent = sniff(path)
    fn = ADAPTERS.get(agent) or parse_generic
    try:
        s = fn(path)
    except Exception:
        return None
    if not s:
        return None
    if not s.get("prompts") and not s.get("title"):
        return None
    return s


# ---------------------------------------------------------------- 发现

DEFAULT_DBS = [
    ("codex", HOME / ".codex" / "thread_history_1.sqlite"),
]

# 无 native 适配、但格式通用（JSON/JSONL 里带 role+content）的客户端，走 generic 兜底
DEFAULT_ROOTS = [
    ("codex", HOME / ".codex" / "sessions"),
    ("claude", HOME / ".claude" / "projects"),
    ("gemini", HOME / ".gemini" / "tmp"),
    ("qwen", HOME / ".qwen" / "tmp"),          # Qwen Code（Gemini CLI 分支）
    ("qwen", HOME / ".iflow" / "tmp"),         # iFlow CLI
    ("workbuddy", HOME / ".workbuddy" / "projects"),
    ("workbuddy", HOME / ".codebuddy" / "projects"),
    ("continue", HOME / ".continue" / "sessions"),
    ("opencode", HOME / ".local" / "share" / "opencode" / "storage"),
]

# VS Code 系编辑器里的 AI 插件（Cline / Roo Code / Copilot Chat）
_VSCODE_APPS = ("Code", "Code - Insiders", "Cursor", "Windsurf", "VSCodium",
                "Trae", "Qoder", "Kiro")
_EDITOR_BASES = [HOME / "Library" / "Application Support", HOME / ".config"]
for _base in _EDITOR_BASES:
    for _app in _VSCODE_APPS:
        DEFAULT_ROOTS.append(
            ("cline", _base / _app / "User" / "globalStorage"
             / "saoudrizwan.claude-dev" / "tasks"))
        DEFAULT_ROOTS.append(("copilot", _base / _app / "User" / "workspaceStorage"))
del _base, _app

# generic 遍历时要跳过的非对话文件
_JUNK_NAMES = {"package.json", "package-lock.json", "tsconfig.json", "settings.json",
               "keybindings.json", "composer.json", "manifest.json", ".eslintrc.json",
               "launch.json", "tasks.json", "extensions.json", "argv.json"}


def _walk_generic(root: Path) -> list[Path]:
    """受控深度遍历：只收 jsonl/json/md，跳过体积大户和非对话配置。"""
    out: list[Path] = []
    for pat in ("**/*.jsonl", "**/*.json", "**/*.md"):
        for f in root.glob(pat):
            try:
                rel = f.relative_to(root)
                if len(rel.parts) > 4 or f.name in _JUNK_NAMES:
                    continue
                sz = f.stat().st_size
            except OSError:
                continue
            limit = 64 * 1024 * 1024 if f.suffix.lower() == ".jsonl" else 8 * 1024 * 1024
            if sz <= limit:
                out.append(f)
    return sorted(set(out))


def _files_under(root: Path, agent: str) -> list[Path]:
    """先按客户端惯例精确匹配；一个都没匹配到就退回通用遍历。

    精确匹配是为了在成千上万个文件里少扫；退回遍历是为了「用户自己指定了一个
    目录」时不至于空手而归——格式仍由 sniff() 按内容判断。
    """
    if not root.exists():
        return []
    if root.is_file():
        return [root]

    got: list[Path] = []
    if agent in ("gemini", "qwen"):
        got = sorted(root.glob("*/chats/*.json"))
    elif agent == "codex":
        got = sorted(root.glob("**/rollout-*.jsonl"))
    elif agent == "claude":
        got = sorted(root.glob("**/*.jsonl"))
    elif agent == "workbuddy":
        got = sorted(root.glob("*/*.jsonl"))
    elif agent == "cline":
        got = sorted(root.glob("*/api_conversation_history.json"))
    elif agent == "copilot":
        got = sorted(root.glob("*/chatSessions/*.json"))
    elif agent == "continue":
        got = sorted(root.glob("*.json")) + sorted(root.glob("*/session.json"))
    elif agent == "opencode":
        msg = root / "message"
        got = [msg] if msg.is_dir() else []
    return got or _walk_generic(root)


def discover(extra: list[dict] | None = None, use_defaults: bool = True) -> list[dict]:
    """返回 [{agent, root, files}]。

    extra 里可以写 {"agent": "generic", "root": "/path/to/transcripts"}，
    让任何自研 agent 都能接进来，不用改代码。
    """
    out: list[dict] = []
    seen_roots: set[str] = set()

    def add(agent: str, root: Path):
        root = root.expanduser()
        key = f"{agent}:{root}"
        if key in seen_roots:
            return
        seen_roots.add(key)
        files = _files_under(root, agent)
        if files:
            out.append({"agent": agent, "root": str(root), "files": files})

    if use_defaults:
        for agent, root in DEFAULT_ROOTS:
            add(agent, root)
        for agent, db in DEFAULT_DBS:
            add(agent, db)
    for item in (extra or []):
        if not isinstance(item, dict):
            continue
        root = item.get("root")
        if not root:
            continue
        add(str(item.get("agent") or "generic"), Path(str(root)))
    return out


# ---------------------------------------------------------------- 自检 CLI

def probe() -> int:
    """python3 scripts/adapters.py —— 列出本机被识别到的客户端和会话数量。"""
    srcs = discover()
    if not srcs:
        print("没有发现任何可读取的对话转录。")
        print("可手动接入：config.json 里加 "
              '{"sources":[{"agent":"generic","root":"/path/to/your/agent/history"}]}')
        return 1
    total = 0
    print(f"{'客户端':<10} {'会话':>6}  {'路径'}")
    for src in srcs:
        n = 0
        for f in src["files"]:
            try:
                n += len(iter_sessions(f))
            except Exception:
                continue
        total += n
        print(f"{src['agent']:<10} {n:>6}  {src['root']}")
    print(f"\n合计 {total} 个会话，来自 {len(srcs)} 个来源。")
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(probe())
