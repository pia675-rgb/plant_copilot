#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_error_codes.py — 계기 매뉴얼 PDF에서 경고/에러 코드표를 뽑아 통합 JSON 생성

대상:
  - Sievers M9/M9e  : Appendix F (Warning and Error Descriptions) — 번호 있는 코드
  - Mettler Toledo M300 : 14장 (파라미터별 Warning / Alarm 목록) — 번호 없음, 메시지 문자열이 키
  - Siemens ET200SP HA AI 16xI 2-wire HART HA : Table A-1(진단) / A-2(정비) — 16진 코드

출력 스키마 (레코드 1건):
  {
    "id":          "M9E-10122",
    "device":      "M9e",
    "code":        "10122",
    "severity":    "warning",
    "name":        "Sample Flow",
    "description": "...",
    "remedy":      "...",
    "scope":       "Analog input",
    "parameter":   "Cond",
    "source":      {"file": "...", "pdf_page": 413, "section": "Appendix F"}
  }

사용:
    python extract_error_codes.py --src /mnt/user-data/uploads --out error_codes.json

의존성: pdfplumber
"""

import argparse
import json
import os
import re

import pdfplumber

M9 = "im_e_sievers-m9-manual_dlm_77020-02.pdf"
M300 = "OM_Transmitter_M300_en_52121389_Dec14.pdf"
ET200 = "et200sp_ha_AI_16xI_2-wire_HART_HA_en-US_en-US.pdf"


def clean(s):
    """줄바꿈 하이픈(‐\n) 결합, 개행 → 공백, 공백 정리."""
    if not s:
        return ""
    s = s.replace("\u2010\n", "").replace("-\n", "")
    s = s.replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def is_header(row, first, second=None):
    if not row or not row[0]:
        return False
    a = clean(row[0]).lower()
    if a != first.lower():
        return False
    if second is not None:
        b = clean(row[1]).lower() if len(row) > 1 and row[1] else ""
        return b == second.lower()
    return True


# ─────────────────────────────────────────────────────────────
# 1) Sievers M9/M9e — Appendix F
# ─────────────────────────────────────────────────────────────
def parse_m9(path):
    out = []
    with pdfplumber.open(path) as pdf:
        for pi, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            if "Appendix F" not in txt:
                continue
            for table in page.extract_tables():
                if not table or not is_header(table[0], "#"):
                    continue
                for row in table[1:]:
                    if len(row) < 4:
                        continue
                    code = clean(row[0])
                    sev = clean(row[1]).lower()
                    name = clean(row[2])
                    desc = clean(row[3])
                    if not code:
                        # 앞 레코드의 설명 이어짐
                        if out and desc:
                            out[-1]["description"] = (
                                out[-1]["description"] + " " + desc).strip()
                            if name and not out[-1]["name"]:
                                out[-1]["name"] = name
                        continue
                    if not re.fullmatch(r"\d{3,6}", code):
                        continue
                    grouped = False
                    if not desc and out and out[-1]["device"] == "M9e":
                        # 4000~40xx 처럼 여러 코드가 한 설명을 공유하는 블록
                        sev = sev or out[-1]["severity"]
                        name = name or out[-1]["name"]
                        desc = out[-1]["description"]
                        grouped = True
                    out.append({
                        "id": "M9E-" + code,
                        "device": "M9e",
                        "code": code,
                        "severity": "error" if "error" in sev else "warning",
                        "name": name,
                        "description": desc,
                        "remedy": "",
                        "scope": None,
                        "parameter": None,
                        "shared_description": grouped,
                        "source": {"file": os.path.basename(path),
                                   "pdf_page": pi + 1,
                                   "section": "Appendix F"},
                    })
    return out


# ─────────────────────────────────────────────────────────────
# 2) Mettler Toledo M300 — 14장
# ─────────────────────────────────────────────────────────────
PARAM_PATTERNS = [
    ("Cond", r"\bcond\b|conductivity|cell (open|shorted)"),
    ("ORP", r"\borp\b"),
    ("pH", r"\bph\b|pna"),
    ("Ozone", r"ozone|\bo\s*3\b"),
    ("DO", r"\bdo\b|dissolved oxygen|\bo\s*2\b"),
]


def guess_parameter(rows):
    scores = {}
    blob = " ".join(clean(r[0]).lower() for r in rows if r and r[0])
    for name, pat in PARAM_PATTERNS:
        scores[name] = len(re.findall(pat, blob, re.I))
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def parse_m300(path):
    out = []
    with pdfplumber.open(path) as pdf:
        for pi, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            if "Error Messages" not in txt and "Warning- and Alarm" not in txt:
                continue
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                head = clean(table[0][0]).lower().rstrip("*")
                if head not in ("warnings", "alarms"):
                    continue
                sev = "warning" if head == "warnings" else "alarm"
                param = guess_parameter(table[1:])
                for row in table[1:]:
                    if len(row) < 2:
                        continue
                    msg = clean(row[0]).rstrip("*").strip()
                    desc = clean(row[1])
                    if not msg or msg.lower() in ("warnings", "alarms"):
                        continue
                    slug = re.sub(r"[^A-Za-z0-9]+", "-", msg).strip("-")[:48]
                    out.append({
                        "id": "M300-" + slug,
                        "device": "M300",
                        "code": None,
                        "severity": sev,
                        "name": msg,
                        "description": desc,
                        "remedy": "",
                        "scope": None,
                        "parameter": param,
                        "source": {"file": os.path.basename(path),
                                   "pdf_page": pi + 1,
                                   "section": "14. Troubleshooting"},
                    })
    return out


# ─────────────────────────────────────────────────────────────
# 3) Siemens ET200SP HA AI 16xI — Table A-1 / A-2
# ─────────────────────────────────────────────────────────────
def norm_hex(s):
    s = clean(s).upper().replace(" ", "")
    m = re.fullmatch(r"([0-9A-F]{1,4})H?", s)
    return (m.group(1) + "H") if m else None


def parse_et200(path):
    out = []
    with pdfplumber.open(path) as pdf:
        for pi, page in enumerate(pdf.pages):
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                h0 = clean(table[0][0]).lower()
                if h0.startswith("diagnostics mes"):
                    kind, sev, section = "diagnostic", "diagnostic", "Table A-1"
                elif h0.startswith("maintenance mes"):
                    kind, sev, section = "maintenance", "maintenance", "Table A-2"
                else:
                    continue
                for row in table[1:]:
                    if len(row) < 5:
                        continue
                    name = clean(row[0])
                    code = norm_hex(row[1])
                    scope = clean(row[2])
                    meaning = clean(row[3])
                    remedy = clean(row[4])
                    if not code:
                        if out and (meaning or remedy):
                            out[-1]["description"] = (
                                out[-1]["description"] + " " + meaning).strip()
                            out[-1]["remedy"] = (
                                out[-1]["remedy"] + " " + remedy).strip()
                        continue
                    out.append({
                        "id": "ET200SP-" + code,
                        "device": "AI 16xI 2-wire HART HA",
                        "code": code,
                        "severity": sev,
                        "name": name,
                        "description": meaning,
                        "remedy": remedy,
                        "scope": scope or None,
                        "parameter": None,
                        "source": {"file": os.path.basename(path),
                                   "pdf_page": pi + 1,
                                   "section": section},
                    })
    return out


# ─────────────────────────────────────────────────────────────
def dedupe(records):
    seen, out = {}, []
    for r in records:
        key = (r["device"], r["id"], r["name"])
        if key in seen:
            prev = out[seen[key]]
            # 더 긴 설명 쪽을 채택
            if len(r["description"]) > len(prev["description"]):
                out[seen[key]] = r
            continue
        seen[key] = len(out)
        out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser(description="매뉴얼 에러코드 표 추출")
    ap.add_argument("--src", default="/mnt/user-data/uploads")
    ap.add_argument("--out", default="error_codes.json")
    ap.add_argument("--csv", default="", help="CSV도 함께 저장할 경로")
    args = ap.parse_args()

    recs = []
    jobs = [(M9, parse_m9), (M300, parse_m300), (ET200, parse_et200)]
    for fname, fn in jobs:
        p = os.path.join(args.src, fname)
        if not os.path.exists(p):
            print("건너뜀 (파일 없음): %s" % fname)
            continue
        got = fn(p)
        print("%-58s %4d건" % (fname[:58], len(got)))
        recs.extend(got)

    recs = dedupe(recs)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)

    if args.csv:
        import csv as _csv
        cols = ["id", "device", "code", "severity", "name", "description",
                "remedy", "scope", "parameter", "file", "pdf_page", "section"]
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in recs:
                row = {k: r.get(k) for k in cols[:9]}
                row.update({"file": r["source"]["file"],
                            "pdf_page": r["source"]["pdf_page"],
                            "section": r["source"]["section"]})
                w.writerow(row)

    by_dev = {}
    for r in recs:
        by_dev[r["device"]] = by_dev.get(r["device"], 0) + 1
    print("\n총 %d건 → %s" % (len(recs), args.out))
    for k, v in by_dev.items():
        print("  %-26s %d" % (k, v))


if __name__ == "__main__":
    main()
