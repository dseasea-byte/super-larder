#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""redactlib.py — 脱敏规则的唯一实现。

build.py 与 recall.py 都必须走这里，否则「一个入口脱敏、另一个入口漏」——
实测踩过：recall 的检索索引里存了未脱敏的 API Key。

三条原则：
  ① 就地脱敏：每条规则自己认得「值在哪」，误伤范围最小。
  ② 全局拉黑：只收「强上下文」的口令值，因为它会在别处裸出现。
  ③ 宁可少抹，不能误伤：误伤会让每一页 YAML 结构失效。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- 数据集

_SECRETS: set[str] = set()

_SECRET_FINDERS = [
    re.compile(r"(?i)(?:pass(?:word|wd)?|pwd)\s*[:=]\s*(\S{4,32})"),
    re.compile(r"(?:密码|口令|密钥|验证码)\s*(?:是|为|[:：=])?\s*([A-Za-z0-9!@#$%^&*._\-]{4,32})"),
]

# 前缀式密钥：没有 password= 这类上下文，只能靠形态识别。
# 两个坑都踩过：
#   · `\bsk-` 在中文字符后面没有边界（「上sk-ca-...」），必须用 (?<![A-Za-z0-9])
#   · `sk-notification` 这种普通标识符会被误判，必须要求含数字
_PREFIX_SECRETS = [
    re.compile(r"(?<![A-Za-z0-9])sk-(?=[A-Za-z0-9._\-]*[0-9])[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[0-9A-Za-z\-]{10,}"),
]

_NOT_SECRET = set("""
session sessions status active commands command info overview services service return admin root
user users test testing error errors true false none null python windows linux docker config
main index page pages file files data value name type size date time
""".split())

_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

_REDACT_RES = [
    # 值可能被引号包着（API_KEY="sk-..."）。引号单独成组、成对回填。
    (re.compile(r"(?i)((?:pass(?:word|wd)?|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|token)"
                r"\s*[:=]\s*)([\"'`]?)([^\s,;，；\"'`（）()`|\[\]{}<>]{2,})\2"), r"\1\2***\2"),
    (re.compile(r"(密码|口令|密钥|验证码)(\s*(?:是|为)?\s*[:：=]?\s*)([A-Za-z0-9!@#$%^&*._\-]{4,})"), r"\1\2***"),
    (re.compile(r"(?i)\b(admin|root|username|user)(\s*/\s*)([A-Za-z0-9!@#$%^&*._\-]{4,})"), r"\1\2***"),
    (re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)"), r"\1****\2"),
]


def _looks_secret(v: str) -> bool:
    """普通词不当口令；含数字或符号的才可能是真口令。"""
    if not (4 <= len(v) <= 32):
        return False
    if _IPV4.match(v) or v.lower() in _NOT_SECRET:
        return False
    return any(c.isdigit() for c in v) or any(c in "!@#$%^&*._-" for c in v)


def secrets_clear() -> None:
    _SECRETS.clear()


def collect_secrets(text: str) -> None:
    """收集强上下文里的口令值，供全库抹除。"""
    if not text:
        return
    for pat in _SECRET_FINDERS:
        for m in pat.finditer(text):
            v = m.group(1).strip(".,;:，。）)【】[]")
            if _looks_secret(v):
                _SECRETS.add(v)
    for pat in _PREFIX_SECRETS:
        for m in pat.finditer(text):
            _SECRETS.add(m.group(0))


def redact_inplace(text: str) -> str:
    for pat, rep in _REDACT_RES:
        text = pat.sub(rep, text)
    for pat in _PREFIX_SECRETS:
        text = pat.sub("***", text)
    return text


def redact(text: str) -> str:
    if not text:
        return text
    text = redact_inplace(text)
    for v in sorted(_SECRETS, key=len, reverse=True):
        if v in text:
            text = text.replace(v, "***")
    return text


def redact_page(text: str) -> str:
    """页面用：YAML 头只做就地脱敏，正文才允许全局抹除。

    YAML 键名（source_sessions、status）绝不能被全局名单碰到，否则页结构直接失效。
    """
    m = re.match(r"^(---\n.*?\n---\n)(.*)$", text, re.S)
    if not m:
        return redact(text)
    return redact_inplace(m.group(1)) + redact(m.group(2))


def scan(text: str) -> list[str]:
    """返回命中的疑似凭据（已脱敏的 *** 不算）。供 lint 与自检使用。"""
    hits: list[str] = []
    for pat in _PREFIX_SECRETS:
        hits += [m.group(0) for m in pat.finditer(text)]
    for pat, _rep in _REDACT_RES[:3]:
        for m in pat.finditer(text):
            groups = [g for g in m.groups() if g]
            val = groups[-1] if groups else ""
            if val and not val.startswith("*") and len(val) >= 4:
                hits.append(m.group(0))
    for m in re.finditer(r"(?<!\d)1[3-9]\d{6}\d{4}(?!\d)", text):
        hits.append(m.group(0))
    return hits
