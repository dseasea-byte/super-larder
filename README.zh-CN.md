# Super Larder · 温故

**它是档案，不是记忆。**

larder 是英文里「把已经付过钱的东西存起来、冬天不必再买」的地方。

[English](README.md) · 中文

> 把历史对话在本地整理成可检索的知识库。**不调用任何大模型，不需要显卡，不上传一个字节。**

**只读一次，之后随时可查。**

[English](#english) · [工作原理](#工作原理) · [安装](#安装三步) · [适合谁](#适合谁)

---

## 它解决什么问题

每开一个新对话，AI 就失忆一次。

昨天讲清楚的口径今天要再讲一遍，上周踩过的坑这周再踩一遍。三个月下来，你对着同一个 AI 说了三遍同样的话——它一次都没记住。

更贵的是额度：它每次「重新理解」你，都在烧你的 token。

真正的解决办法不是让 AI 更聪明，而是**给它一份能查的档案**。

---

## 它做了什么

```
宿主实时写转录 ──> build.py（纯 CPU）──> 知识库 ──> AI 检索
                    ↑
              每次要查之前自动刷新
```

三个层次：

| 层 | 作用 | 成本 |
|---|---|---|
| 执行层 `build.py` | 清洗、抽词、聚类、成页、建索引 | 0 token，约 1–3 秒 |
| 沉淀层 `wiki/` + `raw/` | 主题页、会话快照、关键词倒排 | 纯本地文件（Markdown + JSON） |
| 审核层 | 你或线上模型读一份十行报告、抽查两页 | 数百 token |

**关键：整理工作全部由本机 CPU 完成。** 线上模型只在最后读一份摘要，不参与生成。

---

## 支持哪些客户端

**不用配置，装完自动发现、自动识别格式。**

| 客户端 | 读取位置 | 适配 |
|---|---|---|
| Codex（CLI / Desktop） | `~/.codex/sessions/**/rollout-*.jsonl` | 原生 |
| Codex Desktop 实时线程 | `~/.codex/thread_history_1.sqlite` | 原生 |
| Claude Code | `~/.claude/projects/<slug>/<uuid>.jsonl` | 原生 |
| Gemini CLI | `~/.gemini/tmp/<proj>/chats/*.json` | 原生 |
| Qwen Code / iFlow CLI | `~/.qwen/tmp`、`~/.iflow/tmp` | 原生 |
| WorkBuddy / CodeBuddy | `~/.workbuddy|~/.codebuddy/projects/<proj>/<sid>.jsonl` | 原生 |
| GitHub Copilot Chat（VS Code / Cursor / Windsurf / Trae / Kiro） | `.../workspaceStorage/*/chatSessions/*.json` | 原生 |
| Cline / Roo Code | `.../globalStorage/saoudrizwan.claude-dev/tasks/*/api_conversation_history.json` | 原生 |
| Continue | `~/.continue/sessions/*.json` | 原生 |
| OpenCode | `~/.local/share/opencode/storage/message/<sid>/*.json` | 原生 |
| ChatGPT 导出包 | `conversations.json` | 原生 |
| aider | `.aider.chat.history.md` | 原生 |
| 其他任何 Agent | JSONL / JSON 带 `role` + `content` | 通用兜底 |

先看本机到底认出了什么，不花一个 token：

```bash
python3 scripts/adapters.py
```

自研客户端在 `config.json` 里指个路就行：

```json
{ "sources": [{ "agent": "generic", "root": "~/my-agent/history" }] }
```

换 Agent 不用重建：一个库同时吃多家转录，每页都标注每个会话来自哪个客户端。

---

## 它会自己判断该不该开工

这是大多数工具省掉的一步。

装完时、以及每次重建后，它都会算三个数：

| 指标 | 含义 |
|---|---|
| 会话数 | 见过多少段对话 |
| 压缩比 | 原始 token ÷ 档案 token |
| 回本比 | 典型会话 token ÷ 典型页 token |

**如果读一页比读被替代的原始会话还贵，它就休眠**：不检索、不读页、不打扰，只在后台继续积累语料；等到某次重建跨过阈值，自己切换成启用。

本机实测：8 个会话时压缩比 1.0:1、回本比 0.12 → 休眠；227 个会话时 56:1、回本比 1.21 → 启用。

---

## 实测数据

在一台普通 Mac 上，227 个历史会话、约 224 万 token 原始转录：

| 指标 | 数值 |
|---|---|
| 冷启动建库 | **2.0 秒** |
| 增量刷新 | **0.3–1.4 秒** |
| 产出 | 28 个主题页 / 39,691 token |
| 压缩比 | **56.6 : 1**（224 万 → 4 万 token） |
| 典型会话 | 1,547 token |
| 典型页 | 1,266 token |
| 建库消耗 token | **0** |
| 单次检索定位 | **17 毫秒** |

读一次的成本对照（典型页 1,266 token）。「净」把技能正文自己那约 1,400 token 也算进去——
那才是账单上的数：

| 场景 | 不用技能 | 只算页 | 净（页 + 1,400） | **净省** |
|---|---|---|---|---|
| 替代 2 个中位会话 | 3,094 | 1,266 | 2,666 | **14%** |
| 替代 1 个大会话 | 29,610 | 1,266 | 2,666 | **91%** |
| 只读命中行 | 3,094 | 241 | 1,641 | **47%** |
| 同一会话回溯 3 次 | 9,282 | 3,798 | 5,198 | **44%** |

> 说明成本每会话只付一次，回顾越多越划算。对外只说净省区间 14–91%，不说「省 98%」。

---

## 工作原理

1. **扫描** 各家客户端的转录目录（Codex / Claude Code / Gemini / Qwen / WorkBuddy / Copilot / Cline / Continue / OpenCode …，路径见上表）
2. **清洗**：剥掉 system-reminder、task-notification 等注入块及其残留样板句
3. **抽词**：用 jieba 词性标注，只留名词性词语；**标题权重 3、用户请求权重 1，助手正文不进词表**（工具输出噪音全在正文里）
4. **脱敏**：口令、密钥、手机号的值替换为 `***`
5. **聚类**：按主题词聚合，未归类的会话按月归档
6. **成页**：结论句按标记词抽取，**原样引用并标注出处**，不改写
7. **落盘**：raw / wiki / index / keywords.json / log，并自动校验

### 三条设计铁律

**一、零模型依赖。** 只依赖 Python 3.9+ 和 jieba。不联网、不调大模型、不需要 GPU。
因为多数人的电脑上没有本地模型——把功能挂在模型上，等于只有少数人配用。

**二、原文照录，不生产结论。** 每条结论都带日期和会话 ID，你能顺着回去核对原话。
AI 的记忆会编，档案不会。

**三、脱敏优先于照录。** 口令、密钥、手机号在落盘前替换为 `***`，保留「这里曾有凭据」这一事实，不保留值。
`lint` 会扫描全部快照，发现明文即返回非零。

---

## 安装：三步

1. 把 `super-larder` 整个目录放到：
   - Windows：`%USERPROFILE%\.workbuddy\skills\super-larder\`
   - macOS / Linux：`~/.workbuddy/skills/super-larder/`
2. 运行安装：
   - **Windows**：双击 `setup.cmd`
   - **macOS**：双击 `setup.command`（首次若提示无权限，先在终端执行 `chmod +x setup.command`）
   - **任意系统（命令行）**：`python3 setup.py`（Windows 用 `python setup.py`）
3. 重启 WorkBuddy

`setup.py` 会自动检查 Python 版本、缺则安装 jieba、生成配置文件、建好知识库并出第一份报告。

**需要**：Python 3.9+，约 10 MB 磁盘。**不需要**：显卡、本地模型、API key、网络（首次装 jieba 除外）。

**三个平台同等对待**：Windows、macOS、Linux 跑的是同一份 Python 代码，没有平台专有逻辑。
macOS 若用 Homebrew 装的 Python，pip 可能被 PEP 668 拦住，`setup.py` 会自动重试 `--user`；仍失败时按提示加 `--break-system-packages`。

---

## 日常使用

不需要手动维护。AI 在需要回忆时会自己在 1.4 秒内刷新知识库。

你也可以直接问：
- 「查一下我以前有没有做过 XX」
- 「上次那个 YY 方案是怎么定的」
- 「沿用之前的口径」

或者直接看文件：知识库根目录的 `index.md` 是总目录。

配置在 `config.json`：

```json
{
  "kb_root": "~/convo-kb",
  "projects_root": null,
  "domain_words": ["你自己的", "业务专有名词"]
}
```

`domain_words` 用来告诉分词器哪些是你领域的词——不填也能用，但填了主题名会更准。

---

## 每一页都会自己算账

读之前就知道值不值得读——每页 YAML 里带三个自检字段：

```yaml
payload_chars: 3131     # 本页字数
covered_chars: 94519    # 覆盖原文字数
read_hint: page         # page 读整页 / either 看命中段 / grep 别读整页
```

- `page`：覆盖原文是页面的 1.5 倍以上，读页稳赚
- `grep`：**不读整页**，只读命中行或直接看原文

实测分布（227 个会话）：27 页 `page`、1 页 `either`。

**你永远不会盲读一页。** 每个页面自己声明成本、自己说明值不值得读；整个库值不值得跑，
也由它自己算——不划算就休眠，一分钱不花。

## 为什么靠得住

- **每句都能对回原文。** 结论是原句照录，带日期和会话 ID，随时回去核对。
- **它不生产内容。** 只摘录、不改写、不总结——没有「记忆编造」这回事。
- **用你本来就有的电脑。** Python + jieba，纯 CPU：不要显卡、不要向量库、不要 API key、不上传。
- **12 种格式开箱即用。** Codex、Claude Code、Gemini、Qwen、WorkBuddy、Copilot Chat、Cline、
  Continue、OpenCode、ChatGPT 导出、aider，其他格式走通用兜底。
- **它会自己算账。** 每次构建都重算会话数、压缩比和回本比——先证明值得跑，它才会跑。

---

## 适合谁

长期用 AI 做同一类工作、反复重提旧项目、需要回溯「当时为什么这么定」的人。

判断标准一句话：**过去三个月里，同一件事你做过第二遍吗？**

---

## 命令速查

```bash
python scripts/build.py build           # 增量刷新
python scripts/build.py build --force   # 全量重建（改了抽词规则后）
python scripts/build.py build --quiet   # 静默（供技能内部调用）
python scripts/build.py report          # 审核报告
python scripts/build.py lint            # 合规校验
python scripts/build.py stats           # 库概览

python scripts/recall.py search "关键词" --since 90d --limit 5
python scripts/recall.py show <会话ID>
```

---

## English

**Super Larder** turns your conversation history into a local, searchable knowledge base — without calling a single LLM.

Every new chat starts amnesiac. You re-explain the same context, re-derive the same plan, re-hit the same pitfalls. Online models are billed per token, so "just re-read the history" is expensive and often impossible.

This tool pushes the mechanical work to your own CPU: cleaning transcripts, extracting keywords with jieba POS tagging, clustering sessions into topic pages, and building an inverted index. On a 227-session / 2.24M-token corpus it runs in **2.0 seconds and costs zero tokens**, compressing the raw dialogue into 39,691 tokens of searchable pages (56.6:1).

Design rules: **no model dependency** (Python + jieba only, so anyone can install it), **extractive with provenance** (every conclusion carries a date and session id, never paraphrased), and **redaction before write** (passwords, keys and phone numbers are masked to `***`).

It is an archive, not a memory: the assistant has to look something up to know it. And it only knows what was said and recorded.

MIT licensed.

---

## License

MIT
