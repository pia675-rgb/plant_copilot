# -*- coding: utf-8 -*-
"""
model.py — 배치 JSON(화면) + 인터락 리스트 + IO List → 모의 모델

규칙으로만 만든다. 모델(LLM)은 여기 오지 않는다.

  화면 배치        extract.py 가 옮겨 적은 심볼·태그·위치
  인터락 조건      ingest.interlock.load_interlocks() — 기존 파서 그대로
  범위·단위        IO List(RANGE (단위)) → 계기 리스트(SCALE RANGE)
  IO 점            IO List (L1 표준양식·24종 모두) — 화면 태그와 대조

지어내지 않는다
  · 조건·설정값·지연은 인터락 리스트 원문에서만 온다. 조건마다 IL NO 와
    원문을 달아 둔다 (화면에서 누르면 근거가 보인다)
  · 해석하지 못한 조건은 버리지 않는다. 원문 그대로 '수동 토글' 이 된다
  · 범위를 모르는 계기는 설정값으로 임시 범위를 잡고 '범위 미상' 을 붙인다
  · 리스트에 없는 동작 규칙(자동 기동 조건 등)을 가정으로 채울 때는
    assumptions 에 적어 화면에 띄운다
  · 화면 태그가 리스트에 없으면 '미확인'. 비슷한 태그는 후보로만 보인다
"""
from __future__ import annotations

import difflib
import math
import os
import re
from collections import OrderedDict

import config

ON_ACTIONS = {"START": "RUN", "OPEN": "OPEN", "ON": "ON", "RUN": "RUN"}
OFF_ACTIONS = {"STOP": "STOP", "CLOSE": "CLOSE", "OFF": "OFF"}
DEVICE_TYPES = ("pump", "valve", "control_valve", "other")

# 상태 단어 — 태그 없는 이산 조건의 신호 이름에서 벗긴다
_STRIP_WORDS = re.compile(
    r"\b(ON|OFF)\b|발생|동작|확인|없음|정상|해제|신호|상태|선택|입력", re.I)
_NEG_STATES = {"NO_FAULT"}
_NEG_WORDS = re.compile(r"없음|해제|\bOFF\b", re.I)


def _s(v):
    return str(v).strip() if v is not None else ""


def _alnum(s):
    return re.sub(r"[^A-Z0-9]", "", _s(s).upper())


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def signal_name(raw):
    """'VFD FAULT 없음' → 'VFD FAULT', 'E-STOP PB 동작 (EMERGENCY STOP)' →
    'E-STOP PB'. 같은 신호의 긍정·부정 표현을 한 토글로 묶기 위한 이름."""
    t = re.sub(r"\([^)]*\)", " ", _s(raw).upper())
    t = _STRIP_WORDS.sub(" ", t)
    t = re.sub(r"\d+(\.\d+)?\s*(SEC|S\b|초)", " ", t)
    t = re.sub(r"(연속|지연|DELAY)", " ", t)
    return re.sub(r"\s+", " ", t).strip(" -·,") or _s(raw).upper()


# ── 데이터 적재 ────────────────────────────────────────────────

def load_sources():
    """리스트 세 종을 읽는다. 하나가 실패해도 나머지는 살린다."""
    out = {"points": {}, "interlocks": [], "errors": []}
    try:
        from ingest.lists import load_points
        out["points"] = load_points(
            config.IO_LIST,
            getattr(config, "INSTRUMENT_SPECS", None)
            or getattr(config, "INSTRUMENT_SPEC", None),
            None, getattr(config, "TB_LIST", None))
    except Exception as e:                                  # noqa: BLE001
        out["errors"].append("IO List 읽기 실패: %s" % e)
    try:
        from ingest.interlock import load_interlocks
        out["interlocks"] = load_interlocks()
    except Exception as e:                                  # noqa: BLE001
        out["errors"].append("인터락 리스트 읽기 실패: %s" % e)
    return out


