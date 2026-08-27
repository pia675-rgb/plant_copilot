#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — 검색 파이프라인 조립

mode 로 구성을 갈아끼울 수 있게 만든 것이 이 파일의 요점이다.
같은 평가셋에 대해 아래를 각각 돌려 표를 만든다.

    lexical   BM25 단독            (v1 상당 — 사전은 없음)
    hybrid    BM25 + dense + RRF
    full      BM25 + dense + RRF + cross-encoder 재정렬

"리랭커를 붙였습니다"가 아니라 "붙여서 Top-1 이 몇 점 올랐습니다"를
말하기 위한 구조다.

사용:
    python -m retrieval.pipeline --mode lexical --tag AIT-4002 --alarm "누수"
"""

import argparse
import csv
import json
import os
import sys

from openpyxl import load_workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from ingest.build_index import load as load_index  # noqa: E402
from retrieval.bm25 import BM25  # noqa: E402
from retrieval import alarm_rules  # noqa: E402
from retrieval import fusion  # noqa: E402

MODES = ("lexical", "hybrid", "full")


def load_instruments():
    """IO List + 계기 리스트 조인 (ingest/lists.py 한 곳에서만 합친다)."""
    from ingest.lists import load_points
    return load_points(config.INSTRUMENTS,
                       getattr(config, "INSTRUMENT_SPECS", None) or getattr(config, "INSTRUMENT_SPEC", None),
                         None,
                       getattr(config, "TB_LIST", None))


class Retriever:
    """
    strict=True 이면 요청한 mode 를 실제로 구성하지 못할 때 예외를 던진다.

    무음 강등은 실험을 오염시킨다. 이전 버전은 Ollama 가 안 떠 있으면
    경고 한 줄만 찍고 렉시컬로 내려갔고, 그 결과가 "hybrid" 라는 이름으로
    스코어카드에 실렸다. 평가에서는 반드시 strict=True 로 쓴다.
    """

    def __init__(self, mode="full", verbose=False, strict=False):
        if mode not in MODES:
            raise ValueError("mode 는 %s 중 하나여야 합니다." % (MODES,))
        self.mode = mode
        self.verbose = verbose
        self.records = load_index()
        self.bm25 = BM25(self.records)
        self.instruments = load_instruments()
        self.dense = None
        self._shared = None         # 본문이 같은 코드 묶음 (지연 계산)
        self.degraded = []          # 요청했지만 못 쓴 구성요소
        # 왜 못 썼는지도 남긴다. 사유가 콘솔에만 찍히면 화면에서는
        # "거절만 계속 나온다" 로 보이고 원인을 짚을 수 없다.
        self.degrade_reasons = {}
        self.rerank_active = False

        if mode in ("hybrid", "full"):
            from retrieval.dense import DenseIndex, why_unavailable
            why = why_unavailable()
            if why is None:
                self.dense = DenseIndex(self.records).ensure()
            else:
                msg = "임베딩(%s) 사용 불가 — %s" % (config.embed_signature(), why)
                if strict:
                    raise RuntimeError("mode=%s 를 구성할 수 없습니다 — %s"
                                       % (mode, msg))
                print("  [강등] " + msg)
                self.degraded.append("dense")
                self.degrade_reasons["dense"] = msg

        if mode == "full":
            if not config.RERANK_ENABLED:
                if strict:
                    raise RuntimeError(
                        "mode=full 인데 COPILOT_RERANK=0 으로 꺼져 있습니다.")
                self.degraded.append("rerank(off)")
                self.degrade_reasons["rerank(off)"] = (
                    "COPILOT_RERANK=0 으로 리랭커가 꺼져 있습니다.")
            else:
                try:
                    fusion.get_reranker()
                    self.rerank_active = True
                except Exception as e:              # noqa: BLE001
                    if strict:
                        raise RuntimeError(
                            "리랭커(%s)를 불러올 수 없습니다: %s"
                            % (config.RERANK_MODEL, e))
                    print("  [강등] 리랭커 사용 불가: %s" % e)
                    self.degraded.append("rerank")
                    self.degrade_reasons["rerank"] = (
                        "리랭커(%s)를 불러올 수 없습니다: %s"
                        % (config.RERANK_MODEL, e))

    @property
    def effective_mode(self):
        """실제로 구성된 모드. 강등되었으면 이름을 낮춰서 돌려준다."""
        if self.dense is None:
            return "lexical"
        if self.mode == "full" and not self.rerank_active:
            return "hybrid"
        return self.mode

    def degrade_detail(self):
        """
        강등 사유와 그 결과 무엇이 나빠지는지.

        dense 가 빠지면 어휘가 겹치지 않는 질의(한글·동의어)를 못 찾아
        CRAG 가 abstain 으로 끝낸다. 측정값으로는 lexical 17/45 대
        hybrid 33/45 이고, 답이 있는 39문항 중 28건이 과잉거절이었다.
        """
        out = []
        for k in self.degraded:
            item = {"component": k,
                    "reason": self.degrade_reasons.get(k, "사유 미기록")}
            if k == "dense":
                item["impact"] = ("어휘가 겹치지 않는 질의를 찾지 못해 "
                                  "대부분 거절(abstain)로 끝납니다. "
                                  "측정: lexical 17/45 vs hybrid 33/45")
            elif k.startswith("rerank"):
                item["impact"] = "상위 근거 정렬 품질이 떨어집니다."
            out.append(item)
        return out

    def label(self):
        """스코어카드에 쓸 정직한 라벨."""
        if not self.degraded:
            return self.mode
        return "%s→%s(강등:%s)" % (self.mode, self.effective_mode,
                                  ",".join(self.degraded))

    def _by_pid(self):
        """P&ID 태그 → 레코드. 처음 쓸 때 한 번만 만든다."""
        idx = getattr(self, "_pid_index", None)
        if idx is None:
            idx = {}
            for rec in self.instruments.values():
                for k in (rec.get("P&ID TAG"), rec.get("_pid_source_tag"),
                          rec.get("TAG")):
                    k = str(k or "").strip().upper().replace(" ", "")
                    if k:
                        idx.setdefault(k, rec)
            self._pid_index = idx
        return idx

    def device_of(self, tag):
        """
        태그의 기기 모델/메이커를 반환.
        IO TAG가 들어오면 P&ID TAG / io_tags 로 한 번 더 찾아본다.
        반환값은 리스트 (유연한 부분 매칭용) 또는 None.
        """
        if not tag:
            return None

        inst = self.instruments.get(tag) or {}

        # instruments 는 **IO 태그**로 키가 잡혀 있는데, 조회는 P&ID 태그로
        # 들어온다(api/server.resolve_to_pid 가 바꿔 넣는다). 그래서 계기를
        # 못 찾고 기기 한정이 통째로 풀렸다 — 그러면 어느 태그로 물어도
        # 카드 매뉴얼이 상위를 채우고, 벤더 매뉴얼이 있는데도 "근거가
        # 흩어졌다"로 거절이 난다. P&ID 태그로도 찾을 수 있게 색인해 둔다.
        if not inst:
            inst = self._by_pid().get(str(tag).upper().replace(" ", "")) or {}

        if not inst:
            for key, rec in self.instruments.items():
                io_tags = rec.get("io_tags") or []
                if tag in io_tags or tag == key:
                    inst = rec
                    break

        model = str(inst.get("MODEL") or "").strip()
        maker = str(inst.get("MAKER") or inst.get("Maker") or "").strip()

        if not model and not maker:
            return None

        import re
        keys = []
        if model:
            keys.append(model)
            for part in re.split(r"[\s&/,]+", model):
                part = part.strip()
                if len(part) >= 2:
                    keys.append(part)
        if maker:
            keys.append(maker)
            for part in re.split(r"[\s_/]+", maker):
                if len(part) >= 3:
                    keys.append(part)

        seen = set()
        out = []
        for k in keys:
            ku = k.upper()
            if ku not in seen:
                seen.add(ku)
                out.append(k)
        return out or None

    def retrieve(self, query, tag=None, device=None, top_k=None):
        """반환: [(record, score, trace)] — trace 는 어느 검색기가 올렸는지."""
        device = device or self.device_of(tag)
        top_k = top_k or config.FINAL_TOP_K

        # SCADA 알람 라우팅 — 알람명(HH/LL/LOOP/CMD)과 SSL 코드는
        # 매뉴얼에 존재하지 않는 어휘라 그대로 던지면 못 찾거나 엉뚱한
        # 절차 문서와 겹친다. 유형이 잡히면 매뉴얼·코드표의 실제
        # 어휘를 확장어로 붙여 검색하고, 원문은 코드 조회에만 쓴다.
        # 자연어 질의는 type=None — 종전과 완전히 같은 경로다.
        route = alarm_rules.classify(query)
        self.last_route = route if route.get("type") else None
        # 알람명 자체는 검색어에서 뺀다. 정보량이 없어서만이 아니다 —
        # 같은 낱말이 다른 뜻으로 존재한다. M9e 매뉴얼의 "loop"은
        # 신호 루프가 아니라 DI Loop(수처리 배관)여서, LOOP ERROR 를
        # 그대로 섞으면 Shipping Bracket 제거 절차가 원인 후보로 올라온다.
        q_search = query
        if route["expand"]:
            q_search = " ".join(route["expand"])
        self.last_query = q_search   # 채점·화면은 실제 검색어를 본다

        exact = self.bm25.exact_code(query, device=device)
        lex = self.bm25.search(q_search, device=device)

        if self.mode == "lexical" or self.dense is None:
            hits = [(r, s, {"bm25": i + 1, "bm25_score": float(s),
                            "found_by": 1})
                    for i, (r, s) in enumerate(lex)]
        else:
            den = self.dense.search(q_search, device=device)
            hits = [(r, s, w)
                    for r, s, w in fusion.rrf([lex, den],
                                              names=["bm25", "dense"])]

        if self.mode == "full" and self.rerank_active and hits:
            keep = {r["id"]: w for r, _s, w in hits}   # 융합 단계 신호 보존
            reranked = fusion.rerank(q_search, hits, top_k=top_k + len(exact))
            new = []
            for i, (r, s) in enumerate(reranked):
                w = dict(keep.get(r["id"], {}))
                w["rerank"] = i + 1
                if s is not None:
                    w["rerank_score"] = float(s)
                new.append((r, s if s is not None else 0.0, w))
            hits = new

        # 코드 완전일치는 항상 최상단. 검색 결과가 아니라 조회 결과다.
        seen = {r["id"] for r in exact}
        out = [(r, 999.0, {"exact_code": 1, "found_by": 1}) for r in exact]
        out += [(r, s, w) for r, s, w in hits if r["id"] not in seen]
        out = self._cap_card(out, device,
                             card_primary=route["card_primary"])
        out = self._fold_shared(out)
        return self._diversify(out, top_k, device)

    def _shared_family(self):
        """
        본문이 글자 그대로 같은 코드 묶음. 코퍼스 전체에서 한 번만 센다.

        M9e 매뉴얼 p.403 은 코드 4000~5000 서른일곱 개에 같은 설명 한 줄을
        붙여 놓았다("System Error — ... power cycle the instrument"). 코드는
        다르지만 읽을 내용이 하나뿐이다.

        추출기가 이미 이 상황을 알아채고 shared_description 을 남겨 두었으나,
        검색은 그것을 안 보고 서른일곱 건을 각각 후보로 다뤘다. 어휘도
        벡터도 같은 본문이니 점수도 같고, 결과 다섯 자리가 같은 문장으로
        채워진다. 근거가 다섯 건인 줄 알았는데 실제로는 한 건이다.
        """
        if self._shared is not None:
            return self._shared
        fam = {}
        for r in self.records:
            if r.get("kind") != "error_code":
                continue
            key = (str(r.get("device") or ""), (r.get("text") or "").strip())
            if not key[1]:
                continue
            fam.setdefault(key, []).append(r)
        self._shared = {k: v for k, v in fam.items() if len(v) > 1}
        return self._shared

    def _fold_shared(self, ranked):
        """
        본문이 같은 코드 묶음을 한 자리로 접는다.

        접되 **숨기지는 않는다.** 남긴 항목의 제목에 묶인 코드 범위와 개수를
        적고, trace 에 코드 목록을 넣는다. 서른일곱 개 중 하나만 보여주면서
        그 사실을 말하지 않으면, 근거가 하나뿐인 것처럼 읽힌다.

        코드 완전일치(exact_code)는 접지 않는다. 사용자가 4001 을 직접 쳤는데
        4000 으로 바꿔 보여주면 조회가 아니라 추측이 된다.
        """
        fam = self._shared_family()
        if not fam:
            return ranked

        out, seen = [], set()
        for rec, score, trace in ranked:
            key = (str(rec.get("device") or ""), (rec.get("text") or "").strip())
            if trace.get("exact_code") or key not in fam:
                out.append((rec, score, trace))
                continue
            if key in seen:
                continue                      # 같은 본문 — 이미 한 자리 썼다
            seen.add(key)

            codes = sorted(str(r.get("code") or r.get("id") or "")
                           for r in fam[key])
            rec = dict(rec)                   # 색인 원본은 건드리지 않는다
            rec["title"] = "%s (코드 %s~%s · %d종 공통 설명)" % (
                rec.get("title") or rec.get("id"),
                codes[0], codes[-1], len(codes))
            trace = dict(trace)
            trace["folded"] = len(codes)
            trace["folded_codes"] = codes
            out.append((rec, score, trace))
        return out

    def _cap_card(self, ranked, device, card_primary=False):
        """카드(ET200SP) 근거가 상위를 독식하지 않게 한 자리로 제한한다.

        카드 매뉴얼은 어느 태그로 물어도 통과시킨다 — 배선·채널 문제는
        계기와 무관하게 카드 쪽일 수 있기 때문이다. 그 규칙 자체는 맞다.
        문제는 분량이다. 실물 색인 650청크 중 131이 카드라, 'Loop error'
        처럼 흔한 문구로는 카드 본문이 상위 다섯 자리를 전부 가져간다.
        그러면 벤더 매뉴얼이 있는데도 근거의 기기가 흩어졌다고 판정돼
        abstain 이 나온다 — M300 계기를 물었는데 카드 설명만 나오는 식이다.

        기기 키가 지정된 조회에서, 그 기기의 근거가 하나라도 있으면 카드는
        한 건만 남긴다. 기기 근거가 없으면 카드가 유일한 단서이므로 그대로 둔다.
        """
        if card_primary:
            # 루프·SSL 계열 알람은 카드가 주 근거다. 분석기 전원이
            # 나가면 계기는 아무 코드도 못 낸다 — 그 상실을 진단하는
            # 것은 카드다. 이 경우 카드를 한 건으로 줄이면 정답을
            # 지운다. 제한 규칙 자체는 계측 알람에서 여전히 맞다.
            #
            # 다만 독식도 막는다. 정비원은 카드 진단과 계기 쪽 원인
            # 후보(예: The Analyzer Will Not Power On)를 함께 본다.
            # 확보 창 안에 계기 근거가 없고 뒤에 있으면 마지막 자리와
            # 바꾼다 — 순위 재조정이 아니라 결과 구성 정책이며,
            # 이 분기는 SCADA 알람 유형에서만 발화한다(평가 문항
            # 448개 발화 0건, selfcheck 가드).
            win = int(getattr(config, "FINAL_TOP_K", 5))
            card = str(getattr(config, "CARD_DEVICE", "") or "").upper()
            keys = [device] if isinstance(device, str) else list(device or [])
            keys = [str(k).upper() for k in keys if str(k).strip()]

            def _owned(r):
                rd = str(r.get("device") or "").upper()
                return (bool(rd) and rd != card
                        and any(rd == k or k in rd or rd in k
                                for k in keys))

            if keys and not any(_owned(r) for r, _s, _w in ranked[:win]):
                pick = next((i for i, (r, _s, _w) in enumerate(ranked)
                             if i >= win and _owned(r)), None)
                # 자리를 내주는 쪽은 창 안 마지막 카드 **본문**이다.
                # 코드표 항목(error_code)을 밀어내면 "무엇이 문제인지"
                # 층이 사라진다 — 확보하려던 것을 확보하다 잃는 꼴.
                spots = [i for i, (r, _s, _w) in enumerate(ranked[:win])
                         if str(r.get("device") or "").upper() == card
                         and r.get("kind") == "manual_text"]
                if pick is not None and spots:
                    ranked = list(ranked)
                    ranked.insert(spots[-1], ranked.pop(pick))
                    del ranked[win - 1 if spots[-1] < win - 1 else win]
            return ranked
        card = str(getattr(config, "CARD_DEVICE", "") or "").upper()
        if not card or not device:
            return ranked
        keys = [device] if isinstance(device, str) else list(device or [])
        keys = [str(k).upper() for k in keys if str(k).strip()]
        if not keys:
            return ranked

        def is_card(r):
            return str(r.get("device") or "").upper() == card

        def is_owned(r):
            rd = str(r.get("device") or "").upper()
            return bool(rd) and not is_card(r) and any(
                rd == k or k in rd or rd in k for k in keys)

        if not any(is_owned(r) for r, _s, _w in ranked):
            return ranked
        limit = int(getattr(config, "CARD_MAX_HITS", 1))
        keep, cards = [], []
        for r, s, w in ranked:
            if is_card(r):
                if len(cards) < limit:
                    cards.append((r, s, w))
                continue
            keep.append((r, s, w))
        # 남긴 카드 근거는 해당 기기 근거 **뒤**에 놓는다. 앞에 두면 상위
        # 세 건의 기기가 갈려 "근거가 흩어졌다"로 채점돼, 벤더 매뉴얼이
        # 멀쩡히 있는데도 거절이 나온다. 카드는 보조 단서지 주 근거가 아니다.
        at = min(len(keep), int(getattr(config, "CARD_INSERT_AT", 3)))
        return keep[:at] + cards + keep[at:]

    # ── 결과 구성 다양성 ────────────────────────────────────
    def _diversify(self, ranked, top_k, device):
        """
        상위 결과에 정보 계층이 하나만 남는 것을 막는다.

        왜 필요한가. 색인은 두 층이다. 코드표 항목은 "이 코드가 무슨
        뜻이고 무엇을 하라"를 짧게 말하고, 매뉴얼 본문은 "그 조치를
        어떻게 하는지"를 길게 말한다. 순수 유사도 순위로 자르면 긴
        본문 청크가 짧은 코드표 항목을 밀어내고 상위가 한 층으로
        쏠린다. 정비원에게는 둘 다 필요하다 — 무엇이 문제인지와
        어떻게 조치하는지는 다른 질문이다.

        기기 축도 같다. 계기 자체의 고장과 입력 카드·배선의 고장은
        서로 다른 원인 계층이며, 현장에서 "신호가 이상하다"는 둘
        중 어느 쪽으로도 갈 수 있다. 계기 문서가 수백 청크로 많다는
        이유만으로 카드 문서가 상위에서 사라지면 안 된다.

        이 규칙은 특정 문항을 맞히기 위한 것이 아니라 결과 구성에
        대한 정책이다. 순위 자체는 바꾸지 않고, 확보 창 안에서 과다
        대표된 항목 하나를 빠진 계층의 최상위 항목과 바꾼다.

        확보 창을 상위 3건으로 둔 것은 시스템의 다른 부분과 맞추기
        위해서다. 근거 충분성 채점기도 상위 3건만 보고, 화면도 상단
        몇 건을 먼저 읽힌다. 5번째 자리에 밀어 넣으면 규칙이 있으나
        마나 하다. 1위는 어떤 경우에도 건드리지 않는다.
        """
        if config.DIVERSIFY == "off" or len(ranked) <= top_k:
            return ranked[:top_k]

        win = min(config.DIVERSIFY_WINDOW, top_k)
        head = list(ranked[:top_k])
        tail = list(ranked[top_k:])

        def kind_of(item):
            return item[0]["kind"]

        def is_card(item):
            return (item[0].get("device") or "") == config.CARD_DEVICE

        # 확보할 계층: (판별 함수, 최소 개수)
        wants = [
            (lambda it: kind_of(it) == "error_code", 1),
            (lambda it: kind_of(it) == "manual_text", 1),
        ]
        # 기기 축은 all 모드에서, 계기 태그일 때만
        if config.DIVERSIFY == "all" and device and device != config.CARD_DEVICE:
            wants.append((is_card, 1))

        for match, need in wants:
            if sum(1 for it in head[:win] if match(it)) >= need:
                continue
            cand = next((it for it in head[win:] if match(it)), None)
            pool = head
            if cand is None:
                cand = next((it for it in tail if match(it)), None)
                pool = tail
            if cand is None:
                continue                      # 후보 자체가 없으면 넘어간다
            # 교체 대상: 확보 창 안에서 뒤에서부터, 1위와 코드 완전일치는
            # 제외하고, 다른 확보 조건을 깨지 않는 항목
            victim = None
            for i in range(win - 1, 0, -1):
                it = head[i]
                if it[2].get("exact_code"):
                    continue
                ok = True
                for m2, n2 in wants:
                    if m2(it) and sum(1 for h in head[:win] if m2(h)) <= n2:
                        ok = False
                        break
                if ok:
                    victim = i
                    break
            if victim is None:
                continue
            cand[2]["diversified"] = 1
            pool.remove(cand)
            head.insert(victim, cand)
            head = head[:top_k]
        return head

    # ── 사람이 읽는 출력 ────────────────────────────────────
    def render(self, query, tag=None):
        res = self.retrieve(query, tag=tag)
        L = ["=" * 72,
             "질의: %s   태그: %s   모드: %s" % (query, tag or "-", self.mode),
             "-" * 72]
        for r, s, w in res:
            L.append("· [%s] %s" % (r["kind"], r["title"][:60]))
            L.append("   %s p.%d  score=%.4f  %s"
                     % (r["source"]["file"][:34], r["source"]["pdf_page"],
                        s, w))
            L.append("   %s" % r["text"][:160].replace("\n", " "))
        L.append("=" * 72)
        return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="v2 검색 파이프라인")
    ap.add_argument("--mode", default="full", choices=MODES)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--alarm", default="")
    ap.add_argument("--code", default="")
    ap.add_argument("--strict", action="store_true",
                    help="구성 실패 시 조용히 강등하지 않고 중단")
    args = ap.parse_args()
    q = (args.alarm + " " + args.code).strip()
    r = Retriever(mode=args.mode, strict=args.strict)
    print(r.render(q, tag=args.tag))
    if r.degraded:
        print("※ 실제 구성: %s" % r.label())


if __name__ == "__main__":
    main()
