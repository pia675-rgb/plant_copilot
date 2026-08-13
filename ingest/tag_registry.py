#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tag_registry.py — IO List · 계기 리스트 · 인터락 리스트 태그 교차 점검

세 문서는 각자 관리되지만 **TAG 로 서로를 가리킨다.** 한쪽에서 태그를
고치고 다른 쪽을 안 고치면 조회가 조용히 빈다. 화면에는 그럴듯한 답이
뜨고, 어긋났다는 사실 자체가 드러나지 않는다.

    IO_LIST.xlsx          배선 — 이 태그가 어느 카드 어느 채널인가
    INSTRUMENT_LIST.xlsx  사양 — 제조사·모델·스케일 (실물 양식, 2단 머리)
    DEMO_INTERLOCK_LIST   논리 — 이 태그가 어떤 인터락의 조건·출력인가

여기서는 **판정하지 않고 대조만** 한다. 어느 쪽이 맞는지는 문서를 가진
사람이 정한다. 이 모듈은 "두 문서가 다르다" 까지만 말한다.

── 표기 정규화를 따로 보는 이유 ──────────────────────────────

현장에서 같은 계기를 AIT-1001 / AIT1001 / ait-1001 로 적는다. 완전일치
대조만 하면 "없는 태그" 로 잡히는데, 실제로는 표기 차이다. 둘을 나눠서
보고해야 사람이 무엇을 고칠지 안다.

    누락        정규화해도 짝이 없다        → 문서를 고쳐야 한다
    표기 불일치  정규화하면 같다             → 표기를 통일하면 된다
    태그 형식 아님 접두어가 실재 태그와 다르다 → 파서가 문구를 잘못 뽑았다

    python -m ingest.tag_registry
