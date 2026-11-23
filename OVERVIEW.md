## 中文

**让 AI 记住你说过的话。**

每个新对话，AI 都失忆一次。上周定好的口径，今天要重讲一遍——而且每讲一次都在烧 token。

Super Larder 换个思路：把搬运的活交给你的 CPU。

- 聊过的每一句，在本机压成一份可查档案
- 建库 **0 token**、约 **3 秒**，不联网、不调模型
- 回顾一次省 **84–94%**，只读命中行省 **98%**
- 原句照录，带日期和会话 ID，随时回原文核对

实测：160 条对话 / 746MB → 6.7MB / 28 个主题页。

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
- **Zero tokens** to build, about **3 seconds**, no network, no model calls
- **84–94% fewer tokens** per revisit; **98%** when only the hit line is read
- Extractive with provenance: original sentences, dates and session IDs, always traceable

Measured: 160 conversations / 746 MB → 6.7 MB / 28 topic pages.

Requires only Python + jieba (6 MB). No GPU, no vector DB, no API key.

```bash
skillhub install super-larder
```

> An AI's memory makes things up. An archive doesn't.
