"""Business core shared by MCP server and CLI.

Hard gates enforced HERE (server side), never delegated to model goodwill:
  G1: a citation enters conclusions only after verify_citation succeeds.
  G2: every assessment delta must reference an existing, verified paper_id.
"""
from __future__ import annotations

import json
import re
import sqlite3

from . import db, http, similarity, sources
from .card import render_card

VERDICTS = ("高度新颖", "增量创新", "已有近似工作", "高度重复")
CONFIDENCES = ("low", "medium", "high")


class CoreError(Exception):
    """Structured, user-facing business error (never crash the host)."""


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


class MatScout:
    def __init__(self, conn: sqlite3.Connection | None = None, fetch=None):
        self.conn = conn if conn is not None else db.connect()
        self.fetch = fetch  # injectable HTTP fetch for offline tests

    # ---------- internal helpers ----------
    def _project(self, project_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise CoreError(f"项目不存在: project_id={project_id}")
        return row

    def _upsert_paper(self, p: dict) -> int:
        doi = sources.normalize_doi(p.get("doi"))
        row = None
        if doi:
            row = self.conn.execute("SELECT id FROM papers WHERE doi=?", (doi,)).fetchone()
        if row is None:
            row = self.conn.execute("SELECT id FROM papers WHERE title_hash=?",
                                    (sources.title_hash(p["title"]),)).fetchone()
        if row:
            pid = row["id"]
            self.conn.execute(
                """UPDATE papers SET
                     abstract=COALESCE(NULLIF(abstract,''), ?),
                     venue=COALESCE(NULLIF(venue,''), ?),
                     year=COALESCE(year, ?),
                     doi=COALESCE(doi, ?)
                   WHERE id=?""",
                (p.get("abstract"), p.get("venue"), p.get("year"), doi, pid),
            )
            self.conn.commit()
            return pid
        cur = self.conn.execute(
            """INSERT INTO papers(doi,title,title_hash,abstract,year,venue,authors_json,url,source,raw_json)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (doi, p["title"], sources.title_hash(p["title"]), p.get("abstract"), p.get("year"),
             p.get("venue"), json.dumps(p.get("authors") or [], ensure_ascii=False),
             p.get("url"), p.get("source"), json.dumps(p.get("raw") or {}, ensure_ascii=False)),
        )
        self.conn.commit()
        return cur.lastrowid

    def _mark_verified(self, paper_id: int, via: str) -> None:
        self.conn.execute("UPDATE papers SET verified=1, verified_via=? WHERE id=?", (via, paper_id))
        self.conn.commit()

    def _add_evidence(self, project_id: int, kind: str, content: dict,
                      paper_ids: list[int] | None = None, actor: str = "matscout") -> int:
        cur = self.conn.execute(
            "INSERT INTO evidence(project_id,kind,content_json,paper_ids_json,actor) VALUES(?,?,?,?,?)",
            (project_id, kind, json.dumps(content, ensure_ascii=False),
             json.dumps(paper_ids or []), actor),
        )
        self.conn.commit()
        return cur.lastrowid

    def _paper_view(self, row: sqlite3.Row, snippet: int = 300) -> dict:
        abstract = row["abstract"] or ""
        return {
            "paper_id": row["id"],
            "doi": row["doi"],
            "title": row["title"],
            "year": row["year"],
            "venue": row["venue"],
            "authors": json.loads(row["authors_json"] or "[]"),
            "url": row["url"],
            "verified": bool(row["verified"]),
            "verified_via": row["verified_via"],
            "abstract_snippet": abstract[:snippet] + ("…" if len(abstract) > snippet else ""),
        }

    # ---------- MCP tools ----------
    def create_project(self, name: str, field: str, idea: str) -> dict:
        if not (name and idea):
            raise CoreError("name 与 idea 必填")
        cur = self.conn.execute("INSERT INTO projects(name,field,idea) VALUES(?,?,?)", (name, field, idea))
        self.conn.commit()
        return {"project_id": cur.lastrowid, "name": name, "field": field, "idea": idea}

    def search_literature(self, query: str, project_id: int | None = None,
                          year_from: int | None = None, year_to: int | None = None,
                          limit: int = 10) -> dict:
        if not query or not query.strip():
            raise CoreError("query 必填（建议英文检索式，见 SKILL.md）")
        try:
            papers = sources.openalex_search(query, year_from=year_from, year_to=year_to,
                                             limit=limit, conn=self.conn, fetch=self.fetch)
        except http.HttpError as e:
            raise CoreError(f"检索失败（网络/上游服务）：{e}。请稍后重试或更换检索词；不得凭记忆补文献。")
        ids = [self._upsert_paper(p) for p in papers]
        search_id = None
        if project_id is not None:
            self._project(project_id)
            cur = self.conn.execute(
                "INSERT INTO searches(project_id,query,filters_json) VALUES(?,?,?)",
                (project_id, query, json.dumps({"year_from": year_from, "year_to": year_to, "limit": limit})),
            )
            search_id = cur.lastrowid
            for rank, pid in enumerate(ids, 1):
                self.conn.execute("INSERT OR IGNORE INTO search_results(search_id,paper_id,rank) VALUES(?,?,?)",
                                  (search_id, pid, rank))
            self.conn.commit()
            self._add_evidence(project_id, "search",
                               {"query": query, "source": "openalex", "count": len(ids),
                                "year_from": year_from, "year_to": year_to}, ids)
        views = [self._paper_view(self.conn.execute("SELECT * FROM papers WHERE id=?", (i,)).fetchone())
                 for i in ids]
        return {"search_id": search_id, "source": "openalex", "count": len(views), "papers": views}

    def verify_citation(self, identifier: str, project_id: int | None = None) -> dict:
        s = (identifier or "").strip()
        if not s:
            raise CoreError("identifier 必填（DOI 或完整标题）")
        is_doi = bool(re.match(r"^10\.\d{4,9}/", s)) or "doi.org/" in s.lower()
        p, via = None, None
        try:
            if is_doi:
                doi = sources.normalize_doi(s)
                p = sources.crossref_by_doi(doi, conn=self.conn, fetch=self.fetch)
                via = "crossref"
                if p is None:
                    p = sources.openalex_by_doi(doi, conn=self.conn, fetch=self.fetch)
                    via = "openalex"
            else:
                cands = sources.crossref_title_candidates(s, conn=self.conn, fetch=self.fetch)
                target = similarity.tokenize(s)
                for c in cands:
                    if _jaccard(target, similarity.tokenize(c["title"])) >= 0.9 and c.get("doi"):
                        p, via = c, "crossref-title-match"
                        break
                if p is None:
                    return {"verified": False, "identifier": s,
                            "reason": "标题未能在 Crossref 高置信匹配；请勿在结论中引用。",
                            "candidates": [{"doi": c.get("doi"), "title": c["title"], "year": c.get("year")}
                                           for c in cands]}
        except http.HttpError as e:
            raise CoreError(f"核验失败（网络/上游服务）：{e}。核验未完成前该文献不得进入结论。")
        if p is None:
            return {"verified": False, "identifier": s,
                    "reason": "Crossref 与 OpenAlex 均未收录；请勿在结论中引用该文献。"}
        pid = self._upsert_paper(p)
        self._mark_verified(pid, via)
        if project_id is not None:
            self._project(project_id)
            self._add_evidence(project_id, "verification",
                               {"identifier": s, "verified_via": via}, [pid])
        row = self.conn.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
        return {"verified": True, "verified_via": via, "paper": self._paper_view(row, snippet=1000)}

    def find_closest_work(self, project_id: int, idea_text: str | None = None, k: int = 5) -> dict:
        proj = self._project(project_id)
        idea = (idea_text or proj["idea"]).strip()
        rows = self.conn.execute(
            """SELECT DISTINCT p.* FROM papers p
               JOIN search_results sr ON sr.paper_id=p.id
               JOIN searches s ON s.id=sr.search_id
               WHERE s.project_id=?""", (project_id,)).fetchall()
        auto_search = False
        if not rows:
            self.search_literature(idea, project_id=project_id, limit=15)
            auto_search = True
            rows = self.conn.execute(
                """SELECT DISTINCT p.* FROM papers p
                   JOIN search_results sr ON sr.paper_id=p.id
                   JOIN searches s ON s.id=sr.search_id
                   WHERE s.project_id=?""", (project_id,)).fetchall()
        idea_toks = similarity.tokenize(idea)
        scored = []
        for r in rows:
            s = similarity.score_pair(idea_toks, r["title"], r["abstract"])
            view = self._paper_view(r)
            view.update(s)
            scored.append(view)
        scored.sort(key=lambda x: (-x["score"], -(x["year"] or 0)))
        top = scored[:max(1, min(int(k), 10))]
        self._add_evidence(project_id, "closest_work",
                           {"idea_used": idea, "auto_search": auto_search,
                            "ranking": [{"paper_id": t["paper_id"], "score": t["score"],
                                         "matched_terms": t["matched_terms"]} for t in top]},
                           [t["paper_id"] for t in top])
        return {"idea_used": idea, "candidates_total": len(scored), "auto_search": auto_search,
                "scoring": "lexical overlap + 0.5*title_overlap（透明词面打分，语义近似可能漏检）",
                "ranked": top}

    def save_novelty_assessment(self, project_id: int, verdict: str, confidence: str,
                                summary: str, deltas: list, feasibility: dict | None = None,
                                risks: list | None = None, limitations: str | None = None) -> dict:
        self._project(project_id)
        if verdict not in VERDICTS:
            raise CoreError(f"verdict 必须是 {VERDICTS} 之一")
        if isinstance(confidence, (int, float)):
            confidence = "low" if confidence < 0.4 else ("medium" if confidence < 0.7 else "high")
        if confidence not in CONFIDENCES:
            raise CoreError(f"confidence 必须是 {CONFIDENCES} 之一")
        if not summary or not summary.strip():
            raise CoreError("summary 必填（一句话结论依据）")
        if not deltas:
            raise CoreError("deltas 必填：至少一条「最接近工作」的重合点/差异点分析")
        bad = []
        for i, d in enumerate(deltas):
            if not isinstance(d, dict) or not d.get("claim") or not d.get("difference"):
                raise CoreError(f"deltas[{i}] 需包含 claim（重合点）与 difference（差异点）")
            pid = d.get("paper_id")
            row = self.conn.execute("SELECT verified FROM papers WHERE id=?", (pid,)).fetchone()
            if row is None or not row["verified"]:
                bad.append(pid)
        if bad:
            raise CoreError(
                f"硬门拒绝(G2)：paper_id {bad} 不存在或未通过 verify_citation。"
                "请先逐条核验文献，再提交评估；禁止引用未核验文献。")
        cur = self.conn.execute(
            """INSERT INTO assessments(project_id,verdict,confidence,summary,deltas_json,
                                       feasibility_json,risks_json,limitations)
               VALUES(?,?,?,?,?,?,?,?)""",
            (project_id, verdict, confidence, summary, json.dumps(deltas, ensure_ascii=False),
             json.dumps(feasibility or {}, ensure_ascii=False), json.dumps(risks or [], ensure_ascii=False),
             limitations),
        )
        self.conn.commit()
        self._add_evidence(project_id, "assessment", {"assessment_id": cur.lastrowid, "verdict": verdict},
                           [d["paper_id"] for d in deltas], actor="host-agent")
        return {"assessment_id": cur.lastrowid, "accepted": True,
                "note": "已入库；卡片仍需人工复核后才算定稿。"}

    def render_novelty_card(self, project_id: int) -> dict:
        self._project(project_id)
        md = render_card(self.conn, project_id)
        has = self.conn.execute("SELECT 1 FROM assessments WHERE project_id=? LIMIT 1",
                                (project_id,)).fetchone() is not None
        self._add_evidence(project_id, "card_rendered", {"has_assessment": has})
        return {"markdown": md, "has_assessment": has, "review_status": "pending_human_review"}

    def list_evidence(self, project_id: int) -> dict:
        self._project(project_id)
        rows = self.conn.execute("SELECT * FROM evidence WHERE project_id=? ORDER BY id", (project_id,)).fetchall()
        return {"project_id": project_id, "count": len(rows),
                "evidence": [{"evidence_id": r["id"], "kind": r["kind"], "actor": r["actor"],
                              "created_at": r["created_at"], "paper_ids": json.loads(r["paper_ids_json"] or "[]"),
                              "content": json.loads(r["content_json"])} for r in rows]}

    def get_paper(self, paper_id: int | None = None, doi: str | None = None) -> dict:
        if paper_id is not None:
            row = self.conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        elif doi:
            row = self.conn.execute("SELECT * FROM papers WHERE doi=?", (sources.normalize_doi(doi),)).fetchone()
        else:
            raise CoreError("paper_id 或 doi 至少提供一个")
        if not row:
            raise CoreError("文献不在本地证据库；请先 search_literature 或 verify_citation")
        view = self._paper_view(row, snippet=4000)
        view["abstract"] = row["abstract"]
        return view

    def purge_project(self, project_id: int) -> dict:
        self._project(project_id)
        self.conn.execute("DELETE FROM evidence WHERE project_id=?", (project_id,))
        self.conn.execute("DELETE FROM assessments WHERE project_id=?", (project_id,))
        self.conn.execute("DELETE FROM search_results WHERE search_id IN (SELECT id FROM searches WHERE project_id=?)",
                          (project_id,))
        self.conn.execute("DELETE FROM searches WHERE project_id=?", (project_id,))
        self.conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        self.conn.commit()
        return {"purged": project_id, "note": "项目与证据已物理删除；papers 全局缓存保留（不含项目关联）。"}
