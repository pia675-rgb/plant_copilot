#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools.py — 이 도구가 할 수 있는 일의 **유일한 정의** (패치 35)

## 왜 만들었나

패치 33 에서 "시나리오 정지해주세요" 가 P-5101A 정지 인터락 조회로 샜다.
고치고 나서 원인을 다시 보니, 같은 지식이 **두 곳**에 적혀 있었다.

    규칙(rule_intent)          무엇을 무엇으로 판정할지
    LLM 명령 해석 스키마        모델이 고를 수 있는 것이 무엇인지

정지를 규칙에만 넣고 스키마에 넣지 않으면, 규칙이 아는 표현은 되고 모르는
표현은 모델이 받아 **가장 가까운 것**(인터락 STOP)으로 간다. 실제로 그랬다.
도구를 하나 늘릴 때 두 곳을 고쳐야 하고, 한 곳을 잊으면 그 사고가 다시 난다.

**그래서 도구 목록을 여기 한 곳에 두고, 규칙과 스키마가 이것을 읽는다.**
도구를 늘릴 때 고칠 파일은 이 파일 하나다.

## 한 항목이 갖는 것

| 무엇 | 누가 읽나 |
| --- | --- |
| `trigger` · `handler` | 규칙 (`rule_intent`) |
| `summary` · `limit` · `llm_rule` · `schema_extra` | LLM 명령 해석 스키마 |
| `help_pattern` · `help` | 기능 질문 안내 ("인터락 조회는 뭘 보여줘?") |
| `example` | 포괄 응답·범위 밖 안내의 예시 줄 |
| `returns` · `actionable` · `needs_tag` | 챗봇 계층의 실행 판정 |

한 줄만 적고 나머지를 빠뜨리면 그 도구는 반쪽이 된다. 그래서 `check()` 가
가져오기 시점에 빈 자리를 잡는다 — 잊은 것을 **띄우고 죽는다**. 조용히
반쪽으로 도는 것보다 낫다 (CLAUDE.md 3-4).

## 순서

`order` 가 규칙 판정 순서다. 순서 자체가 그동안 겪은 사고의 기록이라,
숫자 옆에 이유를 적어 둔다. 특히

  - 기능 질문은 명령보다 **먼저** (패치 29b — 물었는데 실행됐다)
  - 시나리오 정지는 인터락보다 **먼저** (패치 33 — '정지' 가 겹친다)
  - 탭 이동은 조회보다 **먼저** (탭으로 가 달라는 말이 조회로 실행됐다)

