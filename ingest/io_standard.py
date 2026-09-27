# -*- coding: utf-8 -*-
"""
io_standard.py — 「L1 IO LIST 표준양식」 판별과 내부 열 이름 변환

왜 필요한가
-----------
앱 내부는 mastertool/MAXIS 24종 열 이름(PLC · PN(DP) · RACK · IO TYPE ·
UNIT …)으로 IO 점을 다룬다. L1 표준양식은 같은 정보를 다른 이름으로,
그리고 **같은 이름을 다른 뜻으로** 적는다. 이름만 보고 읽으면 조용히
틀린다 — 예외 없이 "그럴듯하게" 틀린다.

    열 이름   24종의 뜻              L1 표준양식의 뜻
    -------   ---------------------  ------------------------------------
    PLC       제어기 이름            PLC 기본 I/O Control 유형 (DI·COM·PID)
    UNIT      공학 단위 (%, bar)     대분류 공정 (RO · UF · ORG)
    I/O       (없음)                 모듈 타입 (AI-4 · DI-16 · RTD-8)

그래서 L1 양식이면 **읽는 즉시 내부 이름으로 옮기고**, 뜻이 겹치는 두
열(PLC · UNIT)은 원래 뜻의 새 이름(PLC TYPE · PROCESS UNIT)으로 비켜
놓는다. 이 모듈 밖의 코드는 두 양식을 구별하지 않는다.

지어내지 않는다
---------------
· RACK 열은 L1 에 없다. PN(스테이션) 하나가 랙 하나다 — 「RACK당 1씩
  연번 증가」(가이드 시트 PN 규칙). 그래서 RACK 은 비워 두지 않고 0 으로
  둔다. 카드 식별자는 (판넬, PN, 랙, 슬롯)이라 PN 이 유일성을 만든다.
· 공학 단위와 범위는 「RANGE (단위)」 한 칸에서만 읽는다 (예: 0~100%).
  못 읽으면 비운다. 계기 리스트에 값이 있으면 그쪽이 채운다.
· Spare(TAG 공란) 행은 기존과 같이 점으로 올리지 않는다.
"""

from __future__ import annotations

import re

# L1 양식 판별 — 이 열들이 한 헤더 행에 함께 있으면 L1 이다.
# 하나만 보면 우연히 겹칠 수 있다(24종에도 PANEL·SLOT·TAG 가 있다).
L1_SIGNATURE = {"CPU", "PN", "I/O", "DB BIT", "P&ID NO."}

# 가이드 시트 순서 그대로 (검사·헤더 교정 제안에 쓴다)
L1_ORDER = [
    "INDEX", "LINE", "구분(Phase)", "CPU", "AREA", "PANEL", "PN", "SLOT",
    "CH", "UNIT", "GRP1", "GRP2", "P&ID No.", "MARK", "I/O", "ADD", "TAG",
    "DESCRIPTION", "DB BIT", "DB BYTE", "HMI", "PLC", "SP", "START DB",
    "PRG1 TAG", "PRG1 ADD", "PRG1 BIT", "PRG2 TAG", "PRG2 ADD", "PRG2 BIT",
    "PID DB", "Instrument Power", "RANGE (단위)", "비고", "TEST 담당자",
    "시운전 예정일자", "시운전 완료 일자", "결과", "NG 내용 및 진행상황, 결과",
]

# L1 열(대문자) → 내부 열(대문자). 여기 없는 열은 이름 그대로 싣는다.
L1_TO_INTERNAL = {
    "CPU": "PLC",
    "AREA": "LOCATION",
    "PN": "PN(DP)",
    "P&ID NO.": "DWG NO.",
    "MARK": "SIGNAL TYPE1",
    "INSTRUMENT POWER": "POWER SOURCE",
    "DB BIT": "BIT",
    "DB BYTE": "BYTE",
    "비고": "REMARK",
    # 뜻이 겹치는 두 열 — 원래 뜻의 새 이름으로 비켜 놓는다
    "PLC": "PLC TYPE",
    "UNIT": "PROCESS UNIT",
    "HMI": "HMI TYPE",
    "GRP1": "EQUIP TYPE",
    "GRP2": "EQUIP NO",
    "I/O": "IO MODULE",
    "RANGE (단위)": "RANGE TEXT",
}

