#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel_index.py — 판넬 역인덱스와 상실 영향 조회

계기 리스트의 PANEL 열은 태그 하나가 어느 판넬에 결선되는지를 적어 놓은
것이다. 이걸 뒤집으면 현장에서 실제로 자주 나오는 질문에 답할 수 있다.

    by_tag("AIT-1001")          이 계기는 어느 판넬·카드이고, 현장 어디인가
    by_panel("CUB-B")           이 판넬에는 무엇이 물려 있나
    impact("CUB-B/R0/S8")       이 카드를 잃으면 무엇을 잃나
    common_cause()              한 인터락의 조건이 같은 카드에 몰려 있는가

세 번째가 이 모듈을 만든 이유다. Siemens S7-400H/410H 이중화 구성에서는
CPU·전원·통신이 이중화되고 랙 증설도 스위칭으로 대응하므로, **한 번에
잃는 단위는 판넬이 아니라 IO 카드 하나**다. 카드는 이중화되지 않는다.

판넬 단위 상실은 계산하지 않는다. 성립하지 않는 시나리오에 숫자를 붙여
보여주면 현장 판단을 왜곡한다. 판넬은 위치·구성 조회에만 쓴다.

── 판정하는 것과 판정하지 않는 것 ────────────────────────────

카드를 잃으면 그 카드에 물린 채널의 값이 무효가 된다. 그 다음 PLC 가
어떻게 동작하는지는 **대체값(substitute value) 정책**에 달려 있고, 그건
인터락 리스트에도 계기 리스트에도 없다. 그래서 트립 여부는 단정하지
않는다. 대신 리스트만으로 확실히 말할 수 있는 것을 말한다.

    · 어떤 인터락이 이 카드의 신호에 의존하는가
    · 그 의존이 조건 전체인가 일부인가
    · 결합 논리가 AND 인가 OR 인가 — 남는 보호가 있는가
    · 그 인터락이 바이패스 가능한가, 안전 인터락인가