`before_tag=True` 는 태그 판정 **전에** 도는 것이다. 판넬명·단자 번호는
표기가 태그와 겹쳐서 태그 판정보다 먼저 봐야 한다.
"""

import re

_TOOLS = []


class Tool:
    """도구 하나. 규칙·스키마·안내가 모두 이 한 항목을 읽는다."""

    def __init__(self, key, label, order, returns=None, llm_type=None,
                 tab="", needs_tag=False, actionable=False, before_tag=False,
                 trigger="", summary="", summary_order=0, limit="",
                 llm_rule="",
                 schema_extra=(), help_order=0, help_pattern="", help="",
                 example="", note="", asks_back=False):
        self.key = key
        self.label = label
        self.order = order
        self.returns = returns or key      # rule_intent 가 내는 type
        # 화면·모델이 부르는 이름. 규칙이 내는 type 과 다를 수 있다 —
        # 조치 순서는 규칙에서는 followup(화면 결과가 있어야 만든다)이고
        # 모델에게는 advice 다.
        self.llm_type = llm_type or self.returns
        self.tab = tab
        self.needs_tag = needs_tag
        self.actionable = actionable
        self.before_tag = before_tag
        self.trigger = trigger
        self.summary = summary             # 할 수 있는 일 (LLM 도구 목록)
        # 모델에게 보이는 차례. 판정 순서(order)와 다르다 — 판정은 겹치는
        # 낱말 때문에 좁은 것부터 보지만, 소개는 큰 것부터 하는 것이 맞다.
        self.summary_order = summary_order or order
        self.limit = limit                 # 하지 않는 일 (LLM 도구 목록)
        self.llm_rule = llm_rule
        self.schema_extra = tuple(schema_extra)
        self.help_order = help_order or order
        self.help_pattern = help_pattern
        self.help = help
        self.example = example
        self.note = note
        # 되물을 수 있는 도구. 맥락이 부족하면 실행하지 않고 type=chat 으로
        # 묻는다. 점검이 '예시가 이 도구로 가는가' 를 볼 때 그 답도 정답으로
        # 인정해야 한다 — 되묻기는 실패가 아니다.
        self.asks_back = asks_back
        self.handler = None
        _TOOLS.append(self)

    def rule(self, fn):
        """규칙 본체를 붙이는 데코레이터. 서버가 가져올 때 붙는다."""
        self.handler = fn
        return fn

    def matches(self, low):
        return bool(self.trigger) and bool(re.search(self.trigger, low))

    def __repr__(self):                                     # pragma: no cover
        return "<Tool %s order=%d>" % (self.key, self.order)


# ══════════════════════════════════════════════════════════════
#  도구 목록
# ══════════════════════════════════════════════════════════════

# ── 태그 판정 전 (표기가 태그와 겹치는 것들) ────────────────
FEATURE_HELP = Tool(
    key="feature_help", label="기능 안내", order=10, returns="chat",
    before_tag=True,
    note="기능에 대한 질문은 명령이 아니다. 묻는 사람에게 답 대신 행동이 "
         "나가던 것을 여기서 끊는다 (패치 29b). 답은 각 도구의 help 를 "
         "읽어 만든다 — 도구 설명이 두 곳에 적히지 않도록.",
)

SMALLTALK = Tool(
    key="smalltalk", label="인사 응대", order=15, returns="chat",
    before_tag=True,
    note="인사에 예시 목록을 던지면 사람은 무시당했다고 느낀다. 매뉴얼 "
         "검색으로 넘겨서도 안 된다 — 근거가 없어 거절이 나간다.",
)

TERMINAL = Tool(
    key="terminal", label="단자 번호 역조회", order=20, returns="panel",
    tab="panel", actionable=True, before_tag=True,
    note="화면이 방금 보여준 단자 번호(IW512+)를 되물으면 답해야 한다 "
         "(패치 29c). 번호 표기가 태그 정규식과 겹쳐 태그 판정보다 먼저 본다.",
    llm_rule="단자 번호(IW512+ 같은 표기)로 어느 태그인지 물으면 "
             "type=panel 로 두고 tag 는 비워 두십시오 — 번호를 태그로 "
             "지어내지 마십시오.",
)

NAVIGATE = Tool(
    key="navigate", label="탭 이동", order=22, returns="navigate",
    actionable=True, before_tag=True,
    # 조회보다 먼저다. "알람 조회 탭으로 이동해줘" 가 알람 조회를 **실행**
    # 했다 (9/2 리허설 발견 6 계열). 판넬 규칙보다도 먼저 두는 이유는
    # "판넬 조회 탭 열어줘" 가 판넬 조회로 걸리기 때문이다 — 탭으로 가
    # 달라는 말과 조회해 달라는 말은 다르다.
    trigger=r"탭\s*(으로|에|를|을)?\s*"
            r"(이동|전환|바꿔|바꾸|열어|열기|가자|가줘|가 줘|넘어|띄워|보여)",
    summary_order=8,
    summary="탭 이동: 알람 조회·인터락 조회·판넬 조회·자료 반입 화면으로 "
            "옮깁니다. 조회를 실행하지는 않습니다.",
    llm_rule="화면(탭)으로 옮겨 달라는 말은 type=navigate 로 두고 tab 에 "
             "alarm|interlock|panel|ingest 중 하나를 채우십시오. 조회를 "
             "함께 실행하지 마십시오 — 옮기기만 하는 명령입니다.",
    schema_extra=("tab",),
    help_order=95,      # 기능 질문 안내에서는 맨 뒤 — '탭' 이 흔한 낱말이다
    help_pattern=r"탭\s*(이동|전환)",
    help="탭 이동은 화면만 옮깁니다. 조회는 실행하지 않습니다.\n"
         "예: 인터락 조회 탭으로 이동해줘 / 자료 반입 탭 열어줘",
    example="인터락 조회 탭으로 이동해줘",
)

PANEL = Tool(
    key="panel", label="판넬 조회", order=25, tab="panel",
    actionable=True, before_tag=True,
    note="판넬명(CUB-A)이 태그 표기와 겹쳐 태그 판정보다 먼저 본다.",
    summary_order=3,
    summary="판넬·배선 조회: 계기가 어느 판넬·카드·채널에 물려 있는지, "
            "같은 카드에 물린 다른 계기와 그 카드가 죽었을 때 영향을 받는 "
            "인터락을 보여줍니다.",
    llm_rule="판넬 위치·배선·카드를 물으면 type=panel.",
    help_order=25,
    help_pattern=r"판넬|카드\s*조회|배선",
    help="판넬 조회는 계기가 어디에 어떻게 물려 있는지를 봅니다.\n"
         "· 태그가 어느 판넬·어느 카드·몇 번 채널인지, 단자 번호까지\n"
         "· 같은 카드에 물린 다른 계기 — 카드 한 장이 죽으면 함께 우는 것들\n"
         "· 카드가 죽었을 때 영향을 받는 인터락 (의존 관계만, 트립 단정 없음)\n"
         "· 배치도에서 그 판넬의 위치\n"
         "화면 맨 아래 「동시 알람 조사」로 여러 태그의 공통 원인도 짚습니다.\n"
         "예: CUB-A 판넬 조회해줘 / AIT-4002 어느 판넬이야",
    example="CUB-A 판넬 조회해줘",
)

# ── 태그 판정 후 ────────────────────────────────────────────
HELP = Tool(
    key="help", label="사용법", order=30, actionable=True,
    trigger=r"^(도움|help|사용법|가이드)|^\?$",
    llm_rule="사용법을 물으면 type=help.",
    example="사용법 알려줘",
)

GRAPHIC_STOP = Tool(
    key="graphic_stop", label="시나리오 정지", order=35, returns="interlock",
    tab="interlock", actionable=True,
    # 인터락(75)보다 먼저다. '정지' 가 인터락 동작(STOP)과 겹쳐서, 인터락
    # 규칙이 먼저 걸리면 "시나리오 정지" 가 정지 인터락 조회로 샌다 (패치 33).
    trigger=r"(시나리오|시뮬레이션|재생|공정\s*화면)[^\n]*"
            r"(정지|멈춰|멈춤|중지|스톱|stop)"
            r"|(정지|멈춰|멈춤|중지)[^\n]*(시나리오|시뮬레이션|재생)",
    llm_rule="재생을 멈춰 달라는 말(정지·멈춰·중지)은 stopScenario=true, "
             "playScenario=false 로 두십시오. 여기서 '정지'는 시나리오 "
             "재생을 멈추라는 뜻이며, 펌프 정지 인터락 조회와 다릅니다. "
             "어느 쪽인지 분명하지 않으면 실행하지 말고 type=chat 으로 "
             "무엇을 원하는지 되물으십시오.",
    schema_extra=("stopScenario",),
    example="시나리오 정지해줘",
)

# 낱말만 남은 정지. 맥락을 보고 판정하며, 맥락이 없으면 되묻는다.
STOP_BARE = Tool(
    key="stop_bare", label="정지 (맥락 판정)", order=78, returns="interlock",
    tab="interlock", actionable=True,
    # **인터락 조회(75) 뒤**에 둔다. 순서가 이 도구의 절반이다 —
    # "P-5101A 정지 인터락 조회해줘" 는 인터락이 먼저 가져가야 하고,
    # 인터락이라는 낱말이 없는 "정지해줘" 만 여기로 내려와야 한다.
    #
    # 왜 생겼나 — 배포에서 시나리오를 재생한 뒤 「정지해줘」 라고만 하면
    # 알람 조회가 실행됐다. 패치 33 의 정지 규칙은 시나리오·시뮬레이션·
    # 재생·공정 화면 중 한 낱말을 **함께** 요구했고, 그 가드도
    # "시나리오 정지해주세요" 만 봤다. 낱말이 빠진 표현은 아무도 보지
    # 않았다 (패치 36).
    trigger=r"정지|멈춰|멈춤|멈출|중지|스톱|stop",
    llm_rule="'정지·멈춰·중지' 만 있고 무엇을 멈추라는 말이 없으면, 공정 "
             "화면에서 시나리오가 도는 중일 때만(user 줄의 scenario=playing) "
             "stopScenario=true 로 두십시오. 도는 중이 아니면 **실행하지 "
             "말고** type=chat 으로 시나리오를 멈출 것인지 정지 인터락을 "
             "조회할 것인지 되물으십시오.",
    example="정지해줘",
    # 맥락(시나리오가 도는 중)이 없으면 실행하지 않고 되묻는다.
    asks_back=True,
)

GRAPHIC = Tool(
    key="graphic", label="공정 화면", order=40, returns="interlock",
    tab="interlock", actionable=True,
    trigger=r"시나리오\s*재생|시뮬레이션.*(재생|가동|실행|열|보여)|공정\s*화면",
    summary_order=6,
    summary="공정 화면(P-5101A): 오프라인 모의 화면을 열고, 시나리오를 "
            "재생하거나 재생 중인 것을 멈춥니다. 실제 공정이 아닙니다.",
    llm_rule="공정 화면을 열어 달라면 type=interlock, tag=P-5101A, "
             "openGraphic=true 로 두십시오. 재생은 playScenario=true.",
    schema_extra=("openGraphic", "playScenario"),
    help_order=60,
    help_pattern=r"공정\s*화면|시뮬레이션|시나리오",
    help="공정 화면은 인터락 동작을 눈으로 보는 오프라인 모의 화면입니다.\n"
         "실제 공정과 연결되어 있지 않으며, 조건·세트포인트·지연 시간은 "
         "전부 인터락 리스트에서 읽은 값입니다.\n"
         "P-5101A 인터락 조회 화면에서 「펼치기」, 또는 "
         "\"시나리오 재생해줘\" 라고 말하면 됩니다.",
    example="시나리오 재생해줘",
)

INGEST = Tool(
    key="ingest", label="자료 반입", order=50, returns="chat",
    tab="ingest",
    trigger=r"자료\s*반입|반입|파일\s*(올리|넣|업로드)|업로드",
    summary_order=7,
    summary="자료 반입: 새 매뉴얼·리스트를 넣고 반입 직후 점검 리포트를 "
            "봅니다. 자료를 바꾸는 조작에는 열쇠가 필요합니다.",
    llm_rule="자료를 넣는 방법을 물으면 type=chat 으로 자료 반입 탭을 "
             "안내하십시오. 파일을 대신 올릴 수는 없습니다.",
    help_order=40,
    help_pattern=r"반입|업로드|파일\s*(올리|넣)",
    help="자료 반입은 새 매뉴얼·리스트를 넣는 화면입니다.\n"
         "· 올리면 즉시 점검 — 읽은 행 수, 표준 열, 매뉴얼-기종 연결, "
         "태그 맞물림\n"
         "· 「수리안」이 고칠 수 있는 것을 제안 — 자동은 정답이 계산되는 "
         "것만, 반영 전 이전 판 보존\n"
         "· 수정에는 열쇠가 필요합니다 (보기는 누구나)\n"
         "매뉴얼을 바꾸면 색인 재생성이 필요합니다.",
)

FOLLOWUP_REF = Tool(
    key="followup_ref", label="후속 질문 (가리키는 말)", order=55,
    returns="followup",
    trigger=r"(조회된|검색된|나온|방금|위의|이|그|저)\s*(내용|결과|것|거)"
            r"|결과를?\s*(보고|바탕|기반)|앞서|아까",
    note="화면에 결과가 떠 있는 상태의 후속 질문은 명령이 아니다. "
         "'조회' 라는 글자 때문에 같은 조회를 반복하며 대화가 제자리를 "
         "돌았다 (패치 29).",
    example="조회된 내용을 보고 조치방법을 알려줘",
)

FOLLOWUP_EXPLAIN = Tool(
    key="followup_explain", label="후속 질문 (설명 요청)", order=60,
    returns="followup",
    trigger=r"(설명|알려|해석|정리)\s*(해|해서|을|를)?\s*"
            r"(줄|주|달|부탁|가능|해)",
    note="가리키는 말이 없는 설명 요청도 후속 질문이다. 이것이 없으면 "
         "인터락을 조회한 뒤 '설명해줘' 가 직전 알람 근거로 답했다 (패치 29).",
)

DRAWING = Tool(
    key="drawing", label="도면 보기", order=65, tab="alarm",
    needs_tag=True, actionable=True,
    trigger=r"도면|p\s*&\s*i\s*d|pid|p&id",
    summary_order=4,
    summary="도면: 태그가 표시된 P&ID 위치와 배선 정보를 보여줍니다.",
    llm_rule="P&ID·도면을 보여 달라면 type=drawing.",
    help_order=50,
    help_pattern=r"도면|p\s*&\s*i\s*d|pid",
    help="도면 보기는 태그가 실린 P&ID·결선도·배치도를 엽니다.\n"
         "알람 조회 결과나 판넬 조회에서 바로 열 수 있고, "
         "챗봇으로도 됩니다. 예: AIT-1001 도면 보여줘",
    example="AIT-1001 P&ID 도면 보여줘",
)

INTERLOCK_SOURCE = Tool(
    key="interlock_source", label="인터락 원본", order=70, tab="interlock",
    needs_tag=True, actionable=True,
    trigger=r"인터락.*원본|원본.*인터락",
    llm_rule="리스트 원문을 보여 달라면 type=interlock_source, openSource=true.",
    schema_extra=("openSource", "action"),
    example="LCV-01 인터락 원본 보여줘",
)

INTERLOCK = Tool(
    key="interlock", label="인터락 조회", order=75, tab="interlock",
    needs_tag=True, actionable=True,
    trigger=r"인터락|interlock",
    summary_order=2,
    summary="인터락 조회: 밸브·펌프가 왜 안 움직이는지, 동작 조건을 "
            "인터락·퍼미시브·시퀀스로 나누어 보여주고 엑셀 원본과 "
            "대조합니다.",
    llm_rule="인터락 조건을 물으면 type=interlock. action 은 "
             "OPEN|CLOSE|START|STOP 중 하나입니다.",
    schema_extra=("action",),
    help_order=20,
    help_pattern=r"인터락|interlock",
    help="인터락 조회는 설비가 왜 멈췄는지(못 움직이는지)를 리스트에서 찾아 "
         "보여줍니다.\n"
         "· 동작(정지·기동 등)별 조건과 세트포인트, 지연 시간\n"
         "· 래치 여부 — 수동(MANUAL)은 사람이 리셋해야 풀립니다\n"
         "· 역방향 — 이 계기가 어느 설비를 세우는지\n"
         "· 「원본 보기」로 리스트 원문 대조\n"
         "예: P-5101A 인터락 조회해줘 / LIT-4003 이 걸린 인터락",
    example="XV-4101 인터락 조회해줘",
)

ADVICE = Tool(
    key="advice", label="조치 순서", order=80, returns="followup",
    llm_type="advice", tab="alarm", actionable=True, needs_tag=True,
    trigger=r"조치|어떻게\s*(해|하나|하면)|뭘\s*해|해결",
    summary_order=5,
    summary="조치 순서·4D 리포트: 조회된 근거로 점검 순서를 만들고 "
            "PDF 보고서로 출력합니다. 근거가 없는 단계는 만들지 않습니다.",
    llm_rule="조치 순서를 만들어 달라면 type=advice.",
    help_order=80,
    help_pattern=r"조치|4\s*d|리포트",
    help="조치 순서 생성은 조회된 근거로 점검 순서를 만듭니다 — 근거가 없는 "
         "단계는 만들지 않습니다.\n조치가 끝나면 실제 원인을 기록하고, "
         "그 기록은 다음 사람의 조회에 근거로 뜹니다.\n"
         "4D 리포트는 작업지시서에 첨부할 PDF 로, 근거가 없으면 "
         "\"매뉴얼 근거: 없음\" 이라고 적습니다.",
    note="조치 순서는 조회 결과가 있어야 만들 수 있다. 화면 상태를 아는 "
         "챗봇 계층에서 처리하도록 followup 으로 넘긴다.",
)

OUT_OF_SCOPE = Tool(
    key="out_of_scope", label="범위 밖 질문", order=57, returns="chat",
    # 알람 조회(90)보다 먼저다. 날짜·날씨 같은 질문이 매뉴얼 검색으로
    # 흘러 무관한 인용이 붙었다 (9/2 리허설 발견 6). 검색이 답을 못 찾는
    # 것이 아니라 **비슷한 문구를 찾아 붙이는** 것이 문제다.
    #
    # 설명 요청 후속 규칙(60)보다도 먼저다 — "오늘 날짜 알려줘" 의
    # '알려줘' 를 그쪽이 먼저 가져가 "먼저 조회하십시오" 로 끝난다.
    #
    # 이 도구가 끊는 것은 **도구가 알 수 없는 사실 질문**뿐이다. 날짜·
    # 시각·날씨·환율·뉴스는 등록된 자료에 없고, 모델이 답하면 지어낸
    # 값이 된다. 농담·노래 같은 요청은 여기서 끊지 않는다 — 그쪽은
    # 지어내도 사람이 속지 않으며, 자유 모드에서 모델이 사양하면 된다.
    trigger=r"(오늘|지금|현재|내일|어제)\s*(이?\s*)?(날짜|며칠|몇\s*시|요일|시각)"
            r"|며칠이(야|에요|예요)|몇\s*시(야|에요|예요|입니까)"
            r"|무슨\s*요일|날씨|기온|미세먼지|환율|주가|비트코인|뉴스|로또",
    limit="날짜·시각·날씨·환율·뉴스처럼 등록된 정비 자료에 없는 것은 "
          "알지 못합니다. 지어내지 않고 모른다고 답합니다.",
    llm_rule="날짜·시각·날씨·환율·뉴스 같은 도구 범위 밖 질문에는 "
             "매뉴얼을 뒤지지 말고 type=chat 으로 알지 못한다고 한 줄로 "
             "답하십시오. 지어내지 마십시오.",
)

DIAGNOSE = Tool(
    key="diagnose", label="알람 조회", order=90, tab="alarm",
    needs_tag=True, actionable=True,
    # 원래 조건이 두 갈래다 — 조회 낱말이 있거나, 태그와 함께 "해줘·
    # 보여" 가 있거나. 표현은 두 갈래를 합쳐 두고 갈래 판정은 규칙 본체가
    # 한다 (설명·재생 같은 낱말이 섞이면 조회가 아니다).
    trigger=r"알람|조회|검색|고장|해줘|보여",
    summary_order=1,
    summary="알람 조회: 설비 태그와 증상을 주면 벤더 매뉴얼과 에러코드표에서 "
            "원인·조치를 찾아 출처(문서·페이지)와 함께 보여줍니다. 증상은 "
            "한국어로 써도 되고 매뉴얼이 영문이어도 찾습니다. 보수 이력이 "
            "있으면 함께 보여줍니다.",
    limit="근거가 부족하면 답을 지어내지 않고 근거 부재를 알립니다.",
    llm_rule="알람·증상 검색은 type=diagnose 이며 alarm 에 증상을 담습니다.",
    schema_extra=("alarm",),
    help_order=30,
    help_pattern=r"알람\s*조회|알람\s*기능|진단",
    help="알람 조회는 태그와 증상으로 벤더 매뉴얼 근거를 찾아 옵니다.\n"
         "· 근거마다 문서명·페이지 — 원문 보기로 확인\n"
         "· 현장 조치 이력이 있으면 함께, 매뉴얼과 다르면 경고\n"
         "· 근거가 부족하면 답하지 않고 거절(ABSTAIN)합니다\n"
         "· 조치 순서 생성 → 결과 기록 → 4D 리포트로 이어집니다\n"
         "예: AIT-4002 loop error 알람 조회해줘",
    example="AIT-4002 acid residual low 알람 조회해줘",
)

GENERIC = Tool(
    key="generic", label="포괄 응답", order=99, returns="chat",
    note="아무 규칙에도 걸리지 않은 것. generic 표식을 달아 챗봇 계층이 "
         "LLM 답을 덮지 않게 한다.",
)

# 도구가 아니라 모드 설명. 기능 질문에만 답한다.
MODE_HELP = Tool(
    key="mode", label="근거 모드·자유 모드", order=0, returns="chat",
    help_order=70,
    help_pattern=r"자유\s*모드|근거\s*모드|모드",
    help="근거 모드(기본)는 등록된 문서에 있는 것만 답하고, 없으면 없다고 "
         "합니다.\n자유 모드는 근거가 없어도 모델의 일반 지식으로 답하되 "
         "「추측」 라벨이 붙고 화면 테두리가 주황색이 됩니다.\n"
         "추측은 조치 순서·4D 리포트·이력에 섞이지 않습니다. "
         "조회 명령의 결과는 모드와 무관하게 같습니다.",
)


# ══════════════════════════════════════════════════════════════
#  읽는 쪽
# ══════════════════════════════════════════════════════════════
def all_tools():
    return list(_TOOLS)


def by_key(key):
    for t in _TOOLS:
        if t.key == key:
            return t
    raise KeyError("등록되지 않은 도구: %s" % key)


def ordered(before_tag=None):
    """규칙 판정 순서. before_tag 로 태그 판정 전후를 가른다."""
    got = [t for t in _TOOLS if t.handler]
    if before_tag is not None:
        got = [t for t in got if t.before_tag == before_tag]
    return sorted(got, key=lambda t: t.order)


def actionable_types():
    """화면이 실행하는 명령 type. 챗봇이 이 목록으로 실행 여부를 가른다."""
    return {t.llm_type for t in _TOOLS if t.actionable}


def needs_tag_types():
    return {t.llm_type for t in _TOOLS if t.needs_tag}


def feature_help(low):
    """기능 질문에 대한 안내. 도구 설명은 각 항목의 help 하나뿐이다."""
    for t in sorted([x for x in _TOOLS if x.help_pattern and x.help],
                    key=lambda x: x.help_order):
        if re.search(t.help_pattern, low):
            return t.help
    return None


# 탭 하나에 대응하는 도구. 탭 이동이 고를 수 있는 것이 곧 이 목록이다 —
# 화면 이름을 따로 적어 두면 도구가 늘 때 그 목록만 낡는다.
TAB_TOOLS = ("diagnose", "interlock", "panel", "ingest")


def tab_targets():
    """(탭, 이름, 그 탭을 가리키는 표현). 표현은 각 도구의 기능 질문
    표현을 그대로 쓴다 — 같은 낱말을 두 번 적지 않는다."""
    out = []
    for k in TAB_TOOLS:
        t = by_key(k)
        if t.tab and t.help_pattern:
            out.append((t.tab, t.label, t.help_pattern))
    return out


def examples(keys=("diagnose", "interlock", "panel", "drawing")):
    """예시 줄. 안내문마다 예시를 따로 적지 않기 위해 여기서 가져간다."""
    out = []
    for k in keys:
        t = by_key(k)
        if t.example:
            out.append(t.example)
    return out


# ── LLM 명령 해석 스키마 ────────────────────────────────────
#
# 스키마도 **같은 목록을 읽는다.** 도구를 늘리면 모델이 고를 수 있는 것도
# 같이 늘어난다. 패치 33 은 정확히 이것이 어긋나서 났다.
_SCHEMA_BASE = ('"type"', '"tag"', '"reply"')


def llm_tool_block():
    """모델에게 주는 '할 수 있는 일' 목록."""
    lines = []
    for t in sorted(_TOOLS, key=lambda x: x.summary_order):
        if t.summary:
            lines.append("- " + t.summary)
    for t in sorted(_TOOLS, key=lambda x: x.order):
        if t.limit:
            lines.append("- " + t.limit)
    return "\n".join(lines)


def llm_schema_line():
    types = sorted(actionable_types() | {"chat"})
    tabs = sorted({t.tab for t in _TOOLS if t.tab})
    extra = []
    for t in sorted(_TOOLS, key=lambda x: x.order):
        for f in t.schema_extra:
            if f not in extra:
                extra.append(f)
    fields = ['"type":"%s"' % "|".join(types),
              '"tag":"AIT-4002 or null"']
    for f in extra:
        if f == "tab":
            fields.append('"tab":"%s or null"' % "|".join(tabs))
        elif f == "alarm":
            fields.append('"alarm":"symptom text or null"')
        elif f == "action":
            fields.append('"action":"OPEN|CLOSE|START|STOP or null"')
        else:
            fields.append('"%s":false' % f)
    fields.append('"reply":"short Korean confirmation"')
    return "{" + ",".join(fields) + "}"


def llm_rule_block():
    lines = []
    for t in sorted(_TOOLS, key=lambda x: x.order):
        if t.llm_rule:
            lines.append(t.llm_rule)
    return " ".join(lines)


# ── 등록 점검 ───────────────────────────────────────────────
def check():
    """빠뜨린 자리를 가져오기 시점에 잡는다.

    한 곳만 적고 나머지를 잊는 것이 패치 33 의 원인이었다. 그러니 잊으면
    **띄우고 죽는다.** 조용히 반쪽으로 도는 것보다 낫다.
    """
    bad = []
    keys = [t.key for t in _TOOLS]
    for k in set(keys):
        if keys.count(k) > 1:
            bad.append("%s: 같은 key 가 %d번" % (k, keys.count(k)))
    for t in _TOOLS:
        if t.trigger and not t.handler:
            bad.append("%s: 표현(trigger)은 있는데 규칙 본체가 없습니다" % t.key)
        if t.actionable and not t.returns:
            bad.append("%s: 실행 명령인데 type 이 없습니다" % t.key)
        if t.help_pattern and not t.help:
            bad.append("%s: 기능 질문 표현만 있고 안내문이 없습니다" % t.key)
        if t.actionable and not (t.llm_rule or t.summary):
            # 스키마에 안 실리면 모델은 그 도구를 **고를 수 없다**.
            # 규칙이 아는 표현만 되고 나머지는 엉뚱한 곳으로 간다.
            bad.append("%s: 실행 명령인데 LLM 스키마 설명이 없습니다" % t.key)
    if bad:
        raise RuntimeError("도구 목록이 반쪽입니다 — " + " / ".join(bad))
    return True
