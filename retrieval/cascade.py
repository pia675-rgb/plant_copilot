#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cascade.py — 인터락 연쇄 추적

"XV-4101이 닫히면 뭐가 연달아 서나."

인터락 리스트는 그 자체가 그래프다. 한 출력의 상태가 다른 인터락의
조건으로 등장하면 거기서 간선이 생긴다.

    XV-3102 CLOSE
      → IL-3101-02 퍼미시브 조건 "XV-3102 OPEN 확인" 불만족
      → P-3101 기동 허가 상실 → STOP
      → IL-4101-02 퍼미시브 조건 "P-3101 운전 중" 불만족
      → XV-4101 열림 허가 상실 → CLOSE

전파 규칙은 두 가지뿐이다.

    INTERLOCK(OR)   조건 하나라도 성립 → 출력이 그 ACTION 으로 강제됨
    PERMISSIVE(AND) 조건 하나라도 불만족 → 그 ACTION 허가 상실
                    → 반대 상태로 귀결 (FAIL 위치가 아니라 로직상의 귀결)

**한계를 분명히 해 둔다.** 이 그래프는 *로직* 그래프지 *공정* 그래프가
아니다. "밸브가 닫혀서 탱크 수위가 떨어지고 그래서 펌프가 선다"는
연쇄는 인터락 리스트 어디에도 적혀 있지 않다. 그건 공정 지식이다.
추정해서 그리지 않는다 — 필요하면 data/PROCESS_LINKS.csv 에 사람이
명시적으로 적고, 그렇게 들어온 간선은 출처를 PROCESS 로 구분해 표시한다.

사용:
    python -m retrieval.cascade --tag XV-3102 --state CLOSE
    python -m retrieval.cascade --tag AIT-4001 --cond LOW --depth 4
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from retrieval.interlock_index import InterlockIndex, OPPOSITE, cond_text  # noqa: E402

PROCESS_LINKS = os.path.join(config.DATA_DIR, "PROCESS_LINKS.csv")

# 조건에 쓰인 상태 ↔ 실제 출력 상태 대응
STATE_EQ = {
    "RUN": {"RUN", "START", "ON", "OPEN"},
    "STOP": {"STOP", "OFF", "CLOSE"},
    "OPEN": {"OPEN", "RUN", "START", "ON"},
    "CLOSE": {"CLOSE", "STOP", "OFF"},
}


def state_matches(cond_state, actual):
    """조건이 요구하는 상태와 실제 상태가 같은 쪽인가."""
    if cond_state is None:
        return None
    return actual in STATE_EQ.get(cond_state, {cond_state})


