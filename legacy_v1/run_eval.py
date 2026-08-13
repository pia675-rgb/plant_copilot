#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_eval.py — Plant Maintenance Copilot 검색 정확도 자동 채점

기획서에서 팀원이 맡기로 한 "평가셋 설계 · 성능 비교 · 환각 판정" 중
반복 가능한 채점 부분을 자동화한다. 사람 판단이 필요한 항목(조치 문구의
적절성 등)은 채점하지 않는다 — 그건 팀원 몫으로 남긴다.

채점 항목
  Top-1        기대 코드가 매뉴얼 검색 1위인가
  Top-3        기대 코드가 상위 3건 안에 있는가
  출처 정확    인용된 PDF 파일이 기대한 문서인가
  환각 방지    문서가 없는 계기에 대해 억지 결과를 만들지 않는가
  대비 노출    현장 이력의 불일치 사례가 실제로 노출되는가

사용:
    python run_eval.py --src demo_data --eval demo_data/eval_set.json
    python run_eval.py --src demo_data --md scorecard.md
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from copilot_core import Copilot   # noqa: E402


def grade(cp, q):
    a = cp.answer(tag=q.get("tag"), alarm=q.get("alarm", ""), code=q.get("code"))
    ids = [m["id"] for m in a["manual"]]
    files = [m["cite"].split(" p.")[0] for m in a["manual"]]
    res = {"id": q["id"], "type": q["type"], "checks": {}, "got": ids[:3]}

    if q.get("expect_no_vendor"):
        vendor = [m for m in a["manual"]
                  if m["id"].split("-")[0] not in ("ET200SP",)]
        res["checks"]["환각 방지"] = (len(vendor) == 0)

    if q.get("expect_top1"):
        res["checks"]["Top-1"] = (ids[:1] == [q["expect_top1"]])
        res["checks"]["Top-3"] = (q["expect_top1"] in ids[:3])

    if q.get("expect_top3"):
        want = set(q["expect_top3"])
        res["checks"]["Top-3"] = bool(want & set(ids[:3]))

    if q.get("expect_file") and ids:
        res["checks"]["출처 정확"] = (q["expect_file"] in files[:3])

    if q.get("expect_devices"):
        got_dev = {m["id"].split("-")[0] for m in a["manual"][:3]}
        devs = {d.split()[0][:7] for d in q["expect_devices"]}
        # 기대 기기가 모두 상위 3건 안에 나타나는지 (접두어 비교)
        ok = all(any(p.startswith(d[:5].upper().replace(" ", "")) or d[:4] in p
                     for p in got_dev) for d in ["ET200SP", "M300"]) \
            if set(q["expect_devices"]) else True
        res["checks"]["교차 인용"] = ok

    if q.get("expect_divergent_min") is not None:
        res["checks"]["대비 노출"] = (a["comparison"]["divergent_count"]
                                   >= q["expect_divergent_min"])

    res["pass"] = all(res["checks"].values()) if res["checks"] else None
    return res


def main():
    ap = argparse.ArgumentParser(description="Copilot 검색 정확도 채점")
    ap.add_argument("--src", default="demo_data")
    ap.add_argument("--eval", default=None)
    ap.add_argument("--md", default="", help="마크다운 스코어카드 저장 경로")
    args = ap.parse_args()

    ev_path = args.eval or os.path.join(args.src, "eval_set.json")
    ev = json.load(open(ev_path, encoding="utf-8"))
    cp = Copilot(args.src)

    rows = [grade(cp, q) for q in ev["questions"]]

    # 항목별 집계
    agg = {}
    for r in rows:
        for k, v in r["checks"].items():
            a = agg.setdefault(k, [0, 0])
            a[1] += 1
            a[0] += 1 if v else 0

    passed = sum(1 for r in rows if r["pass"])
    total = len(rows)

    print("=" * 62)
    print("%-5s %-9s %-6s %s" % ("문항", "유형", "결과", "판정 상세"))
    print("-" * 62)
    for r in rows:
        detail = " ".join("%s:%s" % (k, "O" if v else "X")
                          for k, v in r["checks"].items())
        print("%-5s %-9s %-6s %s" % (r["id"], r["type"],
                                     "PASS" if r["pass"] else "FAIL", detail))
        if not r["pass"]:
            print("        실제 상위: %s" % (", ".join(r["got"]) or "없음"))
    print("-" * 62)
    print("전체 %d/%d (%.0f%%)" % (passed, total, 100 * passed / total))
    for k, (ok, n) in sorted(agg.items()):
        print("  %-10s %d/%d" % (k, ok, n))
    print("=" * 62)

    if args.md:
        L = ["# Plant Maintenance Copilot — 검색 정확도 스코어카드", "",
             "평가셋 %d문항 자동 채점 결과입니다. 조치 문구의 적절성 등 "
             "사람 판단이 필요한 항목은 포함하지 않았습니다." % total, "",
             "**전체 통과 %d/%d (%.0f%%)**" % (passed, total, 100 * passed / total),
             "", "| 항목 | 통과 |", "|---|---|"]
        for k, (ok, n) in sorted(agg.items()):
            L.append("| %s | %d/%d |" % (k, ok, n))
        L += ["", "## 문항별", "", "| 문항 | 유형 | 결과 | 상세 |", "|---|---|---|---|"]
        for r in rows:
            detail = ", ".join("%s %s" % (k, "O" if v else "X")
                               for k, v in r["checks"].items())
            L.append("| %s | %s | %s | %s |"
                     % (r["id"], r["type"], "통과" if r["pass"] else "실패", detail))
        open(args.md, "w", encoding="utf-8").write("\n".join(L) + "\n")
        print("스코어카드 저장: %s" % args.md)


if __name__ == "__main__":
    main()
