#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fusion.py — 순위 융합(RRF)과 재정렬(cross-encoder)

RRF 를 쓰는 이유: BM25 점수와 코사인 유사도는 척도가 달라 그대로 더할
수 없다. 정규화해서 가중합하는 방법도 있지만 가중치를 손으로 맞춰야
하고, 그 손맞춤이 다시 "평가셋에 맞춘 튜닝"이 된다. RRF 는 점수를
버리고 순위만 쓰므로 튜닝할 자유도가 사실상 없다 — v1 이 사전 튜닝으로
점수를 부풀렸던 문제를 반복하지 않기 위한 선택이다.

리랭커는 질의와 문서를 한 번에 읽는 cross-encoder 라 bi-encoder(임베딩)
보다 정확하지만 느리다. 그래서 융합 상위 30건에만 건다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

_RERANKER = None


def rrf(ranked_lists, k=None, top_k=None, names=None):
    """
    ranked_lists: [[(record, score), ...], ...]  각 검색기의 순위 목록
    names: 각 목록의 이름 (기본 ["bm25", "dense", ...])
    반환: [(record, rrf_score, trace)]

    trace 에는 검색기별 **순위와 원점수**를 함께 남긴다. RRF 는 점수를
    버리고 순위만 쓰지만, 뒤에서 근거 충분성을 채점하려면 원점수가
    필요하다 — 특히 dense 유사도는 질의 언어에 의존하지 않는 유일한
    신뢰 신호다. 버리면 한글 질의를 채점할 방법이 없어진다.
    """
    k = k or config.RRF_K
    top_k = top_k or config.FUSED_TOP_K
    names = names or ["bm25", "dense", "list%d"]
    acc, trace, keep = {}, {}, {}
    for li, lst in enumerate(ranked_lists):
        nm = names[li] if li < len(names) else ("list%d" % li)
        for rank, (rec, s) in enumerate(lst, start=1):
            rid = rec["id"]
            acc[rid] = acc.get(rid, 0.0) + 1.0 / (k + rank)
            t = trace.setdefault(rid, {})
            t[nm] = rank
            if s is not None:
                t[nm + "_score"] = float(s)
            keep.setdefault(rid, rec)
    for rid, t in trace.items():
        t["found_by"] = sum(1 for nm in names if nm in t)
    order = sorted(acc.items(), key=lambda x: -x[1])[:top_k]
    return [(keep[rid], sc, trace[rid]) for rid, sc in order]


def get_reranker():
    """지연 로드. 모델 다운로드가 필요하므로 실제 사용 시점에만 부른다."""
    global _RERANKER
    if _RERANKER is None:
        from sentence_transformers import CrossEncoder
        _RERANKER = CrossEncoder(config.RERANK_MODEL, max_length=512)
    return _RERANKER


def rerank(query, candidates, top_k=None):
    """
    candidates: [(record, ...), ...]  튜플의 첫 원소만 본다.
    반환: [(record, rerank_score)]
    리랭커를 못 쓰는 환경이면 입력 순서를 그대로 돌려준다 (실험 조건에 기록).
    """
    top_k = top_k or config.FINAL_TOP_K
    recs = [c[0] for c in candidates]
    if not recs:
        return []
    if not config.RERANK_ENABLED:
        return [(r, None) for r in recs[:top_k]]
    try:
        ce = get_reranker()
    except Exception as e:                       # noqa: BLE001
        print("  리랭커 사용 불가 (%s) — 융합 순위를 그대로 사용합니다." % e)
        return [(r, None) for r in recs[:top_k]]
    pairs = [(query, (r["title"] + "\n" + r["text"])[:1500]) for r in recs]
    scores = ce.predict(pairs)
    ranked = sorted(zip(recs, scores), key=lambda x: -x[1])
    return [(r, float(s)) for r, s in ranked[:top_k]]
