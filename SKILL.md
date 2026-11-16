---
name: super-larder
slug: super-larder
version: 4.1.2
displayName: Super Larder · 接续
display_name_en: Super Larder
description: 把历史对话在本地整理成可查档案，让 AI 下次不必重读原料。整理与检索全部由本机脚本完成，不调用任何模型、不耗一个 token；需要判断时只读一份十行审核报告。知识库从已有对话自动生成，不需单独录入或整理。当用户在新会话重提旧任务、要求「沿用上次/接着之前/查一下以前」、或需要回溯已定口径与踩坑记录时使用。纯闲聊、单点概念问答、明确要求从零重做时不触发。
description_en: Turns past conversations into a locally searchable archive so the assistant stops re-reading raw transcripts. Extraction, clustering and retrieval all run in local scripts with zero model calls and zero tokens; the only paid step is reading a ten-line review report. The knowledge base builds itself from existing conversations — no manual curation. Use when a new session revisits prior work, when the user asks to continue or reuse earlier conclusions, or when earlier decisions and pitfalls must be recalled.
author: "董海洋（DHY.sea）"
---

# Super Larder · 接续

> 中文「温故」取自「温故而知新」；英文 Super Larder 取自 larder——
> 英文里「把已经付过钱的东西存起来、取用时不必再买」的地方。
>
> **Read once. Answer forever.** 只读一次，之后随时可查。

## 先看能力，再决定装不装

只依赖两样东西，**缺一样就别装**：

| 能力 | 要求 | 没有会怎样 |
|---|---|---|
| Python | 3.9 及以上 | 无法运行 |
| jieba 分词 | `pip install jieba`（约 6 MB，纯 CPU） | 脚本报错退出，不降级 |

**不需要**：显卡、本地大模型、API key、向量库、Docker、联网（首次装分词库除外）。

**装了也没用的情况**：对话只有三五轮就结束、从不重提旧事、主要让 AI 做一次性生成。判断标准只有一条——**过去三个月里，同一件事做过第二遍吗？**

## 优势

1. **不用单独建库。** 知识库从已有对话转录自动生成，不录入、不整理、不打标签。你正常聊天，它自己长出来。
2. **建库零 token。** 整理、抽词、聚类、成页、索引全在本机完成，线上模型一步都不参与。
3. **原文照录，不生产结论。** 每条结论带日期与会话 ID，可回到原话核对。AI 的记忆会编，档案不会。
4. **自动刷新，用户零操作。** 检索前静默重建，约 1.4 秒，不弹窗、不询问，不需要记得去点什么。
5. **自带性价比自检。** 每页标注 `read_hint`，小语料时机器自己认输，只读命中行，不让读页变亏。
6. **脱敏优先于照录。** 口令、密钥、手机号落盘前替换为 `***`；`lint` 扫全部快照，命中即拒绝入库。

## 性能

用例：本机 101 个会话 / 15,459 条消息 / 627 MB 原始转录 / 清洗后正文 2,931,475 tokens。

| 项目 | 数据 | 口径 |
|---|---|---|
| 冷启动建库 | **2.9 秒** | 纯计算，不含解释器启动 |
| 热启动重建 | **0.8 秒** | 解析缓存全命中 |
| 自动刷新 | **1.4 秒** | 含解释器启动，静默 |
| 单次检索定位 | **17 毫秒** | grep 主题页 |
| 产出 | 22 个主题页 / 39,946 tokens | 压缩比 **73 : 1** |
| 建库消耗 token | **0** | 无任何网络请求 |

读取成本对照（单页平均 1,815 tokens）：

| 场景 | 无技能 | 有技能 | 节省 |
|---|---|---|---|
| 回顾一次（替代 2 个中位会话） | 11,390 | 1,815 | **84%** |
| 回顾一次（替代 1 个大会话） | 29,610 | 1,815 | **94%** |
| 只读命中行 | 11,390 | 241 | **98%** |
| 读全语料（理论上限） | 2,931,475 | 39,946 | 98.6% |

> 最后一行是理论上限，现实中无人通读全语料。对外只说 84–94%；98.6% 会被一句「谁会读全语料」问住。

**小语料是反的**：9 个短会话只生成 3 页，全部 `grep`——读它们净亏。所以每页自带 `read_hint`，见「判据」。

## English Overview

Super Larder turns conversation history into a local, searchable archive without calling a single LLM.

Every new chat starts amnesiac: the same context gets re-explained, the same plan re-derived, the same pitfalls re-hit. Online models bill per token, so re-reading history is expensive and often impossible.

This skill pushes the mechanical work to your own CPU — cleaning transcripts, extracting keywords with jieba POS tagging, clustering sessions into topic pages, building an inverted index. On a 101-session / 627 MB corpus it finishes in 2.9 seconds at zero token cost, compressing 2.93M tokens of dialogue into 40K tokens of pages (73:1). The point is saving tokens: 84–94% fewer tokens on every revisit.

**The knowledge base builds itself.** There is no separate curation step: point it at the transcripts your client already writes, and it grows on its own.

Three design rules: no model dependency (Python + jieba only, so anyone can install it), extractive with provenance (every conclusion carries a date and session id, never paraphrased), and redaction before write (passwords, keys and phone numbers become `***`).

It is an archive, not a memory: the assistant must look something up to know it, and it only knows what was said and recorded. Each page ships a `read_hint` field so the agent can tell, mechanically, whether reading the whole page beats reading the raw sessions.

## 术语对照