계기 단품 고장 방향 판정은 없다. FAULT MODE 열이 실물 Instrument List 에
없기 때문이다. 관행으로 가정하면 리스트에 없는 값을 근거로 인터락 성립을
판정하게 되므로 기능 자체를 두지 않는다.
"""

import csv
import os
import sys
from collections import defaultdict

from openpyxl import load_workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

# SYSTEM·LOOP GROUP 은 뺐다. 업로드 자료 어디에도 없는 열이었고, 데모
# 원천에만 있어서 실물 전환 시 통째로 비었다. 상실 범위는 계통 대신
# 단자대(TB) 로 묶는다 — TB 는 TB List 에서 실제로 온다.
WANT = ["TAG", "SERVICE", "MAKER", "MODEL",
        "MEAS TYPE", "UNIT", "SIGNAL", "PLC", "RACK",
        "SLOT", "CH", "PANEL", "TERMINAL", "DWG No.", "MANUAL FILE",
        "PN(DP)", "LOCATION", "IO TYPE", "ADD", "DESCRIPTION"]

# 표준 열 별칭은 ingest/lists.py 가 처리한다 (조인 지점과 같은 곳).


def _norm(v):
    return str(v).strip() if v is not None else ""


def load_instrument_rows(path=None):
    """
    IO List + 계기 리스트 조인 결과를 행 목록으로.

    두 문서를 합치는 규칙은 ingest/lists.py 한 곳에만 둔다. 읽는 쪽이
    세 군데라 각자 조인하면 규칙이 갈라진다.
    """
    from ingest.lists import load_points
    points = load_points(path or config.INSTRUMENTS,
                         getattr(config, "INSTRUMENT_SPECS", None) or getattr(config, "INSTRUMENT_SPEC", None),
                         None,
                         getattr(config, "TB_LIST", None))
    if not points:
        raise RuntimeError("IO List 를 읽지 못했습니다: %s"
                           % (path or config.INSTRUMENTS))
    out = []
    seen_panel_col = False
    for tag in sorted(points):
        src = points[tag]
        if "PANEL" in src:
            seen_panel_col = True
        rec = {w.upper(): _norm(src.get(w.upper())) for w in WANT}
        # 배선이 비어 있는 점(출력 등)은 판넬·카드 조회 대상이 아니다.
        # 실물에서 채워야 할 칸이며, 여기서 추정해 채우지 않는다.
        if not rec["PANEL"]:
            continue
        out.append(rec)
    if not seen_panel_col:
        raise RuntimeError("IO List 에 PANEL 열이 없습니다.")
    return out


def load_locations(path=None):
    """PANEL_LOCATIONS.csv — 배치도와 같은 원천에서 나온 판넬 위치."""
    path = path or config.PANEL_LOCATIONS
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            name = (r.get("PANEL") or "").strip()
            if not name:
                continue
            out[name] = {
                "panel": name,
                "kind": r.get("KIND") or "",
                "area": r.get("AREA") or "",
                "indoor": (r.get("INDOOR") or "").upper() == "Y",
                "grid": r.get("GRID") or "",
                "width_mm": r.get("WIDTH_MM") or "",
                "depth_mm": r.get("DEPTH_MM") or "",
                "file": r.get("FILE") or "",
                "sheet_no": r.get("SHEET_NO") or "",
                "page": int(r["PAGE"]) if (r.get("PAGE") or "").isdigit() else 1,
                "find": r.get("FIND") or name,
                "points": r.get("POINTS") or "",
                "remark": r.get("REMARK") or "",
            }
    return out


class PanelIndex:
    def __init__(self, instruments_path=None, locations_path=None,
                 interlock=None):
        self.rows = load_instrument_rows(instruments_path)
        self.locations = load_locations(locations_path)
        self._by_tag = {}
        self._by_panel = defaultdict(list)
        self._by_card = defaultdict(list)
        for r in self.rows:
            self._by_tag[r["TAG"]] = r
            self._by_panel[r["PANEL"]].append(r)
            self._by_card[self._card_key(r)].append(r)
        self._il = interlock          # InterlockIndex (선택)
        # 위치 정보가 없는 판넬 — 감추지 않고 드러낸다
        self.unlocated = sorted(p for p in self._by_panel
                                if p and p not in self.locations)

    # ── 기본 조회 ───────────────────────────────────────────
    def panels(self):
        out = []
        for name in sorted(self._by_panel):
            if not name:
                continue
            loc = self.locations.get(name, {})
            out.append({"panel": name, "points": len(self._by_panel[name]),
                        "area": loc.get("area", ""), "grid": loc.get("grid", ""),
                        "kind": loc.get("kind", ""),
                        "located": name in self.locations})
        return out

    def by_tag(self, tag):
        r = self._by_tag.get(tag)
        if not r:
            return None
        panel = r["PANEL"]
        loc = self.locations.get(panel)
        return {
            "tag": tag,
            "service": r["SERVICE"],
            "panel": panel,
            "terminal": r["TERMINAL"],
            "plc": r["PLC"],
            "rack": r["RACK"],
            "slot": r["SLOT"],
            "ch": r["CH"],
            "card": self._card_key(r),
            "station": r.get("PN(DP)", ""),
            "signal": r["SIGNAL"],
            "location": loc,
            "drawing": ({"type": "ARRANGEMENT", "sheet_no": loc["sheet_no"],
                         "file": loc["file"], "page": loc["page"],
                         "find": loc["find"]} if loc else None),
        }

    def by_panel(self, panel):
        items = self._by_panel.get(panel)
        if not items:
            return None
        by_terminal = defaultdict(list)
        for r in items:
            by_terminal[(r["TERMINAL"] or "-").split("-")[0]].append(r["TAG"])
        return {
            "panel": panel,
            "location": self.locations.get(panel),
            "points": len(items),
            "tags": sorted(r["TAG"] for r in items),
            "by_terminal": {k: sorted(v) for k, v in sorted(by_terminal.items())},
            "plc": sorted({r["PLC"] for r in items if r["PLC"]}),
        }

    # ── 카드 (IO 모듈) ──────────────────────────────────────
    #
    # Siemens S7-400H/410H 이중화 구성에서는 CPU·전원·통신이 이중화되고
    # **IO 카드만 단일**이다. 그래서 현실적으로 한 번에 잃는 최소 단위는
    # 판넬이 아니라 카드다. 판넬 단위는 증설·개조처럼 계획된 작업에서만
    # 의미가 있다.
    #
    # 카드 식별은 (판넬, 랙, 슬롯)이다. 분산 IO 에서는 판넬이 곧
    # 스테이션이라 랙·슬롯 번호가 판넬별로 매겨진다.
    @staticmethod
    def card_id(panel, rack, slot, station=""):
        """
        카드 식별자.

        표준 IO List 에는 PN(DP)(PROFINET 스테이션) 열이 있어서
        원격 스테이션이 구분된다. 중앙 큐비클은 PN(DP) 가 비고 RACK 으로
        갈린다. 판넬을 앞에 두는 것은 사람이 읽기 위해서고, 뒤쪽
        (스테이션, 랙, 슬롯) 이 실제 유일성을 만든다.
        """
        st = _norm(station)
        head = "%s/DP%s" % (panel, st) if st else panel
        return "%s/R%s/S%s" % (head, rack if rack != "" else "0",
                               slot if slot != "" else "0")

    def _card_key(self, r):
        return self.card_id(r["PANEL"], r["RACK"], r["SLOT"],
                            r.get("PN(DP)", ""))

    def cards(self):
        out = []
        for key in sorted(self._by_card):
            rows = self._by_card[key]
            r0 = rows[0]
            # 대표 IO TYPE (가장 많이 나온 값)
            from collections import Counter
            types = [str(x.get("IO TYPE") or "").strip() for x in rows]
            types = [t for t in types if t]
            io_type = Counter(types).most_common(1)[0][0] if types else ""
            out.append({
                "card": key,
                "panel": r0["PANEL"],
                "station": r0.get("PN(DP)", ""),
                "rack": r0["RACK"],
                "slot": r0["SLOT"],
                "plc": r0["PLC"],
                "io_type": io_type,
                "points": len(rows),
                "channels": sorted((x["CH"] for x in rows),
                                   key=lambda c: int(c) if str(c).isdigit()
                                   else 0),
                "tags": sorted(x["TAG"] for x in rows),
            })
        return out

    def by_card(self, card):
        rows = self._by_card.get(card)
        if not rows:
            return None
        r0 = rows[0]
        return {
            "card": card,
            "panel": r0["PANEL"],
            "station": r0.get("PN(DP)", ""),
            "rack": r0["RACK"],
            "slot": r0["SLOT"],
            "plc": r0["PLC"],
            "location": self.locations.get(r0["PANEL"]),
            "points": len(rows),
            "tags": sorted(x["TAG"] for x in rows),
            "channels": [{"ch": x["CH"], "tag": x["TAG"],
                          "service": x["SERVICE"],
                          "terminal": x["TERMINAL"],
                          "signal": x["SIGNAL"]}
                         for x in sorted(rows, key=lambda x: (
                             int(x["CH"]) if str(x["CH"]).isdigit() else 0))],
        }

    def card_of(self, tag):
        r = self._by_tag.get(tag)
        return self._card_key(r) if r else None

    # ── 카드 상실 영향 ──────────────────────────────────────
    def impact(self, card):
        """
        이 카드를 잃으면 무엇을 잃나.

        판넬 단위 상실은 다루지 않는다. 이중화(S7-400H/410H) 구성에서는
        랙 증설도 스위칭으로 대응하므로 판넬 전체가 죽는 상황 자체가
        성립하지 않는다. 성립하지 않는 시나리오를 계산해 보여주면
        현장 판단을 왜곡한다.

        트립 여부도 판정하지 않는다(대체값 정책이 리스트에 없음).
        말할 수 있는 것은 의존 관계와 남는 보호 유무까지다.
        """
        base = self.by_card(card)
        if not base:
            return None
        lost = set(base["tags"])
        by_tb = defaultdict(list)
        for r in self._by_card[card]:
            by_tb[(r["TERMINAL"] or "-").split("-")[0]].append(r["TAG"])
        head = {"card": card, "panel": base["panel"],
                "location": base["location"],
                "by_tb": {k: sorted(v)
                          for k, v in sorted(by_tb.items())},
                # 잃는 점을 채널 단위로 싣는다.
                #
                # 화면에서 판넬 계기 목록을 없앴는데, 인터락 표에는 조건에
                # 걸린 태그만 나온다. 그래서 인터락에 안 걸린 계기가 어디에도
                # 보이지 않았다 — "이 카드 내리면 뭘 잃나" 에 답이 반쪽이 된다.
                # 채널 순서·서비스·단자를 함께 주어 화면이 그대로 쓰게 한다.
                "channels": base["channels"]}

        il = self._interlock()
        deps, affected = [], defaultdict(list)
        if il is not None:
            for it in il.items:
                cond_tags = set()
                for c in it["conditions"]:
                    cond_tags.update(c["tags"])
                hit = cond_tags & lost
                if not hit:
                    continue
                total = bool(cond_tags) and cond_tags <= lost
                logic = (it.get("logic") or "").upper()
                if total:
                    remain = "없음 — 조건 태그 전부가 이 카드"
                elif logic == "AND":
                    remain = ("없음 — AND 결합이라 한 태그만 잃어도 "
                              "성립을 확인할 수 없음")
                elif logic == "OR":
                    remain = "일부 — OR 결합, 남은 태그 경로는 유지 (%s)" % \
                             ", ".join(sorted(cond_tags - lost))
                else:
                    remain = "판정 불가 — 결합 논리 미표기"
                rec = {
                    "il_no": it["il_no"],
                    "output_tag": it["output_tag"],
                    "kind": it["kind"],
                    "action": it["action"],
                    "logic": logic,
                    "priority": it.get("priority"),
                    "bypassable": it.get("bypassable"),
                    "reset": it.get("reset"),
                    "lost_tags": sorted(hit),
                    "cond_tags": sorted(cond_tags),
                    "dependency": "전체" if total else "일부",
                    "remaining_protection": remain,
                    "dwg_no": it.get("dwg_no"),
                    "sheet": it.get("sheet"),
                    "remark": it.get("remark"),
                    "safety": (it["kind"] == "INTERLOCK"
                               and not it.get("bypassable")),
                }
                deps.append(rec)
                affected[it["output_tag"]].append(rec)

        out_rows = []
        for tag in sorted(affected):
            recs = affected[tag]
            meta = (il.outputs.get(tag, {}) if il is not None else {}) or {}
            out_rows.append({
                "tag": tag,
                "service": meta.get("service") or "",
                "type": meta.get("type") or "",
                "fail_position": meta.get("fail") or "",
                "interlocks": [r["il_no"] for r in recs],
                "has_safety": any(r["safety"] for r in recs),
                "worst_dependency": ("전체" if any(r["dependency"] == "전체"
                                                 for r in recs) else "일부"),
            })

        dep_tags = set()
        for r in deps:
            dep_tags.update(r["lost_tags"])
        deps.sort(key=lambda r: (not r["safety"], r["dependency"] != "전체",
                                 r["il_no"]))

        caveat = ("PLC 대체값(substitute value) 정책은 인터락 리스트·계기 "
                  "리스트에 없습니다. 트립 여부는 판정하지 않았고, 의존 "
                  "관계만 리스트에서 그대로 계산했습니다.")

        # 각 채널이 인터락에 걸려 있는지 표시한다. 화면에서 "지시·기록만
        # 상실" 과 "보호까지 상실" 을 한눈에 가르기 위한 것이다.
        for ch in head.get("channels", []):
            ch["interlocks"] = sorted(
                r["il_no"] for r in deps if ch["tag"] in r["lost_tags"])
            ch["safety"] = any(r["safety"] for r in deps
                               if ch["tag"] in r["lost_tags"])

        head.update({
            "points": len(lost),
            "lost_tags": sorted(lost),
            "tags_in_interlock": sorted(dep_tags),
            "tags_not_in_interlock": sorted(lost - dep_tags),
            "dependencies": deps,
            "affected_outputs": out_rows,
            "safety_count": sum(1 for r in deps if r["safety"]),
            "interlock_loaded": il is not None,
            "caveat": caveat,
        })
        return head

    # ── 공통원인 점검 ───────────────────────────────────────
    def common_cause(self):
        """
        한 인터락의 조건 태그가 **같은 카드**에 몰려 있지 않은가.

        카드가 단일 고장 지점이므로, OR 로 여러 계기를 걸어 두어도 그
        계기들이 같은 카드에 물려 있으면 카드 하나로 보호가 통째로
        사라진다. 설계 검토에서 실제로 보는 항목이다.

        판정은 리스트만으로 한다. 결과가 0건이면 '문제 없음'이 아니라
        '이 리스트 범위에서는 걸린 것이 없음'이다.
        """
        il = self._interlock()
        if il is None:
            return {"loaded": False, "findings": [], "checked": 0}
        findings = []
        for it in il.items:
            cond = set()
            for c in it["conditions"]:
                cond.update(c["tags"])
            known = {t: self.card_of(t) for t in cond
                     if self.card_of(t) is not None}
            if len(known) < 2:
                continue
            groups = defaultdict(list)
            for t, k in known.items():
                groups[k].append(t)
            shared = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
            if not shared:
                continue
            all_one = len(groups) == 1 and len(known) == len(cond)
            findings.append({
                "il_no": it["il_no"],
                "output_tag": it["output_tag"],
                "kind": it["kind"],
                "logic": (it.get("logic") or "").upper(),
                "bypassable": it.get("bypassable"),
                "cond_tags": sorted(cond),
                "shared_cards": shared,
                "all_on_one_card": all_one,
                "severity": ("보호 전부 상실" if all_one else "중복 조건 축소"),
                "safety": (it["kind"] == "INTERLOCK"
                           and not it.get("bypassable")),
            })
        findings.sort(key=lambda f: (not f["safety"], not f["all_on_one_card"],
                                     f["il_no"]))
        return {"loaded": True, "checked": len(il.items),
                "findings": findings,
                "note": ("한 인터락의 조건 태그가 같은 카드에 물려 있으면 "
                         "카드 하나로 중복 조건이 함께 사라집니다. "
                         "0건은 '설계가 안전하다'가 아니라 '이 리스트 "
                         "범위에서 걸린 것이 없다'는 뜻입니다.")}


    # 계기 단품 고장 방향 판정(fault_effect)은 제거했습니다.
    #
    # Upscale / Downscale 판정은 FAULT MODE 열에 전적으로 의존했는데,
    # 실물 Instrument List 에 그 열이 없습니다. 관행(4-20mA 는 NAMUR
    # Downscale)으로 가정할 수도 있지만, 그러면 리스트에 없는 값을
    # 근거로 인터락 성립을 판정하게 됩니다. 이 프로젝트가 지켜온
    # 원칙과 어긋나므로 기능을 뺐습니다.
    #
    # 계기 사양서를 받을 수 있게 되면 되살릴 수 있습니다.

    # ── 내부 ────────────────────────────────────────────────
    def _interlock(self):
        if self._il is None:
            try:
                from retrieval.interlock_index import InterlockIndex
                self._il = InterlockIndex()
            except Exception as e:      # 조용히 넘기지 않는다
                self.interlock_error = str(e)
                return None
        return self._il

    # ── 렌더 ────────────────────────────────────────────────
    def render_tag(self, tag):
        d = self.by_tag(tag)
        if not d:
            return "계기 리스트에 %s 가 없습니다." % tag
        loc = d["location"]
        L = ["=" * 72, "%s   %s" % (d["tag"], d["service"]), "=" * 72,
             "판넬     : %s" % d["panel"]]
        if loc:
            L.append("설치 위치 : %s / 그리드 %s / %s"
                     % (loc["area"], loc["grid"],
                        "실내" if loc["indoor"] else "옥외"))
            L.append("배치 도면 : %s Sh.%s p.%d"
                     % (loc["file"], loc["sheet_no"], loc["page"]))
        else:
            L.append("설치 위치 : 배치 정보 없음 (PANEL_LOCATIONS.csv 미등록)")
        L.append("단자대   : %s" % (d["terminal"] or "-"))
        L.append("IO       : %s Rack %s Slot %s Ch %s"
                 % (d["plc"], d["rack"], d["slot"], d["ch"]))
        L.append("신호     : %s" % d["signal"])
        L.append("=" * 72)
        return "\n".join(L)

    def render_panel(self, panel):
        d = self.by_panel(panel)
        if not d:
            return "계기 리스트에 %s 판넬이 없습니다." % panel
        loc = d["location"]
        L = ["=" * 72, "%s   계기 %d점" % (panel, d["points"]), "=" * 72]
        if loc:
            L.append("%s / 그리드 %s / %s / %s"
                     % (loc["area"], loc["grid"],
                        "실내" if loc["indoor"] else "옥외", loc["kind"]))
            L.append("배치 도면 %s Sh.%s p.%d"
                     % (loc["file"], loc["sheet_no"], loc["page"]))
        L.append("")
        L.append("■ 시스템별")
        for tb, tags in d["by_tb"].items():
            L.append("  %-10s %2d  %s" % (tb, len(tags), ", ".join(tags)))
        L.append("")
        L.append("■ 단자대별")
        for tb, tags in d["by_terminal"].items():
            L.append("  %-6s %2d  %s" % (tb, len(tags), ", ".join(tags)))
        L.append("=" * 72)
        return "\n".join(L)

    def render_impact(self, card):
        d = self.impact(card)
        if not d:
            return "계기 리스트에 %s 카드가 없습니다." % card
        loc = d["location"]
        L = ["=" * 76, "%s 카드를 잃으면 — 영향 범위" % card, "=" * 76,
             "잃는 계기 %d점 · 단자대 %d곳"
             % (d["points"], len(d["by_tb"])),
             "판넬 %s" % d["panel"]]
        if loc:
            L.append("위치 %s / 그리드 %s" % (loc["area"], loc["grid"]))
        L.append("")
        L.append("■ 잃는 채널")
        for ch in d.get("channels", []):
            mark = "★" if ch.get("safety") else ("·" if ch.get("interlocks")
                                                 else " ")
            L.append("  %s Ch%-3s %-12s %-30s %-9s %s"
                     % (mark, ch["ch"], ch["tag"], ch["service"][:30],
                        ch["terminal"] or "-",
                        ",".join(ch.get("interlocks") or []) or "인터락 없음"))
        L.append("")

        if not d["interlock_loaded"]:
            L.append("■ 인터락 리스트를 읽지 못해 의존 관계를 계산하지 "
                     "못했습니다.")
            L.append("=" * 76)
            return "\n".join(L)

        L.append("■ 이 카드 신호에 의존하는 인터락 %d건 (안전 인터락 %d건)"
                 % (len(d["dependencies"]), d["safety_count"]))
        for r in d["dependencies"]:
            mark = "★" if r["safety"] else " "
            L.append("")
            L.append("  %s [%s] %s %s → %s   의존 %s"
                     % (mark, r["il_no"], r["output_tag"], r["kind"],
                        r["action"], r["dependency"]))
            L.append("      잃는 조건 태그: %s   (전체 조건: %s / %s)"
                     % (", ".join(r["lost_tags"]), ", ".join(r["cond_tags"]),
                        r["logic"] or "논리 미표기"))
            L.append("      남는 보호: %s" % r["remaining_protection"])
            L.append("      바이패스 %s · 리셋 %s · 근거 %s Sh.%s"
                     % ("가능" if r["bypassable"] else "불가",
                        r["reset"], r["dwg_no"], r["sheet"]))

        L.append("")
        L.append("■ 영향받는 출력 %d건" % len(d["affected_outputs"]))
        for o in d["affected_outputs"]:
            L.append("  %s %-28s %s · 고장위치 %s · 의존 %s%s"
                     % ("★" if o["has_safety"] else " ", o["tag"],
                        o["service"] or "-", o["fail_position"] or "-",
                        o["worst_dependency"],
                        "  (안전 인터락 포함)" if o["has_safety"] else ""))

        if d["tags_not_in_interlock"]:
            L.append("")
            L.append("■ 인터락에 걸려 있지 않은 계기 %d점 — 지시·기록만 상실"
                     % len(d["tags_not_in_interlock"]))
            L.append("  " + ", ".join(d["tags_not_in_interlock"]))

        L.append("")
        L.append("※ " + d["caveat"])
        L.append("=" * 76)
        return "\n".join(L)

    def render_common_cause(self):
        d = self.common_cause()
        if not d["loaded"]:
            return "인터락 리스트를 읽지 못했습니다."
        L = ["=" * 76,
             "공통원인 점검 — 한 인터락의 조건이 같은 카드에 몰려 있는가",
             "=" * 76,
             "인터락 %d건 점검 · 지적 %d건" % (d["checked"],
                                              len(d["findings"]))]
        for f in d["findings"]:
            L.append("")
            L.append("  %s[%s] %s %s (%s 결합) — %s"
                     % ("★ " if f["safety"] else "  ", f["il_no"],
                        f["output_tag"], f["kind"], f["logic"] or "논리 미표기",
                        f["severity"]))
            for card, tags in f["shared_cards"].items():
                L.append("      같은 카드 %s ← %s" % (card, ", ".join(tags)))
            L.append("      전체 조건: %s" % ", ".join(f["cond_tags"]))
        if not d["findings"]:
            L.append("")
            L.append("  지적 없음.")
        L.append("")
        L.append("※ " + d["note"])
        L.append("=" * 76)
        return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="판넬 조회")
    ap.add_argument("--tag", help="계기 태그 — 어느 판넬인가")
    ap.add_argument("--panel", help="판넬명 — 무엇이 물려 있나")
    ap.add_argument("--card", help="카드 ID (예: CUB-B/R0/S8) — 카드 상실 영향")
    ap.add_argument("--cards", action="store_true", help="카드 목록")
    ap.add_argument("--common-cause", action="store_true",
                    dest="common_cause",
                    help="한 인터락의 조건이 같은 카드에 몰려 있는지 점검")
    ap.add_argument("--list", action="store_true", help="판넬 목록")
    a = ap.parse_args()
    ix = PanelIndex()
    if a.list:
        for p in ix.panels():
            print("%-8s %3d점  %-24s %-4s %s"
                  % (p["panel"], p["points"], p["area"], p["grid"],
                     "" if p["located"] else "← 배치 정보 없음"))
    elif a.cards:
        for c in ix.cards():
            print("%-16s %-7s ch %-2d  %s"
                  % (c["card"], c["panel"], c["points"], ", ".join(c["tags"])))
    elif a.common_cause:
        print(ix.render_common_cause())
    elif a.card:
        print(ix.render_impact(a.card))
    elif a.panel:
        print(ix.render_panel(a.panel))
    elif a.tag:
        print(ix.render_tag(a.tag))
    else:
        ap.print_help()
