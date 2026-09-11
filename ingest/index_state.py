#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
index_state.py — 색인이 지금 자료와 맞는지 판정한다 (패치 34)

9/2 리허설 발견 4번. 자료를 하나도 바꾸지 않았는데 「색인 다시 만들기」를
누르면 그대로 몇 분을 돌았다. 화면은 진행률만 보여 주었고, 그 몇 분이
필요한 것이었는지는 끝나도 알 수 없었다.

**판정은 서버에서 하고 화면은 값만 읽는다.** 화면이 스스로 판정하면 같은
질문에 두 곳이 다른 답을 하게 되고, 어느 쪽이 맞는지 아무도 모른다.

**자동으로 건너뛰지 않는다.** 이 모듈은 답을 말할 뿐이고, 재생성을 누를지
는 사람이 정한다. 판정 근거(무엇을 무엇과 대조했는지)를 함께 싣는 이유도
그것이다 — 근거를 못 보면 사람이 판정을 믿을 수도, 의심할 수도 없다.

## 대조 기준 두 가지

manifest  재생성이 끝날 때 원본의 SHA-256 을 적어 둔 기록과 대조한다.
          내용이 같은지 다른지를 정확히 안다.
mtime     그 기록이 없을 때(배치로 만든 색인, 이 패치 이전의 색인)는 파일
          수정 시각을 색인 파일 시각과 견준다. **시각을 그대로 둔 채 내용만
          바꾼 경우는 알 수 없다.** 그래서 판정에 기준을 함께 실어 화면이
          그 한계를 말할 수 있게 한다 — 조용히 틀리는 것보다 시끄럽게
          모르겠다고 하는 쪽이 낫다.

