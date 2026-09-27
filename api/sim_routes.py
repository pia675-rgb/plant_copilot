# -*- coding: utf-8 -*-
"""
sim_routes.py — 공정 모의 화면 API (패치 37)

새 엔드포인트만 둔다. 검색·판정 경로는 건드리지 않는다 (CLAUDE.md 6-1).

  GET  /api/sim/screens                  목록
  POST /api/sim/screens?title=&name=&hint=   본문=캡처 이미지 바이트 → GPT-5.5 추출 → 생성
  POST /api/sim/screens/layout?title=    본문=배치 JSON (모델 없이 생성)
  GET  /api/sim/screens/{sid}/layout     배치 JSON (사람이 고칠 원본)
  PUT  /api/sim/screens/{sid}/layout     배치 교체 → 재생성 (이전 판 보존)
  POST /api/sim/screens/{sid}/rebuild    리스트가 바뀐 뒤 재생성
  GET  /api/sim/screens/{sid}/model      모델 요약(경고·가정·통계)
  GET  /api/sim/screens/{sid}/view       모의 화면 HTML (?embed=1 로 머리 숨김)
  GET  /api/sim/tag/{tag}                이 태그가 있는 화면

  POST /api/sim/jobs?title=&name=&hint=  위 이미지 생성의 비동기판 → {job}
  GET  /api/sim/jobs/{job}               진행 상태 · 끝나면 결과

MAXIS AGENT 노드 게이트웨이는 15초에 요청을 끊는다(패치 이식 때 실측,
스트리밍으로도 못 넘음). 비전 모델 추출은 수십 초~수 분이라 동기판은
노드에서 반드시 끊긴다. 화면(sim_studio)은 비동기판을 쓴다.
작업 목록은 메모리에 둔다 — 파드가 재기동되면 진행 중이던 작업은 사라진다
(만들어진 화면 파일은 디스크에 남는다).

업로드는 반입 화면과 같이 multipart 없이 본문 바이트로 받는다
(python-multipart 의존성을 늘리지 않기 위해).
쓰기 조작은 반입과 같은 열쇠(_require_edit)를 거친다.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

MAX_IMAGE = 15 * 1024 * 1024
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def build_router(require_edit):
    r = APIRouter(prefix="/api/sim")
    from sim import store

    def _exists(sid):
        if not os.path.isfile(store.path(sid, "layout.json")):
            raise HTTPException(404, "화면이 없습니다: %s" % sid)

    @r.get("/screens")
    def screens():
        return {"screens": store.list_screens()}

    @r.post("/screens")
    async def create_from_image(request: Request, title: str = Query(""),
                                name: str = Query("screen.png"),
                                hint: str = Query("")):
        require_edit(request)
        safe = os.path.basename(name).strip() or "screen.png"
        if not safe.lower().endswith(IMG_EXT):
            raise HTTPException(400, "이미지(.png/.jpg/.webp)만 받습니다")
        body = await request.body()
        if not body:
            raise HTTPException(400, "빈 파일입니다")
        if len(body) > MAX_IMAGE:
            raise HTTPException(413, "이미지가 너무 큽니다 (15MB 이하)")
        from sim.extract import ExtractError, extract_layout
        try:
            layout, warns, usage = extract_layout(body, safe, hint)
        except ExtractError as e:
            raise HTTPException(502, str(e))
        sid = store.create(title or os.path.splitext(safe)[0], body, safe,
                           layout, warns, layout["source"]["extractor"])
        m = store.build(sid)
        return {"id": sid, "stats": m["stats"], "extract_warnings": warns,
                "warnings": m["warnings"], "assumptions": m["assumptions"],
                "usage": usage}

    jobs = {}
    lock = threading.Lock()

    def _gc():
        now = time.time()
        with lock:
            for k in [k for k, v in jobs.items() if now - v["t0"] > 3600]:
                jobs.pop(k, None)

    def _run(jid, body, safe, title, hint):
        from sim.extract import ExtractError, extract_layout
        try:
            jobs[jid]["stage"] = "모델이 화면을 옮겨 적는 중"
            layout, warns, usage = extract_layout(body, safe, hint)
            jobs[jid]["stage"] = "리스트와 대조하는 중"
            sid = store.create(title or os.path.splitext(safe)[0], body, safe,
                               layout, warns, layout["source"]["extractor"])
            m = store.build(sid)
            jobs[jid].update(state="done", result={
                "id": sid, "stats": m["stats"], "extract_warnings": warns,
                "warnings": m["warnings"], "assumptions": m["assumptions"],
                "usage": usage})
        except ExtractError as e:
            jobs[jid].update(state="error", error=str(e))
        except Exception as e:                              # noqa: BLE001
            jobs[jid].update(state="error", error="%s: %s" % (type(e).__name__, e))

    @r.post("/jobs")
    async def start_job(request: Request, title: str = Query(""),
                        name: str = Query("screen.png"), hint: str = Query("")):
        require_edit(request)
        safe = os.path.basename(name).strip() or "screen.png"
        if not safe.lower().endswith(IMG_EXT):
            raise HTTPException(400, "이미지(.png/.jpg/.webp)만 받습니다")
        body = await request.body()
        if not body:
            raise HTTPException(400, "빈 파일입니다")
        if len(body) > MAX_IMAGE:
            raise HTTPException(413, "이미지가 너무 큽니다 (15MB 이하)")
        _gc()
        jid = uuid.uuid4().hex[:12]
        jobs[jid] = {"state": "running", "stage": "대기", "t0": time.time()}
        threading.Thread(target=_run, args=(jid, body, safe, title, hint),
                         daemon=True).start()
        return {"job": jid}

    @r.get("/jobs/{jid}")
    def job(jid: str):
        j = jobs.get(jid)
        if not j:
            raise HTTPException(404, "작업이 없습니다 (서버가 재기동되었을 수 있습니다)")
        out = {k: v for k, v in j.items() if k != "t0"}
        out["elapsed"] = round(time.time() - j["t0"], 1)
        return out

    @r.post("/screens/layout")
    def create_from_layout(request: Request, title: str = Query("screen"),
                           layout: dict = Body(...)):
        require_edit(request)
        from sim.extract import ExtractError, sanitize
        src = layout.get("source") or {}
        try:
            lay, warns = sanitize(layout, src.get("width"), src.get("height"),
                                  extractor=src.get("extractor") or "manual")
        except ExtractError as e:
            raise HTTPException(400, str(e))
        sid = store.create(title, None, "", lay, warns, "manual")
        m = store.build(sid)
        return {"id": sid, "stats": m["stats"], "extract_warnings": warns,
                "warnings": m["warnings"], "assumptions": m["assumptions"]}

    @r.get("/screens/{sid}/layout")
    def get_layout(sid: str):
        _exists(sid)
        return json.load(open(store.path(sid, "layout.json"), encoding="utf-8"))

    @r.put("/screens/{sid}/layout")
    def put_layout(sid: str, request: Request, layout: dict = Body(...)):
        require_edit(request)
        _exists(sid)
        from sim.extract import ExtractError, sanitize
        src = layout.get("source") or {}
        try:
            lay, warns = sanitize(layout, src.get("width"), src.get("height"),
                                  extractor=src.get("extractor") or "manual-edit")
        except ExtractError as e:
            raise HTTPException(400, str(e))
        store.update_layout(sid, lay)
        m = store.build(sid)
        return {"id": sid, "stats": m["stats"], "extract_warnings": warns,
                "warnings": m["warnings"], "assumptions": m["assumptions"]}

    @r.post("/screens/{sid}/rebuild")
    def rebuild(sid: str, request: Request):
        require_edit(request)
        _exists(sid)
        m = store.build(sid)
        return {"id": sid, "stats": m["stats"], "warnings": m["warnings"],
                "assumptions": m["assumptions"]}

    @r.get("/screens/{sid}/model")
    def model(sid: str):
        _exists(sid)
        p = store.path(sid, "model.json")
        if not os.path.isfile(p):
            store.build(sid)
        m = json.load(open(p, encoding="utf-8"))
        return {k: m.get(k) for k in ("title", "stats", "warnings",
                                      "assumptions", "sources")}

    @r.get("/screens/{sid}/view", response_class=HTMLResponse)
    def view(sid: str):
        _exists(sid)
        p = store.path(sid, "screen.html")
        if not os.path.isfile(p):
            store.build(sid)
        return HTMLResponse(open(p, encoding="utf-8").read())

    @r.get("/tag/{tag}")
    def by_tag(tag: str):
        return {"tag": tag, "screens": store.screen_for_tag(tag)}

    return r
