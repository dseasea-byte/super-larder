#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build.py — 对话库构建流水线（纯 CPU，不调用任何模型）。

设计前提：线上 AI 按 token 计费，本机 CPU 不计费。因此凡是「可机械判定」的环节
全部放在本脚本里：清洗、抽词、聚类、成页、索引、校验。模型只负责审核。

数据源：<WorkBuddyHome>/projects/<工作区>/<会话ID>.jsonl
产出：  <本库>/raw/<YYYY-MM>/<会话ID>.md   清洗后的不可变快照
        <本库>/wiki/<主题>.md               LLM Wiki 风格主题页
        <本库>/index.md                     主题索引
        <本库>/_系统/keywords.json          倒排索引
        <本库>/_系统/log.md                 入库日志

子命令：
  build   [--since 90d] [--force] [--limit N]   全流程构建
  report                                        生成审核报告（给线上 AI 看，≤2KB）
  lint                                          校验生成物合规性
  stats                                         库概览
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ------------------------------------------------------------------ 路径配置
#
# 代码与数据分离：本脚本属于技能包，知识库位置由 config.json / 环境变量决定。
# 取值优先级：CONVO_KB 环境变量 > 技能目录下 config.json 的 kb_root > 默认 ~/.workbuddy/convo-kb

SKILL_DIR = Path(__file__).resolve().parent.parent          # 技能根目录
CONFIG_PATH = Path(os.environ.get("CONVO_RECALL_CONFIG")
                   or (SKILL_DIR / "config.json"))

WB_HOME = Path(os.environ.get("WORKBUDDY_HOME") or (Path.home() / ".workbuddy"))


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


CONFIG = _load_config()


def resolve_kb() -> Path:
    if os.environ.get("CONVO_KB"):
        return Path(os.environ["CONVO_KB"]).expanduser()
    if CONFIG.get("kb_root"):
        return Path(CONFIG["kb_root"]).expanduser()
    return Path.home() / ".super-larder"


LIB = resolve_kb()
RAW = LIB / "raw"
WIKI = LIB / "wiki"
SYS = LIB / "_系统"
INDEX = LIB / "index.md"
KWFILE = SYS / "keywords.json"
LOGFILE = SYS / "log.md"
STATE = SYS / "state.json"        # 已处理会话指纹，用于增量
GATEFILE = SYS / "gate.json"      # 启动自检：语料够不够本
CACHE = SYS / "sessions.json"     # 解析结果缓存：文件没变就不重读 600MB

# 会话转录来源，默认 WorkBuddy 的项目目录
# 兼容旧配置：新版本按 adapters.DEFAULT_ROOTS 自动发现，不再依赖单一目录。
PROJECTS = Path(CONFIG["projects_root"]).expanduser() if CONFIG.get("projects_root") \
    else (WB_HOME / "projects")

GENERATOR = "build.py v1.3"


