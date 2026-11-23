"""Novelty card renderer: every claim traceable, disclosure mandatory."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

DISCLOSURE = (
    "本卡片由 MatScout（AI 辅助工具）生成初稿：文献元数据经 OpenAlex/Crossref 核验，"
    "相似度为透明词面打分。查新结论与可行性判断**需领域专家人工复核后方可使用**；"
    "AI 不署名、不替代科研判断。对外使用时请按目标期刊/机构政策披露 AI 辅助情况。"
)
COVERAGE_NOTE = (
    "检索局限：MVP 仅覆盖 OpenAlex/Crossref 开放元数据与摘要；词面相似度可能漏掉语义近似工作；"
    "中文文献、专利、会议摘要覆盖有限；预印本与期刊正式版可能重复计数。结论不代表穷尽查新。"
)
FEAS_LABELS = {"equipment": "设备/仪器", "compute": "算力", "precursors": "前驱体/原料",
               "timeline": "时间尺度", "other": "其他条件"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _authors(row_authors_json: str) -> str:
    authors = json.loads(row_authors_json or "[]")
    if not authors:
        return "作者未知"
    return ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")


def _link(doi, url) -> str:
    if doi:
        return f"[{doi}](https://doi.org/{doi})"
    return url or "（无 DOI）"


def _badge(verified, via) -> str:
    return f"✔ 已核验（{via}）" if verified else "⚠ 未核验（不得作为结论依据）"


def render_card(conn: sqlite3.Connection, project_id: int) -> str:
    proj = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    assess = conn.execute("SELECT * FROM assessments WHERE project_id=? ORDER BY id DESC LIMIT 1",
                          (project_id,)).fetchone()
    closest = conn.execute("SELECT * FROM evidence WHERE project_id=? AND kind='closest_work' ORDER BY id DESC LIMIT 1",
                           (project_id,)).fetchone()
    searches = conn.execute("SELECT * FROM searches WHERE project_id=? ORDER BY id", (project_id,)).fetchall()
    evidence = conn.execute("SELECT id, kind, created_at FROM evidence WHERE project_id=? ORDER BY id",
                            (project_id,)).fetchall()

    L: list[str] = []
    L.append(f"# 查新卡片 ｜ {proj['name']}")
    L.append("")
    L.append(f"- 项目 ID：{project_id} ｜ 领域：{proj['field'] or '未指定'}")
    L.append(f"- 创建时间：{proj['created_at']} ｜ 卡片生成：{_now()}")
    L.append("- **复核状态：待人工复核（未经专家确认不得作为立项/投稿依据）**")
    L.append("")
    L.append("## 1. 想法描述")
    L.append(proj["idea"])
    L.append("")
    L.append("## 2. 查新结论")
    if assess:
        L.append(f"**{assess['verdict']}**（置信度：{assess['confidence']}）")
        L.append("")
        L.append(assess["summary"])
    else:
        L.append("（尚未提交查新评估；以下仅为检索相似度排序，不构成查新结论。）")
    L.append("")
    L.append("## 3. 最接近的工作")
    deltas_by_paper = {}
    if assess:
        for d in json.loads(assess["deltas_json"]):
            deltas_by_paper.setdefault(d["paper_id"], []).append(d)
    if closest:
        ranking = json.loads(closest["content_json"]).get("ranking", [])
        for i, item in enumerate(ranking, 1):
            r = conn.execute("SELECT * FROM papers WHERE id=?", (item["paper_id"],)).fetchone()
            if not r:
                continue
            L.append(f"### [{i}] {r['title']}")
            L.append(f"{_authors(r['authors_json'])} ｜ {r['venue'] or '来源未知'} {r['year'] or ''} ｜ "
                     f"{_link(r['doi'], r['url'])} ｜ {_badge(r['verified'], r['verified_via'])} ｜ paper_id={r['id']}")
            L.append(f"- 词面相似度：{item['score']}（匹配词：{', '.join(item['matched_terms'][:12]) or '无'}）")
            for d in deltas_by_paper.get(r["id"], []):
                L.append(f"- 重合点：{d['claim']}")
                L.append(f"- 差异点：{d['difference']}")
            L.append("")
    else:
        L.append("（尚未运行 find_closest_work。）")
        L.append("")
    L.append("## 4. 可行性清单（待专家确认）")
    feas = json.loads(assess["feasibility_json"]) if assess and assess["feasibility_json"] else {}
    if feas:
        for key, label in FEAS_LABELS.items():
            if feas.get(key):
                L.append(f"- **{label}**：{feas[key]}")
        for k, v in feas.items():
            if k not in FEAS_LABELS and v:
                L.append(f"- **{k}**：{v}")
    else:
        L.append("（待填写：设备/算力/前驱体/时间尺度/其他条件。）")
    L.append("")
    L.append("## 5. 风险与不确定项")
    risks = json.loads(assess["risks_json"]) if assess and assess["risks_json"] else []
    for rk in risks:
        L.append(f"- {rk}")
    if assess and assess["limitations"]:
        L.append(f"- {assess['limitations']}")
    L.append(f"- {COVERAGE_NOTE}")
    L.append("")
    L.append("## 6. 证据附录")
    if searches:
        L.append("| 检索 ID | 检索式 | 来源 | 时间 (UTC) |")
        L.append("|---|---|---|---|")
        for s in searches:
            L.append(f"| {s['id']} | {s['query']} | OpenAlex | {s['created_at']} |")
    else:
        L.append("（无检索记录。）")
    L.append("")
    L.append("证据链：" + ", ".join(f"#{e['id']}({e['kind']})" for e in evidence))
    L.append("")
    L.append("## 7. AI 使用披露")
    L.append(DISCLOSURE)
    L.append("")
    return "\n".join(L)

