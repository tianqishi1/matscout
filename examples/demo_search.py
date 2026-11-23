"""Demo phase 1: create project, multi-query search, rank, verify, print abstracts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from matscout import db
from matscout.core import MatScout

ms = MatScout(db.connect())
p = ms.create_project(
    "高熵氯化物固态电解质", "固态电解质/锂金属全固态电池",
    "用高熵多阳离子策略设计氯化物固态电解质（Li2ZrCl6 基），同步提升室温离子电导率与对锂金属负极的界面稳定性")
pid = p["project_id"]
print("project_id =", pid)
for q in ["high-entropy chloride solid electrolyte lithium",
          "halide solid electrolyte lithium metal interface stability",
          "Li2ZrCl6 chloride solid electrolyte ionic conductivity"]:
    r = ms.search_literature(q, project_id=pid, year_from=2019, limit=10)
    print("search:", q, "->", r["count"])
c = ms.find_closest_work(pid, k=5)
print("candidates:", c["candidates_total"])
for t in c["ranked"]:
    print(f"  paper_id={t['paper_id']} score={t['score']} verified={t['verified']} "
          f"{t['year']} | {t['doi']} | {t['title'][:85]}")
print("\n--- verify top-5 + abstracts ---")
for t in c["ranked"]:
    if not t["doi"]:
        print("no DOI, skip:", t["paper_id"]); continue
    v = ms.verify_citation(t["doi"], project_id=pid)
    print(f"\n[paper_id={t['paper_id']}] verified={v['verified']} via={v.get('verified_via')}")
    if v["verified"]:
        pp = v["paper"]
        print("TITLE:", pp["title"])
        print("VENUE:", pp["venue"], pp["year"])
        print("ABSTRACT:", (pp.get("abstract_snippet") or "")[:600])
