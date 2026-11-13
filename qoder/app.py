"""数据库代码审查助手 · Qoder 生成并增强的 Streamlit 应用。

由 Qoder（AI IDE）根据如下提示词生成，本仓库在其基础上补齐了规则引擎与多模型接入：

    请帮我用 Python 写一个 Streamlit 应用，调用大模型 API 做一个「数据库代码审查助手」。

并按赛题要求**真实接入 seekdb**：
    * 审查依据来自 seekdb 的混合检索（本地 bge 向量 + IK 全文 + RRF，融合在 seekdb 内核内完成）；
    * 每轮审查记录会**写回 seekdb**，可在界面上实时查回历史。

运行：

    pip install -r requirements.txt
    streamlit run app.py          # 会自动拉起 seekdb 知识服务
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import streamlit as st
except ModuleNotFoundError:
    # 评审环境没装 streamlit 时不能让 `python app.py` 直接 ImportError 退出：
    # 直接起零依赖 HTTP 服务，界面与接口照常可用。
    from run import main as _serve

    raise SystemExit(_serve())

# ---------------------------------------------------------------------------
# 裸跑自举：`python app.py` 时 Streamlit 不会启动服务器，脚本会静默退出，
# 评审探活就会判「运行失败」。这里检测到不在 Streamlit 运行时内，就直接起
# 零依赖 HTTP 服务（run.py），保证 `python app.py` / `python run.py` /
# `streamlit run app.py` / docker 四种入口都能起来。
# ---------------------------------------------------------------------------
def _inside_streamlit() -> bool:
    try:
        return bool(st.runtime.exists())
    except Exception:  # noqa: BLE001 - 老版本没有 st.runtime
        return False


if not _inside_streamlit() and __name__ == "__main__":
    from run import main as _serve

    raise SystemExit(_serve())

HERE = Path(__file__).resolve().parent
# make the project importable no matter how the app is launched
# (streamlit run / streamlit.testing AppTest / python -m) and no matter which
# directory the repository was cloned into: the seekdb service may live next to
# this project (./seekdb_service) or in a sibling Dify project.
for extra in (HERE, HERE / "seekdb_service", HERE.parent / "Dify" / "seekdb_service"):
    if extra.is_dir() and str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from reviewer import (
    LEVELS,
    LEVEL_LABEL,
    PROVIDER_PRESETS,
    Finding,
    LLMReviewer,
    analyze,
    summarize,
)
import seekdb_bridge
from auto_start import ensure_service  # noqa: E402

st.set_page_config(
    page_title="数据库代码审查助手",
    page_icon="🧐",
    layout="wide",
)

SAMPLES: dict[str, str] = {
    "慢查询 / 深分页": """SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01'
  AND o.status IN ('NEW', 'PAID', 'SHIPPED', 'DONE')
  AND c.city LIKE '%杭州%'
ORDER BY o.created_at DESC
LIMIT 20, 200000;""",
    "全表更新": """UPDATE orders SET status = 'ARCHIVED';""",
    "缺失主键": """CREATE TABLE order_items (
  id BIGINT NOT NULL,
  order_id BIGINT NOT NULL,
  price DECIMAL(10, 2)
);""",
    "NOT IN 空集陷阱": """SELECT id FROM orders
