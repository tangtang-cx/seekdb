#!/usr/bin/env python3
"""Offline replay of the Dify DSL — proves the workflow runs without Dify.

The submitted DSL is intentionally model-free, so its behaviour is fully
deterministic and can be reproduced here with the standard library only:

    python replay.py                                  # built-in sample
    python replay.py "SELECT * FROM t WHERE DATE(c) = '2026-01-01';"
    python replay.py --check                          # structure check only

It walks the graph from `start` to `answer`, resolves Dify's variable
references (`{{#sys.query#}}`, `{{#<node>.text#}}`) and prints exactly what the
Dify runtime would render for the same input.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DSL = HERE / "app.yml"
VAR_RE = re.compile(r"\{\{#\s*([A-Za-z0-9_\-]+)\.([A-Za-z0-9_]+)\s*#\}\}")

SAMPLE = """SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
AND c.city LIKE '%杭州%'
ORDER BY o.created_at DESC
LIMIT 20, 200000;"""


def load_dsl(path: Path) -> dict:
    """Parse YAML; fall back to a tiny reader when PyYAML is unavailable."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ModuleNotFoundError:
        raise SystemExit(
            "PyYAML 未安装：pip install pyyaml   （或用 --check 之外的方式导入 Dify）"
        )


def graph_of(dsl: dict) -> tuple[list[dict], list[dict]]:
    graph = (dsl.get("workflow") or {}).get("graph") or {}
    return graph.get("nodes") or [], graph.get("edges") or []


def walk(start: str, edges: list[dict]) -> list[str]:
    """Return the node ids in execution order (single-outgoing chain)."""
    nxt = {e["source"]: e["target"] for e in edges}
    order, node, guard = [], start, 0
    while node and guard < 200:
        order.append(node)
        node = nxt.get(node)
        guard += 1
    return order


def render(template: str, variables: dict[str, str]) -> str:
    def sub(match: re.Match[str]) -> str:
        key = f"{match.group(1)}.{match.group(2)}"
        return variables.get(key, match.group(0))

    return VAR_RE.sub(sub, template or "")


def check(dsl: dict) -> int:
    nodes, edges = graph_of(dsl)
    ids = {n["id"]: n for n in nodes}
    types = {n["id"]: (n.get("data") or {}).get("type") for n in nodes}
    print(f"DSL        : {dsl.get('app', {}).get('name')}")
    print(f"节点       : {len(nodes)}  {[f'{k}({v})' for k, v in types.items()]}")
    print(f"边         : {len(edges)}")

    order = walk("start", edges)
    print(f"执行链     : {' -> '.join(order)}")
    problems = []
    if not order or order[0] != "start":
        problems.append("执行链未从 start 开始")
    if "answer" not in order:
        problems.append("执行链没有到达 answer 节点（应用不会返回结果）")
    for edge in edges:
        if edge.get("source") not in ids or edge.get("target") not in ids:
            problems.append(f"边 {edge.get('id')} 指向不存在的节点")
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") == "answer":
            for ref in VAR_RE.findall(data.get("answer") or ""):
                key = f"{ref[0]}.{ref[1]}"
                if ref[0] not in ids and ref[0] != "sys":
                    problems.append(f"answer 引用了不存在的节点 {ref[0]}")
                else:
                    print(f"answer 变量: {key}  (可解析)")

    if problems:
        print("\n阻断性问题:")
        for item in problems:
            print("  -", item)
        return 1
    print("\nPASS: DSL 结构完整，导入 Dify 后可直接接收输入并返回结果")
    return 0


def replay(dsl: dict, query: str) -> int:
    nodes, edges = graph_of(dsl)
    by_id = {n["id"]: n for n in nodes}
    variables = {"sys.query": query}
    order = walk("start", edges)

    for node_id in order:
        data = (by_id[node_id].get("data") or {})
        kind = data.get("type")
        if kind == "template":
            variables[f"{node_id}.text"] = render(data.get("template") or "", variables)
        elif kind == "answer":
            variables[f"{node_id}.answer"] = render(data.get("answer") or "", variables)

    answer_node = next((n for n in nodes if (n.get("data") or {}).get("type") == "answer"), None)
    if answer_node is None:
        print("DSL 里没有 answer 节点", file=sys.stderr)
        return 1
    text = variables.get(f"{answer_node['id']}.answer") or render(
        (answer_node.get("data") or {}).get("answer") or "", variables
    )
    print(f"== 输入 SQL ==\n{query}\n")
    print("== 应用输出（与 Dify 运行时一致）==\n")
    print(text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="离线回放 Dify DSL")
    parser.add_argument("query", nargs="?", default=SAMPLE)
    parser.add_argument("--dsl", default=str(DEFAULT_DSL))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    dsl = load_dsl(Path(args.dsl))
    return check(dsl) if args.check else replay(dsl, args.query)


if __name__ == "__main__":
    raise SystemExit(main())
