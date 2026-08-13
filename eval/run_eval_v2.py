#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_eval_v2.py — v1 / v2 A/B 채점

같은 평가셋(eval_set_v2.json)을 여러 시스템에 돌려 나란히 세운다.

    v1        원본 copilot_core (KO_EN 사전, 코드표 306건만 색인)
    lexical   v2 BM25 단독 (사전 없음, 코드표 + 본문 1,826건)
    hybrid    v2 BM25 + dense + RRF
    full      v2 위 + cross-encoder 재정렬

채점 항목
    Top-1        기대 근거가 1위인가
    Top-3        기대 근거가 상위 3건 안에 있는가
    출처 정확    인용된 파일이 기대한 문서인가
    본문 적중    기대 섹션의 본문 청크가 상위 3건에 있는가 (body 유형)
    오귀속 방지  다른 기종의 근거를 올리지 않는가 (wrongdev)
    환각 방지    문서 없는 계기에 벤더 근거를 만들지 않는가
    거절         근거 없는 질의를 거절하는가 (v2 CRAG 만 해당)

기본값이 네 구성 전부인 이유:
    이전 기본값은 v1,lexical 이었다. 그대로 돌리면 v2 의 논지(다국어
    임베딩이 사전을 대체한다)를 증명할 열이 아예 없는 스코어카드가 나온다.
    BM25 단독으로 한글 질의를 영문 매뉴얼에 붙이는 것은 구조적으로
    불가능하므로, lexical 열만 있는 표는 v2 를 v1 보다 못한 것으로 보이게 한다.

    또한 각 시스템은 strict 로 구성한다. Ollama 가 안 떠 있으면 조용히
    렉시컬로 내려간 결과가 "hybrid" 라는 이름으로 표에 실리는 것을 막는다.
    구성에 실패한 열은 사유와 함께 '미실행'으로 남긴다 — 빈칸이 거짓 숫자보다 낫다.

사용:
    python -m eval.run_eval_v2                       # 네 구성 전부
    python -m eval.run_eval_v2 --systems v1,lexical  # 일부만
    python -m eval.run_eval_v2 --md eval/scorecard_v2.md --dump-grades