| 中文 | English | 含义 |
|---|---|---|
| 档案 | archive | 本知识库的定位：被动查询，不是主动记忆 |
| 主题页 | topic page | 按主题聚合的会话摘要页，一页一个主题 |
| 月度档案 | monthly digest | 未归入主题的会话，按月归档 |
| read_hint | read_hint | 读整页是否划算：`page` / `either` / `grep` |
| payload_chars | payload_chars | 本页字数 |
| covered_chars | covered_chars | 本页覆盖的原文总字数 |
| 脱敏 | redaction | 口令值替换为 `***`，保留「曾有凭据」的事实 |
| 照录 | extractive quoting | 原句摘录，不改写、不总结 |

## 生效规则

### 四条不打扰红线

1. **静默刷新**。不宣布「我正在整理历史」，刷新是内部动作。
2. **高置信不问**。命中明确时直接带结论往下干，不发起选择。
3. **刷新一次，检索不限轮次**。刷新每会话只做一次（约 1.4 秒）；检索不按轮次卡——一级检索不花 token，卡轮次只会漏掉会话中段的追问。
4. **同一实体只读一次页**。同一会话里同一个实体已读过整页，之后靠上下文，不再重读，除非用户说「再查一下」。

### 触发分级（一级几乎免费，二级才花钱）

两级成本差两个数量级，因此必须分开控制，不能用一个开关管两件事。

| 级别 | 动作 | 成本 | 触发条件 |
|---|---|---|---|
| **刷新** | `build.py build --quiet` | 1.4 秒 / 0 token | 每会话一次，在首次检索前顺带做 |
| **一级** | `grep` 主题页 | 25 毫秒 / 0 token | 出现**已知实体**（用户的项目名、系统名）或**回溯词**（上次/继续/沿用/以前定过），**不限轮次** |
| **二级** | 读整页 | 1,815 tokens | 四条同时满足：① 一级有命中 ② `read_hint: page` ③ 命中项标题含当前实体 ④ 用户要的是旧结论或旧产物 |

一级不命中就停，**不升级到二级**。一级命中但 `read_hint` 为 `either`／`grep` 时，只读命中行，不读整页。

**一级也不必做的四种情况**：纯闲聊、单点概念问答（答案在文档里不在档案里）、明确要求从零重做、本轮内容已在上下文里。

显式触发（「接着上次」「以前定过没」「再查一下」）跳过条件 ①②③，且**必须有回话**，包括「没找到」这个否定结论；只有红线 4 仍然生效。

## 判据

### 读整页还是只读命中行

每页 YAML 自带三个字段：

```yaml
payload_chars: 3131     # 本页字数
covered_chars: 94519    # 覆盖原文总字数
read_hint: page         # page / either / grep
```

| `read_hint` | 处置 |
|---|---|
| `page` | 读整页。覆盖原文 ≥ 本页 × 1.5，稳赚 |
| `either` | 先读命中段，不够再读整页 |
| `grep` | **不读整页**，只取命中行或看 `raw/` 快照 |

实测分布（101 会话）：12 页 `page`、8 页 `either`、2 页 `grep`。
小语料（9 会话）3 页全为 `grep`——此时读页纯亏。

### 呈现置信度

| 档位 | 条件 | 形态 |
|---|---|---|
| 高 | 命中项标题含当前任务的核心实体 | 一句话带出结论，不提问 |
| 中 | 同一业务域但产物不同 | 候选表 ≤3 条 + `0 = 都不用` |
| 低 | 仅共享泛化关键词 | 不呈现，静默吸收 |

## 执行顺序

1. **判要不要动**——出现已知实体或回溯词才继续；否则像普通对话一样回答，不刷新、不检索、不留痕
2. **刷新（每会话仅一次）**——`build.py build --quiet`（静默，约 1.4 秒，失败则跳过，用旧索引继续）
3. **一级检索**——`grep` 主题页；不中就停，不升级；仍需要时再退到 `recall.py` 查原始转录
4. **判深度**——按 `read_hint`、当前实体、红线 4 决定读整页还是只读命中行
5. **呈现**——高置信一句话带出，中低置信给候选表

刷新必须在检索之前，否则刚结束的对话不在索引里。

## 参数

```bash
python scripts/build.py build           # 增量刷新
python scripts/build.py build --force   # 全量重建（改了抽词规则后）
python scripts/build.py build --quiet   # 静默，供技能内部调用
python scripts/build.py report          # 审核报告（约十行）
python scripts/build.py lint            # 合规 + 凭据扫描
python scripts/build.py stats           # 库概览

python scripts/recall.py search "关键词" --since 90d --limit 5
python scripts/recall.py show <会话ID>
```

配置在 `config.json`：`kb_root`（知识库位置）、`projects_root`（转录来源）、`domain_words`（你自己的领域词）。

## 能力缺失时的降级

| 情况 | 处置 |
|---|---|
| 缺 jieba | 报错退出并提示安装，**不退回 n-gram**（会产出碎片主题名） |
| 转录目录不存在 | 提示「先用几天再来构建」，不报错 |
| 刷新失败 | 跳过，用上一版索引继续检索 |
| 主题页不存在 | 退到 `recall.py` 查原始转录 |
| 两路都空 | 显式触发→回「没找到」；自动触发→什么都不说，直接干活 |
| 索引/缓存损坏 | 自动回退默认值并重建，不崩 |

## 禁止事项

- 让线上模型读原始转录做摘要（那是本方案要消灭的成本）
- 把档案当记忆用（「你应该记得吧」——它不查就不知道）
- 手改 `wiki/`（下次构建整体覆盖）
- 把生成内容当权威引用（它是线索层）
- 每轮都读整页（一级 grep 可以每轮做，它不花 token；二级读页必须过四道条件）
- 检索为空时反复换词重试三轮
- 对外宣称「省 98.6%」或「AI 有了记忆」
