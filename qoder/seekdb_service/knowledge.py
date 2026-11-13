"""Rule knowledge base for the Qoder track.

The documents are **generated from ``reviewer.RULES``**, so the knowledge base
and the rule engine can never drift apart: every rule that the engine can fire
has exactly one knowledge entry, carrying the same title / message /
suggestion.

The entries are what gets written into seekdb (``qoder_rule_knowledge``) and
what the reviewer retrieves as the *basis* of a finding, so seekdb takes part in
the review itself instead of merely storing the result.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

# Real-world counter examples / fixed versions, one pair per rule.
# They are used as the "典型反例 / 修复示例" part of the knowledge entry.
EXAMPLES: dict[str, tuple[str, str]] = {
    "OB-001": (
        "UPDATE orders SET status = 'ARCHIVED';",
        "UPDATE orders SET status = 'ARCHIVED' WHERE id = 42;",
    ),
    "OB-002": (
        "SELECT o.id FROM orders o JOIN customers c;",
        "SELECT o.id FROM orders o JOIN customers c ON o.customer_id = c.id;",
    ),
    "OB-003": (
        "CREATE TABLE orders (id BIGINT, name VARCHAR(64));",
        "CREATE TABLE orders (id BIGINT PRIMARY KEY, name VARCHAR(64));",
    ),
    "OB-004": (
        "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id;",
        "SELECT o.id, o.created_at, c.city FROM orders o JOIN customers c ON o.customer_id = c.id;",
    ),
    "OB-005": (
        "SELECT id FROM customers WHERE city LIKE '%杭州%';",
        "SELECT id FROM customers WHERE city LIKE '杭州%';",
    ),
    "OB-006": (
        "SELECT id FROM orders WHERE DATE(created_at) = '2026-01-01';",
        "SELECT id FROM orders WHERE created_at >= '2026-01-01' AND created_at < '2026-01-02';",
    ),
    "OB-007": (
        "SELECT id FROM orders ORDER BY id LIMIT 20, 200000;",
        "SELECT id FROM orders WHERE id > :last_seen_id ORDER BY id LIMIT 100;",
    ),
    "OB-008": (
        "SELECT id FROM orders WHERE status NOT IN ('PAID') AND tag != 'vip';",
        "SELECT id FROM orders WHERE (status <> 'PAID' OR status IS NULL) AND (tag <> 'vip' OR tag IS NULL);",
    ),
    "OB-009": (
        "SELECT id FROM orders WHERE user_id IN (1, 2, 3, ... 80 more ids ...);",
        "SELECT id FROM orders WHERE user_id IN (:id1, :id2) /* 参数化 + 批量表关联 */;",
    ),
    "OB-010": (
        "SELECT id FROM orders FOR UPDATE;",
        "SELECT id FROM orders WHERE id = 42 FOR UPDATE;",
    ),
    "OB-011": (
        "SELECT id FROM orders WHERE status = 'NEW' UNION SELECT id FROM orders WHERE status = 'PAID';",
        "SELECT id FROM orders WHERE status IN ('NEW', 'PAID');",
    ),
    "OB-012": (
        "DELETE FROM audit_log WHERE created_at < '2025-01-01';",
        "TRUNCATE TABLE audit_log;",
    ),
    "OB-013": (
        "SELECT id FROM orders WHERE customer_id = 42;",
        "EXPLAIN SELECT id FROM orders WHERE customer_id = 42; /* 先看执行计划再上线 */",
    ),
    "OB-014": (
        "SELECT id FROM orders WHERE user_id = '42';",
        "SELECT id FROM orders WHERE user_id = 42;",
    ),
    "OB-015": (
        "SELECT COUNT(1) FROM orders WHERE status = 'NEW';",
        "SELECT COUNT(*) FROM orders WHERE status = 'NEW';",
    ),
}


def _rule_text(rule: Any, bad: str, good: str) -> str:
    level = {"error": "阻断", "warn": "警告", "info": "提示"}.get(rule.level, rule.level)
    keywords = "、".join(rule.keywords) if rule.keywords else "（不限关键词，全量匹配）"
    return (
        f"规则 {rule.id}｜{rule.title}\n"
        f"级别：{level}\n"
        f"判定说明：{rule.message}\n"
        f"修复建议：{rule.suggestion}\n"
        f"触发关键词：{keywords}\n"
        f"典型反例：{bad}\n"
        f"修复示例：{good}"
    )


def build_documents() -> list[dict[str, Any]]:
    """One knowledge document per rule, ready for ``SeekdbStore.upsert()``."""
    from reviewer import RULES  # noqa: PLC0415  (local import: keeps run.py import-light)

    documents: list[dict[str, Any]] = []
    for rule in RULES:
        bad, good = EXAMPLES.get(
            rule.id,
            (f"-- 触发 {rule.id} 的语句", f"-- 修复 {rule.id} 后的语句"),
        )
        documents.append(
            {
                "id": rule.id,
                "text": _rule_text(rule, bad, good),
                "metadata": {
                    "title": f"{rule.id} {rule.title}",
                    "source": "rules/sql_review_rules.md",
                    "rule_id": rule.id,
                    "level": rule.level,
                },
            }
        )
    return documents


def query_for(rule_id: str, title: str) -> str:
    """A natural-language question used to retrieve the basis of one finding."""
    return f"{title} 这条规则是怎么判定的，应该怎么修？"
