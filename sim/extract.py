# -*- coding: utf-8 -*-
"""
extract.py — 화면승인자료(SCADA 캡처 이미지) → 배치 JSON

모델이 하는 일은 **보이는 것을 옮겨 적는 것**까지다.
  · 심볼 종류(탱크·펌프·밸브·조절밸브·계기·AVG·PID)와 위치(bbox)
  · 심볼 옆 태그 라벨 글자 — 보이는 그대로
  · 배관선의 대략적인 경로

모델이 하지 않는 일
  · 인터락 조건·설정값 — 인터락 리스트에서 규칙으로만 읽는다 (model.py)
  · 태그를 추정해 붙이기 — 라벨이 없으면 tag=null. 나중에 사람이 적는다
  · 태그 교정 — 리스트와 안 맞으면 '미확인' 으로 두고 후보만 보인다

그래서 모델이 틀려도 "배치가 어색한" 수준에서 그치고, "없는 인터락이
생기는" 사고로 번지지 않는다.

환경변수
  COPILOT_SIM_PROVIDER   openai(기본) | azure
  COPILOT_SIM_MODEL      기본 gpt-5.5  (azure 는 배포 이름)
  COPILOT_SIM_API_KEY / COPILOT_SIM_BASE_URL  화면 추출 전용 (비우면 아래 공용)
  OPENAI_API_KEY / OPENAI_BASE_URL          (config 와 공유)
  AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY / AZURE_OPENAI_API_VERSION
  COPILOT_SIM_TIMEOUT    기본 180 (초)
"""
from __future__ import annotations

import base64
import json
import os
import re

import config

SCHEMA_ID = "plant-screen-layout/1"
TYPES = ("tank", "pump", "valve", "control_valve", "transmitter", "avg",
         "pid", "other")

PROVIDER = os.environ.get("COPILOT_SIM_PROVIDER", "openai").lower()
# 화면 추출 전용 키·주소. 비우면 앱 공용(OPENAI_*)을 쓴다.
# 배포판은 공용 OPENAI_* 가 DeepInfra(임베딩·챗)를 가리키므로, GPT-5.5 를
# 쓰려면 이 둘을 따로 줘야 한다 — 안 주면 DeepInfra 에 gpt-5.5 를 요청한다.
SIM_API_KEY = os.environ.get("COPILOT_SIM_API_KEY", "")
SIM_BASE_URL = os.environ.get("COPILOT_SIM_BASE_URL", "")
MODEL = os.environ.get("COPILOT_SIM_MODEL", "gpt-5.5")
TIMEOUT = int(os.environ.get("COPILOT_SIM_TIMEOUT", "180"))

SYSTEM_PROMPT = """You convert a screenshot of an industrial SCADA/HMI process screen (Siemens WinCC OA style, ultrapure-water plant) into a JSON layout.
You only TRANSCRIBE what is visible. You never infer control logic, setpoints or interlocks.

Return ONE JSON object, no prose:
{
 "objects": [
  {"id": "o1",
   "type": "tank|pump|valve|control_valve|transmitter|avg|pid|other",
   "tag": "exact tag label text as printed, e.g. NWP-0011, or null if the symbol has no readable tag label next to it",
   "bbox": [x0, y0, x1, y1],        // normalized 0..1 of the image width/height, symbol INCLUDING its faceplate widgets, EXCLUDING the tag label box
   "label_bbox": [x0, y0, x1, y1],  // normalized bbox of the tag label box, or null
   "badges": ["L","A","SC", ...],   // small letter boxes printed on/near the symbol, verbatim
   "sources": ["LT-001A","LT-001B"],// only for type avg: tags whose values are averaged, if visibly associated
   "pv": "o3 or a tag",             // only for type pid or tank: which transmitter/avg object feeds it, if visibly connected; else null
   "outputs": ["o7","o8"],          // only for type pid: control valves visibly driven by it; else []
   "conf": 0.0-1.0                  // your confidence in type AND tag reading
  }
 ],
 "lines": [ {"pts": [[x,y],[x,y],...], "style": "pipe|signal"} ]   // pipes solid, signal lines dashed; normalized coordinates
}

Rules:
- Read tag text character by character. Do not correct, complete or guess tags. If partially unreadable, set tag null and conf <= 0.4.
- A level/flow/pressure transmitter shown only as a tag box with a value (e.g. "LT-001A 000.00 %") is type transmitter.
- An "AVG" readout block is type avg. A faceplate with PID / SP / PV / CV rows is type pid.
- A bow-tie valve with a dome actuator and a % readout is control_valve; a plain bow-tie is valve.
- A pump symbol (circle with triangle) plus its L/A/SC badges and CV/FB readouts is ONE pump object.
- Include every symbol even if it has no tag.
- Coordinates: (0,0) top-left, (1,1) bottom-right.
"""


class ExtractError(RuntimeError):
    pass


def _mime(path):
    ext = os.path.splitext(path)[1].lower()
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/png")


