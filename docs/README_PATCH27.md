# 패치 27 — SCADA 알람 어휘와 카드 진단

## 문제

SCADA가 실제로 보내는 알람은 HH / LL / LOOP ERROR / ON·OFF COMMAND와
Siemens SSL 진단 코드뿐인데, 이 어휘가 매뉴얼에 **없습니다**. 색인 전수
검색 실측: "loop error" 0건 · "high high" 0건 · "low low" 0건. 알람은
상태를 말하고 매뉴얼은 절차를 말하기 때문입니다. 그 결과 네 가지가
무너져 있었습니다.

1. `LOOP ERROR`로 물으면 거절되거나, M9e의 "DI Loop"(수처리 배관 —
   같은 단어, 다른 뜻) 절이 올라왔습니다.
2. SSL 코드(`11H`, `8H`, `1FH` …)는 조회 자체가 안 됐습니다 —
   `exact_code`의 정규식이 십진 숫자만 잡았습니다.
3. 카드가 죽어 5점이 동시에 LOOP ERROR를 내면, 개별 태그 조회는 다섯 번
   다 오답입니다. 진짜 원인(카드 1장)을 가리키는 경로가 없었습니다.
4. 데모 IO List에 같은 카드·같은 채널을 쓰는 점이 7건 있었습니다 —
   실물이라면 배선이 불가능한 데이터입니다.

## 무엇을 바꿨나

### 1. SSL 16진 코드 조회 (`retrieval/bm25.py`)

`exact_code`에 `\b[0-9][0-9A-Fa-f]{0,3}[Hh]\b` 패턴을 추가했습니다.
카드 진단 코드 24종 전부 조회됩니다(5H/8H/11H/1FH/10EH/105H 확인).

함정이 하나 있었습니다 — 태그 `AIT-4002`의 숫자부 `4002`가 코드 `4002`로
오인됐습니다. 태그 패턴을 먼저 제거한 뒤 코드를 추출합니다.

### 2. 알람 라우팅 (`retrieval/alarm_rules.py` 신규)

`classify(query)`가 알람 5종(HH/LL/LOOP/CMD/SSL)을 식별하고 확장어를
돌려줍니다. 확장어는 평가셋이 아니라 **카드 진단표·트러블슈팅 표제어**에서
왔습니다(LOOP: wire break, supply voltage missing, will not power on,
fuse, underrange, 4-20 mA). LOOP·SSL은 `card_primary=True`.

핵심 한 가지: 확장 시 **알람명 자체는 검색어에서 뺍니다**. "loop"는 M9e
에서 수처리 배관(DI Loop)을 뜻하는 가짜 친구(false friend)라, 남겨 두면
엉뚱한 절이 올라옵니다. 원문은 `exact_code` 경로에만 씁니다.

**첫 배포 시험에서 잡힌 구멍 하나(27b)**: 판별이 대문자 원문만 봐서
소문자 `loop error`가 라우팅을 비껴갔습니다 — 화면에는 충분성 1.00으로
System Error 공통 설명과 DI loop 절이 올라왔습니다. 자신 있게 어긋난,
정확히 패치 전 증상입니다. SCADA는 대문자로 보내지만 사람은 소문자로
칩니다. 구문형(loop error / high high / low low / on·off command)은
대소문자 무시로 넓히고, 오인 여지가 있는 축약형 `HH`/`LL`만 대문자를
유지했습니다. 넓힌 뒤 평가 448문항 발화 0건·lexical 16/45 재확인.

### 3. 파이프라인·채점 연결 (`pipeline.py`, `graph/nodes.py`)

- `retrieve()`가 라우팅을 통합하고 `last_route`/`last_query`를 노출합니다.
- `_cap_card`: `card_primary`면 카드 청크 상한을 풀되, 확보창 안에 계기
  근거 1건을 보장합니다(밀려나는 자리는 카드 본문만, error_code 보호).
- 채점 질의를 **실제 검색어**로 바꿨습니다. 전에는 "LOOP ERROR" 원문으로
  적중률을 재서, 확장 검색이 정답을 찾아와도 거절했습니다 — 정답을 찾고도
  버리는 구조였습니다.
- trace에 `alarm-route:` 줄이 1회 남습니다(첫 시도에만). 화면에서 확장
  근거를 그대로 보여주기 위함입니다.

### 4. 알람 폭주 역추적 (`retrieval/panel_index.py`, `api/server.py`)

- `siblings(tag)`: 같은 카드 동반 태그. diagnose 응답에 `card_siblings`
  필드로 실리고, 4D PDF의 D2에 "※ 동일 카드(…) 동반 태그: … — 동시 알람 시
  카드 공통 원인 우선 점검" 한 줄이 붙습니다.
