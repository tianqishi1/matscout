"""Demo phase 2: re-rank with normalized English idea; verify new entrants."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from matscout import db
from matscout.core import MatScout

ms = MatScout(db.connect())
idea_en = ("high-entropy multication chloride solid electrolyte Li2ZrCl6 "
           "ionic conductivity lithium metal interface stability all-solid-state battery")
c = ms.find_closest_work(1, idea_text=idea_en, k=8)
print("candidates:", c["candidates_total"])
for t in c["ranked"]:
    print(f"  paper_id={t['paper_id']} score={t['score']} verified={t['verified']} "
          f"{t['year']} | {t['doi']} | {t['title'][:90]}")
print("\n--- verify unverified in top-6 ---")
for t in c["ranked"][:6]:
    if t["verified"] or not t["doi"]:
        continue
    v = ms.verify_citation(t["doi"], project_id=1)
    print(f"paper_id={t['paper_id']} verified={v['verified']} via={v.get('verified_via')}")
    if v["verified"]:
        pp = v["paper"]
        print("  TITLE:", pp["title"])
        print("  VENUE:", pp["venue"], pp["year"])
        print("  ABSTRACT:", (pp.get("abstract_snippet") or "")[:500])