"""

import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from ingest.lists import read_rows, read_instrument_rows  # noqa: E402


def norm(tag):
    """대소문자·구분자 차이를 지운 대조 키."""
    return re.sub(r"[^A-Z0-9]", "", str(tag or "").upper())


def tag_prefixes(tags):
    """실재하는 태그에서 접두어를 뽑는다 (AIT, PIT, XV, P …)."""
    out = set()
    for t in tags:
        m = re.match(r"^([A-Za-z]+)", str(t))
        if m:
            out.add(m.group(1).upper())
    return out


def _tags(rows):
    return [str(r.get("TAG") or "").strip() for r in rows
            if str(r.get("TAG") or "").strip()]


def _dups(tags):
    return sorted(t for t, n in Counter(tags).items() if n > 1)


def collect():
    """세 문서에서 태그를 모은다. 없는 문서는 빈 목록으로 둔다."""
    io_rows = read_rows(config.IO_LIST if os.path.isfile(config.IO_LIST)
                        else config.INSTRUMENTS)
    # 계기 리스트는 실물 양식(2단 머리)이라 전용 리더가 필요하다.
    spec_rows = read_instrument_rows(getattr(config, "INSTRUMENT_SPECS", None) or getattr(config, "INSTRUMENT_SPEC", ""))

    cond, outs = [], []
    try:
        from ingest.interlock import load_interlocks
        for it in load_interlocks():
            outs.append(str(it.get("output_tag") or "").strip())
            for c in it["conditions"]:
                cond.extend(str(t).strip() for t in c["tags"])
    except Exception as e:                                  # noqa: BLE001
        print("[tag] 인터락 리스트를 읽지 못했습니다:", e)

    return {
        "io": _tags(io_rows),
        "spec": _tags(spec_rows),
        "il_input": sorted({t for t in cond if t}),
        "il_output": sorted({t for t in outs if t}),
    }


def _compare(left, right, label_l, label_r):
    """
    left 에 있는데 right 에 없는 태그를 누락과 표기 불일치로 나눈다.
    """
    idx = defaultdict(list)
    for t in right:
        idx[norm(t)].append(t)
    missing, mismatch = [], []
    for t in sorted(set(left)):
        if t in right:
            continue
        near = idx.get(norm(t))
        if near:
            mismatch.append({"tag": t, "in": label_l,
                             "counterpart": sorted(set(near)), "of": label_r})
        else:
            missing.append({"tag": t, "in": label_l, "missing_from": label_r})
    return missing, mismatch


def cross_check():
    """
    대조 결과. findings 가 비면 세 문서의 태그가 서로 맞는다는 뜻이다.
    """
    t = collect()
    findings = defaultdict(list)

    # 리스트 안의 중복
    for key, label in (("io", "IO List"), ("spec", "계기 리스트")):
        for d in _dups(t[key]):
            findings["중복"].append({"tag": d, "in": label})

    # 배선 ↔ 사양
    m, x = _compare(t["io"], t["spec"], "IO List", "계기 리스트")
    findings["사양 없음"] += m
    findings["표기 불일치"] += x
    m, x = _compare(t["spec"], t["io"], "계기 리스트", "IO List")
    findings["배선 없음"] += m
    findings["표기 불일치"] += x

    # 인터락 조건 태그는 IO List 에 있어야 신호 출처가 확인된다.
    # 다만 조건이 자연어라 파서가 태그가 아닌 문구를 뽑는 경우가 있다
    # ("STAND-BY" 등). 접두어가 실재 태그와 다르면 그쪽으로 분류한다 —
    # 문서 누락과 파서 오추출은 고쳐야 할 곳이 다르다.
    # 접두어 목록에 인터락 출력 태그도 넣는다. 지금 IO List 에는 입력만
    # 있어서 P·XV 접두어가 잡히지 않았고, 실제 출력 태그가 '태그 형식
    # 아님' 으로 분류됐다. 접두어 목록이 좁으면 진짜 누락이 파서 오류로
    # 둔갑한다.
    pres = (tag_prefixes(t["io"]) | tag_prefixes(t["spec"])
            | tag_prefixes(t["il_output"]))
    m, x = _compare(t["il_input"], t["io"], "인터락 조건", "IO List")
    for f in m:
        head = re.match(r"^([A-Za-z]+)", f["tag"])
        if head and head.group(1).upper() in pres:
            findings["조건 태그 출처 불명"].append(f)
        else:
            findings["태그 형식 아님"].append(
                {"tag": f["tag"], "in": "인터락 조건",
                 "missing_from": "태그 접두어 목록"})
    findings["표기 불일치"] += x

    # 인터락 출력 태그는 어느 문서에 있는가
    known = set(t["io"]) | set(t["spec"])
    for tag in t["il_output"]:
        if tag in known:
            continue
        near = [k for k in known if norm(k) == norm(tag)]
        if near:
            findings["표기 불일치"].append(
                {"tag": tag, "in": "인터락 출력",
                 "counterpart": sorted(near), "of": "IO List/계기 리스트"})
        else:
            findings["출력 태그 출처 불명"].append(
                {"tag": tag, "in": "인터락 출력",
                 "missing_from": "IO List·계기 리스트"})

    counts = {k: len(v) for k, v in findings.items() if v}
    return {
        "counts": {"io": len(set(t["io"])), "spec": len(set(t["spec"])),
                   "interlock_input": len(t["il_input"]),
                   "interlock_output": len(t["il_output"])},
        "findings": {k: v for k, v in findings.items() if v},
        "finding_counts": counts,
        "total": sum(counts.values()),
        "note": ("어느 쪽이 맞는지는 판정하지 않습니다 — 두 문서가 다르다는 "
                 "사실만 대조했습니다. 표기 불일치는 정규화하면 짝이 있는 "
                 "경우이고, 누락은 짝 자체가 없는 경우입니다."),
    }


def render():
    d = cross_check()
    c = d["counts"]
    L = ["=" * 76, "태그 교차 정합성 — IO List · 계기 리스트 · 인터락 리스트",
         "=" * 76,
         "IO List %d · 계기 리스트 %d · 인터락 조건 %d · 인터락 출력 %d"
         % (c["io"], c["spec"], c["interlock_input"], c["interlock_output"]),
         ""]
    if not d["findings"]:
        L.append("지적 없음 — 세 문서의 태그가 서로 맞습니다.")
    for kind, items in d["findings"].items():
        L.append("■ %s %d건" % (kind, len(items)))
        for f in items[:20]:
            if "counterpart" in f:
                L.append("   %s (%s) ↔ %s (%s)"
                         % (f["tag"], f["in"], ", ".join(f["counterpart"]),
                            f["of"]))
            else:
                L.append("   %s — %s 에 있으나 %s 에 없음"
                         % (f["tag"], f["in"],
                            f.get("missing_from", f.get("of", ""))))
        if len(items) > 20:
            L.append("   … 외 %d건" % (len(items) - 20))
        L.append("")
    L.append("※ " + d["note"])
    L.append("=" * 76)
    return "\n".join(L)


if __name__ == "__main__":
    print(render())
