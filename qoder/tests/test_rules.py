"""Unit tests for the deterministic SQL review rules.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reviewer import analyze  # noqa: E402


def rule_ids(sql: str) -> set[str]:
    return {finding.id for finding in analyze(sql)}


class RuleTriggerTests(unittest.TestCase):
    def test_update_without_where_is_blocking(self) -> None:
        self.assertIn("OB-001", rule_ids("UPDATE orders SET status = 'X';"))

    def test_update_with_where_is_not_flagged(self) -> None:
        self.assertNotIn("OB-001", rule_ids("UPDATE orders SET status = 'X' WHERE id = 1;"))

    def test_delete_without_where(self) -> None:
        self.assertIn("OB-001", rule_ids("DELETE FROM orders;"))

    def test_join_without_on(self) -> None:
        self.assertIn("OB-002", rule_ids("SELECT * FROM a JOIN b;"))

    def test_join_with_on_is_fine(self) -> None:
        self.assertNotIn("OB-002", rule_ids("SELECT * FROM a JOIN b ON a.id = b.id;"))

    def test_create_table_without_primary_key(self) -> None:
        sql = "CREATE TABLE t (id BIGINT NOT NULL, name VARCHAR(20));"
        self.assertIn("OB-003", rule_ids(sql))

    def test_create_table_with_primary_key(self) -> None:
        sql = "CREATE TABLE t (id BIGINT PRIMARY KEY, name VARCHAR(20));"
        self.assertNotIn("OB-003", rule_ids(sql))

    def test_select_star(self) -> None:
        self.assertIn("OB-004", rule_ids("SELECT * FROM t WHERE id = 1;"))

    def test_like_prefix_wildcard(self) -> None:
        self.assertIn("OB-005", rule_ids("SELECT id FROM t WHERE name LIKE '%abc';"))

    def test_function_on_column(self) -> None:
        self.assertIn("OB-006", rule_ids("SELECT id FROM t WHERE YEAR(created_at) = 2026;"))

    def test_date_function_on_column(self) -> None:
        # DATE(col) is the most common form; it used to slip through the rule
        self.assertIn("OB-006", rule_ids("SELECT id FROM t WHERE DATE(created_at) = '2026-01-01';"))
        self.assertIn(
            "OB-006",
            rule_ids("SELECT * FROM t WHERE DATE(c)='2026-01-01' LIMIT 20, 200000;"),
        )

    def test_deep_pagination(self) -> None:
        self.assertIn("OB-007", rule_ids("SELECT id FROM t LIMIT 20, 200000;"))

    def test_not_in_null_trap(self) -> None:
        self.assertIn("OB-008", rule_ids("SELECT id FROM t WHERE id NOT IN (SELECT id FROM b);"))

    def test_long_in_list(self) -> None:
        values = ",".join(str(index) for index in range(60))
        self.assertIn("OB-009", rule_ids(f"SELECT id FROM t WHERE id IN ({values});"))

    def test_for_update_without_where(self) -> None:
        self.assertIn("OB-010", rule_ids("SELECT id FROM t FOR UPDATE;"))

    def test_union_without_all(self) -> None:
        self.assertIn("OB-011", rule_ids("SELECT id FROM a UNION SELECT id FROM b;"))

    def test_union_all_is_fine(self) -> None:
        self.assertNotIn("OB-011", rule_ids("SELECT id FROM a UNION ALL SELECT id FROM b;"))

    def test_truncate(self) -> None:
        self.assertIn("OB-012", rule_ids("TRUNCATE TABLE orders;"))

    def test_explain_hint_on_select(self) -> None:
        self.assertIn("OB-013", rule_ids("SELECT id FROM t WHERE id = 1;"))

    def test_count_one_hint(self) -> None:
        self.assertIn("OB-015", rule_ids("SELECT COUNT(1) FROM t;"))

    def test_comments_are_ignored(self) -> None:
        sql = "-- UPDATE orders SET status='X';\n/* DELETE FROM orders; */\nSELECT id FROM t WHERE id=1;"
        self.assertNotIn("OB-001", rule_ids(sql))

    def test_seekdb_vector_ddl_passes(self) -> None:
        sql = """
        CREATE TABLE doc_chunk (
          id VARBINARY(512) PRIMARY KEY NOT NULL,
          document STRING,
          embedding VECTOR(512),
          FULLTEXT INDEX idx_fts (document) WITH PARSER ik PARSER_PROPERTIES=(ik_mode='smart'),
          VECTOR INDEX idx_vec (embedding) WITH(distance=cosine, type=hnsw, lib=vsag,
               m=16, ef_construction=200, ef_search=64)
        ) ORGANIZATION = HEAP;
        """
        ids = rule_ids(sql)
        self.assertNotIn("OB-003", ids)

    def test_findings_are_sorted_by_severity(self) -> None:
        sql = "SELECT * FROM a JOIN b; UPDATE t SET x = 1;"
        findings = analyze(sql)
        levels = [finding.level for finding in findings]
        self.assertEqual(levels, sorted(levels, key=lambda level: ("error", "warn", "info").index(level)))


if __name__ == "__main__":
    unittest.main()
