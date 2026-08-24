# -*- coding: utf-8 -*-
"""
history_index.py — 현장 보수 이력 우선 매칭

조치 순서를 만들기 전에, 같은 증상을 겪은 기록이 있는지 먼저 본다.
특히 매뉴얼대로 했는데 아니었던 기록(manual_match == "불일치")은
매뉴얼 근거보다 앞에 세운다.

설계 판단 — 매칭 축은 태그·증상·기종 세 가지다. 셋 다 사용자 입력이나
Instrument List 조회에서 항상 얻어지므로, **검색이 실패해도 이력은
나온다.** 알람 코드(code_ref)를 축으로 삼으면 검색이 코드표를 집지
못하는 순간 이력 기능 전체가 죽기 때문에, 코드는 정렬 가산 신호로만
쓴다.

이력의 symptom 은 전부 한글이고 질의도 한글이다. 매뉴얼 검색이 겪는
한글→영문 문제가 없으므로 임베딩 없이 어휘 겹침으로 충분하다.
같은 입력에 항상 같은 결과가 나오는 결정적 함수여야 한다 — 채점
가능성이 여기에 달려 있다.

    python -m retrieval.history_index --tag AIT-4002 --symptom "시료 유량 미검출"
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Sequence

# ── 규칙 상수 ────────────────────────────────────────────────
SIM_THRESHOLD = 0.35      # 진짜 유사 건 0.438 과 무관 건 0.333 사이. calibrate 참조
MAX_PER_LAYER = 3
MAX_TOTAL = 5

_GRADE_ORDER = {"불일치": 0, "부분일치": 1, "일치": 2, "": 3, None: 3}

# 증상 문구에서 정보가 없는 말들. 어느 이력에나 붙어서
# 겹침 점수를 부풀리기만 한다.
_STOP = {
    "알람", "경고", "진단", "감지", "발생", "이상", "확인", "상태",
    "및", "또는", "미만", "이상값", "alarm", "warning", "error",
}


# ── 토큰화 ──────────────────────────────────────────────────
def _tokens(text: str) -> List[str]:
    """
    한글·영숫자 토큰. 한글은 조사를 떼지 않는다 — 형태소 분석기를
    넣으면 의존성이 늘고, 이 규모(수십 건)에서는 이득이 없다.
    대신 2글자 이상만 남겨 조사 단독 토큰을 배제한다.
    """
    if not text:
        return []
    t = unicodedata.normalize("NFKC", str(text)).lower()
    raw = re.findall(r"[가-힣]+|[a-z]+|\d+", t)
    out = []
    for w in raw:
        if len(w) < 2:
            continue
        if w in _STOP:
            continue
        out.append(w)
    return out


def _bigrams(tokens: Sequence[str]) -> set:
    """
    한글 토큰은 조사가 붙어 어미가 달라진다("유량이" vs "유량").
    2-gram 문자열까지 비교해 부분 일치를 잡는다.
    """
    g = set()
    for w in tokens:
        if re.match(r"^[가-힣]+$", w) and len(w) > 2:
            for i in range(len(w) - 1):
                g.add(w[i:i + 2])
        else:
            g.add(w)
    return g


# ── 극성 가드 ────────────────────────────────────────────────
# 계장 고장 문구는 정반대 고장이 글자만 한 두 개 다르다.
#   "Cond Cell open" 과 "Cond Cell shorted"  — 단선과 단락
#   "상한 위반" 과 "하한 위반"                 — High 와 Low
# 어휘 겹침으로는 0.5, 0.43 이 나와서 진짜 유사 건(0.44)과 구분되지
# 않는다. 임계값을 조정해 가르려 하면 이 데이터에만 맞는 값이 된다.
#
# 그래서 임계값이 아니라 **규칙**으로 막는다. 질의와 이력이 서로 반대
# 극성을 가지면 어휘가 아무리 겹쳐도 유사도를 0 으로 만든다. 반대
# 고장의 조치를 앞세우는 것은 도움이 아니라 오도다.
_POLARITY = [
    ({"open", "단선", "개방", "오픈"}, {"shorted", "short", "단락", "쇼트"}),
    ({"high", "상한", "고온", "과대", "초과", "상승"},
     {"low", "하한", "저온", "과소", "미만", "저하"}),
    ({"기동", "개도", "열림"}, {"정지", "폐쇄", "닫힘"}),
]


def _polarity_conflict(qt: Sequence[str], st: Sequence[str]) -> bool:
    """질의와 이력이 반대 극성이면 True."""
    qs, ss = set(qt), set(st)
    for pos, neg in _POLARITY:
        if (qs & pos and ss & neg) or (qs & neg and ss & pos):
            # 양쪽 다 가진 경우(예: "상한·하한 모두")는 충돌이 아니다
            if not ((qs & pos and qs & neg) or (ss & pos and ss & neg)):
                return True
    return False


def similarity(query: str, symptom: str) -> float:
    """
    증상 유사도 0.0~1.0. 결정적이다.

    토큰 자카드와 문자 2-gram 자카드의 가중 평균. 전자는 정확히 같은
    단어를, 후자는 어미가 다른 같은 말을 잡는다. 단, 극성이 반대면
    겹침과 무관하게 0 이다.
    """
    qt, st = _tokens(query), _tokens(symptom)
    if not qt or not st:
        return 0.0
    if _polarity_conflict(qt, st):
        return 0.0

    qs, ss = set(qt), set(st)
    jacc_tok = len(qs & ss) / len(qs | ss)

    qg, sg = _bigrams(qt), _bigrams(st)
    jacc_gram = len(qg & sg) / len(qg | sg) if (qg | sg) else 0.0

    return round(0.4 * jacc_tok + 0.6 * jacc_gram, 4)


# ── 매칭 ────────────────────────────────────────────────────
def _sort_key(row: dict) -> tuple:
    """
    1) 불일치 우선  2) code_ref 일치  3) 부분일치  4) 최신순

    불일치를 최우선에 두는 것이 이 규칙의 핵심이다. 매뉴얼대로 해서
    안 됐던 기록이 가장 값어치 있는 정보다.
    """
    return (
        _GRADE_ORDER.get(row.get("manual_match"), 3),
        0 if row.get("_code_hit") else 1,
        -row.get("_sim", 0.0),
        row.get("date") or "",
    )


def match(
    history: List[dict],
    tag: str,
    symptom_query: str = "",
    device=None,
    code_ref: Optional[str] = None,
    threshold: float = SIM_THRESHOLD,
    related_tags: Optional[Sequence[str]] = None,
) -> List[dict]:
    """
    3단 매칭. 상위 단계에서 걸린 이력은 하위에서 중복 수집하지 않는다.

      L1  태그 일치 AND 증상 유사도 >= threshold
      L2  태그 일치 (증상 무관)
      L3  기종 일치 AND 증상 유사도 >= threshold (태그 불일치)

    device 는 문자열 또는 목록이다. 이력의 device 는 층위가 섞여 있다 —
    계기 기종(M9e, M300)으로 적힌 건과 IO 카드 기종(AI 16xI 2-wire
    HART HA)으로 적힌 건이 함께 있다. 계기 리스트의 MODEL 하나만
    넘기면 카드 고장 이력이 통째로 안 걸린다. 실제로 PIT-1010 은
    MODEL 이 TX-2000 이라 카드 단선 이력을 놓쳤다. 호출부에서
    [계기 MODEL, config.CARD_DEVICE] 처럼 후보를 함께 넘긴다.

    device 만 같고 증상이 다른 이력은 수집하지 않는다. 같은 기종이라는
    이유만으로 무관한 고장을 끌어오면 노이즈가 된다 — 데모 데이터에서
    M9e 만 16건이라, 이 조건이 없으면 M9e 태그마다 무관한 이력이
    대량으로 딸려온다.

    반환: 이력 dict 사본 목록. 각 항목에 _layer, _sim, _code_hit 추가.
    """
    if not history:
        return []

    tags = {t for t in ([tag] + list(related_tags or [])) if t}
    if device is None:
        devs = set()
    elif isinstance(device, str):
        devs = {device.strip().lower()} if device.strip() else set()
    else:
        devs = {str(d).strip().lower() for d in device if d and str(d).strip()}

    scored = []
    for h in history:
        row = dict(h)
        row["_sim"] = similarity(symptom_query, h.get("symptom", "")) \
            if symptom_query else 0.0
        row["_code_hit"] = bool(
            code_ref and h.get("code_ref")
            and str(h["code_ref"]).strip().lower() == str(code_ref).strip().lower()
        )
        scored.append(row)

    same_tag = [r for r in scored if r.get("tag") in tags]
    other_tag = [r for r in scored if r.get("tag") not in tags]

    l1 = [r for r in same_tag if r["_sim"] >= threshold]
    l1_wo = {r.get("wo_no") for r in l1}
    l2 = [r for r in same_tag if r.get("wo_no") not in l1_wo]

    l3 = []
    if devs:
        l3 = [r for r in other_tag
              if (r.get("device") or "").strip().lower() in devs
              and r["_sim"] >= threshold]

    out = []
    for layer, rows in (("L1", l1), ("L2", l2), ("L3", l3)):
        rows = sorted(rows, key=_sort_key)[:MAX_PER_LAYER]
        for r in rows:
            r["_layer"] = layer
            out.append(r)
    return out[:MAX_TOTAL]


# ── 카드 ────────────────────────────────────────────────────
_LAYER_WHY = {
    "L1": "동일 태그 · 증상 일치",
    "L2": "동일 태그 · 다른 증상",
    "L3": "같은 기종 · 증상 일치",
}


def grade_of(rows: List[dict]) -> Optional[str]:
    """카드 등급. 없으면 None(카드 미표시)."""
    if not rows:
        return None
    marks = {r.get("manual_match") for r in rows}
    if "불일치" in marks:
        return "경고"
    if "부분일치" in marks:
        return "참고"
    return "확인"


_GRADE_MSG = {
    "경고": "매뉴얼과 다른 원인이 기록된 사례가 있습니다",
    "참고": "유사 사례가 있습니다",
    "확인": "매뉴얼과 같은 원인으로 처리된 사례가 있습니다",
}


def build_card(rows: List[dict]) -> Optional[dict]:
    """
    조치 순서 맨 앞에 꽂을 카드. 이력 원문을 그대로 옮기며 요약하거나
    재서술하지 않는다 — 요약하는 순간 근거가 아니라 생성물이 된다.
    """
    grade = grade_of(rows)
    if not grade:
        return None

    items = []
    for i, r in enumerate(rows, 1):
        items.append({
            "ref": "H%d" % i,
            "wo_no": r.get("wo_no", ""),
            "date": r.get("date", ""),
            "tag": r.get("tag", ""),
            "symptom": r.get("symptom", ""),
            "manual_match": r.get("manual_match", ""),
            "first_action": r.get("first_action", ""),
            "root_cause": r.get("root_cause", ""),
            "action_taken": r.get("action_taken", ""),
            "duration_min": r.get("duration_min"),
            "tech": r.get("tech", ""),
            "why": "%s (%s)" % (r.get("_layer", ""),
                                _LAYER_WHY.get(r.get("_layer", ""), "")),
            "sim": r.get("_sim", 0.0),
        })

    return {
        "n": 0,
        "kind": "history",
        "grade": grade,
        "title": "현장 이력 %d건 — %s" % (len(items), _GRADE_MSG[grade]),
        "detail": _GRADE_MSG[grade],
        "items": items,
        "source": "maintenance_history",
    }


def prompt_block(rows: List[dict]) -> str:
    """LLM 프롬프트에 넣을 이력 절. 근거 번호와 구분되게 H 접두를 쓴다."""
    if not rows:
        return ""
    out = ["현장 이력 (같은 태그·기종의 유사 증상, 관련도 순):"]
    for i, r in enumerate(rows, 1):
        out.append(
            "[H%d] %s · %s · %s | 매뉴얼 대조: %s\n"
            "     처음 조치: %s\n"
            "     실제 원인: %s\n"
            "     최종 조치: %s" % (
                i, r.get("date", ""), r.get("tag", ""), r.get("symptom", ""),
                r.get("manual_match", ""), r.get("first_action", ""),
                r.get("root_cause", ""), r.get("action_taken", ""))
        )
    return "\n".join(out)


# ── 임계값 보정 ──────────────────────────────────────────────
def calibrate(history: List[dict], verbose: bool = True) -> dict:
    """
    이력의 symptom 을 그대로 질의로 넣었을 때, 자기 자신이 1위로
    잡히고 무관한 건이 안 딸려오는 지점을 찾는다.

    **평가셋 점수를 보며 조정하지 않는다.** 평가셋에 맞춘 임계값은
    그 평가셋에서만 좋아 보인다.
    """
    sims_self, sims_other = [], []
    for a in history:
        for b in history:
            s = similarity(a.get("symptom", ""), b.get("symptom", ""))
            (sims_self if a.get("symptom") == b.get("symptom")
             else sims_other).append(s)

    sims_other.sort(reverse=True)
    res = {
        "self_min": min(sims_self) if sims_self else 0,
        "other_max": sims_other[0] if sims_other else 0,
        "other_p95": sims_other[max(0, len(sims_other) // 20)] if sims_other else 0,
        "other_p99": sims_other[max(0, len(sims_other) // 100)] if sims_other else 0,
    }
    if verbose:
        for k, v in res.items():
            print("  %-10s %.4f" % (k, v))
    return res


if __name__ == "__main__":
    import argparse
    import json
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config  # noqa: E402

    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="")
    ap.add_argument("--symptom", default="")
    ap.add_argument("--device", default="")
    ap.add_argument("--code", default="")
    ap.add_argument("--calibrate", action="store_true")
    args = ap.parse_args()

    with open(config.HISTORY, encoding="utf-8") as f:
        hist = json.load(f)

    if args.calibrate:
        print("임계값 보정 (이력 %d건)" % len(hist))
        calibrate(hist)
        sys.exit(0)

    rows = match(hist, args.tag, args.symptom, args.device or None,
                 args.code or None)
    card = build_card(rows)
    if not card:
        print("이력 없음")
    else:
        print("[%s] %s\n" % (card["grade"], card["title"]))
        for it in card["items"]:
            print("  [%s] %s · %s · %s" % (
                it["ref"], it["date"], it["tag"], it["symptom"]))
            print("       매뉴얼 대조: %s · 매칭: %s · sim=%.3f"
                  % (it["manual_match"], it["why"], it["sim"]))
            print("       실제 원인: %s" % it["root_cause"])
            print("       최종 조치: %s\n" % it["action_taken"])
