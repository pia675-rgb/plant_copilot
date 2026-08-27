#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bm25.py — 어휘 검색 (BM25 Okapi)

v1 의 IDF 스코어링을 정식 BM25 로 교체한다. 차이는 두 가지다.

  · 문서 길이 정규화가 들어간다. v1 은 코드표(짧은 문자열)만 다뤄서
    필요 없었지만, 본문 청크(1,000자)와 코드 항목(100자)이 한 풀에
    섞이면 길이 보정 없이는 짧은 쪽이 항상 이긴다.
  · KO_EN 사전을 쓰지 않는다. v1 은 사전이 평가셋 용어에 맞춰져 있어
    점수가 부풀려졌다. 한글 질의는 dense 검색이 담당한다.

코드번호 완전일치는 검색이 아니라 조회다. exact_code() 로 분리했다.
"""

import math
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

K1 = 1.5
B = 0.75

TOKEN = re.compile(r"[a-z0-9]+|[가-힣]{2,}")
STOP = set(
    "the a an of is are be to for in on at and or with by from this that it its "
    "as has have been not no if can may will shall should must when then than "
    "see refer page section figure table note".split())

def _match_device(record_device, allowed):
    """allowed 가 str 또는 list 일 수 있다. 부분 일치 허용."""
    if not allowed:
        return True
    if isinstance(allowed, str):
        allowed = [allowed]
    rd = (record_device or "").upper()
    for a in allowed:
        au = (a or "").upper()
        if not au:
            continue
        if rd == au or au in rd or rd in au:
            return True
    if getattr(config, "CARD_DEVICE", None) and rd == str(config.CARD_DEVICE).upper():
        return True
    return False



def tok(s):
    s = (s or "").lower()
    return [w for w in TOKEN.findall(s) if w not in STOP and len(w) > 1]


class BM25:
    def __init__(self, records):
        self.records = records
        self.docs = [tok(r["title"] + " " + r["text"]) for r in records]
        self.n = len(self.docs)
        self.avglen = sum(len(d) for d in self.docs) / max(1, self.n)
        df = Counter()
        self.tf = []
        for d in self.docs:
            c = Counter(d)
            self.tf.append(c)
            df.update(c.keys())
        self.idf = {w: math.log(1 + (self.n - v + 0.5) / (v + 0.5))
                    for w, v in df.items()}
        # 역색인 — 질의어가 등장하는 문서만 훑는다
        self.inv = {}
        for i, c in enumerate(self.tf):
            for w in c:
                self.inv.setdefault(w, []).append(i)

    def search(self, query, top_k=None, device=None):
        top_k = top_k or config.BM25_TOP_K
        q = tok(query)
        if not q:
            return []
        cand = set()
        for w in q:
            cand.update(self.inv.get(w, ()))
        scores = []
        for i in cand:
            r = self.records[i]
            if device and not _match_device(r["device"], device):
                continue
            dl = len(self.docs[i])
            s = 0.0
            for w in q:
                f = self.tf[i].get(w, 0)
                if not f:
                    continue
                s += (self.idf.get(w, 0) * f * (K1 + 1)
                      / (f + K1 * (1 - B + B * dl / self.avglen)))
            if s > 0:
                scores.append((s, i))
        scores.sort(key=lambda x: -x[0])
        return [(self.records[i], s) for s, i in scores[:top_k]]

    def exact_code(self, query, device=None):
        """계기 화면 코드·카드 SSL 코드 완전일치 — 검색이 아니라 조회 경로.

        코드는 두 표기 체계가 섞여 있다. 계기 화면 코드는 십진수(300,
        4001)이고, 카드 진단 코드는 Siemens SSL 관례의 16진수+H 접미사
        (5H, 8H, 1FH, 10EH)다. 이전 패턴 [0-9]{2,6}[A-Fa-f]? 는 H 를
        16진 문자로 취급하지 않아 카드 코드 24종 전부를 놓쳤다 —
        "코드 조회가 있다"고 말하면서 카드 코드는 한 건도 조회되지
        않는 상태였다. 한 자리 코드(5H)와 중간에 16진 문자가 오는
        코드(10EH)까지 잡도록 패턴을 분리한다."""
        q = query or ""
        # 태그 표기(AIT-4002, WO-2026-029)의 숫자부는 코드가 아니다.
        # 조회 질의에 태그가 섞이면 4002 가 계기 코드 4002 와 완전일치해
        # System Error 가 근거 최상단에 오른다 — 태그 패턴을 먼저 지운다.
        q = re.sub(r"\b[A-Za-z]{1,5}(?:-[0-9]{2,6}[A-Za-z]?)+\b", " ", q)
        nums = {x.upper() for x in re.findall(r"[0-9]{2,6}[A-Fa-f]?", q)}
        nums |= {x.upper()
                 for x in re.findall(r"\b[0-9][0-9A-Fa-f]{0,3}[Hh]\b", q)}
        if not nums:
            return []
        out = []
        for r in self.records:
            if r.get("kind") != "error_code":
                continue
            if device and not _match_device(r["device"], device):
                continue
            if (r.get("code") or "").upper() in nums:
                out.append(r)
        return out
