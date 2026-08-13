#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chunker.py — 벤더 매뉴얼 PDF → 섹션 단위 청크 (개선판)

변경 사항 (2026-08-13)
-----------------------
- 하드코딩된 MANUAL_DEVICE 파일 목록에만 의존하지 않음
- data/manuals/ 아래 **모든 하위 폴더**를 재귀적으로 스캔
- 폴더명 + 파일명에서 device(메이커/모델)를 자동 추출
- 기존 MANUAL_DEVICE에 있는 파일은 그 매핑을 우선 사용 (하위 호환)

사용:
    python -m ingest.chunker --stats
    python -m ingest.chunker --dump 3
    python -m ingest.build_index
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

# 목차·색인·판권 등 본문이 아닌 섹션
SKIP_TITLE = re.compile(
    r"table of contents|^contents$|^index$|legal information|"
    r"trademarks|copyright|warranty|quick reference",
    re.I)

WS = re.compile(r"[ \t\xa0]+")
MULTI_NL = re.compile(r"\n{3,}")


def norm_line(s):
    return WS.sub(" ", s.replace("\u200b", "")).strip()


def find_boilerplate(pages, min_ratio=0.25, max_len=90):
    """여러 페이지에 반복 등장하는 짧은 줄 = 머리말/꼬리말로 본다."""
    n = len(pages)
    if n < 8:
        return set()
    c = Counter()
    for txt in pages:
        lines = {norm_line(x) for x in txt.split("\n")[:4]}
        lines |= {norm_line(x) for x in txt.split("\n")[-4:]}
        for x in lines:
            if 3 < len(x) <= max_len:
                c[x] += 1
    return {x for x, v in c.items() if v >= n * min_ratio}


def strip_page(txt, boiler):
    out = []
    for raw in txt.split("\n"):
        line = norm_line(raw)
        if not line or line in boiler:
            continue
        if re.fullmatch(r"[-–\s]*\d{1,4}[-–\s]*", line):
            continue
        out.append(line)
    return "\n".join(out)


def toc_sections(doc):
    """책갈피 → [(level, title, start_page0, end_page0)] (0-based, 끝 포함)."""
    toc = doc.get_toc()
    if not toc:
        return [(1, "(전체)", 0, doc.page_count - 1)]
    entries = [(lv, title, max(0, page - 1)) for lv, title, page in toc]
    out = []
    for i, (lv, title, start) in enumerate(entries):
        end = entries[i + 1][2] - 1 if i + 1 < len(entries) else doc.page_count - 1
        end = max(start, end)
        out.append((lv, title, start, end))
    return out


def split_text(text, target, max_chars, overlap, min_chars):
    """긴 본문을 목표 길이로 나눈다. 문단 경계를 우선한다."""
    text = MULTI_NL.sub("\n\n", text).strip()
    if len(text) <= max_chars:
        return [text] if len(text) >= min_chars else []

    paras = re.split(r"\n\s*\n", text)
    chunks, buf = [], ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if buf and len(buf) + len(p) + 2 > target:
            if len(buf) >= min_chars:
                chunks.append(buf)
            # overlap
            if overlap > 0 and len(buf) > overlap:
                buf = buf[-overlap:] + "\n\n" + p
            else:
                buf = p
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p

        while len(buf) > max_chars:
            cut = buf.rfind("\n", 0, max_chars)
            if cut < min_chars:
                cut = max_chars
            chunks.append(buf[:cut].strip())
            buf = buf[max(0, cut - overlap):].strip()

    if buf and len(buf) >= min_chars:
        chunks.append(buf)
    return chunks


def chunk_manual(path, device):
    doc = pymupdf.open(path)
    fname = os.path.basename(path)
    pages = [doc[i].get_text() for i in range(doc.page_count)]
    boiler = find_boilerplate(pages)
    clean = [strip_page(t, boiler) for t in pages]

    out = []
    for lv, title, s, e in toc_sections(doc):
        if SKIP_TITLE.search(title):
            continue
        body = "\n\n".join(clean[s:e + 1]).strip()
        if len(body) < config.CHUNK_MIN_CHARS:
            continue
        parts = split_text(body, config.CHUNK_TARGET_CHARS,
                           config.CHUNK_MAX_CHARS,
                           config.CHUNK_OVERLAP_CHARS,
                           config.CHUNK_MIN_CHARS)
        for k, part in enumerate(parts):
            span = max(1, e - s + 1)
            approx = s + min(span - 1, int(k * span / max(1, len(parts))))
            out.append({
                "id": "%s#%s#%d" % (device, re.sub(r"\W+", "_", title)[:40], k),
                "kind": "manual_text",
                "device": device,
                "title": title,
                "level": lv,
                "text": part,
                "source": {
                    "file": fname,
                    "rel_path": str(Path(path).relative_to(config.MANUAL_DIR)).replace("\\", "/")
                               if Path(path).is_relative_to(config.MANUAL_DIR) else fname,
                    "pdf_page": approx + 1,
                    "page_from": s + 1,
                    "page_to": e + 1,
                    "section": title,
                },
            })
    doc.close()
    return out


