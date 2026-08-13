#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manual_match.py — 계기 모델/메이커 ↔ 매뉴얼 파일 자동 대조 (개선판)

변경 사항 (2026-08-13)
-----------------------
1. 폴더명(메이커)도 매칭 신호로 사용한다.
   - 기존: 파일명 토큰에 모델명이 있을 때만 연결 (폴더명은 무시)
   - 변경: 모델 매칭이 애매하거나 없을 때, 상위 폴더명에 메이커가
           들어있으면 그 후보를 우선한다.

2. P&ID TAG 기준으로 매뉴얼을 찾도록 지원.
   - 알람 조회는 IO List TAG를 사용
   - 매뉴얼·계기 사양 조회는 P&ID TAG (또는 그로부터 얻은 MODEL/MAKER)를 사용

3. find_manual(maker, model) 헬퍼 추가 → 4D 리포트 / advisor에서 바로 사용 가능

원칙은 그대로 유지:
  - 후보가 여러 개면 잇지 않는다 (잘못된 매뉴얼이 없는 것보다 나쁨)
  - 사람이 이미 MANUAL FILE을 적어 둔 경우 덮어쓰지 않는다
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


# ---------------------------------------------------------------------------
# 토큰 / 키 유틸
# ---------------------------------------------------------------------------

def _tokens(name: str) -> set:
    """파일명/폴더명을 대조용 토큰으로 쪼갠다. 확장자·구분자 제거, 대문자."""
    stem = os.path.splitext(name)[0].upper()
    return set(t for t in re.split(r"[^A-Z0-9]+", stem) if t and len(t) >= 2)


def _model_keys(model: str) -> List[str]:
    """
    모델 표기에서 대조 키를 만든다.

    'M300' 은 그대로, 'M9e' 는 'M9E' 로.
    '510 & 31120' 같은 표기도 조각으로 본다.
    """
    m = (model or "").strip().upper()
    if not m:
        return []
    keys = [re.sub(r"[^A-Z0-9]", "", m)]
    keys += [t for t in re.split(r"[^A-Z0-9]+", m) if len(t) >= 2]

    # 숫자로 끝나는 앞부분도 키로 (M9e → M9)
    base = re.match(r"^([A-Z]+\d+)", keys[0]) if keys else None
    if base and len(base.group(1)) >= 2:
        keys.append(base.group(1))

    # 순수 숫자 모델 (510, 31120 등) 도 인정
    for t in re.findall(r"\d{3,}", m):
        keys.append(t)

    return [k for k in dict.fromkeys(keys) if len(k) >= 2]


def _maker_keys(maker: str) -> List[str]:
    """메이커 이름에서 검색 키 추출."""
    m = (maker or "").strip().upper()
    if not m:
        return []
    keys = [re.sub(r"[^A-Z0-9]", "", m)]
    keys += [t for t in re.split(r"[^A-Z0-9]+", m) if len(t) >= 3]
    return [k for k in dict.fromkeys(keys) if len(k) >= 3]


# ---------------------------------------------------------------------------
# 매뉴얼 파일 목록 (재귀)
# ---------------------------------------------------------------------------

def list_manual_pdfs(manual_dir: str | None = None) -> List[str]:
    """매뉴얼 PDF 목록 — 하위 폴더까지 전부 훑는다. 상대경로 반환."""
    manual_dir = manual_dir or config.MANUAL_DIR
    if not os.path.isdir(manual_dir):
        return []
    out = []
    for root, _dirs, files in os.walk(manual_dir):
        for f in files:
            if f.lower().endswith(".pdf") and not f.startswith("~$"):
                rel = os.path.relpath(os.path.join(root, f), manual_dir)
                out.append(rel.replace("\\", "/"))
    return sorted(out)


def _folder_tokens(rel_path: str) -> set:
    """상대경로의 폴더 부분에서 토큰을 뽑는다 (파일명 제외)."""
    parts = rel_path.replace("\\", "/").split("/")[:-1]
    toks = set()
    for p in parts:
        toks |= _tokens(p)
    return toks


# ---------------------------------------------------------------------------
# 핵심 매칭
# ---------------------------------------------------------------------------

