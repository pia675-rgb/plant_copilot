#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_eval_panel.py — 판넬 조회 채점

    python -m eval.run_eval_panel --md eval/scorecard_panel.md
    python -m eval.run_eval_panel --mutate          변이 시험

채점 대상은 retrieval.panel_index.PanelIndex 다. 정답은 원천 레코드에서
직접 계산된 것이라 두 경로가 독립이다.

판넬 조회는 검색이 아니라 조회이므로 만점이 기본값이다. 점수가 낮으면
성능이 부족한 게 아니라 **로직이 틀린** 것이다.

── 변이 시험이 왜 붙어 있나 ──────────────────────────────────

만점짜리 평가는 그 자체로는 아무것도 증명하지 않는다. 채점이 실제로
무언가를 붙잡고 있는지 보려면 로직을 일부러 망가뜨렸을 때 점수가
무너져야 한다. --mutate 는 세 가지를 끈다.

    no-location    배치 CSV 를 비운다        → place 가 무너져야 한다
    no-logic       AND/OR 결합을 무시한다     → cdepend 가 무너져야 한다
    no-card-split  슬롯 구분을 없앤다         → card 계열이 무너져야 한다

무너지지 않는 항목이 있으면 그 문항은 아무것도 시험하지 않고 있다.
"""

import argparse
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from retrieval import panel_index as PI  # noqa: E402
from retrieval.panel_index import PanelIndex  # noqa: E402

EVAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "eval_set_panel.json")

TYPE_NOTE = {
    "locate": "태그가 어느 판넬·카드인지 계기 리스트대로인가",
    "card": "카드에 물린 채널 집합이 정확한가",
    "cscope": "카드 상실 시 영향받는 출력을 빠짐없이 세는가",
    "cdepend": "카드 상실 시 남는 보호가 없는 인터락을 가려내는가",
    "common": "한 인터락의 조건이 같은 카드에 몰려 있는지 찾아내는가",
    "place": "판넬 위치·그리드가 배치도와 일치하는가",
    "roster": "판넬에 물린 계기 집합이 정확한가",
    "absent": "없는 판넬·태그를 지어내지 않는가",
}


def check(ix, q):
    """(통과여부, 실제값, 실패사유)"""
    t = q["type"]

    if t == "locate":
        d = ix.by_tag(q["tag"])
        if not d:
            return False, "(조회 결과 없음)", "계기를 찾지 못함"
        got = "%s / %s" % (d["panel"], d.get("card"))
        if d["panel"] != q["expect_panel"]:
            return False, got, "판넬 불일치 (기대 %s)" % q["expect_panel"]
        if "expect_card" in q and d.get("card") != q["expect_card"]:
            return False, got, "카드 불일치 (기대 %s)" % q["expect_card"]
        return True, got, ""

    if t == "place":
        d = ix.by_panel(q["panel"])
        loc = (d or {}).get("location")
        if not loc:
            return False, "(위치 없음)", "배치 정보를 찾지 못함"
        got = "%s / %s / %s" % (loc["area"], loc["grid"],
                                "실내" if loc["indoor"] else "옥외")
        ok = (loc["area"] == q["expect_area"]
              and loc["grid"] == q["expect_grid"]
              and loc["indoor"] == q["expect_indoor"])
        return ok, got, "" if ok else "기대 %s / %s" % (q["expect_area"],
                                                       q["expect_grid"])

    if t == "roster":
        d = ix.by_panel(q["panel"])
        if not d:
            return False, "(조회 결과 없음)", "판넬을 찾지 못함"
        got = "%d점" % d["points"]
        if d["points"] != q["expect_points"]:
            return False, got, "점수 불일치 (기대 %d)" % q["expect_points"]
        if d["tags"] != q["expect_tags"]:
            miss = set(q["expect_tags"]) - set(d["tags"])
            extra = set(d["tags"]) - set(q["expect_tags"])
            return False, got, "태그 불일치 (누락 %s / 초과 %s)" % (
                ",".join(sorted(miss)) or "-", ",".join(sorted(extra)) or "-")
        # 단자가 없는 점(출력 등)은 "-" 로 묶인다. 있는 것만 대조한다 —
        # 단자 정보는 TB List 에서 오고, 없는 것이 정상인 점이 있다.
        got_tb = sorted(k for k in d["by_terminal"] if k and k != "-")
        want_tb = sorted(q.get("expect_tbs") or [])
        if got_tb != want_tb:
            return False, got, ("단자대 집계 불일치 (기대 %s / 실제 %s)"
                                % (",".join(want_tb) or "없음",
                                   ",".join(got_tb) or "없음"))
        return True, got, ""

    if t == "card":
        d = ix.by_card(q["card"])
        if not d:
            return False, "(조회 결과 없음)", "카드를 찾지 못함"
        got = "%d점 / %s" % (d["points"], d["panel"])
        if d["points"] != q["expect_points"]:
            return False, got, "점수 불일치 (기대 %d)" % q["expect_points"]
        if d["tags"] != q["expect_tags"]:
            return False, got, "태그 불일치"
        if d["panel"] != q["expect_panel"]:
            return False, got, "판넬 불일치 (기대 %s)" % q["expect_panel"]
        return True, got, ""

    if t in ("cscope", "cdepend"):
        d = ix.impact(q["card"])
        if not d:
            return False, "(조회 결과 없음)", "카드를 찾지 못함"
        if not d["interlock_loaded"]:
            return False, "(인터락 미적재)", "인터락 리스트를 읽지 못함"
        if t == "cscope":
            got = sorted(o["tag"] for o in d["affected_outputs"])
            ok = got == q["expect_outputs"]
            return ok, ",".join(got) or "-", "" if ok else "기대 %s" % (
                ",".join(q["expect_outputs"]) or "-")
        got_none, got_part = [], []
        for r in d["dependencies"]:
            (got_none if r["remaining_protection"].startswith("없음")
             else got_part).append(r["il_no"])
        got_none, got_part = sorted(got_none), sorted(got_part)
        got = "보호없음=%s" % (",".join(got_none) or "-")
        if got_none != q["expect_no_remaining"]:
            return False, got, "보호 상실 판정 불일치 (기대 %s)" % (
                ",".join(q["expect_no_remaining"]) or "-")
        if got_part != q["expect_partial"]:
            return False, got, "부분 의존 판정 불일치"
        return True, got, ""

    if t == "common":
        d = ix.common_cause()
        if not d["loaded"]:
            return False, "(인터락 미적재)", "인터락 리스트를 읽지 못함"
        got = sorted(f["il_no"] for f in d["findings"])
        ok = got == q["expect_findings"]
        return ok, "지적 %d건 %s" % (len(got), ",".join(got) or ""), \
            "" if ok else "기대 %s" % (",".join(q["expect_findings"]) or "0건")

    if t == "absent":
        if q.get("card"):
            ok = (ix.by_card(q["card"]) is None
                  and ix.impact(q["card"]) is None)
            return ok, "없음" if ok else "결과 반환됨", \
                "" if ok else "없는 카드에 결과를 만들어냄"
        if q.get("panel"):
            got = ix.by_panel(q["panel"])
            imp = ix.impact(q["panel"])
            ok = got is None and imp is None
            return ok, "없음" if ok else "결과 반환됨", \
                "" if ok else "리스트에 없는 판넬에 결과를 만들어냄"
        ok = ix.by_tag(q["tag"]) is None
        return ok, "없음" if ok else "결과 반환됨", \
            "" if ok else "리스트에 없는 태그에 결과를 만들어냄"

    return False, "-", "알 수 없는 유형 %s" % t


def run(ix, qs):
    by_type, fails = OrderedDict(), []
    for q in qs:
        t = q["type"]
        by_type.setdefault(t, [0, 0])
        by_type[t][1] += 1
        ok, got, why = check(ix, q)
        if ok:
            by_type[t][0] += 1
        else:
            fails.append((q, got, why))
    return by_type, fails


# ── 변이 시험 ────────────────────────────────────────────────
def mutate(name, ix):
    """로직을 하나 꺼서 점수가 무너지는지 본다. 되돌릴 함수를 반환."""
    if name == "no-location":
        saved = ix.locations
        ix.locations = {}
        return lambda: setattr(ix, "locations", saved)
    if name == "no-logic":
        saved = [it.get("logic") for it in ix._interlock().items]
        for it in ix._interlock().items:
            it["logic"] = "OR"          # AND 결합을 무시
        def undo():
            for it, v in zip(ix._interlock().items, saved):
                it["logic"] = v
        return undo
    if name == "no-card-split":
        # 모든 태그를 한 카드로 몰아 카드 구분을 없앤다
        for r in ix.rows:
            r["RACK"], r["SLOT"] = "0", "0"
        saved = ix._by_card
        from collections import defaultdict as _dd
        ix._by_card = _dd(list)
        for r in ix.rows:
            ix._by_card[ix.card_id(r["PANEL"], r["RACK"], r["SLOT"])].append(r)
        return lambda: setattr(ix, "_by_card", saved)
    raise SystemExit("알 수 없는 변이: %s" % name)


def main():
    ap = argparse.ArgumentParser(description="판넬 조회 채점")
    ap.add_argument("--eval", default=EVAL_PATH)
    ap.add_argument("--md", default=None, help="스코어카드 출력 경로")
    ap.add_argument("--mutate", action="store_true", help="변이 시험 실행")
    a = ap.parse_args()

    with open(a.eval, encoding="utf-8") as f:
        data = json.load(f)
    qs = data["questions"]

    ix = PanelIndex()
    by_type, fails = run(ix, qs)
    total = sum(v[1] for v in by_type.values())
    passed = sum(v[0] for v in by_type.values())

    print("전체 %d/%d" % (passed, total))
    for t, (p, n) in by_type.items():
        print("  %-8s %d/%d" % (t, p, n))

    mut_rows = []
    if a.mutate:
        print("\n변이 시험")
        for name in ("no-location", "no-logic", "no-card-split"):
            # 캐시를 지우고 새 인덱스로 시험
            ix2 = PanelIndex()
            ix2._interlock()
            undo = mutate(name, ix2)
            bt, _ = run(ix2, qs)
            undo()
            row = {t: bt[t][0] for t in bt}
            mut_rows.append((name, sum(row.values()), row))
            print("  %-13s 전체 %d/%d   %s" % (
                name, sum(row.values()), total,
                " ".join("%s %d/%d" % (t, bt[t][0], bt[t][1]) for t in bt)))

    if a.md:
        write_md(a.md, data, by_type, fails, passed, total, mut_rows)
        print("\n스코어카드 →", a.md)

    return 0 if passed == total else 1


def write_md(path, data, by_type, fails, passed, total, mut_rows):
    meta = data.get("meta", {})
    L = ["# 판넬 조회 스코어카드", "",
         "계기 %s · 배치 %s · 인터락 %s 에서 자동 생성한 %d문항입니다."
         % (meta.get("source", {}).get("instruments", "-"),
            meta.get("source", {}).get("locations", "-"),
            meta.get("source", {}).get("interlock", "-"), total), "",
         "> 정답은 원천 레코드에서 직접 계산했으며 PanelIndex 의 출력을 쓰지 "
         "않았다. 판넬 조회는 검색이 아니라 조회이므로 만점이 기본값이며, "
         "이 평가의 목적은 성능 측정이 아니라 회귀 방지다.", "",
         "## 유형별", "",
         "| 유형 | 문항 | 통과 | 무엇을 보는가 |", "|---|---|---|---|"]
    for t, (p, n) in by_type.items():
        L.append("| %s | %d | %d/%d | %s |" % (t, n, p, n, TYPE_NOTE.get(t, "")))
    L.append("| **전체** | **%d** | **%d/%d** | |" % (total, passed, total))
    L.append("")

    L.append("## 실패 문항 (%d건)" % len(fails))
    L.append("")
    if not fails:
        L.append("없음.")
    else:
        L.append("| 문항 | 유형 | 대상 | 실제 | 사유 |")
        L.append("|---|---|---|---|---|")
        for q, got, why in fails:
            L.append("| %s | %s | %s | %s | %s |"
                     % (q["id"], q["type"],
                        q.get("tag") or q.get("panel") or "-", got, why))
    L.append("")

    if mut_rows:
        L += ["## 변이 시험", "",
              "만점은 그 자체로 아무것도 증명하지 않는다. 로직을 하나씩 "
              "껐을 때 점수가 실제로 무너지는지 확인한 결과다.", "",
              "| 변이 | 무엇을 껐나 | 전체 |", "|---|---|---|"]
        what = {"no-location": "배치 CSV 를 비움",
                "no-logic": "AND/OR 결합을 무시",
                "no-card-split": "슬롯 구분을 없애 카드를 하나로"}
        for name, s, _ in mut_rows:
            L.append("| %s | %s | %d/%d |" % (name, what.get(name, ""), s, total))
        L.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
