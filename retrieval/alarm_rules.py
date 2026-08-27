#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alarm_rules.py — SCADA 알람 어휘 → 검색 정책 라우팅

왜 필요한가. SCADA 가 실제로 띄우는 알람명은 다섯 종 남짓이다 —
HH, LL, LOOP ERROR, ON/OFF COMMAND, 그리고 카드가 내는 SSL 진단 코드.
색인 전수 검색으로 확인한 사실: 이 어휘는 매뉴얼에 존재하지 않는다.

    loop error   0건
    high high    0건
    low low      0건

매뉴얼은 벤더가 쓰고 알람명은 SCADA 엔지니어가 쓴다. 접점이 없는 것이
정상이다. 그래서 알람명을 그대로 검색에 던지면 두 가지 중 하나가 된다 —
아무것도 못 찾거나, "power off"처럼 절차 문서 제목과 우연히 겹쳐
원인 절에 조작 절차가 실린다.

알람명이 유한하므로 의미 검색이 아니라 규칙으로 잇는다. 각 알람 유형에
매뉴얼·코드표의 실제 어휘를 확장어로 붙이고, 루프·SSL 계열은 카드가
주 근거임을 표시한다(분석기 전원이 나가면 계기는 아무 말도 못 한다 —
그 상실을 진단하는 것은 카드다).

확장어의 출처는 평가셋이 아니라 카드 진단표(ET200SP)와 매뉴얼
트러블슈팅 장의 실제 항목명이다. 평가셋 문항에는 이 알람 어휘가
등장하지 않음을 selfcheck(c_alarm_rules_inert)가 지킨다 — 라우팅이
평가 점수를 몰래 움직이는 일을 막는 가드다.
"""

import re

# Siemens SSL 진단 코드 — 5H, 8H, 1FH, 10EH, 105H …
SSL_CODE = re.compile(r"\b[0-9][0-9A-Fa-f]{0,3}[Hh]\b")

# 판별 규칙 — 두 부류를 다르게 다룬다.
#   구문형(loop error, high high, on command …)은 **대소문자 무시**.
#     SCADA 는 대문자로 보내지만 사람이 화면에 칠 때는 소문자다. 실제로
#     소문자 'loop error' 가 라우팅을 비껴가 DI loop(수처리 배관) 절이
#     올라온 일이 있었다. 구문 자체가 두 단어라 오인 여지가 없다.
#   축약형(HH, LL)만 **원문 대문자 그대로**. 소문자까지 받으면 언젠가
#     영어 낱말 속 hh/ll 과 부딪힐 수 있어 보수적으로 둔다 — SCADA 축약
#     알람을 사람이 소문자로 옮겨 칠 일은 드물고, 필요해지면 측정과 함께
#     넓힌다.
_PAT = [
    ("LOOP", [re.compile(r"\bLOOP\s*(ERROR|FAULT)\b|\bBAD\s*PV\b", re.I),
              re.compile(r"루프\s*에러|루프\s*이상")]),
    ("HH",   [re.compile(r"\bHH\b"),
              re.compile(r"\bHIGH\s*HIGH\b", re.I)]),
    ("LL",   [re.compile(r"\bLL\b"),
              re.compile(r"\bLOW\s*LOW\b", re.I)]),
    ("CMD",  [re.compile(r"\b(ON|OFF)\s*COMMAND\b", re.I)]),
]

# 확장어 — 카드 진단표·매뉴얼 트러블슈팅 장의 실제 표제어.
#   LOOP : 카드 6H(Wire break)·11H(Supply voltage missing)·8H(underrange),
#          매뉴얼 "The Analyzer Will Not Power On"(p.274)
#   HH/LL: 카드 7H/8H(limit violated, overrange/underrange)
#   CMD  : 출력 계통 — 매뉴얼 어휘가 아니라 인터락 영역이므로 확장하지
#          않는다. 유형만 표시해 화면·후속 로직이 인터락 조회로 안내한다.
_EXPAND = {
    "LOOP": ["wire break", "supply voltage missing",
             "will not power on", "fuse", "underrange", "4-20 mA"],
    "HH":   ["high limit violated", "overrange"],
    "LL":   ["low limit violated", "underrange"],
    "CMD":  [],
    "SSL":  [],           # 코드 완전일치(exact_code)가 처리한다
}

# 카드가 주 근거인 유형 — _cap_card 의 "카드 한 건 제한"을 푼다.
_CARD_PRIMARY = {"LOOP", "SSL"}


def classify(query):
    """알람 문구 → 라우팅 정보.

    반환: {"type": None|LOOP|HH|LL|CMD|SSL,
           "expand": [...], "card_primary": bool, "ssl_codes": [...]}
    유형이 안 잡히면 type=None — 검색은 종전과 완전히 같게 동작한다.
    자연어 질의(45문항·홀드아웃)는 전부 이 경로다.
    """
    q = query or ""
    ssl = sorted({m.group(0).upper() for m in SSL_CODE.finditer(q)})
    typ = None
    for name, pats in _PAT:
        if any(p.search(q) for p in pats):
            typ = name
            break
    if typ is None and ssl:
        typ = "SSL"
    return {
        "type": typ,
        "expand": list(_EXPAND.get(typ, [])),
        "card_primary": typ in _CARD_PRIMARY,
        "ssl_codes": ssl,
    }
