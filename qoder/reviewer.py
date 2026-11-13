"""Deterministic SQL review engine + OpenAI-compatible LLM reviewer.

Two layers:

* :func:`analyze` -- regex/regex-based static rules.  Deterministic, offline,
  no API key needed.  This is what makes the tool usable on the first click.
* :class:`LLMReviewer` -- optional deep review through any OpenAI-compatible
  endpoint (Qoder-compatible, StepFun, MiniMax, ModelScope, ...).  The HTTP
  call is done with the standard library so the app only needs Streamlit.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

LEVELS = ("error", "warn", "info")
LEVEL_LABEL = {"error": "阻断", "warn": "警告", "info": "提示"}


@dataclass
class Finding:
    """One review result."""

    id: str
    level: str
    title: str
    message: str
    suggestion: str
    snippet: str = ""
    source: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Rule:
    id: str
    level: str
    title: str
    pattern: str
    message: str
    suggestion: str
    keywords: tuple[str, ...] = ()
    group: int = field(default=0, compare=False)
    matcher: Any = None
    """Optional custom checker: ``matcher(sql: str) -> re.Match | None``.

    Used by rules that need to *count* something (e.g. commas in an IN list).
    A counting regex would backtrack catastrophically on long lists, so those
    rules scan the list with a linear regex and count in Python instead.
    """

    def compile(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.IGNORECASE | re.DOTALL)


def _match_long_in_list(sql: str) -> re.Match[str] | None:
    """Flag ``IN (...)`` lists with more than 50 items (linear scan, no backtracking)."""
    for match in re.finditer(r"\bin\s*\(([^()]*)\)", sql, re.IGNORECASE):
        body = match.group(1)
        if body.count(",") + 1 > 50:
            return match
    return None


RULES: list[Rule] = [
    Rule(
        id="OB-001",
        level="error",
        title="UPDATE / DELETE 缺少 WHERE",
        pattern=r"\b(update|delete\s+from)\b(?![\s\S]{0,400}?\bwhere\b)",
        message="语句没有 WHERE 条件，会更新/删除全表数据。",
        suggestion="补全 WHERE 条件；生产环境先在同事务里 SELECT 校验影响行数。",
        keywords=("update", "delete"),
    ),
    Rule(
        id="OB-002",
        level="error",
        title="JOIN 缺少关联条件",
        pattern=r"\bjoin\b(?![^;]{0,400}?\b(on|using)\b)",
        message="存在 JOIN 但没有 ON / USING，会产生笛卡尔积。",
        suggestion="补上 ON 关联条件，并确认两侧字段类型一致。",
        keywords=("join",),
    ),
    Rule(
        id="OB-003",
        level="error",
        title="建表缺少主键",
        pattern=r"\bcreate\s+(temporary\s+)?table\b(?![^;]{0,2000}?\bprimary\s+key\b)",
        message="建表语句里没有 PRIMARY KEY。",
        suggestion="加上 PRIMARY KEY（OceanBase 推荐 BIGINT 自增或有序主键，避免随机 UUID 主键）。",
        keywords=("create table",),
    ),
    Rule(
        id="OB-004",
        level="warn",
        title="SELECT * 列出全部列",
        pattern=r"\bselect\s+\*",
        message="SELECT * 会带来无效 IO、回表与 schema 变更风险。",
        suggestion="显式列出需要的列。",
    ),
    Rule(
        id="OB-005",
        level="warn",
        title="LIKE 前置通配符",
        pattern=r"\blike\s+'%",
        message="LIKE '%xxx' 无法使用索引，只能全表扫描。",
        suggestion="改成前缀匹配 LIKE 'xxx%'，或改用全文索引 / 倒排索引。",
    ),
    Rule(
        id="OB-006",
        level="warn",
        title="索引列被函数包裹",
        # 列名允许带表别名前缀（o.created_at）与空白，这是线上最常见的写法
        pattern=r"\b(where|and|or|on|group\s+by|order\s+by)\b[^;\n]{0,400}?\b(year|month|day|date|date_format|substring|left|right|lower|upper|concat|ifnull|if_null|trim)\s*\(\s*[a-z_][a-z0-9_]*(\s*\.\s*[a-z_][a-z0-9_]*)?\s*\)",
        message="在 WHERE 里对列使用函数会让普通索引失效。",
        suggestion="改成范围条件（>= / <），或建函数索引 / 生成列索引。",
    ),
    Rule(
        id="OB-007",
        level="warn",
        title="深分页 OFFSET",
        pattern=r"\blimit\s+\d+\s*,\s*(\d{4,})|\boffset\s+(\d{4,})\b",
        message="大 OFFSET 会让数据库扫描并丢弃前面的大量行。",
        suggestion="改成游标分页（WHERE id > last_id ORDER BY id LIMIT n）。",
    ),
    Rule(
        id="OB-008",
        level="warn",
        title="NOT IN / != 与 NULL 组合",
        pattern=r"\bnot\s+in\s*\(|\b(!=|<>)\b",
        message="NOT IN 子查询或 != 比较一旦遇到 NULL，结果集会被意外放大或清空。",
        suggestion="改用 NOT EXISTS，并把列定义为 NOT NULL。",
    ),
    Rule(
        id="OB-009",
        level="warn",
        title="IN 列表过长",
        pattern=r"\bin\s*\([^()]*\)",
        message="IN 列表过长会拖慢解析并撑大执行计划。",
        suggestion="改用 JOIN 临时表，或分批提交。",
        matcher=_match_long_in_list,
    ),
    Rule(
        id="OB-010",
        level="warn",
        title="SELECT ... FOR UPDATE 无 WHERE",
        pattern=r"\bfor\s+update\b(?![\s\S]{0,400}?\bwhere\b)",
        message="没有 WHERE 的 FOR UPDATE 会锁住整表。",
        suggestion="补 WHERE 条件缩小锁范围，并保证事务足够短。",
    ),
    Rule(
        id="OB-011",
        level="info",
        title="UNION 去重开销",
        pattern=r"\bunion\b(?!\s+all\b)",
        message="UNION 需要去重（排序或哈希），比 UNION ALL 慢。",
        suggestion="确认不需要去重时改成 UNION ALL。",
    ),
    Rule(
        id="OB-012",
        level="info",
        title="TRUNCATE 代替 DELETE 清表",
        pattern=r"\btruncate\s+(table\s+)?",
        message="TRUNCATE 是 DDL 语义，不能回滚且会重置自增。",
        suggestion="需要可回滚就用 DELETE；只是清空重建且能接受 DDL 时用 TRUNCATE。",
    ),
    Rule(
        id="OB-013",
        level="info",
        title="缺少执行计划验证",
        pattern=r"^\s*(select|with)\b",
        message="查询未附带执行计划验证信息。",
        suggestion="在 OceanBase 上用 EXPLAIN / EXPLAIN FORMAT=JSON 确认命中索引与扫描行数。",
    ),
    Rule(
        id="OB-014",
        level="info",
        title="疑似隐式类型转换",
        # 只报真反模式：数值口径的列被写成字符串字面量（id = '123'）。
        # 「id = 123」在无法获知列类型时属于正常写法，不报，避免误报噪声。
        pattern=r"\b([a-z_][a-z0-9_]*)\s*(?:=|<>|!=)\s*'(\d{1,18})'",
        message="数值列与字符串字面量比较会触发隐式类型转换，导致索引失效。",
        suggestion="让字面量类型与列类型一致：数值列直接写数字（id = 123），不要加引号。",
        keywords=("where",),
    ),
    Rule(
        id="OB-015",
        level="info",
        title="COUNT(*) 与 COUNT(1)",
        pattern=r"\bcount\s*\(\s*1\s*\)",
        message="现代 MySQL 协议 / OceanBase 中 COUNT(*) 已走索引优化，与 COUNT(1) 基本等价。",
        suggestion="统一写 COUNT(*) 语义更清晰。",
    ),
]

_COMMENT_RE = re.compile(r"(--[^\n]*|/\*[\s\S]*?\*/)")
_WS_RE = re.compile(r"\s+")


def normalize(sql: str) -> str:
    """Strip comments and collapse whitespace so the rules see clean SQL."""
    without_comments = _COMMENT_RE.sub(" ", sql)
    return _WS_RE.sub(" ", without_comments).strip()


def _snippet(sql: str, start: int, end: int, width: int = 90) -> str:
    left = max(0, start - width // 3)
    right = min(len(sql), end + width // 3)
    text = sql[left:right].strip()
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(sql) else ""
    return f"{prefix}{text}{suffix}"


def analyze(sql: str) -> list[Finding]:
    """Run every deterministic rule over ``sql``."""
    cleaned = normalize(sql)
    if not cleaned:
        return []

    findings: list[Finding] = []
    for rule in RULES:
        if rule.keywords:
            lowered = cleaned.lower()
            if not any(keyword in lowered for keyword in rule.keywords):
                continue
        match = rule.matcher(cleaned) if rule.matcher else rule.compile().search(cleaned)
        if not match:
            continue
        # OB-014 fires on any "col = 123"; keep it only when a WHERE clause exists.
        if rule.id == "OB-014" and "where" not in cleaned.lower():
            continue
        findings.append(
            Finding(
                id=rule.id,
                level=rule.level,
                title=rule.title,
                message=rule.message,
                suggestion=rule.suggestion,
                snippet=_snippet(cleaned, match.start(), match.end()),
            )
        )
    order = {level: index for index, level in enumerate(LEVELS)}
    findings.sort(key=lambda item: (order.get(item.level, 9), item.id))
    return findings


def summarize(findings: Iterable[Finding]) -> dict[str, int]:
    counts = {level: 0 for level in LEVELS}
    for finding in findings:
        counts[finding.level] = counts.get(finding.level, 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# LLM layer
# --------------------------------------------------------------------------- #

DEFAULT_SYSTEM_PROMPT = """你是 OceanBase / seekdb 的资深数据库评审工程师。
请对用户提交的 SQL 做代码审查，逐条给出问题。

