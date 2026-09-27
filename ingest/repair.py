# -*- coding: utf-8 -*-
"""
자료 반입 수리 보조 — 점검이 짚은 것을 고칠 수 있는 형태로 내놓는다.

원칙 세 가지. 이 모듈이 지키지 않으면 존재 이유가 없다.

  1) **제안과 반영을 가른다.** propose() 는 읽기만 하고, apply() 만 쓴다.
     반영은 사용자가 제안 id 를 골라 보낸 것만, 열쇠 검사를 통과한
     요청만 수행한다. 자동으로 전부 고치는 모드는 만들지 않는다 —
     어느 쪽이 맞는지는 데이터 주인이 아는 일이다.
  2) **자동 수정은 정답이 계산되는 종류만.** 채널 중복(빈 채널 재배정),
     헤더 오기(표준 24종과의 근사 일치)가 그것이다. 태그 오타 추정처럼
     문서 사이 의미가 걸린 것은 후보만 보이고 auto=False 로 둔다.
  3) **반영 전 .prev 보존, 반영 후 재점검.** 수리안이 점검을 통과하는지가
     판정 기준이다 — 고쳤다고 말하지 않고 재점검 수치로 보인다.

apply() 는 클라이언트가 보낸 내용(before/after)을 믿지 않는다. 제안을
서버에서 새로 계산해 id 가 일치하는 것만 반영한다. 화면과 파일 사이에
시간이 흐르는 동안 자료가 바뀌었으면 id 가 달라져 그 제안은 건너뛴다.

0 은 유효한 채널 번호다. 빈 값 검사는 `is None / == ""` 로만 한다 —
`or` 로 접으면 CH=0 이 사라진다 (패치 27에서 실제로 겪은 버그).
"""
import os
import shutil
import difflib

import config

# 채널 재배정 탐색 상한. AI/AO 카드는 8~16채널이 보통이라 0~15에서
# 빈 자리를 찾고, 없으면 31까지 본다. 그래도 없으면 자동 수정을
# 포기하고 auto=False 로 내린다 — 지어내지 않는다.
_CH_MAX_PRIMARY = 15
_CH_MAX_EXTENDED = 31

_NEED_COLS = ("TAG", "PLC", "PN(DP)", "RACK", "SLOT", "CH")


def _load_sheet(io_path):
    """워크북·시트·헤더행·열지도. 쓰기 가능 모드로 연다(호출자가 닫는다)."""
    import openpyxl
    wb = openpyxl.load_workbook(io_path)
    from ingest.io_standard import pick_sheet
    _ps = pick_sheet(wb.sheetnames)
    ws = wb[_ps] if _ps else wb.active
    hdr_row = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=10,
                                         values_only=True), 1):
        cells = [str(c).strip() for c in row if c not in (None, "")]
        if len(cells) >= 3 and any("TAG" in c.upper() and len(c) <= 20
                                   for c in cells):
            hdr_row = i
            break
    if hdr_row is None:
        wb.close()
        raise ValueError("IO List 에서 헤더 행(TAG 열)을 찾지 못했습니다")
    colmap = {}
    for j, cell in enumerate(ws[hdr_row], 1):
        name = str(cell.value).strip() if cell.value is not None else ""
        if name:
            colmap[name] = j
    # L1 표준양식 — 채널 검사가 보는 열을 내부 이름으로 가리킨다.
    # L1 의 'PLC' 는 제어 유형(DI·COM·PID)이라 그대로 두면 카드가 제어
    # 유형별로 쪼개져 채널 중복을 못 본다. CPU 가 제어기 이름이다.
    from ingest.io_standard import is_l1_header
    if is_l1_header(list(colmap)):
        colmap["__L1__"] = 0
        if "CPU" in colmap:
            colmap["PLC"] = colmap["CPU"]
        if "PN" in colmap:
            colmap["PN(DP)"] = colmap["PN"]
    return wb, ws, hdr_row, colmap


def _cell(row_vals, colmap, name):
    j = colmap.get(name)
    if not j:
        return None
    v = row_vals[j - 1]
    return None if v is None or str(v).strip() == "" else v


def _ch_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# ── 1. 채널 중복 ─────────────────────────────────────────────────