def load_json(path: Path, default):
    """读取 JSON；文件缺失或损坏一律回退默认值，绝不让后台刷新崩掉。"""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, obj) -> None:
    """原子写：先写临时文件再替换，避免进程中断留下半截 JSON。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

QUIET = False          # --quiet：供技能在对话中静默刷新，不打扰用户


def say(*a) -> None:
    if not QUIET:
        print(*a)


# ------------------------------------------------------------------ 文本清洗

NOISE_TAGS = [
    "system-reminder", "task-notification", "cb_summary", "craft_mode",
    "user_info", "identity_context", "project_context", "connector-status",
    "current_time", "additional-data", "memory", "user_memory",
    "tone_and_style", "product_identity", "available_skills", "working_modes",
    "agent_loop", "result_presentation", "final_answer", "tool_usage_policy",
    "search_routing", "wecom_cli_routing", "project_layout",
]
_BLOCK_RE = re.compile(
    r"<(" + "|".join(re.escape(t) for t in NOISE_TAGS) + r")\b[^>]*>.*?</\1>", re.S | re.I
)
_ORPHAN_RE = re.compile(
    r"</?(?:" + "|".join(re.escape(t) for t in NOISE_TAGS) + r")\b[^>]*>", re.I
)
_USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.S | re.I)
_BOILER_RE = [
    re.compile(r"Use the \w+ tool with .*?(?:act on it|the output)\.?", re.S | re.I),
    re.compile(r"IMPORTANT: Before responding,.*", re.S | re.I),
    re.compile(r"You can now use the \w+ tool.*", re.S | re.I),
    re.compile(r"For background shell tasks,.*", re.S | re.I),
    re.compile(r"\[SYSTEM NOTIFICATION[^\]]*\].*", re.S | re.I),
    re.compile(r"This is an automated background.*", re.S | re.I),
]
_BOILER_HEAD = re.compile(
    r"^(Use the|IMPORTANT|Note:|The following|Tool result|System:|For background|\[SYSTEM|This is an automated)",
    re.I,
)
_CJK = re.compile(r"[\u4e00-\u9fff]")
_WS = re.compile(r"[ \t\u3000]+")
_NL = re.compile(r"\n{2,}")


def norm(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _WS.sub(" ", s)
    return _NL.sub("\n", s).strip()


def clean(raw: str, prefer_query: bool = True) -> str:
    if not raw:
        return ""
    if prefer_query:
        m = _USER_QUERY_RE.search(raw)
        if m:
            return norm(m.group(1))
    t = _BLOCK_RE.sub(" ", raw)
    t = _ORPHAN_RE.sub(" ", t)
    for p in _BOILER_RE:
        t = p.sub(" ", t)
    t = norm(t)
    if not t:
        return ""
    if _BOILER_HEAD.match(t[:40]) and len(_CJK.findall(t)) < 3:
        return ""
    if len(t.strip(" .,:;!?-_=*#>|/\\\n")) < 2:
        return ""
    return t


def content_text(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for b in c:
            if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text"):
                t = b.get("text")
                if isinstance(t, str):
                    out.append(t)
        return "\n".join(out)
    return ""


# ------------------------------------------------------------------ 词表

# 中文高频虚词与泛动词：出现即判为无区分度
STOP_CN = set("""
的 了 是 在 我 你 他 她 它 们 和 与 及 或 对 从 到 把 被 让 给 就 都 也 还 很 更 最 不 没 要 会 能 可 以
这 那 哪 些 个 上 下 中 前 后 内 外 时 候 问 题 方 法 东 西 一 样 知 道 觉 得 应 该 需 要 做 用 说 看 想
如 果 但 而 且 所 因 为 之 于 其 此 该 各 每 某 些 什 么 怎 么 怎 样 为 何 哪 里 这 里 那 里 现 在 已 经
可 是 但 是 然 后 接 着 另 外 此 外 例 如 比 如 一 般 通 常 大 概 可 能 也 许 应 当 必 须 一 定 需 求
已 未 将 曾 正 刚 才 又 再 更 加 稍 微 非 常 十 分 特 别 极 其 相 当 比 较 较 为 略 微 几 乎 差 不 多
做 好 弄 搞 整 处 理 完 成 实 现 进 行 开 始 结 束 出 现 发 生 存 在 属 于 包 含 具 有 拥 有 使 用 采 用
我 们 你 们 他 们 自 己 本 人 大 家 各 位 诸 位 有 的 地 得 着 过 呢 吗 吧 啊 呀 哦 嗯 啦 哈
""".split())

# 常见双字泛词，避免「可以」「这样」类误入主题
STOP_BIGRAM = set("""
可以 这样 那样 什么 怎么 为什 么样 一个 一些 一下 一种 一直 一样 这些 那些 哪些 这个 那个 哪个
我们 你们 他们 自己 现在 已经 还是 但是 因为 所以 如果 虽然 然后 而且 并且 或者 不过 只是
没有 不是 就是 也是 都是 还有 以及 关于 对于 由于 通过 根据 按照 依据 除了 包括 其中
问题 方法 方式 情况 内容 部分 方面 时候 地方 东西 事情 结果 原因 影响 作用 意义 价值
需要 应该 必须 可以 能够 进行 使用 采用 实现 完成 处理 提供 支持 包含 属于 存在 出现
这样 那样 怎样 如何 为何 是否 能否 有无 多少 几个 第一 第二 第三 首先 其次 最后 总之
""".split())

STOP_EN = set("""
the and for with that this from have not are was were will can may but you your all any how what
when where which who why use used using get got set put run make made take took give gave
python py md json txt log exe bat cmd ps1 sh js ts html css yaml yml csv xml http https www com
def class import return self true false none null ok yes no id llm ai api url uri sdk cli gui
image images screenshot file folder text code data user system message error test demo final main
index page list item name type size time date value label button input output request response
new old good bad yes one two use used here there this that with from have will can
""".split())


# ---------------------------------------------------------------- 分词（jieba）
# 纯 Python、离线、纯 CPU。n-gram 无法判断哪个窗口才是词（「袋指南品」与「品牌设计」
# 同为四字窗口），必须用词典分词；词性标注再顺带解决「动词当主题名」的问题。

try:
    import logging as _logging
    import jieba
    import jieba.posseg as pseg

    jieba.setLogLevel(_logging.ERROR)
except ImportError:  # pragma: no cover
    print("[!] 缺少 jieba，请先执行：python -m pip install jieba", file=sys.stderr)
    raise SystemExit(2)

# 领域词：不加会导致被切碎或误切
# 领域词：不分词会把「开发板」「小程序」切碎，导致主题名残缺。
# 代码里只放通用词；各人自己的业务词请写进 config.json 的 domain_words，
# 这样升级脚本时自己的词不会被覆盖，也不会有谁的私有词被带进别人的机器。
DOMAIN_WORDS = """
知识库 开发板 小程序 公众号 局域网 模型网关 全息副屏 副屏 八字 排盘 命例 卦象 三视图
直播 线索 退款 成交率 天气时钟 桌面摆件 任务中心 老板看板 员工端
抓取 打包 烧录 固件 串口 编译 部署 迁移 备份 归档
""".split()
DOMAIN_WORDS += [w for w in (CONFIG.get("domain_words") or []) if isinstance(w, str)]
for _w in DOMAIN_WORDS:
    jieba.add_word(_w)

# 允许进入词表的词性：名词类 + 英文 + 专名。动词、形容词、虚词一律排除
KEEP_POS = {"n", "ns", "nt", "nz", "nr", "ng", "l", "i", "eng", "j", "s", "f"}


def terms_of(text: str) -> Counter:
    """分词并只保留名词性词语。返回 词 -> 频次。"""
    c: Counter = Counter()
    if not text:
        return c
    for w, flag in pseg.cut(strip_noise(text)):
        w = w.strip()
        if len(w) < 2:
            continue
        if flag not in KEEP_POS:
            continue
        if w in GENERIC_CN or w in VERB_CN:
            continue
        if w.isascii():
            if len(w) < 3 or w.lower() in STOP_EN:
                continue
        c[w] += 1
    return c


# 脱敏的唯一实现在 redactlib.py —— build 与 recall 共用，避免「一个入口抹了、
# 另一个入口漏了」。实测踩过：recall 的检索索引里存过未脱敏的 API Key。
from redactlib import (collect_secrets, redact, redact_page,  # noqa: E402
                       secrets_clear)

# 结论句标记：出现这些词的句子更可能是可复用结论
CONCL_MARK = (
    "结论", "所以", "因此", "最终", "定稿", "确认", "实测", "决定", "改为", "改用",
    "根因", "原因", "修复", "解决", "踩坑", "不要", "不能用", "必须", "注意",
    "结果是", "验证", "生效", "失败", "报错", "发现", "纠正", "推翻", "作废",
)

# 征询/推销句：即使带了「需要/确认」也不能当结论。`要不要` 含 `不要`、
# `需要先确认` 含 `确认`，靠这个正则前置挡掉。
_OFFER_RE = re.compile(
    r"(?:要不要我|要不要先|需要我|是否需要|需不需要|我可以(?:帮你|为你|继续|先)|"
    r"你希望(?:我)?|请问|请确认|请告诉我|告诉我(?:你|您的)|你可以选择|"
    r"如果你(?:需要|想要|希望)|如需|下一步(?:我)?(?:可以|要不要))"
)

# 可复用产物：路径、版本号、命令、URL
PATH_WIN = re.compile(r"[A-Za-z]:\\[^\s\"'<>|，。；）】]+")
PATH_NIX = re.compile(r"(?:~|/)[\w.\-]+(?:/[\w.\-]+){1,6}")
VER = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")
CMD = re.compile(r"^\s*(?:\$|>|python|pip|npm|git|curl|docker|ssh|powershell|pwsh)\b.*$", re.M)
EN_TOKEN = re.compile(r"\b([A-Za-z][A-Za-z0-9_.\-]{1,30})\b")

# 抽词前必须剥离的噪音：路径、URL、代码、哈希、数字。它们进主题名毫无意义
_STRIP_RES = [
    re.compile(r"```.*?```", re.S),
    re.compile(r"`[^`\n]{1,120}`"),
    re.compile(r"[A-Za-z]:\\[^\s\"'<>|，。；）】]+"),
    re.compile(r"\\\\[\w.\-\\]+"),
    re.compile(r"https?://\S+", re.I),
    re.compile(r"@['\"]?[A-Za-z]:\\[^\s]+"),
    re.compile(r"(?:/[\w.\-]+){2,}/?"),      # /Users/xxx/Library/... 这类 POSIX 绝对路径
    re.compile(r"~/[\w.\-/]+"),
    re.compile(r"\b[0-9a-f]{8,}\b", re.I),
    re.compile(r"\b\w+\.(?:py|js|ts|json|md|txt|log|png|jpg|jpeg|gif|webp|svg|apk|exe|bat|cmd|ps1|sh|yml|yaml|csv|xlsx|docx|pptx|mp4|zip)\b", re.I),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:GB|MB|KB|TB|ms|s|px|mm|cm|kg|g|W|V|A)\b"),
    re.compile(r"\b\d{2,}\b"),
]

# 泛化词：语义上真实，但不足以命名主题
GENERIC_CN = set("""
数据 模型 设备 员工 孩子 指南 板子 系统 文件 时间 内容 功能 方法 方案 问题 需求 项目 页面
界面 布局 图片 视频 文案 文章 代码 程序 软件 硬件 网络 服务 配置 目录 版本 环境 电脑 手机
表格 文档 今天 明天 昨天 现在 一下 一个 这个 那个 什么 怎么 可以 需要 应该 已经 还是
东西 事情 地方 情况 部分 方面 结果 原因 影响 作用 意义 价值 方式 过程 步骤 思路 想法
资料 信息 工作 视图 相关 内容 需求 情况 时候 之后 之前 下面 上面 这里 那里
智能 技能 平台 工具 名字 全体 全部 主体 主线 目标 效果 体验 操作 动作
""".split())

# 动作动词：在标题里高频，但它们是「做什么」不是「关于什么」，不能当主题名
VERB_CN = set("""
查找 查询 查看 检查 检测 检查 安装 创建 新建 建立 控制 显示 统计 制作 生成 更新 设计
配置 修改 删除 添加 优化 测试 打开 关闭 确认 分析 整理 处理 实现 完成 扫描 绘制 打印
询问 了解 注册 适配 清理 计算 对比 比较 修复 排查 搭建 开发 执行 继续 保持 取消 定制
转译 推荐 讨论 评估 落地 迁移 备份 恢复 部署 调试 运行 启动 停止 上传 下载 导入 导出
转换 提取 合并 拆分 替换 重写 改写 精简 扩展 升级 降级 回滚 提交 推送 拉取 克隆
判断 定位 核实 验证 复现 记录 汇总 归纳 补充 说明 介绍 解释 演示 展示 呈现 输出
快速 简单 最简 完整 统一 集中 批量 自动 手动 当前 最新 历史 全部 部分 主要 核心
""".split())

# 英文短名白名单：长度不足 3 但有明确指代
EN_ALLOW = {"ai", "3d", "ui", "os", "pc", "tv", "kb", "ds", "gpt"}


INTERROG = {"是不是", "有没有", "能不能", "可不可以", "要不要", "对不对", "行不行",
            "为什么", "怎么样", "如何", "是否"}


def is_topic_term(t: str, title_df: int) -> bool:
    """判定一个词是否够格当主题名。词性与泛词已在 terms_of 里过滤，这里只补证据门槛。"""
    if not t or len(t) < 2:
        return False
    if t in GENERIC_CN or t in VERB_CN or t in STOP_BIGRAM:
        return False
    if any(ch in t for ch in "啥吗呢吧啊呗嘛么呀啦") or t in INTERROG:
        return False            # 口语与疑问词不作主题名
    if t.endswith(("一下", "一些", "一点", "一样", "时候", "之后", "之前")):
        return False            # 量词/时间后缀，语义为空
    if t.isascii() and not any(c.isupper() for c in t):
        return False            # 全小写英文多为命令或字段
    if len(t) == 2 and title_df < 3:
        return False            # 两字词证据不足时不作锚点
    return True


def strip_noise(text: str) -> str:
    """剥离路径/URL/代码/哈希/数字，只留自然语言。"""
    for r in _STRIP_RES:
        text = r.sub(" ", text)
    return text


# ---------------------------------------------------------------- 会话解析
# 各客户端的格式差异全部收在 adapters.py；这里只保留清洗与统一结构，
# 保证「脱敏/抽词/聚类」只有一套规则，不会因为多接一个客户端就分叉。

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapters  # noqa: E402


def est_tokens(text: str) -> int:
    """粗略 token 估算：中文约 1.5 字/token，英文约 3.8 字符/token。

    不引第三方分词器，因为这里只需要「够用来比较大小」的量级；
    为它引入带模型文件的 tiktoken 不划算。
    """
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    return int(cjk / 1.5 + (len(text) - cjk) / 3.8) + 1


def _clean_raw(raw: dict, path: Path) -> dict | None:
    """把适配器给的原始消息洗干净，并补上派生字段。"""
    prompts: list[str] = []
    for x in raw.get("prompts", []):
        t = clean(x)
        if t and (not prompts or prompts[-1] != t):
            prompts.append(t)
    asst: list[str] = []
    for x in raw.get("asst", []):
        t = clean(x)
        if t:
            asst.append(t)

    title = clean(raw.get("title") or "")
    if not title:
        # 客户端的首条消息常常只有「？」「继续」，挑第一条有实质内容的
        title = next((x[:30] for x in prompts if len(x) >= 8),
                     prompts[0][:30] if prompts else "")
    if not prompts and not title:
        return None

    try:
        st = path.stat()
    except OSError:
        st = None
    return {
        "id": raw["id"],
        "title": title or "(无标题)",
        "cwd": raw.get("cwd") or "",
        "start": raw["start"],
        "end": raw["end"],
        "msgs": raw.get("msgs", 0),
        "prompts": prompts,
        "asst": asst,
        "agent": raw.get("agent", "unknown"),
        "tokens": est_tokens("\n".join(prompts) + "\n" + "\n".join(asst)),
        "mtime": int(st.st_mtime) if st else 0,
        "size": st.st_size if st else 0,
    }


def parse_sessions(path: Path) -> list[dict]:
    """一个来源可能产出多个会话（SQLite 里一个线程一个会话）。"""
    out = []
    for raw in adapters.iter_sessions(path):
        s = _clean_raw(raw, path)
        if s:
            out.append(s)
    return out


def parse_session(path: Path) -> dict | None:
    """单会话入口，保留给外部调用。"""
    got = parse_sessions(path)
    return got[0] if got else None


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；\n])", text)
    return [p.strip() for p in parts if p and p.strip()]


def conclusions(sess: dict, cap: int = 14) -> list[str]:
    """抽取结论句：优先末段助手消息，带标记词的整句原样保留（可溯源）。"""
    out: list[str] = []
    seen = set()
    for msg in reversed(sess["asst"][-4:]):
        for s in sentences(msg):
            s = s.strip(" -·*#>")
            if not (16 <= len(s) <= 220):
                continue
            # 反问句和征求确认不是结论。子串匹配的坑：`要不要` 里含 `不要`、
            # `需要先确认` 里含 `确认`，都能命中下面的标记词，所以必须前置挡掉。
            if s.rstrip().endswith(("？", "?")):
                continue
            if _OFFER_RE.search(s):
                continue
            if not any(m in s for m in CONCL_MARK):
                continue
            key = s[:24]
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= cap:
                return out
    return out


def products(sess: dict, cap: int = 8) -> list[tuple[str, str]]:
    """抽取可复用产物：路径 / 命令 / 版本。"""
    blob = "\n".join(sess["asst"][-6:]) + "\n" + "\n".join(sess["prompts"][:4])
    out: list[tuple[str, str]] = []
    seen = set()
    for m in PATH_WIN.finditer(blob):
        v = m.group(0).rstrip(".,;:）)")
        if len(v) > 8 and v not in seen:
            seen.add(v)
            out.append(("路径", v))
    for m in CMD.finditer(blob):
        v = m.group(0).strip()
        if 4 < len(v) < 160 and v not in seen:
            seen.add(v)
            out.append(("命令", v))
    return out[:cap]


# ------------------------------------------------------------------ 关键词抽取

def select_terms(global_counts: Counter, df: Counter, n_sessions: int,
                 max_terms: int = 4000) -> dict[str, float]:
    """最大 n-gram 选择 + IDF 打分。返回 term -> 全局分值。"""
    # 去掉被更长且频次相近的词覆盖的短词
    keep: dict[str, float] = {}
    items = sorted(global_counts.items(), key=lambda x: (-len(x[0]), -x[1]))
    survivors: list[tuple[str, int]] = []
    for term, cnt in sorted(items, key=lambda x: -x[1]):
        if cnt < 3:
            continue
        covered = False
        for longer, lcnt in survivors:
            if len(longer) > len(term) and term in longer and lcnt >= cnt * 0.55:
                covered = True
                break
        if covered:
            continue
        survivors.append((term, cnt))
        if len(survivors) >= max_terms * 2:
            break

    for term, cnt in survivors:
        d = max(1, df.get(term, 1))
        idf = math.log((n_sessions + 1) / (d + 0.5))
        keep[term] = cnt * max(idf, 0.05)
    return dict(sorted(keep.items(), key=lambda x: -x[1])[:max_terms])


# ------------------------------------------------------------------ 聚类

def cluster_sessions(per_session: dict[str, list[tuple[str, float]]],
                     scores: dict[str, float],
                     title_df: Counter,
                     max_groups: int = 26) -> tuple[list[dict], list[str]]:
    """按「主题词」聚合会话。

    主题词质量 = (出现在标题的次数×4 + 覆盖会话数) × 词长加成。
    标题是模型生成的会话摘要，比正文 n-gram 可信得多，因此标题命中权重最高。
    """
    df: Counter = Counter()
    for terms in per_session.values():
        for t, _ in terms:
            df[t] += 1

    def quality(t: str) -> float:
        td = title_df.get(t, 0)
        d = df.get(t, 0)
        if d < 2:
            return 0.0
        return (td * 4 + d) * math.log(len(t) + 1)

    pool = [(t, quality(t), df.get(t, 0), title_df.get(t, 0)) for t in df]
    pool = [x for x in pool if x[1] > 0 and is_topic_term(x[0], x[3])]
    pool.sort(key=lambda x: (-x[1], -x[3], x[2]))

    assigned: set[str] = set()
    groups: list[dict] = []
    for term, q, d, td in pool:
        if len(groups) >= max_groups:
            break
        if d > 14:          # 覆盖过广的词不配当主题名
            continue
        members = [sid for sid in per_session
                   if sid not in assigned and any(t == term for t, _ in per_session[sid])]
        if len(members) < 2:
            continue
        assigned.update(members)
        groups.append({"anchor": term, "score": q, "sessions": members})

    leftovers = [sid for sid in per_session if sid not in assigned]
    return groups, leftovers


# ------------------------------------------------------------------ 渲染

def slugify(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", s.strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s or "未命名")[:40]


def ymd(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


# 「读整页 vs 读原文」的判据：页的大小 / 它替代掉的原文大小。
# 覆盖原文远大于页 -> 读页划算；反之读页纯亏，应直接 grep 命中行或看原文。
_READ_RATIO = 1.5


# 页面的绝对成本上限：再划算也不该让模型读一个几万 token 的页。
# 只按「覆盖/本页」比值判断会随语料增长失效——300 个会话的月档页照样标 page。
MAX_PAGE_TOKENS = int((CONFIG.get("read_hint") or {}).get("max_page_tokens", 6000))


def _covered_chars(group, sessions_) -> int:
    return sum(sessions_[x].get("_raw_chars", 0) for x in group["sessions"])


def _covered_tokens(group, sessions_) -> int:
    return sum(sessions_[x].get("tokens", 0) for x in group["sessions"])


def _hint_by_tokens(page_tokens: int, covered_tokens: int, n_sessions: int = 0) -> str:
    if page_tokens > MAX_PAGE_TOKENS:
        return "grep"          # 绝对上限：页太大，读整页一定亏
    # 稀释判据：一个页里塞了十几个会话，说明它是个「索引」，不是「答案」。
    # 此时读整页＝为了两行答案读三十段，先看命中行即可。
    if n_sessions >= 12 and page_tokens > 2500:
        return "either"
    if covered_tokens >= page_tokens * _READ_RATIO:
        return "page"          # 覆盖原文远超本页，读整页稳赚
    if covered_tokens < page_tokens:
        return "grep"          # 本页比原文还大，只取命中行
    return "either"


def _yaml_head(title: str, date: str, tags: list[str], ents: list[str],
               n_sessions: int, body: str, covered_chars: int, covered_tokens: int) -> list[str]:
    """先渲染正文、再量长度写进 YAML。

    早期版本用「估算」填 payload_chars，结果与实际差到 7.6 倍，
    而 read_hint 建立在这个数上——判据直接失真。现在一律实测。
    """
    ptok = est_tokens(body)
    return [
        "---",
        f"title: {title}",
        f"date: {date}",
        "type: synthesis",
        f"tags: [{', '.join(_uniq(tags))}]",
        f"entities: [{', '.join(_uniq(ents)[:6])}]",
        "status: active",
        "confidence: high",
        "relations: []",
        f"generated_by: {GENERATOR}",
        f"source_sessions: {n_sessions}",
        f"payload_chars: {len(body)}",
        f"payload_tokens: {ptok}",
        f"covered_chars: {covered_chars}",
        f"covered_tokens: {covered_tokens}",
        f"read_hint: {_hint_by_tokens(ptok, covered_tokens, n_sessions)}",
        "reviewed:",
        "---",
    ]


def render_page(group: dict, sessions: dict[str, dict], kw: dict[str, list[str]]) -> str:
    anchor = group["anchor"]
    members = sorted((sessions[s] for s in group["sessions"]), key=lambda x: x["end"])
    titles = [m["title"] for m in members]
    tags = ["对话沉淀"] + _pick_terms(members, anchor, 3, 3)
    ents = [anchor] + _pick_terms(members, anchor, 5, 3)

    B: list[str] = []
    B.append(f"# {anchor}·对话沉淀")
    B.append("")
    B.append("> 本页由脚本从历史会话中原样摘录，未经模型改写；引号内为原话，可回溯到会话 ID。")
    B.append("")
    B.append("## 涉及会话")
    B.append("")
    B.append("| 日期 | 会话标题 | 来源 | 消息数 | 会话 ID |")
    B.append("|---|---|---|---|---|")
    for m in members:
        B.append(f"| {ymd(m['end'])} | {_esc(m['title'])} | {m.get('agent', '?')} "
                 f"| {m['msgs']} | `{m['id'][:8]}` |")
    B.append("")
    B.append("## 关键结论（原文摘录）")
    B.append("")
    for m in members:
        for c in m["_concl"][:4]:
            B.append(f"- {ymd(m['end'])}｜「{_esc(c)}」 —— 出自《{_esc(m['title'])}》`{m['id'][:8]}`")
    if not any(m["_concl"] for m in members):
        B.append("- （本组会话未抽到带结论标记的整句，见下方用户请求）")
    B.append("")
    B.append("## 用户诉求")
    B.append("")
    for m in members:
        for pr in m["prompts"][:2]:
            # 顺序很重要：先脱敏、再截断。反过来会把 `sk-ws-...` 切成 `sk-ws-`，
            # 正则认不出半截密钥，于是它以「看起来无害」的形式留在页面上。
            B.append(f"- {ymd(m['end'])}｜{_esc(redact(pr)[:180])}")
    B.append("")
    B.append("## 可复用产物")
    B.append("")
    got = False
    for m in members:
        for kind, v in m["_prod"][:4]:
            B.append(f"- `{kind}` {_esc(v)}  —— 《{_esc(m['title'])}》")
            got = True
    if not got:
        B.append("- （无路径/命令级产物）")
    B.append("")
    B.append("## 关键词")
    B.append("")
    B.append("　".join(f"`{t}`" for t in kw.get(anchor, [])[:10]))
    B.append("")
    B.append("## 更新日志")
    B.append("")
    B.append(f"- {time.strftime('%Y-%m-%d %H:%M')}｜{GENERATOR} 生成｜来源 {len(members)} 个会话"
             f"（{titles[0][:20]} 等）")
    B.append("")

    body = "\n".join(B)
    head = _yaml_head(anchor, ymd(max(m["end"] for m in members)), tags, ents,
                      len(members), body,
                      _covered_chars(group, sessions), _covered_tokens(group, sessions))
    return "\n".join(head + ["", body])


def render_month(month: str, members_in: dict[str, dict]) -> str:
    """未归入主题的会话按月归档，保证「每个会话都能被找到」，又不制造几十个碎页。"""
    members = sorted(members_in.values(), key=lambda x: x["end"])
    B: list[str] = []
    B.append(f"# {month} 会话档案")
    B.append("")
    B.append("> 本月未归入专门主题的会话，按时间排列。主题明确的会话已单独成页。")
    B.append("")
    B.append("## 会话清单")
    B.append("")
    B.append("| 日期 | 会话 | 来源 | 消息数 | 关键词 | ID |")
    B.append("|---|---|---|---|---|---|")
    for m in members:
        kws = "、".join(m["_ent"][:3]) or "—"
        B.append(f"| {ymd(m['end'])} | {_esc(m['title'])} | {m.get('agent', '?')} "
                 f"| {m['msgs']} | {_esc(kws)} | `{m['id'][:8]}` |")
    B.append("")
    B.append("## 代表性结论")
    B.append("")
    any_c = False
    for m in members:
        for c in m["_concl"][:1]:
            B.append(f"- {ymd(m['end'])}｜「{_esc(c)}」 —— 《{_esc(m['title'])}》")
            any_c = True
    if not any_c:
        B.append("- （本月会话未抽到带结论标记的整句）")
    B.append("")
    B.append("## 更新日志")
    B.append("")
    B.append(f"- {time.strftime('%Y-%m-%d %H:%M')}｜{GENERATOR} 生成｜来源 {len(members)} 个会话")
    B.append("")

    body = "\n".join(B)
    head = _yaml_head(f"{month} 会话档案", ymd(members[-1]["end"]),
                      ["对话沉淀", "按时间归档", month],
                      _uniq(_top_entities(members))[:5], len(members), body,
                      sum(m.get("_raw_chars", 0) for m in members),
                      sum(m.get("tokens", 0) for m in members))
    return "\n".join(head + ["", body])


_DISPLAY_EN_STOP = {"important", "summary", "note", "notes", "step", "steps", "example",
                    "result", "results", "output", "input", "value", "values", "true", "false",
                    "must", "save", "saved", "should", "need", "needs", "done", "todo"}


def _display_ok(t: str) -> bool:
    """展示字段（tags/entities）用的词过滤。

    检索索引里保留 n-gram 碎片无妨（搜「识库」也能命中「知识库」），
    但写进 YAML 供人看时必须是像样的词，否则整页显得不可信。
    """
    if not t or len(t) < 2:
        return False
    if t in STOP_BIGRAM or t in VERB_CN or t in GENERIC_CN:
        return False
    if t.isascii():
        if t.lower() in STOP_EN or t.lower() in _DISPLAY_EN_STOP:
            return False
        return len(t) >= 3 and any(c.isupper() for c in t)
    if any(ch in t for ch in "啥吗呢吧啊呗嘛么哦呀啦") or t in INTERROG:
        return False          # 口语与疑问碎片，如「啥意思」「是不是」
    if t.endswith(("一下", "一些", "一点", "一样", "时候", "之后", "之前")):
        return False          # 量词/时间后缀，语义为空
    return not t.endswith(("的", "了", "是"))


def _pick_terms(members: list[dict], anchor: str, n: int = 3, min_len: int = 3) -> list[str]:
    """为 tags/entities 挑展示词：过滤碎片，并去掉被更长候选包含的词。"""
    c: Counter = Counter()
    for m in members:
        c.update(m["_ent"])
    cands: list[str] = []
    for t, _ in c.most_common(60):
        if t == anchor or not _display_ok(t):
            continue
        if not t.isascii() and len(t) < min_len:
            continue
        cands.append(t)
    out: list[str] = []
    for t in cands:
        if any(len(u) > len(t) and t in u for u in cands) and t not in DOMAIN_WORDS:
            continue        # 长词覆盖短词时只留长词（真词见 DOMAIN_WORDS 白名单）
        out.append(t)
        if len(out) >= n:
            break
    return out


def _top_entities(members: list[dict]) -> list[str]:
    c: Counter = Counter()
    for m in members:
        c.update(m["_ent"])
    return [k for k, _ in c.most_common(24) if _display_ok(k)]


def _uniq(seq):
    out, seen = [], set()
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").strip()


def render_raw(sess: dict) -> str:
    L = [f"# {sess['title']}", "",
         f"- 会话：`{sess['id']}`",
         f"- 时间：{ymd(sess['start'])} ~ {ymd(sess['end'])}",
         f"- 工作区：{sess['cwd']}",
         f"- 消息数：{sess['msgs']}", "",
         "## 用户请求", ""]
    for i, p in enumerate(sess["prompts"], 1):
        L.append(f"{i}. {p}")
        L.append("")
    L.append("## 助手结论摘录")
    L.append("")
    for c in sess["_concl"]:
        L.append(f"- {c}")
    L.append("")
    return "\n".join(L)


# ------------------------------------------------------------------ 索引 / 日志

def render_index(pages: list[dict], total_sessions: int, gate: dict | None = None) -> str:
    gate = gate or {}
    status = gate.get("status", "unknown")
    flag = "🟢 可启用" if status == "active" else ("🔴 休眠中" if status == "dormant" else "—")
    L = ["# 对话库 索引", "",
         "> 由技能包 `super-larder` 的 `scripts/build.py` 自动维护，**不要手改**。",
         f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M')}｜已沉淀会话：{total_sessions}"
         f"｜主题页：{len(pages)}",
         f"> 自检状态：**{flag}**｜{gate.get('reason', '')}",
         f"> 压缩比 {gate.get('compression', 0)}:1｜典型会话 {gate.get('median_session_tokens', 0)} token"
         f"｜典型页 {gate.get('median_page_tokens', 0)} token", "",
         "## 主题页", "",
         "| 主题 | 会话数 | 最近活跃 | 文件 |",
         "|---|---|---|---|"]
    for p in sorted(pages, key=lambda x: -x["recent"]):
        L.append(f"| {p['title']} | {p['n']} | {ymd(p['recent'])} | [[{p['slug']}]] |")
    L.append("")
    L.append("## 关键词速查")
    L.append("")
    L.append("> 检索用：`build.py stats` 看高频词，或 `recall.py search` 查原始会话。")
    L.append("")
    return "\n".join(L)


def append_log(rows: list[str]) -> None:
    SYS.mkdir(parents=True, exist_ok=True)
    head = ""
    if not LOGFILE.exists():
        head = "# 对话库 入库日志\n\n> 格式：`- YYYY-MM-DD HH:MM｜做了什么｜依据`\n\n"
    with LOGFILE.open("a", encoding="utf-8") as fh:
        if head:
            fh.write(head)
        for r in rows:
            fh.write(r + "\n")


# ------------------------------------------------------------------ 启动自检

def _median(xs: list[int]) -> int:
    xs = sorted(x for x in xs if x)
    if not xs:
        return 0
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) // 2


def compute_gate(sessions: dict, pages: list[dict]) -> dict:
    """判断这个库现在到底省不省 token。

    三个条件全部成立才允许启用：
      ① 会话数够多，聚类才有意义；
      ② 压缩比够高（原始语料 ÷ 全库页数），说明真有大量可压内容；
      ③ 一页的成本不超过一个典型会话——否则「读一页」比「直接读会话」还贵，
         这正是小语料反亏的根因（实测 9 个会话时读页 1112 token vs 读原文 486）。
    """
    sess_tokens = [s.get("tokens", 0) for s in sessions.values() if s.get("tokens")]
    page_tokens = [x.get("tokens", 0) for x in pages if x.get("tokens")]
    raw_total = sum(sess_tokens)
    page_total = sum(page_tokens)
    med_sess = _median(sess_tokens)
    med_page = _median(page_tokens)
    compression = (raw_total / page_total) if page_total else 0.0
    payoff = (med_sess / med_page) if med_page else 0.0

    cfg = CONFIG.get("gate") or {}
    min_sessions = int(cfg.get("min_sessions", 20))
    min_compression = float(cfg.get("min_compression", 8))
    min_payoff = float(cfg.get("min_payoff", 1.0))

    reasons = []
    if len(sess_tokens) < min_sessions:
        reasons.append(f"会话只有 {len(sess_tokens)} 个，至少需要 {min_sessions} 个")
    if compression < min_compression:
        reasons.append(f"压缩比 {compression:.1f}:1，至少需要 {min_compression:.0f}:1")
    if payoff < min_payoff:
        reasons.append(f"典型会话 {med_sess} token，不足一页（{med_page} token）")
    return {
        "status": "dormant" if reasons else "active",
        "checked_at": time.strftime("%Y-%m-%d %H:%M"),
        "sessions": len(sess_tokens),
        "pages": len(page_tokens),
        "raw_tokens": raw_total,
        "page_tokens": page_total,
        "median_session_tokens": med_sess,
        "median_page_tokens": med_page,
        "compression": round(compression, 2),
        "payoff": round(payoff, 2),
        "thresholds": {"min_sessions": min_sessions, "min_compression": min_compression,
                       "min_payoff": min_payoff},
        "reason": "；".join(reasons) if reasons else "三个条件均满足，可启用",
    }


# ------------------------------------------------------------------ 构建

def cmd_build(args) -> int:
    t0 = time.time()
    for d in (RAW, WIKI, SYS):
        d.mkdir(parents=True, exist_ok=True)

    sources = adapters.discover(CONFIG.get("sources") or [],
                                use_defaults=not CONFIG.get("sources_only"))
    files: list[Path] = []
    seen_files: set[str] = set()
    for src in sources:
        for f in src["files"]:
            if str(f) in seen_files:
                continue
            seen_files.add(str(f))
            files.append(f)
    if not files:
        print("尚未发现任何客户端的对话转录。")
        print("已检查：" + "、".join(f"{a} {r}" for a, r in adapters.DEFAULT_ROOTS))
        print('可补来源： "sources": [{"agent": "generic", "root": "~/my-agent/history"}]')
        return 0
    say("来源：" + "、".join(f"{s_['agent']}×{len(s_['files'])}" for s_ in sources))

    state = load_json(STATE, {})
    prev = state.get("sessions", {})
    new_state: dict[str, list[int]] = {}

    sessions: dict[str, dict] = {}
    changed: list[str] = []
    keys: dict[Path, str] = {}
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        key = f"{adapters.agent_of(p)}:{p.stem}"
        keys[p] = key
        fp = [st.st_mtime_ns // 10**6, st.st_size]
        new_state[key] = fp
        if prev.get(key) != fp:
            changed.append(key)

    if not args.force and not changed:
        say("无新增或变更会话，跳过构建。")
        return 0

    # 全量聚类，但解析走缓存：文件指纹没变就直接复用上次结果，
    # 避免每次都重新读一遍几百 MB 磁盘。聚类仍基于全部会话，索引不会残缺。
    pcache = load_json(CACHE, {})

    def _put(sess: dict) -> None:
        """同一会话可能同时出现在 rollout 文件和 SQLite 里，留内容更全的那份。

        标题另有讲究：SQLite 的标题来自客户端目录（真实标题），rollout 只能用
        首条提问兜底。所以保留更全消息的同时，优先采用「客户端给的标题」。
        """
        old = sessions.get(sess["id"])
        if old:
            keep_old = old.get("msgs", 0) > sess.get("msgs", 0)
            big, small = (old, sess) if keep_old else (sess, old)
            if small.get("title_src") and not big.get("title_src"):
                big["title"] = small["title"]
                big["title_src"] = "agent"
            if not big.get("cwd") and small.get("cwd"):
                big["cwd"] = small["cwd"]
            if keep_old:
                return
        sessions[sess["id"]] = sess

    reused = 0
    for p in files:
        key = keys.get(p)
        fp = new_state.get(key) if key else None
        unchanged = (not args.force) and key is not None and prev.get(key) == fp

        if unchanged:
            # 来源没变：直接按来源标签从缓存恢复，不重读磁盘
            restored = 0
            for entry in pcache.values():
                if not isinstance(entry, dict) or entry.get("_src") != key:
                    continue
                s = {k: v for k, v in entry.items() if k != "_fp"}
                s["asst"] = []
                _put(s)
                restored += 1
            if restored:
                reused += restored
                continue

        for s in parse_sessions(p):
            s["_concl"] = conclusions(s)
            s["_prod"] = products(s)
            # 读原文的代价：raw 快照包含用户请求全文 + 结论摘录
            s["_raw_chars"] = (sum(len(x) for x in s["prompts"])
                               + sum(len(x) for x in s["_concl"]) + 200)
            s["_key"] = key
            s["_src"] = key
            s.pop("asst", None)
            _put(s)

    # ---- 抽词：标题为主（权重 3），用户请求为辅（权重 1），助手正文不进词表
    def session_terms(s: dict) -> tuple[Counter, Counter]:
        """标题权重 3，用户请求权重 1；助手正文不进词表（工具输出噪音全在那里）。"""
        tc = terms_of(s["title"])
        pc = terms_of("\n".join(s["prompts"][:8]))
        merged: Counter = Counter()
        for k, v in tc.items():
            merged[k] += v * 3
        for k, v in pc.items():
            merged[k] += v
        return tc, merged

    per: dict[str, list[tuple[str, float]]] = {}
    glob_c: Counter = Counter()
    df: Counter = Counter()
    title_df: Counter = Counter()
    cache: dict[str, Counter] = {}

    for sid, s in sessions.items():
        tc, merged = session_terms(s)
        cache[sid] = merged
        glob_c.update(merged)
        df.update(set(merged))
        title_df.update(set(tc))

    scores = select_terms(glob_c, df, max(1, len(sessions)))

    for sid, s in sessions.items():
        local = cache.pop(sid)
        terms = [(t, local[t] * (scores.get(t, 0.0) / max(glob_c[t], 1)))
                 for t in local if t in scores]
        terms.sort(key=lambda x: -x[1])
        per[sid] = terms[:20]
        s["_ent"] = [t for t, _ in terms[:8]]

    # ---- 收集凭证值（必须在渲染之前，供两遍脱敏的第二遍使用）
    secrets_clear()
    for s_ in sessions.values():
        collect_secrets("\n".join(s_["prompts"]))
        collect_secrets("\n".join(s_["_concl"]))
        collect_secrets("\n".join(v for k, v in s_["_prod"]) if s_["_prod"] else "")

    # ---- 聚类
    groups, leftovers = cluster_sessions(per, scores, title_df)

    # ---- 落盘：raw
    for sid, s in sessions.items():
        d = RAW / ymd(s["end"])[:7]
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{sid}.md").write_text(redact(render_raw(s)), encoding="utf-8")

    # ---- 落盘：wiki
    # macOS/Windows 的文件系统默认不区分大小写，`WORKBUDDY.md` 与 `WorkBuddy.md`
    # 会落成同一个文件——28 个主题悄悄变成 27 个。slug 必须按小写去重。
    used_slugs: set[str] = set()

    def _unique_slug(title: str) -> str:
        base = slugify(title) or "untitled"
        cand = base
        i = 2
        while cand.lower() in used_slugs:
            cand = f"{base}-{i}"
            i += 1
        used_slugs.add(cand.lower())
        return cand

    pages: list[dict] = []
    for g in groups:
        kw = {g["anchor"]: [t for t, _ in per[g["sessions"][0]]]}
        body = render_page(g, sessions, kw)
        slug = _unique_slug(g["anchor"])
        (WIKI / f"{slug}.md").write_text(redact_page(body), encoding="utf-8")
        pages.append({
            "title": g["anchor"], "slug": slug, "n": len(g["sessions"]),
            "recent": max(sessions[s]["end"] for s in g["sessions"]),
            "tokens": est_tokens(body),
        })

    # 未归类会话按月归档，避免出现一个吞掉四成语料的巨型「零散」页
    by_month: dict[str, list[str]] = defaultdict(list)
    for sid in leftovers:
        by_month[ymd(sessions[sid]["end"])[:7]].append(sid)
    for month, sids in sorted(by_month.items()):
        sub = {s: sessions[s] for s in sids}
        slug = _unique_slug(f"{month}-会话档案")
        mbody = render_month(month, sub)
        (WIKI / f"{slug}.md").write_text(redact_page(mbody), encoding="utf-8")
        pages.append({"title": f"{month} 会话档案", "slug": slug, "n": len(sids),
                      "recent": max(sessions[s]["end"] for s in sids),
                      "tokens": est_tokens(mbody)})

    # ---- 启动自检（写进 _系统/gate.json，技能每次先读它）
    gate = compute_gate(sessions, pages)
    save_json(GATEFILE, gate)
    if gate["status"] == "dormant":
        say(f"[休眠] {gate['reason']}。此时不检索、不读页，只继续积累语料。")

    # ---- keywords.json
    kwmap: dict[str, list[str]] = defaultdict(list)
    for sid, terms in per.items():
        for t, _ in terms[:10]:
            kwmap[t].append(sid)
    save_json(KWFILE, {"built": int(time.time()), "sessions": len(new_state),
                       "terms": dict(kwmap)})

    # ---- 清理上一轮遗留、本轮已不存在的主题页
    # 只删带 generated_by 标记的（自己生成的）；手写文件一律不动，只提示。
    keep = {f"{p['slug']}.md" for p in pages}
    removed = 0
    for old in WIKI.glob("*.md"):
        if old.name in keep:
            continue
        try:
            head = old.read_text(encoding="utf-8", errors="replace")[:400]
        except OSError:
            continue
        if "generated_by:" in head:
            old.unlink()
            removed += 1
        else:
            say(f"[!] 保留非生成页：{old.name}（手写内容请移到主库 wiki/）")

    # 旧版本会写 _系统/index.json，里面存着未脱敏的历史条目；
    # 现已由 keywords.json + index.md 取代，必须清掉，否则脱敏永远有漏网。
    legacy = SYS / "index.json"
    if legacy.exists():
        try:
            legacy.unlink()
        except OSError:
            pass

    # ---- index / state / log
    INDEX.write_text(render_index(pages, len(sessions), gate), encoding="utf-8")
    save_json(STATE, {"sessions": new_state})
    new_pcache = {}
    for sid, s in sessions.items():
        entry = {k: v for k, v in s.items() if k != "asst"}
        # 缓存里同样不能留明文：它虽不进仓库，却会跟着知识库目录一起同步出去
        for k in ("title",):
            if isinstance(entry.get(k), str):
                entry[k] = redact(entry[k])
        for k in ("prompts", "_concl"):
            if isinstance(entry.get(k), list):
                entry[k] = [redact(x) for x in entry[k]]
        if entry.get("_prod"):
            entry["_prod"] = [[a, redact(b)] for a, b in entry["_prod"]]
        entry["_raw_chars"] = entry.get("_raw_chars", 0)
        entry["_src"] = entry.get("_src") or entry.get("_key")
        entry["_fp"] = new_state.get(entry.get("_key") or sid)
        new_pcache[sid] = entry
    save_json(CACHE, new_pcache)
    if changed:
        append_log([f"- {time.strftime('%Y-%m-%d %H:%M')}｜build｜解析 {len(sessions)} 个会话"
                    f"（变更 {len(changed)}），生成 {len(pages)} 个主题页"
                    f"｜源 " + "、".join(f"{s_['agent']}×{len(s_['files'])}" for s_ in sources)])

    dt = time.time() - t0
    say(f"构建完成：{len(sessions)} 个会话（缓存命中 {reused}，需重解析 {len(sessions) - reused}）"
        f"→ {len(pages)} 个主题页"
        + (f"，清理过期页 {removed}" if removed else "")
        + f"，耗时 {dt:.1f}s")
    say(f"  索引：{INDEX}")
    say(f"  倒排：{KWFILE}")
    say(f"  raw ：{RAW}")
    say(f"\n下一步：python {Path(__file__).resolve()} report   # 生成审核报告，交给线上模型过目")
    return 0


# ------------------------------------------------------------------ 报告 / 校验

def cmd_report(args) -> int:
    gate0 = load_json(GATEFILE, {})
    n_sess = gate0.get("sessions") or len(load_json(STATE, {}).get("sessions", {}))
    pages = sorted(WIKI.glob("*.md"))
    kw = load_json(KWFILE, {"terms": {}})

    rows = []
    for p in pages:
        txt = p.read_text(encoding="utf-8", errors="replace")
        ok_yaml = txt.startswith("---")
        has_log = "## 更新日志" in txt
        chars = len(re.sub(r"\s", "", re.sub(r"```.*?```", "", txt, flags=re.S)))
        rows.append((p.stem, chars, ok_yaml, has_log))

    thin = [r for r in rows if r[1] < 300]
    bad_yaml = [r for r in rows if not r[0]]
    no_log = [r[0] for r in rows if not r[3]]

    gate = load_json(GATEFILE, {})
    lines = [
        f"对话库构建报告 {time.strftime('%Y-%m-%d %H:%M')}",
        f"自检 {gate.get('status', 'unknown')}｜{gate.get('reason', '')}",
        f"会话总数 {n_sess}｜主题页 {len(pages)}｜关键词 {len(kw.get('terms', {}))}",
        f"薄页面(<300字) {len(thin)}｜缺更新日志 {len(no_log)}",
    ]
    if thin:
        lines.append("薄页：" + "、".join(f"{t[0]}({t[1]}字)" for t in thin[:5]))
    lines.append("抽查建议：" + "、".join(p.stem for p in pages[:2]))
    print("\n".join(lines))
    return 0


_LEAK_RES = [
    re.compile(r"\bsk-[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{20,})\b"),
    # 引号必须成对，且值不能是 ***（已脱敏）或空
    re.compile(r"(?i)(?:pass(?:word|wd)?|api[_-]?key|secret)\s*[:=]\s*([\"'`]?)(?!\*)([^\s\"'`]{4,})\1"),
    re.compile(r"(?:密码|口令|密钥)\s*[:：=]\s*(?!\*)([A-Za-z0-9!@#$%^&*._\-]{4,})"),
    re.compile(r"(?<!\d)1[3-9]\d{6}\d{4}(?!\d)"),
]


def cmd_lint(args) -> int:
    # 先扫 raw/：快照虽不可变，但必须确认脱敏生效（凭据一旦落盘就是事故）
    leaks = 0
    for f in RAW.rglob("*.md"):
        t = f.read_text(encoding="utf-8", errors="replace")
        # 三条都要「真的像值」才算泄漏。早期版本把 `KEY=` 后面紧跟的反引号/引号
        # 当成值，于是 DB_PASS=`、TOKEN_PLAN_API_KEY=" 全部误报——狼来了比漏报更伤。
        if any(pat.search(t) for pat in _LEAK_RES):
            print(f"[!] 凭据未脱敏：{f.name}")
            leaks += 1
    if leaks:
        print(f"\n[!] {leaks} 个 raw 快照含明文凭据，禁止提交或同步。")
        return 2

    pages = sorted(WIKI.glob("*.md"))
    if not pages:
        print("wiki/ 为空，无内容可校验。")
        return 0
    errs = 0
    for p in pages:
        t = p.read_text(encoding="utf-8", errors="replace")
        probs = []
        if not t.startswith("---\n"):
            probs.append("YAML 不在首行")
        for f in ("title:", "date:", "type:", "tags:", "entities:", "status:"):
            if f"\n{f}" not in t and not t.startswith(f"{f}"):
                probs.append(f"缺字段 {f}")
        need = ("## 会话清单", "## 代表性结论", "## 更新日志") if "会话档案" in p.name \
            else ("## 涉及会话", "## 关键结论", "## 更新日志")
        for sec in need:
            if sec not in t:
                probs.append(f"缺章节 {sec}")
        vis = re.sub(r"```.*?```", "", t, flags=re.S)
        if len(re.sub(r"\s", "", vis)) < 300:
            probs.append("正文少于 300 字")
        for bad in ("TODO", "待补充", "待填写"):
            if bad in vis:
                probs.append(f"占位符 {bad}")
        if any(pat.search(vis) for pat in _LEAK_RES):
            probs.append("疑似明文凭据")
        if probs:
            errs += 1
            print(f"[!] {p.name}: " + "；".join(probs))
    print(f"\n共 {len(pages)} 页，问题页 {errs} 个。")
    return 1 if errs else 0


def cmd_stats(args) -> int:
    state = load_json(STATE, {})
    kw = load_json(KWFILE, {"terms": {}})
    pages = sorted(WIKI.glob("*.md"))
    gate = load_json(GATEFILE, {})
    print(f"自检状态：{gate.get('status', 'unknown')}（{gate.get('reason', '')}）")
    print(f"压缩比：{gate.get('compression', 0)}:1｜典型会话 {gate.get('median_session_tokens', 0)} token"
          f"｜典型页 {gate.get('median_page_tokens', 0)} token")
    print(f"已沉淀会话：{gate.get('sessions') or len(state.get('sessions', {}))}")
    print(f"主题页：{len(pages)}")
    print(f"关键词：{len(kw.get('terms', {}))}")
    top = sorted(kw.get("terms", {}).items(), key=lambda x: -len(x[1]))[:12]
    if top:
        print("高频关键词（覆盖会话数）：")
        for k, v in top:
            print(f"  {len(v):>3}  {k}")
    return 0


# ------------------------------------------------------------------ 入口

def main() -> int:
    ap = argparse.ArgumentParser(prog="build.py", description="对话库构建流水线（纯 CPU）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="全流程构建")
    p.add_argument("--force", action="store_true", help="忽略缓存，全量重建")
    p.add_argument("--quiet", action="store_true", help="静默模式，只在出错时输出")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("report", help="生成审核报告")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("lint", help="校验生成物")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("stats", help="库概览")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    global QUIET
    QUIET = bool(getattr(args, "quiet", False))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
