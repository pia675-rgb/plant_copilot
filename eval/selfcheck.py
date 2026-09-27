#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selfcheck.py — 시연 전 전 경로 점검 (고장 주입 포함)

preflight 는 "환경이 갖춰졌는가"를 본다. 이 스크립트는 한 걸음 더
들어가 **각 경로가 실제로 동작하는가, 그리고 실패했을 때 그 사실이
드러나는가**를 본다.

    python -m eval.selfcheck
    python -m eval.selfcheck --skip-llm     # 모델 없이 구조만

## 왜 만들었나

지금까지 세 번 같은 유형으로 깨졌다.

1. 임베딩 캐시가 다른 모델 것이어도 그대로 재사용됨 → 검색 품질만 조용히 저하
2. 조치 생성 LLM 이 없어도 화면은 그럴듯하게 나옴 → 근거 나열인 줄 모름
3. COPILOT_PROVIDER=ollama 가 챗봇에서는 인정되지 않음 → 조용히 규칙 엔진

공통점은 **실패해야 알 수 있는 가정**이었고, 실패해도 화면이 그럴듯해서
알기 어려웠다는 것이다. 그래서 여기서는 정상 동작만 보지 않고, 고장을
주입해서 **검출 장치가 실제로 작동하는지**까지 확인한다.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

_rows = []


def run(name, fn, critical=True):
    try:
        ok, detail = fn()
    except Exception as e:                                  # noqa: BLE001
        ok, detail = False, "%s: %s" % (type(e).__name__, str(e)[:130])
    _rows.append(("OK  " if ok else ("실패" if critical else "주의"),
                  name, detail))
    return ok


# ── 1. 검색 경로 ────────────────────────────────────────────
def c_search_modes():
    """세 모드가 모두 구성되고 강등 없이 도는가."""
    from retrieval.pipeline import Retriever
    out = []
    for m in ("lexical", "hybrid"):
        r = Retriever(mode=m)
        if r.degraded:
            return False, "%s 강등: %s" % (m, ",".join(r.degraded))
        n = len(r.retrieve("acid residual low", tag="AIT-4002"))
        out.append("%s %d건" % (m, n))
    return True, " / ".join(out)


def c_korean_query():
    """한글 질의가 실제로 영문 매뉴얼에 닿는가 — v2 논지의 핵심."""
    from graph.app_graph import Copilot2
    o = Copilot2(mode="hybrid").answer(
        tag="AIT-4002", alarm="산 잔량이 부족하다고 뜹니다")
    if o["decision"] != "advise":
        return False, "판정 %s (충분성 %.2f) — 한글 질의가 거절됨" % (
            o["decision"], o.get("grade", 0))
    return True, "advise %.2f, 근거 %d건" % (o.get("grade", 0),
                                           len(o.get("evidence", [])))


def c_abstain_works():
    """벤더 문서 없는 태그를 실제로 거절하는가."""
    from graph.app_graph import Copilot2
    o = Copilot2(mode="hybrid").answer(
        tag="PIT-2003", alarm="압력 지시가 이상합니다")
    if o["decision"] != "abstain":
        return False, "판정 %s — 근거 없는 태그에 답하고 있음" % o["decision"]
    # 거절했다고 다 통과시키면 안 된다. 검색이 죽어서 아무것도 못 찾은
    # 경우도 abstain 이 나오기 때문이다. 벤더 문서 게이트가 이유여야 한다.
    parts = o.get("grade_parts") or {}
    if "no_vendor_doc" not in parts:
        return False, ("거절은 했으나 사유가 다릅니다 (%s) — 검색이 죽어서 "
                       "생긴 거절일 수 있습니다" % (o.get("grade_reason") or "")[:50])
    return True, "벤더 문서 게이트로 거절 — %s" % (o.get("grade_reason") or "")[:50]


def c_degrade_visible():
    """
    [주입] 강등이 화면에서 보이는가.

    벡터 검색이 꺼지면 대부분의 질의가 거절로 끝난다. 그런데 거절은
    정상 동작처럼 보여서 "왜 다 거절하지" 만 반복하게 된다. 실제로
    모든 태그가 abstain 인 상태를 며칠 만에 발견했다.

    /api/health 가 강등 사유와 그 결과를 함께 싣는지 확인한다. 강등이
    없는 정상 상태에서는 통과다 — 이 항목이 보는 것은 '강등되었을 때
    드러나는가' 이지 '강등되었는가' 가 아니다.
    """
    from api.server import health
    h = health()
    if not h.get("degraded"):
        return True, "강등 없음 (%s)" % h.get("effective_mode")
    detail = h.get("degrade_detail")
    if not detail:
        return False, ("강등 %s 인데 사유가 실리지 않습니다 — 화면에서 "
                       "원인을 짚을 수 없습니다" % h["degraded"])
    for d in detail:
        if not d.get("reason") or d["reason"] == "사유 미기록":
            return False, "%s 강등 사유가 비어 있습니다" % d.get("component")
    return True, "강등 %s / 사유·영향 노출됨" % ", ".join(h["degraded"])


def c_ssl_code_lookup():
    """카드 SSL 코드(H 접미사)가 실제로 조회되는가.

    이전 정규식은 H 를 16진 문자로 취급하지 않아 카드 코드 24종
    전부가 조회 불가였다 — "코드 조회가 있다"고 말하면서 카드
    코드는 한 건도 못 찾는 상태. 대표 형태별로 확인한다."""
    from retrieval.pipeline import Retriever
    r = Retriever(mode="lexical")
    for code in ("5H", "11H", "1FH", "10EH"):
        hits = r.bm25.exact_code(code)
        if not any((h.get("code") or "").upper() == code for h in hits):
            return False, "SSL 코드 %s 조회 실패" % code
    # 태그 숫자부 오인 방지 — AIT-4002 의 4002 는 코드가 아니다
    hits = r.bm25.exact_code("AIT-4002 BAD PV")
    if hits:
        return False, "태그 숫자부(4002)를 코드로 오인: %s" % [
            h.get("code") for h in hits]
    return True, "SSL 4형태 조회, 태그 오인 없음"


def c_alarm_rules_inert():
    """알람 라우팅이 평가 문항에서 발화하지 않는가.

    라우팅은 SCADA 알람 어휘(HH/LL/LOOP/CMD/SSL)에서만 켜져야
    한다. 자연어 평가 문항에서 발화하면 확장어가 평가 점수를
    몰래 움직인다 — 평가셋 맞춤 금지 원칙의 자동 가드."""
    import glob
    import json as _json
    from retrieval.alarm_rules import classify
    base = os.path.dirname(os.path.abspath(__file__))
    fired, total = [], 0
    for fp in glob.glob(os.path.join(base, "eval_set*.json")):
        d = _json.load(open(fp, encoding="utf-8"))
        items = d if isinstance(d, list) else \
            d.get("items") or d.get("questions") or []
        for it in items:
            q = it.get("q") or it.get("question") or it.get("query") or ""
            total += 1
            if classify(q)["type"]:
                fired.append(q[:40])
    if fired:
        return False, "평가 문항 %d개에서 라우팅 발화: %s" % (
            len(fired), fired[:3])
    return True, "평가 %d문항 발화 0건" % total


def c_io_channel_unique():
    """같은 카드(판넬·스테이션·랙·슬롯)에 채널 번호가 겹치지 않는가.

    물리적으로 불가능한 배선이다. 데모 데이터 생성 단계에서 채널
    중복이 들어온 적이 있고(7건), 카드 단위 그룹핑을 보여주는 순간
    IO List 를 여는 사람 눈에 바로 걸린다."""
    from retrieval.panel_index import PanelIndex
    p = PanelIndex()
    dup = []
    for card, rows in p._by_card.items():
        seen = {}
        for r in rows:
            ch = str(r.get("CH") if r.get("CH") is not None else "")
            if ch == "":
                continue
            if ch in seen:
                dup.append("%s CH%s: %s/%s"
                           % (card, ch, seen[ch], r["TAG"]))
            seen[ch] = r["TAG"]
    if dup:
        return False, "채널 중복 %d건 — %s" % (len(dup), dup[:3])
    return True, "카드 %d장 채널 유일" % len(p._by_card)


def c_repair_roundtrip():
    """수리안 왕복 [주입] — 중복·헤더 오기를 픽스처에 심고 제안→반영→재점검."""
    import shutil, tempfile, os, hashlib
    from ingest import repair
    src = str(config.IO_LIST)
    orig = hashlib.md5(open(src, 'rb').read()).hexdigest()
    fx = os.path.join(tempfile.gettempdir(), 'sc_repair_fx.xlsx')
    shutil.copy2(src, fx)
    wb, ws, hdr, cm = repair._load_sheet(fx)
    for c in ('PLC', 'PN(DP)', 'RACK', 'SLOT', 'CH'):
        ws.cell(row=hdr + 2, column=cm[c],
                value=ws.cell(row=hdr + 1, column=cm[c]).value)
    ws.cell(row=hdr + 5, column=cm['CH'], value=0)   # 0 은 유효 채널
    ws.cell(row=hdr + 6, column=cm['CH'], value=0)
    for c in ('PLC', 'PN(DP)', 'RACK', 'SLOT'):
        ws.cell(row=hdr + 6, column=cm[c],
                value=ws.cell(row=hdr + 5, column=cm[c]).value)
    ws.cell(row=hdr, column=cm['SIGNAL TYPE1'], value='SIGNL TYPE1')
    wb.save(fx); wb.close()
    plan = repair.propose(io_path=fx, include_cross=False)
    auto = [q for q in plan['proposals'] if q.get('auto')]
    if len(auto) < 3:
        return False, '주입 3건(중복2·헤더1)인데 자동 제안 %d건' % len(auto)
    out = repair.apply([q['id'] for q in auto], io_path=fx)
    left = repair.propose(io_path=fx, include_cross=False)['counts']['auto']
    if left != 0:
        return False, '반영 후에도 자동 제안 %d건 잔존' % left
    if not os.path.exists(fx + '.prev'):
        return False, '.prev 보존이 없음'
    if hashlib.md5(open(src, 'rb').read()).hexdigest() != orig:
        return False, '원본 IO List 가 바뀜 — 픽스처 격리 실패'
    return True, '주입 3건 제안·반영·재점검 0건 / .prev 보존 / 원본 무손상'


def c_repair_key_gate():
    """수리 반영 열쇠 [주입] — 열쇠 없이 apply 가 열리면 실패."""
    import os
    from fastapi.testclient import TestClient
    import api.server as srv
    old = os.environ.get('COPILOT_INGEST_KEY')
    os.environ['COPILOT_INGEST_KEY'] = 'sc-test-key'
    try:
        c = TestClient(srv.app)
        r = c.post('/api/ingest/repair-apply', json={'ids': ['x']})
        if r.status_code != 401:
            return False, '무열쇠 요청이 %d — 401 이어야 함' % r.status_code
        r = c.post('/api/ingest/repair-apply', json={'ids': ['x']},
                   headers={'X-Ingest-Key': 'sc-test-key'})
        if r.status_code != 200:
            return False, '유열쇠 요청이 %d' % r.status_code
    finally:
        if old is None:
            os.environ.pop('COPILOT_INGEST_KEY', None)
        else:
            os.environ['COPILOT_INGEST_KEY'] = old
        try:
            srv._edit_lease['owner'] = None   # 가드가 잡은 임대 반납
        except Exception:
            pass
    return True, '무열쇠 401 · 유열쇠 통과 (반영 대상 없음)'


def c_scenario_stop():
    """시나리오 정지 명령 [주입] — 멈춰 달라는 말이 조회로 새지 않는가.

    "시나리오 정지해주세요" 가 P-5101A **정지 인터락 조회**로 흘렀다.
    "정지" 라는 낱말이 인터락 동작(STOP)과 겹쳐서다. 챗봇으로 시작한
    일을 챗봇으로 끝내지 못했다 (패치 33).
    """
    import os
    from api.server import rule_intent
    for m in ('시나리오 정지해주세요', '재생 멈춰줘', '시뮬레이션 중지',
              '아 시나리오 재생한걸 정지해달란 이야기였어요'):
        r = rule_intent(m, 'P-5101A', 'interlock') or {}
        if not r.get('stopScenario'):
            return False, "'%s' → %s / stop=%s" % (
                m[:22], r.get('type'), r.get('stopScenario'))
        if r.get('playScenario'):
            return False, "'%s' 가 재생도 함께 켠다" % m[:22]
    # 재생·조회는 원래대로
    r = rule_intent('시나리오 재생해줘', 'P-5101A', 'interlock') or {}
    if not r.get('playScenario') or r.get('stopScenario'):
        return False, '재생 명령이 망가졌습니다'
    r = rule_intent('P-5101A 정지 인터락 조회해줘', None, 'alarm') or {}
    if r.get('type') != 'interlock' or r.get('action') != 'STOP':
        return False, '정지 인터락 조회가 %s/%s 로 샜습니다' % (
            r.get('type'), r.get('action'))
    # 화면 쪽 — 그래픽 페이지가 stop-scenario 를 받는가
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ('ui/react/public/interlock_P-5101A.html',
                'ui/react/dist/interlock_P-5101A.html'):
        p2 = os.path.join(here, rel)
        if not os.path.isfile(p2):
            continue
        with open(p2, encoding='utf-8') as f:
            if 'stop-scenario' not in f.read():
                return False, '%s 가 stop-scenario 를 받지 않습니다' % rel
    # LLM 이 고를 수 있는 도구 목록에도 시나리오 제어가 있어야 한다.
    # 규칙이 못 잡은 표현은 LLM 이 받는데, 그 스키마에 정지가 없으면
    # 가장 가까운 것(인터락 STOP)을 고른다. 실제로 그렇게 샜다.
    # 패치 35 부터 이 지침은 도구 목록에서 만들어진다. 그래서 함수
    # 소스가 아니라 **만들어진 지침**을 본다 — 소스를 문자열로 뒤지는
    # 가드는 코드를 옮기는 순간 보던 자리를 잃고, 잃은 줄도 모른다.
    from api import tools as _tools
    from api.server import llm_command_prompt
    prompt = llm_command_prompt(False)
    # 스키마 줄과 설명을 **따로** 본다. 한 덩어리로 놓고 낱말만 찾으면,
    # 스키마에서 필드가 빠져도 설명문에 남은 같은 낱말이 가려 준다.
    schema = _tools.llm_schema_line()
    for token in ('stopScenario', 'playScenario', 'openGraphic'):
        if token not in schema:
            return False, 'LLM 명령 스키마에 %s 가 없습니다' % token
    for token in ('공정 화면', '시나리오'):
        if token not in prompt:
            return False, '명령 지침에 %s 안내가 없습니다' % token
    # 화면이 없는 태그를 물으면 있는 화면을 열어 주면 안 된다.
    # 사용자는 그 태그의 화면을 보고 있다고 믿는다 (패치 33b).
    for m in ('LCV-01 공정 화면 재생해줘', 'AIT-4002 시나리오 재생해줘',
              'LCV-01 시나리오 정지'):
        r = rule_intent(m, None, 'interlock') or {}
        if r.get('type') != 'chat' or r.get('tag'):
            return False, "'%s' 가 없는 화면을 열었습니다 (tag=%s)" % (
                m[:22], r.get('tag'))
        if '없습니다' not in (r.get('reply') or ''):
            return False, "'%s' 응답에 없다는 말이 없습니다" % m[:22]
    # 화면이 있는 태그는 그대로 열린다
    r = rule_intent('P-5101A 공정 화면 열어줘', None, 'interlock') or {}
    if r.get('tag') != 'P-5101A' or not r.get('openGraphic'):
        return False, 'P-5101A 화면이 열리지 않습니다'
    if r.get('playScenario'):
        return False, '열기만 시켰는데 재생까지 켭니다'
    # ── 낱말만 남은 정지 (패치 36) ─────────────────────────
    #
    # 위 네 표현은 모두 시나리오·시뮬레이션·재생 중 한 낱말을 함께 갖고
    # 있다. 정작 사람이 한 말은 「정지해줘」 였고, 그 표현은 이 가드가
    # 본 적이 없어 알람 조회로 실행되는 동안 아무도 몰랐다. **고친 표현만
    # 보는 가드는 고친 것만 지킨다.**
    from api.server import ChatContext, GraphicState
    playing = ChatContext(
        tag='P-5101A', tab='interlock',
        graphic=GraphicState(open=True, playing=True, tag='P-5101A'))
    idle = ChatContext(
        tag='P-5101A', tab='interlock',
        graphic=GraphicState(open=True, playing=False, tag='P-5101A'))

    # (1) 시나리오가 도는 중이면 낱말 하나로도 멈춘다
    for m in ('정지해줘', '멈춰줘', '멈춰주세요', '중지', '스톱', '정지'):
        r = rule_intent(m, 'P-5101A', 'interlock', ctx=playing) or {}
        if not r.get('stopScenario'):
            return False, ("재생 중인데 '%s' 가 %s 로 갑니다 — 맥락을 "
                           "보지 않습니다" % (m, r.get('type')))
        if r.get('playScenario'):
            return False, "'%s' 가 재생을 함께 켭니다" % m
        if r.get('tag') != 'P-5101A':
            return False, "'%s' 가 %s 를 멈추려 합니다" % (m, r.get('tag'))

    # (2) 맥락이 없으면 **실행하지 않고 되묻는다.** 알람 조회로 실행하던
    #     것이 이 사고의 본체였다.
    for name, ctx in (('도는 중 아님', idle), ('맥락 없음', None)):
        r = rule_intent('정지해줘', 'P-5101A', 'interlock', ctx=ctx) or {}
        if r.get('type') != 'chat' or r.get('stopScenario'):
            return False, "%s 인데 '정지해줘' 가 %s 로 실행됩니다" % (
                name, r.get('type'))
        rep = r.get('reply') or ''
        if '시나리오' not in rep or '인터락' not in rep:
            return False, "%s 되묻기가 두 갈래를 제시하지 않습니다" % name
        if r.get('generic'):
            return False, ("%s 되묻기가 포괄 응답이라 매뉴얼 검색으로 "
                           "샙니다" % name)
    # 문장에 태그가 있으면 그 태그로 되묻는다 — 우리가 바꿔 물으면 안 된다
    r = rule_intent('XV-4101 정지해줘', 'P-5101A', 'interlock') or {}
    if 'XV-4101' not in (r.get('reply') or ''):
        return False, "'XV-4101 정지해줘' 를 다른 설비로 되묻습니다"

    # (3) 조회는 그대로여야 한다 — 정지 인터락 조회, 알람 어휘의 STOP
    r = rule_intent('P-5101A 정지 인터락 조회해줘', None, 'alarm',
                    ctx=playing) or {}
    if r.get('type') != 'interlock' or r.get('action') != 'STOP' \
            or r.get('stopScenario'):
        return False, ("재생 중에 정지 인터락 조회가 %s/%s 로 샙니다"
                       % (r.get('type'), r.get('action')))
    r = rule_intent('P-5101A CMD STOP 알람 조회해줘', None, 'alarm') or {}
    if r.get('type') != 'diagnose':
        return False, ("알람 어휘의 STOP 이 %s 로 갑니다 — 되묻기가 조회를 "
                       "막습니다" % r.get('type'))

    # (4) 맥락은 화면이 실어 보내는 것이다. 서버만 고치고 화면을 안 고치면
    #     판정은 통과하는데 실제로는 맥락이 영영 오지 않는다 (패치 29b 와
    #     같은 자리).
    for rel in ('ui/react/public/interlock_P-5101A.html',
                'ui/react/dist/interlock_P-5101A.html'):
        p2 = os.path.join(here, rel)
        if not os.path.isfile(p2):
            continue
        with open(p2, encoding='utf-8') as f:
            page = f.read()
        if 'plant-graphic' not in page:
            return False, '%s 가 재생 상태를 알려주지 않습니다' % rel
        # 알리는 함수가 있는 것으로는 부족하다 — 재생과 정지 **양쪽에서**
        # 불러야 한다. 한쪽만 부르면 멈춘 뒤에도 도는 중으로 남는다.
        if page.count('scnNotify();') < 2:
            return False, ('%s 가 재생·정지 양쪽에서 상태를 알리지 '
                           '않습니다 (호출 %d곳)'
                           % (rel, page.count('scnNotify();')))

        # 주석으로 꺼 둔 것도 안 부르는 것이다. 글자만 세면 꺼 둔 줄이
        # 그대로 통과한다 — 실제로 이 시험에서 한 번 새어 나갔다.
        if re.search(r'//\s*scnNotify|/\*\s*scnNotify', page):
            return False, '%s 의 상태 알림이 주석 처리되어 있습니다' % rel
    app, app_path = _ui_src('ui/react/src/App.jsx')
    if 'plant-graphic' not in app:
        return False, 'App.jsx 가 재생 상태를 받지 않습니다'
    if 'graphic: {' not in app:
        return False, 'App.jsx 가 재생 상태를 챗봇 맥락에 싣지 않습니다'
    # 선언보다 앞에서 쓰면 렌더 중에 ReferenceError(TDZ) 가 나 화면이
    # 통째로 죽는다. 빌드도 통과하고 위의 글자 검사도 통과했다 — 띄워
    # 보고서야 콘솔에서 찾았다. 그 순서를 여기서 못 박는다 (패치 36).
    if app.index('const [graphicOpen') > app.index('playing: !!(graphicOpen'):
        return False, ('App.jsx 가 graphicOpen 을 선언보다 먼저 씁니다 — '
                       '화면이 렌더 중에 죽습니다')
    import glob as _glob
    js = _glob.glob(os.path.join(here, 'ui', 'react', 'dist', 'assets', '*.js'))
    newest = max(js, key=os.path.getmtime) if js else None
    if not newest or os.path.getmtime(newest) < os.path.getmtime(app_path):
        return False, '빌드본이 App.jsx 보다 오래되었습니다 — npm run build'
    with open(newest, encoding='utf-8') as f:
        if 'plant-graphic' not in f.read():
            return False, '빌드본에 재생 상태 수신이 없습니다 — 빌드가 낡았습니다'

    # (5) 모델도 같은 맥락을 받아야 한다. 규칙만 맥락을 보면 규칙이 아는
    #     표현만 되고 나머지는 다시 엉뚱한 곳으로 간다 (패치 33·35).
    from api.server import ChatRequest, llm_user_line
    line = llm_user_line(
        ChatRequest(message='정지해줘', tag='P-5101A', tab='interlock',
                    context=playing), '정지해줘')
    if 'scenario=playing' not in line:
        return False, '모델에게 재생 상태가 가지 않습니다 — %s' % line[:60]
    if 'scenario=' not in llm_user_line(
            ChatRequest(message='정지해줘'), '정지해줘'):
        return False, '맥락이 없을 때도 상태 칸은 있어야 합니다'
    if 'scenario' not in prompt:
        return False, '명령 지침이 재생 상태 칸을 설명하지 않습니다'

    return True, ('정지 4종 · 낱말 단독 6종(재생 중) · 맥락 없을 때 되묻기 · '
                  '없는 화면 거절 3종 · 열기/재생 구분 · 조회 무손상 · '
                  '화면·빌드본·LLM 스키마 포함')


