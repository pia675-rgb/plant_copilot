# -*- coding: utf-8 -*-
"""
동시 알람 조사 — 사람이 다섯 번 누르던 것을 한 번에.

카드 한 장이 죽으면 물린 계기 전체가 알람을 낸다. 그때의 조사 절차는
정해져 있다: 공통 조상 판정 → 안 운 동반 태그(반례) 확인 → 진단 코드
근거 수집 → 종합. 이 모듈은 그 절차를 대신 밟고, **밟은 단계를 전부
steps 로 남긴다** — 화면의 trace 와 같은 이유다. 무엇을 어떤 순서로
조회했는지가 결론만큼 중요하다.

자율성의 경계: 이 조사기는 어느 조회를 다음에 부를지만 정하고, 각 조회의
결과는 이미 검증된 계층(판넬 색인·코드 완전일치·검색 파이프라인)이
보장한다. 결론 문장은 규칙으로 조립하며 LLM 을 쓰지 않는다 — 같은
입력에 같은 보고가 나와야 한다.

지금 아는 한계 (기획서 4-5): 동시에 떴다는 사실 자체는 SCADA 미연결이라
사람이 태그를 넣어 줘야 한다. 이 모듈은 그 입력 이후를 자동화한다.
"""


def investigate(tags, panel, retriever, codes=None, alarm=None):
    """tags: 동시 알람 태그들 / codes: 함께 뜬 SSL 진단 코드(선택)
    alarm: 알람명(선택, 예: LOOP ERROR — 카드 문서 근거 검색에 사용)

    반환: {steps, common, per_tag, code_evidence, doc_evidence, conclusion}
    """
    tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    codes = [str(c).strip().upper() for c in (codes or []) if str(c).strip()]
    steps, report = [], {}

    def step(what, result):
        steps.append({"n": len(steps) + 1, "what": what, "result": result})

    if len(tags) < 2:
        step("입력 확인", "태그 %d개 — 동시 알람 조사는 2개부터" % len(tags))
        return {"steps": steps, "common": None, "per_tag": [],
                "code_evidence": [], "doc_evidence": [],
                "conclusion": "태그를 2개 이상 넣어 주십시오. 1개면 알람 "
                              "조회 화면이 맞습니다."}

    # 1) 공통 조상 판정 — 판넬 색인(전건 검증된 계층)
    common = panel.common_cause_of(tags)
    report["common"] = common
    step("공통 조상 판정 (판넬 색인)",
         "level=%s · node=%s · 미등재 %d" % (common.get("level"),
                                             common.get("node") or "-",
                                             len(common.get("unknown") or [])))

    # 2) 반례 확인 — 같은 묶음인데 알람이 안 뜬 태그
    uncovered = common.get("uncovered") or []
    if uncovered:
        step("미알람 동반 태그(반례) 확인",
             "%s — 공통 원인 가설과 함께 현장 확인 필요" % ", ".join(uncovered))
    else:
        step("미알람 동반 태그(반례) 확인", "없음 — 묶음 전체가 알람")

    # 3) 태그별 신원 — 판넬 색인에서 그대로 읽는다
    per_tag = []
    for t in tags:
        key = panel.card_of(t)
        card = "/".join(str(x) for x in key) if isinstance(key, (list, tuple)) \
            else (str(key) if key else "")
        per_tag.append({"tag": t, "card": card, "known": bool(key)})
    report["per_tag"] = per_tag
    step("태그 소속 카드 대조",
         "; ".join("%s→%s" % (p["tag"], p["card"] or "미등재")
                   for p in per_tag))

    # 4) 진단 코드 근거 — 코드가 주어졌을 때만. 지어내지 않는다.
    code_ev = []
    if codes:
        found = retriever.retrieve(" ".join(codes), tag=tags[0])
        for rec, score, tr in found:
            if rec.get("kind") == "error_code":
                code_ev.append({"code_hit": True,
                                "title": rec.get("title", ""),
                                "cite": rec.get("cite", ""),
                                "text": (rec.get("text") or "")[:200]})
        step("SSL 진단 코드 조회 (%s)" % ",".join(codes),
             "코드표 근거 %d건" % len(code_ev))
    else:
        step("SSL 진단 코드 조회", "코드 미입력 — 건너뜀")
    report["code_evidence"] = code_ev

    # 5) 알람명 기반 카드 문서 근거 — 알람명이 주어졌을 때만
    doc_ev = []
    if alarm:
        found = retriever.retrieve(alarm, tag=tags[0])
        for rec, score, tr in found[:3]:
            doc_ev.append({"title": rec.get("title", ""),
                           "cite": rec.get("cite", "")})
        step("알람명 근거 검색 (%s)" % alarm, "근거 %d건" % len(doc_ev))
    report["doc_evidence"] = doc_ev

    # 6) 결론 — 규칙 조립. 판넬 색인이 만든 note 를 근간으로 쓴다.
    level = common.get("level")
    if level == "card":
        concl = common.get("note") or ""
        if uncovered:
            concl += (" 단, 같은 카드의 %s 는 알람이 없어 반례가 될 수 "
                      "있습니다 — 함께 확인." % ", ".join(uncovered))
    elif level in ("rack", "panel", "plc"):
        concl = (common.get("note") or "") + \
            " 카드 단위 공통 원인은 아니므로 상위 전원·통신 계통을 보십시오."
    elif level == "scattered":
        concl = ("공통 조상이 없습니다 — 개별 원인일 가능성이 큽니다. "
                 "태그별로 알람 조회를 따로 수행하십시오.")
    else:
        concl = common.get("note") or "판정 불가 — 미등재 태그를 확인하십시오."
    report["conclusion"] = concl
    step("결론 조립 (규칙)", concl[:80])

    report["steps"] = steps
    return report