class TagBook:
    """화면 태그 ↔ 리스트 태그 대조."""

    def __init__(self, points, interlocks):
        self.points = points or {}
        self.by_pid, self.by_alnum = {}, {}
        for io_tag, r in self.points.items():
            for key in (_s(r.get("P&ID TAG")), _s(io_tag),
                        _s(r.get("EQUIP NO"))):
                if key:
                    self.by_pid.setdefault(key.upper(), []).append(io_tag)
            self.by_alnum.setdefault(_alnum(io_tag), []).append(io_tag)
        self.il_out, self.il_in = set(), set()
        for it in interlocks or []:
            if _s(it.get("output_tag")):
                self.il_out.add(_s(it["output_tag"]).upper())
            for c in it.get("conditions") or []:
                for t in c.get("tags") or []:
                    self.il_in.add(_s(t).upper())
        self.universe = sorted(set(self.by_pid) | self.il_out | self.il_in)

    def io_points(self, tag, limit=12):
        """화면 태그에 물린 IO 점. 정확 일치 → 태그 문자 포함 순."""
        if not tag:
            return []
        T = tag.upper()
        hits = list(dict.fromkeys(self.by_pid.get(T, [])))
        a = _alnum(T)
        if len(a) >= 5:
            for k, tags in self.by_alnum.items():
                if a in k:
                    for t in tags:
                        if t not in hits:
                            hits.append(t)
        out = []
        for t in hits[:limit]:
            r = self.points.get(t) or {}
            out.append({k: r.get(v) for k, v in (
                ("io_tag", "IO TAG"), ("pid_tag", "P&ID TAG"),
                ("io_type", "IO TYPE"), ("module", "IO MODULE"),
                ("add", "ADD"), ("plc", "PLC"), ("panel", "PANEL"),
                ("pn", "PN(DP)"), ("slot", "SLOT"), ("ch", "CH"),
                ("desc", "DESCRIPTION"), ("dwg", "DWG NO."),
                ("plc_type", "PLC TYPE"), ("range", "RANGE TEXT"))})
            out[-1]["io_tag"] = out[-1]["io_tag"] or t
        return out

    def spec(self, tag):
        """범위·단위. IO List(L1 RANGE) 가 먼저, 없으면 계기 리스트."""
        for t in self.by_pid.get(_s(tag).upper(), []):
            r = self.points.get(t) or {}
            lo, hi = _num(r.get("RANGE MIN")), _num(r.get("RANGE MAX"))
            if lo is not None and hi is not None and hi > lo:
                src = "IO List RANGE" if r.get("_io_format") == "L1" and \
                    _s(r.get("RANGE TEXT")) else "계기 리스트 SCALE RANGE"
                return lo, hi, _s(r.get("UNIT")), src
        return None, None, "", ""

    def known(self, tag):
        T = _s(tag).upper()
        return bool(T) and (T in self.by_pid or T in self.il_out or T in self.il_in)

    def near(self, tag, n=3):
        if not tag:
            return []
        return difflib.get_close_matches(tag.upper(), self.universe, n=n,
                                         cutoff=0.72)


# ── 모델 생성 ──────────────────────────────────────────────────

def _dir(action):
    a = _s(action).upper()
    if a in ON_ACTIONS:
        return 1
    if a in OFF_ACTIONS:
        return -1
    return 0


def _cond_test(c, out_tag, devices_on_screen):
    """파싱 결과 → 모의 판정식. (test, var_decls, note)"""
    kind = c.get("kind")
    tags = [_s(t).upper() for t in (c.get("tags") or [])]
    st = c.get("state")
    raw = _s(c.get("raw"))
    if kind == "ANALOG" and len(tags) == 1 and c.get("op") and \
            c.get("setpoint") is not None:
        return ({"t": "cmp", "tag": tags[0], "op": c["op"],
                 "sp": float(c["setpoint"]), "unit": c.get("unit") or ""},
                [("analog", tags[0])], "")
    if kind == "DISCRETE" and tags and st in ("OPEN", "CLOSE", "RUN", "STOP"):
        want = st in ("OPEN", "RUN")
        multi = "ALL" if (c.get("multi") == "AND" or "모두" in raw) else "ANY"
        decls = []
        for t in tags:
            if t not in devices_on_screen:
                decls.append(("bool", "%s:ON" % t,
                              "%s %s" % (t, "OPEN/RUN")))
        return ({"t": "dev", "tags": tags, "on": want, "multi": multi},
                decls, "")
    if kind == "DISCRETE" and tags and st in ("FAULT", "NO_FAULT", "READY"):
        name = "%s %s" % (tags[0], "READY" if st == "READY" else "FAULT")
        val = st != "NO_FAULT"
        return ({"t": "bool", "var": name, "value": val}, [("bool", name, name)], "")
    if kind == "DISCRETE":
        name = "%s:%s" % (out_tag, signal_name(raw))
        val = not (st in _NEG_STATES or (st != "READY" and _NEG_WORDS.search(raw)))
        return ({"t": "bool", "var": name, "value": val},
                [("bool", name, signal_name(raw))], "")
    # 해석 못 한 조건 — 원문 그대로 수동 토글
    name = "%s:%s" % (out_tag, raw)
    return ({"t": "bool", "var": name, "value": True},
            [("bool", name, raw)], "해석 불가 — 원문 조건을 수동 토글로 둠")


