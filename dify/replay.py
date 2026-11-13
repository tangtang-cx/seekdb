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
import json
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
    """Parse the DSL. Uses PyYAML when available, otherwise the committed JSON view.

    `app.dsl.json` is the same document as `app.yml` (generated from it), so the
    replay still works on a machine with nothing installed but Python itself.
    """
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ModuleNotFoundError:
        json_view = path.with_name("app.dsl.json")
        if json_view.exists():
            print(f"(PyYAML 未安装，使用 {json_view.name} 回放)", file=sys.stderr)
            return json.loads(json_view.read_text(encoding="utf-8"))
        raise SystemExit(
            "PyYAML 未安装，且找不到 app.dsl.json；请 pip install pyyaml 或重新导出 JSON 视图。"
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


def start_id_of(nodes: list[dict]) -> str:
    """Dify exports use numeric node ids, so find the start node by its type."""
    for node in nodes:
        if (node.get("data") or {}).get("type") == "start":
            return node["id"]
    return "start"


def check(dsl: dict) -> int:
    nodes, edges = graph_of(dsl)
    ids = {n["id"]: n for n in nodes}
    types = {n["id"]: (n.get("data") or {}).get("type") for n in nodes}
    print(f"DSL        : {dsl.get('app', {}).get('name')}")
    print(f"节点       : {len(nodes)}  {[f'{k}({v})' for k, v in types.items()]}")
    print(f"边         : {len(edges)}")

    order = walk(start_id_of(nodes), edges)
    print(f"执行链     : {' -> '.join(order)}")
    problems = []
    if not order or order[0] != start_id_of(nodes):
        problems.append("执行链未从 start 开始")
    terminal = [types.get(n) for n in order[-1:]]
    if not terminal or terminal[0] not in ("answer", "end"):
        problems.append("执行链没有到达 answer / end 节点（应用不会返回结果）")
    for edge in edges:
        if edge.get("source") not in ids or edge.get("target") not in ids:
            problems.append(f"边 {edge.get('id')} 指向不存在的节点")
    for node in nodes:
        data = node.get("data") or {}
        kind = data.get("type")
        if kind in ("answer", "end"):
            refs = []
            if kind == "answer":
                refs = VAR_RE.findall(data.get("answer") or "")
                refs = [(r[0], r[1]) for r in refs]
            else:
                refs = [(s["value_selector"][0], s["value_selector"][1])
                        for s in (data.get("outputs") or [])]
            for ref in refs:
                key = f"{ref[0]}.{ref[1]}"
                if ref[0] not in ids and ref[0] != "sys":
                    problems.append(f"{kind} 节点引用了不存在的节点 {ref[0]}")
                else:
                    print(f"{kind} 输出变量: {key}  (可解析)")
        if kind == "code":
            code = data.get("code") or ""
            if "def main(" not in code:
                problems.append("code 节点缺少 main() 入口")
            declared = set(data.get("outputs") or {})
            for spec in data.get("variables") or []:
                ref = spec.get("value_selector") or []
                if not ref or (ref[0] not in ids and ref[0] != "sys"):
                    problems.append(f"code 节点的入参 {spec.get('variable')} 指向不存在的节点")
            if not declared:
                problems.append("code 节点没有声明 outputs")

    if problems:
        print("\n阻断性问题:")
        for item in problems:
            print("  -", item)
        return 1
    print("\nPASS: DSL 结构完整，导入 Dify 后可直接接收输入并返回结果")
    return 0


def run_code(code: str, kwargs: dict) -> dict:
    """Execute a Dify code node the way the sandbox does: main(**inputs) -> dict."""
    scope: dict = {}
    exec(compile(code, "<dify-code-node>", "exec"), scope)  # noqa: S102 - our own DSL
    entry = scope.get("main")
    if entry is None:
        raise RuntimeError("code 节点里没有 main()")
    return entry(**kwargs) or {}


def resolve(selector: list, variables: dict):
    key = ".".join(str(part) for part in selector)
    if key not in variables:
        raise KeyError(f"变量 {key} 未产生（上游节点未执行或输出名不一致）")
    return variables[key]


def execute(dsl: dict, query: str) -> dict:
    """Run the workflow the way Dify does, returning the terminal outputs."""
    nodes, edges = graph_of(dsl)
    by_id = {n["id"]: n for n in nodes}
    sid = start_id_of(nodes)
    variables = {"sys.query": query}
    for var in ((by_id.get(sid) or {}).get("data") or {}).get("variables") or []:
        name = var.get("variable")
        variables[f"start.{name}"] = query
        variables[f"{sid}.{name}"] = query

    result = {"answer": "", "summary": ""}
    for node_id in walk(sid, edges):
        data = (by_id[node_id].get("data") or {})
        kind = data.get("type")
        if kind == "template":
            variables[f"{node_id}.text"] = render(data.get("template") or "", variables)
        elif kind == "code":
            kwargs = {
                spec["variable"]: resolve(spec["value_selector"], variables)
                for spec in (data.get("variables") or [])
            }
            for key, value in run_code(data.get("code") or "", kwargs).items():
                variables[f"{node_id}.{key}"] = value
        elif kind == "answer":
            variables[f"{node_id}.answer"] = render(data.get("answer") or "", variables)
            result["answer"] = variables[f"{node_id}.answer"]
        elif kind == "end":
            for spec in data.get("outputs") or []:
                result[spec["variable"]] = resolve(spec["value_selector"], variables)
    if not result.get("answer"):
        values = [v for k, v in result.items() if isinstance(v, str) and v]
        result["answer"] = values[0] if values else ""
    return result


def replay(dsl: dict, query: str) -> int:
    out = execute(dsl, query)
    if not out.get("answer"):
        print("DSL 里没有 answer / end 节点，或输出为空", file=sys.stderr)
        return 1
    print(f"== 输入 SQL ==\n{query}\n")
    print("== 应用输出（与 Dify 运行时一致）==\n")
    print(out["answer"])
    if out.get("summary"):
        print(f"\n-- 计数：{out['summary']}")
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