def c_preflight_gate():
    """환경 점검 게이트 [주입] — 실패를 표시하고도 통과시키지 않는가.

    preflight 가 화면에 "실패 2건" 을 찍고서 종료 코드 0 을 돌려주어,
    배치의 errorlevel 검사가 걸리지 않았다. 검사가 실패를 보고서
    통과시키는 것은 검사가 없는 것보다 나쁘다 — 봤다고 착각하게 만든다.

    아울러 인터락 자료 판정이 isfile 만 보아, 폴더로 해결된 정상 자료를
    "없음" 으로 보고하던 것도 함께 확인한다.
    """
    import subprocess, sys, os
    from eval.preflight import _interlock_exists
    import config

    # 1) 인터락 자료 판정 — 폴더도 유효
    if not _interlock_exists(config.INTERLOCK_XLSX):
        return False, "인터락 자료를 찾지 못함: %s" % config.INTERLOCK_XLSX
    if os.path.isdir(config.INTERLOCK_XLSX):
        pass          # 폴더로 해결된 경우가 이 검사의 본래 대상이다

    # 2) 종료 코드 — 없는 자료 폴더를 가리켜 실패를 만든 뒤 확인
    env = dict(os.environ)
    env["COPILOT_DATA_DIR"] = os.path.join(
        os.path.dirname(config.DATA_DIR), "__no_such_data__")
    # 출력을 파이프로 받으면 윈도우에서 인코딩이 cp949 로 잡힌다. 요약줄의
    # em dash 같은 글자가 그 표에 없어 UnicodeEncodeError 로 죽고, 그것이
    # 종료 코드 1 로 나타나 게이트가 동작한 것처럼 보인다. 콘솔에서는
    # 멀쩡하고 파이프로 받을 때만 그러므로 알아채기 어렵다.
    env["PYTHONIOENCODING"] = "utf-8"

    def _run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "eval.preflight"] + list(extra),
            capture_output=True, env=env, text=True,
            encoding="utf-8", errors="replace")

    r = _run()
    if "Traceback" in (r.stderr or ""):
        return False, "preflight 가 예외로 죽었습니다 — %s" % (
            (r.stderr or "").strip().splitlines()[-1][:70])
    if r.returncode == 0:
        return False, "실패 상황인데 종료 코드 0 — 배치가 멈추지 않는다"
    r2 = _run("--lenient")
    if "Traceback" in (r2.stderr or ""):
        return False, "--lenient 실행이 예외로 죽었습니다 — %s" % (
            (r2.stderr or "").strip().splitlines()[-1][:70])
    if r2.returncode != 0:
        return False, "--lenient 인데 종료 코드 %d" % r2.returncode
    return True, "인터락 폴더 인식 / 실패 시 종료 1 · --lenient 시 0"


def c_terminal_unique():
    """단자 번호 유일성 [주입] — 한 PLC 안에서 주소가 겹치지 않는가.

    IW582+ 한 번호에 다섯 태그가 붙어 있었다. 주소를 슬롯·채널만으로
    만들어 다른 스테이션·랙의 같은 자리와 겹쳤기 때문이다. 배선을
    조회하는 도구가 배선이 불가능한 값을 내놓고 있었다 (패치 30).
    """
    from collections import defaultdict
    from retrieval.panel_index import PanelIndex
    px = PanelIndex()
    by = defaultdict(list)
    for r in px.rows:
        t = str(r.get('TERMINAL') or '').strip().upper()
        if t:
            by[t].append('%s/%s' % (r.get('PANEL'), r.get('TAG')))
    if not by:
        return False, '단자 번호가 하나도 없습니다'
    dups = {k: v for k, v in by.items() if len(v) > 1}
    if dups:
        k, v = sorted(dups.items())[0]
        return False, '단자 %d종 중복 — 예: %s 에 %d건 (%s)' % (
            len(dups), k, len(v), ', '.join(v[:4]))
    return True, '단자 %d점 전부 유일 (한 PLC 기준)' % sum(
        len(v) for v in by.values())


def c_terminal_lookup():
    """단자 번호 역조회 [주입] — 화면이 보여준 값을 되물으면 답하는가.

    판넬 조회가 "IW512+ 1" 처럼 단자 번호를 보여주는데, 그것을 되물으면
    안내문만 돌려주었다. 자료(by_terminal)에는 있는 값이었다 (패치 29c).
    """
    from api.server import rule_intent, get_panel
    px = get_panel()
    if px is None:
        return False, '판넬 색인을 읽지 못했습니다'
    # 자료에서 실재하는 단자 하나를 골라 되묻는다
    term = tag = None
    for prow in px.panels():
        pn = prow.get('panel') if isinstance(prow, dict) else prow
        d = px.by_panel(pn) or {}
        for k, v in (d.get('by_terminal') or {}).items():
            if len(v) == 1:
                term, tag = k, v[0]
                break
        if term:
            break
    if not term:
        return True, '단자가 1건뿐인 항목이 없어 시험 건너뜀'
    q = '%s 태그명은 뭐지?' % str(term).rstrip('+-')
    r = rule_intent(q, None, 'panel') or {}
    rep = r.get('reply') or ''
    if tag not in rep:
        return False, "'%s' → '%s' — %s 가 답에 없음" % (q, rep[:40], tag)
    # 없는 단자는 지어내지 않는다
    r2 = rule_intent('IW9999 태그명은 뭐지?', None, 'panel') or {}
    if '찾지 못했' not in (r2.get('reply') or ''):
        return False, '없는 단자에 답을 지어냈습니다'
    return True, '%s → %s / 없는 단자는 거절' % (term, tag)


def c_feature_question():
    """기능 질문 라우팅 [주입] — 질문이 명령으로 오인되지 않는가 (패치 29b).

    "판넬 조회로 뭘 알 수 있지?" 가 알람 조회 명령으로 실행되던 것을
    막는다. 질문은 안내로, 명령은 명령으로. 그리고 판넬명 챗봇 조회가
    옛 키 이름(by_tb)으로 죽던 것도 함께 확인한다.
    """
    from api.server import rule_intent
    qs = [
        ('판넬 조회로 나는 어떤걸 알 수 있지?', '판넬 조회는'),
        ('인터락 조회는 뭘 보여줘?', '인터락 조회는'),
        ('알람 조회는 어떻게 쓰는거야?', '알람 조회는'),
        ('자료 반입은 무슨 기능이야?', '자료 반입은'),
        ('자유 모드가 뭐야?', '근거 모드(기본)'),
    ]
    for m, head in qs:
        r = rule_intent(m, 'P-5101A', 'interlock') or {}
        if r.get('type') != 'chat' or not (r.get('reply') or '').startswith(head):
            return False, "'%s' → %s / '%s...' — 기능 안내가 아님" % (
                m[:20], r.get('type'), (r.get('reply') or '')[:20])
    cmds = [
        ('P-5101A 인터락 조회해줘', 'interlock'),
        ('AIT-4002 loop error 알람 조회해줘', 'diagnose'),
        ('CUB-A 판넬 조회해줘', 'panel'),      # 크래시 회귀 확인 겸
        ('사용법 알려줘', 'help'),
    ]
    for m, want in cmds:
        try:
            t = (rule_intent(m, None, 'alarm') or {}).get('type')
        except Exception as e:                              # noqa: BLE001
            return False, "'%s' 처리 중 예외 %s" % (m[:20], type(e).__name__)
        if t != want:
            return False, "'%s' → %s (기대 %s)" % (m[:20], t, want)
    return True, '질문 5종 안내 · 명령 4종 유지 · 판넬명 조회 무사'


def c_followup_interlock():
    """인터락 후속 질문 [주입] — 화면 결과로 답하는가 (패치 29).

    이 검사가 없던 동안, 인터락을 조회한 뒤 "말로 설명해줘" 라고 물으면
    직전 알람 조회의 매뉴얼 근거로 답이 나왔다. 사용자가 보는 화면과
    챗봇이 보는 것이 달랐다. 그래서 두 가지를 함께 본다 — 설명 요청이
    후속 질문으로 라우팅되는가, 그 답이 인터락 결과에서 나오는가.
    """
    from fastapi.testclient import TestClient
    import api.server as srv
    c = TestClient(srv.app)

    # 1) 라우팅 — 지시 대명사 없는 설명 요청도 후속 질문이어야 한다
    for m in ('말로 풀어서 설명 부탁해', '자세히 설명해줘'):
        t = (srv.rule_intent(m, 'P-5101A', 'interlock') or {}).get('type')
        if t != 'followup':
            return False, "'%s' 판정 %s — followup 이어야 함" % (m, t)
    # 조회 명령·사용법은 여전히 원래 경로로 가야 한다
    for m, want in (('P-5101A 인터락 조회해줘', 'interlock'),
                    ('사용법 알려줘', 'help'),
                    ('AIT-4002 알람 조회해줘', 'diagnose')):
        t = (srv.rule_intent(m, 'P-5101A', 'interlock') or {}).get('type')
        if t != want:
            return False, "'%s' 판정 %s — %s 이어야 함" % (m, t, want)

    # 2) 답의 출처 — 알람 근거가 함께 있어도 인터락으로 답해야 한다
    il = c.post('/api/interlock',
                json={'tag': 'P-5101A', 'action': 'STOP'}).json()
    if not il.get('found'):
        return False, '인터락 조회 자체가 실패'
    r = c.post('/api/chat', json={
        'message': '말로 풀어서 설명 부탁해', 'tag': 'P-5101A',
        'tab': 'interlock', 'use_llm': False,
        'context': {'tag': 'P-5101A', 'tab': 'interlock', 'interlock': il,
                    'evidence': [{'id': 'x', 'title': 'M300 Alarm',
                                  'cite': 'p.36'}]}}).json()
    if r.get('engine') != 'followup-interlock':
        return False, 'engine %s — 알람 근거로 답하고 있음' % r.get('engine')
    rep = r.get('reply') or ''
    if 'IL-5101A-01' not in rep:
        return False, '인터락 번호가 답에 없음'
    if 'M300' in rep or 'Alarm/Clean' in rep:
        return False, '알람 매뉴얼 내용이 섞였음'
    # 래치 표기를 리스트 그대로 말하는가 (MANUAL 만 사람이 리셋)
    if '사람이 리셋' not in rep:
        return False, 'MANUAL 리셋 표기가 답에 없음'
    return True, '설명 요청 라우팅·인터락 근거 답변·래치 표기 일치'


def c_flood_investigate():
    """동시 알람 조사 [주입] — 4태그+11H 로 판정·반례·코드 근거·단계."""
    from retrieval.panel_index import PanelIndex
    from retrieval.pipeline import Retriever
    from retrieval.flood import investigate
    r = investigate(['AIT-4002', 'AIT-3002', 'FIT-2009', 'AIT-2002'],
                    panel=PanelIndex(), retriever=Retriever(mode='lexical'),
                    codes=['11H'])
    if (r.get('common') or {}).get('level') != 'card':
        return False, '판정 %s — card 여야 함' % (r.get('common') or {}).get('level')
    if 'FIT-2004' not in (r.get('conclusion') or ''):
        return False, '반례(FIT-2004)가 결론에 없음'
    titles = ' '.join(e.get('title', '') for e in r.get('code_evidence') or [])
    if 'Supply voltage missing' not in titles:
        return False, '11H 코드 근거가 없음'
    if len(r.get('steps') or []) < 5:
        return False, '조사 단계 %d — 5단계 이상이어야 함' % len(r.get('steps') or [])
    return True, 'card 판정·반례 명시·코드 근거·%d단계 기록' % len(r['steps'])


def c_flood_reverse():
    """알람 폭주 역추적이 계층을 올바르게 가르는가."""
    from retrieval.panel_index import PanelIndex
    p = PanelIndex()
    sib = p.siblings("AIT-4002")
    if not sib or not sib.get("siblings"):
        return False, "AIT-4002 동반 태그 조회 실패"
    full = [sib["tag"]] + sib["siblings"]
    r1 = p.common_cause_of(full)
    if r1.get("level") != "card":
        return False, "카드 전체인데 판정 %s" % r1.get("level")
    r2 = p.common_cause_of(full[:3])
    if r2.get("level") != "card" or not r2.get("uncovered"):
        return False, "부분 알람에서 미알람 반례가 비어 있음"
    r3 = p.common_cause_of([full[0], "XX-9999"])
    if r3.get("unknown") != ["XX-9999"]:
        return False, "미등재 태그가 조용히 사라짐"
    return True, "card 판정·미알람 반례·미등재 분리 확인"


def c_diversify_off():
    """측정에서 기각된 설정이 켜져 있지 않은가."""
    if config.DIVERSIFY != "off":
        return False, ("COPILOT_DIVERSIFY=%s — 측정 결과 off(33/45)보다 "
                       "낮습니다(kind 29, all 27)" % config.DIVERSIFY)
    return True, "off"