def load_process_links():
    """사람이 직접 적은 공정 연계. 없으면 빈 목록."""
    if not os.path.exists(PROCESS_LINKS):
        return []
    out = []
    with open(PROCESS_LINKS, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if not r.get("FROM_TAG"):
                continue
            out.append({k: (v or "").strip() for k, v in r.items()})
    return out


class Cascade:
    def __init__(self, index=None):
        self.ix = index or InterlockIndex()
        self.links = load_process_links()

    # ── 한 단계 전개 ────────────────────────────────────────
    def step(self, tag, state):
        """
        tag 가 state 가 되었을 때 직접 영향받는 출력들.
        반환: [{output, result_state, il, why, via}]
        """
        out = []
        for it, c in self.ix._by_in.get(tag, []):
            if not c["parsed"] or c["state"] is None:
                continue
            # 여러 태그가 걸린 조건은 AND 면 전부 같은 상태여야 성립
            if len(c["tags"]) > 1 and c["multi"] == "AND":
                # 지금 단계에서는 확정할 수 없다 — 부분 성립으로 표시
                partial = True
            else:
                partial = False

            ok = state_matches(c["state"], state)
            if ok is None:
                continue

            if it["kind"] == "INTERLOCK" and it["logic"] == "OR" and ok:
                out.append({
                    "output": it["output_tag"],
                    "result": it["action"],
                    "il": it, "cond": c, "via": "INTERLOCK",
                    "partial": partial,
                    "why": "%s 조건 성립 → %s 강제"
                           % (it["il_no"], it["action"]),
                })
            elif it["kind"] == "PERMISSIVE" and it["logic"] == "AND" and not ok:
                res = OPPOSITE.get(it["action"], it["action"])
                out.append({
                    "output": it["output_tag"],
                    "result": res,
                    "il": it, "cond": c, "via": "PERMISSIVE",
                    "partial": partial,
                    "why": "%s 허가 조건 불만족 → %s 불가, %s 로 귀결"
                           % (it["il_no"], it["action"], res),
                })

        # 사람이 명시한 공정 연계
        for lk in self.links:
            if lk["FROM_TAG"] == tag and lk.get("FROM_STATE", "") in ("", state):
                out.append({
                    "output": lk["TO_TAG"], "result": lk.get("TO_STATE", "?"),
                    "il": None, "cond": None, "via": "PROCESS",
                    "partial": False,
                    "why": "공정 연계(사용자 정의): %s" % lk.get("NOTE", ""),
                })
        return out

    # ── N차 전개 ────────────────────────────────────────────
    def trace(self, tag, state, depth=4):
        """
        너비 우선으로 depth 단계까지. 같은 (태그, 상태)는 한 번만 전개한다.
        반환: [{level, from, from_state, ...step 결과}]
        """
        seen = {(tag, state)}
        frontier = [(tag, state)]
        levels = []
        for lv in range(1, depth + 1):
            nxt, rows = [], []
            for t, st in frontier:
                for e in self.step(t, st):
                    key = (e["output"], e["result"])
                    rows.append(dict(e, level=lv, src_tag=t, src_state=st,
                                     repeated=key in seen))
                    if key not in seen:
                        seen.add(key)
                        nxt.append(key)
            if not rows:
                break
            levels.append(rows)
            frontier = nxt
            if not frontier:
                break
        return levels

    # ── 렌더 ────────────────────────────────────────────────
    def render(self, tag, state, depth=4):
        levels = self.trace(tag, state, depth)
        info = self.ix.outputs.get(tag)
        L = ["=" * 76,
             "기점: %s = %s%s" % (tag, state,
                                  ("  (%s)" % info["service"]) if info else ""),
             "=" * 76]
        if not levels:
            L.append("  이 상태 변화로 파급되는 인터락이 리스트에 없습니다.")
            L.append("=" * 76)
            return "\n".join(L)

        total = 0
        for rows in levels:
            lv = rows[0]["level"]
            L.append("")
            L.append("── %d차 ──" % lv)
            for e in rows:
                total += 1
                mark = "  (기존 경로와 중복)" if e["repeated"] else ""
                L.append("  %s = %s   ← %s = %s%s"
                         % (e["output"], e["result"], e["src_tag"],
                            e["src_state"], mark))
                if e["via"] == "PROCESS":
                    L.append("      %s   ※ 로직이 아닌 공정 연계"
                             % e["why"])
                    continue
                L.append("      %s" % e["why"])
                L.append("      조건: %s" % cond_text(e["cond"]))
                if e["partial"]:
                    L.append("      ※ 이 조건은 여러 태그가 AND 로 묶여 있음 "
                             "— 나머지 태그 상태 확인 필요")
                it = e["il"]
                L.append("      근거: %s | %s | 도면 %s Sh.%s"
                         % (it["il_no"], it["plc_block"], it["dwg_no"],
                            it["sheet"]))
        L.append("")
        L.append("총 %d개 파급 (최대 %d차)" % (total, len(levels)))
        if not self.links:
            L.append("※ 공정 연계(수위 저하 등)는 인터락 리스트에 없는 정보라 "
                     "포함되지 않았습니다.")
            L.append("   필요하면 data/PROCESS_LINKS.csv 에 직접 등록하십시오.")
        L.append("=" * 76)
        return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="인터락 연쇄 추적")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--state", required=True,
                    help="OPEN / CLOSE / RUN / STOP / ON / OFF")
    ap.add_argument("--depth", type=int, default=4)
    a = ap.parse_args()
    print(Cascade().render(a.tag, a.state.upper(), a.depth))


if __name__ == "__main__":
    main()
