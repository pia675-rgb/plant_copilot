#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_index.py — 검색 단위 통합 인덱스 생성

두 종류를 하나의 스키마로 합친다.

    error_code   v1 이 만든 코드표 306건. 구조화되어 있고 정답이 분명하다.
    manual_text  매뉴얼 본문 청크 1,500여 건. 코드표에 없는 증상을 담당한다.

둘을 섞되 kind 를 남겨둔다. 코드 질의는 error_code 가, 서술형 증상은
manual_text 가 이기는 게 정상이고, 그 분포 자체가 평가 지표가 된다.

산출: index/chunks.jsonl  (1행 1청크)

사용:
    python -m ingest.build_index
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from ingest.chunker import chunk_all  # noqa: E402


def code_records():
    """error_codes.json → 통합 스키마."""
    with open(config.ERROR_CODES, encoding="utf-8") as f:
        codes = json.load(f)
    out = []
    for c in codes:
        # 검색 본문에는 코드번호를 반복해 넣지 않는다.
        # 번호 일치는 별도 경로(exact match)로 처리하고,
        # 여기서는 의미 검색이 걸리도록 자연어만 담는다.
        text = " — ".join(x for x in [c.get("name"), c.get("description"),
                                      c.get("remedy")] if x)
        out.append({
            "id": c["id"],
            "kind": "error_code",
            "device": c["device"],
            "title": c.get("name") or c["id"],
            "level": 0,
            "text": text,
            "code": c.get("code") or "",
            "severity": c.get("severity") or "",
            "remedy": c.get("remedy") or "",
            "source": c["source"],
        })
    return out


def build():
    print("[1/2] 매뉴얼 본문 청킹")
    chunks = chunk_all()
    print("[2/2] 코드표 로드")
    codes = code_records()
    print("  error_code %d건" % len(codes))

    allrec = codes + chunks
    os.makedirs(config.INDEX_DIR, exist_ok=True)
    with open(config.CHUNKS_JSONL, "w", encoding="utf-8") as f:
        for r in allrec:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n인덱스 저장: %s  (총 %d건)" % (config.CHUNKS_JSONL, len(allrec)))
    return allrec


def load():
    """저장된 인덱스를 읽는다. 없으면 만들어서 읽는다."""
    if not os.path.exists(config.CHUNKS_JSONL):
        return build()
    with open(config.CHUNKS_JSONL, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


if __name__ == "__main__":
    build()
