#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_eval_panel.py — 판넬 조회 평가셋 생성

정답을 **원천(계기 리스트 엑셀 · 배치 CSV · 인터락 엑셀)에서 직접 계산**
한다. PanelIndex 의 출력을 정답으로 쓰면 엔진이 틀려도 만점이 나오므로
두 경로가 독립이어야 시험이 성립한다.

    python -m eval.make_eval_panel --out eval/eval_set_panel.json

문항 유형
    locate    계기 태그 → 어느 판넬·카드인가
    place     판넬 → 구역·그리드가 배치도와 일치하는가
    roster    판넬 → 물려 있는 계기 집합
    card      카드 → 물려 있는 채널 집합
    cscope    카드 상실 → 영향받는 출력 집합
    cdepend   카드 상실 → 남는 보호가 없는 인터락 집합
    common    한 인터락의 조건이 같은 카드에 몰려 있는가
    absent    없는 판넬·태그·카드 → 지어내지 않는지

이중화(S7-400H/410H) 구성에서 CPU·전원·통신은 이중화되고 랙 증설도
스위칭으로 대응한다. 단일인 것은 IO 카드뿐이므로 상실 문항은
카드 단위(cscope/cdepend/common)만 둔다. 판넬 단위 상실은 성립하지
않는 시나리오라 문항을 만들지 않는다 — 판넬은 위치·구성 조회 대상이다.

주의할 점이 하나 있다. scope/depend 의 정답을 여기서 계산하는 방식이
PanelIndex 와 논리적으로 같다면, 두 경로가 코드만 다를 뿐 같은 오해를
공유할 수 있다. 그래서 run_eval_panel.py 에 **변이 시험**을 붙였다.
규칙을 하나씩 꺼서 점수가 실제로 무너지는지 확인한다. 무너지지 않으면
그 문항은 아무것도 시험하지 않고 있던 것이다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from ingest.interlock import load_interlocks  # noqa: E402
from retrieval.panel_index import (  # noqa: E402
    load_instrument_rows, load_locations)

ABSENT_PANELS = ["CUB-Z", "RIO-09", "MCC-01", "LCP-777"]
ABSENT_TAGS = ["AIT-9999", "PIT-9001", "ZZT-1234"]
ABSENT_CARDS = ["CUB-Z/R0/S1", "CUB-A/R9/S99", "RIO-01/DP99/R0/S1"]


def card_id(panel, rack, slot, station=""):
    """
    PanelIndex.card_id 와 같은 규칙을 여기서 다시 쓴다.

    한쪽 구현을 불러다 쓰면 그 구현이 틀려도 만점이 나온다. 두 경로가
    독립이어야 시험이 성립한다. 표준 IO List 의 PN(DP)(스테이션)까지
    같은 규칙으로 반영한다.
    """
    st = str(station).strip() if station is not None else ""
    head = "%s/DP%s" % (panel, st) if st else panel
    return "%s/R%s/S%s" % (head,
                           rack if str(rack).strip() != "" else "0",
                           slot if str(slot).strip() != "" else "0")


def _cid(r):
    return card_id(r["PANEL"], r["RACK"], r["SLOT"], r.get("PN(DP)", ""))


def _affect(items, lost):
    """상실 태그 집합 → (영향 출력, 남는 보호 없음, 부분 의존)."""
    outs, full, partial = set(), set(), set()
    for it in items:
        cond = set()
        for c in it["conditions"]:
            cond.update(c["tags"])
        if not (cond & lost):
            continue
        outs.add(it["output_tag"])
        # '남는 보호 없음' = 조건 태그 전부를 잃었거나 AND 결합
        if cond and cond <= lost:
            full.add(it["il_no"])
        elif (it.get("logic") or "").upper() == "AND":
            full.add(it["il_no"])
        else:
            partial.add(it["il_no"])
    return outs, full, partial