# ── 2. 임베딩 캐시 신원 ─────────────────────────────────────
def c_cache_identity():
    """다른 모델로 구운 캐시를 재사용하지 않는가 (고장 주입)."""
    import json
    if not os.path.isfile(config.EMBED_META):
        return False, "캐시 없음"
    meta = json.load(open(config.EMBED_META, encoding="utf-8"))
    if meta.get("signature") != config.embed_signature():
        return False, "서명 불일치: %s ≠ %s" % (meta.get("signature"),
                                            config.embed_signature())

    # 주입: 서명을 바꾼 척하고 load() 가 거부하는지 본다
    from ingest.build_index import load as load_index
    from retrieval.dense import DenseIndex
    real = config.EMBED_MODEL
    try:
        config.EMBED_MODEL = real + "-FAKE"
        di = DenseIndex(load_index())
        if di.load(verbose=False) is not None:
            return False, "다른 모델 서명인데 캐시를 재사용함 — 검출 실패"
    finally:
        config.EMBED_MODEL = real
    return True, "서명 대조 정상 (%s)" % meta.get("signature")


# ── 3. 조치 생성 ────────────────────────────────────────────
def c_advisor_reachable():
    from graph.advisor import available
    return available()


def c_advisor_rejects_fake():
    """없는 근거를 인용하면 버리는가 (고장 주입)."""
    from graph import advisor
    ev = [{"id": "M9E-401", "title": "Acid container",
           "text": "volume of acid is less than 10%", "cite": "a.pdf p.400"}]
    orig = config.LLM_PROVIDER
    try:
        config.LLM_PROVIDER = "_selfcheck"
        advisor._CHAT["_selfcheck"] = lambda m, t: (
            '{"summary":"x","steps":[{"title":"A","detail":"B",'
            '"evidence":["M9E-9999"]},{"title":"C","detail":"D",'
            '"evidence":[99]}]}')
        try:
            advisor.generate("AIT-4002", "산 잔량 부족", ev)
            return False, "없는 근거를 인용했는데 통과함 — 환각 차단 실패"
        except advisor.AdvisorError:
            pass
        # 정상 인용은 통과해야 한다
        advisor._CHAT["_selfcheck"] = lambda m, t: (
            '{"summary":"x","steps":[{"title":"A","detail":"B",'
            '"evidence":[1]}]}')
        r = advisor.generate("AIT-4002", "산 잔량 부족", ev)
        if r["steps"][0]["evidence_ids"] != ["M9E-401"]:
            return False, "정상 인용이 잘못 되돌려짐"
    finally:
        config.LLM_PROVIDER = orig
        advisor._CHAT.pop("_selfcheck", None)
    return True, "가짜 근거 차단 / 번호 인용 복원 정상"


def c_advisor_real():
    """실제 모델로 조치가 생성되는가."""
    from graph.advisor import generate
    from graph.app_graph import Copilot2
    o = Copilot2(mode="hybrid").answer(
        tag="AIT-4002", alarm="산 잔량이 부족하다고 뜹니다")
    if o["decision"] != "advise":
        return False, "판정 %s — 조치 생성 단계에 도달하지 못함" % o["decision"]
    r = generate("AIT-4002", "산 잔량이 부족하다고 뜹니다", o["evidence"])
    if r["dropped"]:
        return False, "%d개 단계가 근거 검증에서 버려짐" % r["dropped"]
    return True, "%d단계 — %s" % (len(r["steps"]), r["steps"][0]["title"])


# ── 4. 챗봇 ─────────────────────────────────────────────────
def c_chat_gateway():
    """챗봇과 조치 생성이 같은 제공자 설정을 쓰는가."""
    from graph.advisor import _CHAT
    if config.LLM_PROVIDER == "off":
        return True, "off — 규칙 엔진만 사용 (의도된 구성)"
    if config.LLM_PROVIDER not in _CHAT:
        return False, ("COPILOT_PROVIDER=%s 를 대화 게이트웨이가 모릅니다"
                       % config.LLM_PROVIDER)
    return True, "%s — 조치 생성과 동일 경로" % config.LLM_PROVIDER


def c_chat_rule():
    """모델이 없어도 규칙 엔진이 명령을 알아듣는가."""
    from api.server import rule_intent
    cases = [("AIT-4002 산 잔량 알람 조회해줘", "diagnose", "AIT-4002"),
             ("XV-4101 인터락 조회", "interlock", "XV-4101")]
    bad = []
    for t, want, tag in cases:
        r = rule_intent(t) or {}
        if r.get("type") != want or r.get("tag") != tag:
            bad.append(t)
    if bad:
        return False, "인식 실패: %s" % " / ".join(bad)
    return True, "알람·인터락 명령 인식 정상"


def c_tag_notation():
    """현장 표기(공백·하이픈 없음)를 실제 태그로 되돌리는가."""
    from api.server import normalize_tag, rule_intent
    for raw, want in (("LCV 01", "LCV-01"), ("lcv01", "LCV-01"),
                      ("XV 4101", "XV-4101"), ("AIT 4002", "AIT-4002")):
        if normalize_tag(raw) != want:
            return False, "%s -> %s (기대 %s)" % (raw, normalize_tag(raw), want)
    # 없는 태그를 지어내지 않는가
    if normalize_tag("ZZZ-99") is not None:
        return False, "존재하지 않는 태그를 통과시킴"
    r = rule_intent("LCV 01 인터락 보여줘")
    if r.get("type") != "interlock" or r.get("tag") != "LCV-01":
        return False, "'LCV 01 인터락 보여줘' -> %s / %s" % (r.get("type"),
                                                          r.get("tag"))
    if (rule_intent("ZZZ-99 인터락 조회") or {}).get("type") != "chat":
        return False, "없는 태그로 조회를 시도함"
    return True, "공백·무하이픈 표기 복원 / 없는 태그 거절"


# ── 5. 인터락 ───────────────────────────────────────────────
def c_chat_dispatch():
    """
    LLM 이 엉뚱한 응답을 해도 화면이 실행되는가 (고장 주입).

    7B 급 모델은 이 작업에서 규칙보다 못하다. "LCV-01 인터락 조회해줘"
    에 type=chat 과 친절한 문구만 돌려주면 화면은 아무것도 하지 않고,
    사용자는 왜 안 되는지 알 수 없다. 규칙이 우선인지 확인한다.
    """
    from graph import advisor
    from api.server import chat_help, ChatRequest
    orig = config.LLM_PROVIDER
    try:
        config.LLM_PROVIDER = "_selfcheck"
        advisor._CHAT["_selfcheck"] = lambda m, t: (
            '{"type":"chat","reply":"확인하겠습니다."}')
        cases = [("LCV-01 인터락 조회해줘", "interlock", "LCV-01"),
                 ("LCV 01 인터락 보여줘", "interlock", "LCV-01"),
                 ("AIT-4002 산 잔량 알람 조회해줘", "diagnose", "AIT-4002"),
                 ("사용법", "help", None)]
        for msg, want, tag in cases:
            r = chat_help(ChatRequest(message=msg, tab="alarm", use_llm=True))
            if r.get("type") != want or (tag and r.get("tag") != tag):
                return False, "'%s' -> %s / %s (기대 %s / %s)" % (
                    msg, r.get("type"), r.get("tag"), want, tag)
        # 없는 태그는 여전히 실행하지 않아야 한다
        r = chat_help(ChatRequest(message="ZZZ-99 인터락 조회", tab="alarm",
                                  use_llm=True))
        if r.get("type") != "chat":
            return False, "없는 태그로 조회를 시도함"

        # 반대 방향도 본다. 규칙이 못 알아들은 질문은 LLM 답이
        # 살아 있어야 한다 — 규칙의 예시 문구로 덮어쓰면 "어떤 기능이
        # 있니" 에 예시만 반복하게 된다.
        advisor._CHAT["_selfcheck"] = lambda m, t: (
            '{"type":"chat","reply":"__LLM_ANSWER__"}')
        # QA 경로를 끄고 일반 대화만 본다 — 여기서 보려는 것은
        # "규칙의 예시 문구가 LLM 답을 덮지 않는가" 이지 QA 품질이 아니다.
        #
        # 탐침을 "안녕하세요" 에서 바꿨다. 인사는 이제 규칙이 직접
        # 응대하므로(c_smalltalk 참조) 포괄 응답 경로를 지나지 않는다.
        # 규칙에 걸리지 않는 잡담이어야 이 항목이 원래 보려던 것을 본다.
        qa_on = config.CHAT_QA
        try:
            config.CHAT_QA = False
            r = chat_help(ChatRequest(message="그냥 해본 말이야",
                                      tab="alarm", use_llm=True))
            if r.get("reply") != "__LLM_ANSWER__":
                return False, "규칙 예시 문구가 LLM 답변을 덮어씀"
        finally:
            config.CHAT_QA = qa_on
    finally:
        config.LLM_PROVIDER = orig
        advisor._CHAT.pop("_selfcheck", None)
    return True, "규칙 우선 실행 / 대화 질문은 LLM 답 유지"


def c_chat_qa():
    """챗봇 질의응답이 근거 없는 답을 만들지 않는가 (고장 주입)."""
    from graph import advisor, qa
    orig = config.LLM_PROVIDER
    ev = [{"id": "M9E-401", "title": "Acid container",
           "text": "volume of acid is less than 10%", "cite": "m9.pdf p.400"}]

    class Advise:
        def answer(self, **k):
            return {"decision": "advise", "grade": 0.7, "evidence": ev}

    class Abstain:
        def answer(self, **k):
            return {"decision": "abstain", "grade": 0.2, "evidence": [],
                    "grade_reason": "근거 없음"}

    try:
        config.LLM_PROVIDER = "_selfcheck"
        # 없는 근거를 인용한 문장이 섞인 응답
        advisor._CHAT["_selfcheck"] = lambda m, t: (
            '{"answer":"잔량이 10% 미만이면 경보가 뜹니다 [1]. '
            '펌프를 분해하십시오 [9].","used":[1]}')
        r = qa.answer("산 잔량 경보는 언제 뜨나요?", copilot=Advise())
        if not r["ok"] or r.get("dropped", 0) < 1:
            return False, "없는 근거 인용을 버리지 못함"
        if "분해" in r["reply"]:
            return False, "지어낸 문장이 답변에 남음"
        # 근거가 없으면 답을 만들지 않아야 한다
        r2 = qa.answer("커피 냄새가 나요", copilot=Abstain())
        if r2["ok"]:
            return False, "근거가 없는데 답변을 생성함"
    finally:
        config.LLM_PROVIDER = orig
        advisor._CHAT.pop("_selfcheck", None)
    return True, "인용 검증 / 근거 없을 때 거절"


def c_chat_followup():
    """화면 결과를 근거로 후속 질문에 답하는가."""
    from graph import advisor
    from api.server import chat_help, ChatRequest, ChatContext, rule_intent
    # 후속 질문이 명령으로 오인되지 않아야 한다
    for msg in ("조회된 내용을 보고 조치방법을 알려줘", "조치방법 알려줘",
                "방금 결과 설명해줘"):
        if (rule_intent(msg, "AIT-1001") or {}).get("type") != "followup":
            return False, "'%s' 가 명령으로 오인됨" % msg
    # 결과가 없으면 먼저 조회하라고 안내해야 한다
    r = chat_help(ChatRequest(message="조치방법 알려줘", tag="AIT-1001",
                              use_llm=True))
    if "조회" not in (r.get("reply") or ""):
        return False, "조회 결과가 없는데 안내하지 않음"

    orig = config.LLM_PROVIDER
    try:
        config.LLM_PROVIDER = "_selfcheck"
        advisor._CHAT["_selfcheck"] = lambda m, t: (
            '{"summary":"확인 순서","steps":[{"title":"산 용기 잔량 확인",'
            '"detail":"10% 미만이면 주문하십시오.","evidence":[1]}]}')
        ev = [{"id": "M9E-401", "title": "Acid container",
               "text": "volume of acid is less than 10%",
               "cite": "m9.pdf p.400"}]
        ctx = ChatContext(tag="AIT-1001", alarm="acid low",
                          decision="advise", grade=0.71, evidence=ev)
        r = chat_help(ChatRequest(message="조회된 내용을 보고 조치방법을 알려줘",
                                  tag="AIT-1001", context=ctx, use_llm=True))
        if r.get("engine") != "advice" or "산 용기" not in (r.get("reply") or ""):
            return False, "화면 결과로 조치를 만들지 못함: %s" % r.get("engine")
    finally:
        config.LLM_PROVIDER = orig
        advisor._CHAT.pop("_selfcheck", None)
    return True, "후속 질문을 화면 근거로 처리"


def c_interlock_eval():
    """인터락 72문항이 통과하는가."""
    import json
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "eval_set_interlock.json")
    if not os.path.isfile(p):
        return False, "평가셋 없음 — python -m eval.make_eval_interlock"
    from eval.run_eval_interlock import check
    from retrieval.interlock_index import InterlockIndex
    ix = InterlockIndex()
    qs = json.load(open(p, encoding="utf-8"))["questions"]
    bad = [q["id"] for q in qs if not check(ix, q)[0]]
    if bad:
        return False, "%d문항 실패: %s" % (len(bad), ",".join(bad[:6]))
    return True, "%d/%d" % (len(qs), len(qs))


# ── 5-2. 판넬 ───────────────────────────────────────────────
def c_panel_eval():
    """판넬 평가셋이 통과하는가."""
    import json
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "eval_set_panel.json")
    if not os.path.isfile(p):
        return False, "평가셋 없음 — python -m eval.make_eval_panel"
    from eval.run_eval_panel import check
    from retrieval.panel_index import PanelIndex
    ix = PanelIndex()
    qs = json.load(open(p, encoding="utf-8"))["questions"]
    bad = [q["id"] for q in qs if not check(ix, q)[0]]
    if bad:
        return False, "%d문항 실패: %s" % (len(bad), ",".join(bad[:6]))
    return True, "%d/%d" % (len(qs), len(qs))


def c_card_scope():
    """
    [주입] 카드 단위 상실 계산이 실제로 카드를 구분하고 있는가.

    이중화 구성에서 단일 고장 지점은 카드다. 슬롯 구분이 사라지면
    카드 조회는 '판넬 전체'와 같아지는데, 화면은 여전히 카드라고
    표시한다. 그 상태를 검출한다.
    """
    from retrieval.panel_index import PanelIndex
    ix = PanelIndex()
    cards = ix.cards()
    if len(cards) < 2:
        return False, "카드가 %d장뿐 — 슬롯 정보를 읽지 못했을 수 있습니다" % len(cards)
    cid = cards[0]["card"]
    d = ix.impact(cid)
    panel_points = ix.by_panel(d["panel"])["points"]
    if d["points"] >= panel_points:
        return False, ("카드 상실(%d점)이 판넬 전체(%d점)와 같습니다 — "
                       "슬롯 구분이 동작하지 않습니다"
                       % (d["points"], panel_points))
    return True, "카드 %d장 / %s 는 %d점 (판넬 %d점 중)" % (
        len(cards), cid, d["points"], panel_points)


def c_card_channels_visible():
    """
    [주입] 카드 상실 화면이 잃는 점을 빠짐없이 보여주는가.

    화면에서 판넬 계기 목록을 없앴는데, 인터락 표에는 **조건에 걸린
    태그만** 나온다. 그래서 인터락에 안 걸린 계기가 어디에도 보이지
    않았다. 실제로 CUB-B/R1/S8 은 3점인데 인터락 조건에 걸린 것은
    1점뿐이라, 나머지 2점이 화면에서 사라졌다.

    impact 가 채널 전체를 싣는지, 그리고 인터락 의존 여부가 채널마다
    붙는지 확인한다.
    """
    from retrieval.panel_index import PanelIndex
    ix = PanelIndex()
    partial = None          # 일부 채널만 인터락에 걸린 카드
    for c in ix.cards():
        d = ix.impact(c["card"])
        if not d or not d.get("interlock_loaded"):
            continue
        chs = d.get("channels") or []
        if len(chs) != d["points"]:
            return False, ("%s: 채널 %d개 ≠ 잃는 점 %d — 화면에서 일부 계기가 "
                           "보이지 않습니다" % (c["card"], len(chs), d["points"]))
        hit = [x for x in chs if x.get("interlocks")]
        if hit and len(hit) < len(chs):
            partial = (c["card"], len(chs), len(hit))
    if partial is None:
        return True, "채널 수 일치 (일부만 인터락에 걸린 카드는 없음)"
    card, n, k = partial
    return True, "%s 등: 채널 %d개 전부 노출 (인터락 관련 %d개)" % (card, n, k)


def c_common_cause():
    """
    [주입] 공통원인 점검이 실제로 무언가를 붙잡는가.

    지적 0건은 '설계가 안전하다'가 아니라 '이 리스트에서 걸린 것이
    없다'는 뜻이다. 조건 태그 두 개를 같은 카드로 옮겨 잡히는지 본다.
    """
    from retrieval.panel_index import PanelIndex
    ix = PanelIndex()
    base = ix.common_cause()
    if not base["loaded"]:
        return False, "인터락 리스트 미적재"
    # 조건 태그가 2개 이상인 인터락 하나를 골라 같은 카드로 몰아 본다
    target = None
    for it in ix._interlock().items:
        cond = set()
        for c in it["conditions"]:
            cond.update(c["tags"])
        known = [t for t in cond if t in ix._by_tag]
        if len(known) >= 2:
            target = (it["il_no"], known[:2])
            break
    if not target:
        return True, ("조건 태그가 2개 이상인 인터락이 없어 시험 건너뜀 — "
                      "실물 인터락 리스트는 행마다 조건이 하나(OR)입니다")
    il_no, (a, b) = target
    # 카드 식별에 PN(DP)(스테이션)까지 들어가므로 그 값도 함께 옮겨야
    # 실제로 같은 카드가 된다. 배선 열을 하나라도 빼면 주입이 성립하지
    # 않는데, 검사는 통과한 것처럼 보인다.
    wiring = ("PANEL", "PN(DP)", "RACK", "SLOT")
    src, dst = ix._by_tag[a], ix._by_tag[b]
    saved = {k: dst.get(k) for k in wiring}
    for k in wiring:
        dst[k] = src.get(k)
    got = [f["il_no"] for f in ix.common_cause()["findings"]]
    dst.update(saved)
    if il_no not in got:
        return False, "%s 의 조건을 같은 카드로 몰았는데 잡지 못함" % il_no
    return True, "기준 지적 %d건 / 주입 시 %s 검출" % (
        len(base["findings"]), il_no)