def build_model(layout, sources=None, title="", image_data_uri=None):
    src = sources or load_sources()
    book = TagBook(src["points"], src["interlocks"])
    warns = list(src.get("errors") or [])
    assumptions = []

    objs = [dict(o) for o in layout.get("objects") or []]
    counters = {}
    for o in objs:
        counters[o["type"]] = counters.get(o["type"], 0) + 1
        o["key"] = o.get("tag") or "%s#%d" % (o["type"].upper(), counters[o["type"]])
        o["label"] = o.get("tag") or ""
        v = {"io": book.io_points(o.get("tag")),
             "il_out": bool(o.get("tag")) and o["tag"] in book.il_out,
             "il_in": bool(o.get("tag")) and o["tag"] in book.il_in}
        v["known"] = bool(v["io"] or v["il_out"] or v["il_in"])
        if o.get("tag") and not v["known"]:
            v["near"] = book.near(o["tag"])
        o["verify"] = v
        if o["type"] in ("avg", "pid") or (o["type"] == "tank" and not o.get("tag")):
            continue
        if not o.get("tag"):
            warns.append("%s(%s): 태그 라벨이 없음 — 리스트와 연결 불가"
                         % (o["id"], o["type"]))
        elif not v["known"]:
            warns.append("%s: IO List·인터락 리스트 어디에도 없음%s"
                         % (o["tag"], (" — 후보 " + ", ".join(v["near"]))
                            if v.get("near") else ""))
        if o.get("conf") is not None and o["conf"] < 0.6:
            warns.append("%s: 판독 신뢰도 낮음(%.2f) — 원본과 대조 필요"
                         % (o["key"], o["conf"]))

    screen_devices = {o["tag"]: o for o in objs
                      if o.get("tag") and o["type"] in DEVICE_TYPES}

    # 인터락 → 장치 그룹
    devices, conds = OrderedDict(), OrderedDict()
    analog, boolv = OrderedDict(), OrderedDict()
    for tag, o in screen_devices.items():
        devices[tag] = {"tag": tag, "type": o["type"], "groups": [],
                        "fail": "", "on_word": "", "off_word": "",
                        "obj": o["id"]}
    for it in src["interlocks"]:
        out = _s(it.get("output_tag")).upper()
        if out not in devices:
            continue
        d = devices[out]
        a = _s(it.get("action")).upper()
        dr = _dir(a)
        if dr > 0:
            d["on_word"] = d["on_word"] or ON_ACTIONS[a]
        elif dr < 0:
            d["off_word"] = d["off_word"] or OFF_ACTIONS[a]
        d["fail"] = d["fail"] or _s(it.get("fail"))
        kind = _s(it.get("kind")).upper() or "INTERLOCK"
        g = {"il_no": _s(it.get("il_no")), "kind": kind, "action": a,
             "dir": dr, "logic": (_s(it.get("logic")).upper() or
                                  ("OR" if kind == "INTERLOCK" else "AND")),
             "reset": _s(it.get("reset")).upper(),
             "latch": kind == "INTERLOCK" and _s(it.get("reset")).upper() == "MANUAL",
             "priority": it.get("priority"), "plc_block": _s(it.get("plc_block")),
             "dwg": _s(it.get("dwg_no")), "sheet": _s(it.get("sheet")),
             "remark": _s(it.get("remark")), "file": _s(it.get("_file") or it.get("file")),
             "conds": []}
        if dr == 0:
            warns.append("%s %s: 동작 '%s' 의 방향을 알 수 없어 표시만 함"
                         % (g["il_no"], out, a))
        for i, c in enumerate(it.get("conditions") or []):
            cid = "%s#%d" % (g["il_no"] or out, i + 1)
            test, decls, note = _cond_test(c, out, screen_devices)
            conds[cid] = {"id": cid, "raw": _s(c.get("raw")), "il_no": g["il_no"],
                          "device": out, "kind": kind, "test": test,
                          "delay": float(c.get("delay_sec") or 0),
                          "parsed": bool(c.get("parsed")), "note": note}
            g["conds"].append(cid)
            for dk in decls:
                if dk[0] == "analog":
                    analog.setdefault(dk[1], {"tag": dk[1], "sps": []})
                    analog[dk[1]]["sps"].append(test["sp"])
                else:
                    boolv.setdefault(dk[1], {"key": dk[1], "label": dk[2],
                                             "device": out})
        d["groups"].append(g)

    for tag, d in devices.items():
        if not d["groups"]:
            continue
        has_seq_on = any(g["kind"] == "SEQUENCE" and g["dir"] > 0 for g in d["groups"])
        if not has_seq_on:
            assumptions.append(
                "%s: 자동 기동(시퀀스 %s) 조건이 리스트에 없음 — AUTO 에서는 "
                "허가 조건만 맞으면 %s 로 둠 (모의 가정)"
                % (tag, d["on_word"] or "ON", d["on_word"] or "ON"))
        if not d["on_word"]:
            d["on_word"] = "RUN" if d["type"] == "pump" else "OPEN"
        if not d["off_word"]:
            d["off_word"] = "STOP" if d["type"] == "pump" else "CLOSE"
    for tag, d in devices.items():
        if not d["groups"]:
            d["on_word"] = d["on_word"] or ("RUN" if d["type"] == "pump" else "OPEN")
            d["off_word"] = d["off_word"] or ("STOP" if d["type"] == "pump" else "CLOSE")
            if screen_devices[tag]["verify"]["known"]:
                assumptions.append("%s: 인터락 리스트에 출력 항목 없음 — 수동 "
                                   "조작만 가능" % tag)

    # 화면 계기(transmitter)는 조건에 안 걸려도 조작 슬라이더를 준다
    for o in objs:
        if o["type"] == "transmitter" and o.get("tag"):
            analog.setdefault(o["tag"], {"tag": o["tag"], "sps": []})
        if o["type"] == "avg":
            for t in o.get("sources") or []:
                analog.setdefault(t, {"tag": t, "sps": []})

    for t, a in analog.items():
        lo, hi, unit, rsrc = book.spec(t)
        if lo is None:
            sps = a["sps"]
            unit = next((conds[c]["test"].get("unit") for c in conds
                         if conds[c]["test"].get("tag") == t
                         and conds[c]["test"].get("unit")), "")
            if unit == "%" or not sps:
                lo, hi = 0.0, 100.0
            else:
                top = max(abs(x) for x in sps) * 1.5 or 10.0
                mag = 10 ** math.floor(math.log10(top))
                hi = math.ceil(top / mag) * mag
                lo = min(0.0, min(sps) * 1.5)
            rsrc = "범위 미상 — 설정값 기준 임시 범위"
            if sps or any(o.get("tag") == t for o in objs):
                warns.append("%s: IO List·계기 리스트에 범위 없음 → %s~%s %s 로 임시"
                             % (t, _fmt(lo), _fmt(hi), unit))
        a.update({"min": lo, "max": hi, "unit": unit, "range_src": rsrc,
                  "on_screen": any(o.get("tag") == t for o in objs)})

    _choose_initial(analog, boolv, conds, devices)

    # 화면에는 없지만 조건에 나오는 계기 — 조작은 주되 표시한다
    for t, a in analog.items():
        if not a["on_screen"] and not book.known(t):
            warns.append("%s: 조건에 쓰였지만 IO List 에 없음" % t)

    trace = trace_problems({"conds": conds}, src["interlocks"])
    warns += ["근거 추적 실패 — " + x for x in trace]

    il_files = sorted({g["file"] for d in devices.values() for g in d["groups"]
                       if g.get("file")})
    return {
        "schema": "plant-screen-model/1",
        "title": title or "공정 화면",
        "image": image_data_uri,
        "aspect": _aspect(layout),
        "objects": objs,
        "lines": layout.get("lines") or [],
        "devices": devices,
        "conds": conds,
        "analog": analog,
        "bool": boolv,
        "warnings": list(dict.fromkeys(warns)),
        "assumptions": assumptions,
        "sources": {
            "io_list": os.path.basename(str(config.IO_LIST)),
            "io_format": _io_format(src["points"]),
            "interlock": il_files or [os.path.basename(str(getattr(
                config, "INTERLOCK_XLSX", "") or ""))],
            "extractor": (layout.get("source") or {}).get("extractor"),
        },
        "stats": {
            "objects": len(objs),
            "verified": sum(1 for o in objs if o["verify"]["known"]),
            "tagged": sum(1 for o in objs if o.get("tag")),
            "devices_with_logic": sum(1 for d in devices.values() if d["groups"]),
            "conditions": len(conds),
            "unparsed": sum(1 for c in conds.values() if not c["parsed"]),
        },
    }