def build_map(
    manual_dir: str | None = None,
    models: List[str] | None = None,
    makers: Dict[str, str] | None = None,
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    모델 → 매뉴얼 상대경로.

    makers: {model: maker} 딕셔너리를 넘기면 폴더명 메이커 신호를 추가로 사용.

    반환: (확실한 매핑, 애매한 후보들)
    """
    manual_dir = manual_dir or config.MANUAL_DIR
    if not os.path.isdir(manual_dir):
        return {}, {}

    files = list_manual_pdfs(manual_dir)
    # 파일명 토큰 + 폴더 토큰
    file_index = {}
    for f in files:
        base = os.path.basename(f)
        file_index[f] = {
            "name_toks": _tokens(base),
            "folder_toks": _folder_tokens(f),
            "all_toks": _tokens(base) | _folder_tokens(f),
        }

    out: Dict[str, str] = {}
    ambiguous: Dict[str, List[str]] = {}

    for model in sorted(set(models or [])):
        model = str(model or "").strip()
        if not model:
            continue

        mkeys = _model_keys(model)
        if not mkeys:
            continue

        maker = (makers or {}).get(model, "")
        maker_keys = _maker_keys(maker)

        # 1차: 파일명에 모델 토큰이 있는 후보
        name_hits = [
            f for f, info in file_index.items()
            if any(k in info["name_toks"] for k in mkeys)
        ]

        if len(name_hits) == 1:
            out[model] = name_hits[0]
            continue
        if len(name_hits) > 1:
            # 메이커 폴더로 좁혀본다
            if maker_keys:
                narrowed = [
                    f for f in name_hits
                    if any(k in file_index[f]["folder_toks"] for k in maker_keys)
                ]
                if len(narrowed) == 1:
                    out[model] = narrowed[0]
                    continue
            ambiguous[model] = name_hits
            continue

        # 2차: 파일명에는 없지만, 폴더(메이커) + 모델 힌트로 찾기
        # (예: DO_Oribisphere/510.pdf  + model="510")
        if maker_keys:
            folder_hits = [
                f for f, info in file_index.items()
                if any(k in info["folder_toks"] for k in maker_keys)
                and any(k in info["name_toks"] for k in mkeys)
            ]
            if len(folder_hits) == 1:
                out[model] = folder_hits[0]
                continue
            if len(folder_hits) > 1:
                ambiguous[model] = folder_hits
                continue

            # 모델 토큰이 파일명에 없어도, 메이커 폴더 안에 PDF가 딱 하나면 연결
            # (위험할 수 있으므로 후보가 1개일 때만)
            maker_only = [
                f for f, info in file_index.items()
                if any(k in info["folder_toks"] for k in maker_keys)
            ]
            if len(maker_only) == 1:
                out[model] = maker_only[0]
                continue

    return out, ambiguous


def manual_for(points: dict, manual_dir: str | None = None) -> Tuple[int, dict, dict]:
    """
    조인 결과(TAG → 레코드)에 MANUAL FILE 을 채운다.

    이미 값이 있으면 건드리지 않는다.
    """
    models = []
    makers_map = {}  # model → maker
    for r in points.values():
        model = str(r.get("MODEL") or "").strip()
        maker = str(r.get("MAKER") or r.get("Maker") or "").strip()
        if model:
            models.append(model)
            if maker:
                makers_map[model] = maker

    mapping, ambiguous = build_map(manual_dir, models, makers_map)
    n = 0
    for r in points.values():
        if str(r.get("MANUAL FILE") or "").strip():
            continue
        model = str(r.get("MODEL") or "").strip()
        f = mapping.get(model)
        if f:
            r["MANUAL FILE"] = f
            n += 1
    return n, mapping, ambiguous


def find_manual(
    maker: str = "",
    model: str = "",
    manual_dir: str | None = None,
) -> Optional[str]:
    """
    메이커 + 모델로 매뉴얼 상대경로를 바로 찾는다.
    4D 리포트 / advisor / API에서 사용하기 좋은 헬퍼.
    """
    if not model and not maker:
        return None
    models = [model] if model else []
    makers = {model: maker} if model and maker else {}
    mapping, _ = build_map(manual_dir, models, makers)
    if model and model in mapping:
        return mapping[model]

    # model이 비어있고 maker만 있는 경우 → 해당 메이커 폴더의 PDF가 1개면 반환
    if maker and not model:
        files = list_manual_pdfs(manual_dir)
        maker_keys = _maker_keys(maker)
        hits = []
        for f in files:
            if any(k in _folder_tokens(f) for k in maker_keys):
                hits.append(f)
        if len(hits) == 1:
            return hits[0]
    return None


# ---------------------------------------------------------------------------
# 디버그 / CLI
# ---------------------------------------------------------------------------

def render() -> str:
    from ingest.lists import read_instrument_rows
    rows = read_instrument_rows(
        getattr(config, "INSTRUMENT_SPECS", None)
        or getattr(config, "INSTRUMENT_SPEC", None)
    )
    models = [str(r.get("MODEL") or "").strip() for r in rows]
    makers_map = {}
    for r in rows:
        m = str(r.get("MODEL") or "").strip()
        k = str(r.get("MAKER") or "").strip()
        if m and k:
            makers_map[m] = k

    mapping, ambiguous = build_map(None, models, makers_map)
    uniq = sorted({m for m in models if m})

    L = [
        "=" * 72,
        "모델/메이커 ↔ 매뉴얼 대조 (개선판)",
        "=" * 72,
        "계기 리스트 모델 %d종 · 매뉴얼 %d개"
        % (
            len(uniq),
            len([f for f in list_manual_pdfs() if f.lower().endswith(".pdf")])
            if os.path.isdir(config.MANUAL_DIR)
            else 0,
        ),
        "",
    ]
    for m in uniq:
        maker = makers_map.get(m, "")
        if m in mapping:
            L.append("  %-20s [%s] → %s" % (m, maker or "-", mapping[m]))
        elif m in ambiguous:
            L.append(
                "  %-20s [%s] ? 후보 여럿 — 잇지 않음 (%s)"
                % (m, maker or "-", ", ".join(ambiguous[m][:3]))
            )
        else:
            L.append("  %-20s [%s] — 매뉴얼 없음" % (m, maker or "-"))
    L.append("")
    L.append(
        "※ 1순위: 파일명에 모델 토큰 존재  "
        "2순위: 메이커 폴더 + 모델  "
        "후보가 여럿이면 비움"
    )
    L.append("=" * 72)
    return "\n".join(L)


if __name__ == "__main__":
    print(render())
