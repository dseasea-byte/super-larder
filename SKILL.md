---
name: super-larder
slug: super-larder
version: 5.2.0
displayName: Super Larder · 接续
display_name_en: Super Larder
description: 把历史对话在本地整理成可查档案，让 AI 下次不必重读原料。整理与检索全由本机脚本完成，不调用模型、不耗 token；支持 Codex、Claude Code、Gemini、WorkBuddy 等 12 种客户端。装完先自检，语料不够或读页不划算就休眠。当用户在新会话重提旧任务、要求「沿用上次/接着之前/查一下以前」、或需要回溯已定口径与踩坑记录时使用。
description_en: Turns past conversations into a locally searchable archive so the assistant stops re-reading raw transcripts. Extraction and retrieval run in local scripts: zero model calls, zero tokens. Twelve client formats built in. Self-checks after install and stays dormant until it actually pays off. Use when a session revisits prior work, or when earlier decisions and pitfalls must be recalled.
author: "董海洋（DHY.sea）"
---

# Super Larder · 接续

历史对话 → 本地可查档案。**Read once. Answer forever.** 建库与检索全在本机跑，0 token；
只依赖 Python 3.9+ 与 jieba（`pip install jieba`），不要显卡、不要 API key。
细节都在 `references/`，**用到再读**。

## 第一步：读自检

打开 `<库>/_系统/gate.json`：

| `status` | 动作 |
|---|---|
| `active` | 走下面的三级成本 |
| `dormant` | **什么都不做**：不刷新、不 grep、不读页、不呈现 |
| 不存在 | 跑一次 `build.py build --quiet` 再读 |
| `unknown` | 按 `dormant` 处理 |

`dormant` 唯一例外：用户明确问「以前的资料里有没有…」，回一句原因即可，之后不再读页。
`recall.py` 有硬拦截：`dormant` 时 `search` / `show` 退出码 3，不要绕过。

## 三条红线

1. **静默刷新**：不说「我正在整理历史」。
2. **高置信不问**：命中明确就直接带结论开工。
3. **同一实体只读一次页**：读过就靠上下文，除非用户说「再查一下」。

刷新每会话一次；一级检索不花 token，**不限轮次**。

## 三级成本

| 级别 | 动作 | 成本 | 条件 |
|---|---|---|---|
| 刷新 | `build.py build --quiet` | 1–2 秒 / 0 token | 每会话一次，gate 为 active |
| 一级 | `grep` 主题页 | 25 ms / 0 token | 出现已知实体或回溯词 |
| 二级 | 读整页 | ≈1,266 token（中位） | ① 一级命中 ② `read_hint` 允许 ③ 命中标题含当前实体 ④ 用户要旧结论或旧产物 |

一级不命中就停，**不升级**。不必动：纯闲聊、单点概念、明确要求从零重做、内容已在上下文里。

## 读整页还是读命中行

页面 YAML 自带 `payload_tokens` / `covered_tokens` / `read_hint`：

- `read_hint: page` → 读整页
- `read_hint: either` → 先读命中段，不够再读整页
- `read_hint: grep` → **不读整页**，只取命中行或看 `raw/` 快照

三条降级（任一命中）：`payload_tokens > 6000` → grep；会话 ≥ 12 且 `payload_tokens > 2500` → either；
`covered_tokens < payload_tokens` → grep。

呈现：命中标题含核心实体时一句话带结论；只同业务域时给 ≤3 条候选 + `0 = 都不用`；只共享泛化词就不呈现。

## 执行顺序

1. 读 `gate.json`；`dormant` 到此为止
2. 无实体、无回溯词就正常回答
3. 刷新一次（失败就用旧索引）
4. 再读一次 gate（可能刚好跨阈值）
5. 一级 grep；不中就停；需要时用 `recall.py`
6. 按 `read_hint` 决定读整页或只读命中行
7. 呈现

刷新必须在检索之前。

## 禁止

- 让线上模型读原始转录做摘要
- gate 为 dormant 时仍检索或读页
- 把档案当记忆（不查就不知道）
- 手改 `wiki/`（下次构建会覆盖）
- 把生成内容当权威引用
- 每轮都读整页
- 检索为空时反复换词重试
- 对外宣称「省 98%」或「AI 有了记忆」

## 参考（按需读）

| 文件 | 内容 |
|---|---|
| `references/clients.md` | 12 种客户端路径、自检命令、自定义来源 |
| `references/commands.md` | 全部命令与 config 选项 |
| `references/metrics.md` | 实测数据、回本比公式 |
| `references/glossary.md` | 中英术语对照 |
| `references/trigger-and-query.md` | 触发边界案例与查询模板 |
| `references/user-guide.md` | 新用户安装说明 |
