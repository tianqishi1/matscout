"""Transparent lexical similarity for novelty ranking.

score = overlap_coefficient(idea, title+abstract) + 0.5 * title_overlap
Every score ships with matched_terms so a human can audit it.
Limitation: lexical only; semantic paraphrases may be missed (stated on card).
"""
from __future__ import annotations

import re

STOPWORDS = set("""
a an the and or of for with without via using used use based towards toward
in on at to from by as is are was were be been being it its this that these those
we our they their he she you your i me my
material materials study studies novel new approach method methods methodology
paper papers work works result results show shows shown demonstrate demonstrated
investigation research analysis effect effects influence impact property properties
performance high low enhanced improvement improved recent progress review
can could may might will would shall should also than then so such both each
between among during over under more most much many few several various
potential application applications strategy strategies design designed
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> set[str]:
    text = (text or "").lower()
    toks = {t for t in _TOKEN_RE.findall(text) if t not in STOPWORDS and len(t) > 1}
    # Chinese ideas: character bigrams as fallback tokens (documented limitation).
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            toks.add(run)
        for i in range(len(run) - 1):
            toks.add(run[i:i + 2])
    return toks


def score_pair(idea_tokens: set[str], title: str, abstract: str | None) -> dict:
    title_toks = tokenize(title)
    body_toks = title_toks | tokenize(abstract or "")
    if not idea_tokens:
        return {"score": 0.0, "overlap": 0.0, "title_overlap": 0.0, "matched_terms": []}
    matched = idea_tokens & body_toks
    matched_title = idea_tokens & title_toks
    overlap = len(matched) / len(idea_tokens)
    title_overlap = len(matched_title) / len(idea_tokens)
    score = min(1.0, overlap + 0.5 * title_overlap)
    return {
        "score": round(score, 4),
        "overlap": round(overlap, 4),
        "title_overlap": round(title_overlap, 4),
        "matched_terms": sorted(matched),
    }