def c_no_panel_impact():
    """
    판넬 단위 '상실' 계산이 되살아나지 않았는가.

    이중화 구성에서는 랙 증설도 스위칭으로 대응하므로 판넬 전체가 죽는
    상황이 성립하지 않는다. 성립하지 않는 시나리오에 숫자를 붙여 보여주면
    현장 판단을 왜곡한다. 편의로 다시 넣기 쉬운 기능이라 잠가 둔다.
    """
    import inspect
    from retrieval.panel_index import PanelIndex
    from api.server import panel_detail
    sig = inspect.signature(PanelIndex.impact)
    if "scope" in sig.parameters:
        return False, "PanelIndex.impact 에 scope 인자가 되살아남"
    if "impact" in inspect.signature(panel_detail).parameters:
        return False, "/api/panel 에 impact 인자가 되살아남"
    ix = PanelIndex()
    if ix.impact(sorted(ix._by_panel)[0]) is not None:
        return False, "판넬명으로 상실 계산이 반환됨"
    return True, "카드 단위만 계산 / 판넬은 구성·위치 조회 전용"


def c_data_dir_clean():
    """
    [주입] data/ 에 업로드 자료 말고 다른 것이 섞이지 않았는가.

    data/ 는 **사용자가 넣는 아홉 가지만** 두는 자리다. 생성물이 같이
    있으면 "무엇을 넣어야 하나" 에 한 줄로 답할 수 없고, 실제로 생성물을
    원본으로 착각해 엑셀에서 손으로 고쳤다가 재생성에서 잃을 뻔했다.
    임시 파일(엑셀을 열어 둔 채 생성기를 돌리면 생긴다)도 여기서 걸린다.
    """
    allowed_files = {"INSTRUMENT_LIST.xlsx", "IO_LIST.xlsx", "TB_LIST.xlsx"}
    # 계기 리스트는 계기 종류별로 여러 통으로 들어오는 것이 실물이다
    # (Flow Transmitter · Level Switch · Pressure Gauge …).
    allowed_re = re.compile(r"instrument\s*list.*\.xlsx?$", re.I)
    allowed_dirs = {"manuals", "drawings", "interlock"}
    generated = {"PANEL_LOCATIONS.csv", "TAG_ATTRIBUTES.xlsx  (폐지)",
                 "drawings_index.csv", "error_codes.json",
                 "maintenance_history.json", "maintenance_history.xlsx"}
    if not os.path.isdir(config.DATA_DIR):
        return False, "data/ 가 없습니다: %s" % config.DATA_DIR
    stray = []
    for name in sorted(os.listdir(config.DATA_DIR)):
        full = os.path.join(config.DATA_DIR, name)
        if os.path.isdir(full):
            if name not in allowed_dirs and name != "__pycache__":
                stray.append(name + "/")
            continue
        if name in allowed_files or allowed_re.search(name):
            continue
        if name in generated:
            stray.append("%s (생성물 — derived/ 로)" % name)
        elif name.startswith("~$") or "." not in name:
            stray.append("%s (임시 파일 — 엑셀을 닫고 생성기를 다시 실행)"
                         % name)
        else:
            stray.append(name)
    if stray:
        return False, "data/ 에 업로드 자료가 아닌 것: " + ", ".join(stray)
    n_man = len([f for f in os.listdir(config.MANUAL_DIR)
                 if f.lower().endswith(".pdf")]) \
        if os.path.isdir(config.MANUAL_DIR) else 0
    n_dwg = len([f for f in os.listdir(config.DRAWING_DIR)
                 if f.lower().endswith(".pdf")]) \
        if os.path.isdir(config.DRAWING_DIR) else 0
    return True, "업로드 자료만 (매뉴얼 %d · 도면 %d)" % (n_man, n_dwg)


def c_io_list_standard():
    """
    [주입] 표준 IO List 가 원천과 어긋나지 않는가.

    IO_LIST.xlsx 는 생성물이다. 원천(v1 계기 리스트·출력 리스트)이 바뀌면
    다시 만들어야 하는데, 안 만들면 조회는 옛 IO List 를, 사람은 새 원천을
    보게 된다. 둘 다 그럴듯해서 어긋났다는 사실이 드러나지 않는다.
    PROVENANCE 시트에 찍힌 원천 행수와 실제 원천을 대조한다.
    """
    if not os.path.isfile(config.IO_LIST):
        return True, "표준 IO List 미사용 (v1 원본으로 동작 중)"
    try:
        import openpyxl
    except ImportError:
        return False, "openpyxl 없음"
    wb = openpyxl.load_workbook(config.IO_LIST, read_only=True, data_only=True)
    if "PROVENANCE" not in wb.sheetnames:
        return True, ("PROVENANCE 시트가 없습니다 — 생성기가 아니라 사용자가 "
                      "직접 넣은 IO List 로 보고 원천 대조는 건너뜁니다")
    stamp = {}
    for r in wb["PROVENANCE"].iter_rows(values_only=True):
        if r and r[0]:
            stamp[str(r[0]).strip()] = r[1]

    def count(path):
        ws = openpyxl.load_workbook(path, read_only=True,
                                    data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        hi = next(i for i, x in enumerate(rows)
                  if x and "TAG" in [str(c).strip().upper() if c else ""
                                     for c in x])
        ti = [str(c).strip().upper() if c else ""
              for c in rows[hi]].index("TAG")
        return sum(1 for x in rows[hi + 1:] if x and x[ti])

    src_in = os.path.join(config.SOURCE_DIR, "DEMO_INSTRUMENT_LIST.xlsx")
    if not os.path.isfile(src_in):
        return True, "원천 파일이 없어 대조를 건너뜁니다"
    actual = count(src_in)
    src_out = os.path.join(config.SOURCE_DIR, "DEMO_OUTPUT_LIST.xlsx")
    if os.path.isfile(src_out):
        actual += count(src_out)
    try:
        filed = int(stamp.get("SOURCE ROWS",
                              stamp.get("SOURCE INPUT ROWS", -1)))
    except (TypeError, ValueError):
        filed = -1
    if filed != actual:
        return False, ("원천 %d행 ≠ IO List 기록 %s행 — python "
                       "tools/make_io_list.py 를 다시 실행하십시오"
                       % (actual, filed))
    # 계기 리스트도 같은 원천에서 나왔는지
    spec = getattr(config, "INSTRUMENT_SPEC", "")
    if spec and os.path.isfile(spec):
        from ingest.lists import read_instrument_rows
        n = len(read_instrument_rows(spec))
        if n != actual:
            return False, ("계기 리스트 %d행 ≠ IO List %d행 — 두 문서가 "
                           "다른 시점의 원천에서 나왔습니다" % (n, actual))
    else:
        return False, ("INSTRUMENT_LIST.xlsx 가 없습니다 — 제조사·고장모드·"
                       "매뉴얼 연결이 통째로 빕니다")
    return True, "IO List·계기 리스트 %d행 원천 일치" % actual


def c_io_list_header():
    """
    [주입] IO List 헤더가 mastertool/MAXIS 표준 24종과 정확히 같은가.

    표기가 한 글자만 달라도 완전일치 매핑에서 조용히 빗나간다. 실제로
    5번 열은 PN(DP) 인데 구 표기 DP(PN) 이 문서에 남아 있다. MAXIS 는
    별칭으로 받아주지만 표준 매핑은 어긋난다.

    표준 정의는 io_tools_core.py 한 곳에 있고 여기서는 그 목록을 그대로
    복사해 대조만 한다.
    """
    if not os.path.isfile(config.IO_LIST):
        return True, "표준 IO List 미사용 (v1 원본으로 동작 중)"
    try:
        import openpyxl
    except ImportError:
        return False, "openpyxl 없음"
    from tools.make_io_list import STANDARD_ORDER
    wb = openpyxl.load_workbook(config.IO_LIST, read_only=True,
                                data_only=True)
    try:
        rows = list(wb.active.iter_rows(values_only=True))
    finally:
        wb.close()
    hi = next((i for i, r in enumerate(rows)
               if r and "TAG" in [str(c).strip() if c else "" for c in r]), None)
    if hi is None:
        return False, "헤더 행을 찾지 못했습니다"
    hdr = [str(c).strip() if c else "" for c in rows[hi]]
    got = [h for h in hdr if h]
    front = got[:len(STANDARD_ORDER)]
    if front != STANDARD_ORDER:
        for i, (a, b) in enumerate(zip(front + [""] * 30, STANDARD_ORDER)):
            if a != b:
                return False, ("%d번 열이 표준과 다릅니다: '%s' ≠ '%s' — "
                               "완전일치 매핑에서 빗나갑니다" % (i + 1, a, b))
        return False, "표준 24종 열 수가 맞지 않습니다 (%d개)" % len(front)
    ext = got[len(STANDARD_ORDER):]
    if ext:
        return False, ("IO List 에 표준 밖의 열이 있습니다: %s — 계기 사양은 "
                       "INSTRUMENT_LIST.xlsx 에 두십시오"
                       % ", ".join(ext[:5]))
    return True, "표준 24종만 (확장 열 없음)"


def c_tag_cross_consistency():
    """
    [주입] 세 문서의 태그 교차 대조가 실제로 어긋남을 잡는가.

    IO List·계기 리스트·인터락 리스트는 TAG 로 서로를 가리킨다. 한쪽만
    고치면 조회가 조용히 빈다. 이 항목은 **지적 건수를 판정하지 않는다** —
    지금 데모 데이터에는 실제로 어긋남이 있고 그건 데이터의 문제다.
    여기서 보는 것은 대조기가 살아 있는지다.

    태그 하나의 표기를 바꿔 넣고 '표기 불일치' 로 잡히는지 확인한다.
    """
    from ingest import tag_registry as TR
    base = TR.cross_check()
    base_t = TR.collect()
    if base["counts"]["io"] == 0:
        return False, "IO List 태그를 하나도 읽지 못했습니다"
    if base["counts"]["spec"] == 0:
        return False, "계기 리스트 태그를 하나도 읽지 못했습니다"

    # 주입 대상은 **IO List 와 계기 리스트 양쪽에 있는** 태그여야 한다.
    # 첫 태그를 그냥 집으면 실물에서는 판넬 상태 접점(FAB_CPU_XA_0001)이
    # 걸리는데, 이것은 계기 리스트에 없으므로 바꿔치기해도 대조에 걸릴
    # 것이 없어 시험이 거짓 실패한다.
    spec_tags = set(base_t["spec"]) if base_t else set()
    real = None
    for r in TR.read_rows(config.IO_LIST):
        t0 = str(r.get("TAG") or "").strip()
        if t0 and t0 in spec_tags:
            real = t0
            break
    if not real:
        return True, ("IO List 와 계기 리스트에 함께 있는 태그가 없어 "
                      "주입 시험은 건너뜁니다 — 현재 지적 %d건"
                      % base["total"])

    saved = TR.collect
    mangled = real.replace("-", "").lower()

    def fake():
        t = saved()
        t["spec"] = [mangled if x == real else x for x in t["spec"]]
        return t

    TR.collect = fake
    try:
        got = TR.cross_check()
    finally:
        TR.collect = saved

    hits = [f for f in got["findings"].get("표기 불일치", [])
            if f["tag"] in (real, mangled)]
    if not hits:
        return False, ("'%s' 를 '%s' 로 바꿨는데 표기 불일치로 잡지 "
                       "못했습니다" % (real, mangled))
    return True, ("IO %d · 계기 %d · 인터락 조건 %d / 현재 지적 %d건, "
                  "주입 검출 정상"
                  % (base["counts"]["io"], base["counts"]["spec"],
                     base["counts"]["interlock_input"], base["total"]))


def c_instrument_form():
    """
    [주입] 계기 리스트가 실물 양식(2단 머리)인가.

    한때 이 문서를 제가 임의로 만든 18열 평면 양식으로 두었다. 실물은
    TAG NO. · DESCRIPTION · Q'TY · SENSOR TYPE · MATERIAL(ELEMENT/BODY) ·
    SCALE RANGE(MIN/MAX/UNIT) … 형태의 2단 머리이고, **배선(랙·슬롯·
    채널)은 들어가지 않는다** — IO List 에서 받아간다.

    모양이 다르면 실물을 그대로 갈아 끼울 수 없다.
    """
    spec = getattr(config, "INSTRUMENT_SPEC", "")
    if not spec or not os.path.isfile(spec):
        return False, "INSTRUMENT_LIST.xlsx 가 없습니다"
    from tools.make_io_list import INSTRUMENT_HEAD
    from ingest.lists import read_instrument_rows
    import openpyxl
    ws = openpyxl.load_workbook(spec, read_only=True, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    hi = next((i for i, r in enumerate(rows)
               if r and any(str(c).strip().upper() == "TAG NO."
                            for c in r if c)), None)
    if hi is None:
        return False, "TAG NO. 머리 행을 찾지 못했습니다 — 실물 양식이 아닙니다"

    # 실물 머리 항목은 두 줄로 나뉘어 있다('SENSOR\nTYPE'). 눈으로는 같고
    # 문자열로는 다르므로, 비교 전에 공백을 하나로 접는다.
    groups = [re.sub(r"\s+", " ", str(c).strip()) for c in rows[hi] if c]
    want = [g for g, _sub in INSTRUMENT_HEAD]
    # 실물이 표준보다 열을 더 갖고 있는 것은 문제가 아니다 — 실제 문서에는
    # 뒤에 P&ID 열이 하나 더 붙어 있다. 표준 항목이 **앞에서부터 순서대로
    # 전부 있는지**만 본다. 모자라거나 순서가 어긋나면 갈아 끼울 수 없다.
    if groups[:len(want)] != want:
        for a, b in zip(groups + [""] * 30, want):
            if a != b:
                return False, "머리 항목이 다릅니다: '%s' ≠ '%s'" % (a, b)
        return False, "머리 항목 수가 모자랍니다 (%d개)" % len(groups)
    extra = groups[len(want):]

    # 배선 열이 섞여 들어오지 않았는지
    flat = {str(c).strip().upper() for c in rows[hi] if c}
    flat |= {str(c).strip().upper()
             for c in (rows[hi + 1] if hi + 1 < len(rows) else []) if c}
    wired = flat & {"RACK", "SLOT", "CH", "PANEL", "PN(DP)", "ADD"}
    if wired:
        return False, ("계기 리스트에 배선 열이 있습니다: %s — IO List 에서 "
                       "받아가야 합니다" % ", ".join(sorted(wired)))

    n = len(read_instrument_rows(spec))
    if n == 0:
        return False, "행을 하나도 읽지 못했습니다 (2단 머리 해석 실패)"
    tail = (" · 추가 열 %s" % ", ".join(extra)) if extra else ""
    return True, ("실물 양식 %d항목 / %d행, 배선 열 없음%s"
                  % (len(want), n, tail))


def c_pid_rule_mapping():
    """[주입] IO 심볼명 → P&ID 태그 규칙 매핑이 호기를 구별하는가.

    두 문서는 이름 공간이 다르다(IO: DWP_LS_P5401A_H, 계기: LS-P5401A/B).
    유사도로만 잇던 때는 호기를 못 가려 UPWT_LS_P3601C 가 LS-P3601A 에
    붙었다. C호기를 물었는데 A호기 사양이 나오고, 화면에는 그럴듯하게
    보이므로 사람이 알아채지 못한다. 여기서는 두 가지를 본다.
      · 규칙으로 이어진 건이 실제로 있는가
      · 호기 문자가 붙은 IO 태그는 같은 호기의 계기에 붙었는가
    """
    from ingest.lists import load_points, structural_pid_candidates
    pts = load_points(config.IO_LIST,
                      getattr(config, "INSTRUMENT_SPECS", None)
                      or getattr(config, "INSTRUMENT_SPEC", None))
    ruled = [(t, r) for t, r in pts.items() if r.get("_pid_src") == "rule"]
    if not ruled:
        # 자료에 따라 규칙 매핑이 애초에 필요 없다. IO List 와 계기 리스트가
        # 같은 태그 체계를 쓰면(AIT-1001 ↔ AIT-1001) 그냥 이름으로 조인된다.
        # 규칙은 두 이름 공간이 다를 때(DWP_LS_P5401A_H ↔ LS-P5401A/B) 쓰인다.
        direct = sum(1 for _t, r in pts.items()
                     if str(r.get("MODEL") or "").strip()
                     and r.get("_pid_src") in (None, "", "fallback_io"))
        if direct:
            return True, ("IO 태그와 계기 태그가 같은 체계라 규칙 매핑이 "
                          "필요 없습니다 — 이름으로 직접 조인 %d건" % direct)
        return False, ("규칙으로 이어진 태그가 하나도 없습니다 — "
                       "IO 심볼명과 계기 태그가 유사도에만 의존합니다")

    bad = []
    for t, r in ruled:
        cands = structural_pid_candidates(t)
        if not cands:
            bad.append("%s: 후보를 다시 만들지 못함" % t)
            continue
        want = cands[0].upper()
        got = str(r.get("P&ID TAG") or "").upper()
        if got != want:
            bad.append("%s: %s ≠ %s" % (t, got, want))
    if bad:
        return False, "호기 불일치 %d건 — %s" % (len(bad), bad[0])

    # 붙은 사양이 실제로 그 계기의 것인지 (원문 줄과 대조)
    joined = sum(1 for _t, r in ruled if str(r.get("MODEL") or "").strip())
    return True, ("규칙 %d건 · 호기 일치 · 사양 연결 %d건"
                  % (len(ruled), joined))


def c_advice_path_runs():
    """[주입] 조치 생성 경로가 LLM 없이도 끝까지 도는가.

    LLM 연결과는 별개로, 그래프가 예외 없이 완주하는지만 본다.
    device_of 가 기기 키를 여러 개 돌려주도록 바뀌었을 때 retrieve 단계가
    집합 판정에서 터졌고, 화면에는 예외 문자열 한 줄만 뜬 채 조치 생성이
    통째로 멈췄다 — LLM 이 꺼져 있어도 여기까지는 반드시 돌아야 한다.
    """
    from graph.app_graph import Copilot2
    from ingest.lists import load_points
    pts = load_points(config.IO_LIST,
                      getattr(config, "INSTRUMENT_SPECS", None)
                      or getattr(config, "INSTRUMENT_SPEC", None))
    tags = [t for t, r in pts.items() if r.get("MODEL")][:3] or list(pts)[:3]
    if not tags:
        return False, "IO 점을 읽지 못했습니다"
    prev = config.LLM_PROVIDER
    try:
        config.LLM_PROVIDER = "off"
        c = Copilot2(mode="lexical")
        for t in tags:
            out = c.answer(tag=t, alarm="alarm")
            if not isinstance(out, dict) or "decision" not in out:
                return False, "%s: 응답 형태가 아닙니다" % t
    except Exception as e:                                  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)
    finally:
        config.LLM_PROVIDER = prev
    return True, "태그 %d건 완주 (LLM 없이)" % len(tags)


# ── 6-3. 현장 이력 ──────────────────────────────────────────
def _probe_history():
    """
    이력 카드가 반드시 떠야 하는 질의 한 건을 이력 자료에서 고른다.

    태그와 증상을 코드에 박아 두면 자료를 바꿔 끼웠을 때 그 태그가
    사라지고, 검사는 '카드가 안 뜬다'가 아니라 '태그가 없다'로 실패한다.
    자료에서 뽑으면 어느 세트로 돌려도 같은 뜻의 검사가 된다.
    """
    import json
    path = getattr(config, "HISTORY", None)
    if not path or not os.path.isfile(path):
        return None, None
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    for r in rows:
        if r.get("tag") and r.get("symptom"):
            return r, rows
    return None, rows


def c_history_missing_file():
    """
    [주입] 이력 파일이 없어도 조치 생성이 계속되는가.

    이력은 있으면 좋은 자료지 필수 자료가 아니다. 자기 자료로 바꿔 끼운
    사람에게는 애초에 없는 것이 정상이다. 그런데 카드 삽입이 조치 배열을
    다시 쓰는 자리에 있어서, 이력 조회가 터지면 조치 화면이 통째로 빈다.

    파일을 치워 놓고 두 가지를 함께 본다.

      1) 없을 때  — 예외 없이 완주하고, 카드는 안 뜨고, 조치는 그대로 나온다
      2) 있을 때  — 같은 질의에 카드가 실제로 뜬다

    2를 같이 보지 않으면 이 검사는 아무것도 지키지 못한다. 이력 기능이
    통째로 죽어 있어도 '카드가 안 뜬다'는 항상 참이기 때문이다.
    """
    import api.server as S
    probe, _ = _probe_history()
    if not probe:
        return False, "이력 자료를 읽지 못했습니다: %s" % getattr(
            config, "HISTORY", "(경로 없음)")

    req = S.AdviceRequest(tag=probe["tag"], alarm=probe["symptom"],
                          mode="lexical", mock=True)
    prev_llm = config.LLM_PROVIDER
    orig_path, orig_cache = config.HISTORY, S._history
    try:
        config.LLM_PROVIDER = "off"

        # (2) 정상 상태 — 카드가 떠야 한다
        S._history = None
        ok_out = S.advice(req)
        if not ok_out.get("history_card"):
            return False, ("이력이 있는 태그(%s)인데도 카드가 뜨지 않습니다 — "
                           "이력 경로가 죽어 있으면 아래 부재 검사는 "
                           "무조건 통과합니다" % probe["tag"])

        # (1) 고장 주입 — 파일을 치운다
        config.HISTORY = os.path.join(
            os.path.dirname(orig_path) or ".", "__selfcheck_missing__.json")
        S._history = None
        try:
            out = S.advice(req)
        except Exception as e:                              # noqa: BLE001
            return False, ("이력 파일이 없다고 조치 생성이 터집니다 — %s: %s"
                           % (type(e).__name__, str(e)[:90]))
        if out.get("history_card") or out.get("history_matched"):
            return False, "이력 파일이 없는데 카드가 남아 있습니다 (캐시 잔존)"
        if not out.get("steps"):
            return False, "이력 파일이 없자 조치가 통째로 비었습니다"
        if any(s.get("kind") == "history" for s in out["steps"]):
            return False, "조치 배열에 이력 단계가 남아 있습니다"
    finally:
        config.LLM_PROVIDER = prev_llm
        config.HISTORY, S._history = orig_path, orig_cache

    return True, "있을 때 카드 표시 / 없을 때 %d단계로 완주" % len(out["steps"])


def c_history_wo_forged():
    """
    [주입] 이력 평가셋이 '몇 건 나왔나'가 아니라 '무엇이 나왔나'를 보는가.

    이력 문항은 카드에 특정 wo_no 가 들어 있는지로 채점한다. 그런데
    채점이 건수만 세고 있으면, 규칙이 엉뚱한 이력을 골라도 만점이 나온다.
    실제로 인터락 평가에서 같은 실수를 했었다 — 개수만 맞으면 통과라
    파서를 망가뜨려도 점수가 그대로였다.

    그래서 이력 하나의 wo_no 를 존재하지 않는 값으로 바꿔치기하고,
    **그 이력을 지목한 문항만** 무너지는지 본다. 아무 문항도 안 무너지면
    채점이 신원을 안 보는 것이고, 무관한 문항까지 무너지면 문항이 서로
    엉켜 있어 어느 규칙이 깨졌는지 가려낼 수 없다.
    """
    import json
    from collections import Counter
    from eval.make_eval_history import grade

    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "eval_set_history.json")
    if not os.path.isfile(p):
        return False, "평가셋 없음 — python -m eval.make_eval_history"
    _, hist = _probe_history()
    if not hist:
        return False, "이력 자료를 읽지 못했습니다"
    qs = json.load(open(p, encoding="utf-8"))
    if isinstance(qs, dict):
        qs = qs.get("questions", [])

    # 기준 채점부터 통과해야 한다. 여기서 이미 실패라면 평가셋이 자료와
    # 어긋난 것이고, 아래 위조 검사는 뜻을 잃는다.
    _, base_fails = grade(hist, qs)
    if base_fails:
        return False, ("기준 채점에서 %d문항 실패: %s — 평가셋을 다시 만드십시오"
                       % (len(base_fails),
                          ",".join(f[0] for f in base_fails[:5])))

    # 가장 많은 문항이 지목하는 이력을 고른다. 한 문항짜리를 고르면
    # 검사의 분해능이 1건뿐이라 우연히 통과하기 쉽다.
    # 합성 픽스처 문항은 제외한다. 이력 자료가 아니라 코드 안의 가짜
    # 레코드를 보므로, 자료를 위조해도 반응하지 않는다.
    real_qs = [q for q in qs
               if not (q.get("synthetic") or q.get("synthetic_device"))]
    cnt = Counter()
    for q in real_qs:
        for w in (q.get("expect_contains") or []) + (q.get("expect_first_in") or []):
            cnt[w] += 1
    if not cnt:
        return False, "wo_no 를 지목하는 문항이 없습니다 — 채점이 신원을 안 봅니다"
    target, _n = cnt.most_common(1)[0]
    expect_break = {q["id"] for q in real_qs
                    if target in ((q.get("expect_contains") or [])
                                  + (q.get("expect_first_in") or []))}

    forged = [dict(h, wo_no="WO-FORGED-0000") if h.get("wo_no") == target else h
              for h in hist]
    if forged == hist:
        return False, "위조 대상 %s 가 이력 자료에 없습니다" % target

    _, fails = grade(forged, qs)
    got = {f[0] for f in fails}
    if not got:
        return False, ("wo_no 를 %s 로 위조했는데 %d문항이 그대로 만점입니다 — "
                       "채점이 건수만 세고 있습니다" % (target, len(qs)))
    if not expect_break <= got:
        return False, ("%s 를 지목한 문항 %d개 중 %d개만 반응했습니다 — "
                       "채점이 일부 문항에서 신원을 안 봅니다"
                       % (target, len(expect_break), len(expect_break & got)))
    stray = got - expect_break
    if stray:
        return False, ("무관한 문항까지 무너졌습니다 (%s) — 문항이 서로 엉켜 "
                       "있어 원인을 가려낼 수 없습니다"
                       % ",".join(sorted(stray)[:4]))

    return True, "%d문항 통과 / %s 위조 시 지목 문항 %d개만 검출" % (
        len(qs), target, len(expect_break))


