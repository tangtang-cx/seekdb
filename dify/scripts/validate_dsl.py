#!/usr/bin/env python3
"""Validate a Dify app DSL against the schema Dify itself exports (version 0.6.0).

Reference: langgenius/dify -> cli/test/e2e/fixtures/apps/echo-chat.yml and
reasoning-chat.yml (the DSLs Dify's own CI imports and runs).

    python scripts/validate_dsl.py app.yml
    python scripts/validate_dsl.py app.yml app-rag.template.yml

Exit code 0 = no blocking error, 1 = blocking error found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    print("需要 PyYAML：pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)

NODE_TYPES = {
    "start",
    "llm",
    "answer",
    "knowledge-retrieval",
    "http-request",
    "template",
    "code",
    "tool",
    "if-else",
    "iteration",
    "question-classifier",
    "parameter-extractor",
    "agent",
    "doc-extractor",
    "list-operator",
    "variable-aggregator",
    "assigner",
    "end",
}

REQUIRED_FEATURES = {
    "file_upload",
    "opening_statement",
    "retriever_resource",
    "sensitive_word_avoidance",
    "speech_to_text",
    "suggested_questions",
    "suggested_questions_after_answer",
    "text_to_speech",
}

VARIABLE_RE = re.compile(r"\{\{#([a-zA-Z0-9_\-]+)\.(?:text|result)#\}\}")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)


def validate(path: Path) -> Report:
    report = Report()
    # 模板文件（*.template.yml）允许留空知识库：它必须先挂知识库才能用，
    # 但它不是「直接导入即用」的主应用，所以降级为警告。
    is_template = "template" in path.name.lower()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        report.error(f"无法读取文件：{error}")
        return report

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as error:
        report.error(f"YAML 解析失败：{error}")
        return report

    if not isinstance(data, dict):
        report.error("顶层必须是 mapping")
        return report

    # ---- top level ------------------------------------------------------
    for key in ("app", "dependencies", "kind", "version", "workflow"):
        if key not in data:
            report.error(f"缺少顶层字段 `{key}`")

    app = data.get("app")
    if not isinstance(app, dict):
        report.error("`app` 必须是 mapping")
        return report

    for key in ("mode", "name", "icon", "icon_background"):
        if not app.get(key):
            report.error(f"`app.{key}` 缺失或为空（缺失会导致导入后应用类型无法判定）")
    if app.get("mode") not in {"advanced-chat", "advanced-chatflow", "agent-chat", "workflow", "chat"}:
        report.warn(f"`app.mode` 的值不常见：{app.get('mode')!r}")
    if not isinstance(data.get("dependencies"), list):
        report.error("`dependencies` 必须是 list（例如 `dependencies: []`）")

    if data.get("kind") != "app":
        report.error(f"`kind` 必须是 `app`，当前是 {data.get('kind')!r}")
    if not str(data.get("version", "")).startswith("0."):
        report.warn(f"`version` 看起来不是 DSL 版本号：{data.get('version')!r}")

    # ---- workflow -------------------------------------------------------
    workflow = data.get("workflow")
    if not isinstance(workflow, dict):
        report.error("`workflow` 必须是 mapping")
        return report

    for key in ("conversation_variables", "environment_variables", "rag_pipeline_variables"):
        if not isinstance(workflow.get(key), list):
            report.error(f"`workflow.{key}` 缺失或不是 list（写 `[]` 即可）")

    features = workflow.get("features")
    if not isinstance(features, dict):
        report.error("`workflow.features` 必须是 mapping")
    else:
        missing = REQUIRED_FEATURES - set(features)
        if missing:
            report.error(f"`features` 缺少字段：{sorted(missing)}")
        upload = features.get("file_upload")
        if isinstance(upload, dict):
            config = upload.get("fileUploadConfig")
            if config is not None and not isinstance(config, dict):
                report.error("`features.file_upload.fileUploadConfig` 必须是 mapping（不要嵌套两层）")
            if isinstance(config, dict) and "fileUploadConfig" in config:
                report.error("`fileUploadConfig` 里又出现了一个 `fileUploadConfig`，schema 非法")
            if upload.get("enabled") and upload.get("allowed_file_types") == ["custom"]:
                if not upload.get("allowed_file_extensions"):
                    report.error("自定义文件类型必须给出 `allowed_file_extensions`")

    graph = workflow.get("graph")
    if not isinstance(graph, dict):
        report.error("`workflow.graph` 必须是 mapping")
        return report

    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not nodes:
        report.error("`graph.nodes` 缺失或为空")
        return report
    if not isinstance(edges, list) or not edges:
        report.error("`graph.edges` 缺失或为空")
        return report

    node_ids: set[str] = set()
    node_types: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            report.error("node 必须是 mapping")
            continue
        node_id = node.get("id")
        if not node_id:
            report.error("node 缺少 `id`")
            continue
        if node_id in node_ids:
            report.error(f"node id 重复：{node_id}")
        node_ids.add(node_id)
        if node.get("type") != "custom":
            report.error(f"node `{node_id}` 的 `type` 必须是 `custom`")
        for key in ("position", "sourcePosition", "targetPosition"):
            if key not in node:
                report.warn(f"node `{node_id}` 缺少 `{key}`（不阻断，但建议补齐）")
        data_block = node.get("data")
        if not isinstance(data_block, dict):
            report.error(f"node `{node_id}` 缺少 `data`")
            continue
        node_type = data_block.get("type")
        node_types[node_id] = node_type
        if node_type not in NODE_TYPES:
            report.error(f"node `{node_id}` 的类型未知：{node_type!r}")
        if not data_block.get("title"):
            report.warn(f"node `{node_id}` 缺少标题")

        if node_type == "knowledge-retrieval":
            dataset_ids = data_block.get("dataset_ids")
            if not dataset_ids:
                message = (
                    f"知识检索节点 `{node_id}` 的 `dataset_ids` 为空 —— "
                    "这是最典型的「阻断主要流程」错误：导入后该节点无效，主流程跑不起来"
                )
                if is_template:
                    report.warn(message + "（本文件是模板，导入后需挂知识库或用 setup_knowledge.py 自动绑定）")
                else:
                    report.error(message)
            if not isinstance(data_block.get("multiple_retrieval_config"), dict):
                report.warn(f"知识检索节点 `{node_id}` 缺少 `multiple_retrieval_config`")

        if node_type == "http-request":
            method = str(data_block.get("method", "")).lower()
            url = str(data_block.get("url", "")).strip()
            if not url:
                report.error(f"HTTP 节点 `{node_id}` 缺少 `url`")
            elif not url.startswith(("http://", "https://")):
                report.error(f"HTTP 节点 `{node_id}` 的 url 非法：{url!r}")
            if method not in {"get", "post", "put", "patch", "delete", "head"}:
                report.error(f"HTTP 节点 `{node_id}` 的 method 非法：{method!r}")
            body = data_block.get("body")
            if isinstance(body, dict) and body.get("type") == "json":
                items = body.get("data")
                if not isinstance(items, list) or not items:
                    report.error(f"HTTP 节点 `{node_id}` 的 json body 为空")
                else:
                    for item in items:
                        if not isinstance(item, dict) or "value" not in item:
                            report.error(f"HTTP 节点 `{node_id}` 的 body 条目缺少 `value`")
                        elif "id" not in item:
                            report.error(f"HTTP 节点 `{node_id}` 的 body 条目缺少 `id`")
            elif method in {"post", "put", "patch"}:
                report.warn(f"HTTP 节点 `{node_id}` 是 {method} 但没有 json body")
            report.note(f"HTTP 节点 `{node_id}` 会真实调用 {url}")

        if node_type == "llm":
            model = data_block.get("model")
            if not isinstance(model, dict):
                report.error(f"LLM 节点 `{node_id}` 缺少 `model`")
            else:
                for key in ("provider", "name", "mode"):
                    if key not in model:
                        report.error(f"LLM 节点 `{node_id}` 的 `model.{key}` 缺失")
                if model.get("mode") != "chat":
                    report.warn(f"LLM 节点 `{node_id}` 的 `model.mode` 应为 `chat`")
                provider = model.get("provider")
                if provider:
                    report.warn(
                        f"LLM 节点 `{node_id}` 硬编码了 provider={provider!r}："
                        "目标工作区若未安装该模型供应商，节点会失效并阻断主流程；"
                        "留空则回退到工作区默认模型"
                    )
                else:
                    report.note(f"LLM 节点 `{node_id}` 使用工作区默认模型（导入后不会因缺 provider 报错）")
            if not isinstance(data_block.get("prompt_template"), list):
                report.error(f"LLM 节点 `{node_id}` 缺少 `prompt_template`")
            if "memory" not in data_block:
                report.warn(f"LLM 节点 `{node_id}` 缺少 `memory`（多轮对话将不可用）")

        if node_type == "answer":
            answer = data_block.get("answer", "")
            for ref in VARIABLE_RE.findall(str(answer)):
                if ref not in node_ids:
                    report.error(f"回复节点 `{node_id}` 引用了不存在的节点：{ref}")

    # ---- edges ----------------------------------------------------------
    node_type_by_id = {node_id: kind for node_id, kind in node_types.items()}
    for edge in edges:
        if not isinstance(edge, dict):
            report.error("edge 必须是 mapping")
            continue
        for key in ("id", "source", "target", "sourceHandle", "targetHandle"):
            if key not in edge:
                report.error(f"edge 缺少 `{key}`：{edge.get('id')}")
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids:
            report.error(f"edge `{edge.get('id')}` 的 source 不存在：{source}")
        if target not in node_ids:
            report.error(f"edge `{edge.get('id')}` 的 target 不存在：{target}")
        if edge.get("sourceHandle") != "source":
            report.warn(f"edge `{edge.get('id')}` 的 `sourceHandle` 应为 `source`")
        # Dify only imports edges that carry `type: custom` and data.sourceType/targetType.
        # Without them the nodes run unconnected and the answer node resolves to an
        # empty string (observed on the published app: predecessor_node_id = null).
        if edge.get("type") != "custom":
            report.error(
                f"edge `{edge.get('id')}` 缺少 `type: custom` —— "
                "Dify 导入时会丢弃这条边，节点之间不连通，回答节点会输出空字符串"
            )
        data = edge.get("data")
        if not isinstance(data, dict):
            report.error(
                f"edge `{edge.get('id')}` 缺少 `data.sourceType/targetType` —— "
                "同样会导致边被丢弃、主流程断开"
            )
        else:
            expected_source = node_type_by_id.get(source)
            expected_target = node_type_by_id.get(target)
            if data.get("sourceType") != expected_source:
                report.error(
                    f"edge `{edge.get('id')}` 的 sourceType 应为 {expected_source!r}，"
                    f"当前 {data.get('sourceType')!r}"
                )
            if data.get("targetType") != expected_target:
                report.error(
                    f"edge `{edge.get('id')}` 的 targetType 应为 {expected_target!r}，"
                    f"当前 {data.get('targetType')!r}"
                )

    # ---- connectivity ---------------------------------------------------
    starts = [node_id for node_id, kind in node_types.items() if kind == "start"]
    if not starts:
        report.error("缺少 start 节点")
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        if isinstance(edge, dict) and edge.get("source") in outgoing:
            outgoing[edge["source"]].append(edge.get("target"))

    visited: set[str] = set()
    stack = list(starts)
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        stack.extend(outgoing.get(current, []))
    unreachable = node_ids - visited
    if unreachable:
        report.error(f"以下节点从 start 不可达（会阻断主流程）：{sorted(unreachable)}")

    for node_id, kind in node_types.items():
        if kind not in {"end", "answer"} and not outgoing.get(node_id):
            report.error(f"节点 `{node_id}`（{kind}）没有任何出边，是孤立节点")

    if report.errors:
        return report

    # ---- soft checks ----------------------------------------------------
    if "knowledge-retrieval" not in node_types.values():
        report.note("该应用不依赖知识库：导入到任意 Dify 实例都能直接跑通，不会因空知识库阻断")
    llm_nodes = [node_id for node_id, kind in node_types.items() if kind == "llm"]
    for node_id in llm_nodes:
        for node in nodes:
            if node.get("id") != node_id:
                continue
            context = node.get("data", {}).get("context", {})
            if context.get("enabled"):
                selector = context.get("variable_selector") or []
                if not selector or selector[0] not in node_ids:
                    report.error(f"LLM 节点 `{node_id}` 开启了 context，但 variable_selector 无效")
    return report


def main(argv: list[str]) -> int:
    targets = [Path(item) for item in argv[1:]] or [Path(__file__).resolve().parent.parent / "app.yml"]
    failed = False
    for target in targets:
        print(f"\n=== {target} ===")
        report = validate(target)
        for message in report.errors:
            print(f"  [阻断] {message}")
        for message in report.warnings:
            print(f"  [警告] {message}")
        for message in report.notes:
            print(f"  [提示] {message}")
        if report.errors:
            failed = True
            print("  结果：存在阻断主流程的错误")
        else:
            print("  结果：通过，无阻断性错误")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
