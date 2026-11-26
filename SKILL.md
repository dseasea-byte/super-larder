---
name: super-larder
slug: super-larder
version: 5.1.0
displayName: Super Larder · 接续
display_name_en: Super Larder
description: 把历史对话在本地整理成可查档案，让 AI 下次不必重读原料。支持 Codex、Claude Code、Gemini CLI、Qwen Code、WorkBuddy、GitHub Copilot Chat、Cline、Continue、OpenCode、ChatGPT 导出包、aider 等客户端的转录，任何 JSON/JSONL 转录也能兜底接入，整理与检索全部由本机脚本完成，不调用任何模型、不耗一个 token。装完会先自检：语料太小、读页不划算时自动休眠，不检索也不打扰；达到阈值后自行启用。当用户在新会话重提旧任务、要求「沿用上次/接着之前/查一下以前」、或需要回溯已定口径与踩坑记录时使用。
description_en: Turns past conversations into a locally searchable archive so the assistant stops re-reading raw transcripts. Reads transcripts from Codex, Claude Code, Gemini CLI, Qwen Code, WorkBuddy, GitHub Copilot Chat, Cline, Continue, OpenCode, ChatGPT exports and aider, with a generic JSON/JSONL fallback for any other agent; extraction, clustering and retrieval run in local scripts with zero model calls and zero tokens. It self-checks after install and stays dormant (no lookups, no interruption) until the corpus is large enough to actually pay off. Use when a session revisits prior work, or when earlier decisions and pitfalls must be recalled.
author: "董海洋（DHY.sea）"
---

# Super Larder · 接续

> 中文「温故」取自「温故而知新」；英文 larder 指「把已经付过钱的东西存起来、取用时不必再买」的地方。
>
> **Read once. Answer forever.** 只读一次，之后随时可查。

## 先看能力，再决定装不装

只依赖两样东西，**缺一样就别装**：

| 能力 | 要求 | 没有会怎样 |
|---|---|---|
| Python | 3.9 及以上 | 无法运行 |
| jieba 分词 | `pip install jieba`（约 6 MB，纯 CPU） | 脚本报错退出，不降级 |

**不需要**：显卡、本地大模型、API key、向量库、Docker、联网（首次装分词库除外）。

**装了也可能用不上**：只聊过十几轮、从不重提旧事、主要做一次性生成。装完会自检，不划算时它自己休眠，不会打扰你。

## 支持的客户端

**不用配置，装完自动发现。** 每个来源第一次出现时自动识别格式：

| 客户端 | 读取位置 | 适配 |
|---|---|---|
| Codex（CLI / Desktop） | `~/.codex/sessions/**/rollout-*.jsonl` | 原生 |
| Codex Desktop 实时线程 | `~/.codex/thread_history_1.sqlite` | 原生（进行中的对话也在这里） |
| Claude Code | `~/.claude/projects/<slug>/<uuid>.jsonl` | 原生 |
| Gemini CLI | `~/.gemini/tmp/<proj>/chats/*.json` | 原生 |
| Qwen Code / iFlow CLI | `~/.qwen/tmp`、`~/.iflow/tmp` | 原生（Gemini 格式） |
| WorkBuddy / CodeBuddy | `~/.workbuddy|~/.codebuddy/projects/<proj>/<sid>.jsonl` | 原生 |
| GitHub Copilot Chat（VS Code / Cursor / Windsurf / Trae / Kiro） | `.../User/workspaceStorage/*/chatSessions/*.json` | 原生 |
| Cline / Roo Code | `.../globalStorage/saoudrizwan.claude-dev/tasks/*/api_conversation_history.json` | 原生 |
| Continue | `~/.continue/sessions/*.json` | 原生 |
| OpenCode | `~/.local/share/opencode/storage/message/<sid>/*.json` | 原生（按会话目录合并） |
| ChatGPT 官方导出包 | `conversations.json` | 原生（一个文件几百个会话） |
| aider | `.aider.chat.history.md` | 原生（按 `####` 分块） |
| 其他任何 Agent | JSONL / JSON 里带 `role` + `content`，或对话型 Markdown | 通用兜底 |

先看本机到底认出了什么，不花一个 token：

```bash
python3 scripts/adapters.py        # 列出每个客户端 / 路径 / 会话数
```

自研或小众客户端，在 `config.json` 里直接指路：

```json
{
  "sources": [{"agent": "generic", "root": "~/my-agent/history"}],
  "sources_only": false
}
```

`agent` 可选 `codex` / `claude` / `gemini` / `qwen` / `workbuddy` / `copilot` / `cline` /
`continue` / `opencode` / `chatgpt` / `aider` / `generic`；填错也不致命，会退回通用解析。

## 优势

1. **不用单独建库。** 知识库从已有对话转录自动生成，不录入、不整理、不打标签。
2. **建库零 token。** 整理、抽词、聚类、成页、索引全在本机完成，线上模型一步都不参与。
3. **不绑定客户端。** 换 Agent 不用重建：同一个库同时吃多家转录，来源在页面里标得出来。
4. **会自己判断该不该开工。** 装完先自检，语料不够就休眠，达到阈值自动启用。
5. **原文照录，不生产结论。** 每条结论带日期与会话 ID，可回到原话核对。
6. **脱敏优先于照录。** 口令、密钥（含 `sk-`/`ghp_` 这类前缀式）、手机号落盘前替换为 `***`。

