# -*- coding: utf-8 -*-
"""
make_eval_history.py — 이력 우선 규칙 평가셋 생성·채점

이력 원천 레코드에서 문항을 자동 생성한다. 사람이 문항을 쓰면 구현과
같은 편향이 들어가고, 무엇보다 자료가 바뀔 때마다 다시 써야 한다.

**부정 문항이 절반이다.** 나와야 할 것이 나오는지만 재면 규칙을 한없이
넓혀도 만점이 나온다. 나오면 안 되는 것이 안 나오는지를 같이 재야
점수가 의미를 갖는다.

    python -m eval.make_eval_history            # 생성 + 채점
    python -m eval.make_eval_history --mutate   # 변이 시험
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config                                                    # noqa: E402
from retrieval import history_index as HX                        # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "eval_set_history.json")

# device_guard 합성 픽스처. 실이력의 문구를 쓰지 않는다 — 자료가 바뀌면
# 같이 흔들려서, 규칙이 깨진 것인지 문구가 바뀐 것인지 가릴 수 없다.
_SYN_SYMPTOM = "시료 유량 미검출"
_SYN_DEV_OK = "SYN-DEV-A"
_SYN_DEV_NG = "SYN-DEV-B"


def load_hist():
    with open(config.HISTORY, encoding="utf-8") as f:
        return json.load(f)


# ── 문항 생성 ───────────────────────────────────────────────
def build(hist):
    q = []
    by_tag = defaultdict(list)
    by_dev = defaultdict(list)
    for h in hist:
        by_tag[h["tag"]].append(h)
        by_dev[h.get("device", "")].append(h)

    # l1_hit — 자기 증상으로 물으면 자기 이력이 나와야 한다
    for h in hist:
        q.append({
            "id": "l1_%s" % h["wo_no"], "type": "l1_hit",
            "tag": h["tag"], "symptom": h["symptom"],
            "device": h.get("device", ""),
            "expect_contains": [h["wo_no"]],
        })

    # l3_cross — 같은 기종 다른 태그의 같은 증상이 나와야 한다
    seen = set()
    for dev, rows in by_dev.items():
        for a in rows:
            for b in rows:
                if a["tag"] == b["tag"] or a["wo_no"] == b["wo_no"]:
                    continue
                if HX.similarity(a["symptom"], b["symptom"]) < HX.SIM_THRESHOLD:
                    continue
                key = (a["wo_no"], b["wo_no"])
                if key in seen:
                    continue
                seen.add(key)
                q.append({
                    "id": "l3_%s_%s" % (a["wo_no"], b["wo_no"]),
                    "type": "l3_cross",
                    "tag": a["tag"], "symptom": a["symptom"],
                    "device": dev,
                    "expect_contains": [b["wo_no"]],
                })

    # sort_rule — 정렬 규칙을 격리해서 시험한다.
    #
    # 처음에는 "불일치 이력의 증상으로 물으면 그 이력이 1위인가"로
    # 만들었는데, 그 이력이 유사도 1.0 이라 어떤 정렬을 써도 1위가
    # 됐다. 정렬을 껐는데 점수가 그대로였다 — 문항이 아무것도
    # 시험하지 못한 것이다.
    #
    # 그래서 **유사도가 같은 상황을 인위적으로 만들어** 정렬만
    # 남긴다. 같은 태그·같은 증상 문구를 쓰는 이력 묶음에서
    # 등급이 섞인 경우를 찾는다.
    by_key = defaultdict(list)
    for h in hist:
        by_key[(h["tag"], h["symptom"])].append(h)
    for (tg, sym), rows in by_key.items():
        marks = {r.get("manual_match") for r in rows}
        if len(rows) < 2 or "불일치" not in marks or marks == {"불일치"}:
            continue
        worst = [r for r in rows if r.get("manual_match") == "불일치"]
        q.append({
            "id": "sr_%s" % worst[0]["wo_no"], "type": "sort_rule",
            "tag": tg, "symptom": sym, "device": rows[0].get("device", ""),
            "expect_first_in": [r["wo_no"] for r in worst],
        })

    # 같은 태그·같은 문구 묶음이 없으면 합성 픽스처로 규칙을 시험한다.
    # 실데이터에 해당 상황이 없다고 규칙을 안 재고 넘어갈 수는 없다.
    if not any(x["type"] == "sort_rule" for x in q):
        q.append({
            "id": "sr_synth", "type": "sort_rule", "synthetic": True,
            "expect_first_in": ["SYN-BAD"],
        })

    # grade — 등급 판정
    for h in hist:
        rows = HX.match(hist, h["tag"], h["symptom"], h.get("device"))
        g = HX.grade_of(rows)
        if not g:
            continue
        q.append({
            "id": "gr_%s" % h["wo_no"], "type": "grade",
            "tag": h["tag"], "symptom": h["symptom"],
            "device": h.get("device", ""),
            "expect_grade": g,
        })

    # no_leak — 이력에 없는 태그에는 카드가 없어야 한다
    unknown = ["ZZT-9999", "FIT-0001", "XV-9911", "PT-8888", "LT-7777"]
    for t in unknown:
        for h in hist[:2]:
            q.append({
                "id": "nl_%s_%s" % (t, h["wo_no"]), "type": "no_leak",
                "tag": t, "symptom": h["symptom"], "device": "",
                "expect_empty": True,
            })

    # device_guard — 증상이 비슷해도 기종이 다르면 안 끌어온다
    for a in hist:
        for b in hist:
            if a["tag"] == b["tag"]:
                continue
            if (a.get("device") or "") == (b.get("device") or ""):
                continue
            if HX.similarity(a["symptom"], b["symptom"]) < HX.SIM_THRESHOLD:
                continue
            q.append({
                "id": "dg_%s_%s" % (a["wo_no"], b["wo_no"]),
                "type": "device_guard",
                "tag": a["tag"], "symptom": a["symptom"],
                "device": a.get("device", ""),
                "expect_absent": [b["wo_no"]],
            })

    # 교차 기종 쌍이 하나도 안 걸리면 합성 픽스처로 규칙을 시험한다.
    #
    # 현재 자료에서 실제로 그렇다. 다른 기종 쌍 500개의 최대 유사도가
    # 0.125 로 임계(0.35) 근처에도 못 온다 — 기종이 다르면 증상 문구도
    # 아예 다르게 적혀 있다. 그래서 device 조건을 통째로 지워도 실데이터
    # 문항은 한 개도 안 무너진다. **규칙을 안 재고 있는 상태다.**
    #
    # sort_rule 과 같은 처리를 한다. 자료에 상황이 없다는 것이 규칙을
    # 안 재도 된다는 뜻은 아니다.
    if not any(x["type"] == "device_guard" for x in q):
        q.append({
            "id": "dg_synth", "type": "device_guard", "synthetic_device": True,
            "expect_contains": ["GD-SAME"],
            "expect_absent": ["GD-OTHER"],
        })

    # no_search — 검색이 통째로 실패해도(code_ref 없음) 카드는 나와야 한다
    for h in hist:
        if h.get("manual_match") != "불일치":
            continue
        q.append({
            "id": "ns_%s" % h["wo_no"], "type": "no_search",
            "tag": h["tag"], "symptom": h["symptom"],
            "device": h.get("device", ""),
            "no_code": True,
            "expect_contains": [h["wo_no"]],
        })

    return q


# ── 채점 ────────────────────────────────────────────────────
def grade(hist, questions, opts=None):
    opts = opts or {}
    res = Counter()
    fails = []

    for q in questions:
        if q.get("synthetic"):
            fixture = [
                dict(wo_no="SYN-OK", manual_match="일치", date="2026-01-01",
                     _sim=0.9, _code_hit=False, _layer="L1"),
                dict(wo_no="SYN-BAD", manual_match="불일치", date="2025-01-01",
                     _sim=0.9, _code_hit=False, _layer="L1"),
                dict(wo_no="SYN-MID", manual_match="부분일치", date="2026-06-01",
                     _sim=0.9, _code_hit=False, _layer="L1"),
            ]
            got = sorted(fixture, key=HX._sort_key)
            ok = got[0]["wo_no"] in q["expect_first_in"]
            res[q["type"] + ("_ok" if ok else "_ng")] += 1
            if not ok:
                fails.append((q["id"], q["type"], [r["wo_no"] for r in got]))
            continue
        if q.get("synthetic_device"):
            # 같은 증상 문구를 기종만 달리해서 둘 놓는다. 기종이 맞는
            # 쪽은 걸리고 다른 쪽은 안 걸려야 한다.
            #
            # 두 가지를 한 문항에서 함께 본다. 배제만 재면 L3 를 통째로
            # 지워도 만점이 나오고, 수집만 재면 device 조건을 지워도
            # 만점이 나온다. 한쪽만으로는 규칙을 못 가둔다.
            fx = [
                dict(wo_no="GD-SAME", tag="TAG-B", device=_SYN_DEV_OK,
                     symptom=_SYN_SYMPTOM, manual_match="일치",
                     date="2026-01-01"),
                dict(wo_no="GD-OTHER", tag="TAG-C", device=_SYN_DEV_NG,
                     symptom=_SYN_SYMPTOM, manual_match="일치",
                     date="2026-01-02"),
            ]
            rows = HX.match(fx, "TAG-A", _SYN_SYMPTOM, _SYN_DEV_OK)
            wos = [r.get("wo_no") for r in rows]
            ok = (all(w in wos for w in q["expect_contains"])
                  and all(w not in wos for w in q["expect_absent"]))
            res[q["type"] + ("_ok" if ok else "_ng")] += 1
            if not ok:
                fails.append((q["id"], q["type"], wos))
            continue

        rows = HX.match(
            hist, q["tag"], q.get("symptom", ""), q.get("device") or None,
            code_ref=None if q.get("no_code") else q.get("code_ref"),
            threshold=opts.get("threshold", HX.SIM_THRESHOLD),
        )
        wos = [r.get("wo_no") for r in rows]
        ok = True

        if q.get("expect_contains"):
            ok = all(w in wos for w in q["expect_contains"])
        elif q.get("expect_absent"):
            ok = all(w not in wos for w in q["expect_absent"])
        elif q.get("expect_first_in"):
            ok = bool(wos) and wos[0] in q["expect_first_in"]
        elif q.get("expect_empty"):
            ok = (HX.grade_of(rows) is None)
        elif q.get("expect_grade"):
            ok = (HX.grade_of(rows) == q["expect_grade"])

        res[q["type"] + ("_ok" if ok else "_ng")] += 1
        if not ok:
            fails.append((q["id"], q["type"], wos))

    return res, fails


def report(res, fails, title="채점"):
    types = sorted({k.rsplit("_", 1)[0] for k in res})
    tot_ok = tot = 0
    print("\n%s" % title)
    for t in types:
        ok, ng = res[t + "_ok"], res[t + "_ng"]
        tot_ok += ok
        tot += ok + ng
        print("  %-16s %3d/%3d" % (t, ok, ok + ng))
    print("  %-16s %3d/%3d" % ("합계", tot_ok, tot))
    if fails:
        print("  실패 %d건 (앞 5건): %s"
              % (len(fails), ", ".join(f[0] for f in fails[:5])))
    return tot_ok, tot


# ── 변이 시험 ───────────────────────────────────────────────
def _neg_date(d):
    """날짜 문자열 내림차순 정렬용 키."""
    return tuple(-int(x) for x in d.split("-")) if d else (0, 0, 0)


def mutate(hist, questions):
    """
    기능을 하나씩 꺼서 해당 문항만 무너지는지 본다. 점수가 허수가
    아님을 확인하는 유일한 방법이다.
    """
    print("\n=== 변이 시험 ===")
    base_match = HX.match

    # 1. L3 매칭 제거
    def no_l3(history, tag, symptom_query="", device=None, **kw):
        return base_match(history, tag, symptom_query, None, **kw)

    # 2. 불일치 우선 정렬 제거 (날짜순으로만)
    orig_key = HX._sort_key

    def flat_key(row):
        # 자연스러운 대안 정렬은 '최신순'이다. 오름차순으로 두면
        # 불일치 건이 대체로 이른 날짜라 우연히 같은 순서가 나와서
        # 변이가 아무것도 시험하지 못한다.
        return (_neg_date(row.get("date") or ""),)

    # 3. device 조건 제거 (L3 를 증상만으로)
    def no_dev(history, tag, symptom_query="", device=None, **kw):
        rows = base_match(history, tag, symptom_query, device, **kw)
        extra = [dict(h, _layer="L3", _sim=HX.similarity(symptom_query,
                                                         h.get("symptom", "")),
                      _code_hit=False)
                 for h in history
                 if h.get("tag") != tag
                 and HX.similarity(symptom_query, h.get("symptom", ""))
                 >= HX.SIM_THRESHOLD]
        seen = {r.get("wo_no") for r in rows}
        return (rows + [e for e in extra if e.get("wo_no") not in seen])[:5]

    # 4. 증상 유사도 무시 (전건 수집)
    def no_sim(history, tag, symptom_query="", device=None, **kw):
        rows = [dict(h, _layer="L2", _sim=1.0, _code_hit=False)
                for h in history]
        return rows[:5]

    for name, fn, key in (
        ("L3 매칭 제거", no_l3, None),
        ("불일치 우선 정렬 제거", None, flat_key),
        ("device 조건 제거", no_dev, None),
        ("증상 유사도 무시", no_sim, None),
    ):
        if fn:
            HX.match = fn
        if key:
            HX._sort_key = key
        r, f = grade(hist, questions)
        report(r, f, "변이: %s" % name)
        HX.match = base_match
        HX._sort_key = orig_key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    args = ap.parse_args()

    hist = load_hist()
    qs = build(hist)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(qs, f, ensure_ascii=False, indent=1)
    print("문항 %d개 생성 → %s" % (len(qs), OUT))
    print("  유형별:", dict(Counter(q["type"] for q in qs)))

    r, fl = grade(hist, qs)
    report(r, fl, "=== 기준 채점 ===")

    if args.mutate:
        mutate(hist, qs)


if __name__ == "__main__":
    main()