def c_guess_only_on_abstain():
    """
    [주입] 추측이 근거 있는 조회에 새지 않는가.

    근거를 못 찾았을 때 화면이 비는 것을 막으려고 모델 추측을 붙였다.
    이 기능의 위험은 하나다 — 근거 있는 답과 추측이 같은 화면에서 같은
    무게로 보이는 것. 그러면 "근거 없이 답하지 않는다" 는 전제가 무너진다.

    세 가지를 본다.

      1) advise 판정에는 추측이 붙지 않는다
      2) 추측은 조치 배열(steps)에 섞이지 않는다 — 별도 필드로만 나간다
      3) 4D 리포트에 추측이 실리지 않는다

    2·3 은 한 번 섞이면 되돌리기 어렵다. 조치로 저장된 추측은 다음
    조회에서 이력 근거가 되고, 리포트로 나간 추측은 결재를 탄다.
    """
    import api.server as S
    prev = config.LLM_PROVIDER
    try:
        config.LLM_PROVIDER = "off"     # 추측 생성 자체를 막고 경로만 본다
        tag = _first_tag_with_manual()
        if not tag:
            return False, "매뉴얼이 있는 태그를 찾지 못했습니다"

        out = S.advice(S.AdviceRequest(tag=tag, alarm="산 잔량 10% 미만 경고",
                                       mode="lexical", mock=True))
        if out.get("guess"):
            return False, "mock 조회인데 추측이 붙었습니다"
        if any((s.get("kind") == "guess") for s in out.get("steps", [])):
            return False, "추측이 조치 배열에 섞였습니다"

        # 자유 모드 — 추측이 모든 판정에 붙을 수 있게 되지만,
        # steps 분리는 모드와 무관하게 유지되어야 한다. 자유 모드가
        # 이 선을 넘으면 추측이 조치로 저장되어 다음 조회의 이력
        # 근거가 된다.
        out = S.advice(S.AdviceRequest(tag=tag, alarm="산 잔량 10% 미만 경고",
                                       mode="lexical", mock=True, free=True))
        if any((s.get("kind") == "guess") for s in out.get("steps", [])):
            return False, "자유 모드에서 추측이 조치 배열에 섞였습니다"

        rep = S.report_4d(S.ReportRequest(tag=tag, alarm="근거 없는 증상",
                                          mode="lexical"))
        body = rep.body if isinstance(rep.body, (bytes, bytearray)) else b""
        if b"model_only" in body or "모델 추측".encode("utf-8") in body:
            return False, "4D 리포트에 추측이 실렸습니다"
    except Exception as e:                                  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:90])
    finally:
        config.LLM_PROVIDER = prev
    return True, "advise 미부착 / 자유 모드 포함 조치 배열 분리 / 리포트 미포함"


def _first_tag_with_manual():
    """벤더 매뉴얼이 있는 계기 태그 하나."""
    from api.server import load_instruments
    for t, r in load_instruments().items():
        if str(r.get("MODEL") or "").strip():
            return t
    return None


def c_attr_source_real():
    """
    [주입] TYPE·FAIL POSITION 이 실물 문서에서 오는가.

    두 항목은 한때 내가 만든 부속 데이터에만 있었다. 실물 전환 시 채울
    곳이 없는 값이라, 데모에서는 그럴듯하게 보이고 실물에서는 통째로
    비는 유형이다. 출처를 확인했다.

        TYPE           계기 리스트 SENSOR TYPE
        FAIL POSITION  인터락 리스트 "* Valve Action : Fail Open"

    부속 데이터의 값은 그 문서에서 못 읽었을 때만 쓰는 대체값이므로,
    실물 문서 값이 이겨야 한다.
    """
    from ingest.lists import read_instrument_rows
    from ingest.interlock import load_interlocks
    from retrieval.interlock_index import load_outputs

    # TYPE — 계기 리스트에서 온 값이 그대로 실리는가
    spec = {str(r.get("TAG") or "").strip(): r
            for r in read_instrument_rows(getattr(config, "INSTRUMENT_SPECS", None) or getattr(config, "INSTRUMENT_SPEC", None))}
    outs = load_outputs()
    checked = 0
    for tag, r in spec.items():
        want = (r.get("MEAS TYPE") or "").strip()
        if not want or tag not in outs:
            continue
        got = (outs[tag].get("type") or "").strip()
        if got != want:
            return False, ("%s TYPE 이 계기 리스트와 다릅니다: '%s' ≠ '%s'"
                           % (tag, got, want))
        checked += 1
    if checked == 0:
        return False, "계기 리스트에서 SENSOR TYPE 을 하나도 읽지 못했습니다"

    # FAIL POSITION — 인터락 리스트에 적힌 값이 이기는가
    fails = {it["output_tag"]: it["fail"] for it in load_interlocks()
             if it.get("fail")}
    for tag, want in fails.items():
        got = (outs.get(tag) or {}).get("fail") or ""
        if got.strip().upper() != want.strip().upper():
            return False, ("%s FAIL POSITION 이 인터락 리스트와 다릅니다: "
                           "'%s' ≠ '%s'" % (tag, got, want))
    return True, "TYPE %d건 계기 리스트 / FAIL POSITION %d건 인터락 리스트" % (
        checked, len(fails))


def c_no_attr_file():
    """
    [주입] 부속 데이터(TAG_ATTRIBUTES.xlsx)가 되살아나지 않았는가.

    네 항목이 모두 업로드 자료에서 오게 됐다.

        TERMINAL       TB List
        TYPE           계기 리스트 SENSOR TYPE
        FAIL POSITION  인터락 리스트 "* Valve Action"
        MANUAL FILE    MODEL ↔ 매뉴얼 파일명 대조

    내가 만든 열이 하나라도 되살아나면 데모에서는 채워지고 실물에서는
    비는 항목이 다시 생긴다. 그 차이는 화면에 드러나지 않는다.

    파일이 없는지만 보지 않고, **네 항목이 실제로 채워지는지**까지
    확인한다. 파일만 없애고 값이 비면 고친 것이 아니다.
    """
    for d in (config.DERIVED_DIR, config.DATA_DIR):
        p = os.path.join(d, "TAG_ATTRIBUTES.xlsx")
        if os.path.isfile(p):
            return False, "부속 데이터가 되살아났습니다: %s" % p
    from ingest.lists import load_points
    pts = load_points(config.IO_LIST, getattr(config, "INSTRUMENT_SPECS", None) or getattr(config, "INSTRUMENT_SPEC", None), None,
                      getattr(config, "TB_LIST", None))
    n = len(pts) or 1
    got = {}
    for k in ("TERMINAL", "TYPE", "MANUAL FILE"):
        got[k] = sum(1 for r in pts.values() if str(r.get(k) or "").strip())
    if got["TERMINAL"] == 0:
        return False, ("단자가 하나도 없습니다 — TB List 를 넣거나 "
                       "python -m tools.make_tb_list 로 만드십시오")
    if got["TYPE"] == 0:
        return False, "계기 리스트에서 SENSOR TYPE 을 읽지 못했습니다"
    if got["MANUAL FILE"] == 0:
        return False, ("매뉴얼 연결이 비었습니다 — MODEL 과 매뉴얼 파일명이 "
                       "대조되지 않습니다")
    from retrieval.interlock_index import load_outputs
    fails = sum(1 for v in load_outputs().values() if v.get("fail"))
    if fails == 0:
        return False, ("고장 위치가 비었습니다 — 인터락 리스트에 "
                       "\"* Valve Action\" 표기가 없습니다")
    return True, ("부속 없음 / 단자 %d · 종류 %d · 매뉴얼 %d · 고장위치 %d"
                  % (got["TERMINAL"], got["TYPE"], got["MANUAL FILE"], fails))


def c_tb_list():
    """
    [주입] TB 리스트가 IO List 와 같은 프로젝트 것인가.

    TB 리스트는 격자 배치 결선표라 읽기만 성공해도 태그가 하나도 안
    겹칠 수 있다. 실제로 다른 프로젝트 TB 리스트를 넣었더니 2,254점을
    정상적으로 읽고도 단자 조회가 통째로 비었다. 읽기 성공과 쓸모 있음은
    다르다.

    TB 리스트가 없으면 통과다 — 부속 데이터의 값으로 동작한다.
    """
    tb_path = getattr(config, "TB_LIST", "")
    if not tb_path or not os.path.isfile(tb_path):
        return True, "TB 리스트 없음 — 부속 데이터의 단자 값을 사용"
    from ingest.tb_list import load_terminals
    from ingest.lists import read_rows
    tb = load_terminals(tb_path)
    if not tb:
        return False, "TB 리스트를 읽었으나 태그가 하나도 없습니다"
    io_tags = {str(r.get("TAG") or "").strip()
               for r in read_rows(config.IO_LIST)}
    io_tags.discard("")
    hit = len(set(tb) & io_tags)
    if hit == 0:
        return False, ("TB 리스트 %d점과 IO List %d점이 하나도 겹치지 "
                       "않습니다 — 다른 프로젝트 자료로 보입니다. 단자 "
                       "조회가 통째로 빕니다." % (len(tb), len(io_tags)))
    ratio = hit / max(1, len(io_tags))
    if ratio < 0.5:
        return False, ("IO List %d점 중 %d점만 TB 리스트에 있습니다 "
                       "(%.0f%%) — 나머지는 단자 조회가 빕니다."
                       % (len(io_tags), hit, ratio * 100))
    return True, "TB %d점 / IO List 대조 %d점 일치 (%.0f%%)" % (
        len(tb), hit, ratio * 100)


