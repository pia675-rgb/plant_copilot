# -*- coding: utf-8 -*-
"""
convert_io_to_l1.py — 24종(mastertool/MAXIS) IO List → L1 IO LIST 표준양식

용도는 둘이다.
  1) 기존 자료를 새 양식으로 옮기는 이관
  2) 어댑터 회귀 시험 — 같은 자료를 두 양식으로 읽어 같은 점이 나오는지

L1 양식 파일을 틀로 쓴다(가이드·코드 시트를 그대로 둔다). IO LIST 시트의
예시 행은 지우고 원천 행만 싣는다.

지어내지 않는다
  · 원천에 없는 칸(LINE·Phase·GRP·DB BIT 등)은 비운다.
  · IO TYPE 만 있고 모듈 점수를 모르면 I/O 칸에 'AI' 처럼 종류만 적는다.
    (어댑터는 'AI' 도 'AI-4' 도 읽는다)
  · RANGE (단위) 는 원천에 범위가 없으면 단위만 적지 않고 비운다 —
    단위만 있는 칸은 L1 규칙('0~100%')과 모양이 다르다.
    범위는 계기 리스트가 채운다.

사용:
  python -m tools.convert_io_to_l1 --src demo_data/IO_LIST.xlsx \
      --template L1_IO_LIST_표준양식_Rev0_1.xlsx --out demo/IO_LIST_L1.xlsx
"""
from __future__ import annotations

import argparse
import os
import sys

from openpyxl import load_workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ingest.io_standard import L1_ORDER  # noqa: E402
from ingest.lists import read_rows  # noqa: E402

# L1 열 → 24종 원천 열(대문자, read_rows 가 돌려주는 이름)
FROM_24 = {
    "INDEX": "INDEX", "CPU": "PLC", "AREA": "LOCATION", "PANEL": "PANEL",
    "PN": "PN(DP)", "SLOT": "SLOT", "CH": "CH", "P&ID No.": "DWG NO.",
    "MARK": "SIGNAL TYPE1", "ADD": "ADD", "TAG": "TAG",
    "DESCRIPTION": "DESCRIPTION", "DB BIT": "BIT", "DB BYTE": "BYTE",
    "Instrument Power": "POWER SOURCE", "비고": "REMARK",
}


def convert(src, template, out):
    rows = read_rows(src)
    wb = load_workbook(template)
    ws = wb["IO LIST"]
    hdr = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(hdr) if h}
    missing = [h for h in L1_ORDER if h not in col]
    if missing:
        raise SystemExit("틀 파일에 L1 열이 없습니다: %s" % missing)
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    stations = {}
    for n, r in enumerate(rows, start=2):
        for l1, src_col in FROM_24.items():
            v = r.get(src_col)
            if v not in (None, ""):
                ws.cell(row=n, column=col[l1], value=v)
        io = str(r.get("IO TYPE") or "").strip().upper()
        if io:
            ws.cell(row=n, column=col["I/O"], value=io)
        # 24종의 중앙 랙(PN 공란·RACK n) → L1 의 PN. L1 은 랙마다 PN 을
        # 따로 준다(11부터). 원천에 PN 이 없으면 (판넬, 랙) 으로 번호를
        # 매긴다. 번호 자체는 가정값이라 비고에 적는다.
        if r.get("PN(DP)") in (None, ""):
            key = (str(r.get("PANEL") or ""), str(r.get("RACK") or 0))
            if key not in stations:
                stations[key] = 90 + len(stations)
            ws.cell(row=n, column=col["PN"], value=stations[key])
            note = "PN 가정값(원천 RACK %s)" % key[1]
            old = ws.cell(row=n, column=col["비고"]).value
            ws.cell(row=n, column=col["비고"],
                    value=("%s · %s" % (old, note)) if old else note)
    wb.active = wb.sheetnames.index("IO LIST")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    wb.save(out)
    return len(rows), stations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    n, st = convert(a.src, a.template, a.out)
    print("[convert] %d행 → %s (가정 PN %d개)" % (n, a.out, len(st)))


if __name__ == "__main__":
    main()