# 모듈 타입 → 내부 IO TYPE. RTD 는 아날로그 입력이지만 배선·카드가
# 다르므로 RTD 로 남긴다 (판넬 조회에서 카드 종류로 보인다).
_MODULE_RE = re.compile(r"^\s*(DI|DO|AI|AO|RTD)\s*-?\s*(\d+)?\s*$", re.I)

# 0~100% · 0 ~ 10 bar · -1~1 MPa · 0-50 m3/h
_RANGE_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*(?:~|–|-(?=\s*-?\d)|to)\s*(-?\d+(?:\.\d+)?)\s*(.*?)\s*$",
    re.I)


def _s(v):
    return str(v).strip() if v is not None else ""


def _hu(v):
    """헤더 정규화 — 줄바꿈·연속 공백을 접고 대문자로."""
    return re.sub(r"\s+", " ", _s(v)).upper()


def is_l1_header(header_cells) -> bool:
    got = {_hu(c) for c in header_cells if _s(c)}
    return L1_SIGNATURE.issubset(got)


def internal_name(l1_header_upper: str) -> str:
    return L1_TO_INTERNAL.get(l1_header_upper, l1_header_upper)


def parse_module(v):
    """'AI-4' → ('AI', 4). 못 읽으면 ('', None)."""
    m = _MODULE_RE.match(_s(v))
    if not m:
        return "", None
    return m.group(1).upper(), (int(m.group(2)) if m.group(2) else None)


def parse_range(v):
    """'0~100%' → (0.0, 100.0, '%'). 못 읽으면 (None, None, '')."""
    t = _s(v)
    if not t:
        return None, None, ""
    m = _RANGE_RE.match(t)
    if not m:
        return None, None, ""
    try:
        lo, hi = float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None, ""
    unit = m.group(3).strip().strip("()[]").strip()
    return lo, hi, unit


def _num(x):
    """0.0 → 0, 12.5 → 12.5 (계기 리스트 값과 같은 모양으로)."""
    return int(x) if x is not None and float(x).is_integer() else x


def normalize_row(rec: dict) -> dict:
    """L1 행(이미 내부 이름으로 옮긴 dict) 의 파생 열을 채운다.

    원본 칸은 그대로 두고 비어 있는 내부 열만 채운다.
    """
    io_type, points = parse_module(rec.get("IO MODULE"))
    if io_type and not _s(rec.get("IO TYPE")):
        rec["IO TYPE"] = io_type
    if points:
        rec["MODULE POINTS"] = points
    if rec.get("RACK") in (None, ""):
        rec["RACK"] = 0
    lo, hi, unit = parse_range(rec.get("RANGE TEXT"))
    if unit and not _s(rec.get("UNIT")):
        rec["UNIT"] = unit
    if lo is not None and rec.get("RANGE MIN") in (None, ""):
        rec["RANGE MIN"] = _num(lo)
    if hi is not None and rec.get("RANGE MAX") in (None, ""):
        rec["RANGE MAX"] = _num(hi)
    rec["_io_format"] = "L1"
    return rec


def pick_sheet(sheetnames):
    """L1 파일은 가이드·Revision·코드 시트가 함께 있다. 'IO LIST' 가
    있으면 그것을 읽는다. 가이드 시트에도 TAG 머리가 있어서, 활성 시트가
    가이드로 저장된 파일을 그냥 읽으면 '신호 식별' 같은 설명 문장이 태그로
    올라온다."""
    for n in sheetnames:
        if _hu(n) == "IO LIST":
            return n
    return None
