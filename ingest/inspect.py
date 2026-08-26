# -*- coding: utf-8 -*-
"""
자료 반입 직후 점검.

이 화면의 본체는 파일을 받는 것이 아니라 **받은 직후의 점검**이다.
지금까지 찾은 결함 여섯 종은 모두 자료를 넣는 시점에 드러났고, 전부
"답이 안 나오는" 형태가 아니라 "그럴듯한 답이 나오되 틀린" 형태였다.
그래서 반입 즉시 세 가지를 사람 앞에 놓는다.

  1) 파일마다 몇 행을 읽었고 무엇을 인식하지 못했는지
  2) 문서 사이의 태그가 얼마나 맞물리는지 (tag_registry 재사용)
  3) 매뉴얼이 어느 기종과 연결되었는지 / 연결 안 된 기종은 무엇인지

판정하지 않는다. 어느 쪽이 맞는지는 데이터 주인이 아는 일이고, 여기는
"두 문서가 다르다" "이 열은 못 읽었다" 는 사실만 보인다.
"""
import os
import re
import glob

import config


def _xlsx_rows(path):
    """엑셀 첫 시트의 (헤더, 데이터 행 수, 전체 행). 실패 시 None."""
    try:
        import openpyxl
        # read_only 워크북은 닫지 않으면 파일 핸들을 쥔 채 남는다.
        # Windows 에서는 그 핸들 때문에 같은 파일의 이름 변경·삭제가
        # PermissionError 로 막힌다 — 점검이 파일 관리를 잠그는 셈이다.
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            rows = list(wb.active.iter_rows(values_only=True))
        finally:
            wb.close()
    except Exception as e:                                  # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:80])}
    def has_tag(r):
        # 헤더의 TAG 셀은 짧다. "…TAG 로 조인합니다" 같은 안내 문장이
        # 걸리지 않도록 셀 길이와 행의 열 수를 함께 본다.
        cells = [str(c).strip() for c in r if c not in (None, "")]
        return (len(cells) >= 3
                and any("TAG" in c.upper() and len(c) <= 20 for c in cells))
    hi = next((i for i, r in enumerate(rows) if r and has_tag(r)), None)
    if hi is None:
        # TB 리스트처럼 TAG 열 자체가 없는 양식도 있다. 결함이 아니라
        # 다른 구조이므로, 행 수만 세고 "구조 미인식" 으로 표시한다.
        data = [r for r in rows if r and any(c not in (None, "") for c in r)]
        return {"free_form": True, "rows": len(data),
                "note": "TAG 열이 없는 양식 — 행 수만 셌습니다"}
    hdr = [str(c).strip() for c in rows[hi] if c not in (None, "")]
    data = [r for r in rows[hi + 1:]
            if r and any(c not in (None, "") for c in r)]
    return {"header_row": hi + 1, "columns": hdr, "rows": len(data)}


def _inspect_io():
    """IO List — 표준 24종 헤더 대조까지."""
    path = config.IO_LIST
    if not path or not os.path.isfile(path):
        return {"file": "IO_LIST.xlsx", "present": False}
    out = {"file": os.path.basename(path), "present": True}
    out.update(_xlsx_rows(path))
    if "columns" in out:
        try:
            from tools.make_io_list import STANDARD_ORDER
            got = out["columns"]
            front = got[:len(STANDARD_ORDER)]
            miss = [c for c in STANDARD_ORDER if c not in got]
            extra = [c for c in got if c not in STANDARD_ORDER]
            out["standard"] = {
                "expected": len(STANDARD_ORDER),
                "matched": len(STANDARD_ORDER) - len(miss),
                "missing": miss,
                "unrecognized": extra,
                "order_ok": front == STANDARD_ORDER,
            }
        except Exception:                                   # noqa: BLE001
            pass
    return out


def _inspect_plain(path, label):
    # 계기 리스트는 설정상 여러 파일일 수 있다(list). 첫 파일만 본다 —
    # 데모·실물 모두 한 파일 구성이고, 여럿이면 파일명에 드러난다.
    if isinstance(path, (list, tuple)):
        path = path[0] if path else None
    path = str(path) if path else None
    if not path or not os.path.isfile(path):
        return {"file": label, "present": False}
    out = {"file": os.path.basename(path), "present": True}
    out.update(_xlsx_rows(path))
    return out


