# 术语对照

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
| overhead_tokens | overhead_tokens | 技能正文自身的加载成本，计入回本比 |
| 脱敏 | redaction | 口令值替换为 `***`，保留「曾有凭据」的事实 |
| 照录 | extractive quoting | 原句摘录，不改写、不总结 |
| 来源 | source | 会话来自哪个客户端，页面里单独一列 |