- `common_cause_of(tags)`: 동시 알람 태그들의 공통 조상을 4계층으로
  판정합니다 — card → rack → panel → plc → scattered. 같은 카드인데
  알람이 안 뜬 동반 태그는 `uncovered`(반례), 색인에 없는 태그는
  `unknown`으로 **분리**합니다. 모른다와 반례는 다른 것입니다.
- 신규 `GET /api/common-cause-of?tags=쉼표구분`. UI 화면은 없습니다
  (dist 미수정) — API·PDF로 노출.

### 5. 4D 리포트 정직성 (`api/report_4d.py`)

매뉴얼 근거가 없는 조회에서 D3가 조용히 비는 대신
"• 매뉴얼 근거: 없음 — …(이력 기준으로 판단)"을 명시합니다.
근거가 없으면 없다고 쓰는 것이 이 도구의 원칙입니다.

### 6. 데모 IO List 채널 중복 수정 (`demo_data/IO_LIST.xlsx`)

중복 7건을 같은 슬롯의 빈 채널로 재배정했습니다(잔존 0). 수정 스크립트
1차본에 `str(value or '')`가 **CH=0을 삼키는 버그**가 있었습니다 —
0번 채널은 falsy라 빈 값으로 취급됐습니다. 정정했습니다.

### 7. 자기 점검 가드 4종 (`eval/selfcheck.py`)

- `c_ssl_code_lookup` — 16진 코드 조회가 다시 죽으면 잡습니다.
- `c_alarm_rules_inert` — **평가 448문항에서 라우팅이 발화하면 실패**.
  알람 라우팅이 평가셋을 오염시키지 않는다는 것을 상시 감시합니다.
- `c_io_channel_unique` — 채널 중복 재발 감시.
- `c_flood_reverse` — 역추적 4계층 판정 회귀 감시.

## 측정

| 항목 | 결과 |
|---|---|
| 45문항 lexical | **16/45 — 기준선 그대로** (sc_demo.md와 동일, 회귀 없음) |
| **45문항 hybrid (데모 세트)** | **28/45 — 기준선 유지** (code 4/4 · wrongdev 3/3 · 과잉거절 없음 39/39) |
| **홀드아웃** | **2/10 — 기준선 유지** |
| **인터락** | **67/67 — 전건 통과** |
| exact_code 평가 448문항 | 변화 **0건** |
| alarm_rules 평가 448문항 발화 | **0건** (평가셋 오염 없음) |
| `AIT-4002 LOOP ERROR` (lexical) | abstain → **advise 0.53**, p.274 도달, siblings 4건 |
| `no power` (lexical) | **advise 0.60**, p.274 1위 |
| `11H` | exact — ET200SP Supply voltage missing |
| 폭주 5태그 역추적 | level=**card**, RIO-01/DP11/R0/S8 |
| selfcheck --skip-llm | 신규 4종 포함 통과. 임베딩 키 없는 창에서는 dense 강등 계열 3건 실패가 **정상**(사유가 health에 실림) |

**재측정 완료 (2026-08-27, `run_eval_demo.bat` / ollama·bge-m3)**: 45문항
hybrid 28/45 · 홀드아웃 2/10 · 인터락 67/67 — **전부 기준선 유지, 회귀 0**.

수치가 오르지 않은 것도 설계대로입니다. 45문항은 자연어 질의 세트라
SCADA 알람 어휘가 등장하지 않고(라우팅 발화 0건), 패치 27이 고친 것은
평가셋에 없는 **입력 경로**입니다. 올랐다면 오히려 평가셋 오염을
의심해야 했습니다. 알람 경로의 개선은 시나리오 문서의 실측
(`docs/SCENARIO_SCADA.md`)으로 따로 보고합니다.

## 정정 2건 (기록)

1. 앞선 대화에서 `COPILOT_DIVERSIFY`를 켜자고 제안했으나 **철회**합니다.
   이미 측정으로 기각된 설정입니다(off 33/45 > kind 29 > all 27,
   `c_diversify_off` 가드 존재). 알람 라우팅은 전역 재정렬이 아니라 알람
   유형에만 발화하는 규칙층이라 이 기각과 충돌하지 않습니다(발화 0건 실측).
2. "기기 필터가 카드 코드를 막는다"는 진단은 **틀렸습니다** —
   `_match_device`는 카드 device를 항상 통과시킵니다. 실제 결함은
   정규식뿐이었습니다.

## 적용

서버 파일만 바뀌었습니다 — **재시작만, 빌드 불필요**. 변경 파일:
`retrieval/bm25.py` · `retrieval/alarm_rules.py`(신규) ·
`retrieval/pipeline.py` · `retrieval/panel_index.py` · `graph/nodes.py` ·
`api/server.py` · `api/report_4d.py` · `eval/selfcheck.py` ·
`demo_data/IO_LIST.xlsx` · `docs/SCENARIO_SCADA.md`(신규)