输出格式：先输出一个 ```json 代码块，内容是数组，每个元素形如
{"level": "error|warn|info", "title": "简短的标题", "message": "为什么有问题",
 "suggestion": "怎么改（给出可直接复制的 SQL 片段）", "snippet": "命中的 SQL 片段"}
然后再输出 1-3 句整体结论。只输出 JSON 块和结论，不要写其它内容。"""

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "modelscope": {
        "base_url": "https://api-inference.modelscope.cn/v1",
        "model": "Qwen/Qwen3.5-27B",
        "env_key": "MODELSCOPE_API_KEY",
    },
    "stepfun": {
        "base_url": "https://api.stepfun.com/v1",
        "model": "step-2-16k",
        "env_key": "STEPFUN_API_KEY",
    },
    "minimax": {
        "base_url": "https://api.minimax.chat/v1",
        "model": "MiniMax-Text-01",
        "env_key": "MINIMAX_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
    },
}


@dataclass
class LLMResult:
    ok: bool
    content: str = ""
    findings: list[Finding] = field(default_factory=list)
    error: str = ""


class LLMReviewer:
    """Thin OpenAI-compatible chat client (standard library only)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        *,
        timeout: int = 90,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.system_prompt = system_prompt

    @classmethod
    def from_env(cls, provider: str = "modelscope") -> "LLMReviewer | None":
        preset = PROVIDER_PRESETS.get(provider)
        if preset is None:
            return None
        api_key = os.environ.get(preset["env_key"], "")
        if not api_key:
            return None
        return cls(
            base_url=os.environ.get(f"{provider.upper()}_BASE_URL", preset["base_url"]),
            model=os.environ.get(f"{provider.upper()}_MODEL", preset["model"]),
            api_key=api_key,
        )

    def review(self, sql: str, extra_context: str = "") -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": f"请审查下面的 SQL：\n\n```sql\n{sql}\n```"
                    + (f"\n\n补充上下文：{extra_context}" if extra_context else ""),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=ssl.create_default_context()
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            return LLMResult(ok=False, error=f"HTTP {error.code}: {error.read()[:300].decode('utf-8', 'replace')}")
        except Exception as error:  # network / DNS / TLS
            return LLMResult(ok=False, error=f"{type(error).__name__}: {error}")

        try:
            data = json.loads(raw.decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
        except Exception as error:
            return LLMResult(ok=False, error=f"unexpected response: {error}: {raw[:300]!r}")

        return LLMResult(ok=True, content=content, findings=parse_llm_findings(content))


def parse_llm_findings(content: str) -> list[Finding]:
    """Extract the JSON block produced by the model, if there is one."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    payload = match.group(1) if match else content
    start = payload.find("[")
    end = payload.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        items = json.loads(payload[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []

    findings: list[Finding] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        level = str(item.get("level", "info")).lower()
        if level not in LEVELS:
            level = "info"
        findings.append(
            Finding(
                id=f"LLM-{index + 1:02d}",
                level=level,
                title=str(item.get("title", "模型建议")),
                message=str(item.get("message", "")),
                suggestion=str(item.get("suggestion", "")),
                snippet=str(item.get("snippet", "")),
                source="llm",
            )
        )
    return findings
