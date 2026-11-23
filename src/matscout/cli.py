#!/usr/bin/env python3
"""MatScout CLI: same capability layer without an MCP host.

Usage: python -m matscout.cli <command> ...  (PYTHONPATH=src)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matscout import db
from matscout.core import CoreError, MatScout


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="matscout", description="材料科研查新副驾驶（本地证据库）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create-project"); p.add_argument("--name", required=True); p.add_argument("--field", default=""); p.add_argument("--idea", required=True)
    p = sub.add_parser("search"); p.add_argument("--query", required=True); p.add_argument("--project", type=int); p.add_argument("--year-from", type=int); p.add_argument("--year-to", type=int); p.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("verify"); g = p.add_mutually_exclusive_group(required=True); g.add_argument("--doi"); g.add_argument("--title"); p.add_argument("--project", type=int)
    p = sub.add_parser("closest"); p.add_argument("--project", type=int, required=True); p.add_argument("--idea"); p.add_argument("--k", type=int, default=5)
    p = sub.add_parser("assess"); p.add_argument("--project", type=int, required=True); p.add_argument("--file", required=True, help="评估 JSON 文件（verdict/confidence/summary/deltas/feasibility/risks/limitations）")
    p = sub.add_parser("card"); p.add_argument("--project", type=int, required=True); p.add_argument("--out")
    p = sub.add_parser("evidence"); p.add_argument("--project", type=int, required=True)
    p = sub.add_parser("paper"); p.add_argument("--id", type=int); p.add_argument("--doi")
    p = sub.add_parser("purge"); p.add_argument("--project", type=int, required=True)

    a = ap.parse_args(argv)
    ms = MatScout(db.connect())
    try:
        if a.cmd == "create-project":
            _out(ms.create_project(a.name, a.field, a.idea))
        elif a.cmd == "search":
            _out(ms.search_literature(a.query, project_id=a.project, year_from=a.year_from, year_to=a.year_to, limit=a.limit))
        elif a.cmd == "verify":
            _out(ms.verify_citation(a.doi or a.title, project_id=a.project))
        elif a.cmd == "closest":
            _out(ms.find_closest_work(a.project, idea_text=a.idea, k=a.k))
        elif a.cmd == "assess":
            data = json.loads(Path(a.file).read_text(encoding="utf-8"))
            _out(ms.save_novelty_assessment(a.project, data["verdict"], data["confidence"], data["summary"],
                                            data["deltas"], feasibility=data.get("feasibility"),
                                            risks=data.get("risks"), limitations=data.get("limitations")))
        elif a.cmd == "card":
            res = ms.render_novelty_card(a.project)
            if a.out:
                Path(a.out).write_text(res["markdown"], encoding="utf-8")
                _out({"saved": a.out, "review_status": res["review_status"]})
            else:
                print(res["markdown"])
        elif a.cmd == "evidence":
            _out(ms.list_evidence(a.project))
        elif a.cmd == "paper":
            _out(ms.get_paper(paper_id=a.id, doi=a.doi))
        elif a.cmd == "purge":
            _out(ms.purge_project(a.project))
    except CoreError as e:
        print(f"[matscout] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
