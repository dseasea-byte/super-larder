## 中文

**让 AI 记住你说过的话。**

每个新对话，AI 都失忆一次。上周定好的口径，今天要重讲一遍——而且每讲一次都在烧 token。

Super Larder 换个思路：把搬运的活交给你的 CPU。

- 聊过的每一句，在本机压成一份可查档案
- 建库 **0 token**、约 **2 秒**，不联网、不调模型
- 读一次**净省 14–91%**（已扣掉技能正文那 1,400 token；取决于被替代的会话多长），只读命中行净省 **47%**
- 原句照录，带日期和会话 ID，随时回原文核对
- **装完先自检**：语料太小、读页不划算时自动休眠，不检索、不打扰，够了自己醒

实测：227 个会话 / 224 万 token → 28 个主题页 / 39,691 token（压缩比 56:1）。

内置 12 种客户端转录格式（Codex、Claude Code、Gemini、Qwen、WorkBuddy、Copilot Chat、
Cline、Continue、OpenCode、ChatGPT 导出、aider…），其他格式走通用兜底。

只要 Python + jieba（6MB）。不用显卡，不用向量库，不用 API key。

```bash
skillhub install super-larder
```

> AI 的记忆会编，档案不会。

---

## English

**Make the assistant remember what you already said.**

Every new chat starts amnesiac: the same context gets re-explained, the same pitfalls re-hit — and you pay tokens for it, every time.

Super Larder moves the mechanical work to your own CPU:

- Turns everything you've said into a local, searchable archive
- **Zero tokens** to build, about **2 seconds**, no network, no model calls
- **14–91% fewer tokens net** per revisit, after charging the ~1,400 tokens of instructions
  the skill itself loads; about **47%** net when only the hit line is read
- Extractive with provenance: original sentences, dates and session IDs, always traceable
- **Self-checks before it runs**: if the corpus is too small to pay off, it stays dormant —
  no lookups, no interruption — and wakes up on its own once it is

Measured: 227 sessions / 2.24M tokens → 28 topic pages / 39,691 tokens (56:1 compression).

Twelve transcript formats ship in the box (Codex, Claude Code, Gemini, Qwen, WorkBuddy,
Copilot Chat, Cline, Continue, OpenCode, ChatGPT exports, aider…), with a generic fallback.

Requires only Python + jieba (6 MB). No GPU, no vector DB, no API key.

```bash
skillhub install super-larder
```

> An AI's memory makes things up. An archive doesn't.