색인에 들어가는 원본은 두 종류다. 매뉴얼 PDF(manuals/ 아래 전부, 재귀)와
코드표(derived/error_codes.json). 리스트류(IO·계기·TB·인터락)는 색인을
거치지 않고 조회 시점에 읽으므로 여기 들어오지 않는다.
"""

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

MANIFEST_NAME = "index_sources.json"


# ── 원본 목록 ───────────────────────────────────────────────
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _stat_rec(path: str, rel: str, kind: str) -> dict:
    stt = os.stat(path)
    return {
        "rel": rel,
        "kind": kind,                 # manual | codes
        "name": os.path.basename(path),
        "bytes": stt.st_size,
        "mtime": int(stt.st_mtime),
        "sha256": _sha256(path),
    }


def list_sources(manual_dir=None, error_codes=None) -> list:
    """색인에 들어가는 원본 파일. 정렬은 화면에 그대로 나가므로 고정한다."""
    out = []
    root = Path(manual_dir or config.MANUAL_DIR)
    if root.is_dir():
        pdfs = sorted(root.rglob("*.pdf"), key=lambda p: p.as_posix().lower())
        for p in pdfs:
            # 엑셀·PDF 편집기가 남기는 잠금 파일. 청킹도 건너뛴다.
            if p.name.startswith("~$"):
                continue
            out.append(_stat_rec(str(p), p.relative_to(root).as_posix(),
                                 "manual"))
    ec = config.ERROR_CODES if error_codes is None else error_codes
    if ec and os.path.isfile(ec):
        out.append(_stat_rec(ec, "코드표 · %s" % os.path.basename(ec), "codes"))
    return out


# ── 색인 쪽 ─────────────────────────────────────────────────
def _idx_paths(index_dir=None):
    idx = str(index_dir or config.INDEX_DIR)
    return (os.path.join(idx, os.path.basename(config.CHUNKS_JSONL)),
            os.path.join(idx, os.path.basename(config.EMBED_NPY)),
            os.path.join(idx, os.path.basename(config.EMBED_META)))


def _manifest_path(index_dir=None) -> str:
    return os.path.join(str(index_dir or config.INDEX_DIR), MANIFEST_NAME)


def _index_fingerprint(index_dir=None) -> dict:
    """색인 자신의 지문. 기록을 남긴 뒤 배치로 색인을 다시 만들면 기록이
    낡은 것이 되는데, 그것을 모르면 '변경 있음' 을 잘못 말한다."""
    chunks, npy, _ = _idx_paths(index_dir)
    out = {}
    for key, path in (("chunks", chunks), ("embed", npy)):
        try:
            stt = os.stat(path)
            out[key] = [stt.st_size, int(stt.st_mtime)]
        except OSError:
            out[key] = None
    return out


def _built_at(index_dir=None):
    """색인이 만들어진 시각. 청크와 벡터 중 **오래된 쪽**을 본다 — 둘 중
    하나만 새것이면 그 색인은 아직 짝이 맞지 않는 상태다."""
    chunks, npy, _ = _idx_paths(index_dir)
    ts = []
    for path in (chunks, npy):
        try:
            ts.append(os.stat(path).st_mtime)
        except OSError:
            pass
    return min(ts) if ts else None


def _index_embed(meta_path: str) -> str:
    try:
        with open(meta_path, encoding="utf-8") as f:
            m = json.load(f)
        p = str(m.get("provider") or "").lower()
        mo = str(m.get("model") or "")
        return "%s/%s" % (p, mo) if p and mo else ""
    except Exception:                                       # noqa: BLE001
        return ""


def _indexed_names(chunks_path: str):
    """색인 안에서 인용되는 매뉴얼 파일 이름(basename). 기록이 없을 때
    새 파일·빠진 파일을 알아내는 유일한 단서다. 읽지 못하면 None —
    모르는 것을 아는 척하지 않는다."""
    names = set()
    try:
        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    return None
                src = rec.get("source") or {}
                nm = src.get("rel_path") or src.get("file") or ""
                nm = os.path.basename(str(nm))
                if nm.lower().endswith(".pdf"):
                    names.add(nm)
    except OSError:
        return None
    return names


# ── 기록 ────────────────────────────────────────────────────
def write_manifest(index_dir=None, manual_dir=None, error_codes=None) -> dict:
    """재생성이 성공한 직후 서버가 부른다. 임시 이름으로 쓰고 바꿔치기
    하는 이유는, 쓰다 죽은 반쪽 기록이 다음 판정을 틀리게 만들기 때문이다."""
    idx = str(index_dir or config.INDEX_DIR)
    rec = {
        "written_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "embed": config.embed_signature(),
        "index": _index_fingerprint(idx),
        "sources": list_sources(manual_dir, error_codes),
    }
    os.makedirs(idx, exist_ok=True)
    tmp = _manifest_path(idx) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _manifest_path(idx))
    return rec


def read_manifest(index_dir=None):
    try:
        with open(_manifest_path(index_dir), encoding="utf-8") as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else None
    except Exception:                                       # noqa: BLE001
        return None


# ── 판정 ────────────────────────────────────────────────────
def index_state(index_dir=None, manual_dir=None, error_codes=None) -> dict:
    """색인이 지금 자료와 맞는지. 화면은 이 값을 그대로 읽어 쓴다."""
    idx = str(index_dir or config.INDEX_DIR)
    chunks, npy, meta = _idx_paths(idx)
    srcs = list_sources(manual_dir, error_codes)
    cur = {s["rel"]: s for s in srcs}
    manuals = [s for s in srcs if s["kind"] == "manual"]

    st = {
        "changed": None,
        "verdict": "알 수 없음",
        "reason": "",
        "basis": "none",
        "basis_label": "",
        "index_built_at": "",
        "index_dir": idx,
        "manual_dir": str(manual_dir or config.MANUAL_DIR),
        "manual_count": len(manuals),
        "sources": {"total": len(srcs), "added": [], "removed": [],
                    "modified": []},
        "embed": {"index": "", "current": config.embed_signature(),
                  "changed": False},
    }

    if not os.path.isfile(chunks) or not os.path.isfile(npy):
        st.update(changed=True, verdict="색인 없음",
                  reason="색인 파일이 없습니다 — 한 번은 만들어야 매뉴얼 "
                         "검색이 됩니다.")
        return st

    built = _built_at(idx)
    if built:
        st["index_built_at"] = dt.datetime.fromtimestamp(built).strftime(
            "%Y-%m-%d %H:%M")

    idx_emb = _index_embed(meta)
    st["embed"]["index"] = idx_emb or "기록 없음"
    st["embed"]["changed"] = bool(idx_emb) and idx_emb != config.embed_signature()

    man = read_manifest(idx)
    if man and man.get("index") == _index_fingerprint(idx):
        # 기록이 이 색인의 것이다 — 내용까지 대조한다.
        st["basis"] = "manifest"
        st["basis_label"] = "내용 대조 (SHA-256)"
        old = {s.get("rel"): s for s in (man.get("sources") or [])}
        st["sources"]["added"] = sorted(set(cur) - set(old))
        st["sources"]["removed"] = sorted(set(old) - set(cur))
        st["sources"]["modified"] = sorted(
            r for r in (set(cur) & set(old))
            if cur[r].get("sha256") != old[r].get("sha256"))
    else:
        # 기록이 없거나 낡았다. 시각으로 견준다.
        st["basis"] = "mtime"
        st["basis_label"] = "시각 대조 (파일 수정 시각)"
        names = _indexed_names(chunks)
        if names is None:
            st.update(changed=None, verdict="알 수 없음",
                      reason="색인 파일을 읽지 못해 대조하지 못했습니다 — "
                             "재생성이 필요한지 알 수 없습니다.")
            return st
        have = {s["name"] for s in manuals}
        # 코드표는 색인 안에서 파일 이름으로 인용되지 않는다(코드 항목의
        # 출처는 매뉴얼 PDF 다). 새 파일·빠진 파일 대조에서는 빼고,
        # 시각 대조에만 참여시킨다.
        st["sources"]["added"] = sorted(
            s["rel"] for s in manuals if s["name"] not in names)
        st["sources"]["removed"] = sorted(names - have)
        if built:
            st["sources"]["modified"] = sorted(
                s["rel"] for s in srcs
                if s["mtime"] > int(built) and s["rel"] not in
                set(st["sources"]["added"]))

    sc = st["sources"]
    bits = []
    if sc["added"]:
        bits.append("새 파일 %d개" % len(sc["added"]))
    if sc["removed"]:
        bits.append("빠진 파일 %d개" % len(sc["removed"]))
    if sc["modified"]:
        bits.append("바뀐 파일 %d개" % len(sc["modified"]))
    if st["embed"]["changed"]:
        bits.append("임베딩 모델이 색인과 다름 (색인 %s · 지금 %s)"
                    % (st["embed"]["index"], st["embed"]["current"]))

    if bits:
        st["changed"] = True
        st["verdict"] = "변경 있음"
        st["reason"] = "재생성이 필요합니다 — " + ", ".join(bits) + "."
    else:
        st["changed"] = False
        st["verdict"] = "변경 없음"
        st["reason"] = ("색인이 지금 자료와 같습니다 — 매뉴얼 %d개 그대로. "
                        "다시 만들어도 결과는 같습니다."
                        % st["manual_count"])
    if st["basis"] == "mtime":
        st["reason"] += (" 파일 수정 시각으로만 본 것입니다 — 시각을 그대로 "
                         "둔 채 내용만 바꾼 경우는 이 기준으로 알 수 "
                         "없습니다.")
    return st


if __name__ == "__main__":
    print(json.dumps(index_state(), ensure_ascii=False, indent=1))