def _io_format(points):
    fm = {r.get("_io_format") or "24종" for r in (points or {}).values()}
    return "/".join(sorted(fm)) if fm else ""


def _aspect(layout):
    s = layout.get("source") or {}
    try:
        return float(s["height"]) / float(s["width"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return 0.45


def _fmt(v):
    return ("%g" % v) if isinstance(v, (int, float)) else str(v)


def _cmp(v, op, sp):
    return {">": v > sp, ">=": v >= sp, "<": v < sp, "<=": v <= sp,
            "=": v == sp}.get(op, False)


def _choose_initial(analog, boolv, conds, devices):
    """정상 운전에 가까운 초기값 — 인터락·자동정지는 안 걸리고 허가는
    서는 쪽. 목표를 가장 많이 만족하는 값을 고르고, 동점이면 범위 중앙에
    가까운 값. 정해진 정답이 아니라 출발점이다 (화면에서 바꿀 수 있다)."""
    goals = []            # (cond, want_true)
    for d in devices.values():
        for g in d["groups"]:
            for cid in g["conds"]:
                c = conds[cid]
                if g["kind"] == "PERMISSIVE" or (g["kind"] == "SEQUENCE" and g["dir"] > 0):
                    goals.append((c, True))
                elif g["kind"] in ("INTERLOCK", "SEQUENCE"):
                    goals.append((c, False))
    for t, a in analog.items():
        lo, hi = a["min"], a["max"]
        mid = (lo + hi) / 2
        best, best_sc = mid, None
        sps = [c["test"]["sp"] for c, _ in goals
               if c["test"].get("t") == "cmp" and c["test"]["tag"] == t]
        cap = (hi - lo) * 0.1
        for i in range(201):
            v = lo + (hi - lo) * i / 200
            sc = 0
            for c, want in goals:
                tst = c["test"]
                if tst.get("t") == "cmp" and tst["tag"] == t:
                    sc += 1 if _cmp(v, tst["op"], tst["sp"]) == want else 0
            # 설정값 경계에 바짝 붙은 값은 피한다 (조작 한 번에 트립되지 않게)
            margin = min([abs(v - x) for x in sps] + [cap])
            key = (sc, round(margin, 9), -abs(v - mid))
            if best_sc is None or key > best_sc:
                best, best_sc = v, key
        a["init"] = round(best, 3)
    for k, b in boolv.items():
        sc = {True: 0, False: 0}
        for val in (True, False):
            for c, want in goals:
                tst = c["test"]
                if tst.get("t") == "bool" and tst["var"] == k:
                    sc[val] += 1 if ((val == tst["value"]) == want) else 0
                if tst.get("t") == "dev" and k.endswith(":ON") and \
                        k[:-3] in tst["tags"]:
                    sc[val] += 1 if ((val == tst["on"]) == want) else 0
        b["init"] = sc[True] > sc[False]


# ── 근거 추적 ──────────────────────────────────────────────────

_NUM_IN_TEXT = re.compile(r"-?\d+(?:\.\d+)?")


def trace_problems(model, interlocks):
    """모델의 조건이 인터락 리스트 원문으로 되짚어지는지.

    · 조건마다 IL NO 와 원문이 리스트에 실제로 있어야 한다
    · 비교 조건의 설정값·지연 숫자는 그 원문에 적힌 숫자여야 한다
    문제가 없으면 빈 목록. 모델이 설정값을 '만들어' 넣는 경로가 생기면
    여기서 걸린다 (자기 점검 [주입] 이 이것을 본다).
    """
    src = {}
    for it in interlocks or []:
        for c in it.get("conditions") or []:
            src.setdefault(_s(it.get("il_no")), set()).add(_s(c.get("raw")))
    out = []
    for cid, c in (model.get("conds") or {}).items():
        raws = src.get(c.get("il_no"))
        if not raws or c.get("raw") not in raws:
            out.append("%s: 원문이 인터락 리스트에 없음" % cid)
            continue
        nums = {float(x) for x in _NUM_IN_TEXT.findall(c["raw"])}
        t = c.get("test") or {}
        if t.get("t") == "cmp" and float(t.get("sp")) not in nums:
            out.append("%s: 설정값 %s 가 원문에 없음" % (cid, t.get("sp")))
        if c.get("delay") and float(c["delay"]) not in nums:
            out.append("%s: 지연 %s 가 원문에 없음" % (cid, c["delay"]))
    return out