## 性能

实测环境：macOS，227 个会话（Codex 211 + WorkBuddy 73，去重后 227）。

| 项目 | 数据 | 口径 |
|---|---|---|
| 全量构建 | **2.0 秒** | 含 SQLite 库扫描 |
| 增量重建 | **0.3–1.4 秒** | 来源未变则直接复用缓存 |
| 单次检索定位 | **17 毫秒** | grep 主题页 |
| 产出 | 28 个主题页 / 39,691 tokens | 压缩比 **56 : 1** |
| 建库消耗 token | **0** | 无任何网络请求 |

读取成本对照：

| 场景 | 无技能 | 有技能 | 节省 |
|---|---|---|---|
| 回顾一次（替代 2 个中位会话） | 3,094 | 1,281 | **59%** |
| 回顾一次（替代 1 个大会话） | 29,610 | 1,281 | **96%** |
| 只读命中行 | 3,094 | 241 | **92%** |
| 读全语料（理论上限） | 2,238,197 | 39,691 | 98.2% |

> 最后一行是理论上限，现实中无人通读全语料。对外只说单次回顾的数字。
>
> **小语料是反的**：会话只有几十 token 时，读页比读原文更贵。所以有「启动自检」，见下节。

## English Overview

Super Larder turns conversation history into a local, searchable archive without calling a single LLM.

**It is not tied to one client.** Adapters read Codex rollouts and live SQLite threads, Claude Code, Gemini CLI, and WorkBuddy transcripts; anything else falls back to a generic JSONL/JSON reader. Switching agents does not mean rebuilding the archive.

**It checks whether it is worth running.** After install, and on every rebuild, it computes three numbers — session count, compression ratio, and the cost of a typical page versus a typical session. If reading a page would cost more than reading the raw session, the skill goes **dormant**: it does not search, does not read pages, does not interrupt. It keeps indexing quietly in the background so it can cross the threshold on its own.

Three design rules: no model dependency (Python + jieba only), extractive with provenance (every conclusion carries a date and session id), and redaction before write (passwords, API keys and phone numbers become `***`; quoted values included).

It is an archive, not a memory: the assistant must look something up to know it, and it only knows what was said and recorded.

## 术语对照

| 中文 | English | 含义 |
|---|---|---|
| 档案 | archive | 被动查询，不是主动记忆 |
| 主题页 | topic page | 按主题聚合的会话摘要页 |
| 月度档案 | monthly digest | 未归入主题的会话，按月归档 |
| 启动自检 | gate | 判断语料够不够本，决定启用还是休眠 |
| 休眠 | dormant | 不检索、不读页、不打扰，但仍在积累语料 |
| read_hint | read_hint | 读整页是否划算：`page` / `either` / `grep` |
| payload_tokens | payload_tokens | 本页实际 token（渲染后实测，不是估算） |
| covered_tokens | covered_tokens | 本页覆盖的原文 token |
| 脱敏 | redaction | 口令值替换为 `***`，保留「曾有凭据」的事实 |
| 照录 | extractive quoting | 原句摘录，不改写、不总结 |
| 来源 | source | 会话来自哪个客户端，页面里单独一列 |

## 生效规则

### 第一步永远是读自检

```
打开 <库>/_系统/gate.json
```

| `status` | 该做什么 |
|---|---|
| `active` | 正常流程（下面的分级触发） |
| `dormant` | **什么都不做**：不刷新、不 grep、不读页、不呈现；按普通对话回答 |
| 文件不存在 | 先跑一次 `build.py build --quiet`，再读一次 |
| `unknown` | 按 dormant 处理（宁可不用，也不乱花钱） |

`gate.json` 由构建生成：`setup.py` 装完的第 4 步就是首次构建，所以新用户装好当场就有这个文件。
`recall.py` 还会自己做一次硬拦截——`dormant` 时 `search` / `show` 直接以退出码 3 结束。
即使模型没读 `SKILL.md`，也不会在语料不够时花掉 token。

**唯一例外**：用户明确问「以前的资料里有没有…」时，可以回一句否定结论 + 原因，例如：

> 档案还在积累：现在 8 个会话，至少要 20 个；压缩比 1:1，至少要 8:1。暂时先不用它。

这句话之后**不要**再去读页——休眠就是休眠。

### 四条不打扰红线

1. **静默刷新。** 不宣布「我正在整理历史」，刷新是内部动作。
2. **高置信不问。** 命中明确时直接带结论往下干，不发起选择。
3. **刷新一次，检索不限轮次。** 刷新每会话只做一次；一级检索不花 token，卡轮次只会漏掉会话中段的追问。
4. **同一实体只读一次页。** 已读过整页的实体，之后靠上下文，除非用户说「再查一下」。

### 触发分级（一级几乎免费，二级才花钱）

