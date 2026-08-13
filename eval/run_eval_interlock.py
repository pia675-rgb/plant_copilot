#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_eval_interlock.py — 인터락 조회 채점

    python -m eval.run_eval_interlock --md eval/scorecard_interlock.md

채점 대상은 조회 엔진(retrieval.interlock_index.InterlockIndex)이다.
정답은 원천 레코드에서 직접 계산된 것이라 두 경로가 독립이다.

인터락 조회는 검색이 아니라 조회이므로 만점이 기본값이다. 점수가
낮으면 "성능이 부족한" 것이 아니라 **로직이 틀린** 것이다. 그래서
실패 문항은 요약이 아니라 전건을 표로 남긴다.
"""

import argparse
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from retrieval.interlock_index import InterlockIndex  # noqa: E402

EVAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "eval_set_interlock.json")


def _ils(items):
    return sorted(it["il_no"] for it in items)


def check(ix, q):
    """(통과여부, 실제값 문자열, 실패 사유) 를 돌려준다."""
    t = q["type"]

    if t == "layer":
        res = ix.by_output(q["tag"], q["action"])
        if res is None:
            return False, "(조회 결과 없음)", "출력 태그를 찾지 못함"
        got_b, got_e = _ils(res["blocking"]), _ils(res["enabling"])
        ok_b = got_b == q["expect_blocking"]
        ok_e = got_e == q["expect_enabling"]
        # 층이 섞이지 않았는지도 함께 본다 — 이 평가의 핵심
        mixed = [it["il_no"] for it in res["blocking"]
                 if it["kind"] != "INTERLOCK"]
        got = "막음=%s 허가=%s" % (",".join(got_b) or "-", ",".join(got_e) or "-")
        if mixed:
            return False, got, "막음 층에 %s 가 섞임" % ",".join(mixed)
        if not ok_b:
            return False, got, "막음 층 불일치 (기대 %s)" % ",".join(q["expect_blocking"])
        if not ok_e:
            return False, got, "허가 층 불일치 (기대 %s)" % ",".join(q["expect_enabling"])
        return True, got, ""

    if t == "reverse":
        res = ix.by_input(q["tag"])
        if res is None:
            return False, "(조회 결과 없음)", "입력 태그를 찾지 못함"
        got = sorted(res["affected_outputs"])
        if got != q["expect_outputs"]:
            return False, ",".join(got), "영향 출력 불일치 (기대 %s)" % ",".join(q["expect_outputs"])
        return True, ",".join(got), ""

    if t == "absent":
        a = ix.by_output(q["tag"])
        b = ix.by_input(q["tag"])
        if a is None and b is None:
            return True, "없음", ""
        return False, "출력=%s 입력=%s" % (a is not None, b is not None), \
            "리스트에 없는 태그인데 결과를 반환함"

    if t == "value":
        res = ix.by_output(q["tag"])
        if res is None:
            return False, "(조회 결과 없음)", "출력 태그를 찾지 못함"
        it = next((x for x in res["all"] if x["il_no"] == q["il_no"]), None)
        if it is None:
            return False, "(항목 없음)", "%s 를 찾지 못함" % q["il_no"]
        c = next((x for x in it["conditions"] if x["raw"] == q["cond_raw"]), None)
        if c is None:
            return False, "(조건 없음)", "원문 조건이 보존되지 않음"
        exp = q["expect"]
        bad = [k for k, v in exp.items() if c.get(k) != v]
        got = " ".join("%s=%s" % (k, c.get(k)) for k in exp)
        if bad:
            return False, got, "불일치: %s" % ",".join(bad)
        return True, got, ""

    if t == "unparsed":
        res = ix.by_output(q["tag"])
        if res is None:
            return False, "(조회 결과 없음)", "출력 태그를 찾지 못함"
        it = next((x for x in res["all"] if x["il_no"] == q["il_no"]), None)
        if it is None:
            return False, "(항목 없음)", "%s 를 찾지 못함" % q["il_no"]
        c = next((x for x in it["conditions"]
                  if x["raw"] == q["expect_raw"]), None)
        if c is None:
            return False, "(원문 없음)", "미파싱 조건의 원문이 사라짐"
        if c.get("parsed"):
            return False, c["raw"], "미파싱인데 파싱됨으로 표시됨"
        return True, c["raw"][:40], ""

    if t == "attr":
        res = ix.by_output(q["tag"])
        if res is None:
            return False, "(조회 결과 없음)", "출력 태그를 찾지 못함"
        it = next((x for x in res["all"] if x["il_no"] == q["il_no"]), None)
        if it is None:
            return False, "(항목 없음)", "%s 를 찾지 못함" % q["il_no"]
        exp = q["expect"]
        bad = [k for k, v in exp.items() if it.get(k) != v]
        got = " ".join("%s=%s" % (k, it.get(k)) for k in exp)
        if bad:
            return False, got, "불일치: %s" % ",".join(bad)
        return True, got, ""

    return False, "-", "알 수 없는 문항 유형: %s" % t


def main():
    ap = argparse.ArgumentParser(description="인터락 조회 채점")
    ap.add_argument("--eval", default=EVAL_PATH)
    ap.add_argument("--md", default="")
    args = ap.parse_args()

    if not os.path.isfile(args.eval):
        print("평가셋이 없습니다. 먼저 생성하십시오:")
        print("  python -m eval.make_eval_interlock")
        return 1

    ev = json.load(open(args.eval, encoding="utf-8"))
    qs = ev["questions"]
    ix = InterlockIndex()

    rows = []
    for q in qs:
        try:
            ok, got, why = check(ix, q)
        except Exception as e:                              # noqa: BLE001
            ok, got, why = False, "(예외)", "%s: %s" % (type(e).__name__, e)
        rows.append({"q": q, "ok": ok, "got": got, "why": why})
        print("O" if ok else "X", end="", flush=True)
    print()

    by_type = OrderedDict()
    for r in rows:
        a = by_type.setdefault(r["q"]["type"], [0, 0])
        a[1] += 1
        a[0] += 1 if r["ok"] else 0
    total_ok = sum(1 for r in rows if r["ok"])

    print("\n" + "=" * 46)
    print("%-11s %-6s %s" % ("유형", "문항", "통과"))
    print("-" * 46)
    for t, (ok, tot) in by_type.items():
        print("%-11s %-6d %d/%d" % (t, tot, ok, tot))
    print("-" * 46)
    print("%-11s %-6d %d/%d" % ("전체", len(qs), total_ok, len(qs)))
    print("=" * 46)

    fails = [r for r in rows if not r["ok"]]
    if fails:
        print("\n실패 %d건:" % len(fails))
        for r in fails:
            print("  %s %-9s %-10s %s" % (r["q"]["id"], r["q"]["type"],
                                          r["q"].get("tag", ""), r["why"]))
    else:
        print("\n전건 통과. 층 분리·역방향 조회·부재 판정·원문 보존 모두 정상입니다.")

    if args.md:
        write_md(args.md, ev, rows, by_type, total_ok)
        print("스코어카드 저장: %s" % args.md)
    return 0


def write_md(path, ev, rows, by_type, total_ok):
    m = ev["meta"]
    L = ["# 인터락 조회 스코어카드", "",
         "원천 인터락 %d건에서 자동 생성한 %d문항입니다."
         % (m["interlock_rows"], len(rows)), "",
         "> %s" % m["fairness_note"], "",
         "## 유형별", "",
         "| 유형 | 문항 | 통과 | 무엇을 보는가 |",
         "|---|---|---|---|"]
    desc = {
        "layer": "동작을 막는 조건과 허가하는 조건이 섞이지 않는가",
        "reverse": "입력 태그가 어느 출력에 영향을 주는가",
        "absent": "리스트에 없는 태그를 지어내지 않는가",
        "value": "설정치·단위·지연이 원문과 일치하는가",
        "unparsed": "못 읽은 조건의 원문이 보존되는가",
        "attr": "바이패스 가부·리셋 방식이 정확한가",
    }
    for t, (ok, tot) in by_type.items():
        L.append("| %s | %d | %d/%d | %s |" % (t, tot, ok, tot, desc.get(t, "")))
    L.append("| **전체** | **%d** | **%d/%d** | |"
             % (len(rows), total_ok, len(rows)))

    fails = [r for r in rows if not r["ok"]]
    L += ["", "## 실패 문항 (%d건)" % len(fails), ""]
    if fails:
        L += ["| 문항 | 유형 | 태그 | 사유 | 실제 |", "|---|---|---|---|---|"]
        for r in fails:
            L.append("| %s | %s | %s | %s | %s |" % (
                r["q"]["id"], r["q"]["type"], r["q"].get("tag", ""),
                r["why"], str(r["got"])[:44]))
    else:
        L.append("없음.")

    L += ["", "## 읽는 법", "",
          "인터락 조회는 검색이 아니라 조회입니다. 정답이 리스트에 확정적으로",
          "존재하므로 **만점이 기본값**이며, 점수가 낮다는 것은 성능이 부족한",
          "것이 아니라 로직이 틀렸다는 뜻입니다. 이 평가의 값어치는 높은 점수",
          "자체가 아니라, 실물 인터락 리스트로 교체할 때 컬럼 구조 변화로",
          "무엇이 깨지는지를 즉시 알려주는 회귀 방지에 있습니다.", "",
          "출처: `%s`" % m["source"], ""]
    open(path, "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
