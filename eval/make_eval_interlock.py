#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_eval_interlock.py — 인터락 평가셋 생성

정답을 **원천 엑셀에서 직접 계산**한다. 조회 엔진(InterlockIndex)의
출력을 정답으로 삼으면 엔진이 틀려도 100%가 나오므로, 두 경로가
독립이어야 시험이 성립한다. 여기서는 load_interlocks() 가 돌려주는
원본 레코드만 보고 기대값을 만든다.

    python -m eval.make_eval_interlock --out eval/eval_set_interlock.json

문항 유형
    layer      출력 태그 + 동작 → 어느 항목이 blocking / enabling 인가
    reverse    입력 태그 → 영향받는 출력 목록
    absent     리스트에 없는 태그 → 없다고 답해야 함
    value      조건의 설정치·단위·지연이 원문대로인가
    unparsed   못 읽은 조건의 원문이 보존되는가
    attr       bypassable / reset / priority 속성이 정확한가

인터락 조회는 검색이 아니라 조회다. 정답이 리스트에 확정적으로
존재하므로 만점이 기본값이고, 이 평가의 목적은 성능 측정이 아니라
**층 분리 로직의 회귀 방지**다. 실물 인터락 리스트로 교체할 때
컬럼 구조가 달라지면 여기서 먼저 깨진다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ingest.interlock import load_interlocks  # noqa: E402

OPPOSITE = {"OPEN": "CLOSE", "CLOSE": "OPEN",
            "START": "STOP", "STOP": "START",
            "ON": "OFF", "OFF": "ON"}

# 리스트에 없는 태그. 존재하지 않는 것을 지어내지 않는지 본다.
ABSENT_TAGS = ["XV-9999", "P-9101A", "LCV-99", "UV-9999", "R-9999"]


def build(items):
    qs = []
    n = [0]

    def qid():
        n[0] += 1
        return "IL%02d" % n[0]

    by_out = {}
    for it in items:
        by_out.setdefault(it["output_tag"], []).append(it)

    # ── layer: 출력 태그 + 동작 ─────────────────────────────
    # 기대값을 원본 레코드에서 직접 계산한다.
    for tag, rows in sorted(by_out.items()):
        actions = sorted({r["action"] for r in rows})
        for action in actions:
            opp = OPPOSITE.get(action)
            blocking = [r["il_no"] for r in rows
                        if r["kind"] == "INTERLOCK" and r["action"] == opp]
            enabling = [r["il_no"] for r in rows if r["action"] == action]
            if not blocking and not enabling:
                continue
            qs.append({
                "id": qid(), "type": "layer",
                "tag": tag, "action": action,
                "expect_blocking": sorted(blocking),
                "expect_enabling": sorted(enabling),
                "note": "%s %s 시 막는 조건과 허가 조건의 분리" % (tag, action),
            })

    # ── reverse: 입력 태그 → 영향 출력 ──────────────────────
    by_in = {}
    for it in items:
        for c in it.get("conditions", []):
            for t in c.get("tags", []):
                by_in.setdefault(t, set()).add(it["output_tag"])
    # 여러 출력에 걸린 태그를 우선 — 역방향 조회의 값어치가 거기 있다
    ranked = sorted(by_in.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for t, outs in ranked[:12]:
        qs.append({
            "id": qid(), "type": "reverse",
            "tag": t,
            "expect_outputs": sorted(outs),
            "note": "%s 가 걸린 출력 %d개" % (t, len(outs)),
        })

    # ── absent: 없는 태그 ───────────────────────────────────
    known = set(by_out) | set(by_in)
    for t in ABSENT_TAGS:
        if t in known:
            continue
        qs.append({
            "id": qid(), "type": "absent", "tag": t,
            "expect_found": False,
            "note": "리스트에 없는 태그 — 지어내면 안 됨",
        })

    # ── value: 조건 값 정확도 ───────────────────────────────
    picked = 0
    for it in items:
        for c in it.get("conditions", []):
            if not c.get("parsed") or c.get("setpoint") is None:
                continue
            qs.append({
                "id": qid(), "type": "value",
                "tag": it["output_tag"], "il_no": it["il_no"],
                "cond_raw": c["raw"],
                "expect": {"setpoint": c["setpoint"], "unit": c.get("unit"),
                           "op": c.get("op"), "delay_sec": c.get("delay_sec")},
                "note": "설정치·단위·지연이 원문과 일치하는가",
            })
            picked += 1
            break
        if picked >= 10:
            break

    # ── unparsed: 미파싱 원문 보존 ──────────────────────────
    for it in items:
        for c in it.get("conditions", []):
            if c.get("parsed"):
                continue
            qs.append({
                "id": qid(), "type": "unparsed",
                "tag": it["output_tag"], "il_no": it["il_no"],
                "expect_raw": c["raw"],
                "note": "못 읽은 조건은 추측하지 않고 원문을 남겨야 함",
            })

    # ── attr: 속성 정확도 ───────────────────────────────────
    seen = set()
    for it in items:
        key = (it["kind"], it["bypassable"], it["reset"])
        if key in seen:
            continue
        seen.add(key)
        qs.append({
            "id": qid(), "type": "attr",
            "tag": it["output_tag"], "il_no": it["il_no"],
            "expect": {"kind": it["kind"], "bypassable": it["bypassable"],
                       "reset": it["reset"], "priority": it["priority"]},
            "note": "바이패스 가부와 리셋 방식은 안전 판단에 직결됨",
        })

    return qs


def main():
    ap = argparse.ArgumentParser(description="인터락 평가셋 생성")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "eval_set_interlock.json"))
    args = ap.parse_args()

    items = load_interlocks()
    qs = build(items)

    import collections
    cnt = collections.Counter(q["type"] for q in qs)
    doc = {
        "meta": {
            "source": "DEMO_INTERLOCK_LIST.xlsx (합성)",
            "generated_from": "ingest.interlock.load_interlocks — 조회 엔진과 독립",
            "interlock_rows": len(items),
            "fairness_note": (
                "정답은 원천 레코드에서 직접 계산했으며 조회 엔진의 출력을 "
                "쓰지 않았다. 인터락 조회는 검색이 아니라 조회이므로 만점이 "
                "기본값이며, 이 평가의 목적은 성능 측정이 아니라 층 분리 "
                "로직의 회귀 방지다."),
            "counts": dict(cnt),
        },
        "questions": qs,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print("인터락 %d건 → 평가 %d문항" % (len(items), len(qs)))
    for k, v in cnt.most_common():
        print("  %-9s %d" % (k, v))
    print("저장: %s" % args.out)


if __name__ == "__main__":
    main()