"""

import argparse
import json
import os
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

EVAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "eval_set_v2.json")

DEFAULT_SYSTEMS = "v1,lexical,hybrid,full"


# ── 시스템 어댑터 ────────────────────────────────────────────
# 어느 시스템이든 아래 형태의 리스트를 돌려주도록 감싼다.
#   [{"id","kind","device","file","section"}]
class V1System:
    name = "v1"
    note = "원본 copilot_core — KO_EN 사전, 코드표만 색인"

    def __init__(self, strict=True):
        # v1 비교 대상 코드는 legacy_v1/ 에 보존해 두었다.
        sys.path.insert(0, os.path.join(config.ROOT, "legacy_v1"))
        from copilot_core import Copilot
        self.cp = Copilot(config.SOURCE_DIR)

    def label(self):
        return "v1"

    def query(self, q):
        a = self.cp.answer(tag=q.get("tag"), alarm=q.get("alarm", ""),
                           code=q.get("code"))
        out = []
        for m in a["manual"]:
            f = m["cite"].split(" p.")[0]
            out.append({"id": m["id"], "kind": "error_code",
                        "device": _dev_of(m["id"]), "file": f, "section": ""})
        return {"hits": out, "decision": None, "grade": None,
                "grade_parts": None}


class V2System:
    def __init__(self, mode, strict=True):
        from graph.app_graph import Copilot2
        self.name = mode
        self.note = "v2 %s — 사전 없음, 코드표 + 본문 색인" % mode
        self.cp = Copilot2(mode=mode, strict=strict)

    def label(self):
        return self.cp.label

    def query(self, q):
        out = self.cp.answer(tag=q.get("tag"), alarm=q.get("alarm", ""),
                             code=q.get("code", ""))
        hits = []
        for e in out.get("evidence", []):
            cite = e["cite"]
            f = cite.split(" p.")[0]
            sec = cite.split("(", 1)[1].rstrip(")") if "(" in cite else ""
            hits.append({"id": e["id"], "kind": e["kind"],
                         "device": e.get("device") or _dev_of(e["id"]),
                         "file": f, "section": sec})
        return {"hits": hits, "decision": out.get("decision"),
                "grade": out.get("grade"),
                "grade_parts": out.get("grade_parts")}


def build_system(name, strict=True):
    """구성에 실패하면 (None, 사유) 를 돌려준다. 예외로 전체를 죽이지 않는다."""
    try:
        s = V1System(strict) if name == "v1" else V2System(name, strict)
        return s, None
    except Exception as e:                                  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


def _dev_of(rid):
    u = rid.upper()
    if u.startswith("M9E"):
        return "M9e"
    if u.startswith("M300"):
        return "M300"
    if u.startswith("ET200SP") or "16XI" in u:
        return "CARD"
    return rid.split("#")[0]


# ── 채점 ────────────────────────────────────────────────────
def grade(q, res):
    hits = res["hits"]
    ids = [h["id"] for h in hits]
    checks = OrderedDict()

    if q.get("expect_top1"):
        checks["Top-1"] = ids[:1] == [q["expect_top1"]]
        checks["Top-3"] = q["expect_top1"] in ids[:3]

    if q.get("expect_top3"):
        checks["Top-3"] = bool(set(q["expect_top3"]) & set(ids[:3]))

    if q.get("expect_section_any"):
        want = [s.lower() for s in q["expect_section_any"]]
        ok = any(h["kind"] == "manual_text"
                 and any(w in (h["section"] or "").lower() for w in want)
                 for h in hits[:3])
        checks["본문 적중"] = ok

    if q.get("expect_file") and ids:
        checks["출처 정확"] = q["expect_file"] in [h["file"] for h in hits[:3]]

    if q.get("expect_no_device"):
        bad = {d for d in q["expect_no_device"]}
        checks["오귀속 방지"] = not any(h["device"] in bad for h in hits[:3])

    if q.get("expect_no_vendor"):
        checks["환각 방지"] = not any(h["device"] in ("M9e", "M300")
                                   for h in hits)

    if not q.get("expect_abstain") and q.get("type") != "abstain":
        # 정상 문항을 거절해 버리는 과잉 거절도 실패로 본다.
        # 거절 기능이 없는 v1 은 해당 없음.
        checks["과잉거절 없음"] = (res["decision"] != "abstain") \
            if res["decision"] is not None else None

    if q.get("expect_abstain") or q.get("type") == "abstain":
        # v1 은 거절 기능이 없다 — 해당 없음으로 두고 별도 표기
        checks["거절"] = (res["decision"] == "abstain") \
            if res["decision"] is not None else None

    vals = [v for v in checks.values() if v is not None]
    return checks, (all(vals) if vals else None), ids[:3]


def run(system, questions, verbose=True):
    rows = []
    for q in questions:
        try:
            res = system.query(q)
        except Exception as e:                              # noqa: BLE001
            res = {"hits": [], "decision": None, "grade": None,
                   "grade_parts": None}
            print("  %s %s 실행 오류: %s" % (system.name, q["id"], e))
        checks, ok, got = grade(q, res)
        rows.append({"id": q["id"], "type": q["type"], "checks": checks,
                     "pass": ok, "got": got, "decision": res.get("decision"),
                     "grade": res.get("grade"),
                     "grade_parts": res.get("grade_parts")})
        if verbose:
            print("-" if ok is None else ("O" if ok else "X"), end="", flush=True)
    if verbose:
        print()
    return rows


def summarize(rows):
    by_type, agg = OrderedDict(), OrderedDict()
    for r in rows:
        t = by_type.setdefault(r["type"], [0, 0])
        if r["pass"] is not None:
            t[1] += 1
            t[0] += 1 if r["pass"] else 0
        for k, v in r["checks"].items():
            if v is None:
                continue
            a = agg.setdefault(k, [0, 0])
            a[1] += 1
            a[0] += 1 if v else 0
    scored = [r for r in rows if r["pass"] is not None]
    return by_type, agg, sum(1 for r in scored if r["pass"]), len(scored)


def failure_rows(rows, questions):
    """실패 문항만 추린다 — 발표 준비 때 볼 것은 이쪽이다."""
    qmap = {q["id"]: q for q in questions}
    out = []
    for r in rows:
        if r["pass"] is False:
            q = qmap[r["id"]]
            failed = [k for k, v in r["checks"].items() if v is False]
            out.append({
                "id": r["id"], "type": r["type"],
                "query": q.get("alarm") or q.get("code") or "",
                "expected": q.get("expect_top1")
                or ", ".join(q.get("expect_top3", []))
                or ", ".join(q.get("expect_section_any", [])) or "-",
                "got": ", ".join(r["got"]) or "(없음)",
                "failed": ", ".join(failed) or "-",
                "decision": r.get("decision") or "-",
                "grade": r.get("grade"),
            })
    return out


def main():
    ap = argparse.ArgumentParser(description="v1/v2 A/B 채점")
    ap.add_argument("--systems", default=DEFAULT_SYSTEMS,
                    help="기본: %s" % DEFAULT_SYSTEMS)
    ap.add_argument("--eval", default=EVAL_PATH)
    ap.add_argument("--md", default="")
    ap.add_argument("--dump-grades", action="store_true",
                    help="문항별 충분성 점수 내역을 JSON 으로 저장 (임계값 교정용)")
    ap.add_argument("--no-strict", action="store_true",
                    help="구성 실패해도 강등된 채로 진행 (권장하지 않음)")
    args = ap.parse_args()

    ev = json.load(open(args.eval, encoding="utf-8"))
    qs = ev["questions"]

    results, labels, skipped = OrderedDict(), OrderedDict(), OrderedDict()
    for name in [x.strip() for x in args.systems.split(",") if x.strip()]:
        print("· %s 구성" % name)
        s, err = build_system(name, strict=not args.no_strict)
        if s is None:
            skipped[name] = err
            print("  건너뜀 — %s" % err)
            continue
        labels[name] = s.label()
        if labels[name] != name:
            print("  ※ 실제 구성: %s" % labels[name])
        print("· %s 채점 (%d문항)" % (name, len(qs)))
        results[name] = run(s, qs)

    if not results:
        print("\n실행된 시스템이 없습니다. eval/preflight.py 로 환경을 먼저 점검하십시오.")
        return 1

    # 유형별 비교표
    types = list(OrderedDict((q["type"], None) for q in qs))
    summ = {n: summarize(results[n]) for n in results}
    width = 18 + 13 * len(results)
    print("\n" + "=" * width)
    print("%-12s %-5s %s" % ("유형", "문항",
                             " ".join("%-12s" % n for n in results)))
    print("-" * width)
    for t in types:
        n_q = sum(1 for q in qs if q["type"] == t)
        cells = []
        for n in results:
            ok, tot = summ[n][0].get(t, [0, 0])
            cells.append("%-12s" % ("%d/%d" % (ok, tot) if tot else "-"))
        print("%-12s %-5d %s" % (t, n_q, " ".join(cells)))
    print("-" * width)
    print("%-12s %-5d %s" % ("전체", len(qs),
                             " ".join("%-12s" % ("%d/%d" % (summ[n][2], summ[n][3]))
                                      for n in results)))
    print("=" * width)

    # 항목별
    keys = list(OrderedDict((k, None) for n in results for k in summ[n][1]))
    print("\n%-14s %s" % ("채점 항목",
                          " ".join("%-12s" % n for n in results)))
    print("-" * (16 + 13 * len(results)))
    for k in keys:
        print("%-14s %s" % (k, " ".join(
            "%-12s" % ("%d/%d" % tuple(summ[n][1][k]) if k in summ[n][1] else "-")
            for n in results)))

    if skipped:
        print("\n미실행:")
        for n, err in skipped.items():
            print("  · %s — %s" % (n, err))

    print("\n조건: %s" % config.describe())

    if args.dump_grades:
        path = os.path.join(os.path.dirname(args.eval), "grades_dump.json")
        dump = {n: [{"id": r["id"], "type": r["type"],
                     "grade": r["grade"], "decision": r["decision"],
                     "parts": r["grade_parts"]} for r in results[n]]
                for n in results}
        json.dump(dump, open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("충분성 점수 내역: %s" % path)

    if args.md:
        write_md(args.md, ev, qs, results, labels, skipped, summ, types, keys)
        print("스코어카드 저장: %s" % args.md)
    return 0


def write_md(path, ev, qs, results, labels, skipped, summ, types, keys):
    hdr = [labels.get(n, n) for n in results]
    L = ["# Plant Maintenance Copilot — 검색 정확도 스코어카드 v2", "",
         "평가셋 %d문항. 같은 문항을 v1 과 v2 각 구성에 돌린 결과입니다." % len(qs),
         "", "> %s" % ev["meta"]["fairness_note"], ""]

    if skipped:
        L += ["> **미실행 구성이 있습니다.** 아래 열은 이 표에 없습니다 — "
              "강등된 결과를 원래 이름으로 싣지 않기 위해 비워 둡니다.", ""]
        for n, err in skipped.items():
            L.append("> - `%s` — %s" % (n, err))
        L.append("")

    L += ["## 유형별", "",
          "| 유형 | 문항 | " + " | ".join(hdr) + " |",
          "|---|---|" + "---|" * len(results)]
    for t in types:
        n_q = sum(1 for q in qs if q["type"] == t)
        cells = []
        for n in results:
            ok, tot = summ[n][0].get(t, [0, 0])
            cells.append("%d/%d" % (ok, tot) if tot else "-")
        L.append("| %s | %d | %s |" % (t, n_q, " | ".join(cells)))
    L.append("| **전체** | **%d** | %s |"
             % (len(qs), " | ".join("**%d/%d**" % (summ[n][2], summ[n][3])
                                    for n in results)))

    L += ["", "## 채점 항목별", "",
          "| 항목 | " + " | ".join(hdr) + " |",
          "|---|" + "---|" * len(results)]
    for k in keys:
        L.append("| %s | %s |" % (k, " | ".join(
            "%d/%d" % tuple(summ[n][1][k]) if k in summ[n][1] else "-"
            for n in results)))

    # 실패 문항 부록 — 마지막 구성 기준
    last = list(results)[-1]
    fails = failure_rows(results[last], qs)
    L += ["", "## 실패 문항 (%s 기준, %d건)" % (labels.get(last, last), len(fails)), ""]
    if fails:
        L += ["| 문항 | 유형 | 질의 | 기대 | 실제 상위 | 실패 항목 | 판정 |",
              "|---|---|---|---|---|---|---|"]
        for f in fails:
            L.append("| %s | %s | %s | %s | %s | %s | %s%s |" % (
                f["id"], f["type"], f["query"][:28], f["expected"][:32],
                f["got"][:38], f["failed"],
                f["decision"],
                "" if f["grade"] is None else " %.2f" % f["grade"]))
    else:
        L.append("없음.")

    L += ["", "실험 조건: `%s`" % config.describe(), ""]
    open(path, "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
