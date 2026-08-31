# -*- coding: utf-8 -*-
"""
인터락 조회 결과를 말로 풀어 주는 서술기 (패치 29).

왜 필요했나 — 챗봇 후속 질문이 화면에 떠 있는 결과를 보고 답하는데,
그 '화면 결과'가 알람 조회 근거(evidence)만 담고 있었다. 인터락을 조회한
뒤 "말로 설명해 줄래" 하고 물으면 챗봇은 인터락을 보지 못하고 직전 알람
조회의 매뉴얼 근거로 답을 만들었다. 다른 태그, 다른 주제의 답이 나왔다.
사용자가 보고 있는 것과 챗봇이 보는 것이 달랐던 것이다.

원칙 — **LLM 을 쓰지 않는다.** 인터락은 리스트에서 읽은 사실이고,
같은 조회에 같은 문장이 나와야 한다. 모델이 문장을 다시 쓰면 조건이
슬쩍 바뀔 수 있고, 그 위험은 정비 지시에서 감당할 수 없다.

여기서 만드는 문장은 화면 표에 이미 있는 내용을 읽어 주는 것뿐이다.
없는 것을 채우지 않는다 — 파싱하지 못한 조건은 원문을 그대로 인용한다.
"""
from typing import Any, Dict, List

_KIND_KO = {
    "INTERLOCK": "인터락",
    "PERMISSIVE": "허용 조건",
    "SEQUENCE": "시퀀스",
    "PROTECTION": "보호",
}
_ACTION_KO = {
    "STOP": "정지", "START": "기동", "OPEN": "열림",
    "CLOSE": "닫힘", "ON": "켜짐", "OFF": "꺼짐",
}


def _cond_text(c: Dict[str, Any]) -> str:
    """조건 하나를 한 줄로. 파싱 못 한 것은 원문을 그대로 쓴다."""
    if not c.get("parsed"):
        raw = (c.get("raw") or "").strip()
        return "%s (원문 그대로 — 자동 해석하지 않았습니다)" % raw if raw \
            else "내용을 읽지 못한 조건"
    raw = (c.get("raw") or "").strip()
    tags = c.get("tags") or []
    bits = []
    if tags:
        bits.append(", ".join(tags))
    if c.get("state_label"):
        bits.append(str(c["state_label"]))
    elif c.get("op") and c.get("setpoint") is not None:
        unit = (" " + c["unit"]) if c.get("unit") else ""
        bits.append("%s %s%s" % (c["op"], c["setpoint"], unit))
    elif c.get("state"):
        bits.append(str(c["state"]))
    # 태그가 없는 조건(모터 과부하, E-STOP 등)은 상태 코드만 남기면
    # 뜻이 사라진다. 원문을 본문으로 쓰고 코드는 괄호로 덧붙인다.
    if not tags and raw:
        code = " ".join(bits).strip()
        line = raw + ((" (%s)" % code) if code else "")
    else:
        line = " ".join(bits) if bits else raw
    if c.get("delay"):
        line += " (%s초 지연)" % c["delay"]
    if c.get("level"):
        line += " [%s]" % c["level"]
    return line


def _rule_text(it: Dict[str, Any], n: int) -> List[str]:
    kind = _KIND_KO.get(it.get("kind"), it.get("kind") or "")
    act = _ACTION_KO.get(it.get("action"), it.get("action") or "")
    logic = (it.get("logic") or "").upper()
    conds = it.get("conditions") or []

    head = "%d) %s — %s %s" % (n, it.get("il_no") or "번호 없음", act, kind)
    if len(conds) > 1 and logic in ("AND", "OR"):
        head += " · 조건 %d개를 %s 로 묶습니다" % (
            len(conds), "모두 만족해야 성립(AND)" if logic == "AND"
            else "하나만 성립해도 동작(OR)")
    elif len(conds) == 1:
        head += " · 조건 1개"

    lines = [head]
    for c in conds:
        lines.append("   - " + _cond_text(c))

    # 래치는 사람이 리셋해야 풀린다 — 화면에서도 강조하는 항목이다.
    reset = (it.get("reset") or "").strip()
    ru = reset.upper()
    if ru in ("MANUAL", "수동"):
        lines.append("   → 래치됩니다. 해제는 수동(%s) — 원인이 사라져도 "
                     "사람이 리셋해야 풀립니다" % reset)
    elif ru in ("AUTO", "자동"):
        lines.append("   → 자동 복귀(%s) — 조건이 해소되면 스스로 풀립니다"
                     % reset)
    elif ru and ru not in ("-", "NONE", "N/A"):
        lines.append("   → 해제 수단 표기: %s" % reset)
    else:
        lines.append("   → 해제 수단 표기 없음")
    if it.get("bypassable"):
        lines.append("   → 바이패스 가능 표기가 있습니다")
    src = " · ".join(str(it[k]) for k in ("dwg_no", "sheet", "plc_block")
                     if it.get(k))
    if src:
        lines.append("   → 출처: %s" % src)
    return lines


