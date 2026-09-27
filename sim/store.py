# -*- coding: utf-8 -*-
"""
store.py — 공정 모의 화면의 저장·렌더·재생성

저장 위치: <DERIVED_DIR>/sim/<screen_id>/
    source.<ext>     원본 캡처 (화면승인자료)
    layout.json      배치 — 모델이 옮겨 적은 것, 사람이 고친 것
    layout.prev.json 고치기 전 판 (덮어쓰기 전 한 벌 보존)
    model.json       모의 모델 (리스트와 대조한 결과)
    screen.html      모의 화면 (자체 완결 HTML)
    meta.json        제목·추출기·경고 수·만든 시각

원칙
  · 배치(layout.json)는 사람이 고칠 수 있다. 모델·리스트 대조는 매번
    다시 만든다 — 리스트가 바뀌면 재생성 한 번으로 따라간다.
  · 덮어쓰기 전 이전 판을 남긴다 (CLAUDE.md 3-2).
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import shutil

import config

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template.html")
MARK = "/*__MODEL__*/null"


def root():
    d = os.path.join(config.DERIVED_DIR, "sim")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_id(s):
    s = re.sub(r"[^A-Za-z0-9_\-가-힣]+", "_", str(s or "")).strip("_")
    return s[:60] or "screen"


def new_id(title):
    base = _safe_id(title)
    ts = dt.datetime.now().strftime("%y%m%d_%H%M%S")
    return "%s_%s" % (base, ts)


def path(sid, name=""):
    sid = _safe_id(sid)
    d = os.path.join(root(), sid)
    return os.path.join(d, name) if name else d


def render_html(model):
    tpl = open(TEMPLATE, encoding="utf-8").read()
    if MARK not in tpl:
        raise RuntimeError("template.html 에 모델 자리표시가 없습니다")
    js = json.dumps(model, ensure_ascii=False, default=str)
    # </script> 로 스크립트가 끊기지 않게
    js = js.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return tpl.replace(MARK, js, 1)


def _image_uri(sid):
    for f in sorted(os.listdir(path(sid))):
        if f.startswith("source."):
            ext = f.rsplit(".", 1)[-1].lower()
            mime = {"jpg": "jpeg"}.get(ext, ext)
            b = open(path(sid, f), "rb").read()
            return "data:image/%s;base64,%s" % (mime, base64.b64encode(b).decode())
    return None


def build(sid, sources=None):
    """layout.json → model.json + screen.html. 리스트는 매번 새로 읽는다."""
    from sim.model import build_model
    layout = json.load(open(path(sid, "layout.json"), encoding="utf-8"))
    meta = load_meta(sid)
    model = build_model(layout, sources=sources, title=meta.get("title") or sid,
                        image_data_uri=_image_uri(sid))
    json.dump({k: v for k, v in model.items() if k != "image"},
              open(path(sid, "model.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    open(path(sid, "screen.html"), "w", encoding="utf-8").write(render_html(model))
    meta.update({"built": dt.datetime.now().isoformat(timespec="seconds"),
                 "stats": model["stats"], "warnings": len(model["warnings"]),
                 "assumptions": len(model["assumptions"]),
                 "tags": sorted(o["tag"] for o in model["objects"] if o.get("tag"))})
    save_meta(sid, meta)
    return model


def load_meta(sid):
    p = path(sid, "meta.json")
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


def save_meta(sid, meta):
    json.dump(meta, open(path(sid, "meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def create(title, image_bytes=None, image_name="screen.png", layout=None,
           extract_warnings=None, extractor=""):
    sid = new_id(title)
    os.makedirs(path(sid), exist_ok=True)
    if image_bytes:
        ext = os.path.splitext(image_name)[1].lower().lstrip(".") or "png"
        open(path(sid, "source." + ext), "wb").write(image_bytes)
    json.dump(layout, open(path(sid, "layout.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    save_meta(sid, {"id": sid, "title": title, "extractor": extractor,
                    "extract_warnings": extract_warnings or [],
                    "created": dt.datetime.now().isoformat(timespec="seconds")})
    return sid


def update_layout(sid, layout):
    cur = path(sid, "layout.json")
    if os.path.isfile(cur):
        shutil.copy2(cur, path(sid, "layout.prev.json"))
    json.dump(layout, open(cur, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def list_screens():
    out = []
    r = root()
    for sid in os.listdir(r):
        if os.path.isfile(os.path.join(r, sid, "layout.json")):
            m = load_meta(sid)
            m.setdefault("id", sid)
            m["has_html"] = os.path.isfile(os.path.join(r, sid, "screen.html"))
            out.append(m)
    # 최근 순 — 이름순이면 제목 첫 글자에 따라 오래된 화면이 앞에 온다
    out.sort(key=lambda m: (m.get("created") or "", m["id"]), reverse=True)
    return out


def screen_for_tag(tag):
    """이 태그가 들어 있는 화면들 (최근 순). 챗봇 연결용."""
    T = str(tag or "").upper()
    return [m["id"] for m in list_screens() if T and T in (m.get("tags") or [])]
