#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app_graph.py — CRAG 그래프 조립

    retrieve → grade ─┬─ advise  → END
                      ├─ rewrite → retrieve   (최대 MAX_REWRITES 회)
                      └─ abstain → END

Streamlit 화면에는 trace 를 그대로 뿌린다. "1차 검색 실패 → 질의 재작성
→ 재검색"이 눈에 보이는 것이 데모의 핵심이다.

사용:
    python -m graph.app_graph --tag AIT-4002 --alarm "산 잔량 부족" --mode lexical
"""

import argparse
import os
import sys

from langgraph.graph import END, StateGraph

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from graph import nodes  # noqa: E402
from retrieval.pipeline import Retriever  # noqa: E402


def build_graph(retriever, advisor_fn=None):
    g = StateGraph(nodes.CopilotState)
    g.add_node("retrieve", nodes.make_retrieve(retriever))
    g.add_node("grade", nodes.grade)
    g.add_node("rewrite", nodes.rewrite)
    g.add_node("advise", nodes.make_advise(advisor_fn))
    g.add_node("abstain", nodes.abstain)

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", nodes.route_after_grade,
                            {"advise": "advise", "rewrite": "rewrite",
                             "abstain": "abstain"})
    g.add_conditional_edges("rewrite", nodes.route_after_rewrite,
                            {"retrieve": "retrieve", "abstain": "abstain"})
    g.add_edge("advise", END)
    g.add_edge("abstain", END)
    return g.compile()


class Copilot2:
    """평가 스크립트와 UI 가 함께 쓰는 진입점."""

    def __init__(self, mode="full", advisor_fn=None, strict=False):
        self.retriever = Retriever(mode=mode, strict=strict)
        self.graph = build_graph(self.retriever, advisor_fn)
        self.mode = mode

    @property
    def label(self):
        return self.retriever.label()

    def answer(self, tag=None, alarm="", code=""):
        state = {"tag": tag, "alarm": alarm or "", "code": code or "",
                 "attempts": 0, "rewrites": [], "trace": []}
        return self.graph.invoke(state)


def main():
    ap = argparse.ArgumentParser(description="v2 CRAG 그래프")
    ap.add_argument("--mode", default="full",
                    choices=("lexical", "hybrid", "full"))
    ap.add_argument("--tag", default=None)
    ap.add_argument("--alarm", default="")
    ap.add_argument("--code", default="")
    args = ap.parse_args()

    out = Copilot2(mode=args.mode).answer(tag=args.tag, alarm=args.alarm,
                                          code=args.code)
    print("=" * 72)
    for t in out.get("trace", []):
        print("  · %s" % t)
    print("-" * 72)
    print("판정: %s   충분성 %.2f (%s)"
          % (out.get("decision"), out.get("grade", 0), out.get("grade_reason")))
    print("-" * 72)
    for e in out.get("evidence", [])[:config.FINAL_TOP_K]:
        print("  [%s] %s" % (e["kind"], e["title"][:60]))
        print("      %s" % e["cite"])
    print("=" * 72)


if __name__ == "__main__":
    main()
