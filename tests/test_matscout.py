"""Offline unit tests (mocked HTTP). Run: python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from matscout import db, http, similarity, sources
from matscout.core import CoreError, MatScout

http.MIN_INTERVAL = {}  # speed up tests; no real network in this file


def fake_work(doi="10.1234/demo", title="High-entropy chloride solid electrolytes for lithium metal batteries",
              year=2024):
    return {
        "id": "https://openalex.org/W1", "doi": f"https://doi.org/{doi}",
        "display_name": title, "publication_year": year,
        "authorships": [{"author": {"display_name": "A. Researcher"}}, {"author": {"display_name": "B. Scientist"}}],
        "primary_location": {"source": {"display_name": "Nature Materials"}},
        "abstract_inverted_index": {"chloride": [0], "solid": [1], "electrolyte": [2], "high-entropy": [3]},
    }


def crossref_message(doi="10.1234/demo", title="High-entropy chloride solid electrolytes for lithium metal batteries"):
    return {"message": {"DOI": doi, "title": [title], "issued": {"date-parts": [[2024]]},
                        "container-title": ["Nature Materials"],
                        "author": [{"given": "A.", "family": "Researcher"}]}}


class TestSources(unittest.TestCase):
    def test_abstract_reconstruction(self):
        self.assertEqual(sources.reconstruct_abstract({"hello": [0], "world": [1]}), "hello world")
        self.assertIsNone(sources.reconstruct_abstract(None))

    def test_doi_normalization(self):
        self.assertEqual(sources.normalize_doi("https://doi.org/10.1038/X"), "10.1038/x")
        self.assertEqual(sources.normalize_doi("doi: 10.1038/x "), "10.1038/x")
        self.assertIsNone(sources.normalize_doi(""))


class TestSimilarity(unittest.TestCase):
    def test_stopwords_and_scoring(self):
        toks = similarity.tokenize("novel high-entropy chloride solid electrolyte materials")
        self.assertNotIn("materials", toks)
        self.assertNotIn("novel", toks)
        self.assertIn("chloride", toks)
        s = similarity.score_pair(toks, "High-entropy chloride solid electrolytes", "chloride solid electrolyte high-entropy")
        self.assertGreater(s["score"], 0.5)
        self.assertIn("chloride", s["matched_terms"])

    def test_chinese_bigrams(self):
        toks = similarity.tokenize("固态电解质")
        self.assertIn("固态", toks)


class TestCoreGates(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def _ms(self, fetch):
        return MatScout(self.conn, fetch=fetch)

    def test_upsert_dedupe_by_doi_and_title(self):
        ms = self._ms(None)
        p = sources._norm_openalex(fake_work())
        id1 = ms._upsert_paper(p)
        id2 = ms._upsert_paper(p)
        self.assertEqual(id1, id2)
        p2 = dict(p, doi=None)  # same title, no DOI -> title_hash dedupe
        self.assertEqual(ms._upsert_paper(p2), id1)

    def test_verify_then_assessment_gate(self):
        def fetch(url):
            if "api.crossref.org/works/10.1234" in url:
                return crossref_message()
            raise http.HttpError(url, 404, "not found")
        ms = self._ms(fetch)
        proj = ms.create_project("demo", "固态电解质", "high-entropy chloride solid electrolyte lithium metal")
        pid = proj["project_id"]
        v = ms.verify_citation("10.1234/demo", project_id=pid)
        self.assertTrue(v["verified"])
        paper_id = v["paper"]["paper_id"]
        # unverified paper must be rejected (G2)
        raw_id = ms._upsert_paper(sources._norm_openalex(fake_work(doi="10.9999/unverified", title="Unverified work")))
        with self.assertRaises(CoreError):
            ms.save_novelty_assessment(pid, "增量创新", "medium", "summary",
                                       [{"claim": "c", "paper_id": raw_id, "difference": "d"}])
        # verified paper accepted
        res = ms.save_novelty_assessment(pid, "增量创新", "medium", "已有氯化物电解质框架，差异在高熵化",
                                         [{"claim": "同属氯化物固态电解质", "paper_id": paper_id,
                                           "difference": "引入高熵阳离子策略"}],
                                         feasibility={"equipment": "手套箱+烧结炉（待专家确认）"},
                                         risks=["界面副反应未知"], limitations="仅 OpenAlex 覆盖")
        self.assertTrue(res["accepted"])

    def test_verify_not_found_never_fabricates(self):
        def fetch(url):
            raise http.HttpError(url, 404, "not found")
        ms = self._ms(fetch)
        v = ms.verify_citation("10.0000/does-not-exist")
        self.assertFalse(v["verified"])
        self.assertIn("请勿", v["reason"])

    def test_search_network_error_is_structured(self):
        def fetch(url):
            raise http.HttpError(url, None, "connection reset")
        ms = self._ms(fetch)
        with self.assertRaises(CoreError) as ctx:
            ms.search_literature("perovskite")
        self.assertIn("检索失败", str(ctx.exception))

    def test_full_pipeline_and_card(self):
        def fetch(url):
            if url.startswith("https://api.openalex.org/works?"):
                return {"results": [fake_work()]}
            if "api.crossref.org/works/10.1234" in url:
                return crossref_message()
            raise http.HttpError(url, 404, "not found")
        ms = self._ms(fetch)
        pid = ms.create_project("demo", "固态电解质", "high-entropy chloride solid electrolyte lithium metal")["project_id"]
        ms.search_literature("high-entropy chloride solid electrolyte", project_id=pid)
        closest = ms.find_closest_work(pid, k=5)
        self.assertEqual(len(closest["ranked"]), 1)
        paper_id = closest["ranked"][0]["paper_id"]
        ms.verify_citation("10.1234/demo", project_id=pid)
        ms.save_novelty_assessment(pid, "增量创新", "medium", "summary",
                                   [{"claim": "重合", "paper_id": paper_id, "difference": "差异"}])
        card = ms.render_novelty_card(pid)["markdown"]
        for needle in ["查新卡片", "10.1234/demo", "待人工复核", "AI 使用披露", "证据附录", "增量创新"]:
            self.assertIn(needle, card)
        ev = ms.list_evidence(pid)
        kinds = {e["kind"] for e in ev["evidence"]}
        self.assertTrue({"search", "closest_work", "verification", "assessment", "card_rendered"} <= kinds)


class TestMCPProtocol(unittest.TestCase):
    def test_stdio_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, PYTHONPATH=SRC, MATSCOUT_DB=str(Path(td) / "t.db"))
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "create_project", "arguments": {"name": "p", "field": "f", "idea": "i"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "get_paper", "arguments": {"paper_id": 999}}},
                {"jsonrpc": "2.0", "id": 5, "method": "bogus/method"},
            ]
            proc = subprocess.run([sys.executable, "-m", "matscout.mcp_server"],
                                  input="\n".join(json.dumps(m) for m in msgs) + "\n",
                                  capture_output=True, text=True, encoding="utf-8", timeout=60, env=env, cwd=str(Path(SRC).parent))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
            by_id = {m.get("id"): m for m in lines}
            self.assertEqual(len(lines), 5)  # notification gets no response
            self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-06-18")
            self.assertEqual(len(by_id[2]["result"]["tools"]), 8)
            self.assertIn("project_id", by_id[3]["result"]["content"][0]["text"])
            self.assertTrue(by_id[4]["result"]["isError"])
            self.assertEqual(by_id[5]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()