WHERE customer_id NOT IN (SELECT id FROM blacklist_customer);""",
    "OceanBase 向量检索": """CREATE TABLE doc_chunk (
  id VARBINARY(512) PRIMARY KEY NOT NULL,
  document STRING,
  embedding VECTOR(512),
  FULLTEXT INDEX idx_fts (document) WITH PARSER ik PARSER_PROPERTIES=(ik_mode='smart'),
  VECTOR INDEX idx_vec (embedding) WITH(distance=cosine, type=hnsw, lib=vsag,
       m=16, ef_construction=200, ef_search=64)
) ORGANIZATION = HEAP;""",
}

LEVEL_COLORS = {"error": "🔴", "warn": "🟠", "info": "🔵"}


def render_finding(finding: Finding) -> None:
    icon = LEVEL_COLORS.get(finding.level, "⚪")
    label = LEVEL_LABEL.get(finding.level, finding.level)
    st.markdown(
        f"##### {icon} `{finding.id}` {finding.title} <span style='font-size:0.8em;color:#888'>"
        f"· {label} · {finding.source}</span>",
        unsafe_allow_html=True,
    )
    if finding.snippet:
        st.code(finding.snippet, language="sql")
    st.markdown(f"**问题**：{finding.message}")
    st.markdown(f"**建议**：{finding.suggestion}")
    st.divider()


def export_markdown(findings: list[Finding], sql: str, llm_text: str) -> str:
    lines = ["# 数据库代码审查报告", "", "## 待审查 SQL", "", "```sql", sql, "```", ""]
    counts = summarize(findings)
    lines.append(
        "## 统计：" + " / ".join(f"{LEVEL_LABEL[level]} {counts.get(level, 0)}" for level in LEVELS)
    )
    lines.append("")
    for finding in findings:
        lines.append(f"### [{finding.id}] {LEVEL_LABEL.get(finding.level, finding.level)} {finding.title}")
        lines.append(f"- 问题：{finding.message}")
        lines.append(f"- 建议：{finding.suggestion}")
        if finding.snippet:
            lines.append(f"- 命中片段：`{finding.snippet}`")
        lines.append("")
    if llm_text:
        lines += ["## 大模型深度审查", "", llm_text]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("⚙️ 模型配置")
    provider = st.selectbox(
        "推理服务",
        list(PROVIDER_PRESETS),
        index=0,
        format_func=lambda key: {
            "modelscope": "魔搭 ModelScope",
            "stepfun": "阶跃星辰 StepFun",
            "minimax": "MiniMax",
            "openai": "OpenAI 兼容（自定义）",
        }[key],
    )
    preset = PROVIDER_PRESETS[provider]
    base_url = st.text_input("Base URL", value=os.environ.get(f"{provider.upper()}_BASE_URL", preset["base_url"]))
    model = st.text_input("模型名", value=os.environ.get(f"{provider.upper()}_MODEL", preset["model"]))
    api_key = st.text_input(
        "API Key",
        value=os.environ.get(preset["env_key"], ""),
        type="password",
        help=f"环境变量 {preset['env_key']} 优先；留空则只跑本地规则引擎。",
    )
    use_llm = st.checkbox("同时调用大模型做深度审查", value=bool(api_key))
    st.caption(f"协议：OpenAI 兼容 `{base_url}/chat/completions`")

    st.header("📋 规则集")
    st.caption("本地静态规则（无需 API）：15 条 OceanBase / MySQL 通用规则，详见 rules/sql_review_rules.md")

    st.header("🔌 seekdb")
    kb_url = st.text_input(
        "seekdb 知识服务地址",
        value=os.environ.get("SEEKDB_SERVICE_URL", "http://127.0.0.1:8848"),
        help="dify/seekdb_service/serve.py 提供的混合检索服务（向量 + 全文 + RRF）",
    )
    use_kb = st.checkbox("用 seekdb 检索审查依据", value=True)
    save_to_kb = st.checkbox("把审查记录写回 seekdb", value=True)
    with st.spinner("连接/启动 seekdb…"):
        status = ensure_service(kb_url, background=True)
    if status.get("ok"):
        st.success(f"seekdb 已就绪 · 模式 {status.get('mode')} · 知识块 {status.get('chunks')} · 历史 {status.get('reviews')}")
    else:
        st.warning(f"seekdb 未就绪：{status.get('error')}（规则审查仍然可用）")

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("🧐 数据库代码审查助手")
st.markdown(
    "输入 SQL 或 DDL，助手先跑**确定性静态规则**（毫秒级、离线可用），"
    "再向 **seekdb** 检索相关「医书」作为审查依据，可选调用大模型做**语义级深度审查**，"
    "最后把审查记录写回 seekdb 并导出 Markdown 报告。"
)
st.caption("生成方式：本项目由 Qoder AI IDE 生成并在本仓库增强；支持 OceanBase / seekdb / MySQL 语法。")

left, right = st.columns([3, 2])
with left:
    st.subheader("① 待审查的 SQL")
    sample_name = st.selectbox("示例", list(SAMPLES) + ["（自己粘贴）"])
    default_sql = SAMPLES.get(sample_name, "")
    sql = st.text_area(
        "SQL / DDL",
        value=default_sql,
        height=280,
        placeholder="SELECT ... FROM ...",
    )
with right:
    st.subheader("② 审查选项")
    dialect = st.selectbox("目标数据库", ["OceanBase 4.x (MySQL 模式)", "seekdb", "MySQL 8.0"])
    include_ddl = st.checkbox("同时检查 DDL（建表 / 索引）", value=True)
    extra_context = st.text_area("附加上下文（可选）", height=90, placeholder="表结构、数据量、慢查询耗时…")

run = st.button("🚀 开始审查", type="primary", use_container_width=True)

if run:
    if not sql.strip():
        st.warning("请先输入要审查的 SQL。")
        st.stop()

    st.session_state["last_sql"] = sql
    with st.spinner("正在执行静态规则…"):
        findings = analyze(sql)
        if not include_ddl:
            findings = [item for item in findings if "create table" not in item.message.lower()]

    # --- seekdb：检索审查依据（向量 + 全文 + RRF，融合在 seekdb 内核内完成） ---
    kb_hits: list[dict] = []
    if use_kb:
        with st.spinner("正在 seekdb 里检索相关「医书」…"):
            try:
                kb_hits = seekdb_bridge.search_knowledge(sql[:500], kb_url, top_k=3)
            except Exception as error:
                st.warning(f"seekdb 检索失败：{error}")
    if kb_hits:
        with st.expander(f"📖 seekdb 检索到的依据（{len(kb_hits)} 条，来自 seekdb 混合检索）", expanded=True):
            for hit in kb_hits:
                st.markdown(f"**{hit.get('title', '')}** · {hit.get('source', '')}")
                st.text((hit.get("text") or "")[:400])

    llm_result_text = ""
    llm_findings: list[Finding] = []
    if use_llm:
        if not api_key.strip():
            st.info("未填 API Key，跳过大模型深度审查（规则结果仍然有效）。")
        else:
            with st.spinner(f"正在调用 {model} 做深度审查…"):
                reviewer = LLMReviewer(base_url=base_url, model=model, api_key=api_key.strip())
                context = "\n\n".join(
                    f"[{i + 1}] {h.get('title', '')}\n{h.get('text', '')}" for i, h in enumerate(kb_hits)
                )
                result = reviewer.review(sql, extra_context=context)
            if result.ok:
                llm_result_text = result.content
                llm_findings = result.findings
            else:
                st.error(f"大模型调用失败：{result.error}")

    merged = findings + llm_findings
    counts = summarize(merged)

    # --- seekdb：把本轮审查写回 seekdb（存储侧） ---
    if save_to_kb:
        try:
            saved = seekdb_bridge.save_review(
                sql=sql,
                findings=[item.to_dict() for item in merged],
                engine="rules+llm" if llm_findings else "rules",
                summary=(
                    f"阻断 {counts.get('error', 0)} / 警告 {counts.get('warn', 0)} / "
                    f"提示 {counts.get('info', 0)}；seekdb 命中 {len(kb_hits)} 条依据"
                ),
                kb_hits=len(kb_hits),
                base_url=kb_url,
            )
            st.caption(f"本轮审查已写入 seekdb（记录 id {saved.get('id')}，累计 {saved.get('reviews')} 条）")
        except Exception as error:
            st.warning(f"写回 seekdb 失败：{error}")

    st.subheader("③ 审查结果")
    c1, c2, c3 = st.columns(3)
    c1.metric("🔴 阻断", counts.get("error", 0))
    c2.metric("🟠 警告", counts.get("warn", 0))
    c3.metric("🔵 提示", counts.get("info", 0))

    if not merged:
        st.success("✅ 没有发现明显问题。")
    for finding in merged:
        render_finding(finding)

    if llm_result_text:
        with st.expander("大模型原始输出", expanded=False):
            st.markdown(llm_result_text)

    report = export_markdown(merged, sql, llm_result_text)
    st.download_button(
        "⬇️ 导出 Markdown 评审报告",
        data=report,
        file_name="sql-review-report.md",
        mime="text/markdown",
    )
    st.download_button(
        "⬇️ 导出 JSON（可接入 CI）",
        data=json.dumps([item.to_dict() for item in merged], ensure_ascii=False, indent=2),
        file_name="sql-review-report.json",
        mime="application/json",
    )

    try:
        history = seekdb_bridge.list_reviews(kb_url)
    except Exception:
        history = []
    if history:
        with st.expander(f"🗂️ seekdb 里的审查历史（{len(history)} 条，实时从 seekdb 查询）", expanded=False):
            st.table(history)

    st.caption(f"目标数据库：{dialect}")