def build(rows, locs, items):
    qs = []
    n = [0]

    def qid():
        n[0] += 1
        return "PN%02d" % n[0]

    by_panel = {}
    for r in rows:
        by_panel.setdefault(r["PANEL"], []).append(r)
    tag2panel = {r["TAG"]: r["PANEL"] for r in rows}

    # ── locate : 태그 → 판넬 ───────────────────────────────
    # 전건을 넣는다. 이 매핑이 나머지 전부의 전제이기 때문이다.
    tag2card = {r["TAG"]: _cid(r) for r in rows}
    for tag in sorted(tag2panel):
        qs.append({"id": qid(), "type": "locate", "tag": tag,
                   "expect_panel": tag2panel[tag],
                   "expect_card": tag2card[tag]})

    # ── place : 판넬 → 구역·그리드 ─────────────────────────
    for panel in sorted(by_panel):
        loc = locs.get(panel)
        if not loc:
            continue
        qs.append({"id": qid(), "type": "place", "panel": panel,
                   "expect_area": loc["area"], "expect_grid": loc["grid"],
                   "expect_indoor": loc["indoor"]})

    # ── roster : 판넬 → 계기 집합 ──────────────────────────
    for panel in sorted(by_panel):
        qs.append({"id": qid(), "type": "roster", "panel": panel,
                   "expect_points": len(by_panel[panel]),
                   "expect_tags": sorted(r["TAG"] for r in by_panel[panel]),
                   "expect_tbs": sorted({(r["TERMINAL"] or "-").split("-")[0]
                                         for r in by_panel[panel]
                                         if r["TERMINAL"]})})

    # ── card : 카드 구성 ───────────────────────────────────
    by_card = {}
    for r in rows:
        by_card.setdefault(_cid(r), []).append(r)

    for cid in sorted(by_card):
        qs.append({"id": qid(), "type": "card", "card": cid,
                   "expect_points": len(by_card[cid]),
                   "expect_tags": sorted(r["TAG"] for r in by_card[cid]),
                   "expect_panel": by_card[cid][0]["PANEL"]})

    # ── cscope / cdepend : 카드 상실 영향 (실제 단일 고장 단위) ──
    for cid in sorted(by_card):
        lost = {r["TAG"] for r in by_card[cid]}
        outs, full, partial = _affect(items, lost)
        qs.append({"id": qid(), "type": "cscope", "card": cid,
                   "expect_outputs": sorted(outs)})
        if outs:
            qs.append({"id": qid(), "type": "cdepend", "card": cid,
                       "expect_no_remaining": sorted(full),
                       "expect_partial": sorted(partial)})

    # ── common : 공통원인 (조건이 같은 카드에 몰려 있는가) ──
    tag2card_all = {r["TAG"]: _cid(r) for r in rows}
    expect_common = []
    for it in items:
        cond = set()
        for c in it["conditions"]:
            cond.update(c["tags"])
        known = {t: tag2card_all[t] for t in cond if t in tag2card_all}
        if len(known) < 2:
            continue
        seen = {}
        for t, k in known.items():
            seen.setdefault(k, []).append(t)
        if any(len(v) > 1 for v in seen.values()):
            expect_common.append(it["il_no"])
    qs.append({"id": qid(), "type": "common",
               "expect_findings": sorted(expect_common)})

    # ── absent ────────────────────────────────────────────
    for p in ABSENT_PANELS:
        if p in by_panel:
            continue
        qs.append({"id": qid(), "type": "absent", "panel": p})
    for t in ABSENT_TAGS:
        if t in tag2panel:
            continue
        qs.append({"id": qid(), "type": "absent", "tag": t})
    for cid in ABSENT_CARDS:
        if cid in by_card:
            continue
        qs.append({"id": qid(), "type": "absent", "card": cid})

    return qs


def main():
    ap = argparse.ArgumentParser(description="판넬 평가셋 생성")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--out", default=os.path.join(here, "eval_set_panel.json"))
    a = ap.parse_args()

    rows = load_instrument_rows()
    locs = load_locations()
    items = load_interlocks()
    if not locs:
        print("[경고] PANEL_LOCATIONS.csv 가 없습니다. "
              "tools/make_arrangement.py 를 먼저 실행하십시오.")
    qs = build(rows, locs, items)

    from collections import Counter
    cnt = Counter(q["type"] for q in qs)
    meta = {
        "source": {
            "instruments": os.path.basename(config.INSTRUMENTS),
            "locations": os.path.basename(config.PANEL_LOCATIONS),
            "interlock": os.path.basename(config.INTERLOCK_XLSX),
        },
        "counts": dict(cnt),
        "total": len(qs),
        "note": ("정답은 원천 레코드에서 직접 계산했으며 PanelIndex 출력을 "
                 "쓰지 않았다. 변이 시험은 run_eval_panel.py --mutate 참조."),
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "questions": qs}, f,
                  ensure_ascii=False, indent=1)
    print("문항 %d개 → %s" % (len(qs), a.out))
    for k, v in sorted(cnt.items()):
        print("  %-8s %d" % (k, v))


if __name__ == "__main__":
    main()
