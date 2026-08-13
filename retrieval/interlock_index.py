#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
interlock_index.py — 인터락 역인덱스와 조회

리스트는 "인터락 항목" 순으로 적혀 있지만, 현장 질문은 "태그" 기준으로
들어온다. 그래서 두 방향의 역인덱스를 만든다.

    by_output("XV-4101")  이 밸브는 언제 열리나 / 닫히나
    by_input("AIT-4002")  이 계기가 걸린 인터락은 무엇이고 뭘 멈추나

첫 번째가 현장 문의의 대부분이다. 답을 낼 때 지켜야 할 원칙이 하나 있다.

    **인터락 → 퍼미시브 → 시퀀스 → 수동 순으로 층을 나눠서 보여준다.**

"조건은 다 맞는데 왜 안 열리지"의 답이 거의 항상 첫 층에 있기 때문이다.
전부 한 덩어리로 나열하면 엑셀을 직접 보는 것과 다를 게 없다.

모든 출력은 리스트에 적힌 내용을 그대로 옮긴 것이다. LLM 이 만들지 않는다.
"""

import os
import sys
from collections import defaultdict

from openpyxl import load_workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from ingest.interlock import load_interlocks  # noqa: E402

# 표시 순서 = 실제 우선순위
KIND_ORDER = ["INTERLOCK", "PERMISSIVE", "SEQUENCE", "MANUAL"]
KIND_LABEL = {
    "INTERLOCK": "인터락 — 성립하면 무조건 동작, 다른 조건 무시",
    "PERMISSIVE": "퍼미시브 — 허가 조건",
    "SEQUENCE": "시퀀스 — 자동 운전",
    "MANUAL": "수동 — 운전원 조작",
}
# 요청 동작과 반대 방향(=막는 쪽) 매핑
OPPOSITE = {"OPEN": "CLOSE", "CLOSE": "OPEN", "START": "STOP",
            "STOP": "START", "ON": "OFF", "OFF": "ON"}


def load_outputs(path=None):
    """
    출력(밸브·펌프) 사양.

    별도 "output list" 문서는 실제 프로젝트에 없다. 출력은 IO List 의
    DO/AO 점이고, 사양은 계기 리스트와 부속 데이터에 있다. 세 문서를
    합치는 규칙은 ingest/lists.py 한 곳에만 둔다 — 여기서 엑셀을 직접
    읽으면 계기 리스트 양식이 바뀔 때마다 조용히 깨진다.
    """
    from ingest.lists import load_points
    pts = load_points(path or config.IO_LIST,
                      getattr(config, "INSTRUMENT_SPECS", None) or getattr(config, "INSTRUMENT_SPEC", None),
                      None)
    out = {}
    for tag, r in pts.items():
        out[tag] = {
            "tag": tag,
            "service": r.get("SERVICE") or r.get("DESCRIPTION") or "",
            "type": r.get("TYPE") or "",
            # FAIL POSITION 은 인터락 리스트의 "* Valve Action" 이 원본이다.
            # 아래 값은 그 문서에서 못 읽었을 때 쓰는 대체값이라, 인터락
            # 조회 쪽에서 읽은 값이 있으면 그것이 이긴다(_merge_fail 참조).
            "fail": r.get("FAIL POSITION") or "",
        }
    # 인터락 리스트에 Valve Action 이 적힌 출력은 그 값으로 덮는다.
    try:
        from ingest.interlock import load_interlocks
        for it in load_interlocks():
            f = it.get("fail")
            t = it.get("output_tag")
            if not t:
                continue
            if t not in out:
                # 인터락 리스트에만 있는 출력 태그(밸브·펌프)는 IO List 나
                # 계기 리스트에 없을 수 있다. 그냥 버리면 "이 밸브 고장
                # 위치는?" 에 답할 자리가 사라지므로, 인터락 문서를 출처로
                # 하는 최소 레코드를 만들어 둔다.
                out[t] = {"tag": t,
                          "service": it.get("service") or "",
                          "type": "",
                          "fail": "",
                          "_src": "interlock"}
            if f:
                out[t]["fail"] = f
    except Exception as e:                                  # noqa: BLE001
        print("[outputs] 인터락 Valve Action 반영 실패:", e)
    return out


def cond_text(c):
    """구조화된 조건을 사람이 읽는 한 줄로. 미파싱이면 원문 그대로."""
    if not c["parsed"]:
        return "%s   ※ 구조화 실패 — 원문 확인 필요" % c["raw"]
    bits = []
    if c["tags"]:
        joiner = " 또는 " if c["multi"] == "OR" else (
            " 및 " if c["multi"] == "AND" else ", ")
        bits.append(joiner.join(c["tags"]))
    if c["kind"] == "ANALOG":
        bits.append("%s %s%s" % (c["op"], _fmt(c["setpoint"]),
                                 (" " + c["unit"]) if c["unit"] else ""))
        if c["level"]:
            bits.append("(%s)" % c["level"])
    else:
        bits.append(c["state"])
    if c["delay_sec"]:
        bits.append("[%s초]" % _fmt(c["delay_sec"]))
    return " ".join(str(b) for b in bits if b)


def _fmt(v):
    return int(v) if float(v).is_integer() else v



def _tag_aliases(tag: str):
    """조회용 별칭. F05-POL-A-UPWP-DI-6019A~F → 6019A 형태도 포함."""
    t = (tag or "").strip()
    if not t:
        return []
    out = {t, t.upper()}
    # ~범위 접미 제거
    import re
    base = re.sub(r"~[A-Z0-9]+$", "", t, flags=re.I)
    if base and base != t:
        out.add(base)
        out.add(base.upper())
    # 슬래시 복합 LCV-P1501/LCV-P1502 → 각 부분
    if "/" in t:
        for part in t.split("/"):
            part = part.strip()
            if part:
                out.add(part)
                out.add(re.sub(r"~[A-Z0-9]+$", "", part, flags=re.I))
    return [x for x in out if x]


class InterlockIndex:
    def __init__(self, interlock_path=None, output_path=None):
        self.items = load_interlocks(interlock_path)
        self.outputs = load_outputs(output_path)
        # 실물 리스트 태그 메타 보강 (OUTPUT_LIST 에 없어도 조회 가능)
        for it in self.items:
            tag = it.get("output_tag")
            if not tag:
                continue
            if tag not in self.outputs:
                self.outputs[tag] = {
                    "tag": tag,
                    "service": it.get("service") or "",
                    "type": "",
                    "fail": it.get("fail") or "",
                }
            else:
                if it.get("service") and not self.outputs[tag].get("service"):
                    self.outputs[tag]["service"] = it["service"]
                if it.get("fail") and not self.outputs[tag].get("fail"):
                    self.outputs[tag]["fail"] = it["fail"]
        self._by_out = defaultdict(list)
        self._by_in = defaultdict(list)
        for it in self.items:
            tag = it["output_tag"]
            self._by_out[tag].append(it)
            # 별칭: F05-...-6019A~F → F05-...-6019A 로도 조회 가능하게
            for al in _tag_aliases(tag):
                if al != tag:
                    self._by_out[al].append(it)
            for c in it["conditions"]:
                for tg in c["tags"]:
                    self._by_in[tg].append((it, c))
                    for al in _tag_aliases(tg):
                        if al != tg:
                            self._by_in[al].append((it, c))

    # ── 출력 태그 조회 ──────────────────────────────────────

    def _resolve_out(self, tag):
        """정확 일치 → 별칭 → 대소문자 무시 → 접두 일치."""
        if not tag:
            return []
        items = self._by_out.get(tag) or self._by_out.get(tag.upper()) or []
        if items:
            return items
        for al in _tag_aliases(tag):
            items = self._by_out.get(al) or self._by_out.get(al.upper()) or []
            if items:
                return items
        # 접두: 질의가 저장된 태그의 ~ 앞부분
        tu = tag.upper()
        for key, vals in self._by_out.items():
            ku = key.upper()
            base = ku.split("~")[0]
            if tu == base or ku.startswith(tu + "~") or tu.startswith(base):
                return vals
        return []

    def by_output(self, tag, action=None):
        """
        action 을 주면(예: OPEN) 그 동작을 기준으로 재구성한다.
          · blocking : 반대 동작을 강제하는 인터락 = 열림을 막는 것
          · enabling : 해당 동작의 퍼미시브/시퀀스/수동
        """
        items = self._resolve_out(tag)
        if not items:
            return None
        # 대표 키는 리스트에 실제 저장된 output_tag
        tag = items[0].get("output_tag") or tag
        info = self.outputs.get(tag, {"tag": tag})
        opp = OPPOSITE.get((action or "").upper())

        blocking, enabling, other = [], [], []
        for it in sorted(items, key=lambda x: (x["priority"],
                                               KIND_ORDER.index(x["kind"])
                                               if x["kind"] in KIND_ORDER else 9)):
            if not action:
                other.append(it)
            elif it["kind"] == "INTERLOCK" and it["action"] == opp:
                blocking.append(it)
            elif it["action"] == action.upper():
                enabling.append(it)
            else:
                other.append(it)
        return {"output": info, "action": (action or "").upper() or None,
                "blocking": blocking, "enabling": enabling, "other": other,
                "all": items}

    # ── 입력 태그 조회 ──────────────────────────────────────
    def by_input(self, tag):
        """이 계기가 걸려 있는 인터락과, 그 결과 영향받는 출력."""
        hits = self._by_in.get(tag, [])
        if not hits:
            return None
        affected = sorted({it["output_tag"] for it, _ in hits})
        return {"tag": tag, "hits": hits, "affected_outputs": affected}

    # ── 렌더 ────────────────────────────────────────────────
    def render_output(self, tag, action=None):
        res = self.by_output(tag, action)
        if not res:
            return "인터락 리스트에 %s 항목이 없습니다." % tag
        o = res["output"]
        L = ["=" * 76,
             "%s   %s" % (o["tag"], o.get("service") or ""),
             "%s · %s · %s · %s" % (o.get("type") or "-", o.get("fail") or "-",
                                    o.get("type") or "-", o.get("fail") or "-"),
             "=" * 76]

        if res["action"]:
            L.append("질의: %s 는 언제 %s 되는가" % (tag, res["action"]))
            L.append("")

        if res["blocking"]:
            L.append("■ %s 을(를) 막는 조건 — 하나라도 성립하면 %s 되지 않음"
                     % (res["action"], res["action"]))
            L.append("  이 층이 최우선입니다. 아래 허가 조건이 전부 만족해도 "
                     "여기가 살아 있으면 동작하지 않습니다.")
            L += self._block(res["blocking"])

        if res["enabling"]:
            L.append("■ %s 조건" % res["action"])
            L += self._block(res["enabling"])

        if res["other"]:
            L.append("■ 그 밖의 항목")
            L += self._block(res["other"])
        L.append("=" * 76)
        return "\n".join(L)

    def _block(self, items):
        L = []
        for it in items:
            L.append("")
            L.append("  [%s] %s → %s   (%s)"
                     % (it["il_no"], it["kind"], it["action"],
                        KIND_LABEL.get(it["kind"], "")))
            joiner = "OR — 하나라도 성립하면" if it["logic"] == "OR" \
                else "AND — 전부 만족해야"
            L.append("    조건 결합: %s | 리셋: %s | 바이패스: %s"
                     % (joiner, it["reset"],
                        "가능" if it["bypassable"] else "불가"))
            for c in it["conditions"]:
                L.append("      · %s" % cond_text(c))
                if c["raw"] != cond_text(c):
                    L.append("          원문: %s" % c["raw"])
            L.append("    근거: 인터락 리스트 %s | %s | 도면 %s Sh.%s"
                     % (it["il_no"], it["plc_block"], it["dwg_no"], it["sheet"]))
            if it["remark"]:
                L.append("    비고: %s" % it["remark"])
        return L

    def render_input(self, tag):
        res = self.by_input(tag)
        if not res:
            return "%s 가 걸린 인터락이 없습니다." % tag
        L = ["=" * 76,
             "%s 가 걸려 있는 인터락" % tag,
             "영향 받는 출력: %s" % ", ".join(res["affected_outputs"]),
             "=" * 76]
        for it, c in res["hits"]:
            L.append("  [%s] %s %s → %s"
                     % (it["il_no"], it["output_tag"], it["kind"], it["action"]))
            L.append("      조건: %s" % cond_text(c))
            L.append("      바이패스 %s | 리셋 %s | %s"
                     % ("가능" if it["bypassable"] else "불가",
                        it["reset"], it["dwg_no"]))
        L.append("=" * 76)
        return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="인터락 조회")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--action", default=None,
                    help="OPEN / CLOSE / START / STOP / ON / OFF")
    ap.add_argument("--input", action="store_true",
                    help="입력 태그 기준 조회 (이 계기가 뭘 멈추나)")
    a = ap.parse_args()
    ix = InterlockIndex()
    print(ix.render_input(a.tag) if a.input
          else ix.render_output(a.tag, a.action))
