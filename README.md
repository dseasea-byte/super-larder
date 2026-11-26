# Super Larder

**An archive, not a memory.**

A *larder* is where you keep what you've already paid for, so winter costs nothing.

[中文](README.zh-CN.md) · English

Turns your past conversations into a local, searchable archive — **without calling a single LLM, without a GPU, without uploading a byte.**

### Read once. Answer forever.

---

## The problem

Every new chat starts amnesiac.

Yesterday's decisions get re-explained today. Last week's pitfalls get re-hit this week. After three months you've told the same assistant the same thing three times, and it remembers none of it.

The expensive part isn't your time — it's the tokens. Every time it "re-understands" you, it burns your quota.

The real fix isn't a smarter model. It's giving the model **something it can look up**.

---

## What it does

```
your client writes transcripts ──> build.py (pure CPU) ──> archive ──> assistant reads
                                          ↑
                              runs automatically before each lookup
```

| Layer | Job | Cost |
|---|---|---|
| `build.py` | clean, extract, cluster, render, index | **0 tokens**, 1–3 s |
| `wiki/` + `raw/` | topic pages, session snapshots, keyword index | plain Markdown + JSON |
| Review | read a ten-line report, spot-check two pages | a few hundred tokens |

**The archive builds itself.** There is no separate curation step — no import, no tagging, no editor. Point it at the transcripts your client already writes and it grows on its own.

---

## Supported agents

**No configuration required** — it auto-discovers and auto-detects:

| Client | Where it reads |
|---|---|
| Codex (CLI / Desktop) | `~/.codex/sessions/**/rollout-*.jsonl` |
| Codex Desktop live threads | `~/.codex/thread_history_1.sqlite` |
| Claude Code | `~/.claude/projects/<slug>/<uuid>.jsonl` |
| Gemini CLI | `~/.gemini/tmp/<proj>/chats/*.json` |
| Qwen Code / iFlow CLI | `~/.qwen/tmp`, `~/.iflow/tmp` |
| WorkBuddy / CodeBuddy | `~/.workbuddy|~/.codebuddy/projects/<proj>/<sid>.jsonl` |
| GitHub Copilot Chat (VS Code, Cursor, Windsurf, Trae, Kiro) | `.../User/workspaceStorage/*/chatSessions/*.json` |
| Cline / Roo Code | `.../globalStorage/saoudrizwan.claude-dev/tasks/*/api_conversation_history.json` |
| Continue | `~/.continue/sessions/*.json` |
| OpenCode | `~/.local/share/opencode/storage/message/<sid>/*.json` |
| ChatGPT export | `conversations.json` |
| aider | `.aider.chat.history.md` |
| Anything else | Generic reader: any JSONL/JSON with `role` + `content` |

Check what it found on your machine (zero tokens):

```bash
python3 scripts/adapters.py
```

Point it at a custom agent from `config.json`:

```json
{ "sources": [{ "agent": "generic", "root": "~/my-agent/history" }] }
```

Switching agents does not mean rebuilding: one archive reads them all, and every page lists which client each session came from.

---

## It decides whether it is worth running

This is the part most tools skip.

After install — and on every rebuild — it computes three numbers:

| Metric | Meaning |
|---|---|
| sessions | how many conversations it has seen |
| compression | raw tokens ÷ archive tokens |
| payoff | typical session tokens ÷ typical page tokens |

If reading one page would cost more than reading the raw session it replaces, the skill goes **dormant**: no lookups, no page reads, no interruption. It keeps indexing quietly so it can cross the threshold on its own, and flips to `active` on the first rebuild that qualifies.

An 8-session corpus measured here: compression 1.0:1, payoff 0.12 → dormant. A 227-session corpus: 56:1, payoff 1.21 → active.

---

## Measured

227 sessions / 2.24M tokens of raw transcripts, on an ordinary desktop:

| Metric | Value |
|---|---|
| Cold build | **2.0 s** |
| Incremental rebuild | **0.3–1.4 s** |
| Archive size | 28 pages / 39,691 tokens |
| Compression | **56.6 : 1** (2.24M → 40K tokens) |
| Median session | 1,547 tokens |
| Median page | 1,266 tokens |
| Tokens spent building | **0** |
| Retrieval lookup | **17 ms** |

Cost of reading (median page: 1,266 tokens). "Net" also charges the ~1,400 tokens of
instructions the skill itself loads — that is the number your bill actually sees:

| Task | Without | Page only | Net (page + 1,400) | Net saved |
|---|---|---|---|---|
| Revisit one topic (2 median sessions) | 3,094 | 1,266 | 2,666 | **14%** |
| Revisit one large session | 29,610 | 1,266 | 2,666 | **91%** |
| Read matched lines only | 3,094 | 241 | 1,641 | **47%** |
| Three lookups in one session | 9,282 | 3,798 | 5,198 | **44%** |