def describe(res: Dict[str, Any]) -> str:
    """인터락 조회 응답(dict)을 사람이 읽을 문단으로."""
    if not res or not res.get("found"):
        return (res or {}).get("message") \
            or "인터락 리스트에서 찾지 못했습니다."

    tag = res.get("tag") or ""

    # 역방향 — 이 태그가 어느 출력에 영향을 주는가
    if res.get("as_input"):
        outs = res.get("affected_outputs") or []
        hits = res.get("hits") or []
        lines = ["%s 는 입력 조건으로 쓰이고 있습니다. "
                 "영향을 받는 출력이 %d개입니다." % (tag, len(outs))]
        if outs:
            lines.append("영향 대상: " + ", ".join(str(o) for o in outs))
        for i, h in enumerate(hits, 1):
            act = _ACTION_KO.get(h.get("action"), h.get("action") or "")
            kind = _KIND_KO.get(h.get("kind"), h.get("kind") or "")
            lines.append("%d) %s 의 %s %s — 조건: %s"
                         % (i, h.get("output_tag") or "?", act, kind,
                            _cond_text(h.get("condition") or {})))
        lines.append("정비 중에 무엇이 함께 멈추는지 미리 확인하십시오.")
        return "\n".join(lines)

    # 정방향 — 이 출력이 왜 안 되는가
    act = _ACTION_KO.get(res.get("action"), res.get("action") or "")
    blocking = res.get("blocking") or []
    enabling = res.get("enabling") or []
    other = res.get("other") or []

    lines = ["%s 의 %s 조회 결과입니다. 해당 동작 규칙 %d건%s."
             % (tag, act, len(blocking) + len(enabling),
                ", 다른 동작 규칙 %d건" % len(other) if other else "")]

    n = 0
    for grp, label in ((blocking, "[%s 을(를) 막는 조건]" % act),
                       (enabling, "[%s 동작에 관여하는 규칙]" % act)):
        if not grp:
            continue
        lines.append("")
        lines.append(label)
        for it in grp:
            n += 1
            lines += _rule_text(it, n)
    if other:
        lines.append("")
        lines.append("[다른 동작 규칙 — 참고]")
        m = 0
        for it in other:
            m += 1
            lines += _rule_text(it, m)

    lines.append("")
    lines.append("위 내용은 인터락 리스트에서 읽은 값이며 해석을 덧붙이지 "
                 "않았습니다. 원문은 화면의 「원본 보기」에서 확인하십시오.")
    return "\n".join(lines)


def citations(res: Dict[str, Any]) -> List[Dict[str, str]]:
    """인용 목록 — 인터락 번호와 도면 번호를 근거로 내놓는다."""
    out = []
    if not res or not res.get("found"):
        return out
    groups = ([res.get("hits") or []] if res.get("as_input")
              else [res.get("blocking") or [], res.get("enabling") or [],
                    res.get("other") or []])
    for g in groups:
        for it in g:
            no = it.get("il_no")
            if not no:
                continue
            src = " · ".join(str(it[k]) for k in ("dwg_no", "sheet")
                             if it.get(k))
            out.append({"id": str(no), "title": str(no),
                        "cite": src or "인터락 리스트"})
    return out[:5]