def analyze_channels(io_path=None):
    """같은 카드(PLC·PN·RACK·SLOT)의 같은 CH 를 쓰는 태그들.

    반환: (dups, used)
      dups: [{key, ch, tags(순서 보존), rows{tag: 행번호}}]
      used: {slot_key: set(int ch)}
    """
    io_path = io_path or str(config.IO_LIST)
    wb, ws, hdr_row, colmap = _load_sheet(io_path)
    try:
        # L1 양식에는 RACK 열이 없다 — PN 하나가 랙 하나다
        need = [c for c in _NEED_COLS
                if not (c == "RACK" and "__L1__" in colmap)]
        missing = [c for c in need if c not in colmap]
        if missing:
            return [], {}, "IO List 에 %s 열이 없어 채널 검사를 건너뜁니다" \
                % ", ".join(missing)
        groups, used, rows_of = {}, {}, {}
        for i, row in enumerate(ws.iter_rows(min_row=hdr_row + 1,
                                             values_only=True), hdr_row + 1):
            tag = _cell(row, colmap, "TAG")
            ch = _ch_int(_cell(row, colmap, "CH"))
            if tag is None or ch is None:
                continue
            slot = tuple(str(_cell(row, colmap, c) or "")
                         for c in ("PLC", "PN(DP)", "RACK", "SLOT"))
            used.setdefault(slot, set()).add(ch)
            groups.setdefault(slot + (ch,), []).append(str(tag))
            rows_of[str(tag)] = i
        dups = []
        for key, tags in groups.items():
            if len(tags) > 1:
                dups.append({"slot": key[:4], "ch": key[4], "tags": tags,
                             "rows": {t: rows_of[t] for t in tags}})
        dups.sort(key=lambda d: (d["slot"], d["ch"]))
        return dups, used, None
    finally:
        wb.close()


def _free_channel(used_in_slot, planned):
    taken = set(used_in_slot) | set(planned)
    for hi in (_CH_MAX_PRIMARY, _CH_MAX_EXTENDED):
        for c in range(hi + 1):
            if c not in taken:
                return c
    return None


def _channel_proposals(io_path=None):
    dups, used, note = analyze_channels(io_path)
    out = []
    if note:
        out.append({"id": "ch:skip", "kind": "channel_dup", "auto": False,
                    "file": os.path.basename(str(io_path or config.IO_LIST)),
                    "before": "", "after": "", "rationale": note})
        return out
    planned = {}                      # slot → 이번 계획에서 새로 쓰는 ch
    for d in dups:
        keep, movers = d["tags"][0], d["tags"][1:]
        for t in movers:
            slot = d["slot"]
            new_ch = _free_channel(used.get(slot, set()),
                                   planned.get(slot, set()))
            slot_str = "/".join(slot)
            pid = "ch:%s/CH%d:%s" % (slot_str, d["ch"], t)
            if new_ch is None:
                out.append({
                    "id": pid, "kind": "channel_dup", "auto": False,
                    "file": os.path.basename(str(io_path or config.IO_LIST)),
                    "before": "%s CH%d ← %s (유지: %s)" % (slot_str, d["ch"],
                                                           t, keep),
                    "after": "",
                    "rationale": "빈 채널이 없어 자동 재배정 불가 — 수동 확인",
                })
                continue
            planned.setdefault(slot, set()).add(new_ch)
            out.append({
                "id": pid, "kind": "channel_dup", "auto": True,
                "file": os.path.basename(str(io_path or config.IO_LIST)),
                "tag": t, "row": d["rows"][t], "new_ch": new_ch,
                "before": "%s CH%d 에 %s · %s 동거" % (slot_str, d["ch"],
                                                      keep, t),
                "after": "%s → CH%d (같은 슬롯의 빈 채널)" % (t, new_ch),
                "rationale": "같은 카드·같은 채널에 두 점은 배선 불가. "
                             "먼저 적힌 %s 를 유지하고 %s 를 옮깁니다. "
                             "ADD 열은 바꾸지 않으므로 주소는 별도 확인."
                             % (keep, t),
            })
    return out


# ── 2. 헤더 오기 ─────────────────────────────────────────────────

def _header_proposals(io_path=None):
    io_path = io_path or str(config.IO_LIST)
    try:
        from tools.make_io_list import STANDARD_ORDER
    except Exception:                                       # noqa: BLE001
        return []
    wb, ws, hdr_row, colmap = _load_sheet(io_path)
    wb.close()
    if "__L1__" in colmap:
        # L1 표준양식은 L1 열 순서와 대조한다. 24종과 대조하면 표준 열이
        # 전부 '없음' 으로 나오고, 근사 일치가 L1 열 이름을 24종 이름으로
        # 바꾸자고 제안한다 — 멀쩡한 양식을 망가뜨리는 수리안이다.
        from ingest.io_standard import L1_ORDER as STANDARD_ORDER
        std_label = "L1 표준양식"
        # 별칭(PLC→CPU 등)을 뺀 원래 머리글로 다시 짠다
        colmap = {}
        for j, cell in enumerate(ws[hdr_row], 1):
            name = str(cell.value).strip() if cell.value is not None else ""
            if name:
                colmap[name] = j
    else:
        std_label = "표준 24종"
    got = list(colmap.keys())
    miss = [c for c in STANDARD_ORDER if c not in got]
    extra = [c for c in got if c not in STANDARD_ORDER]
    out = []
    for x in extra:
        cand = difflib.get_close_matches(x, miss, n=1, cutoff=0.75)
        if cand:
            y = cand[0]
            out.append({
                "id": "hdr:%s→%s" % (x, y), "kind": "header_rename",
                "auto": True, "file": os.path.basename(io_path),
                "col": colmap[x], "row": hdr_row, "old": x, "new": y,
                "before": "열 이름 '%s' — %s에 없음" % (x, std_label),
                "after": "'%s' 로 변경 (표준의 '%s' 와 근사 일치)" % (y, y),
                "rationale": "표준 열만 파서가 읽습니다. 오기로 보이면 "
                             "표준 이름으로 되돌립니다.",
            })
            miss.remove(y)
    for m in miss:
        out.append({"id": "hdr-miss:%s" % m, "kind": "header_missing",
                    "auto": False, "file": os.path.basename(io_path),
                    "before": "표준 열 '%s' 없음 — 근사 후보도 없음" % m,
                    "after": "",
                    "rationale": "원본 양식 확인 필요. 지어서 채우지 않습니다."})
    return out


