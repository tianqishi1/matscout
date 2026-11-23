#!/usr/bin/env python3
"""Live recall@10 evaluation (requires network).

Ground-truth DOIs are themselves re-verified via Crossref/OpenAlex first,
so the eval doubles as an anti-hallucination check on the eval set.
Run: python evals/run_eval.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matscout import db
from matscout.core import MatScout
from matscout.sources import normalize_doi


def main() -> int:
    cases = [json.loads(l) for l in (Path(__file__).parent / "cases.jsonl").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    with tempfile.TemporaryDirectory() as td:
        ms = MatScout(db.connect(Path(td) / "eval.db"))
        total = hit = 0
        print(f"{'case':<28} {'recall@10':>9}  details")
        for c in cases:
            expected = {normalize_doi(d) for d in c["expected_dois"]}
            verified = set()
            for d in expected:
                try:
                    v = ms.verify_citation(d)
                    if v["verified"]:
                        verified.add(d)
                    else:
                        print(f"  [warn] ground-truth DOI 未通过核验: {d}")
                except Exception as e:
                    print(f"  [warn] 核验异常 {d}: {e}")
            res = ms.search_literature(c["query"], limit=10)
            got = {normalize_doi(p["doi"]) for p in res["papers"] if p["doi"]}
            h = len(expected & got)
            total += len(expected)
            hit += h
            missing = sorted(expected - got)
            print(f"{c['id']:<28} {h}/{len(expected):>7}  missing={missing or '-'}")
        ms.conn.close()  # Windows: release SQLite handle before tempdir cleanup
        recall = hit / total if total else 0.0
        print(f"\nOverall recall@10 = {hit}/{total} = {recall:.2%}  (MVP 目标 ≥ 80%)")
        return 0 if recall >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())