| 级别 | 动作 | 成本 | 触发条件 |
|---|---|---|---|
| **刷新** | `build.py build --quiet` | 1–2 秒 / 0 token | 每会话一次，仅在 gate 为 active 时 |
| **一级** | `grep` 主题页 | 25 毫秒 / 0 token | 出现已知实体或回溯词，**不限轮次** |
| **二级** | 读整页 | 1,281 tokens（中位） | 四条同时满足：① 一级有命中 ② `read_hint` 允许 ③ 命中项标题含当前实体 ④ 用户要旧结论或旧产物 |

一级不命中就停，**不升级到二级**。

**一级也不必做的情况**：纯闲聊、单点概念问答、明确要求从零重做、本轮内容已在上下文里。

显式触发（「接着上次」「以前定过没」「再查一下」）仍受 gate 约束；gate 为 dormant 时只回一句「还没到能用的时候」，不检索。

## 判据

### 读整页还是只读命中行

每页 YAML 自带实测字段：

```yaml
payload_tokens: 1281     # 本页实际 token（渲染后量出来的）
covered_tokens: 90573    # 覆盖原文 token
read_hint: page          # page / either / grep
```

| `read_hint` | 处置 |
|---|---|
| `page` | 读整页 |
| `either` | 先读命中段，不够再读整页 |
| `grep` | **不读整页**，只取命中行或看 `raw/` 快照 |

判定顺序（任一条命中即降级）：

1. `payload_tokens > 6000` → `grep`（绝对上限，页太大一定亏）
2. 会话数 ≥ 12 且 `payload_tokens > 2500` → `either`（这是索引页，不是答案页）
3. `covered_tokens < payload_tokens` → `grep`（页比原文还大）

### 呈现置信度

| 档位 | 条件 | 形态 |
|---|---|---|
| 高 | 命中项标题含当前任务的核心实体 | 一句话带出结论，不提问 |
| 中 | 同一业务域但产物不同 | 候选表 ≤3 条 + `0 = 都不用` |
| 低 | 仅共享泛化关键词 | 不呈现，静默吸收 |

## 执行顺序

1. **读 `_系统/gate.json`** —— `dormant` 就到此为止，按普通对话回答
2. **判要不要动** —— 出现已知实体或回溯词才继续；否则正常回答，不刷新、不检索
3. **刷新（每会话仅一次）** —— `build.py build --quiet`，失败则跳过，用旧索引继续
4. **再读一次 gate** —— 刷新后可能刚好跨过阈值，或刚好掉下来
5. **一级检索** —— `grep` 主题页；不中就停；需要时退到 `recall.py` 查原始转录
6. **判深度** —— 按 `read_hint`、当前实体、红线 4 决定读整页还是只读命中行
7. **呈现** —— 高置信一句话带出，中低置信给候选表

刷新必须在检索之前，否则刚结束的对话不在索引里。

## 参数

```bash
python scripts/adapters.py               # 自检：本机认出了哪些客户端、多少会话（零 token）
python scripts/build.py build            # 增量刷新
python scripts/build.py build --force    # 全量重建（改了抽词规则后）
python scripts/build.py build --quiet    # 静默，供技能内部调用
python scripts/build.py report           # 审核报告（约十行，含自检结论）
python scripts/build.py lint             # 合规 + 凭据扫描
python scripts/build.py stats            # 库概览（含自检三指标）

python scripts/recall.py search "关键词" --since 90d --limit 5
python scripts/recall.py show <会话ID>
```

`config.json` 可选项：

```json
{
  "kb_root": "~/.codex/convo-kb",
  "sources": [{"agent": "generic", "root": "~/my-agent/history"}],
  "sources_only": false,
  "gate": {"min_sessions": 20, "min_compression": 8, "min_payoff": 1.0},
  "read_hint": {"max_page_tokens": 6000},
  "domain_words": ["你自己的业务词"]
}
```

## 能力缺失时的降级

| 情况 | 处置 |
|---|---|
| 缺 jieba | 报错退出并提示安装，**不退回 n-gram** |
| 没有任何转录目录 | 提示可用的客户端与自定义方式，不报错 |
| 某客户端格式不认识 | 退回通用解析；仍解析不出就跳过该文件，不影响其他来源 |
| 刷新失败 | 跳过，用上一版索引继续检索 |
| gate 为 dormant | 不检索、不读页，只回一句原因；`recall.py` 也会以退出码 3 拒绝 |
| 索引/缓存损坏 | 自动回退默认值并重建，不崩 |

## 禁止事项

- 让线上模型读原始转录做摘要（那是本方案要消灭的成本）
- **gate 为 dormant 时仍然检索或读页**（这就把「自动休眠」变成了摆设）
- 把档案当记忆用（「你应该记得吧」——它不查就不知道）
- 手改 `wiki/`（下次构建整体覆盖）
- 把生成内容当权威引用（它是线索层）
- 每轮都读整页（一级 grep 可以每轮做；二级读页必须过四道条件）
- 检索为空时反复换词重试三轮
- 对外宣称「省 98%」或「AI 有了记忆」