# ---------------------------------------------------------------------------
# device 이름 자동 추출
# ---------------------------------------------------------------------------

def _guess_device(rel_path: str, fname: str) -> str:
    """
    상대경로 + 파일명에서 검색에 쓸 device 키를 만든다.

    우선순위:
      1. config.MANUAL_DEVICE에 등록된 파일명
      2. 파일명 stem (확장자 제거)
      3. 바로 위 폴더명 (메이커 폴더)
    """
    # 1) 기존 하드코딩 매핑 우선
    mapping = getattr(config, "MANUAL_DEVICE", {}) or {}
    if fname in mapping:
        return mapping[fname]

    stem = Path(fname).stem

    # 숫자 모델이 분명한 경우 (510, M9e, M300 등)
    if re.fullmatch(r"[A-Za-z]*\d+[A-Za-z0-9]*", stem) and len(stem) >= 2:
        return stem

    # 폴더에서 메이커/모델 힌트
    parts = Path(rel_path).parts[:-1]  # 파일 제외
    for part in reversed(parts):
        cleaned = part.strip()
        if not cleaned:
            continue
        low = cleaned.lower()
        if low in ("manuals", "카탈로그", "catalog", "catalogue",
                   "analyzer catalogue", "instrument catalogue", "data"):
            continue
        # DO_Oribisphere → Oribisphere 또는 510
        if "_" in cleaned:
            # 앞부분(카테고리) 버리고 뒷부분을 우선
            tail = cleaned.split("_", 1)[-1]
            if len(tail) >= 3:
                return tail
        if len(cleaned) >= 3:
            return cleaned

    return stem or "Unknown"


def _list_all_pdfs(manual_dir: str) -> list[tuple[str, str]]:
    """
    (절대경로, manuals 기준 상대경로) 리스트.
    """
    root = Path(manual_dir)
    if not root.is_dir():
        return []
    out = []
    for p in root.rglob("*.pdf"):
        if p.name.startswith("~$"):
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.name
        out.append((str(p), rel))
    return sorted(out, key=lambda x: x[1].lower())


def chunk_all(manual_dir=None, mapping=None):
    """
    manuals/ 아래 모든 PDF를 재귀적으로 청킹한다.
    """
    manual_dir = manual_dir or config.MANUAL_DIR
    # mapping은 이제 override용으로만 사용 (하위 호환)
    override = mapping or getattr(config, "MANUAL_DEVICE", {}) or {}

    out = []
    pdfs = _list_all_pdfs(manual_dir)
    if not pdfs:
        print("  [경고] PDF를 하나도 찾지 못했습니다: %s" % manual_dir)
        return out

    print("  발견된 PDF %d개" % len(pdfs))
    for abs_path, rel in pdfs:
        fname = os.path.basename(abs_path)
        device = override.get(fname) or _guess_device(rel, fname)
        try:
            got = chunk_manual(abs_path, device)
            print("  %-55s  device=%-20s  청크 %d" % (
                rel[:55], device[:20], len(got)))
            out.extend(got)
        except Exception as e:
            print("  [실패] %s → %s" % (rel, e))
    return out


def main():
    ap = argparse.ArgumentParser(description="매뉴얼 청킹 (재귀 스캔)")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--dump", type=int, default=0, help="샘플 청크 N건 출력")
    args = ap.parse_args()

    chunks = chunk_all()
    print("\n총 청크 %d건" % len(chunks))
    if args.stats:
        if not chunks:
            return
        lens = sorted(len(c["text"]) for c in chunks)
        print("길이 중앙값 %d / 최소 %d / 최대 %d"
              % (lens[len(lens) // 2], lens[0], lens[-1]))
        by = Counter(c["device"] for c in chunks)
        print("\n[device별 청크 수]")
        for k, v in sorted(by.items(), key=lambda x: -x[1]):
            print("  %-28s %d" % (k, v))
    for c in chunks[:args.dump]:
        print("\n" + "-" * 70)
        print("%s  [%s p.%d]" % (c["id"], c["source"]["file"],
                                 c["source"]["pdf_page"]))
        print(c["text"][:400])


if __name__ == "__main__":
    main()