def _call_llm(image_bytes, mime, hint=""):
    # requests 를 쓰지 않는다 — 기존 코드처럼 표준 라이브러리만 (의존성 무증가)
    import urllib.error
    import urllib.request
    b64 = base64.b64encode(image_bytes).decode("ascii")
    user = [{"type": "text",
             "text": "Transcribe this process screen into the JSON layout."
                     + (("\nContext from the engineer: " + hint) if hint else "")},
            {"type": "image_url",
             "image_url": {"url": "data:%s;base64,%s" % (mime, b64),
                           "detail": "high"}}]
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        # 추론형 모델은 temperature 를 받지 않는다 — 넣지 않는다
        "max_completion_tokens": 16000,
    }
    if PROVIDER == "azure":
        ep = (config.AOAI_ENDPOINT or "").rstrip("/")
        if not ep or not config.AOAI_API_KEY:
            raise ExtractError("AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY 가 없습니다")
        url = "%s/openai/deployments/%s/chat/completions?api-version=%s" % (
            ep, MODEL, config.AOAI_API_VERSION)
        headers = {"api-key": config.AOAI_API_KEY}
        body.pop("model", None)
    else:
        key = SIM_API_KEY or config.OPENAI_API_KEY
        base = SIM_BASE_URL or config.OPENAI_BASE_URL
        if not key:
            raise ExtractError("COPILOT_SIM_API_KEY(또는 OPENAI_API_KEY) 가 없습니다 — "
                               "화면 추출은 GPT-5.5 API 키가 필요합니다")
        url = base.rstrip("/") + "/chat/completions"
        headers = {"Authorization": "Bearer " + key}
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ExtractError("모델 호출 실패 %s: %s"
                           % (e.code, e.read().decode("utf-8", "replace")[:300]))
    except (urllib.error.URLError, TimeoutError) as e:
        raise ExtractError("모델 서버에 연결하지 못했습니다: %s" % e)
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise ExtractError("모델 응답 형식이 예상과 다릅니다: %s"
                           % json.dumps(data)[:300])
    return text, (data.get("usage") or {})


def _parse_json(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise ExtractError("모델 응답에서 JSON 을 찾지 못했습니다")
        return json.loads(m.group(0))


def _box(v, w=None, h=None):
    try:
        x0, y0, x1, y1 = [float(a) for a in v]
    except (TypeError, ValueError):
        return None
    # 모델이 지시와 달리 픽셀로 준 경우 — 이미지 크기를 알면 나눠서 살린다.
    # 모르면 버린다 (크기를 짐작해 나누면 배치 전체가 어긋난다).
    if max(x0, y0, x1, y1) > 1.5:
        if not (w and h) or x1 > w * 1.02 or y1 > h * 1.02:
            return None
        x0, x1, y0, y1 = x0 / w, x1 / w, y0 / h, y1 / h
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    if x1 - x0 < 0.003 or y1 - y0 < 0.003:
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def sanitize(raw, width=None, height=None, extractor="manual"):
    """모델(또는 사람)이 준 배치를 검증·정리한다. 버린 것은 이유와 함께
    warnings 로 돌려준다 — 조용히 빼지 않는다."""
    warns = []
    objs_in = raw.get("objects") if isinstance(raw, dict) else None
    if not isinstance(objs_in, list):
        raise ExtractError("objects 배열이 없습니다")
    seen, objs = set(), []
    for i, o in enumerate(objs_in):
        if not isinstance(o, dict):
            continue
        oid = str(o.get("id") or "o%d" % (i + 1)).strip()
        if oid in seen:
            oid = "%s_%d" % (oid, i + 1)
        seen.add(oid)
        typ = str(o.get("type") or "other").strip().lower()
        if typ not in TYPES:
            warns.append("%s: 알 수 없는 종류 '%s' → other" % (oid, typ))
            typ = "other"
        box = _box(o.get("bbox"), width, height)
        if box and max(float(a) for a in o.get("bbox")) > 1.5:
            warns.append("%s: 픽셀 좌표를 이미지 크기로 정규화" % oid)
        if not box:
            warns.append("%s: bbox 가 없거나 잘못되어 제외" % oid)
            continue
        tag = o.get("tag")
        tag = re.sub(r"\s+", "", str(tag)).upper() if tag not in (None, "", "null") else None
        conf = o.get("conf")
        try:
            conf = max(0.0, min(1.0, float(conf)))
        except (TypeError, ValueError):
            conf = None
        rec = {"id": oid, "type": typ, "tag": tag, "bbox": box,
               "label_bbox": _box(o.get("label_bbox"), width, height),
               "badges": [str(b).strip()[:4] for b in (o.get("badges") or [])
                          if str(b).strip()][:6],
               "conf": conf}
        if typ == "avg":
            rec["sources"] = [re.sub(r"\s+", "", str(s)).upper()
                              for s in (o.get("sources") or []) if s]
        if typ in ("pid", "tank"):
            pv = o.get("pv")
            rec["pv"] = str(pv).strip() if pv not in (None, "", "null") else None
        if typ == "pid":
            rec["outputs"] = [str(x).strip() for x in (o.get("outputs") or []) if x]
        objs.append(rec)
    lines = []
    for ln in (raw.get("lines") or []):
        pts = []
        for p in (ln.get("pts") or []) if isinstance(ln, dict) else []:
            try:
                x, y = float(p[0]), float(p[1])
            except (TypeError, ValueError, IndexError):
                continue
            if 0 <= x <= 1.02 and 0 <= y <= 1.02:
                pts.append([round(min(x, 1), 4), round(min(y, 1), 4)])
        if len(pts) >= 2:
            lines.append({"pts": pts,
                          "style": "signal" if (ln.get("style") == "signal") else "pipe"})
    return {"schema": SCHEMA_ID,
            "source": {"width": width, "height": height,
                       "extractor": extractor},
            "objects": objs, "lines": lines}, warns


def image_size(image_bytes):
    try:
        from io import BytesIO
        from PIL import Image
        im = Image.open(BytesIO(image_bytes))
        return im.size
    except Exception:                                       # noqa: BLE001
        return None, None


def extract_layout(image_bytes, filename="screen.png", hint=""):
    """이미지 바이트 → (layout, warnings, usage)."""
    w, h = image_size(image_bytes)
    text, usage = _call_llm(image_bytes, _mime(filename), hint)
    raw = _parse_json(text)
    layout, warns = sanitize(raw, w, h, extractor="%s:%s" % (PROVIDER, MODEL))
    return layout, warns, usage