# ── 3. 문서 사이 태그 (제안만, auto=False) ───────────────────────

def _tag_proposals():
    out = []
    try:
        from ingest import tag_registry as TR
        cc = TR.cross_check()
        io_tags = sorted({str(t) for t in (cc.get("io_tags") or [])}) \
            if cc.get("io_tags") else None
        if io_tags is None:
            from ingest.lists import load_points
            pts = load_points(config.IO_LIST,
                              getattr(config, "INSTRUMENT_SPECS", None)
                              or getattr(config, "INSTRUMENT_SPEC", None),
                              None, getattr(config, "TB_LIST", None))
            io_tags = sorted(pts.keys())
        for kind_ko, items in (cc.get("findings") or {}).items():
            for f in items[:20]:
                tag = str(f.get("tag") or "")
                if not tag:
                    continue
                cand = difflib.get_close_matches(tag, io_tags, n=2,
                                                 cutoff=0.8)
                out.append({
                    "id": "tag:%s:%s" % (kind_ko, tag), "kind": "tag_mismatch",
                    "auto": False,
                    "file": str(f.get("in") or ""),
                    "before": "%s — %s" % (kind_ko, tag),
                    "after": ("근사 후보: " + ", ".join(cand)) if cand
                             else "근사 후보 없음",
                    "rationale": "문서 사이 태그 수정은 의미가 걸려 있어 "
                                 "자동 반영하지 않습니다. 원본에서 직접 "
                                 "확인하십시오.",
                })
    except Exception as e:                                  # noqa: BLE001
        out.append({"id": "tag:error", "kind": "tag_mismatch", "auto": False,
                    "file": "", "before": "태그 대조 실패", "after": "",
                    "rationale": "%s: %s" % (type(e).__name__, str(e)[:60])})
    return out


# ── 묶음 ─────────────────────────────────────────────────────────

def propose(io_path=None, include_cross=True):
    """수리안 전체. 읽기만 한다."""
    props = _channel_proposals(io_path) + _header_proposals(io_path)
    if include_cross and io_path is None:
        props += _tag_proposals()
    auto = [p for p in props if p.get("auto")]
    return {"proposals": props,
            "counts": {"total": len(props), "auto": len(auto),
                       "manual": len(props) - len(auto)}}


def apply(ids, io_path=None):
    """선택된 자동 수리안만 반영. 제안은 서버에서 새로 계산한 것 기준.

    반환에 before/after 재점검 수치를 실어, 고쳐졌는지를 말이 아니라
    수치로 보인다.
    """
    io_path = str(io_path or config.IO_LIST)
    plan = propose(io_path=io_path, include_cross=False)
    by_id = {p["id"]: p for p in plan["proposals"]}
    todo, skipped = [], []
    for pid in ids:
        p = by_id.get(pid)
        if p is None:
            skipped.append({"id": pid, "why": "제안이 더 이상 유효하지 않음 "
                                              "(자료가 바뀌었을 수 있음)"})
        elif not p.get("auto"):
            skipped.append({"id": pid, "why": "자동 반영 불가 항목"})
        else:
            todo.append(p)
    before = {"channel_dup": len(analyze_channels(io_path)[0]),
              "selected": len(ids)}
    if not todo:
        return {"applied": [], "skipped": skipped, "before": before,
                "after": before, "prev": None}

    # 반영 전 보존 — 덮어쓴 파일의 이전 판은 .prev 로 남는다 (반입 관례)
    prev = io_path + ".prev"
    shutil.copy2(io_path, prev)

    wb, ws, hdr_row, colmap = _load_sheet(io_path)
    try:
        for p in todo:
            if p["kind"] == "channel_dup":
                ws.cell(row=p["row"], column=colmap["CH"], value=p["new_ch"])
            elif p["kind"] == "header_rename":
                ws.cell(row=p["row"], column=p["col"], value=p["new"])
        wb.save(io_path)
    finally:
        wb.close()

    after = {"channel_dup": len(analyze_channels(io_path)[0])}
    return {"applied": [p["id"] for p in todo], "skipped": skipped,
            "before": before, "after": after,
            "prev": os.path.basename(prev)}