def c_rack_unique():
    """
    (PLC, RACK, SLOT) 이 카드를 유일하게 가리키는가.

    RACK 이 전 행 같은 값이면 슬롯 번호가 판넬마다 겹쳐 카드를 구분할 수
    없다. 실제로 v1 데모 데이터가 그랬고, 그래서 카드 ID 에 판넬을 섞어
    쓰고 있다. 겹침이 있으면 실패가 아니라 경고로 남긴다 — 카드 ID 는
    판넬을 포함하므로 동작에는 지장이 없다.
    """
    from retrieval.panel_index import PanelIndex
    from collections import defaultdict
    ix = PanelIndex()
    seen = defaultdict(set)
    for r in ix.rows:
        seen[(r["PLC"], str(r.get("PN(DP)", "")), str(r["RACK"]),
              str(r["SLOT"]))].add(r["PANEL"])
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    if dup:
        k, v = sorted(dup.items())[0]
        return False, ("스테이션·랙 번호가 카드를 구분하지 못합니다 — 예: "
                       "%s 가 %s 에 동시 존재 (겹침 %d건). IO List 의 "
                       "PN(DP)·RACK 을 실제 값으로 채우십시오."
                       % ("/".join(k), ", ".join(sorted(v)), len(dup)))
    return True, "카드 %d장이 (PLC, PN(DP), RACK, SLOT) 으로 유일" % len(
        ix.cards())


def c_arrangement_fresh():
    """
    [주입] 배치도의 판넬별 점수가 현재 계기 리스트와 맞는가.

    배치도는 생성물이라 계기 리스트가 바뀌면 다시 만들어야 한다.
    안 만들면 도면에는 옛 점수가, 조회에는 새 점수가 나오는데 둘 다
    그럴듯해서 어긋났다는 사실이 드러나지 않는다. 실제로 계기 4점이
    추가됐을 때 도면만 옛 값에 머물러 있었다.
    """
    from retrieval.panel_index import PanelIndex, load_locations
    ix = PanelIndex()
    locs = load_locations()
    if not locs:
        return False, "PANEL_LOCATIONS.csv 없음 — tools/make_arrangement.py 실행"
    bad = []
    for p in ix.panels():
        rec = locs.get(p["panel"])
        if rec is None:
            bad.append("%s 배치 정보 없음" % p["panel"])
            continue
        try:
            filed = int(rec.get("points") or -1)
        except (TypeError, ValueError):
            filed = -1
        if filed != p["points"]:
            bad.append("%s 도면 %s점 ≠ 리스트 %d점"
                       % (p["panel"], filed, p["points"]))
    if bad:
        return False, ("; ".join(bad)
                       + " — tools/make_arrangement.py 를 다시 실행하십시오")
    return True, "판넬 %d개 점수 일치 (총 %d점)" % (
        len(locs), sum(p["points"] for p in ix.panels()))


def c_panel_drawing():
    """배치도 PDF 가 있고, 판넬명이 그 안에서 실제로 찾아지는가."""
    if not os.path.exists(config.ARRANGEMENT_PDF):
        return False, ("배치도 없음 — python tools/make_arrangement.py "
                       "(판넬 도면 보기가 통째로 404 가 됩니다)")
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    from retrieval.panel_index import PanelIndex
    ix = PanelIndex()
    doc = fitz.open(config.ARRANGEMENT_PDF)
    miss = []
    for name, loc in ix.locations.items():
        page = doc[max(0, loc["page"] - 1)]
        if not page.search_for(loc["find"]):
            miss.append(name)
    doc.close()
    if miss:
        return False, ("도면에서 못 찾는 판넬: %s — 하이라이트가 안 걸립니다"
                       % ", ".join(miss))
    return True, "판넬 %d개 모두 도면에서 검색됨" % len(ix.locations)


def c_panel_no_verdict():
    """
    [주입] 판넬 상실에 트립 여부를 단정하지 않는가.

    대체값 정책은 리스트에 없다. 그런데 화면이 '트립됩니다' 라고 쓰면
    사용자는 그걸 근거로 판단한다. 근거 없는 단정이 새로 들어오면
    여기서 걸린다.
    """
    from retrieval.panel_index import PanelIndex
    ix = PanelIndex()
    for c in ix.cards()[:5]:
        txt = ix.render_impact(c["card"])
        bad = [w for w in ("트립됩니다", "트립된다", "정지합니다", "동작합니다")
               if w in txt]
        if bad:
            return False, "%s 서술에 단정 표현: %s" % (c["card"],
                                                      ", ".join(bad))
        if "판정하지 않" not in txt:
            return False, ("%s 서술에서 판정 유보 문구가 사라짐 — 근거 없는 "
                           "결론으로 읽힙니다" % c["card"])
    return True, "카드 서술 의존 관계만, 트립 판정 없음"


def c_manual_vocab_not_blocked():
    """
    [주입] 매뉴얼 용어를 태그 오타로 오인해 질문을 막지 않는가.

    "없는 태그는 거절한다" 를 넓히면 반대쪽이 뚫린다. 태그 정규식은
    "PCS 7", "TB2", "AI 16xI", "bge-m3" 같은 기술 용어도 잡는데,
    이걸 태그 오타로 처리하면 매뉴얼 질문이 통째로 거절된다.
    "AI 16xI 모듈 상태 표시" 는 실제 매뉴얼 6.1 절 제목이다.

    반대 방향도 함께 본다 — 낯선 접두어라고 현재 화면 태그로
    대체해서도 안 된다.
    """
    from api.server import find_tag, rule_intent, known_tag_prefixes
    pres = known_tag_prefixes()
    if not pres:
        return False, "태그 접두어를 뽑지 못했습니다"

    # 1) 매뉴얼 용어가 거절되지 않아야 한다
    for q in ("AI 16xI 모듈 상태 표시 설명해줘", "PCS 7 알람 확인 방법",
              "TB2 단자대가 뭐야", "NAMUR NE43 이 뭐야"):
        _, miss = find_tag(q)
        if miss:
            return False, "'%s' 를 태그 오타(%s)로 오인 — 매뉴얼 질문이 막힙니다" % (q, miss)

    # 2) 낯선 접두어는 현재 태그로 대체하지 않아야 한다
    cur = "AIT-4002"
    got, _ = find_tag("zzt-9999는 어디야", cur)
    if got == cur:
        return False, "낯선 접두어 질의가 현재 태그(%s)로 대체됨" % cur
    r = rule_intent("zzt-9999는 어느 위치에 있어?", cur)
    if cur in (r.get("reply") or ""):
        return False, "없는 태그 위치 질문에 현재 태그 답이 나감"

    # 3) 실재 접두어 오타는 여전히 거절해야 한다
    _, miss = find_tag("AIT-9999 알람 조회해줘", cur)
    if not miss:
        return False, "AIT-9999 를 거절하지 못함 — 없는 태그가 통과합니다"
    return True, "접두어 %d종 기준 / 매뉴얼 용어 통과·없는 태그 거절" % len(pres)


def c_smalltalk():
    """
    [주입] 인사에 예시 목록이나 매뉴얼 거절을 돌려주지 않는가.

    "안녕하세요" 에 "예) AIT-4002 low acid 알람 조회해줘 …" 가 나갔고,
    이어진 "인사 안 해주고 예시를 들어주네?" 는 매뉴얼 검색으로 넘어가
    "근거를 찾지 못했습니다" 가 나왔다. 둘 다 사람 눈에는 명백한데
    지표로는 안 잡힌다.

    인사가 조회 의도를 가로채지 않는지도 함께 본다.
    """
    from api.server import rule_intent
    for greet in ("안녕?", "안녕하세요", "ㅎㅇ", "고마워"):
        r = rule_intent(greet)
        rep = r.get("reply") or ""
        if r.get("type") != "chat":
            return False, "'%s' 가 %s 로 분류됨" % (greet, r.get("type"))
        if "예)" in rep or "예:" in rep:
            return False, "'%s' 에 예시 목록이 나갑니다" % greet
        if r.get("generic"):
            return False, ("'%s' 가 포괄 응답으로 떨어져 매뉴얼 검색으로 "
                           "넘어갑니다" % greet)
    # 인사가 조회를 삼키지 않아야 한다
    r = rule_intent("안녕하세요 그런데 AIT-1001 판넬 어디야")
    if r.get("type") != "panel":
        return False, "인사말이 붙은 조회 요청을 %s 로 삼킴" % r.get("type")
    return True, "인사·감사 4종 응대 / 조회 요청은 그대로 통과"


def c_tag_particle():
    """
    [주입] 조사가 붙은 태그를 읽고, 못 읽었을 때 다른 태그로 대체하지 않는가.

    "ait-1001은 어디야" 처럼 조사가 붙으면 \\b 경계가 깨져 태그를 놓치고,
    그러면 현재 선택된 태그로 조용히 대체되어 **다른 설비의 답**이
    나간다. 화면에는 그럴듯한 문장이 떠서 틀렸다는 사실이 드러나지
    않는다. 실제로 한 번 나갔던 고장이다.
    """
    from api.server import find_tag, rule_intent, get_panel
    px = get_panel()
    if px is None:
        return False, "판넬 인덱스 미적재"
    real = sorted(px._by_tag)[0]
    other = sorted(px._by_tag)[-1]
    for suffix in ("은", "는", "이", "가", "의", "에서"):
        got, _ = find_tag("%s%s 어디야" % (real.lower(), suffix), other)
        if got != real:
            return False, ("'%s%s' 를 %s 로 읽음 — 조사가 붙으면 태그를 "
                           "놓칩니다" % (real, suffix, got))
    # 없는 태그를 물었을 때 현재 태그로 대신 답하지 않는가
    r = rule_intent("zzt-9999는 어느 위치에 있어?", other)
    if other in (r.get("reply") or ""):
        return False, "없는 태그 질문에 현재 태그(%s)로 대신 답함" % other
    return True, "조사 6종 복원 / 미해결 태그는 대체하지 않음"


def c_panel_chat():
    """판넬 명령이 규칙 엔진에서 인식되는가 (표기가 태그와 겹침)."""
    from api.server import rule_intent, get_panel
    px = get_panel()
    if px is None:
        return False, "판넬 인덱스 미적재"
    name = sorted(px._by_panel)[0]
    r = rule_intent("%s 내리면 뭐가 죽어?" % name)
    if r.get("type") != "panel":
        return False, "'%s 내리면' 이 %s 로 잘못 분류됨" % (name, r.get("type"))
    # 태그 의도가 판넬 규칙에 먹히지 않았는지도 함께 본다
    r2 = rule_intent("XV-4101 인터락 조회해줘")
    if r2.get("type") != "interlock":
        return False, "판넬 규칙이 인터락 명령을 가로챔 (%s)" % r2.get("type")
    return True, "판넬 %s / 인터락 명령 각각 정상" % name


# ── 6. 리포트 ───────────────────────────────────────────────
def c_report_font():
    """4D 리포트 한글이 깨지지 않는가."""
    from api.report_4d import _register_fonts
    _register_fonts()
    p = os.environ.get("PMC_KR_FONT")
    if not p:
        return False, ("한글 폰트를 찾지 못해 Helvetica 로 떨어집니다 — "
                       "PDF 한글이 통째로 깨집니다")
    return True, p


# ── 7. 화면이 하는 설명 (리허설 발견) ─────────────────────────
def _ui_src(rel):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, rel)
    with open(path, encoding="utf-8") as f:
        return f.read(), path


def _ix_fixture(root, pdfs, bad_embed=False):
    """색인 판정용 픽스처. **임시 폴더에만 만든다** — 데모 자료는 건드리지
    않는다. 시각은 손으로 박는다. 픽스처가 같은 초에 만들어지면 시각 대조가
    그날 운에 따라 통과·실패하기 때문이다."""
    import json as _json
    import time as _t
    man = os.path.join(root, "manuals")
    idx = os.path.join(root, "index")
    os.makedirs(man, exist_ok=True)
    os.makedirs(idx, exist_ok=True)
    for name, body in pdfs.items():
        with open(os.path.join(man, name), "wb") as f:
            f.write(body)
    codes = os.path.join(root, "error_codes.json")
    with open(codes, "w", encoding="utf-8") as f:
        _json.dump([], f)
    with open(os.path.join(idx, "chunks.jsonl"), "w", encoding="utf-8") as f:
        for name in pdfs:
            f.write(_json.dumps(
                {"id": name, "kind": "manual_text",
                 "source": {"file": name, "rel_path": name}},
                ensure_ascii=False) + "\n")
    with open(os.path.join(idx, "embeddings.npy"), "wb") as f:
        f.write(b"\x00" * 16)
    with open(os.path.join(idx, "embeddings.meta.json"), "w",
              encoding="utf-8") as f:
        _json.dump({"provider": ("zz-없는제공자" if bad_embed
                                 else config.EMBED_PROVIDER),
                    "model": config.EMBED_MODEL}, f, ensure_ascii=False)
    # 원본은 오래된 것, 색인은 그 뒤에 만들어진 것으로 시각을 고정한다.
    now = _t.time()
    for folder, back in ((man, 3000), (idx, 1500)):
        for nm in os.listdir(folder):
            os.utime(os.path.join(folder, nm), (now - back, now - back))
    os.utime(codes, (now - 3000, now - 3000))
    return man, idx, codes


