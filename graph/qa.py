#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa.py — 문서 근거 질의응답 (챗봇용)

챗봇이 매뉴얼을 근거로 답하게 한다. 지금까지 챗봇은 명령 해석만 했고,
검색·판정·근거 검증은 알람 조회 화면에서만 쓰였다. 같은 부품을 대화
경로에도 연결한다.

## 지시문과 사양서를 어떻게 넣는가

세 층을 프롬프트에 함께 넣는다.

1. **지시문** — 이 도구가 무엇이고 무엇을 하면 안 되는지 (SYSTEM)
2. **사양서** — 질의에 태그가 있으면 그 계기의 제조사·모델·신호
3. **근거** — 하이브리드 검색이 찾아온 매뉴얼 청크 (번호로 인용)

## 지어내지 않게 하는 방식

알람 조회와 같은 규칙을 그대로 쓴다.

- 근거 충분성이 임계값에 못 미치면 **답을 만들지 않고 모른다고 한다**
- 답의 각 문장은 근거 번호를 인용해야 하고, 검색 결과에 없는 번호를
  인용하면 그 문장을 버린다
- 남는 문장이 없으면 역시 모른다고 한다

이것이 일반 챗봇과의 차이다. "그럴듯한 답"보다 "출처 있는 답 또는
모른다"가 정비 현장에서 쓸모 있다.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

MAX_EVIDENCE = 6
MAX_CHARS = 800

SYSTEM = """당신은 Plant Maintenance Copilot 의 정비 지원 도우미입니다.
반도체 초순수(UPW) 플랜트의 계기·설비를 다룹니다.

주어진 근거만 사용해 한국어로 답하십시오.

규칙:
- 근거에 없는 내용을 쓰지 마십시오. 일반 상식이나 추측을 넣지 마십시오.
- 근거는 관련도 순입니다. 1번이 질문과 가장 가깝습니다.
- 각 문장 끝에 사용한 근거를 번호로 표기하십시오. 예: ... 입니다 [1]
- 근거가 질문에 답하지 못하면 steps 를 비우고 answer 에
  "근거를 찾지 못했습니다" 라고 쓰십시오. 지어내지 마십시오.
- 3~5문장으로 간결하게 쓰십시오. 정비원에게 말하듯 쓰십시오.
- 매뉴얼이 영문이어도 답변은 한국어로 하십시오.

JSON만 출력하십시오. 코드펜스를 붙이지 마십시오.
{"answer": "본문 [1] 형태로 근거 번호를 표기한 한국어 답변",
 "used": [1, 2]}"""


def _spec_block(tag, instruments):
    """계기 사양서. 태그가 있을 때만 넣는다."""
    if not tag or not instruments:
        return ""
    i = instruments.get(tag) or instruments.get(str(tag).upper())
    if not i:
        return ""
    fields = [("제조사", i.get("maker")), ("모델", i.get("model")),
              ("용도", i.get("service")), 
              ("신호", i.get("signal")), ("계측", i.get("meas_type")),
              ("범위", i.get("range")), ("도면", i.get("dwg_no"))]
    vals = ["%s %s" % (k, v) for k, v in fields if v]
    if not vals:
        return ""
    return "대상 계기 사양: %s — %s\n\n" % (tag, " / ".join(vals))


def _prompt(question, tag, evidence, instruments=None):
    head = "질문: %s\n\n" % question
    head += _spec_block(tag, instruments)
    head += "근거 (관련도 순, 1번이 가장 가까움):\n"
    for i, e in enumerate(evidence[:MAX_EVIDENCE], 1):
        head += "[%d] %s — %s\n" % (
            i, e.get("title", ""),
            re.sub(r"\s+", " ", e.get("text", ""))[:MAX_CHARS])
    return head


def _parse(raw):
    t = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("JSON 을 찾지 못했습니다.")
    return json.loads(t[i:j + 1])


def answer(question, tag=None, mode=None, copilot=None, instruments=None):
    """
    반환:
      {"ok": True,  "reply": 답변, "evidence": [...], "grade": float}
      {"ok": False, "reply": 사유, "evidence": [...], "grade": float}

    ok=False 는 실패가 아니라 **정상적인 거절**이다. 근거가 없으면
    답하지 않는 것이 이 도구의 설계다.
    """
    from graph.advisor import _CHAT
    from graph.app_graph import Copilot2

    cp = copilot or Copilot2(mode=mode or "hybrid")
    out = cp.answer(tag=tag, alarm=question)
    ev = out.get("evidence") or []
    grade = out.get("grade", 0.0)

    if out.get("decision") != "advise" or not ev:
        return {"ok": False, "grade": grade, "evidence": ev,
                "reply": "매뉴얼에서 근거를 찾지 못했습니다. %s"
                         % (out.get("grade_reason") or "")}

    fn = _CHAT.get(config.LLM_PROVIDER)
    if fn is None:
        # 모델이 없으면 근거만 정리해 돌려준다. 지어내지 않는다.
        lines = ["매뉴얼에서 관련 항목을 찾았습니다. 문장 요약은 대화 모델이 "
                 "없어 생략합니다."]
        for i, e in enumerate(ev[:3], 1):
            lines.append("%d. %s — %s" % (i, e.get("title", ""),
                                          e.get("cite", "")))
        return {"ok": True, "grade": grade, "evidence": ev[:3],
                "reply": "\n".join(lines), "engine": "no-llm"}

    raw = fn([{"role": "system", "content": SYSTEM},
              {"role": "user", "content": _prompt(question, tag, ev,
                                                  instruments)}], 60)
    data = _parse(raw)
    text = (data.get("answer") or "").strip()

    # 인용 검증. 근거 목록에 없는 번호를 인용한 문장은 버린다.
    n = len(ev[:MAX_EVIDENCE])
    cited, dropped = set(), 0
    kept = []
    for sent in re.split(r"(?<=[.!?요다])\s+", text):
        nums = [int(x) for x in re.findall(r"\[(\d+)\]", sent)]
        if nums and all(1 <= x <= n for x in nums):
            cited.update(nums)
            kept.append(sent)
        elif not nums:
            kept.append(sent)          # 인용 없는 연결 문장은 남긴다
        else:
            dropped += 1               # 없는 번호를 인용 — 버린다

    text = " ".join(s.strip() for s in kept if s.strip())
    if not text or not cited:
        return {"ok": False, "grade": grade, "evidence": ev[:3],
                "reply": "근거에 기반한 답변을 만들지 못했습니다. "
                         "알람 조회 화면에서 원문을 직접 확인해 주세요."}

    used = [ev[i - 1] for i in sorted(cited) if 1 <= i <= n]
    return {"ok": True, "grade": grade, "reply": text,
            "evidence": used or ev[:3], "dropped": dropped, "engine": "llm"}
