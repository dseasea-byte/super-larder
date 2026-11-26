# 命令与配置

```bash
python scripts/adapters.py               # 自检：认出了哪些客户端、多少会话（零 token）
python scripts/build.py build            # 增量刷新
python scripts/build.py build --force    # 全量重建（改了抽词规则之后）
python scripts/build.py build --quiet    # 静默，供技能内部调用
python scripts/build.py report           # 审核报告（约十行，含自检结论）
python scripts/build.py lint             # 合规 + 凭据扫描，命中即非零退出
python scripts/build.py stats            # 库概览（含自检三指标）

python scripts/recall.py index --force   # 全量重建检索索引
python scripts/recall.py search "关键词" --since 90d --limit 5
python scripts/recall.py show <会话ID>
```

`config.json` 可选项：

```json
{
  "kb_root": "~/.super-larder",
  "sources": [{"agent": "generic", "root": "~/my-agent/history"}],
  "sources_only": false,
  "gate": {
    "min_sessions": 20,
    "min_compression": 8,
    "min_payoff": 1.0,
    "overhead_tokens": 1400
  },
  "read_hint": {"max_page_tokens": 6000},
  "domain_words": ["你自己的业务词"]
}
```

- `overhead_tokens`：技能正文的加载成本，默认 1400（对应正文约 1,277 token）。正文越长就调得越高，
  调高会让门槛更严（宁可休眠，也不做亏本买卖）。
- `sources_only: true` 时只读 `sources` 里列出的目录，不自动发现。