def c_screen_notices():
    """
    [주입] 화면이 이유를 말하는가 — 9/2 리허설 발견 1·4·5 (패치 34).

    세 건 다 기능이 아니라 **안내**의 결함이었다. 버튼이 회색인 이유를
    화면이 말하지 않았고(1), 자료가 바뀌지 않았는데도 재생성이 몇 분을
    그대로 돌았고(4), 태그를 쓰지 않는 반입 화면에 태그 선택기가 남아
    있었다(5).

    보는 것 넷.

    1) 색인 변경 판정이 **서버에서** 정답을 내는가. 픽스처를 임시 폴더에
       만들어 그대로·내용만 바뀜·새 파일·빠진 파일·색인 없음·임베딩 다름을
       각각 주입한다. 특히 **시각을 그대로 둔 채 내용만 바꾼** 경우를 본다 —
       기록(SHA-256)이 있으면 잡아야 하고, 없으면 못 잡는다고 말해야 한다.
    2) 판정이 재생성 앞에 **문으로 서지 않는가.** 변경이 없다고 자동으로
       건너뛰면, 그래도 다시 만들고 싶은 사람에게는 방법이 없어진다.
    3) 화면이 그 값을 읽어 말하는가 (App.jsx 세 자리).
    4) **빌드본이 원본보다 오래되지 않았는가.** 고치고 빌드를 잊으면 화면은
       그대로다 — 이 프로젝트에서 두 번 겪은 자리다. 라우팅만 보는 가드가
       서버 500 을 놓쳤던 것과 같은 이유로, 원본만 보고 끝내지 않는다.
    """
    import glob
    import inspect as _inspect
    import shutil
    import tempfile
    from ingest.index_state import index_state, list_sources, write_manifest

    # 주입 전 원본 지문. 시험이 실제 자료를 건드리지 않았음을 끝에서
    # 대조한다 (CLAUDE.md 7 — 임시 폴더에 심고 원본 해시를 대조한다).
    before = [(x["rel"], x["sha256"]) for x in list_sources()]

    root = tempfile.mkdtemp(prefix="pmc_ixstate_")
    try:
        man, idx, codes = _ix_fixture(
            root, {"a.pdf": b"AAAA" * 64, "b.pdf": b"BBBB" * 64})

        def state():
            return index_state(index_dir=idx, manual_dir=man,
                               error_codes=codes)

        # (1) 기록이 없으면 시각 대조. 그 한계를 말해야 한다.
        st = state()
        if st["basis"] != "mtime":
            return False, "기록이 없는데 대조 기준이 %s" % st["basis"]
        if st["changed"] is not False:
            return False, "그대로인데 시각 대조가 '%s'" % st["verdict"]
        if "시각" not in st["reason"]:
            return False, "시각 대조인데 그 사실을 말하지 않습니다"

        # (2) 기록을 남기면 내용 대조로 올라간다.
        write_manifest(index_dir=idx, manual_dir=man, error_codes=codes)
        st = state()
        if st["basis"] != "manifest" or st["changed"] is not False:
            return False, "기록을 남겼는데 %s / '%s'" % (st["basis"],
                                                        st["verdict"])

        # (3) 주입 — 시각은 그대로 두고 내용만 바꾼다. 시각 대조로는
        #     절대 못 잡는 경우다.
        pa = os.path.join(man, "a.pdf")
        keep = os.stat(pa)
        with open(pa, "wb") as f:
            f.write(b"CCCC" * 64)
        os.utime(pa, (keep.st_atime, keep.st_mtime))
        st = state()
        if st["changed"] is not True or st["sources"]["modified"] != ["a.pdf"]:
            return False, ("시각 그대로 내용만 바뀐 것을 못 잡습니다 — "
                           "'%s' / %s" % (st["verdict"], st["sources"]))

        # (4) 주입 — 새 파일·빠진 파일
        write_manifest(index_dir=idx, manual_dir=man, error_codes=codes)
        with open(os.path.join(man, "c.pdf"), "wb") as f:
            f.write(b"DDDD" * 64)
        os.remove(os.path.join(man, "b.pdf"))
        st = state()
        if st["sources"]["added"] != ["c.pdf"] or \
                st["sources"]["removed"] != ["b.pdf"]:
            return False, "새 파일·빠진 파일을 못 잡습니다 — %s" % st["sources"]

        # (5) 주입 — 색인이 없으면 없다고 말해야 한다.
        os.remove(os.path.join(idx, "chunks.jsonl"))
        st = state()
        if st["verdict"] != "색인 없음" or st["changed"] is not True:
            return False, "색인이 없는데 '%s'" % st["verdict"]

        # (6) 주입 — 임베딩 모델이 색인과 다르면 그것도 변경이다. 파일이
        #     그대로여도 그 색인으로는 검색이 조용히 강등된다.
        root2 = tempfile.mkdtemp(prefix="pmc_ixstate2_")
        try:
            man2, idx2, codes2 = _ix_fixture(root2, {"a.pdf": b"AAAA" * 64},
                                             bad_embed=True)
            write_manifest(index_dir=idx2, manual_dir=man2,
                           error_codes=codes2)
            st = index_state(index_dir=idx2, manual_dir=man2,
                             error_codes=codes2)
            if st["changed"] is not True or "임베딩" not in st["reason"]:
                return False, "임베딩 모델이 달라졌는데 '%s'" % st["verdict"]
        finally:
            shutil.rmtree(root2, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if [(x["rel"], x["sha256"]) for x in list_sources()] != before:
        return False, "주입 시험이 실제 자료를 건드렸습니다 — 되돌리십시오"

    # 서버가 그 판정을 화면에 내주는가
    import api.server as _srv
    got = _srv.ingest_index_state()
    for k in ("changed", "verdict", "reason", "basis_label",
              "index_built_at", "sources"):
        if k not in got:
            return False, "/ingest/index-state 응답에 %s 가 없습니다" % k

    # 판정이 재생성 앞에 문으로 서 있으면 안 된다.
    src = _inspect.getsource(_srv.ingest_rebuild)
    if "index_state" in src or "changed" in src:
        return False, ("재생성이 변경 판정을 보고 갈라집니다 — 판정은 "
                       "알려 주기만 해야 합니다")

    # 화면 — 세 건이 실제로 App.jsx 에 들어 있는가
    app, app_path = _ui_src("ui/react/src/App.jsx")
    if "const ALARM_HINT" not in app:
        return False, "App.jsx 에 증상 안내 문장(ALARM_HINT)이 없습니다"
    if app.count("ALARM_HINT") < 3:
        return False, ("증상 안내가 버튼 title·아래 안내 양쪽에 쓰이지 "
                       "않습니다 (%d곳)" % app.count("ALARM_HINT"))
    if "/ingest/index-state" not in app:
        return False, "반입 화면이 색인 변경 판정을 읽지 않습니다"
    head = app[:app.index("<h3>설비 태그</h3>")]
    if "tab !== 'ingest'" not in head[-400:]:
        return False, "자료 반입 탭에서 설비 태그 선택기가 그대로 보입니다"
    if "onClick={rebuild} disabled={st && st.running}" not in app:
        return False, ("재생성 버튼이 재생성 중 말고 다른 이유로 꺼집니다 — "
                       "판정으로 버튼을 막지 않습니다")

    # 빌드본 — 원본보다 오래되면 화면은 고쳐지지 않은 것이다
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = glob.glob(os.path.join(here, "ui", "react", "dist", "assets", "*.js"))
    if not js:
        return False, "빌드본이 없습니다 — ui/react 에서 npm run build"
    newest = max(js, key=os.path.getmtime)
    if os.path.getmtime(newest) < os.path.getmtime(app_path):
        return False, ("빌드본이 App.jsx 보다 오래되었습니다 — "
                       "npm run build 를 하지 않았습니다")
    with open(newest, encoding="utf-8") as f:
        built = f.read()
    for token in ("증상이 비어 있어", "ingest/index-state", "대조 기준"):
        if token not in built:
            return False, "빌드본에 '%s' 가 없습니다 — 빌드가 낡았습니다" % token
    return True, ("판정 6종(내용·시각·새·빠진·색인없음·임베딩) / 자동 "
                  "건너뛰기 없음 / App.jsx 3자리 · 빌드본 반영 / 원본 무손상")


# ── 8. 도구 목록 ────────────────────────────────────────────
def c_tool_registry():
    """
    [주입] 도구 목록이 한 곳인가, 그리고 기존 명령이 그대로인가 (패치 35).

    패치 33 은 같은 지식이 두 곳(규칙·LLM 스키마)에 적혀 있어서 났다.
    한 곳만 고치면 규칙이 아는 표현은 되고 모르는 표현은 모델이 받아
    엉뚱한 곳으로 간다. 목록을 한 곳으로 모았으니, 이 가드는 **모은 것이
    실제로 하나로 도는지**와 **모으면서 기존 것을 깨지 않았는지**를 본다.

    보는 것 넷.

    1) 규칙이 판정하는 도구가 모델이 고를 수 있는 목록에도 들어 있는가.
       하나라도 빠지면 패치 33 이 다시 난다.
    2) **주입** — 반쪽으로 등록한 도구를 넣으면 등록 점검이 죽는가.
       표현만 적고 본체를 잊은 것, 실행 명령인데 스키마 설명이 없는 것.
       (진짜 목록은 건드리지 않는다. 넣었다 되돌리고 원상태를 대조한다.)
    3) 새로 넣은 도구 둘 — 탭 이동과 범위 밖 질문 — 이 실제로 도는가.
    4) **기존 챗봇 계열이 그대로인가.** 이 가드의 절반은 여기다. 규칙
       계층을 통째로 갈아끼웠으므로, 조회·후속 질문·인사·기능 안내가
       예전과 같은 판정을 내는지 표로 대조한다.
    """
    from api import tools
    from api.server import (ChatRequest, chat_help, llm_command_prompt,
                            rule_intent)

    # (1) 규칙 ↔ 스키마 — 같은 목록을 읽는가
    prompt = llm_command_prompt(False)
    schema = tools.llm_schema_line()
    rules = tools.llm_rule_block()
    for t in tools.all_tools():
        if t.actionable and t.llm_type not in schema:
            return False, ("%s 가 규칙에는 있는데 모델이 고를 수 있는 "
                           "목록에 없습니다 (패치 33 이 난 자리)" % t.key)
        if t.summary and t.summary not in prompt:
            return False, "%s 설명이 지침에 실리지 않았습니다" % t.key
        if t.llm_rule and t.llm_rule not in rules:
            return False, "%s 지시문이 지침에 실리지 않았습니다" % t.key
        # 이 도구가 쓰는 필드가 스키마 줄에 있어야 한다. 설명문에만
        # 남아 있으면 모델은 스키마에 없는 필드를 채우게 된다.
        for f in t.schema_extra:
            if f not in schema:
                return False, "%s 의 %s 필드가 스키마 줄에 없습니다" % (
                    t.key, f)

    # 화면이 실제로 읽는 것들. 목록에서 지웠을 때 가드도 함께 지워지면
    # 그건 점검이 아니다 — 그래서 기대하는 이름을 **여기에 따로** 적는다.
    for ty in ("diagnose", "drawing", "interlock", "interlock_source",
               "panel", "navigate", "advice", "help", "chat"):
        if ty not in schema:
            return False, "스키마 줄에 %s 명령이 없습니다" % ty
    for f in ("tag", "tab", "alarm", "action", "openSource",
              "openGraphic", "playScenario", "stopScenario"):
        if f not in schema:
            return False, "스키마 줄에 %s 필드가 없습니다" % f

    # 규칙이 실제로 내는 type 을 모델이 고를 수 있는가.
    #
    # 표시(actionable)를 믿지 않고 **돌려서** 확인한다. 표시를 지우면
    # 스키마에서 빠지는데, 규칙은 그대로 그 명령을 내므로 화면은 도는데
    # 모델만 모르는 상태가 된다 — 패치 33 이 정확히 그 모양이었다.
    for t in tools.all_tools():
        if not t.example:
            continue
        r = rule_intent(t.example, None, "alarm") or {}
        # 되물을 수 있는 도구는 chat 도 정답이다 — 맥락이 없을 때
        # 실행하지 않고 묻는 것이 그 도구의 본래 동작이다 (패치 36).
        want = {t.returns, "chat"} if t.asks_back else {t.returns}
        if r.get("type") not in want:
            return False, "%s 의 예시 '%s' 가 %s 로 갑니다 (기대 %s)" % (
                t.key, t.example[:20], r.get("type"),
                "/".join(sorted(want)))
        if r["type"] in ("chat", "followup"):
            continue
        if r["type"] not in schema:
            return False, ("규칙은 %s 를 내는데 모델은 그것을 고를 수 "
                           "없습니다 — 목록이 갈라졌습니다" % r["type"])

    # (2) 주입 — 반쪽 등록을 잡는가. 진짜 목록은 건드리지 않는다.
    before = list(tools._TOOLS)
    try:
        broken = [
            ("표현만 있고 본체 없음",
             dict(key="_probe_a", label="주입", order=1,
                  trigger=r"이런낱말은없다")),
            ("실행 명령인데 스키마 설명 없음",
             dict(key="_probe_b", label="주입", order=1, actionable=True)),
            ("기능 질문 표현만 있고 안내문 없음",
             dict(key="_probe_c", label="주입", order=1,
                  help_pattern=r"이런낱말은없다")),
        ]
        for name, kw in broken:
            tools.Tool(**kw)
            try:
                tools.check()
            except RuntimeError:
                pass                       # 잡았다 — 정상
            else:
                return False, "반쪽 등록(%s)을 그대로 통과시킵니다" % name
            finally:
                tools._TOOLS[:] = before
        # 되돌린 뒤 진짜 목록은 여전히 성한가
        tools.check()
    finally:
        tools._TOOLS[:] = before
    if [t.key for t in tools._TOOLS] != [t.key for t in before]:
        return False, "주입 시험이 진짜 도구 목록을 바꿨습니다"

    # (3) 새 도구 둘
    #
    # 탭 이동 — 화면만 옮기고 조회를 실행하지 않아야 한다. 태그도 그대로
    # 두어야 한다. 옮기라는 말에 사이드바 태그까지 바뀌면 다음 조회가
    # 엉뚱한 설비를 본다.
    for msg, want_tab in (("알람 조회 탭으로 이동해줘", "alarm"),
                          ("인터락 조회 탭으로 가줘", "interlock"),
                          ("판넬 조회 탭 열어줘", "panel"),
                          ("자료 반입 탭으로 이동", "ingest")):
        r = rule_intent(msg, "AIT-4002", "alarm") or {}
        if r.get("type") != "navigate" or r.get("tab") != want_tab:
            return False, "'%s' → %s / tab=%s" % (msg[:18], r.get("type"),
                                                  r.get("tab"))
        if r.get("tag"):
            return False, "'%s' 가 태그까지 바꿉니다 (%s)" % (msg[:18],
                                                            r.get("tag"))
    r = rule_intent("탭 이동해줘", "AIT-4002", "alarm") or {}
    if r.get("type") != "chat" or "어느 탭" not in (r.get("reply") or ""):
        return False, "어느 탭인지 없는데 되묻지 않고 %s" % r.get("type")

    # 범위 밖 질문 — 매뉴얼 검색으로 내려가면 안 된다. generic 이면
    # 챗봇 계층이 QA 로 넘기므로, generic 이 아니어야 한다.
    for msg in ("오늘 며칠이야", "지금 몇 시야", "오늘 날짜 알려줘",
                "내일 날씨 어때", "환율 얼마야"):
        r = rule_intent(msg, "AIT-4002", "alarm") or {}
        if r.get("type") != "chat" or r.get("generic"):
            return False, "'%s' → %s (generic=%s) — 매뉴얼 검색으로 샙니다" % (
                msg, r.get("type"), r.get("generic"))
        if "알지 못" not in (r.get("reply") or ""):
            return False, "'%s' 응답이 모른다고 말하지 않습니다" % msg
    # 실제로 챗봇을 태워 인용이 붙지 않는지까지 본다. 라우팅만 보면
    # 화면에 무엇이 붙는지는 모른다 (패치 29b 에서 겪은 자리).
    got = chat_help(ChatRequest(message="오늘 며칠이야", tab="alarm",
                                use_llm=False))
    if got.get("citations"):
        return False, "범위 밖 질문에 근거 인용이 붙었습니다"
    if got.get("engine") != "rule":
        return False, "범위 밖 질문이 %s 경로로 갔습니다" % got.get("engine")

    # 경계 — 정비 낱말이 섞인 시간 질문까지 끊으면 안 된다
    for msg in ("지연 시간이 얼마야", "LIT-4003 이 걸린 인터락"):
        r = rule_intent(msg, "AIT-4002", "alarm") or {}
        if "알지 못" in (r.get("reply") or ""):
            return False, "'%s' 를 범위 밖으로 잘못 끊습니다" % msg

    # 화면이 그 명령을 실제로 실행하는가. 규칙이 옳게 판정해도 화면이
    # 걸러 버리면 아무 일도 일어나지 않는다 — 사용자에게는 무시당한
    # 것으로 보인다. 라우팅만 보는 가드가 서버 500 을 놓쳤던 자리와 같다.
    app, _path = _ui_src("ui/react/src/App.jsx")
    if "if (cmd.tab) setTab(cmd.tab)" not in app:
        return False, "화면이 탭 이동 명령을 받지 않습니다 (App.jsx)"
    if "cmd.type !== 'navigate'" not in app:
        return False, ("탭 이동이 조회 명령처럼 화면에 전달됩니다 — "
                       "옮기기만 해야 합니다 (App.jsx)")

    # (4) 기존 챗봇 계열 — 갈아끼우기 전과 같은 판정인가
    same = [
        ("AIT-4002 산 잔량 알람 조회해줘", "diagnose", "AIT-4002"),
        ("AIT-4002 acid residual low 알람 조회해줘", "diagnose", "AIT-4002"),
        ("XV-4101 인터락 조회", "interlock", "XV-4101"),
        ("LCV 01 인터락 보여줘", "interlock", "LCV-01"),
        ("LCV-01 인터락 원본 보여줘", "interlock_source", "LCV-01"),
        ("AIT-1001 P&ID 도면 보여줘", "drawing", "AIT-1001"),
        ("CUB-A 판넬 조회해줘", "panel", None),
        ("사용법 알려줘", "help", None),
        ("시나리오 재생해줘", "interlock", "P-5101A"),
        ("시나리오 정지해주세요", "interlock", "P-5101A"),
        ("조회된 내용을 보고 조치방법을 알려줘", "followup", None),
        ("조치방법 알려줘", "followup", None),
        ("말로 풀어서 설명해줘", "followup", None),
        ("자료 반입 어떻게 해", "chat", None),
        ("안녕하세요", "chat", None),
        ("ZZZ-99 인터락 조회", "chat", None),
        ("판넬 조회로 나는 어떤걸 알 수 있지?", "chat", None),
        ("그냥 해본 말이야", "chat", None),
    ]
    for msg, want, tag in same:
        r = rule_intent(msg, None, "alarm") or {}
        if r.get("type") != want:
            return False, "'%s' → %s (기대 %s) — 기존 명령이 깨졌습니다" % (
                msg[:22], r.get("type"), want)
        if tag and r.get("tag") != tag:
            return False, "'%s' 태그 %s (기대 %s)" % (msg[:22], r.get("tag"),
                                                     tag)
    # 인사·기능 안내는 포괄 응답으로 떨어지면 안 되고(매뉴얼 검색으로
    # 샌다), 못 알아들은 잡담은 반대로 포괄이어야 한다(LLM 이 받는다).
    if (rule_intent("안녕하세요") or {}).get("generic"):
        return False, "인사가 포괄 응답으로 떨어집니다"
    if not (rule_intent("그냥 해본 말이야") or {}).get("generic"):
        return False, "못 알아들은 말이 포괄 응답이 아닙니다 — LLM 이 못 받습니다"

    n_rule = len([t for t in tools.all_tools() if t.handler])
    return True, ("도구 %d종 한 곳에서 정의 / 규칙·스키마 일치 / 반쪽 등록 "
                  "3종 검출 / 탭 이동 4탭·범위 밖 5종 / 기존 명령 %d종 유지"
                  % (n_rule, len(same)))


# ── 실행 ────────────────────────────────────────────────────
ROOT_DIR_37 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 패치 37 — L1 IO LIST 표준양식 · 공정 모의 화면 ───────────────

_L1_TEMPLATE = os.path.join(ROOT_DIR_37, "demo", "L1_IO_LIST_표준양식_Rev0_1.xlsx")


def _l1_fixture(tmp):
    from tools.convert_io_to_l1 import convert
    out = os.path.join(tmp, "IO_LIST_L1.xlsx")
    convert(str(config.IO_LIST), _L1_TEMPLATE, out)
    return out


def c_io_l1_equiv():
    """L1 표준양식 동등성 [주입] — 같은 자료를 두 양식으로 읽어 같은 점이 나오는가.
    주입: L1 의 UNIT(공정 대분류) 칸에 'RO' 를 적어 공학 단위로 새지 않는지 본다."""
    import tempfile
    import openpyxl
    from ingest.lists import load_points
    spec = getattr(config, "INSTRUMENT_SPECS", None) or getattr(config, "INSTRUMENT_SPEC", None)
    with tempfile.TemporaryDirectory() as tmp:
        fx = _l1_fixture(tmp)
        a = load_points(str(config.IO_LIST), spec, None, getattr(config, "TB_LIST", None))
        b = load_points(fx, spec, None, getattr(config, "TB_LIST", None))
        if set(a) != set(b):
            return False, "점 집합이 다름 (24종 %d · L1 %d)" % (len(a), len(b))
        keys = ("PLC", "PANEL", "SLOT", "CH", "UNIT", "IO TYPE", "DESCRIPTION",
                "P&ID TAG", "TYPE", "RANGE MIN", "RANGE MAX", "TERMINAL")
        diff = [(t, k) for t in a for k in keys if str(a[t].get(k)) != str(b[t].get(k))]
        if diff:
            return False, "필드 불일치 %d건 — %s" % (len(diff), diff[:3])
        # 주입 — 뜻이 겹치는 열
        wb = openpyxl.load_workbook(fx)
        ws = wb["IO LIST"]
        hdr = [c.value for c in ws[1]]
        ws.cell(row=2, column=hdr.index("UNIT") + 1, value="RO")
        ws.cell(row=2, column=hdr.index("PLC") + 1, value="PID")
        ws.cell(row=2, column=hdr.index("RANGE (단위)") + 1, value="0~250 kPa")
        tag = ws.cell(row=2, column=hdr.index("TAG") + 1).value
        wb.save(fx)
        c = load_points(fx, spec, None, None)[tag]
        if c.get("UNIT") == "RO" or c.get("PLC") == "PID":
            return False, "L1 의 UNIT/PLC 가 공학 단위/제어기 이름으로 샘 (%s/%s)" % (c.get("UNIT"), c.get("PLC"))
        if c.get("UNIT") != "kPa" or float(c.get("RANGE MAX")) != 250:
            return False, "RANGE (단위) 를 읽지 못함 — %s %s" % (c.get("RANGE MAX"), c.get("UNIT"))
    return True, "%d점 × %d필드 일치 / 주입(UNIT=RO·PLC=PID·0~250 kPa) 격리 확인" % (len(a), len(keys))


def c_io_l1_repair():
    """L1 수리안 [주입] — 깨끗한 L1 에 수리안 0건, 채널 중복·헤더 오기는 잡는가.
    24종 기준으로 대조하면 L1 열 이름을 24종 이름으로 바꾸자는 수리안이 나온다."""
    import tempfile
    import openpyxl
    from ingest import repair
    with tempfile.TemporaryDirectory() as tmp:
        fx = _l1_fixture(tmp)
        n0 = repair.propose(io_path=fx, include_cross=False)["counts"]["total"]
        if n0:
            return False, "깨끗한 L1 에 수리안 %d건 — 양식을 24종으로 보고 있음" % n0
        wb = openpyxl.load_workbook(fx)
        ws = wb["IO LIST"]
        hdr = [c.value for c in ws[1]]
        for k in ("CPU", "PN", "SLOT", "CH", "PANEL"):
            j = hdr.index(k) + 1
            ws.cell(row=4, column=j, value=ws.cell(row=3, column=j).value)
        ws.cell(row=1, column=hdr.index("DESCRIPTION") + 1, value="DESCRIPTON")
        wb.save(fx)
        ids = [p["id"] for p in repair.propose(io_path=fx, include_cross=False)["proposals"]]
    kinds = {i.split(":")[0] for i in ids}
    if not {"ch", "hdr"} <= kinds:
        return False, "주입 2종(채널 중복·헤더 오기) 중 못 잡음 — %s" % ids
    return True, "깨끗한 L1 수리안 0건 / 주입 채널 중복·헤더 오기 검출"


def _sim_model():
    import json as _j
    from sim.model import build_model, load_sources
    lay = _j.load(open(os.path.join(ROOT_DIR_37, "demo", "sim", "layout_P5101_demo.json"),
                       encoding="utf-8"))
    src = load_sources()
    return build_model(lay, sources=src, title="selfcheck"), src


def c_sim_trace():
    """공정 모의 근거 추적 [주입] — 조건·설정값·지연이 인터락 원문에서만 오는가.
    주입: 모델의 설정값 하나를 바꿔 추적이 잡는지, 리스트에 없는 태그가 '미확인' 인지."""
    import copy
    from sim.model import trace_problems
    m, src = _sim_model()
    if not m["conds"]:
        return False, "P-5101A 대조 배치에서 조건 0건 — 인터락 연결 실패"
    probs = trace_problems(m, src["interlocks"])
    if probs:
        return False, "근거 추적 실패 %d건 — %s" % (len(probs), probs[:2])
    bad = copy.deepcopy(m)
    k = next(c for c, v in bad["conds"].items() if v["test"].get("t") == "cmp")
    bad["conds"][k]["test"]["sp"] += 1.5
    if not trace_problems(bad, src["interlocks"]):
        return False, "주입한 설정값 변조를 추적이 못 잡음"
    unk = [o["tag"] for o in m["objects"] if o.get("tag") and not o["verify"]["known"]]
    if unk != ["UPW-TK"]:
        return False, "미확인 판정이 다름 — %s (기대 UPW-TK)" % unk
    if "UPW-TK" in m["devices"] and m["devices"]["UPW-TK"]["groups"]:
        return False, "리스트에 없는 태그에 로직이 붙음"
    return True, "조건 %d건 원문 추적 / 주입 변조 검출 / 미확인 태그 UPW-TK 무로직" % len(m["conds"])


def c_sim_routes():
    """공정 모의 API [주입] — 열쇠 없는 쓰기 401, 생성·조회·배치 교체·경로 탈출 차단."""
    import json as _j
    import tempfile
    from fastapi.testclient import TestClient
    import api.server as srv
    lay = _j.load(open(os.path.join(ROOT_DIR_37, "demo", "sim", "layout_P5101_demo.json"),
                       encoding="utf-8"))
    old_d, old_k = config.DERIVED_DIR, os.environ.get("COPILOT_INGEST_KEY")
    with tempfile.TemporaryDirectory() as tmp:
        config.DERIVED_DIR = tmp                     # 산출물을 격리한다
        os.environ["COPILOT_INGEST_KEY"] = "sc-sim-key"
        try:
            c = TestClient(srv.app)
            r = c.post("/api/sim/screens/layout?title=sc", json=lay)
            if r.status_code != 401:
                return False, "무열쇠 생성이 %d — 401 이어야 함" % r.status_code
            h = {"X-Ingest-Key": "sc-sim-key", "X-Ingest-Session": "sc"}
            r = c.post("/api/sim/screens/layout?title=sc", json=lay, headers=h)
            if r.status_code != 200:
                return False, "생성 실패 %d %s" % (r.status_code, r.text[:120])
            sid = r.json()["id"]
            v = c.get("/api/sim/screens/%s/view" % sid).text
            if "const M = {" not in v or v.count("</script>") != 1:
                return False, "모의 화면에 모델이 안 실렸거나 스크립트가 끊김"
            if "P-5101A" not in c.get("/api/sim/tag/P-5101A").json()["screens"][0] + sid and \
                    sid not in c.get("/api/sim/tag/P-5101A").json()["screens"]:
                return False, "태그→화면 조회 실패"
            lay2 = c.get("/api/sim/screens/%s/layout" % sid).json()
            lay2["objects"] = [o for o in lay2["objects"] if o["tag"] != "UV-5102"]
            r = c.put("/api/sim/screens/%s/layout" % sid, json=lay2, headers=h)
            if r.status_code != 200 or r.json()["stats"]["objects"] != 5:
                return False, "배치 교체 실패 %d" % r.status_code
            if not os.path.isfile(os.path.join(tmp, "sim", sid, "layout.prev.json")):
                return False, "배치 교체 전 판(.prev) 보존 없음"
            if c.get("/api/sim/screens/..%2F..%2Fconfig/view").status_code != 404:
                return False, "경로 탈출 차단 실패"
        finally:
            config.DERIVED_DIR = old_d
            if old_k is None:
                os.environ.pop("COPILOT_INGEST_KEY", None)
            else:
                os.environ["COPILOT_INGEST_KEY"] = old_k
            try:
                srv._edit_lease["owner"] = None
            except Exception:
                pass
    return True, "무열쇠 401 · 생성·화면·태그 조회 · 배치 교체(.prev) · 경로 탈출 404"


def c_sim_engine():
    """공정 모의 엔진 [주입] — 조건 점검이 리스트대로 PASS 하고, 래치를 못 거는 엔진은 FAIL 하는가.
    주입은 모델이 아니라 엔진에 심는다. 기대 동작도 모델(리스트)에서 오므로, 모델을
    바꾸면 기대와 동작이 함께 바뀌어 점검이 통과해 버린다 — 그것은 고장 검출이 아니다.
    브라우저(playwright)가 있을 때만 실제로 띄워 본다 (화면 코드는 띄워 봐야 안다)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None, "playwright 없음 — 건너뜀 (pip install playwright · playwright install chromium)"
    import tempfile
    from sim.store import render_html
    m, _ = _sim_model()
    good = render_html(m)
    hook = "st.latch[g.il_no]=true"
    if good.count(hook) != 1:
        return False, "엔진의 래치 설정 지점을 찾지 못함 — 주입 지점 갱신 필요"
    bad = good.replace(hook, "void 0")              # 주입: 래치를 못 거는 엔진
    res = []
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        b = p.chromium.launch()
        for html in (good, bad):
            f = os.path.join(tmp, "s.html")
            open(f, "w", encoding="utf-8").write(html)
            pg = b.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto("file://" + f)
            pg.wait_for_timeout(300)
            pg.evaluate("runTests()")
            res.append((pg.evaluate("window.__TEST__"), errs))
            pg.close()
        b.close()
    (ok, e1), (ng, e2) = res
    if e1 or e2:
        return False, "화면 스크립트 오류 — %s" % (e1 or e2)[:2]
    if ok["FAIL"] or ok["PASS"] < 15:
        return False, "정상 모델 점검 PASS %d · FAIL %d" % (ok["PASS"], ok["FAIL"])
    if not ng["FAIL"]:
        return False, "래치를 못 거는 엔진을 점검이 못 잡음"
    return True, "정상 PASS %d·FAIL 0·SKIP %d / 주입(엔진 래치 상실) FAIL %d 검출" % (
        ok["PASS"], ok["SKIP"], ng["FAIL"])


def c_llm_no_temperature():
    """temperature 거절 모델 [주입] — GPT-5 계열이 temperature 0 을 400 으로
    거절해도 조치 생성이 살아남는가. 네트워크 없이 _post 를 바꿔 끼워 본다.
    주입 1: 별칭 모델이 400(temperature) → 빼고 재시도해 성공해야 한다.
    주입 2: 모델 이름 오류 400 → 재시도 없이, 본문이 실린 오류여야 한다."""
    import io
    import urllib.error
    from graph import advisor as A
    sent = []

    def fake(url, payload, headers, timeout=120):
        sent.append(dict(payload))
        if payload.get("model") == "bad-name":
            raise urllib.error.HTTPError(url, 400, "Bad Request", {},
                                         io.BytesIO(b'{"error":"Invalid model name"}'))
        if "temperature" in payload:
            raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(
                b'{"error":{"message":"Unsupported value: \'temperature\' does not support 0"}}'))
        return {"choices": [{"message": {"content": "ok"}}]}

    orig, A._post = A._post, fake
    try:
        r = A._post_chat("u", {"model": "alias-x"}, {}, 5, "alias-x")
        if r["choices"][0]["message"]["content"] != "ok" or len(sent) != 2:
            return False, "temperature 거절 후 재시도 실패 (호출 %d회)" % len(sent)
        sent.clear()
        A._post_chat("u", {"model": "alias-x"}, {}, 5, "alias-x")
        if len(sent) != 1 or "temperature" in sent[0]:
            return False, "거절된 모델을 기억하지 못함"
        sent.clear()
        if "temperature" in (A._post_chat("u", {"model": "esg-gpt-5.5"}, {}, 5,
                                          "esg-gpt-5.5") and sent[0]):
            return False, "gpt-5 계열에 temperature 를 보냄"
        sent.clear()
        try:
            A._post_chat("u", {"model": "bad-name"}, {}, 5, "bad-name")
            return False, "모델 이름 오류가 통과됨"
        except A.AdvisorError as e:
            if len(sent) != 1 or "Invalid model name" not in str(e):
                return False, "이름 오류에 재시도했거나 본문이 없음 — %s" % e
    finally:
        A._post = orig
        A._NO_TEMP.discard("alias-x")
    return True, "거절 시 빼고 재시도·기억 / gpt-5 계열 처음부터 제외 / 이름 오류는 본문과 함께 실패"

def main():
    ap = argparse.ArgumentParser(description="시연 전 전 경로 점검")
    ap.add_argument("--skip-llm", action="store_true",
                    help="모델 호출 없이 구조만 점검")
    args = ap.parse_args()

    # 출력이 파이프·파일로 갈 때 윈도우는 인코딩을 cp949 로 잡는다. 이
    # 파일의 메시지에는 cp949 에 없는 글자(em dash)가 있어, 콘솔에서는
    # 멀쩡하다가 로그 파일로 받는 순간 첫 줄에서 UnicodeEncodeError 로
    # 죽었다. 점검 결과를 기록으로 남기려는 순간에만 죽으므로 알아채기
    # 어렵다. preflight 에는 같은 것을 못 박아 두고(패치 32) 정작 이
    # 파일은 빠져 있었다.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    print("\nPlant Maintenance Copilot — 시연 전 점검\n" + "=" * 78)

    run("검색 모드 구성", c_search_modes)
    run("한글 질의 도달", c_korean_query)
    run("근거 없을 때 거절", c_abstain_works)
    run("강등 가시성 [주입]", c_degrade_visible)
    run("다양성 설정", c_diversify_off, critical=False)
    run("SSL 코드 조회 [주입]", c_ssl_code_lookup)
    run("알람 라우팅 격리 [주입]", c_alarm_rules_inert)
    run("IO 채널 유일성 [주입]", c_io_channel_unique)
    run("알람 폭주 역추적 [주입]", c_flood_reverse)
    run("수리안 왕복 [주입]", c_repair_roundtrip)
    run("수리 반영 열쇠 [주입]", c_repair_key_gate)
    run("동시 알람 조사 [주입]", c_flood_investigate)
    run("인터락 후속 질문 [주입]", c_followup_interlock)
    run("기능 질문 라우팅 [주입]", c_feature_question)
    run("단자 번호 역조회 [주입]", c_terminal_lookup)
    run("단자 번호 유일성 [주입]", c_terminal_unique)
    run("환경 점검 게이트 [주입]", c_preflight_gate)
    run("시나리오 정지 명령 [주입]", c_scenario_stop)
    run("임베딩 캐시 신원 [주입]", c_cache_identity)
    run("환각 차단 [주입]", c_advisor_rejects_fake)
    run("챗봇·조치 경로 일치", c_chat_gateway)
    run("규칙 엔진 명령 인식", c_chat_rule)
    run("태그 표기 복원", c_tag_notation)
    run("챗봇 명령 실행 [주입]", c_chat_dispatch)
    run("챗봇 근거 답변 [주입]", c_chat_qa)
    run("챗봇 후속 질문", c_chat_followup)
    run("인터락 72문항", c_interlock_eval)
    run("판넬 평가셋", c_panel_eval)
    run("카드 단위 분리 [주입]", c_card_scope)
    run("카드 채널 노출 [주입]", c_card_channels_visible)
    run("공통원인 점검 [주입]", c_common_cause)
    run("판넬 상실 미제공", c_no_panel_impact)
    run("data 폴더 정결 [주입]", c_data_dir_clean)
    run("표준 IO List 원천 대조 [주입]", c_io_list_standard)
    run("IO List 표준 헤더 [주입]", c_io_list_header)
    run("태그 교차 정합성 [주입]", c_tag_cross_consistency)
    run("계기 리스트 실물 양식 [주입]", c_instrument_form)
    run("사양 출처 실물 문서 [주입]", c_attr_source_real)
    run("P&ID 규칙 매핑 [주입]", c_pid_rule_mapping)
    run("조치 생성 경로 [주입]", c_advice_path_runs)
    run("이력 파일 부재 [주입]", c_history_missing_file)
    run("이력 번호 위조 [주입]", c_history_wo_forged)
    run("추측 격리 [주입]", c_guess_only_on_abstain)
    run("부속 데이터 폐지 [주입]", c_no_attr_file)
    run("TB 리스트 대조 [주입]", c_tb_list)
    run("스테이션·랙 유일성", c_rack_unique)
    # 도면은 실물 반입이 어려워 데모 도면을 그대로 쓰기로 했다. 실물 IO List
    # 와 데모 배치도를 함께 쓰면 판넬명이 어긋나는 것이 당연하므로, 이 항목은
    # 시연을 막는 실패가 아니라 주의로 둔다 — 데모 세트로 돌리면 그대로 통과한다.
    run("배치도 최신 [주입]", c_arrangement_fresh, critical=False)
    run("판넬 배치도 검색", c_panel_drawing)
    run("카드 트립 단정 금지 [주입]", c_panel_no_verdict)
    run("판넬 명령 인식", c_panel_chat)
    run("인사 응대 [주입]", c_smalltalk)
    run("태그 조사 표기 [주입]", c_tag_particle)
    run("매뉴얼 용어 오인 금지 [주입]", c_manual_vocab_not_blocked)
    run("화면 안내 3건 [주입]", c_screen_notices)
    run("도구 목록 통합 [주입]", c_tool_registry)
    run("L1 표준양식 동등성 [주입]", c_io_l1_equiv)
    run("L1 수리안 [주입]", c_io_l1_repair)
    run("공정 모의 근거 추적 [주입]", c_sim_trace)
    run("공정 모의 API [주입]", c_sim_routes)
    run("공정 모의 엔진 [주입]", c_sim_engine, critical=False)
    run("temperature 거절 모델 [주입]", c_llm_no_temperature)
    run("한글 PDF 폰트", c_report_font, critical=False)
    if not args.skip_llm:
        run("조치 생성 모델 연결", c_advisor_reachable, critical=False)
        run("조치 생성 실행", c_advisor_real, critical=False)

    w = max(len(r[1]) for r in _rows)
    for st, name, detail in _rows:
        print("[%s] %-*s  %s" % (st, w, name, detail))
    print("=" * 78)

    bad = [r for r in _rows if r[0] == "실패"]
    warn = [r for r in _rows if r[0] == "주의"]
    if bad:
        print("실패 %d건 — 이 상태로 시연하면 해당 경로가 조용히 무너집니다." % len(bad))
        return 1
    if warn:
        print("필수 경로 정상. 주의 %d건은 화면 품질에 영향합니다." % len(warn))
    else:
        print("전 경로 정상. 고장 주입 검사도 통과했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
