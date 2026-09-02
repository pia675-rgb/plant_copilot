#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 서버 — React UI용 백엔드 (v1 기능 포함)

실행:
    uvicorn api.server:app --reload --port 8000
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

from pathlib import Path
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from openpyxl import load_workbook
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from graph.app_graph import Copilot2  # noqa: E402
from retrieval.pipeline import Retriever  # noqa: E402
from retrieval.interlock_index import InterlockIndex  # noqa: E402
from retrieval.panel_index import PanelIndex  # noqa: E402

# 기본 모드. lexical 은 한글 질의를 구조적으로 못 푼다 — 시연 기본값으로 쓰면
# 가장 약한 구성을 심사위원에게 먼저 보여주게 된다. 환경변수로 덮을 수 있다.
DEFAULT_MODE = os.environ.get("COPILOT_UI_MODE", "hybrid")

app = FastAPI(title="Plant Maintenance Copilot v2", version="2.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _prewarm_llm():
    """모델을 미리 올려둔다. 첫 조회가 로딩 시간을 물지 않게 한다.

    별도 스레드로 돌린다 — 예열이 끝날 때까지 서버 기동을 붙잡으면
    화면이 늦게 뜬다. COPILOT_PREWARM=0 으로 끌 수 있다.
    """
    if os.environ.get("COPILOT_PREWARM", "1").strip() == "0":
        return
    import threading
    from graph import advisor

    def run():
        ok, msg = advisor.prewarm()
        print("[prewarm] %s" % msg)

    threading.Thread(target=run, daemon=True).start()

# ── 싱글톤 ──────────────────────────────────────────────────
_retrievers: Dict[str, Retriever] = {}
_copilots: Dict[str, Copilot2] = {}
_interlock: Optional[InterlockIndex] = None
_panel: Optional[PanelIndex] = None
_panel_error: Optional[str] = None
_instruments: Optional[Dict[str, dict]] = None
_history: Optional[List[dict]] = None
_drawings: Optional[Dict[str, list]] = None


def get_retriever(mode: str = DEFAULT_MODE) -> Retriever:
    if mode not in _retrievers:
        _retrievers[mode] = Retriever(mode=mode)
    return _retrievers[mode]


def get_copilot(mode: str = DEFAULT_MODE) -> Copilot2:
    if mode not in _copilots:
        _copilots[mode] = Copilot2(mode=mode)
    return _copilots[mode]


def get_interlock() -> InterlockIndex:
    global _interlock
    if _interlock is None:
        _interlock = InterlockIndex()
    return _interlock


def get_panel() -> Optional[PanelIndex]:
    """
    계기 리스트의 PANEL 열 + 배치 CSV. 인터락 인덱스를 넘겨 재사용한다.

    실패하면 조용히 None 을 돌려주는 대신 사유를 남기고 /api/health 에
    드러낸다. 판넬 조회가 통째로 안 뜨는데 이유를 알 수 없는 상태가
    이 프로젝트에서 반복해서 나온 고장 유형이다.
    """
    global _panel, _panel_error
    if _panel is None and _panel_error is None:
        try:
            _panel = PanelIndex(interlock=get_interlock())
        except Exception as e:                              # noqa: BLE001
            _panel_error = str(e)
            print("[panel] 적재 실패:", e)
    return _panel


def load_instruments() -> Dict[str, dict]:
    """
    P&ID TAG 기준 기기 딕셔너리.

    · 알람·매뉴얼·태그 목록·계기 상세 → 이 함수 (키 = P&ID TAG)
    · 판넬/카드/채널 배선 → retrieval.panel_index 가 load_points(IO TAG) 사용
    """
    global _instruments
    if _instruments is not None:
        return _instruments
    path = config.INSTRUMENTS
    if not path or not os.path.isfile(path):
        print("[api] IO List 없음:", path)
        _instruments = {}
        return _instruments
    try:
        from ingest.lists import load_pid_devices
        devices = load_pid_devices(
            path,
            getattr(config, "INSTRUMENT_SPECS", None) or getattr(config, "INSTRUMENT_SPEC", None),
            None,
            getattr(config, "TB_LIST", None),
        )
        clean = {}
        for pid, r in devices.items():
            row = {}
            for k, v in r.items():
                if k in ("io_tags", "io_points"):
                    row[k] = v
                else:
                    row[k] = "" if v is None else v
            clean[pid] = row
        _instruments = clean
        n_io = sum(len(r.get("io_tags") or []) for r in clean.values())
        print("[api] P&ID 기기 %d건 / IO 점 %d건 (%s)"
              % (len(_instruments), n_io, path))
        return _instruments
    except Exception as e:
        print("[api] IO List 로드 실패:", e)
        _instruments = {}
        return _instruments


_io_points = None


def load_io_points() -> Dict[str, dict]:
    """IO TAG → 배선 레코드 (알람 선택·판넬용)."""
    global _io_points
    if _io_points is not None:
        return _io_points
    path = config.INSTRUMENTS
    if not path or not os.path.isfile(path):
        _io_points = {}
        return _io_points
    try:
        from ingest.lists import load_points
        pts = load_points(
            path,
            getattr(config, "INSTRUMENT_SPECS", None) or getattr(config, "INSTRUMENT_SPEC", None),
            None,
            getattr(config, "TB_LIST", None),
        )
        clean = {}
        for tag, r in pts.items():
            row = {k: ("" if v is None else v) for k, v in r.items()
                   if k not in ("io_tags", "io_points")}
            # bool 유지
            if r.get("_spare"):
                row["_spare"] = True
            clean[tag] = row
        _io_points = clean
        print("[api] IO 점 %d건" % len(_io_points))
        return _io_points
    except Exception as e:
        print("[api] IO 점 로드 실패:", e)
        _io_points = {}
        return _io_points


def resolve_to_pid(tag: str):
    """IO TAG 또는 P&ID → (pid_tag, io_tag|None).
    도면·매뉴얼 검색은 항상 pid_tag 사용."""
    tag = (tag or "").strip()
    if not tag:
        return "", None
    io = load_io_points().get(tag)
    if io:
        pid = (io.get("P&ID TAG") or tag).strip()
        return pid, tag
    inst = load_instruments().get(tag)
    if inst:
        return tag, None
    for pid, r in load_instruments().items():
        if tag in (r.get("io_tags") or []):
            return pid, tag
    return tag, None


def load_history() -> List[dict]:
    global _history
    if _history is not None:
        return _history
    path = config.HISTORY
    if not os.path.exists(path):
        _history = []
        return _history
    with open(path, encoding="utf-8") as f:
        _history = json.load(f)
    return _history


def save_history(rows: List[dict]):
    global _history
    path = config.HISTORY
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    _history = rows



# 인터락 태그 적재 중 삼킨 오류. /api/health 로 드러낸다.
_interlock_tag_error = None


def load_drawings() -> Dict[str, list]:
    global _drawings
    if _drawings is not None:
        return _drawings
    path = config.DRAWINGS_INDEX
    out: Dict[str, list] = {}
    if not os.path.exists(path):
        _drawings = out
        return out
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            tag = (r.get("TAG") or "").strip()
            if not tag:
                continue
            out.setdefault(tag, []).append({
                "type": r.get("TYPE") or "",
                "sheet_no": r.get("SHEET_NO") or "",
                "file": r.get("FILE") or "",
                "page": int(r["PAGE"]) if r.get("PAGE") else 0,
                "find": r.get("FIND") or tag,
            })
    for tag in out:
        out[tag].sort(key=lambda d: {"P&ID": 0, "SCHEMATIC": 1, "OUTLINE": 2,
                                     "ARRANGEMENT": 3}.get(d["type"], 9))
    _drawings = out
    return out


def load_output_tags() -> Dict[str, dict]:
    """
    출력 태그: 인터락이 동작시키는 대상.

    별도 output list 문서는 없다. IO List(DO/AO 점) + 계기 리스트 +
    부속 데이터를 합친 결과에서 인터락 출력에 해당하는 태그를 고른다.
    """
    from retrieval.interlock_index import load_outputs
    try:
        return load_outputs()
    except Exception as e:                                  # noqa: BLE001
        print("[api] 출력 태그 로드 실패:", e)
        return {}


# ── 모델 ────────────────────────────────────────────────────
class SearchRequest(BaseModel):
    tag: Optional[str] = None
    alarm: str = ""
    code: str = ""
    mode: str = Field(default=DEFAULT_MODE, pattern="^(lexical|hybrid|full)$")


class DiagnoseRequest(BaseModel):
    tag: Optional[str] = None
    alarm: str = ""
    code: str = ""
    mode: str = Field(default=DEFAULT_MODE, pattern="^(lexical|hybrid|full)$")


class InterlockRequest(BaseModel):
    tag: str
    action: Optional[str] = None
    as_input: bool = False


class FeedbackRequest(BaseModel):
    tag: str
    symptom: str = ""
    root_cause: str
    action_taken: str
    code_ref: str = ""
    manual_match: str = "부분일치"  # 일치 / 부분일치 / 불일치
    duration_min: int = 0
    parts: str = "-"
    tech: str = ""


class ChatContext(BaseModel):
    """화면에 떠 있는 조회 결과. 후속 질문에 답하려면 이것이 필요하다.

    알람 조회 근거(evidence)만 담던 것이 패치 29 에서 문제가 됐다.
    인터락을 조회한 뒤 후속 질문을 하면 챗봇이 직전 알람 근거로 답을
    만들어, 사용자가 보는 화면과 다른 주제의 답이 나왔다. 그래서 어느
    탭의 결과인지(tab)와 인터락 응답 원본(interlock)을 함께 받는다.
    """
    tag: Optional[str] = None
    alarm: str = ""
    decision: Optional[str] = None
    grade: Optional[float] = None
    evidence: List[dict] = []
    steps: List[dict] = []
    # 화면이 어느 탭인지. 후속 질문을 어느 결과로 답할지 가른다.
    tab: Optional[str] = None
    # 인터락 조회 응답 그대로. 서술은 규칙으로 하며 LLM 을 쓰지 않는다.
    interlock: Optional[dict] = None


class ChatRequest(BaseModel):
    message: str
    tag: str = ""
    tab: str = "alarm"
    use_llm: bool = True
    # 자유 모드. 규칙·근거 경로가 처리하지 못한 입력에 한해 모델이
    # 자유롭게 답한다. 조회 명령은 모드와 무관하게 규칙이 먼저 잡는다.
    free: bool = False
    # 화면에 떠 있는 조회 결과. 후속 질문에 답하려면 필요하다.
    context: Optional[ChatContext] = None


class ReportRequest(BaseModel):
    tag: str
    alarm: str = ""
    code: str = ""
    mode: str = DEFAULT_MODE
    tech: str = ""
    confirmed_cause: str = ""
    final_action: str = ""
    parts: str = "-"
    duration_min: Optional[int] = None
    # 화면이 이미 만든 조치 순서. 넘어오면 그대로 쓴다 — 리포트는 즉시
    # 나와야 하므로 여기서 LLM 을 다시 부르지 않는다. 안 넘어오면
    # 아래에서 규칙으로 만든다.
    steps: Optional[List[str]] = None


class AdviceRequest(BaseModel):
    tag: Optional[str] = None
    alarm: str = ""
    code: str = ""
    mode: str = DEFAULT_MODE
    # 기본은 LLM 조치 생성. True 를 주면 근거 나열 템플릿만 쓴다.
    mock: bool = False
    # 자유 모드. True 면 근거를 찾은 조회에도 모델 추측을 덧붙인다.
    # 추측이 steps·4D 리포트에 섞이지 않는 것은 모드와 무관하게 유지된다.
    free: bool = False


# ── 엔드포인트 ──────────────────────────────────────────────
@app.get("/api/health")
def health():
    """
    강등 여부를 여기서 드러낸다. 시연 중 Ollama 가 안 떠 있으면 UI 는
    'hybrid' 라고 표시하면서 실제로는 렉시컬로 도는데, 그 상태를 모르고
    "왜 한글이 안 먹지" 를 무대에서 디버깅하게 된다.
    """
    info = {"status": "ok", "version": "2.2", "default_mode": DEFAULT_MODE}
    try:
        r = get_retriever(DEFAULT_MODE)
        info["effective_mode"] = r.effective_mode
        info["degraded"] = r.degraded
        if r.degraded:
            info["degrade_detail"] = r.degrade_detail()
        info["label"] = r.label()
        if _interlock_tag_error:
            info["interlock_tag_error"] = _interlock_tag_error
        known_tags()
        if _known_tags_error:
            info["tag_index_error"] = _known_tags_error
        info["known_tags"] = len(known_tags())
        px = get_panel()
        if _panel_error:
            info["panel_index_error"] = _panel_error
        elif px is not None:
            info["panels"] = len(px.panels())
            info["arrangement_pdf"] = os.path.exists(config.ARRANGEMENT_PDF)
            if px.unlocated:
                info["panels_unlocated"] = px.unlocated
    except Exception as e:                                  # noqa: BLE001
        info["status"] = "degraded"
        info["error"] = str(e)
    return info


@app.get("/api/tags")
def list_tags(system: Optional[str] = None, q: Optional[str] = None,
              kind: Optional[str] = None):
    """kind=instrument|output|all(default).

    · instrument (알람) : **IO TAG** — DI/AI 입력점 (트립·상태·계측)
    · output (인터락)  : **P&ID TAG** — DO/AO 가 있는 출력 장비
    도면·매뉴얼은 항상 pid_tag 로 조회.
    """
    rows = []

    def _is_do_ao(io_type: str) -> bool:
        t = (io_type or "").strip().upper()
        return bool(t) and ("DO" in t or "AO" in t)

    def _is_di_ai(io_type: str) -> bool:
        t = (io_type or "").strip().upper()
        return bool(t) and ("DI" in t or "AI" in t)

    def _looks_like_io_tag(t: str) -> bool:
        import re as _re
        return bool(_re.match(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$", (t or "").upper()))

    # ── 알람용: IO TAG (DI/AI) ──────────────────────────────
    if kind in (None, "all", "instrument"):
        for tag, r in sorted(load_io_points().items()):
            if r.get("_spare"):
                continue
            iot = str(r.get("IO TYPE") or "")
            if _is_do_ao(iot):
                continue
            if iot and not _is_di_ai(iot):
                continue
            if not iot:
                continue
            pid = (r.get("P&ID TAG") or tag)
            svc = r.get("DESCRIPTION") or r.get("SERVICE") or ""
            if q:
                hay = " ".join([tag, pid, svc, iot]).lower()
                if q.lower() not in hay:
                    continue
            rows.append({
                "tag": tag,
                "pid_tag": pid,
                "service": svc,
                "maker": r.get("MAKER") or "",
                "model": r.get("MODEL") or r.get("TYPE") or "",
                "signal": r.get("SIGNAL") or iot,
                "io_type": iot,
                "kind": "instrument",
                "io_count": 1,
            })

    # ── 인터락용: P&ID 출력 장비 ────────────────────────────
    if kind in (None, "all", "output"):
        for tag, r in sorted(load_instruments().items()):
            types = [str(r.get("IO TYPE") or "")]
            for p in (r.get("io_points") or []):
                types.append(str(p.get("io_type") or ""))
            is_out = any(_is_do_ao(t) for t in types)
            if not is_out:
                continue
            if _looks_like_io_tag(tag) and "-" not in tag.split("_")[0]:
                continue
            if q:
                hay = " ".join(str(x) for x in [
                    tag, r.get("SERVICE"), r.get("MODEL"),
                    " ".join(r.get("io_tags") or []),
                ]).lower()
                if q.lower() not in hay:
                    continue
            rows.append({
                "tag": tag,
                "pid_tag": r.get("P&ID TAG") or tag,
                "service": r.get("SERVICE") or "",
                "maker": r.get("MAKER") or "",
                "model": r.get("MODEL") or r.get("TYPE") or "",
                "signal": r.get("SIGNAL") or "",
                "kind": "output",
                "io_count": len(r.get("io_tags") or []),
            })

    # ── 인터락 입력 표시 ────────────────────────────────────
    #
    # 화면에서 '입력 태그 기준 조회' 를 켜면 묻는 대상이 출력 기기가
    # 아니라 입력 계기로 바뀐다. 그때 무엇을 고를 수 있는지는 태그의
    # 종류(계기/출력)가 아니라 **인터락 조건에 실제로 등장하는가**로
    # 정해진다. 종류로 짐작하면 두 방향으로 틀린다 — 조건에는 다른 출력
    # 기기의 상태도 들어오고, 계기 리스트의 태그가 전부 인터락에 걸려
    # 있는 것도 아니다.
    try:
        _ilin = {t.upper() for t in get_interlock().input_tags()}
    except Exception:                                       # noqa: BLE001
        _ilin = set()

    _seen = set()
    for r in rows:
        hit = (str(r["tag"]).upper() in _ilin
               or str(r.get("pid_tag") or "").upper() in _ilin)
        r["in_interlock"] = hit
        if hit:
            _seen.add(str(r["tag"]).upper())
            _seen.add(str(r.get("pid_tag") or "").upper())

    # 어느 목록에도 없이 인터락에만 등장하는 태그도 고를 수 있어야 한다.
    # 이것들을 빼면 화면에서 조회할 방법이 없는 인터락 조건이 생긴다.
    if kind in (None, "all", "output"):
        for t in sorted(_ilin - _seen):
            if q and q.lower() not in t.lower():
                continue
            rows.append({
                "tag": t, "pid_tag": t, "service": "",
                "maker": "", "model": "", "signal": "",
                "kind": "interlock_input", "io_count": 0,
                "in_interlock": True,
            })

    return {"tags": rows, "systems": [], "count": len(rows)}


@app.get("/api/instrument/{tag:path}")
def instrument_detail(tag: str):
    pid, io_tag = resolve_to_pid(tag)
    try:
        inst = load_instruments().get(pid) or load_instruments().get(tag)
        io_rec = load_io_points().get(tag) or load_io_points().get(io_tag or "")
    except Exception as e:
        return {
            "tag": tag,
            "pid_tag": pid or tag,
            "instrument": {"tag": tag, "pid_tag": pid or tag},
            "drawings": [],
            "history": [],
            "history_count": 0,
            "warning": str(e),
        }
    if not inst and io_rec:
        # IO 만 있는 경우 — P&ID 메타는 최소
        inst = {
            "TAG": pid or tag,
            "P&ID TAG": pid or tag,
            "SERVICE": io_rec.get("DESCRIPTION") or io_rec.get("SERVICE") or "",
            "IO TYPE": io_rec.get("IO TYPE") or "",
            "PANEL": io_rec.get("PANEL") or "",
            "RACK": io_rec.get("RACK"),
            "SLOT": io_rec.get("SLOT"),
            "CH": io_rec.get("CH"),
            "io_tags": [tag],
            "io_points": [],
        }
    if not inst:
        return {
            "tag": tag,
            "pid_tag": pid or tag,
            "instrument": {"tag": tag, "pid_tag": pid or tag},
            "drawings": list(load_drawings().get(pid or tag, [])),
            "history": [h for h in load_history() if h.get("tag") in (tag, pid)],
            "history_count": 0,
        }
    pid = inst.get("P&ID TAG") or pid or tag
    io_tags = list(inst.get("io_tags") or [])
    io_points = list(inst.get("io_points") or [])
    dwgs = list(load_drawings().get(pid, [])) or list(load_drawings().get(tag, []))
    panel_loc = None
    px = get_panel()
    if px is not None:
        # 판넬 위치는 IO TAG 로 조회 (P&ID 가 아님)
        pt = None
        for iot in ([tag] + list(io_tags or [])):
            pt = px.by_tag(iot)
            if pt:
                break
        if pt:
            panel_loc = pt["location"]
            if pt["drawing"] and not any(d.get("type") == "ARRANGEMENT"
                                         for d in dwgs):
                dwgs.append(pt["drawing"])
    hist = [h for h in load_history()
            if h.get("tag") in (tag, pid) or h.get("tag") in io_tags]
    hist.sort(key=lambda x: x.get("date") or "", reverse=True)
    return {
        "tag": tag,
        "pid_tag": pid,
        "io_tags": io_tags,
        "io_points": io_points,
        "instrument": {
            "tag": tag,
            "pid_tag": pid,
            "service": inst.get("SERVICE") or "",
            "maker": inst.get("MAKER") or "",
            "model": inst.get("MODEL") or "",
            "meas_type": inst.get("MEAS TYPE") or "",
            "unit": inst.get("UNIT") or "",
            "signal": inst.get("SIGNAL") or "",
            "panel": inst.get("PANEL") or inst.get("PANEL NO") or "",
            "terminal": inst.get("TERMINAL") or inst.get("TB") or "",
            "plc": inst.get("PLC") or "",
            "slot": inst.get("SLOT") or "",
            "channel": inst.get("CHANNEL") or inst.get("CH") or "",
            "dwg_no": inst.get("DWG NO") or inst.get("DWG_NO") or "",
        },
        "panel_location": panel_loc,
        "drawings": dwgs,
        "history": hist,
        "history_count": len(hist),
    }


# 주의: 아래 /api/history/{tag} 보다 먼저 등록해야 한다 — 뒤에 두면
# 'stats' 가 태그로 잡힌다 (등록 순서 매칭).
@app.get("/api/history/stats")
def history_stats(top: int = Query(8, ge=3, le=20)):
    """태그별 고장 이력 집계 — 말썽 많은 순 상위 N.

    전 태그를 다 그리면 화면이 감당을 못 하므로 상위만 주고 나머지는
    합계로 접는다. 매뉴얼 일치 구분을 함께 주는 이유: 건수가 많은
    것과 매뉴얼과 자주 어긋나는 것은 다른 신호이고, 후자가 더 급하다.
    """
    rows = load_history()
    by = {}
    for r in rows:
        t = r.get("tag") or "?"
        d = by.setdefault(t, {"tag": t, "total": 0,
                              "일치": 0, "부분일치": 0, "불일치": 0,
                              "last": ""})
        d["total"] += 1
        m = r.get("manual_match") or "부분일치"
        if m in d:
            d[m] += 1
        if (r.get("date") or "") > d["last"]:
            d["last"] = r.get("date") or ""
    ranked = sorted(by.values(), key=lambda x: (-x["total"], x["tag"]))
    head, rest = ranked[:top], ranked[top:]
    return {"total_records": len(rows),
            "total_tags": len(ranked),
            "top": head,
            "rest_tags": len(rest),
            "rest_records": sum(x["total"] for x in rest)}


@app.get("/api/history/{tag}")
def history_by_tag(tag: str):
    hist = [h for h in load_history() if h.get("tag") == tag]
    hist.sort(key=lambda x: x.get("date") or "", reverse=True)
    return {"tag": tag, "history": hist, "count": len(hist)}


@app.post("/api/feedback")
def add_feedback(req: FeedbackRequest):
    rows = load_history()
    wo = "WO-%s-%03d" % (dt.date.today().strftime("%Y"), len(rows) + 1)
    rec = {
        "wo_no": wo,
        "date": dt.date.today().isoformat(),
        "tag": req.tag,
        "device": (load_instruments().get(req.tag) or {}).get("MODEL") or "",
        "symptom": req.symptom,
        "code_ref": req.code_ref,
        "first_action": "",
        "root_cause": req.root_cause,
        "action_taken": req.action_taken,
        "manual_match": req.manual_match,
        "duration_min": req.duration_min,
        "parts": req.parts or "-",
        "tech": req.tech or "",
    }
    rows.append(rec)
    save_history(rows)
    return {"ok": True, "record": rec}


@app.delete("/api/history/{wo_no}")
def delete_history(wo_no: str):
    """작업번호(wo_no)에 해당하는 보수 이력을 삭제한다. (legacy_v1 기능 복원)"""
    rows = load_history()
    new_rows = [r for r in rows if r.get("wo_no") != wo_no]
    if len(new_rows) == len(rows):
        raise HTTPException(404, "이력 %s 을(를) 찾을 수 없습니다." % wo_no)
    save_history(new_rows)
    return {"ok": True, "deleted": wo_no, "remaining": len(new_rows)}


@app.post("/api/search")
def search(req: SearchRequest):
    try:
        r = get_retriever(req.mode)
        query = (req.alarm + " " + req.code).strip()
        hits = r.retrieve(query, tag=req.tag)
        results = []
        for rec, score, trace in hits:
            src = rec.get("source") or {}
            results.append({
                "id": rec["id"],
                "kind": rec["kind"],
                "title": rec["title"],
                "text": rec["text"][:500],
                "score": round(float(score), 4),
                "trace": trace,
                "source": src,
                "device": rec.get("device", ""),
                "cite": "%s p.%s (%s)" % (
                    src.get("file", ""), src.get("pdf_page", ""), src.get("section", "")),
            })
        return {"query": query, "tag": req.tag, "mode": req.mode,
                "count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/diagnose")
def diagnose(req: DiagnoseRequest):
    try:
        pid, io_tag = resolve_to_pid(req.tag)
        # 매뉴얼·검색은 P&ID, 응답에는 원본 IO TAG 유지
        search_tag = pid or req.tag
        out = get_copilot(req.mode).answer(
            tag=search_tag, alarm=req.alarm, code=req.code)
        evidence = []
        for e in out.get("evidence", [])[: config.FINAL_TOP_K]:
            evidence.append({
                "id": e.get("id"),
                "kind": e.get("kind"),
                "title": e.get("title"),
                "text": (e.get("text") or "")[:500],
                "score": e.get("score"),
                "cite": e.get("cite"),
                "source": e.get("source") or {},
                "summary_ko": "",
            })

        # 매뉴얼 근거 한국어 요약 (표시용). 실패해도 무시.
        #
        # 순차로 부르던 때는 요약 한 건에 15~40초가 걸려 조회 전체가 1~2분씩
        # 걸렸다. 검색·판정은 이미 1ms 안에 끝나 있는데 화면은 요약을 기다린다.
        # 요약끼리는 서로 의존하지 않으므로 동시에 던진다 — 대기 시간이 가장
        # 느린 한 건으로 줄어든다. COPILOT_SUMMARY=off 면 통째로 건너뛴다.
        if getattr(config, "SUMMARY_KO", True):
            try:
                from concurrent.futures import ThreadPoolExecutor
                from graph.advisor import summarize_ko
                targets = [it for it in evidence
                           if it.get("kind") == "manual_text"
                           ][: getattr(config, "SUMMARY_MAX", 3)]
                if targets:
                    with ThreadPoolExecutor(max_workers=len(targets)) as ex:
                        futs = [ex.submit(summarize_ko,
                                          it.get("text") or "",
                                          it.get("title") or "")
                                for it in targets]
                        for it, fu in zip(targets, futs):
                            try:
                                ko = fu.result()
                            except Exception:               # noqa: BLE001
                                ko = ""
                            if ko:
                                it["summary_ko"] = ko
            except Exception as _e:                         # noqa: BLE001
                print("[diagnose] summary_ko 생략:", _e)

        # 같은 카드 동반 태그 — 알람 폭주의 1차 용의선. 판넬 색인이
        # 없어도 조회는 살아야 하므로 실패는 조용히 None 으로 둔다.
        card_siblings = None
        try:
            _p = get_panel()
            if _p:
                card_siblings = _p.siblings(io_tag or req.tag) \
                    or _p.siblings(req.tag)
        except Exception:                                   # noqa: BLE001
            card_siblings = None

        return {
            "decision": out.get("decision"),
            "grade": out.get("grade"),
            "grade_reason": out.get("grade_reason"),
            "trace": out.get("trace", []),
            "attempts": out.get("attempts"),
            "rewrites": out.get("rewrites", []),
            "evidence": evidence,
            "mode": req.mode,
            "tag": req.tag,
            "pid_tag": search_tag,
            "io_tag": io_tag,
            "query": out.get("query") or req.alarm,
            "card_siblings": card_siblings,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


def _template_steps(evidence):
    """LLM 없이 근거를 그대로 보여주는 대체 경로."""
    steps = []
    for i, e in enumerate(evidence[:5], 1):
        steps.append({
            "n": i,
            "title": e.get("title") or f"근거 {i}",
            "detail": (e.get("text") or "")[:220],
            "source": e.get("cite") or "",
            "kind": "manual" if e.get("kind") == "manual_text" else "code",
            "evidence_ids": [e.get("id")],
        })
    return steps


@app.post("/api/advice")
def advice(req: AdviceRequest):
    """
    조치 순서 생성.

    LLM 이 붙어 있으면 근거를 정비원이 따라갈 순서로 바꾼다. 이때
    각 단계는 반드시 검색 결과에 있는 근거 ID 를 인용해야 하며,
    없는 ID 를 인용한 단계는 코드에서 버린다(graph/advisor.py).

    LLM 이 없거나 실패하면 근거를 그대로 나열하는 템플릿으로 되돌아간다.
    빈 화면을 보여주는 것보다 낫고, 근거 자체는 검증된 것이기 때문이다.
    mock 필드로 어느 경로였는지 화면에 알린다.

    req.mock=True 를 주면 LLM 을 건너뛰고 템플릿만 쓴다.
    """
    try:
        diag = get_copilot(req.mode).answer(tag=req.tag, alarm=req.alarm, code=req.code)
        evidence = diag.get("evidence") or []
        decision = diag.get("decision")

        steps, mock, note, dropped = None, True, "", 0

        # ── 현장 이력 매칭 ──────────────────────────────────
        # LLM 호출보다 먼저 한다. 조치 문장을 만들 때 이력을 함께
        # 넘겨야 "매뉴얼대로 했는데 아니었다" 는 기록이 반영된다.
        # 규칙으로 결정되므로 LLM 이 실패해도, 검색이 실패해도 남는다.
        hist_rows = []
        try:
            from retrieval.history_index import match as _hmatch
            _inst = load_instruments().get(req.tag) or {}
            _code = None
            for e in evidence:
                if e.get("kind") == "error_code" and e.get("code"):
                    _code = e["code"]
                    break
            hist_rows = _hmatch(
                load_history(), req.tag,
                symptom_query=req.alarm or "",
                device=[_inst.get("MODEL"), getattr(config, "CARD_DEVICE", None)],
                code_ref=_code,
                related_tags=list(_inst.get("io_tags") or []),
            )
        except Exception:                                   # noqa: BLE001
            hist_rows = []

        # 거절 판정에서는 조치를 만들지 않는다. 근거가 부족하다고
        # 판정한 뒤에 조치를 생성하면 판정이 의미가 없어진다.
        if decision == "advise" and evidence and not req.mock:
            try:
                from graph.advisor import generate
                res = generate(req.tag, req.alarm, evidence,
                               history=hist_rows)
                steps = [dict(s, n=i, kind="llm")
                         for i, s in enumerate(res["steps"], 1)]
                mock, dropped = False, res.get("dropped", 0)
                note = res.get("summary", "")
                if dropped:
                    note += " (근거 검증에서 %d개 단계 제외)" % dropped
            except Exception as e:                          # noqa: BLE001
                note = "조치 생성 미사용 — %s" % str(e)[:120]

        if steps is None:
            steps = _template_steps(evidence)

        # 이력 카드는 조치 순서 맨 앞에 꽂는다. LLM 이 이력을 반영해
        # 문장을 만들었더라도, 기록 원문을 그대로 보여주는 것은 별개다.
        hist_card = None
        try:
            from retrieval.history_index import build_card
            hist_card = build_card(hist_rows)
        except Exception:                                   # noqa: BLE001
            hist_card = None

        if hist_card:
            steps = [hist_card] + [dict(x, n=i + 1)
                                   for i, x in enumerate(steps)]

        if not steps:
            steps = [{
                "n": 1,
                "title": "근거 부족 — 현장 확인 우선",
                "detail": "검색·CRAG 결과가 충분하지 않습니다. 태그 상태와 현장 계측값을 먼저 확인하십시오.",
                "source": "system",
                "kind": "system",
            }]
        # 근거를 못 찾았을 때만 추측을 붙인다.
        #
        # 화면이 통째로 비면 사용자는 도구를 닫고 다른 데로 간다. 그렇다고
        # 조치 자리에 끼워 넣으면 근거 있는 답과 구분이 사라진다. 그래서
        # steps 에 넣지 않고 별도 필드로 내보낸다 — 화면은 접힌 상태로
        # 따로 보여주고, 4D 리포트는 이 필드를 읽지 않는다.
        guess, guess_note = None, ""
        if (req.free or decision != "advise") and not req.mock:
            try:
                from graph.advisor import guess as _guess
                guess, guess_note = _guess(
                    req.tag, req.alarm,
                    device=str(_inst.get("MODEL") or ""),
                    service=str(_inst.get("SERVICE") or ""))
            except Exception as e:                          # noqa: BLE001
                guess, guess_note = None, "%s: %s" % (type(e).__name__,
                                                      str(e)[:90])

        summary = (
            f"판정: {decision} (충분성 {diag.get('grade', 0):.2f}). "
            f"{diag.get('grade_reason') or ''}"
        )
        if note:
            summary += " — " + note
        return {
            "mock": mock,
            "dropped_steps": dropped,
            "summary": summary,
            "steps": steps,
            "decision": decision,
            "grade": diag.get("grade"),
            "trace": diag.get("trace", []),
            "evidence": evidence[: config.FINAL_TOP_K],
            "history_card": hist_card,
            "history_matched": len(hist_rows),
            "guess": guess,
            "guess_note": guess_note,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/interlock")
def interlock(req: InterlockRequest):
    try:
        ix = get_interlock()
        if req.as_input:
            res = ix.by_input(req.tag)
            if not res:
                return {"found": False, "tag": req.tag,
                        "message": f"{req.tag} 가 걸린 인터락이 없습니다."}
            hits = []
            for it, c in res["hits"]:
                hits.append({
                    "il_no": it["il_no"], "output_tag": it["output_tag"],
                    "kind": it["kind"], "action": it["action"],
                    "condition": _cond_dict(c),
                    "bypassable": it["bypassable"], "reset": it["reset"],
                    "dwg_no": it["dwg_no"],
                })
            return {"found": True, "as_input": True, "tag": req.tag,
                    "affected_outputs": res["affected_outputs"], "hits": hits}

        res = ix.by_output(req.tag, req.action)
        if not res:
            return {"found": False, "tag": req.tag,
                    "message": f"인터락 리스트에 {req.tag} 항목이 없습니다."}

        def pack(items):
            return [{
                "il_no": it["il_no"], "kind": it["kind"], "action": it["action"],
                "logic": it["logic"], "reset": it["reset"],
                "bypassable": it["bypassable"],
                "conditions": [_cond_dict(c) for c in it["conditions"]],
                "plc_block": it.get("plc_block"), "dwg_no": it.get("dwg_no"),
                "sheet": it.get("sheet"), "remark": it.get("remark"),
            } for it in items]

        return {
            "found": True, "as_input": False, "tag": req.tag,
            "action": res["action"], "output": res["output"],
            "blocking": pack(res["blocking"]),
            "enabling": pack(res["enabling"]),
            "other": pack(res["other"]),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


def _cond_dict(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "parsed": c.get("parsed", False),
        "raw": c.get("raw", ""),
        "tags": c.get("tags", []),
        "kind": c.get("kind"),
        "op": c.get("op"),
        "setpoint": c.get("setpoint"),
        "unit": c.get("unit"),
        "level": c.get("level"),
        "state": c.get("state"),
        "state_label": c.get("state_label"),
        "multi": c.get("multi"),
        "delay": c.get("delay_sec") if c.get("delay_sec") is not None else c.get("delay"),
    }




@app.post("/api/report")
def report_4d(req: ReportRequest):
    """4D 트러블 리포트 PDF 다운로드."""
    try:
        from api.report_4d import build_4d_pdf
    except ImportError:
        from report_4d import build_4d_pdf  # type: ignore

    try:
        inst_data = None
        try:
            inst_data = instrument_detail(req.tag)
        except Exception:
            inst_data = {"instrument": {}, "history": [], "drawings": []}

        inst = inst_data.get("instrument") or {}
        history_raw = inst_data.get("history") or []

        # 검색 근거
        try:
            r = get_retriever(req.mode)
            query = (req.alarm + " " + req.code).strip()
            hits = r.retrieve(query, tag=req.tag) if query else []
        except Exception:
            hits = []

        manuals = []
        for rec, score, trace in hits[:6]:
            src = rec.get("source") or {}
            cite = "%s p.%s" % (src.get("file") or "", src.get("pdf_page") or "")
            manuals.append({
                "id": rec.get("id"),
                "name": rec.get("title") or "",
                "description": (rec.get("text") or "")[:120],
                "cite": cite,
                "cite_short": cite,
            })

        # 현장 이력 — 화면의 이력 카드와 **같은 규칙**으로 고른다.
        # 태그로만 거른 목록을 앞에서 자르면, 화면은 불일치 건을 맨 위에
        # 올려 놓고 PDF 는 날짜순 아무 건이나 싣는 상태가 된다. 같은
        # 조회인데 두 산출물이 다른 근거를 말하면 어느 쪽도 못 믿는다.
        try:
            from retrieval.history_index import match as _hmatch
            _inst_row = load_instruments().get(req.tag) or {}
            hist_rows = _hmatch(
                load_history(), req.tag,
                symptom_query=req.alarm or "",
                device=[_inst_row.get("MODEL"),
                        getattr(config, "CARD_DEVICE", None)],
                related_tags=list(_inst_row.get("io_tags") or []),
            )
        except Exception:                                   # noqa: BLE001
            hist_rows = []
        # 규칙이 한 건도 못 걸면 태그 목록으로 되돌린다. 리포트가 비는
        # 것보다 낫고, 이력 조회가 죽어도 문서는 나와야 한다.
        if not hist_rows:
            hist_rows = history_raw[:5]

        history = []
        for h in hist_rows[:5]:
            mark = h.get("manual_match") or h.get("match") or ""
            layer = h.get("_layer") or ""
            history.append({
                "root_cause": h.get("root_cause") or "",
                "action": h.get("action_taken") or h.get("action") or "",
                "wo_no": h.get("wo_no") or "",
                # 매칭 근거를 같은 줄에 붙인다 — 줄 수를 늘리지 않으면서
                # L3(다른 태그) 가 왜 실렸는지 보인다.
                "match": ("%s · %s" % (mark, layer)) if layer else mark,
                "duration_min": h.get("duration_min"),
                "date": h.get("date") or "",
            })

        # 조치 순서
        #
        # 화면이 만든 순서가 넘어오면 그대로 쓴다. 안 넘어오면 규칙으로
        # 만든다 — 리포트는 버튼을 누른 자리에서 바로 나와야 하므로
        # 여기서 LLM 을 다시 부르지 않는다.
        #
        # 예전에는 검색 상위 청크의 제목을 그대로 단계로 썼다. 영문 목차
        # 제목("Standards Required for Single-Point Calibration")에 체크박스가
        # 붙어 "즉시 조치"로 나갔다. 조치가 아닌 것을 조치라고 부르는
        # 문서였다. 매뉴얼 제목은 확인 항목으로 이름을 바로잡고, 불일치
        # 이력이 있으면 그것을 첫 항목에 올린다.
        steps = []
        if req.steps:
            steps = [str(s).strip() for s in req.steps if str(s).strip()][:5]
        else:
            for h in hist_rows:
                if h.get("manual_match") == "불일치":
                    steps.append("현장 이력 확인 — %s (%s)" % (
                        (h.get("root_cause") or "")[:44],
                        h.get("wo_no") or "-"))
                    break
            for rec, score, trace in hits[:5 - len(steps)]:
                steps.append("매뉴얼 근거 확인: %s"
                             % (rec.get("title") or rec.get("id") or "점검 항목"))

        # 같은 카드 동반 태그 — 리포트 D2 의 "동일 판넬·카드 연관 알람
        # 확인" 항목을 구체 태그로 채운다. 판넬 색인이 없어도 리포트는
        # 나와야 하므로 실패는 None 으로 삼킨다.
        _sib = None
        try:
            _p = get_panel()
            if _p:
                _sib = _p.siblings(req.tag)
        except Exception:                                   # noqa: BLE001
            _sib = None

        import datetime as _dt
        now = _dt.datetime.now()
        payload = {
            "doc_no": "TR-%s-%s" % (now.strftime("%Y%m%d"), (req.tag or "TAG")[-4:]),
            "date_str": now.strftime("%Y-%m-%d %H:%M"),
            "tag": req.tag,
            "alarm": req.alarm or "",
            "code": req.code or "",
            "tech": req.tech or "-",
            "maker": inst.get("maker") or "",
            "model": inst.get("model") or "",
            "panel": inst.get("panel") or "-",
            "panel_grid": ((inst_data.get("panel_location") or {}).get("grid")
                           or ""),
            "panel_area": ((inst_data.get("panel_location") or {}).get("area")
                           or ""),
            "terminal": inst.get("terminal") or "-",
            "service": inst.get("service") or "",
            "status": "조회",
            "manual": manuals,
            "history": history,
            "advice_steps": steps,
            "confirmed_cause": req.confirmed_cause or "",
            "card_siblings": _sib,
            "final_action": req.final_action or "",
            "parts": req.parts or "-",
            "duration_min": req.duration_min,
        }
        pdf = build_4d_pdf(payload)
        fname = "4D_Report_%s_%s.pdf" % (
            (req.tag or "TAG").replace("/", "-"),
            now.strftime("%Y%m%d_%H%M"),
        )
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=%s" % fname,
            },
        )
    except Exception as e:
        raise HTTPException(500, "보고서 생성 실패: %s" % e)



@app.get("/api/interlock-source")
def interlock_source(tag: str = Query(...)):
    """인터락 리스트 엑셀 원본 블록 (사람이 대조할 수 있게)."""
    try:
        from ingest.interlock_real import (
            extract_source_block, detect_real_format, _interlock_files,
        )
        path = config.INTERLOCK_XLSX
        if not os.path.exists(path):
            raise HTTPException(404, "인터락 파일 없음: %s" % path)
        files = _interlock_files(path)
        if not files:
            raise HTTPException(
                404,
                "인터락 xlsx 없음 — data/interlock/ 에 .xlsx 를 넣으십시오 (%s)" % path,
            )
        # 폴더/파일 모두 extract 가 처리 (실물 양식)
        try:
            real = any(detect_real_format(f) for f in files)
        except Exception:
            real = True  # extract 쪽에서 재시도
        if real:
            block = extract_source_block(tag, path)
            if not block:
                raise HTTPException(404, f"{tag} 원본 블록 없음")
            return block
        # 데모 표 형식: 해당 OUTPUT TAG 행만
        from openpyxl import load_workbook
        path = files[0]
        ws = load_workbook(path, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        hi = next(i for i, r in enumerate(rows)
                  if r and "IL NO" in [str(c).strip().upper() if c else "" for c in r])
        hdr = [str(c).strip() if c else "" for c in rows[hi]]
        out_rows = [{"row": hi + 1, "cells": hdr}]
        tag_u = tag.strip().upper()
        for i, r in enumerate(rows[hi + 1:], start=hi + 2):
            vals = [str(c).strip() if c is not None else "" for c in r]
            # OUTPUT TAG column
            try:
                ti = next(k for k, h in enumerate(hdr) if h.upper() == "OUTPUT TAG")
            except StopIteration:
                ti = 1
            if len(vals) > ti and vals[ti].upper() == tag_u:
                while vals and vals[-1] == "":
                    vals.pop()
                out_rows.append({"row": i, "cells": vals})
        if len(out_rows) <= 1:
            raise HTTPException(404, f"{tag} 행 없음")
        return {
            "tag": tag_u,
            "file": os.path.basename(path),
            "path": path,
            "header": tag_u,
            "row_start": out_rows[1]["row"] if len(out_rows) > 1 else hi + 1,
            "row_end": out_rows[-1]["row"],
            "rows": out_rows,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))




# 규칙 기반 의도 분석. 모듈 레벨에 둔다 — 모델이 없을 때의 유일한
# 경로이자 챗봇이 지어낸 태그를 대조하는 기준이므로, 다른 모듈에서
# 불러 시험할 수 있어야 한다. 함수 안에 숨겨 두면 점검이 안 된다.
# ── 태그 표기 정규화 ────────────────────────────────────────
_known_tags_cache = None
_known_tags_error = None


# ── 판넬 조회 ───────────────────────────────────────────────
def _need_panel() -> PanelIndex:
    px = get_panel()
    if px is None:
        raise HTTPException(503, "판넬 인덱스를 적재하지 못했습니다: %s"
                            % (_panel_error or "원인 미상"))
    return px


@app.get("/api/panels")
def list_panels():
    px = _need_panel()
    return {"panels": px.panels(), "unlocated": px.unlocated,
            "arrangement_pdf": os.path.basename(config.ARRANGEMENT_PDF),
            "arrangement_exists": os.path.exists(config.ARRANGEMENT_PDF)}


@app.get("/api/panel/{name}")
def panel_detail(name: str):
    """
    판넬 구성·위치 조회.

    판넬 단위 '상실' 은 제공하지 않는다. 이중화 구성에서는 랙 증설도
    스위칭으로 대응하므로 판넬 전체가 죽는 상황이 성립하지 않는다.
    상실 영향은 /api/card 를 쓴다.
    """
    px = _need_panel()
    d = px.by_panel(name)
    if not d:
        raise HTTPException(404, "계기 리스트에 %s 판넬이 없습니다." % name)
    return d


@app.get("/api/cards")
def list_cards(panel: Optional[str] = None):
    """
    IO 카드 목록.

    이중화(S7-400H/410H) 구성에서는 CPU·전원·통신이 이중화되고 카드만
    단일이다. 그래서 실제 단일 고장 단위는 판넬이 아니라 카드다.
    """
    px = _need_panel()
    cards = px.cards()
    if panel:
        cards = [c for c in cards if c["panel"] == panel]
    return {"cards": cards, "count": len(cards)}


@app.get("/api/card")
def card_detail(id: str = Query(..., description="예: CUB-B/R0/S8"),
                impact: int = Query(0, ge=0, le=1)):
    # 카드 ID 에 '/' 가 들어가므로 경로가 아니라 질의 인자로 받는다.
    px = _need_panel()
    d = px.impact(id) if impact else px.by_card(id)
    if not d:
        raise HTTPException(404, "계기 리스트에 %s 카드가 없습니다." % id)
    return d


@app.get("/api/tag-consistency")
def tag_consistency():
    """
    IO List · 계기 리스트 · 인터락 리스트의 태그 교차 대조.

    어느 쪽이 맞는지는 판정하지 않는다 — 두 문서가 다르다는 사실까지만
    말한다. 실물 문서로 갈아 끼울 때 제일 먼저 걸리는 지점이다.
    """
    from ingest.tag_registry import cross_check
    return cross_check()


@app.get("/api/common-cause")
def common_cause():
    """한 인터락의 조건 태그가 같은 카드에 몰려 있는지 — 설계 검토 항목."""
    px = _need_panel()
    return px.common_cause()


@app.get("/api/common-cause-of")
def common_cause_of(tags: str = Query(
        ..., description="쉼표 구분 태그 목록 — 예: AIT-4002,AIT-3002")):
    """동시 알람 태그 묶음의 공통 상위 노드 역추적 (card→rack→panel→plc).

    /api/common-cause 가 설계 점검(한 인터락의 조건이 같은 카드에 몰려
    있는가)이라면, 이쪽은 사후 진단이다 — 알람 폭주가 왔을 때 태그별로
    N번 조회하는 대신 묶음 한 번으로 카드/랙/판넬 층을 가른다.
    """
    p = _need_panel()
    items = [x.strip() for x in tags.split(",") if x.strip()]
    if not items:
        raise HTTPException(400, "태그가 비어 있습니다")
    return p.common_cause_of(items)


@app.get("/api/panel-of/{tag}")
def panel_of_tag(tag: str):
    px = _need_panel()
    d = px.by_tag(tag)
    if not d:
        raise HTTPException(404, "계기 리스트에 %s 가 없습니다." % tag)
    return d


@app.get("/api/investigate-flood")
def investigate_flood(tags: str = Query(..., description="쉼표 구분 태그"),
                      codes: str = Query("", description="쉼표 구분 SSL 코드"),
                      alarm: str = Query("", description="알람명(선택)"),
                      mode: str = Query(DEFAULT_MODE)):
    """동시 알람 조사 오케스트레이션 (패치 28).

    common-cause-of 가 판정 한 번이라면, 이쪽은 조사 절차 전체다 —
    공통 조상 → 반례(미알람 동반 태그) → 코드·알람명 근거 수집 → 결론.
    밟은 단계가 steps 로 남는다. 결론 문장은 규칙 조립이며 LLM 을 쓰지
    않는다.
    """
    from retrieval.flood import investigate
    p = _need_panel()
    tag_list = [x.strip() for x in tags.split(",") if x.strip()]
    code_list = [x.strip() for x in codes.split(",") if x.strip()]
    if not tag_list:
        raise HTTPException(400, "태그가 비어 있습니다")
    return investigate(tag_list, panel=p, retriever=get_retriever(mode),
                       codes=code_list or None, alarm=alarm or None)


@app.get("/api/ingest/repair-plan")
def ingest_repair_plan():
    """수리안 목록 — 읽기만 하므로 열쇠 불필요 (패치 28)."""
    from ingest import repair
    return repair.propose()


@app.post("/api/ingest/repair-apply")
def ingest_repair_apply(request: Request, body: dict = Body(...)):
    """선택한 자동 수리안 반영 — 자료를 바꾸므로 열쇠·임대를 거친다.

    반영 전 .prev 보존, 반영 후 재점검 수치를 함께 돌려준다 (패치 28).
    """
    _require_edit(request)
    ids = [str(x) for x in (body.get("ids") or [])]
    if not ids:
        raise HTTPException(400, "반영할 제안 id 가 없습니다")
    from ingest import repair
    out = repair.apply(ids)
    # 자료가 바뀌었으니 파생 캐시 표시 — 재생성 안내는 기존 반입 흐름과 동일
    out["note"] = ("IO List 가 바뀌었습니다. 판넬 조회는 즉시 반영되며, "
                   "색인 재생성은 필요 없습니다(문서 본문이 아니라 배선 "
                   "정보이므로). 이전 판은 %s 로 보존되었습니다."
                   % (out.get("prev") or "보존 없음(반영 0건)"))
    global _panel, _panel_error
    _panel, _panel_error = None, None      # 다음 조회에서 다시 읽는다
    return out



def known_tags():
    """계기 리스트 + 인터락 출력 태그의 합집합. 대문자 기준."""
    global _known_tags_cache
    if _known_tags_cache is None:
        # 여기서 실패를 삼키면 태그 목록이 비고, 그러면 챗봇이 멀쩡한
        # 태그에도 "리스트에 없습니다" 라고 답한다. 원인을 찾기 어려운
        # 종류의 고장이므로 사유를 남긴다.
        global _known_tags_error
        ts, errs = set(), []
        for name, fn in (("출력 태그", load_output_tags),
                         ("계기 리스트", load_instruments)):
            try:
                ts |= {str(t).upper() for t in fn().keys()}
            except Exception as e:                          # noqa: BLE001
                errs.append("%s: %s" % (name, e))
        _known_tags_error = " / ".join(errs) if errs else None
        _known_tags_cache = {t for t in ts if t}
    return _known_tags_cache


def normalize_tag(raw):
    """
    사람이 쓰는 표기를 실제 태그로 되돌린다.

    현장에서는 하이픈을 빼거나 띄어 쓴다. "LCV 01", "lcv01", "LCV_01"
    은 모두 LCV-01 을 말한다. 이전 정규식은 하이픈 형태만 받았고,
    그래서 "LCV 01 인터락 보여줘" 가 태그 없이 넘어가 화면에서 아무
    일도 일어나지 않았다. 실패가 조용해서 원인을 알기 어려웠다.

    실재하는 태그로만 되돌린다. 목록에 없으면 None 을 준다 —
    없는 태그를 만들어 조회하지 않기 위해서다.
    """
    if not raw:
        return None
    key = re.sub(r"[^a-z0-9]", "", str(raw).lower())
    if not key:
        return None
    for t in known_tags():
        if re.sub(r"[^a-z0-9]", "", t.lower()) == key:
            return t
    return None


_panel_names_cache = None


def known_panels():
    """판넬명 집합. 실패하면 빈 집합이 아니라 사유를 남긴다."""
    global _panel_names_cache
    if _panel_names_cache is None:
        px = get_panel()
        _panel_names_cache = ({p["panel"].upper() for p in px.panels()}
                              if px is not None else set())
    return _panel_names_cache


def find_panel(msg):
    """
    문장에서 판넬명을 찾는다.

    판넬명(CUB-B, RIO-01)은 태그와 표기가 겹친다. find_tag 가 먼저 돌면
    'RIO-01' 을 없는 태그로 보고 "리스트에 없습니다" 를 반환한다.
    그래서 판넬 판정을 태그 판정보다 앞에 둔다.
    """
    names = known_panels()
    if not names:
        return None
    up = msg.upper()
    hits = [n for n in names if re.search(r"(?<![A-Z0-9])%s(?![A-Z0-9])"
                                          % re.escape(n), up)]
    if hits:
        return max(hits, key=len)
    # 하이픈 없이 쓴 경우 (CUB B / CUBB)
    for n in names:
        loose = re.escape(n).replace(r"\-", r"[\s_-]*")
        if re.search(r"(?<![A-Z0-9])%s(?![A-Z0-9])" % loose, up):
            return n
    return None


_tag_prefix_cache = None


def known_tag_prefixes():
    """
    실재하는 태그에서 접두어를 뽑아 둔다 (AIT, PIT, XV, LCV, P …).

    하드코딩하지 않고 리스트에서 읽는다. 실물 계기 리스트로 바꾸면
    접두어도 함께 바뀌어야 하기 때문이다.
    """
    global _tag_prefix_cache
    if _tag_prefix_cache is None:
        pres = set()
        for t in known_tags():
            m = re.match(r"^([A-Za-z]+)", str(t))
            if m:
                pres.add(m.group(1).upper())
        _tag_prefix_cache = pres
    return _tag_prefix_cache


def find_tag(msg, cur_tag=None):
    """
    문장에서 태그를 찾는다. 하이픈이 없어도 찾고, 실재 여부를 확인한다.

    반환: (태그 또는 None, 후보였지만 목록에 없던 문자열 또는 None)
    두 번째 값이 있으면 "그런 태그는 없습니다" 라고 말할 수 있다.
    """
    # 경계를 \b 로 잡으면 한글 조사가 붙은 표기를 통째로 놓친다.
    #
    #   "ait-1001은 어느 위치에 있어?"
    #        └ \b 는 '1' 과 '은' 사이를 경계로 보지 않는다 (둘 다 word 문자)
    #
    # 그러면 find_tag 가 실패하고 cur_tag 로 조용히 대체되어, 사용자가
    # 물어본 것과 **다른 태그**의 답이 나간다. 화면에는 그럴듯한 답이
    # 떠서 틀렸다는 사실조차 드러나지 않는다.
    #
    # 영숫자만 경계로 보게 바꾼다 — 한글·공백·문장부호는 모두 구분자다.
    B0, B1 = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
    # 밑줄로 여러 마디를 잇는 실물 표기를 **가장 먼저** 본다.
    #   DWP_AMP_6018A · WATER_TANK_LIT_P3601B · FAB_CPU_XA_0001
    # 이것이 없으면 아래 'LCV 01' 규칙이 'DWP_AMP' 까지만 끊어 먹고,
    # 해석에 실패한 뒤 현재 화면 태그로 대체되어 **다른 설비의 답**이
    # 나간다. 화면에는 그럴듯한 문장이 떠서 틀린 줄도 모른다.
    pats = [B0 + r"([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)" + B1,  # DWP_AMP_6018A
            B0 + r"([A-Za-z]{1,8}-[A-Za-z0-9]{1,8})" + B1,      # LCV-01
            B0 + r"([A-Za-z]{2,8})[\s_]+([A-Za-z0-9]{1,8})" + B1,  # LCV 01
            B0 + r"([A-Za-z]{2,8})(\d{1,5}[A-Za-z]?)" + B1]       # LCV01
    # 못 푼 후보를 두 등급으로 나눈다. 등급을 안 나누면 양쪽이 번갈아
    # 뚫린다.
    #
    #   강함 : 접두어가 실재 태그 접두어 (AIT-9999, XV-1234)
    #          → 태그를 말한 게 확실하니 거절하고 QA 로도 넘기지 않는다
    #   약함 : 숫자는 있지만 접두어가 낯설다 (PCS 7, TB2, AI 16xI, bge-m3)
    #          → 태그가 아니라 기술 용어일 수 있으니 질문은 막지 않는다
    #            다만 **현재 화면 태그로 대체하지도 않는다**
    #
    # 약한 후보까지 거절하면 "AI 16xI 모듈 상태 표시" 같은 매뉴얼 질문이
    # 통째로 막히고(실제로 매뉴얼 6.1 절 제목이다), 반대로 약한 후보에
    # 대체를 허용하면 "zzt-9999는 어디야" 에 엉뚱한 설비 답이 나간다.
    miss = None
    weak = False
    for p in pats:
        for m in re.finditer(p, msg):
            cand = "-".join(g for g in m.groups() if g)
            t = normalize_tag(cand)
            if t:
                return t, None
            if not re.search(r"\d", cand):
                continue
            head = re.match(r"^([A-Za-z]+)", cand)
            if head and head.group(1).upper() in known_tag_prefixes():
                if miss is None:
                    miss = cand.upper()
            else:
                weak = True
    if miss:
        return (cur_tag or None), miss
    if weak:
        return None, None          # 대체하지 않는다
    return (cur_tag or None), None


def panel_intent(msg, low, cur_tag=None):
    """
    판넬 관련 의도. 해당 없으면 None 을 돌려 기존 규칙으로 넘긴다.

    답변에 실제 수치를 담는다. "판넬 조회 탭으로 이동합니다" 만 하면
    사용자가 챗봇에 물어본 이유가 사라진다.
    """
    px = get_panel()
    if px is None:
        return None

    panel = find_panel(msg)
    wants_impact = re.search(r"내리|끄|차단|정전|단전|셧다운|shutdown|"
                             r"점검|영향|잃|죽|무슨\s*일", low)
    wants_card = re.search(r"카드|모듈|슬롯|채널|card|module", low)
    wants_cc = re.search(r"공통\s*원인|같은\s*카드|한\s*카드|공통\s*고장|"
                         r"분산\s*배치|common\s*cause", low)

    # ── 공통원인 점검 ─────────────────────────────────────
    if wants_cc:
        cc = px.common_cause()
        if not cc["loaded"]:
            return {"type": "chat", "reply": "인터락 리스트를 읽지 못했습니다."}
        if cc["findings"]:
            head = ", ".join("%s(%s)" % (f["il_no"], f["severity"])
                             for f in cc["findings"][:5])
            body = "인터락 %d건 중 %d건이 지적됩니다 — %s" % (
                cc["checked"], len(cc["findings"]), head)
        else:
            body = ("인터락 %d건을 점검했고 지적은 없습니다. 다만 이는 "
                    "'설계가 안전하다'가 아니라 이 리스트 범위에서 걸린 것이 "
                    "없다는 뜻입니다." % cc["checked"])
        return {"type": "panel", "tab": "panel", "reply": body}

    # ── 카드 상실 영향 ────────────────────────────────────
    # 이중화 구성에서는 카드가 유일한 단일 고장 지점이다.
    if wants_card:
        tag, miss = find_tag(msg, cur_tag)
        if miss:
            return {"type": "panel", "tab": "panel",
                    "reply": "%s 는 계기 리스트에 없습니다." % miss}
        if tag:
            cid = px.card_of(tag)
            d = px.impact(cid) if cid else None
            if d:
                if not d["interlock_loaded"]:
                    body = ("계기 %d점을 잃습니다. 인터락 리스트를 읽지 못해 "
                            "의존 관계는 계산하지 못했습니다." % d["points"])
                else:
                    full = [r["il_no"] for r in d["dependencies"]
                            if r["remaining_protection"].startswith("없음")]
                    body = ("같은 카드에 %d점(%s)이 물려 있습니다. "
                            "의존 인터락 %d건 중 안전 인터락 %d건, 남는 보호가 "
                            "없는 항목은 %s, 영향 출력은 %s 입니다."
                            % (d["points"], ", ".join(d["lost_tags"]),
                               len(d["dependencies"]), d["safety_count"],
                               ", ".join(full) or "없습니다",
                               ", ".join(o["tag"]
                                         for o in d["affected_outputs"])
                               or "없습니다"))
                return {"type": "panel", "tab": "panel", "panel": d["panel"],
                        "card": cid, "tag": tag,
                        "reply": "%s 는 %s 카드입니다. %s\n\n※ %s"
                                 % (tag, cid, body, d["caveat"])}
    # "판넬 명 알려줘", "태그가 있는 판넬", "어느 판넬" 등을 모두 위치 조회로 본다.
    # 이전 패턴은 '어디/위치/어느 판넬' 만 받아서 "판넬 명을 알려줘" 를
    # 놓쳤고, 그 결과 QA/LLM 경로로 넘어가 판넬 이름을 지어냈다.
    wants_where = re.search(
        r"어디|위치|"
        r"어느\s*판\s*넬|무슨\s*판\s*넬|어떤\s*판\s*넬|"
        r"판\s*넬\s*(명|이름|어디|위치|번호|은|는|이|가|을|를)|"
        r"있는\s*판\s*넬|속한\s*판\s*넬|물린\s*판\s*넬|"
        r"판\s*넬.*알려|알려.*판\s*넬|"
        r"which\s*panel|what\s*panel|panel\s*name",
        low)

    # ── 판넬 전체 상실 질문은 성립하지 않는다 ──────────────
    #
    # 이중화(S7-400H/410H) 구성에서는 랙 증설도 스위칭으로 대응하므로
    # 판넬 전체가 한 번에 죽는 상황이 없다. 숫자를 만들어 답하면
    # 없는 시나리오에 근거를 준다. 카드 단위로 되돌린다.
    if panel and wants_impact and not wants_card:
        d = px.by_panel(panel)
        cards = [c for c in px.cards() if c["panel"] == panel]
        return {"type": "panel", "tab": "panel", "panel": panel,
                "reply": ("이중화 구성이라 %s 판넬 전체가 한 번에 죽는 "
                          "상황은 다루지 않습니다. 단일 고장 단위는 IO "
                          "카드이고, %s 에는 카드 %d장에 계기 %d점이 "
                          "물려 있습니다. 카드를 고르면 그 카드 상실 "
                          "영향을 보여드립니다."
                          % (panel, panel, len(cards), d["points"]))}

    # ── 태그가 어느 판넬인가 ──────────────────────────────
    if wants_where and not panel:
        tag, miss = find_tag(msg, cur_tag)
        # miss 가 있다는 것은 문장 안의 태그를 하나도 풀지 못했다는 뜻이다.
        # "어디에 있어?" 는 이름 자체가 질문의 주어라서, 현재 선택된
        # 태그로 대신 답하면 다른 설비의 위치를 알려주게 된다.
        if miss:
            return {"type": "panel", "tab": "panel",
                    "reply": "%s 는 계기 리스트와 인터락 리스트에 없습니다. "
                             "태그를 확인해 주세요." % miss}
        if not tag:
            return {"type": "panel", "tab": "panel",
                    "reply": "말씀하신 태그를 계기 리스트에서 찾지 "
                             "못했습니다. 태그를 확인해 주세요."}
        if tag:
            d = px.by_tag(tag)
            if d:
                loc = d["location"]
                where = ("%s / 그리드 %s / %s"
                         % (loc["area"], loc["grid"],
                            "실내" if loc["indoor"] else "옥외")) if loc \
                    else "배치 정보 없음"
                return {"type": "panel", "tab": "panel", "panel": d["panel"],
                        "tag": tag,
                        "card": d.get("card"),
                        "reply": "%s 는 %s 판넬입니다. 위치는 %s, 단자대 %s, "
                                 "%s Rack %s Slot %s Ch %s (카드 %s) 입니다."
                                 % (tag, d["panel"], where, d["terminal"] or "-",
                                    d["plc"], d["rack"], d["slot"], d["ch"],
                                    d.get("card"))}
            # 태그는 알지만 PANEL 배선이 없다.
            # 출력 태그(LCV/XV/펌프 등)는 인터락 리스트에 있어도
            # 계기 리스트 PANEL 열이 없으면 판넬 위치를 말할 수 없다.
            # 없는 판넬 이름을 지어내지 않는다.
            outs = {}
            try:
                outs = load_output_tags()
            except Exception:                               # noqa: BLE001
                outs = {}
            if tag in outs or tag.upper() in {t.upper() for t in outs}:
                rec = outs.get(tag) or outs.get(tag.upper()) or {}
                svc = rec.get("service") or ""
                return {"type": "panel", "tab": "panel", "tag": tag,
                        "reply": (
                            "%s 는 인터락/출력 태그입니다%s. "
                            "판넬 위치는 계기 리스트의 PANEL 열(IO 배선)에서 "
                            "읽는데, 이 태그에는 그 정보가 없습니다. "
                            "판넬 이름을 추정하지 않습니다. "
                            "동작 조건이 필요하면 인터락 조회를 해 주세요."
                            % (tag, (" (%s)" % svc) if svc else "")
                        )}
            return {"type": "chat",
                    "reply": "%s 는 계기 리스트에 PANEL 정보가 없어 "
                             "판넬 위치를 말할 수 없습니다." % tag}

    # ── 판넬명만 나온 경우 ────────────────────────────────
    if panel and re.search(r"판\s*넬|panel|무엇|뭐|물려|계기", low):
        d = px.by_panel(panel)
        if not d:
            return {"type": "chat",
                    "reply": "%s 판넬을 배선 자료에서 찾지 못했습니다." % panel}
        loc = d.get("location") or {}
        # by_panel 의 키가 by_tb → by_terminal 로 바뀌었는데 이 줄만 옛
        # 이름을 읽어, 판넬명으로 챗봇 조회하면 죽었다 (패치 29b에서 발견).
        tbs = d.get("by_terminal") or {}
        return {"type": "panel", "tab": "panel", "panel": panel,
                "reply": "%s — %s 그리드 %s, 계기 %d점 (%s)"
                         % (panel, loc.get("area", "위치 정보 없음"),
                            loc.get("grid", "-"), d.get("points", 0),
                            ", ".join("%s %d" % (k, len(v))
                                      for k, v in tbs.items()) or "단자 정보 없음")}
    return None


SMALLTALK = [
    # (정규식, 답변)
    (r"^\s*(안녕|하이|헬로|반가|ㅎㅇ|hello|hi|hey)",
     "안녕하세요. 계기 알람·인터락·판넬 조회를 도와드립니다. "
     "찾으시는 태그나 증상을 알려주세요."),
    (r"(고마워|고맙|감사|thanks|thank you)",
     "도움이 되었다면 다행입니다. 더 찾으실 것이 있으면 말씀해 주세요."),
    (r"(잘가|바이|수고|들어가|bye|끝)",
     "네, 필요하실 때 다시 불러 주세요."),
    (r"(미안|죄송|sorry)",
     "괜찮습니다. 다시 말씀해 주세요."),
    (r"(누구|정체|넌\s*뭐|너는\s*뭐|what are you)",
     "이 화면의 조회를 돕는 도우미입니다. 계기 리스트·인터락 리스트·"
     "장비 매뉴얼에 있는 내용만 답하고, 없는 것은 없다고 말합니다."),
    (r"(뭐\s*할\s*수|뭘\s*할\s*수|무엇을\s*할\s*수|기능|어떤\s*걸\s*도와|"
     r"뭐\s*해줄)",
     "알람 조회(태그+증상), 인터락 조회(출력 태그), 판넬·카드 조회, "
     "도면 보기를 할 수 있습니다. 자세한 사용법은 '사용법' 이라고 "
     "말씀해 주세요."),
]


def smalltalk_intent(msg, low):
    """
    인사·감사·잡담에 예시 목록을 던지지 않게 한다.

    "안녕하세요" 에 "예) AIT-4002 low acid 알람 조회해줘 …" 를 돌려주면
    사람은 무시당했다고 느낀다. 실제로 그렇게 나갔다. 짧은 인사말은
    도메인 질의가 아니므로 매뉴얼 검색으로 넘겨서도 안 된다 — 근거가
    없으니 "매뉴얼에서 근거를 찾지 못했습니다" 가 나온다.

    길이를 제한하는 이유는 "안녕히 계세요, 그런데 AIT-1001 은…" 같은
    문장을 인사로 삼키지 않기 위해서다.
    """
    if len(msg.strip()) > 24:
        return None
    for pat, reply in SMALLTALK:
        if re.search(pat, low):
            return {"type": "chat", "reply": reply}
    return None


# 기능에 대한 질문("판넬 조회로 뭘 알 수 있지?")과 기능을 쓰라는
# 명령("판넬 조회해줘")은 다르다. 이 구분이 없던 동안 질문이 명령
# 규칙까지 흘러가 알람 조회가 실행됐다 — 묻는 사람에게 답 대신 행동이
# 나갔다 (패치 29b). 질문 표지가 있으면 명령보다 먼저 안내로 답한다.
_FEATURE_Q = re.compile(
    r"(어떤|무슨|뭔)\s*(기능|것|걸)|기능(이|이야|이지|인가|일까|인지)"
    r"|뭘\s*(알|보여|할|해)|무엇을\s*(알|보여|할)|어떤\s*걸?\s*알"
    r"|알\s*수\s*있(지|나|어|을까)|어떻게\s*(쓰|사용)|사용\s*(법|방법)"
    r"|뭐(야|지|예요|에요|인가요|죠)|뭔가요|뭐가\s*(나와|보여|달라)")

_FEATURE_HELP = [
    (r"판넬|카드\s*조회|배선",
     "판넬 조회는 계기가 어디에 어떻게 물려 있는지를 봅니다.\n"
     "· 태그가 어느 판넬·어느 카드·몇 번 채널인지, 단자 번호까지\n"
     "· 같은 카드에 물린 다른 계기 — 카드 한 장이 죽으면 함께 우는 것들\n"
     "· 카드가 죽었을 때 영향을 받는 인터락 (의존 관계만, 트립 단정 없음)\n"
     "· 배치도에서 그 판넬의 위치\n"
     "화면 맨 아래 「동시 알람 조사」로 여러 태그의 공통 원인도 짚습니다.\n"
     "예: CUB-A 판넬 조회해줘 / AIT-4002 어느 판넬이야"),
    (r"인터락|interlock",
     "인터락 조회는 설비가 왜 멈췄는지(못 움직이는지)를 리스트에서 찾아 "
     "보여줍니다.\n"
     "· 동작(정지·기동 등)별 조건과 세트포인트, 지연 시간\n"
     "· 래치 여부 — 수동(MANUAL)은 사람이 리셋해야 풀립니다\n"
     "· 역방향 — 이 계기가 어느 설비를 세우는지\n"
     "· 「원본 보기」로 리스트 원문 대조\n"
     "예: P-5101A 인터락 조회해줘 / LIT-4003 이 걸린 인터락"),
    (r"알람\s*조회|알람\s*기능|진단",
     "알람 조회는 태그와 증상으로 벤더 매뉴얼 근거를 찾아 옵니다.\n"
     "· 근거마다 문서명·페이지 — 원문 보기로 확인\n"
     "· 현장 조치 이력이 있으면 함께, 매뉴얼과 다르면 경고\n"
     "· 근거가 부족하면 답하지 않고 거절(ABSTAIN)합니다\n"
     "· 조치 순서 생성 → 결과 기록 → 4D 리포트로 이어집니다\n"
     "예: AIT-4002 loop error 알람 조회해줘"),
    (r"반입|업로드|파일\s*(올리|넣)",
     "자료 반입은 새 매뉴얼·리스트를 넣는 화면입니다.\n"
     "· 올리면 즉시 점검 — 읽은 행 수, 표준 열, 매뉴얼-기종 연결, "
     "태그 맞물림\n"
     "· 「수리안」이 고칠 수 있는 것을 제안 — 자동은 정답이 계산되는 "
     "것만, 반영 전 이전 판 보존\n"
     "· 수정에는 열쇠가 필요합니다 (보기는 누구나)\n"
     "매뉴얼을 바꾸면 색인 재생성이 필요합니다."),
    (r"도면|p\s*&\s*i\s*d|pid",
     "도면 보기는 태그가 실린 P&ID·결선도·배치도를 엽니다.\n"
     "알람 조회 결과나 판넬 조회에서 바로 열 수 있고, "
     "챗봇으로도 됩니다. 예: AIT-1001 도면 보여줘"),
    (r"공정\s*화면|시뮬레이션|시나리오",
     "공정 화면은 인터락 동작을 눈으로 보는 오프라인 모의 화면입니다.\n"
     "실제 공정과 연결되어 있지 않으며, 조건·세트포인트·지연 시간은 "
     "전부 인터락 리스트에서 읽은 값입니다.\n"
     "P-5101A 인터락 조회 화면에서 「펼치기」, 또는 "
     "\"시나리오 재생해줘\" 라고 말하면 됩니다."),
    (r"자유\s*모드|근거\s*모드|모드",
     "근거 모드(기본)는 등록된 문서에 있는 것만 답하고, 없으면 없다고 "
     "합니다.\n자유 모드는 근거가 없어도 모델의 일반 지식으로 답하되 "
     "「추측」 라벨이 붙고 화면 테두리가 주황색이 됩니다.\n"
     "추측은 조치 순서·4D 리포트·이력에 섞이지 않습니다. "
     "조회 명령의 결과는 모드와 무관하게 같습니다."),
    (r"조치|4\s*d|리포트",
     "조치 순서 생성은 조회된 근거로 점검 순서를 만듭니다 — 근거가 없는 "
     "단계는 만들지 않습니다.\n조치가 끝나면 실제 원인을 기록하고, "
     "그 기록은 다음 사람의 조회에 근거로 뜹니다.\n"
     "4D 리포트는 작업지시서에 첨부할 PDF 로, 근거가 없으면 "
     "\"매뉴얼 근거: 없음\" 이라고 적습니다."),
]


# 공정 화면(오프라인 모의)이 있는 태그. 화면 파일이 실제로 있는 것만
# 적는다 — 목록에 없는 태그를 물었는데 있는 화면을 열어 주면, 사용자는
# 그 태그의 화면을 보고 있다고 믿는다. 지어내는 것보다 나쁘다 (패치 33b).
GRAPHIC_TAGS = ("P-5101A",)


def _graphic_tag(msg, cur_tag):
    """문장이 가리키는 공정 화면 태그. 없으면 (None, 물어본 태그)."""
    asked = find_tag(msg)[0] or None
    if asked:
        return (asked if asked in GRAPHIC_TAGS else None), asked
    if cur_tag and cur_tag in GRAPHIC_TAGS:
        return cur_tag, cur_tag
    return (GRAPHIC_TAGS[0] if len(GRAPHIC_TAGS) == 1 else None), None


def rule_intent(msg: str, cur_tag: str = None, cur_tab: str = None):
    """
    규칙 기반 의도 분석.

    모델이 없을 때의 유일한 경로이고, 챗봇이 지어낸 태그를 대조하는
    기준이기도 하다. 이전에는 챗봇 엔드포인트 안에 중첩되어 있어
    바깥의 req 를 직접 참조했고, 그래서 밖에서 불러 시험할 수 없었다.
    점검할 수 없는 코드는 조용히 깨진다.
    """
    low = msg.lower()

    # 기능 질문 — 명령이 아니라 안내다. 인사말 규칙보다도 먼저 본다.
    # "자료 반입은 무슨 기능이야?" 가 잡담의 '기능 목록' 답변에 걸려
    # 뭉툭한 답이 나가던 것을 여기서 끊는다. 문장에 태그가 직접 적혀
    # 있으면 그 태그를 조회하려는 뜻일 수 있으니 명령 쪽으로 넘긴다.
    if _FEATURE_Q.search(low) and not find_tag(msg)[0]:
        for pat, reply in _FEATURE_HELP:
            if re.search(pat, low):
                return {"type": "chat", "reply": reply}

    # 인사·감사는 조회 의도가 아니다. 예시 목록도 매뉴얼 검색도 아니다.
    st = smalltalk_intent(msg, low)
    if st:
        return st

    # 단자 번호로 태그를 되찾는다 (패치 29c).
    #
    # 판넬 조회가 "IW512+ 1" 처럼 단자 번호를 보여주는데, 그것을 되물으면
    # 답하지 못했다. 도구가 방금 화면에 띄운 값을 모르는 셈이었다.
    # 자료(by_terminal)에는 있으니 규칙으로 잇는다.
    mterm = re.search(r"\b([iqm][wbd]\s?\d{1,4})\s*\+?", low)
    if mterm and re.search(r"태그|뭐|무엇|뭔|어디|누구|어느", low):
        want = re.sub(r"\s+", "", mterm.group(1)).upper()
        px = get_panel()
        if px is None:
            return {"type": "chat",
                    "reply": "배선 자료를 읽지 못해 단자 조회를 할 수 없습니다."}
        found = []
        for prow in px.panels():
            pname = prow.get("panel") if isinstance(prow, dict) else prow
            d = px.by_panel(pname) or {}
            for term, tags in (d.get("by_terminal") or {}).items():
                if re.sub(r"[^A-Z0-9]", "", str(term).upper()) == want:
                    for t2 in tags:
                        found.append((pname, term, t2))
        if not found:
            return {"type": "chat",
                    "reply": "%s 단자를 배선 자료에서 찾지 못했습니다. "
                             "단자 번호를 확인해 주세요." % want}
        # 문장에 판넬명이 함께 있으면 그 판넬로 좁힌다. 단자 번호는
        # 판넬마다 되풀이되므로, 좁히지 않으면 남의 판넬까지 딸려 온다.
        pm = re.search(r"\b((?:cub|rio|jb|lcp)-[a-z0-9]+)\b", low)
        if pm:
            want_p = pm.group(1).upper()
            narrowed = [f for f in found if str(f[0]).upper() == want_p]
            if narrowed:
                found = narrowed

        if len(found) == 1:
            pn, term, t2 = found[0]
            return {"type": "panel", "tab": "panel", "tag": t2,
                    "reply": "%s 단자는 %s 입니다 (%s 판넬 · 단자 %s)."
                             % (want, t2, pn, term)}
        return {"type": "chat",
                "reply": "%s 단자에 %d건이 걸려 있습니다 — %s"
                         % (want, len(found),
                            ", ".join("%s(%s)" % (t2, pn)
                                      for pn, _, t2 in found[:6]))}

    # 판넬 의도를 태그 판정보다 먼저 본다 (표기가 겹치므로)
    pintent = panel_intent(msg, low, cur_tag)
    if pintent:
        return pintent

    tag, miss = find_tag(msg, cur_tag)
    # 문장에 적힌 태그가 목록에 없으면, 현재 화면 태그로 대체하지 않는다.
    # miss 가 있는데 tag=cur_tag 로 넘어가면 다른 설비 답변이 나간다.
    if miss:
        return {"type": "chat",
                "reply": "%s 는 계기 리스트와 인터락 리스트에 없습니다. "
                         "태그를 확인해 주세요." % miss}
    if re.match(r"^(도움|help|사용법|가이드)", low) or msg.strip() == "?":
        return {
            "type": "help",
            "reply": (
                "사용 가이드\n"
                "1) 알람 조회: 태그 선택 → 증상 입력 → 알람 조회\n"
                "2) 원문/도면: 결과에서 원문 보기·도면 보기\n"
                "3) 인터락: 인터락 조회 탭에서 출력 태그\n"
                "4) 자료 반입: 자료 반입 탭에서 파일 올리기 → 반입 점검 확인\n"
                "5) 자유 모드: 사이드바 토글 — 근거 없는 모델 답변이 라벨과 함께 표시\n"
                "6) 자연어 예: AIT-4002 low acid 알람 조회해줘"
            ),
        }
    # 공정 화면(오프라인 시뮬레이션)의 시나리오 재생. 화면은 P-5101A
    # 인터락 뷰에 붙어 있는 기존 기능이고, 챗봇은 그리로 안내·실행만
    # 한다. 시뮬레이션 화면이 있는 태그는 현재 P-5101A 하나다.
    # 시나리오를 멈춰 달라는 말이 먼저다. "정지" 라는 낱말이 인터락 동작
    # (STOP)과 겹쳐서, 아래 인터락 규칙이 먼저 걸리면 "시나리오 정지" 가
    # P-5101A 정지 인터락 조회로 흘렀다. 실제로 그랬다 (패치 33).
    if re.search(r"(시나리오|시뮬레이션|재생|공정\s*화면)[^\n]*"
                 r"(정지|멈춰|멈춤|중지|스톱|stop)"
                 r"|(정지|멈춰|멈춤|중지)[^\n]*(시나리오|시뮬레이션|재생)", low):
        gtag, asked = _graphic_tag(msg, cur_tag)
        if not gtag:
            return {"type": "chat",
                    "reply": "%s 의 공정 화면은 없습니다. 현재 모의 화면이 "
                             "있는 설비는 %s 뿐입니다."
                             % (asked, ", ".join(GRAPHIC_TAGS))}
        return {"type": "interlock", "tag": gtag, "tab": "interlock",
                "action": "OPEN", "openGraphic": True,
                "stopScenario": True, "playScenario": False,
                "reply": "공정 화면의 시나리오 재생을 멈춥니다. "
                         "화면의 값은 멈춘 시점 그대로 남습니다."}

    if re.search(r"시나리오\s*재생|시뮬레이션.*(재생|가동|실행|열|보여)"
                 r"|공정\s*화면", low):
        gtag, asked = _graphic_tag(msg, cur_tag)
        if not gtag:
            return {"type": "chat",
                    "reply": "%s 의 공정 화면은 없습니다. 현재 모의 화면이 "
                             "있는 설비는 %s 뿐입니다. 인터락 조건은 "
                             "'%s 인터락 조회해줘' 로 보실 수 있습니다."
                             % (asked, ", ".join(GRAPHIC_TAGS), asked)}
        play = bool(re.search(r"재생|가동|실행", low))
        return {"type": "interlock", "tag": gtag, "tab": "interlock",
                "action": "OPEN", "openGraphic": True,
                "playScenario": play,
                "reply": "%s 공정 화면(오프라인 시뮬레이션)을 %s. 실제 공정 "
                         "상태가 아닌 시연 화면입니다."
                         % (gtag, "열어 시나리오를 재생합니다" if play
                            else "엽니다")}

    if re.search(r"자료\s*반입|반입|파일\s*(올리|넣|업로드)|업로드", low):
        return {
            "type": "chat",
            "reply": (
                "자료 반입은 「자료 반입」 탭에서 합니다.\n"
                "1) 종류 선택(IO List·계기·TB·인터락·매뉴얼·도면) → 파일 올리기\n"
                "2) 올리면 즉시 반입 점검 리포트 — 몇 행을 읽었는지, "
                "못 읽은 열, 매뉴얼-기종 연결, 태그 맞물림\n"
                "3) 매뉴얼을 바꿨으면 색인 다시 만들기 (진행률 표시)\n"
                "같은 자리 파일은 덮어쓰기 전에 .prev 로 보존되고, "
                "삭제는 2단계(삭제 → 영구 삭제)입니다."
            ),
        }
    # 화면에 이미 결과가 떠 있는 상태에서의 후속 질문은 명령이 아니다.
    #
    # "조회된 내용을 보고 조치방법을 알려줘" 는 '조회' 라는 글자 때문에
    # 다시 알람 조회 명령으로 걸렸고, 같은 조회를 반복하며 대화가
    # 제자리를 돌았다. 이런 문장은 명령이 아니라 방금 결과에 대한
    # 질문이므로 규칙에서 빼고 질의응답으로 넘긴다.
    if re.search(r"(조회된|검색된|나온|방금|위의|이|그|저)\s*(내용|결과|것|거)"
                 r"|결과를?\s*(보고|바탕|기반)|앞서|아까", low):
        return {"type": "followup", "tag": tag, "question": msg}

    # 지시 대명사가 없는 설명 요청도 후속 질문이다 (패치 29).
    #
    # "말로 풀어서 설명해줘" 처럼 가리키는 말이 없으면 위 규칙에 안 걸려
    # 매뉴얼 검색으로 흘렀다. 인터락을 조회한 뒤 이렇게 물으면 직전 알람
    # 근거로 엉뚱한 답이 나왔다. 조회 대상(태그·인터락 같은 낱말)이 없고
    # 설명을 청하는 문장이면, 화면에 떠 있는 결과에 대한 질문으로 본다.
    if re.search(r"(설명|알려|해석|정리)\s*(해|해서|을|를)?\s*"
                 r"(줄|주|달|부탁|가능|해)", low) \
            and not re.search(r"인터락|interlock|도면|p\s*&\s*i\s*d|pid"
                              r"|판넬|panel|반입|업로드|사용법|사용 방법", low) \
            and not find_tag(msg)[0]:
        return {"type": "followup", "tag": tag, "question": msg}

    if re.search(r"도면|p\s*&\s*i\s*d|pid|p&id", low):
        if not tag:
            return {"type": "chat", "reply": "태그를 알려주세요. 예: AIT-1001 P&ID 도면 보여줘"}
        return {"type": "drawing", "tag": tag, "tab": "alarm",
                "reply": "%s 도면을 엽니다." % tag}
    if re.search(r"인터락.*원본|원본.*인터락", low):
        if not tag:
            return {"type": "chat", "reply": "예: LCV-01 인터락 원본 보여줘"}
        act = "CLOSE" if re.search(r"close|닫", low) else (
            "START" if re.search(r"start|기동", low) else (
            "STOP" if re.search(r"stop|정지", low) else "OPEN"))
        return {"type": "interlock_source", "tag": tag, "tab": "interlock",
                "action": act, "openSource": True,
                "reply": "%s 인터락 원본을 엽니다." % tag}
    if re.search(r"인터락|interlock", low):
        if not tag:
            return {"type": "chat", "reply": "예: XV-4101 인터락 조회해줘"}
        act = "CLOSE" if re.search(r"close|닫", low) else (
            "START" if re.search(r"start|기동", low) else (
            "STOP" if re.search(r"stop|정지", low) else "OPEN"))
        return {"type": "interlock", "tag": tag, "tab": "interlock",
                "action": act,
                "reply": "%s %s 인터락을 조회합니다." % (tag, act)}
    if re.search(r"조치|어떻게\s*(해|하나|하면)|뭘\s*해|해결", low):
        # 조치 순서는 조회 결과가 있어야 만들 수 있다. 화면 상태를
        # 아는 챗봇 계층에서 처리하도록 followup 으로 넘긴다.
        return {"type": "followup", "tag": tag, "question": msg,
                "want": "advice"}

    # "…에 대해 설명해줘" 의 '해줘', "…재생해줘" 의 '해줘' 가 조회
    # 명령으로 걸려 화면 태그로 알람 조회를 납치한 일이 있었다.
    # 설명·정의를 묻는 문장과, 조회가 아닌 동사(재생·시뮬레이션 등
    # 이 도구에 없는 기능 요청 포함)는 뺀다 — 모델로 넘어가면 새
    # 프롬프트 규칙이 "그런 기능은 없다" 고 사양한다.
    _asking = re.search(r"설명|뭐야|뭔가요|무엇|사용법|어떤\s*기능"
                        r"|시뮬레이션|재생|불러|틀어|노래|게임|만들어",
                        low)
    if (re.search(r"알람|조회|검색|고장", low) and not _asking) \
            or (tag and re.search(r"해줘|보여", low) and not _asking):
        alarm = re.sub(r"\b([A-Za-z]{1,8}-[A-Za-z0-9]{1,8})\b", " ", msg)
        alarm = re.sub(r"알람|조회|해줘|해주세요|검색|좀|관련", " ", alarm, flags=re.I)
        alarm = re.sub(r"\s+", " ", alarm).strip() or "alarm"
        if not tag:
            return {"type": "chat", "reply": "예: AIT-4002 acid residual low 알람 조회해줘"}
        return {"type": "diagnose", "tag": tag, "tab": "alarm", "alarm": alarm,
                "reply": "%s 알람 조회를 실행합니다." % tag}
    # 아무 규칙에도 걸리지 않은 포괄 응답. LLM 이 더 나은 답을 낼 수
    # 있으므로 generic 표식을 달아, 챗봇에서 덮어쓰지 않게 한다.
    return {
        "type": "chat",
        "generic": True,
        "reply": ("무엇을 도와드릴까요? 태그와 증상을 함께 말씀하시면 알람 "
                  "조회를 실행합니다.\n"
                  "예) AIT-4002 low acid 알람 조회해줘 · XV-4101 인터락 조회 "
                  "· AIT-1001 은 어느 판넬이야 · 사용법"),
    }



class _FixedEvidence:
    """
    이미 화면에 있는 근거를 그대로 쓰는 어댑터.

    후속 질문에 대해 검색을 다시 돌리면 사용자가 보고 있는 것과 다른
    근거로 답할 수 있다. "조회된 내용을 보고" 라는 요청에는 조회된
    그 내용으로 답해야 한다.
    """

    def __init__(self, evidence, ctx):
        self._ev = evidence
        self._ctx = ctx

    def answer(self, **kw):
        return {"decision": "advise",
                "grade": (self._ctx.grade if self._ctx else None) or 0.7,
                "evidence": self._ev}


def _with_free_reply(res, question, tag="", service=""):
    """
    자유 모드에서 근거로 답하지 못했을 때 모델 답변을 덧붙인다.

    근거 없음을 지우지 않고 **뒤에 붙인다**. 자유 모드를 켠 뜻은
    "근거가 없어도 참고할 것을 달라" 이지 "근거 없음을 감춰 달라" 가
    아니다. 못 찾았다는 사실과 참고 답변이 함께 보여야 사용자가 무엇을
    믿을지 스스로 정할 수 있다.
    """
    from graph.advisor import free_reply
    extra = free_reply(question, tag=tag or "", service=service or "")
    if not extra:
        return res.get("reply") or "", False
    head = (res.get("reply") or "").strip()
    return (head + "\n\n〔모델 답변 · 문서 근거 아님〕\n" + extra
            if head else "〔모델 답변 · 문서 근거 아님〕\n" + extra), True


@app.post("/api/chat")
def chat_help(req: ChatRequest):
    """도우미 챗봇. LLM API 가 있으면 의도 분석, 없으면 규칙 기반."""
    import re
    import json as _json
    import urllib.request

    text = (req.message or "").strip()
    if not text:
        raise HTTPException(400, "message 필요")

    # 대화 모델 호출은 조치 생성과 같은 게이트웨이를 쓴다.
    #
    # 이전에는 여기서 provider 를 따로 해석했고, 목록이
    # ("openai","azure","llm") 이라 COPILOT_PROVIDER=ollama 를 넣으면
    # 조치 생성은 켜지는데 챗봇만 조용히 규칙 엔진으로 떨어졌다.
    # 같은 환경변수가 두 곳에서 다른 뜻을 갖고 있었고, 그 사실이
    # 화면 어디에도 드러나지 않았다. 게이트웨이를 하나로 합친다.
    from graph.advisor import _CHAT, _parse

    ACTIONABLE = {"diagnose", "drawing", "interlock", "interlock_source",
                  "advice", "help", "navigate", "panel"}
    NEEDS_TAG = {"diagnose", "drawing", "interlock", "interlock_source",
                 "advice"}

    def finalize(data, source):
        """태그를 실재하는 것으로 되돌리고, 없으면 되묻는다."""
        data.setdefault("type", "chat")
        data.setdefault("reply", "요청을 처리합니다.")
        t = normalize_tag(data.get("tag"))
        if t:
            data["tag"] = t
        else:
            data.pop("tag", None)
        if data["type"] in NEEDS_TAG and not data.get("tag"):
            data["type"] = "chat"
            data["reply"] = ("어느 태그인지 알려주세요. "
                             "예: LCV-01 인터락 조회 / AIT-4002 알람 조회")
        data["engine"] = source
        return data

    def looks_like_question(t):
        """UI 명령이 아니라 도메인 질문인가."""
        if len(t) < 6:
            return False
        # 물음표 하나로 도메인 질문이라고 보면 안 된다. "인사 안 해주고
        # 예시를 들어주네?" 같은 말이 매뉴얼 검색으로 넘어가 "근거를 찾지
        # 못했습니다" 가 나온다. 의문사·요청어가 실제로 있어야 한다.
        # "뭐지·뭐야" 처럼 흔한 말꼬리가 빠져 있어, 자유 모드인데도 모델에
        # 물어보지 않고 안내문만 돌려주는 일이 있었다 (패치 29c).
        if re.search(r"(어떻게|왜|무엇|뭐|뭔|어디|언제|얼마|방법|절차|"
                     r"주기|원인|의미|뜻|차이|기준|규격|사양|알려|설명|"
                     r"인가요|하나요|되나요|일까|인지|점검|조치|확인|"
                     r"누구|몇|가능한|되는지|맞나|맞는지)", t):
            return True
        return False

    # 규칙 엔진을 먼저 돌린다.
    #
    # 이전에는 LLM 이 우선이었고, 규칙은 LLM 이 없을 때의 대체 경로였다.
    # 그런데 7B 급 모델은 이 작업에서 규칙보다 못하다. "LCV-01 인터락
    # 조회해줘" 에 type=chat 과 "인터락 정보를 조회하겠습니다" 를 돌려주면,
    # 화면은 실행하지 않고 사용자는 왜 안 되는지 알 수 없다.
    #
    # 규칙 엔진은 이 앱이 지원하는 명령을 정확히 덮고 결정적이다.
    # 규칙이 실행 가능한 의도를 뽑아내면 그것을 쓰고, 규칙이 못 알아들은
    # 표현에 한해 LLM 에 물어본다. 이 순서가 시연에서도 안전하다 —
    # 같은 문장에 같은 동작이 나온다.
    rule = rule_intent(text, req.tag,
                       (req.context.tab if req.context else None)
                       or req.tab) or {}
    if rule.get("type") in ACTIONABLE:
        return finalize(rule, "rule")

    # 규칙이 구체적인 답(chat, generic 아님)을 냈으면 그대로 확정한다.
    # QA/LLM 으로 넘기면 정해진 사실 — "그 태그는 목록에 없다",
    # "자료 반입은 이 탭에서 한다" — 를 모델이 덮어쓰거나 지어낸다.
    # 실제로 "자료 반입에 대해 설명해줘" 가 QA 로 넘어가 "근거를 찾지
    # 못했습니다" 로 덮인 일이 있었다. generic(아무것도 못 알아들음)
    # 만 아래 QA·LLM 층으로 내려보낸다.
    if (rule.get("type") == "chat" and rule.get("reply")
            and not rule.get("generic")):
        return finalize(rule, "rule")

    # 후속 질문 — 화면에 떠 있는 결과를 근거로 답한다.
    #
    # 이 경로가 없으면 챗봇은 매 메시지를 독립 명령으로 보고 같은
    # 조회를 반복한다. 사용자는 결과를 보며 묻는데 챗봇만 그것을
    # 모르는 상태였다.
    if rule.get("type") == "followup":
        ctx = req.context
        ev = (ctx.evidence if ctx else None) or []

        # 인터락 결과가 화면에 떠 있으면 그것으로 답한다. 알람 근거로
        # 답하면 사용자가 보는 것과 다른 주제가 나온다 (패치 29).
        il = (ctx.interlock if ctx else None) or None
        on_interlock_tab = bool(ctx and (ctx.tab or "") == "interlock")
        if il and (on_interlock_tab or not ev):
            from retrieval.interlock_describe import describe, citations
            return {"type": "chat", "engine": "followup-interlock",
                    "reply": describe(il), "grounded": True,
                    "citations": citations(il)}
        if on_interlock_tab and not il:
            return finalize({"type": "chat",
                             "reply": "인터락 조회 결과가 화면에 없습니다. "
                                      "태그와 동작을 골라 조회한 뒤 다시 "
                                      "물어봐 주세요."}, "rule")

        if not ev:
            return finalize({"type": "chat",
                             "reply": "아직 조회 결과가 없습니다. 먼저 "
                                      "태그와 증상으로 알람을 조회해 주세요. "
                                      "예: AIT-4002 acid residual low 알람 조회해줘"},
                            "rule")
        # "조회된 내용을 보고 조치방법을 알려줘" 처럼 두 규칙에 걸친
        # 문장이 있으므로 질문 본문에서 다시 판별한다.
        want = rule.get("want")
        if not want and re.search(r"조치|어떻게\s*(해|하나|하면)|뭘\s*해|해결",
                                  rule.get("question", "")):
            want = "advice"
        try:
            if want == "advice":
                from graph.advisor import generate
                res = generate(ctx.tag, ctx.alarm or rule["question"], ev)
                lines = [res.get("summary") or "확인 순서입니다."]
                for i, st in enumerate(res["steps"], 1):
                    lines.append("%d. %s — %s" % (i, st["title"], st["detail"]))
                return {"type": "chat", "engine": "advice",
                        "reply": "\n".join(lines),
                        "grounded": True,
                        "citations": [{"id": e["id"],
                                       "title": e.get("title", ""),
                                       "cite": e.get("cite", "")}
                                      for e in ev[:3]]}
            from graph.qa import answer as qa_answer
            res = qa_answer(rule["question"], tag=ctx.tag,
                            copilot=_FixedEvidence(ev, ctx),
                            instruments=load_instruments())
            reply, added = res["reply"], False
            if not res["ok"] and req.free:
                reply, added = _with_free_reply(res, rule["question"],
                                                tag=ctx.tag)
            return {"type": "chat", "engine": "followup",
                    "reply": reply, "grounded": res["ok"],
                    "free": added,
                    "citations": [{"id": e["id"],
                                   "title": e.get("title", ""),
                                   "cite": e.get("cite", "")}
                                  for e in (res.get("evidence") or [])[:3]]}
        except Exception as e:                              # noqa: BLE001
            return finalize({"type": "chat",
                             "reply": "결과를 해석하지 못했습니다: %s"
                                      % str(e)[:110]}, "rule")

    # 명령이 아니고 도메인 질문으로 보이면 매뉴얼 근거로 답한다.
    #
    # 챗봇이 검색·판정·근거 검증을 쓰지 않고 명령 해석만 하고 있었다.
    # 같은 부품을 대화 경로에도 연결한다. 근거가 부족하면 여기서도
    # 지어내지 않고 모른다고 답한다.
    if config.CHAT_QA and looks_like_question(text):
        try:
            from graph.qa import answer as qa_answer
            res = qa_answer(text, tag=normalize_tag(req.tag),
                            mode=DEFAULT_MODE, copilot=get_copilot(DEFAULT_MODE),
                            instruments=load_instruments())
            # 근거로 답하지 못했을 때, 자유 모드면 여기서 끝내지 않고
            # 아래 자유 경로로 넘긴다. 자유 모드를 켠 사용자에게
            # "근거를 못 찾았습니다" 로 끝내면 모드를 켠 뜻이 없다.
            reply, added = res["reply"], False
            if not res["ok"] and req.free:
                reply, added = _with_free_reply(res, text,
                                                tag=normalize_tag(req.tag))
            return {"type": "chat", "engine": "qa",
                    "reply": reply,
                    "grounded": res["ok"],
                    "free": added,
                    "grade": res.get("grade"),
                    "citations": [{"id": e["id"],
                                   "title": e.get("title", ""),
                                   "cite": e.get("cite", "")}
                                  for e in (res.get("evidence") or [])[:3]]}
        except Exception as e:                              # noqa: BLE001
            pass    # 실패하면 아래 일반 대화 경로로 내려간다

    provider = config.LLM_PROVIDER
    if not (req.use_llm and provider in _CHAT):
        out = finalize(rule, "rule")
        out["llm_reason"] = ("COPILOT_PROVIDER=%s" % provider
                             if req.use_llm else "요청에서 비활성")
        return out

    # 자유 모드의 대화 지침.
    #
    # 명령 해석 스키마는 그대로 둔다 — 조회는 모드와 무관하게 정확해야
    # 한다. 달라지는 것은 type=chat 일 때의 답변 폭이다. 근거 모드는
    # 도구 안내로 한정하고, 자유 모드는 일반 지식으로 답하되 두 가지를
    # 지킨다: 조회 결과(판넬 위치·인터락 조건·매뉴얼 페이지)를 지어내지
    # 않는다, 기술 판단에는 문서 근거가 아님을 밝힌다.
    free_clause = (
        "지금 자유 모드가 켜져 있습니다 (모드를 물으면 켜져 있다고 "
        "답하십시오). 질문이나 대화이면 type=chat 으로 두고 reply 에 "
        "한국어로 자유롭게 답하십시오. 일반적인 정비 지식·개념 설명은 "
        "됩니다. 다만 다음은 지키십시오. "
        "(1) 이 도구의 조회 결과 — 특정 태그의 판넬 위치, 인터락 조건, "
        "매뉴얼 페이지 — 를 지어내지 마십시오. 그런 질문에는 해당 조회 "
        "기능을 안내하십시오. "
        "(2) 기술적 판단을 담은 답에는 문서 근거가 아니라 일반 지식이라는 "
        "점을 한 줄로 밝히십시오. "
        "(3) reply 는 대화 답변일 뿐 아무것도 실행하지 않습니다 — "
        "'조회하겠습니다', '확인해보겠습니다' 처럼 실행을 약속하는 문장을 "
        "쓰지 마십시오. 실행이 필요하면 type 을 해당 명령으로 정하십시오. "
        "(4) 노래·게임·역할극 등 정비 도구 범위 밖의 요청은 할 수 있는 "
        "척하지 말고, 정비 지원 도구라 어렵다고 한 줄로 사양하십시오."
        if req.free else
        "명령이 아니라 질문이나 인사이면 type=chat 으로 두고 reply 에 "
        "한국어로 자연스럽게 답하십시오. 기능을 물으면 위 목록을 바탕으로 "
        "두세 문장으로 설명하고, 바로 써 볼 수 있는 예시를 한 줄 "
        "덧붙이십시오.")

    system = (
        "당신은 Plant Maintenance Copilot 의 도우미입니다. "
        "플랜트 정비원이 쓰는 도구이며, 다음을 할 수 있습니다.\n"
        "- 알람 조회: 설비 태그와 증상을 주면 벤더 매뉴얼과 에러코드표에서 "
        "원인·조치를 찾아 출처(문서·페이지)와 함께 보여줍니다. 증상은 "
        "한국어로 써도 되고 매뉴얼이 영문이어도 찾습니다.\n"
        "- 근거가 부족하면 답을 지어내지 않고 근거 부재를 알립니다.\n"
        "- 보수 이력 대조: 같은 설비에서 과거에 있었던 조치를 함께 보여줍니다.\n"
        "- 인터락 조회: 밸브·펌프가 왜 안 움직이는지, 동작 조건을 "
        "인터락·퍼미시브·시퀀스로 나누어 보여주고 엑셀 원본과 대조합니다.\n"
        "- 도면: 태그가 표시된 P&ID 위치와 배선 정보를 보여줍니다.\n"
        "- 4D 리포트: 조회 결과를 PDF 보고서로 출력합니다.\n"
        "- 공정 화면(P-5101A): 오프라인 모의 화면을 열고, 시나리오를 "
        "재생하거나 재생 중인 것을 멈춥니다. 실제 공정이 아닙니다.\n\n"
        "사용자 메시지를 UI 명령 JSON 으로 해석하십시오. " + free_clause + "\n"
        "Reply language: Korean.\n"
        "Schema:\n"
        '{"type":"diagnose|drawing|interlock|interlock_source|advice|help|chat|navigate",'
        '"tag":"AIT-4002 or null","tab":"alarm|interlock","alarm":"symptom text or null",'
        '"action":"OPEN|CLOSE|START|STOP or null","openSource":false,'
        '"openGraphic":false,"playScenario":false,"stopScenario":false,'
        '"reply":"short Korean confirmation"}\n'
        "Rules: do not invent tags; if tag missing ask in reply with type=chat. "
        "For alarm search type=diagnose. For P&ID type=drawing. For interlock type=interlock. "
        "공정 화면을 열어 달라면 type=interlock, tag=P-5101A, openGraphic=true 로 "
        "두십시오. 재생은 playScenario=true, 재생을 멈춰 달라는 말(정지·멈춰·중지)은 "
        "stopScenario=true 로 두고 playScenario 는 false 로 두십시오. "
        "여기서 '정지'는 시나리오 재생을 멈추라는 뜻이며, 펌프 정지 인터락 조회와 "
        "다릅니다. 어느 쪽인지 분명하지 않으면 실행하지 말고 type=chat 으로 "
        "무엇을 원하는지 되물으십시오. "
        "reply 는 아무것도 실행하지 않으니 실행을 약속하는 문장을 쓰지 마십시오. 범위 밖 요청(노래 등)은 한 줄로 사양하십시오."
    )
    user = "current_tab=%s current_tag=%s\nuser: %s" % (req.tab, req.tag, text)

    try:
        content = _CHAT[provider](
            [{"role": "system", "content": system},
             {"role": "user", "content": user}], 45)
        data = _parse(content)
        out = finalize(data, "llm")
        out["provider"] = provider
        # 규칙이 구체적인 안내를 갖고 있으면 그것을 우선한다
        # (없는 태그·태그 누락 등). 다만 포괄 응답(generic)은 예외다 —
        # 그건 "아무것도 못 알아들었다"는 뜻이라, LLM 의 답을 덮으면
        # "너는 어떤 기능이 있니" 같은 질문에 예시만 반복하게 된다.
        if (out["type"] == "chat" and rule.get("reply")
                and not rule.get("generic")):
            out["reply"] = rule["reply"]
        out.pop("generic", None)
        # 자유 모드의 대화 답변은 근거가 없다는 표식을 싣는다.
        # 화면이 이 표식으로 라벨을 붙인다 — 표식 없이 내보내면
        # 근거 기반 답변(qa·followup)과 구분되지 않는다.
        if req.free and out.get("type") == "chat":
            out["free"] = True
            out["grounded"] = False
        return out
    except Exception as e:                                  # noqa: BLE001
        out = finalize(rule, "rule_fallback")
        out["llm_error"] = str(e)[:160]
        return out


@app.get("/api/chat/status")
def chat_status():
    provider = os.environ.get("COPILOT_PROVIDER", "rule").lower()
    has_key = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY"))
    return {
        "provider": provider,
        "llm_ready": provider in ("openai", "azure", "llm") and has_key,
        "model": os.environ.get("COPILOT_CHAT_MODEL") or os.environ.get("COPILOT_MODEL") or "gpt-4o-mini",
        "base_url": os.environ.get("OPENAI_BASE_URL", ""),
    }


# ── PDF / 도면 렌더 (v1 manuals.py 동일 방식) ────────────────
def _norm_name(name):
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _list_pdfs(folder):
    """하위 폴더까지 훑는다 — 실물 매뉴얼은 벤더별 폴더로 들어온다."""
    if not os.path.isdir(folder):
        return []
    out = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".pdf") and not f.startswith("~$"):
                rel = os.path.relpath(os.path.join(root, f),
                                      folder).replace("\\", "/")
                # 벤더 폴더 이름이 한글이면 파일시스템 인코딩에 따라
                # 디코딩되지 않은 바이트가 섞여 들어온다. 그대로 JSON 으로
                # 내보내면 응답 전체가 500 으로 죽는다 — 매뉴얼 목록이
                # 통째로 안 뜨는데 이유는 안 보이는 형태가 된다.
                out.append(rel)
    return sorted(out)


def _safe_name(s):
    """JSON 으로 내보낼 수 있는 이름.

    벤더 폴더 이름이 한글인데 파일시스템 인코딩과 어긋나면 디코딩되지
    않은 바이트가 문자열에 남는다. 그대로 응답에 실으면 JSON 인코딩에서
    500 이 나 매뉴얼 목록이 통째로 안 뜬다. 윈도우에서는 대개 그대로
    통과하므로 이 함수는 아무것도 바꾸지 않는다.
    """
    return str(s).encode("utf-8", "replace").decode("utf-8")


def _resolve_pdf(file_name, folder):
    if not file_name or not os.path.isdir(folder):
        return None
    exact = os.path.join(folder, file_name)
    if os.path.exists(exact):
        return exact
    # 목록을 안전한 이름으로 내보냈다면 그 이름으로 되돌아온다 — 원래
    # 파일로 되짚는다. 이 되짚기가 없으면 목록은 뜨는데 클릭하면 안 열린다.
    for f in _list_pdfs(folder):
        if _safe_name(f) == file_name:
            return os.path.join(folder, f)
    want = _norm_name(os.path.splitext(file_name)[0])
    best, best_len = None, 0
    for f in _list_pdfs(folder):
        got = _norm_name(os.path.splitext(os.path.basename(f))[0])
        if want and (want in got or got in want):
            n = min(len(want), len(got))
            if n > best_len:
                best, best_len = os.path.join(folder, f), n
    return best


def _open_pdf(path):
    """PDF 를 **바이트로 읽어서** 연다.

    경로를 그대로 넘기면 벤더 폴더 이름이 비ASCII 일 때 MuPDF 의 C 계층이
    경로를 받지 못해 열기부터 실패한다. 파일은 멀쩡한데 화면에는 '렌더
    실패' 만 뜬다. 바이트로 넘기면 경로 인코딩이 개입하지 않는다.
    """
    import fitz
    with open(path, "rb") as fh:
        return fitz.open(stream=fh.read(), filetype="pdf")


def _render_page(path, page_no, dpi=150):
    try:
        import fitz
    except ImportError:
        return None
    if not path or not os.path.exists(path):
        return None
    try:
        with _open_pdf(path) as d:
            i = max(1, min(int(page_no), len(d))) - 1
            return d[i].get_pixmap(dpi=dpi).tobytes("png")
    except Exception:
        return None


def _render_drawing(path, page_no, tag=None, dpi=140, margin=110, band=False):
    try:
        import fitz
    except ImportError:
        return None, None, 0
    if not path or not os.path.exists(path):
        return None, None, 0
    try:
        with _open_pdf(path) as d:
            i = max(1, min(int(page_no), len(d))) - 1
            pg = d[i]
            terms = [t for t in (tag or "").split("|") if t]
            rects, focus = [], []
            for t in terms:
                got = pg.search_for(t)
                rects.extend(got)
                if got and not focus:
                    focus = got
            if rects:
                sh = pg.new_shape()
                for r in rects:
                    sh.draw_rect(fitz.Rect(r.x0 - 9, r.y0 - 9, r.x1 + 9, r.y1 + 9))
                sh.finish(color=(0.82, 0.0, 0.17), width=1.6)
                sh.commit()
            full = pg.get_pixmap(dpi=dpi).tobytes("png")
            crop = None
            if focus:
                r = focus[0]
                if band:
                    box = fitz.Rect(pg.rect.x0 + 8, r.y0 - margin,
                                    pg.rect.x1 - 8, r.y1 + margin) & pg.rect
                    scale = 1.4
                else:
                    box = fitz.Rect(r.x0 - margin, r.y0 - margin,
                                    r.x1 + margin, r.y1 + margin) & pg.rect
                    scale = 2.0
                crop = pg.get_pixmap(dpi=int(dpi * scale), clip=box).tobytes("png")
            return full, crop, len(rects)
    except Exception:
        return None, None, 0


@app.get("/api/manual-status")
def manual_status():
    try:
        import fitz  # noqa: F401
        have = True
    except ImportError:
        have = False
    files = _list_pdfs(config.MANUAL_DIR)
    demo_pdfs = _list_pdfs(config.DRAWING_DIR) if os.path.isdir(config.DRAWING_DIR) else []
    return {
        "pymupdf": have,
        "manual_dir": config.MANUAL_DIR,
        "manual_count": len(files),
        "manuals": [_safe_name(f) for f in files],
        "demo_dir": config.DRAWING_DIR,
        "demo_pdfs": [_safe_name(f) for f in demo_pdfs],
    }


@app.get("/api/manual-page")
def manual_page(
    file: str = Query(..., description="PDF 파일명"),
    page: int = Query(1, ge=1),
    dpi: int = Query(160, ge=72, le=400),
):
    path = _resolve_pdf(file, config.MANUAL_DIR)
    if not path:
        # demo_data 쪽도 한번 찾아봄
        path = _resolve_pdf(file, config.DRAWING_DIR)
    if not path:
        raise HTTPException(404, f"PDF 없음: {file} (dir={config.MANUAL_DIR})")
    png = _render_page(path, page, dpi=dpi)
    if not png:
        raise HTTPException(500, "페이지 렌더 실패 (pymupdf 확인)")
    # HTTP 헤더는 latin-1 만 담을 수 있다. 벤더 폴더 이름이 한글이면
    # 경로를 그대로 넣는 순간 인코딩에서 터져 응답이 500 이 된다 —
    # 렌더는 멀쩡히 끝났는데 화면에는 PDF 가 안 뜨는 형태가 된다.
    from urllib.parse import quote
    return Response(content=png, media_type="image/png", headers={
        "Cache-Control": "public, max-age=3600",
        "X-PDF-Path": quote(_safe_name(path), safe="/"),
    })


@app.get("/api/drawing-page")
def drawing_page(
    file: str = Query(...),
    page: int = Query(1, ge=1),
    find: str = Query(""),
    crop: int = Query(1, ge=0, le=1),
    dpi: int = Query(160, ge=72, le=400),
):
    # 도면 PDF 는 demo_data 에 있음
    # 자료는 전부 data/ 아래에 있다. 도면 → 매뉴얼 → data 루트 순.
    path = _resolve_pdf(file, config.DRAWING_DIR)
    if not path:
        path = _resolve_pdf(file, config.MANUAL_DIR)
    if not path:
        path = _resolve_pdf(file, config.DATA_DIR)
    if not path:
        path = _resolve_pdf(file, config.DRAWING_DIR)
    if not path:
        raise HTTPException(404, f"도면 PDF 없음: {file}")
    full, cropped, hits = _render_drawing(path, page, tag=find or None, dpi=dpi)
    if not full:
        raise HTTPException(500, "도면 렌더 실패")
    body = cropped if (crop and cropped) else full
    return Response(content=body, media_type="image/png", headers={
        "Cache-Control": "public, max-age=3600",
        "X-Hits": str(hits),
        "X-Has-Crop": "1" if cropped else "0",
    })


# ════════════════════════════════════════════════════════════
#  자료 반입
#
#  본체는 파일 받기가 아니라 **반입 직후 점검**이다. 지금까지 찾은
#  결함 여섯 종은 전부 자료를 넣는 시점에 생겼고, 답이 안 나오는
#  형태가 아니라 그럴듯한 답이 나오되 틀린 형태였다. 그래서 넣자마자
#  몇 행을 읽었는지, 못 읽은 것은 무엇인지, 문서 사이 태그가 얼마나
#  맞물리는지를 리포트로 보인다. 판정은 하지 않는다 — 어느 쪽이
#  맞는지는 데이터 주인이 안다.
# ════════════════════════════════════════════════════════════
import threading

# 업로드 종류 → 저장 위치. 파일명이 아니라 종류를 받는 이유:
# 로더가 고정 이름(IO_LIST.xlsx 등)을 찾으므로, 사용자가 무슨 이름으로
# 올리든 그 자리에 놓아야 반영된다.
_INGEST_DEST = {
    "io":         lambda name: str(config.IO_LIST),
    "instrument": lambda name: os.path.join(str(config.DATA_DIR), "INSTRUMENT_LIST.xlsx"),
    "tb":         lambda name: os.path.join(str(config.DATA_DIR), "TB_LIST.xlsx"),
    "interlock":  lambda name: os.path.join(str(config.INTERLOCK_DIR), name),
    "manual":     lambda name: os.path.join(str(config.MANUAL_DIR), name),
    "drawing":    lambda name: os.path.join(str(config.DRAWING_DIR), name)
                  if getattr(config, "DRAWING_DIR", None)
                  else os.path.join(str(config.DATA_DIR), "drawings", name),
}

_rebuild = {"running": False, "stage": "", "done": 0, "total": 0,
            "error": "", "finished_at": ""}


def _reset_caches():
    """자료가 바뀌면 읽어 둔 것을 전부 버린다. 안 버리면 화면은 옛
    자료로 답하면서 점검 리포트만 새 자료를 보는, 둘이 다른 말을 하는
    상태가 된다."""
    global _instruments, _io_points, _history, _drawings, _interlock
    global _panel, _panel_error, _copilots
    _instruments = None
    _io_points = None
    _history = None
    _drawings = None
    _interlock = None
    _panel = None
    _panel_error = None
    _copilots.clear()



# ── 반입 편집 권한 + 동시 잠금 ──────────────────────────────
#
# 배포는 여러 사람이 같이 보는 한 대의 서버다. 한 사람의 시험이
# 모두의 화면을 바꾼다. 그래서 두 겹으로 잠근다.
#
#   1) 열쇠(권한) — COPILOT_INGEST_KEY 가 설정되어 있으면, 자료를
#      바꾸는 조작(업로드·삭제·재생성)은 열쇠가 맞아야 한다.
#      목록·받기·점검은 누구나 볼 수 있다. 기능을 감추는 것이
#      아니라 바꾸는 손만 제한한다.
#   2) 편집 임대(동시 잠금) — 열쇠가 맞아도 한 번에 한 사람만
#      편집한다. 임대는 시간이 지나면 저절로 풀린다(기본 5분,
#      조작마다 연장). 브라우저를 닫고 사라진 편집자가 잠금을
#      영원히 쥐는 상황을 만들지 않기 위해서다.
#
# 열쇠가 설정되지 않은 로컬 실행에서는 둘 다 비활성 — 지금처럼
# 자유롭게 쓴다.

_edit_lease = {"owner": "", "until": 0.0}
_LEASE_SEC = 300


def _ingest_key():
    return (os.environ.get("COPILOT_INGEST_KEY") or "").strip()


def _lease_state():
    import time
    alive = _edit_lease["owner"] and _edit_lease["until"] > time.time()
    return {
        "protected": bool(_ingest_key()),
        "locked_by_other": False,   # 호출자 기준으로 아래에서 채움
        "editing": bool(alive),
        "owner_hint": (_edit_lease["owner"][:4] + "…") if alive else "",
        "remain": max(0, int(_edit_lease["until"] - time.time())) if alive else 0,
    }


def _require_edit(request: Request):
    """자료를 바꾸는 조작 앞에 세우는 문. 열쇠 → 임대 순서로 본다."""
    import time
    key = _ingest_key()
    if not key:
        return                       # 로컬 — 잠금 없음
    got = (request.headers.get("X-Ingest-Key") or "").strip()
    if got != key:
        raise HTTPException(401, "수정 열쇠가 필요합니다. 반입 화면 상단에 "
                                 "열쇠를 입력하십시오.")
    # 편집자 식별은 열쇠+브라우저가 보낸 세션표 (없으면 접속 주소)
    who = (request.headers.get("X-Ingest-Session") or
           (request.client.host if request.client else "?"))
    now = time.time()
    if _edit_lease["owner"] and _edit_lease["until"] > now             and _edit_lease["owner"] != who:
        raise HTTPException(423, "다른 편집자가 작업 중입니다 (%d초 후 "
                            "자동 해제). 잠시 뒤 다시 시도하십시오."
                            % int(_edit_lease["until"] - now))
    _edit_lease["owner"] = who
    _edit_lease["until"] = now + _LEASE_SEC


@app.get("/api/ingest/edit-state")
def ingest_edit_state(request: Request):
    import time
    st = _lease_state()
    who = (request.headers.get("X-Ingest-Session") or
           (request.client.host if request.client else "?"))
    st["locked_by_other"] = bool(
        st["editing"] and _edit_lease["owner"] != who)
    # 열쇠 검증도 여기서 해 준다 — 화면이 입력 즉시 맞는지 보여주게.
    got = (request.headers.get("X-Ingest-Key") or "").strip()
    st["key_ok"] = (not st["protected"]) or (got == _ingest_key())
    return st


@app.post("/api/ingest/edit-release")
def ingest_edit_release(request: Request):
    """편집을 마친 사람이 임대를 바로 돌려준다. 시간 만료를 기다리지
    않아도 되게 하는 예의 장치일 뿐, 안 눌러도 5분이면 풀린다."""
    who = (request.headers.get("X-Ingest-Session") or
           (request.client.host if request.client else "?"))
    if _edit_lease["owner"] == who:
        _edit_lease["owner"] = ""
        _edit_lease["until"] = 0.0
    return {"ok": True}



@app.get("/api/ingest/report")
def ingest_report():
    # 점검 전에 읽어 둔 캐시를 버린다. 사용자가 화면을 거치지 않고
    # 폴더에 파일을 직접 넣는 경우 서버는 알 길이 없다 — "다시 점검"
    # 이 곧 "다시 읽기" 여야 리포트와 조회 화면이 같은 자료를 본다.
    if not _rebuild["running"]:
        _reset_caches()
    from ingest.inspect import inspect_dataset
    return inspect_dataset()


@app.post("/api/ingest/upload")
async def ingest_upload(request: Request,
                        kind: str = Query(...),
                        name: str = Query(...)):
    _require_edit(request)
    """
    본문 = 파일 바이트 그대로. multipart 를 쓰지 않는 이유는 의존성
    (python-multipart) 을 하나 늘리지 않기 위해서다 — 배포 이미지와
    로컬 환경 둘 다에 영향을 준다.
    """
    if _rebuild["running"]:
        raise HTTPException(409, "색인 재생성 중에는 반입할 수 없습니다")
    if kind not in _INGEST_DEST:
        raise HTTPException(400, "kind 는 %s 중 하나여야 합니다"
                            % "/".join(_INGEST_DEST))
    safe = os.path.basename(name).strip()
    if not safe or safe.startswith("."):
        raise HTTPException(400, "파일 이름이 올바르지 않습니다")
    if kind in ("io", "instrument", "tb", "interlock") \
            and not safe.lower().endswith(".xlsx"):
        raise HTTPException(400, "리스트는 .xlsx 파일이어야 합니다")
    if kind in ("manual", "drawing") and not safe.lower().endswith(".pdf"):
        raise HTTPException(400, "매뉴얼·도면은 .pdf 파일이어야 합니다")

    body = await request.body()
    if not body:
        raise HTTPException(400, "빈 파일입니다")
    dest = _INGEST_DEST[kind](safe)
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    # 같은 자리에 파일이 있으면 덮어쓰기 전에 한 벌 남긴다. 색인 덮임
    # 사고에서 배운 것 — 되돌릴 수 없는 덮어쓰기를 만들지 않는다.
    replaced = False
    if os.path.isfile(dest):
        replaced = True
        try:
            os.replace(dest, dest + ".prev")
        except OSError:
            pass
    with open(dest, "wb") as f:
        f.write(body)
    _reset_caches()

    return {"saved": os.path.basename(dest),
            "dir": os.path.dirname(dest),
            "bytes": len(body),
            "replaced": replaced,
            "note": "색인 대상(매뉴얼)이 바뀐 경우 색인을 다시 만들어야 "
                    "검색에 반영됩니다. 리스트류는 즉시 반영됩니다."}


def _rebuild_worker():
    try:
        _rebuild.update(stage="청킹·코드표", done=0, total=0, error="")
        from ingest.build_index import build as build_chunks
        build_chunks()

        _rebuild.update(stage="임베딩")
        from retrieval.dense import DenseIndex
        from ingest.build_index import load as load_chunks
        di = DenseIndex(load_chunks())

        def prog(done, total):
            _rebuild.update(done=done, total=total)
        di.build(progress=prog)

        _reset_caches()
        _rebuild.update(stage="완료",
                        finished_at=dt.datetime.now().strftime("%H:%M:%S"))
    except Exception as e:                                  # noqa: BLE001
        _rebuild.update(error="%s: %s" % (type(e).__name__, str(e)[:160]),
                        stage="실패")
    finally:
        _rebuild["running"] = False


@app.post("/api/ingest/rebuild")
def ingest_rebuild(request: Request):
    _require_edit(request)
    if _rebuild["running"]:
        raise HTTPException(409, "이미 재생성 중입니다")
    _rebuild.update(running=True, stage="시작", done=0, total=0,
                    error="", finished_at="")
    threading.Thread(target=_rebuild_worker, daemon=True).start()
    return {"started": True,
            "index_dir": str(config.INDEX_DIR),
            "warning": "몇 분 걸립니다. 진행 상태는 /api/ingest/status 로 "
                       "확인합니다."}



# ── 자료 파일 목록·다운로드·삭제 ────────────────────────────
#
# 삭제는 두 단계다. 먼저 .deleted 로 이름을 바꿔 앱에서 안 보이게
# 하고(로더가 원래 확장자만 찾는다), 영구 삭제는 .deleted 상태의
# 파일에만 허용한다. 실수 한 번으로 되돌릴 수 없게 되는 조작을
# 만들지 않는다 — .prev 보존과 같은 원칙이다.

_INGEST_FOLDERS = {
    "root":      lambda: str(config.DATA_DIR),
    "interlock": lambda: str(getattr(config, "INTERLOCK_DIR", "") or ""),
    "manuals":   lambda: str(getattr(config, "MANUAL_DIR", "") or ""),
    "drawings":  lambda: str(getattr(config, "DRAWING_DIR", "") or
                             os.path.join(str(config.DATA_DIR), "drawings")),
}


def _ingest_path(folder: str, name: str) -> str:
    """폴더 밖으로 나가는 경로를 막는다. ../ 나 절대경로로 데이터
    폴더 밖 파일을 집는 구멍이 생기면 다운로드가 유출구가 된다."""
    if folder not in _INGEST_FOLDERS:
        raise HTTPException(400, "folder 는 %s 중 하나여야 합니다"
                            % "/".join(_INGEST_FOLDERS))
    base = _INGEST_FOLDERS[folder]()
    if not base or not os.path.isdir(base):
        raise HTTPException(404, "폴더가 없습니다: %s" % folder)
    safe = os.path.basename(name).strip()
    if not safe or safe != name or safe.startswith("."):
        raise HTTPException(400, "파일 이름이 올바르지 않습니다")
    path = os.path.join(base, safe)
    if os.path.commonpath([os.path.abspath(path),
                           os.path.abspath(base)]) != os.path.abspath(base):
        raise HTTPException(400, "경로가 폴더를 벗어납니다")
    return path


@app.get("/api/ingest/files")
def ingest_files():
    out = {}
    for key, fn in _INGEST_FOLDERS.items():
        base = fn()
        rows = []
        if base and os.path.isdir(base):
            for n in sorted(os.listdir(base)):
                p = os.path.join(base, n)
                if not os.path.isfile(p):
                    continue
                if key == "root" and not n.lower().endswith(
                        (".xlsx", ".xlsx.prev", ".xlsx.deleted", ".csv")):
                    continue                         # 루트의 잡파일은 제외
                st = os.stat(p)
                rows.append({
                    "name": n,
                    "bytes": st.st_size,
                    "mtime": dt.datetime.fromtimestamp(st.st_mtime)
                             .strftime("%m-%d %H:%M"),
                    "state": ("deleted" if n.endswith(".deleted")
                              else "prev" if n.endswith(".prev")
                              else "active"),
                })
        out[key] = {"dir": base, "files": rows}
    return out


@app.get("/api/ingest/download")
def ingest_download(folder: str = Query(...), name: str = Query(...)):
    path = _ingest_path(folder, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "파일이 없습니다")
    from fastapi.responses import FileResponse
    return FileResponse(path, filename=os.path.basename(path))


@app.post("/api/ingest/file-op")
def ingest_file_op(request: Request,
                   folder: str = Query(...), name: str = Query(...),
                   op: str = Query(...)):
    _require_edit(request)
    if _rebuild["running"]:
        raise HTTPException(409, "색인 재생성 중에는 파일을 바꿀 수 없습니다")
    path = _ingest_path(folder, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "파일이 없습니다")

    if op == "delete":
        # 1단계 — 앱에서 안 보이게만 한다.
        if name.endswith(".deleted"):
            raise HTTPException(400, "이미 삭제 상태입니다")
        dest = path + ".deleted"
        if os.path.isfile(dest):
            os.remove(dest)                          # 같은 이름의 옛 삭제본
        try:
            os.replace(path, dest)
        except PermissionError:
            # Windows 는 열려 있는 파일의 이름을 못 바꾼다. 엑셀로
            # 열어 둔 경우가 대부분이다.
            raise HTTPException(423, "파일이 다른 프로그램에서 열려 "
                                     "있습니다. 엑셀 등에서 닫고 다시 "
                                     "시도하십시오.")
        _reset_caches()
        return {"ok": True, "state": "deleted",
                "name": os.path.basename(dest),
                "note": "앱에서는 더 이상 읽지 않습니다. 매뉴얼이라면 "
                        "색인을 다시 만들어야 검색에서도 빠집니다. "
                        "영구 삭제는 이 상태에서만 할 수 있습니다."}

    if op == "restore":
        if not (name.endswith(".deleted") or name.endswith(".prev")):
            raise HTTPException(400, "삭제·보존 상태의 파일만 되살릴 수 있습니다")
        dest = path[:-len(".deleted")] if name.endswith(".deleted")                else path[:-len(".prev")]
        if os.path.isfile(dest):
            raise HTTPException(409, "같은 이름의 사용 중 파일이 있습니다 — "
                                     "먼저 그 파일을 삭제하십시오")
        try:
            os.replace(path, dest)
        except PermissionError:
            raise HTTPException(423, "파일이 다른 프로그램에서 열려 "
                                     "있습니다. 닫고 다시 시도하십시오.")
        _reset_caches()
        return {"ok": True, "state": "active", "name": os.path.basename(dest)}

    if op == "purge":
        # 2단계 — .deleted 상태에서만. 화면에서 한 번에 지우는 길을
        # 열지 않는다.
        if not (name.endswith(".deleted") or name.endswith(".prev")):
            raise HTTPException(400, "영구 삭제는 삭제·보존 상태의 파일만 "
                                     "할 수 있습니다. 먼저 삭제하십시오.")
        try:
            os.remove(path)
        except PermissionError:
            raise HTTPException(423, "파일이 다른 프로그램에서 열려 "
                                     "있습니다. 닫고 다시 시도하십시오.")
        return {"ok": True, "state": "purged", "name": name}

    raise HTTPException(400, "op 는 delete/restore/purge 중 하나여야 합니다")


@app.get("/api/ingest/status")
def ingest_status():
    return dict(_rebuild)


# ── 정적 파일 (빌드된 React UI) ─────────────────────────────
# 반드시 모든 /api 라우트 뒤에 와야 한다. 앞에 두면 "/" 아래를
# 정적 파일이 전부 가로채서 API 가 404 로 죽는다.
_UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "react" / "dist"
if _UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_UI_DIST), html=True), name="ui")
else:
    print(f"[warn] UI 빌드본이 없습니다: {_UI_DIST}")
    print("       ui/react 에서 npm run build 를 먼저 실행하십시오.")

