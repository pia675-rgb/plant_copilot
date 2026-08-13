#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nodes.py — CRAG 루프의 상태와 노드

v1 은 한 번 검색하고 끝이었다. 검색이 빗나가면 빗나간 근거 위에서
LLM 이 그럴듯한 답을 만든다. v2 는 검색 결과를 먼저 채점하고, 부족하면
질의를 바꿔 다시 찾고, 그래도 부족하면 답하지 않는다.

    retrieve → grade → (충분) → advise
                     → (부족, 재시도 여유 있음) → rewrite → retrieve
                     → (부족, 여유 없음) → abstain

거절 경로가 이 구조의 목적이다. 정비원에게 틀린 조치 순서를 주는 것은
아무 답도 주지 않는 것보다 나쁘다.

채점은 LLM 없이도 돌아가야 한다(재현성). 기본 채점기는 규칙 기반이고,
LLM 채점은 옵션으로 둔다.
"""

import os
import re
import sys
from typing import Any, Dict, List, Optional

try:
    from typing import TypedDict
except ImportError:                                  # py<3.8
    from typing_extensions import TypedDict          # noqa: F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


class CopilotState(TypedDict, total=False):
    # 입력
    tag: Optional[str]
    alarm: str
    code: str
    # 진행 상태
    query: str
    orig_query: str
    attempts: int
    rewrites: List[str]
    tag_device: str
    has_vendor_doc: bool
    # 산출
    evidence: List[Dict[str, Any]]
    grade: float
    grade_reason: str
    grade_parts: Dict[str, float]
    decision: str          # advise | abstain
    trace: List[str]


# ── 노드 ────────────────────────────────────────────────────
def make_retrieve(retriever):
    def retrieve(state: CopilotState) -> CopilotState:
        q = state.get("query") or " ".join(
            x for x in [state.get("alarm", ""), state.get("code", "")] if x).strip()
        hits = retriever.retrieve(q, tag=state.get("tag"))
        ev = [{"id": r["id"], "kind": r["kind"], "title": r["title"],
               "text": r["text"], "score": s, "trace": w,
               "device": r.get("device", ""),
               "cite": "%s p.%d (%s)" % (r["source"]["file"],
                                         r["source"]["pdf_page"],
                                         r["source"].get("section", "")),
               } for r, s, w in hits]
        tr = list(state.get("trace", []))
        tr.append("retrieve(%d회): '%s' → %d건" %
                  (state.get("attempts", 0) + 1, q, len(ev)))

        # 이 태그의 기종에 벤더 매뉴얼이 있는가.
        # 없으면 아무리 닮은 청크를 찾아와도 그건 답이 아니다.
        # device_of 는 기기 키를 **여러 개** 돌려준다(모델 전체·조각·메이커).
        # 실물에서는 하나만으로 매뉴얼을 못 찾는 경우가 많아 그렇게 바뀌었다.
        # 여기서 스칼라로 취급하면 집합 판정에서 바로 터진다 — 화면에는
        # "unhashable type: 'list'" 한 줄만 뜨고 조치 생성이 통째로 멈춘다.
        dev = retriever.device_of(state.get("tag"))
        dev_keys = [dev] if isinstance(dev, str) else list(dev or [])
        dev_keys = [str(d).strip() for d in dev_keys if str(d).strip()]
        vendor_devs = set(config.MANUAL_DEVICE.values()) - {config.CARD_DEVICE}
        vendor_up = {str(v).upper() for v in vendor_devs}
        has_vendor = any(
            k.upper() in vendor_up
            or any(k.upper() in v or v in k.upper() for v in vendor_up)
            for k in dev_keys)
        return {"query": q, "orig_query": state.get("orig_query") or q,
                "evidence": ev, "trace": tr,
                "tag_device": dev_keys[0] if dev_keys else "",
                "has_vendor_doc": bool(has_vendor),
                "attempts": state.get("attempts", 0) + 1}
    return retrieve


def _ramp(x, lo, hi):
    """lo 이하 0, hi 이상 1 인 선형 구간."""
    if x is None:
        return None
    if hi <= lo:
        return 1.0 if x >= hi else 0.0
    return max(0.0, min(1.0, (float(x) - lo) / (hi - lo)))


_HANGUL = re.compile(r"[가-힣]")


def _coverage(query, text):
    """
    어휘 적중률 — **문자체계가 겹칠 때만** 계산한다. None 이면 '해당 없음'.

    이전 채점기의 결함이 여기 있었다. 한글 질의를 영문 매뉴얼 청크에
    대고 글자 일치를 세면 언제나 0 이 나온다. 검색이 정답을 1위로
    올려도 채점은 0점을 주고, 그래서 CRAG 가 전부 거절로 떨어졌다.
    적중률 0 과 '측정 불가'는 다른 것이므로 구분해서 돌려준다.
    """
    q_ko = bool(_HANGUL.search(query or ""))
    d_ko = bool(_HANGUL.search(text or ""))
    if q_ko and not d_ko:
        return None                    # 한글 질의 ↔ 영문 문서: 측정 불가
    terms = set(re.findall(r"[a-z0-9]{3,}|[가-힣]{2,}", (query or "").lower()))
    if not terms:
        return None
    low = (text or "").lower()
    return sum(1 for t in terms if t in low) / len(terms)


def grade(state: CopilotState) -> CopilotState:
    """
    근거 충분성 채점 (규칙 기반, 0~1). 배점표는 config.GRADE_W.

    LLM 채점을 쓰지 않는 이유는 재현성이다. 같은 질의에 같은 점수가
    나와야 평가셋 비교가 성립한다. LLM 채점기는 grade_llm 으로 따로 둔다.

    신호 선택 기준은 하나다 — **질의 언어에 의존하지 말 것.**
    어휘 적중률은 질의와 문서의 문자체계가 겹칠 때만 쓰고, 겹치지 않으면
    벡터 유사도와 검색기 합의로 대신한다. 그래서 이 채점기는 렉시컬
    모드에서 한글 질의를 정직하게 거절하고(BM25 는 실제로 못 찾는다),
    하이브리드 모드에서는 같은 질의를 통과시킨다. 모드 간 차이가
    채점 버그가 아니라 실제 성능 차이로 드러난다.
    """
    ev = state.get("evidence", [])
    if not ev:
        return {"grade": 0.0, "grade_reason": "검색 결과 없음", "grade_parts": {}}

    W = config.GRADE_W
    query = state.get("query") or ""
    top = ev[:3]
    parts, reasons = {}, []

    # 0) 벤더 문서 적용범위 — 점수를 매기기 전에 먼저 묻는다.
    #
    #    "이 근거가 얼마나 닮았는가"보다 "이 태그에 애초에 답할 자료가
    #    있는가"가 먼저다. 기종에 벤더 매뉴얼이 없으면 device 필터가
    #    범용 I/O 카드 청크만 남기는데, 그것들끼리는 당연히 기기가
    #    일치하고 유사도도 얼마간 붙는다. 유사도만 보면 통과해 버린다.
    #
    #    임계값으로는 못 막는다 — 이 경우의 점수 분포가 정답 문항의
    #    분포와 완전히 겹치기 때문이다. 판정 자체를 앞단에서 끊는다.
    if state.get("tag") and not state.get("has_vendor_doc", True):
        only_card = all((e.get("device") or "") == config.CARD_DEVICE
                        for e in top)
        if only_card:
            return {"grade": 0.0,
                    "grade_reason": "%s 기종(%s)의 벤더 매뉴얼이 없습니다 — "
                                    "범용 I/O 카드 문서만 검색되었습니다"
                                    % (state.get("tag"),
                                       state.get("tag_device") or "미상"),
                    "grade_parts": {"no_vendor_doc": 0.0}}

    def add(key, value, why):
        if value:
            parts[key] = round(value, 3)
            reasons.append(why)

    # 1) 코드 완전일치 — 검색이 아니라 조회다. 가장 강한 신호.
    if any(e["trace"].get("exact_code") for e in ev):
        add("exact_code", W["exact_code"], "코드 완전일치")
    else:
        # 2) 1위 근거의 종류
        k0 = top[0]["kind"]
        if k0 == "error_code":
            add("top1_code", W["top1_code"], "1위가 코드표 항목")
        elif k0 == "manual_text":
            add("top1_manual", W["top1_manual"], "1위가 매뉴얼 본문")

    # 3) 벡터 유사도 — 언어에 의존하지 않는 유일한 신호
    dsims = [e["trace"].get("dense_score") for e in top]
    dsims = [d for d in dsims if d is not None]
    if dsims:
        r = _ramp(max(dsims), config.GRADE_DENSE_LO, config.GRADE_DENSE_HI)
        add("dense", W["dense_max"] * r,
            "벡터 유사도 %.2f" % max(dsims))

    # 4) 검색기 합의 — BM25 와 dense 가 같은 문서를 올렸는가
    if any(e["trace"].get("found_by", 0) >= 2 for e in top):
        add("consensus", W["consensus"], "어휘·벡터 검색 합의")

    # 5) 리랭커 점수
    rs = [e["trace"].get("rerank_score") for e in top]
    rs = [x for x in rs if x is not None]
    if rs:
        r = _ramp(max(rs), config.GRADE_RERANK_LO, config.GRADE_RERANK_HI)
        add("rerank", W["rerank_max"] * r, "재정렬 점수 %.2f" % max(rs))

    # 6) 어휘 적중률 — 문자체계가 겹칠 때만
    top_text = " ".join(e["title"] + " " + e["text"] for e in top)
    cover = _coverage(query, top_text)
    if cover is None:
        reasons.append("어휘 적중률 해당 없음(언어 불일치)")
    else:
        add("coverage", W["coverage_max"] * cover,
            "질의어 적중률 %.0f%%" % (100 * cover))

    # 7) 기기 일관성 — device 필드를 쓰고, 없으면 id 접두사로 대체
    devs = {e.get("device") or e["id"].split("#")[0].split("-")[0]
            for e in top}
    if len(devs) > 2:
        parts["device_scatter"] = W["device_scatter"]
        reasons.append("상위 근거의 기기가 흩어져 있음")
    elif len(devs) == 1:
        add("device_same", W["device_same"], "상위 근거의 기기 일치")

    score = max(0.0, min(1.0, sum(parts.values())))
    return {"grade": score, "grade_reason": ", ".join(reasons),
            "grade_parts": parts}


def rewrite(state: CopilotState) -> CopilotState:
    """
    질의 재작성.

    기본은 규칙 기반 확장이고, LLM 재작성은 옵션이다. 규칙 쪽에서도
    v1 처럼 평가셋 용어를 사전에 박지 않는다 — 구조적 변형만 한다.
    """
    q = state.get("query", "")
    # 변형은 항상 최초 질의를 기준으로 만든다.
    # 직전 결과에 덧붙이면 "troubleshooting alarm fault"가 누적된다.
    base = state.get("orig_query") or q
    tried = list(state.get("rewrites", []))
    variants = [
        re.sub(r"[0-9]+", " ", base).strip(),        # 숫자 제거 → 서술만
        base + " troubleshooting alarm fault",       # 문서 상투어 부착
        " ".join(base.split()[:3]),                  # 앞 세 단어만 (짧게)
    ]
    for v in variants:
        if v and v != q and v not in tried:
            tried.append(v)
            tr = list(state.get("trace", []))
            tr.append("rewrite: '%s' → '%s'" % (q, v))
            return {"query": v, "rewrites": tried, "trace": tr}
    return {"rewrites": tried}


def abstain(state: CopilotState) -> CopilotState:
    tr = list(state.get("trace", []))
    tr.append("abstain: 근거 부족 (grade=%.2f)" % state.get("grade", 0.0))
    return {"decision": "abstain", "trace": tr}


def make_advise(advisor_fn=None):
    """
    advisor_fn(state) → dict. 없으면 근거만 돌려준다.
    v1 의 advisor.py 처럼 근거 ID 검증은 이 바깥에서 한 번 더 건다.
    """
    def advise(state: CopilotState) -> CopilotState:
        tr = list(state.get("trace", []))
        tr.append("advise: 근거 %d건으로 조치 생성" % len(state.get("evidence", [])))
        out = {"decision": "advise", "trace": tr}
        if advisor_fn:
            out.update(advisor_fn(state))
        return out
    return advise


# ── 분기 ────────────────────────────────────────────────────
def route_after_grade(state: CopilotState) -> str:
    if state.get("grade", 0.0) >= config.GRADE_THRESHOLD:
        return "advise"
    if len(state.get("rewrites", [])) < config.MAX_REWRITES:
        return "rewrite"
    return "abstain"


def route_after_rewrite(state: CopilotState) -> str:
    """재작성할 변형이 남아 있지 않으면 바로 거절."""
    return "retrieve" if state.get("query") else "abstain"