def _inspect_interlock():
    """인터락 — 파싱 성공/미파싱을 그대로 보고한다. 미파싱은 결함이
    아니라 보존 대상이다. 임의로 해석해 넣는 순간 안전 로직이 된다."""
    from retrieval.interlock_index import InterlockIndex
    d = getattr(config, "INTERLOCK_DIR", None)
    files = sorted(glob.glob(os.path.join(d, "*.xlsx"))) if d and os.path.isdir(d) else []
    if not files:
        return {"present": False, "files": []}
    try:
        idx = InterlockIndex()
        items = getattr(idx, "items", None) or []
        unparsed = [it for it in items
                    if not it.get("conds") and it.get("raw")]
        return {"present": True,
                "files": [os.path.basename(f) for f in files],
                "rules": len(items),
                "unparsed": len(unparsed),
                "outputs": len(getattr(idx, "outputs", {}) or {}),
                "input_tags": len(idx.input_tags())
                              if hasattr(idx, "input_tags") else None}
    except Exception as e:                                  # noqa: BLE001
        return {"present": True,
                "files": [os.path.basename(f) for f in files],
                "error": "%s: %s" % (type(e).__name__, str(e)[:80])}


def _inspect_manuals():
    """매뉴얼 ↔ 기종 연결. 연결 안 된 기종이 곧 abstain 이 나올 자리다."""
    mdir = getattr(config, "MANUAL_DIR", None)
    pdfs = sorted(glob.glob(os.path.join(mdir, "*.pdf"))) if mdir and os.path.isdir(mdir) else []
    names = [os.path.basename(p) for p in pdfs]

    # 기종(MODEL)별로 매뉴얼 파일과 이어지는지. 서버와 같은 로더를 쓴다.
    devices = {}
    try:
        from api.server import load_instruments
        for tag, r in load_instruments().items():
            m = str(r.get("MODEL") or "").strip()
            if m:
                devices.setdefault(m, []).append(tag)
    except Exception:                                       # noqa: BLE001
        pass

    # 파일마다 색인기가 붙일 device 키를 그대로 계산해 둔다.
    from ingest.chunker import _guess_device
    file_dev = {n: _guess_device(n, n) for n in names}

    def matched(model):
        key = re.sub(r"[^a-z0-9]", "", model.lower())
        for n, dev in file_dev.items():
            dv = re.sub(r"[^a-z0-9]", "", str(dev).lower())
            if key and dv and (key in dv or dv in key):
                return n
        return ""

    link = []
    for model, tags in sorted(devices.items()):
        link.append({"model": model, "tags": len(tags),
                     "manual": matched(model)})

    # 역방향 — 어느 기종과도 이어지지 않는 매뉴얼 파일.
    # 기종 쪽에서만 보면 "매뉴얼 없는 기종" 은 잡아도 "기종 없는
    # 매뉴얼" 은 조용히 지나간다. 잘못 올린 파일이 그렇게 숨는다.
    used = {x["manual"] for x in link if x["manual"]}
    orphan = [n for n in names if n not in used]

    return {"present": bool(pdfs), "files": names,
            "models": link,
            "unlinked": [x["model"] for x in link if not x["manual"]],
            "orphan_files": orphan}


def inspect_dataset():
    """반입 점검 리포트 전체. 판정 없이 사실만."""
    report = {
        "data_dir": str(config.DATA_DIR),
        "io_list": _inspect_io(),
        "instrument_list": _inspect_plain(
            getattr(config, "INSTRUMENT_SPECS", None)
            or getattr(config, "INSTRUMENT_SPEC", None), "INSTRUMENT_LIST.xlsx"),
        "tb_list": _inspect_plain(getattr(config, "TB_LIST", None), "TB_LIST.xlsx"),
        "interlock": _inspect_interlock(),
        "manuals": _inspect_manuals(),
    }
    # 문서 사이 태그 맞물림 — 기존 대조기를 그대로 쓴다.
    try:
        from ingest import tag_registry as TR
        cc = TR.cross_check()
        report["cross"] = {
            "counts": cc.get("counts", {}),
            "finding_counts": cc.get("finding_counts", {}),
            "findings": {k: v[:8] for k, v in (cc.get("findings") or {}).items()},
            "total": cc.get("total", 0),
            "note": cc.get("note", ""),
        }
    except Exception as e:                                  # noqa: BLE001
        report["cross"] = {"error": "%s: %s" % (type(e).__name__, str(e)[:80])}
    return report