> Measured on a 227-session corpus, not projections. Instructions load once per session, so
> repeated lookups amortize them. Quote the net range (14–91%), never a flat "98%". 

---

## How it works

1. **Scan** the JSONL transcripts your client writes
2. **Clean** — strip system reminders, tool notifications and their boilerplate residue
3. **Extract** — jieba POS tagging, nouns only; titles weigh 3×, user prompts 1×, assistant bodies are excluded (all tool noise lives there)
4. **Redact** — passwords, keys and phone numbers become `***`
5. **Cluster** — group sessions by shared topic terms; leftovers fall into monthly digests
6. **Render** — conclusions are quoted **verbatim with a date and session id**, never paraphrased
7. **Write** — pages, index, keyword map, log — then self-check

### Three rules

**No model dependency.** Python 3.9+ and jieba. No GPU, no API key, no local LLM.
Most people don't have a local model — wiring the feature to one means only a handful can use it.

**Extractive, with provenance.** Every conclusion carries a date and session id. Check it against the original. A model's memory hallucinates; an archive doesn't.

**Redaction beats fidelity.** Credentials are masked before anything lands on disk, because an archive gets committed, synced and backed up. `lint` scans every snapshot and exits non-zero on a hit.

---

## Install

1. Drop the folder into `~/.workbuddy/skills/super-larder/`
2. Run the installer:
   - **macOS** — double-click `setup.command` (if macOS refuses, `chmod +x setup.command` first)
   - **Windows** — double-click `setup.cmd`
   - **Linux / any** — `python3 setup.py`
3. Restart your client

The installer checks Python, installs jieba if missing, writes a config, builds the first archive and prints a review report.

**Requires**: Python 3.9+, ~10 MB disk. **Does not require**: GPU, local model, API key, network (beyond the first `pip install jieba`).

All three platforms run the same code — there is no platform-specific branch. On macOS with a Homebrew Python, pip may be blocked by PEP 668; the installer retries with `--user` and tells you what to do if that fails too.

---

## Usage

No maintenance required. The assistant rebuilds the archive before a lookup (about 1.4 s, silent).

You can also just ask:
- "Did I ever work on X?"
- "What did we settle on last time?"
- "Use the same rules as before"

Or read the files: `index.md` in the archive root is the table of contents.

`config.json`:

```json
{
  "kb_root": "~/super-larder-kb",
  "projects_root": null,
  "domain_words": ["your", "domain", "terms"]
}
```

`domain_words` tells the tokenizer what counts as a word in your field. Optional, but topic names get noticeably better.

---

## Every page knows its own cost

Before you read a page, the page tells you whether it is worth reading:

```yaml
payload_chars: 3131     # size of this page
covered_chars: 94519    # size of the raw sessions it covers
read_hint: page         # page | either | grep
```

| `read_hint` | What to do |
|---|---|
| `page` | Read it. Covers ≥1.5× its own size |
| `either` | Read the matched lines first |
| `grep` | **Don't read the page** — take the matched lines or the raw snapshot |

Measured distribution (227 sessions): 27 `page`, 1 `either`.

**You never read a page blind.** Every page declares its own cost and says whether reading it
is worth it. And before the skill touches anything, it checks the whole archive: if a lookup
wouldn't pay for itself, it stays dormant instead of spending your tokens.

---

## Why it holds up

- **Every line is traceable.** Conclusions are quoted verbatim with a date and session ID — open the
  original and check it yourself.
- **It never invents.** Extraction only. No summarizing, no paraphrase, no hallucinated "memory".
- **Runs on a laptop you already own.** Python + jieba, pure CPU: no GPU, no vector database,
  no API key, no upload.
- **Twelve formats out of the box.** Codex, Claude Code, Gemini, Qwen, WorkBuddy, Copilot Chat,
  Cline, Continue, OpenCode, ChatGPT exports, aider — plus a generic reader for anything else.
- **It measures itself.** Session count, compression ratio and payoff are recomputed on every
  build; the archive has to prove it is worth running before it runs.

---

## Commands

```bash
python scripts/build.py build           # incremental refresh
python scripts/build.py build --force   # full rebuild (after changing extraction rules)
python scripts/build.py build --quiet   # silent, used by the skill itself
python scripts/build.py report          # review report
python scripts/build.py lint            # schema + credential scan
python scripts/build.py stats           # overview

python scripts/recall.py search "keyword" --since 90d --limit 5
python scripts/recall.py show <session-id>
```

---

## License

MIT
