# 支持的客户端

**不用配置，装完自动发现**，每个来源第一次出现时按内容识别格式。

| 客户端 | 读取位置 | 适配 |
|---|---|---|
| Codex（CLI / Desktop） | `~/.codex/sessions/**/rollout-*.jsonl` | 原生 |
| Codex Desktop 实时线程 | `~/.codex/thread_history_1.sqlite` | 原生（进行中的对话也在这里） |
| Claude Code | `~/.claude/projects/<slug>/<uuid>.jsonl` | 原生 |
| Gemini CLI | `~/.gemini/tmp/<proj>/chats/*.json` | 原生 |
| Qwen Code / iFlow CLI | `~/.qwen/tmp`、`~/.iflow/tmp` | 原生（Gemini 格式） |
| WorkBuddy / CodeBuddy | `~/.workbuddy\|~/.codebuddy/projects/<proj>/<sid>.jsonl` | 原生 |
| GitHub Copilot Chat（VS Code / Cursor / Windsurf / Trae / Kiro） | `.../User/workspaceStorage/*/chatSessions/*.json` | 原生 |
| Cline / Roo Code | `.../globalStorage/saoudrizwan.claude-dev/tasks/*/api_conversation_history.json` | 原生 |
| Continue | `~/.continue/sessions/*.json` | 原生 |
| OpenCode | `~/.local/share/opencode/storage/message/<sid>/*.json` | 原生（按会话目录合并） |
| ChatGPT 官方导出包 | `conversations.json` | 原生（一个文件几百个会话） |
| aider | `.aider.chat.history.md` | 原生（按 `####` 分块） |
| 其他任何 Agent | JSONL / JSON 里带 `role` + `content`，或对话型 Markdown | 通用兜底 |

## 先看本机认出了什么（零 token）

```bash
python3 scripts/adapters.py
```

输出每个客户端、路径、会话数。某个来源是 0，通常是路径不同或格式没识别出来。

## 接自研 / 小众客户端

在 `config.json` 里直接指路：

```json
{
  "sources": [{"agent": "generic", "root": "~/my-agent/history"}],
  "sources_only": false
}
```

`agent` 可选 `codex` / `claude` / `gemini` / `qwen` / `workbuddy` / `copilot` /
`cline` / `continue` / `opencode` / `chatgpt` / `aider` / `generic`。
填错也不致命——文件格式最终按内容判断，`agent` 只决定先去哪些目录找。
