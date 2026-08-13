# 패치 19-5 — mastertool / MAXIS 표준 24종으로 IO List 통일

패치 19-4 위에 덮으십시오.

```
data/make_io_list.py       표준 24종 + 확장 열 형태로 전면 교체
data/IO_LIST.xlsx          재생성 (24 + 14 = 38열)
retrieval/panel_index.py   표준 열 별칭 · 카드 식별에 PN(DP) 반영
api/server.py              계기 로더 별칭 (SERVICE ← DESCRIPTION)
retrieval/pipeline.py      같은 별칭
eval/make_eval_panel.py    카드 규칙에 스테이션 반영 (203 → 204문항)
eval/selfcheck.py          IO List 표준 헤더 [주입] 추가 (26 → 27)
```

## ★ 5번 열은 PN(DP) 입니다

주신 목록의 5번 `DP(PN)` 은 **구 표기**입니다. 업로드해주신
`io_tools_core.py` 를 직접 읽어 확인했습니다.

```python
STANDARD_ORDER = ["INDEX", "PLC", "PANEL", "LOCATION", "PN(DP)", ...]

STD_ALIASES = {
    ...
    "dp(pn)": "PN(DP)",   # 구 표기 하위 호환
}
```

MAXIS 는 별칭으로 받아주지만, 완전일치 전용 매핑으로 전환하신 뒤로는
헤더를 구 표기로 쓰면 **자동 매핑에서 빠집니다.** `PN(DP)` 로
맞췄습니다.

표준 24종은 여기서 다시 정의하지 않고 `io_tools_core.STANDARD_ORDER`
목록을 그대로 복사해 씁니다. 정의는 계속 그쪽 한 곳에 있습니다.

## 확장 열을 뒤에 붙였습니다

copilot 이 쓰는데 24종에 없는 정보가 있습니다.

| 확장 열 | 쓰이는 곳 |
|---|---|
| FAULT MODE | 계기 단품 고장 방향 판정 |
| TERMINAL | OUTLINE 도면 단자대 하이라이트 |
| SYSTEM | 카드 상실 시 시스템별 분산 집계 |
| MANUAL FILE / MAKER / MODEL | 매뉴얼 검색 연결 |
| ALARM L / H · RANGE | 알람 임계 표시 |
| SIGNAL · MEAS TYPE · LOOP GROUP · POINT TYPE | 신호 형식·계통 |

24종만 쓰면 이 기능들이 조용히 빈칸을 읽습니다. **1~24열은 표준 그대로,
25열부터 확장**(파란 머리)으로 붙였습니다. mastertool·MAXIS 는 자기
24종만 읽으므로 무해합니다.

`SERVICE` 는 표준에 없고 `DESCRIPTION` 이 그 자리입니다. 열 이름을 바꾸지
않고 **읽는 쪽에 별칭 층**을 뒀습니다 (`panel_index` · `api/server` ·
`retrieval/pipeline` 세 곳). 이쪽 코드 이름을 표준에 밀어 넣지 않으려는
것입니다.

## 채우지 않은 열

`ADD · PRG · PG · BIT · BYTE · SIGNAL TYPE1/2 · POWER SOURCE ·
INST. PANEL · P&ID TAG` 는 데모 원천에 없어 **비웠습니다.**
그럴듯한 값을 지어 넣으면 나중에 실물과 구분되지 않습니다. MAXIS
`validate_io_list` 에 넣으면 ADD 가 '필수값 누락' 으로 잡히는데, 그게
정상 동작입니다.

`IO TYPE` 은 `AI` 까지만 적었습니다. 표준 표기는 `AI-8` 처럼 채널 수를
포함하지만 원천에 카드 채널 수가 없어 채널 수는 붙이지 않았습니다.

## PN(DP) 로 카드가 유일해졌습니다

```
중앙 큐비클   CUB-A/R0/S1     PN(DP) 공란, RACK 으로 구분
원격 스테이션 RIO-01/DP11/R0/S3
```

`(PLC, PN(DP), RACK, SLOT)` 충돌 0건입니다. 판넬을 앞에 남긴 것은 사람이
읽기 위해서고, 유일성은 뒤쪽 세 값이 만듭니다.

`LOCATION` 열에는 배치도가 만든 판넬 위치(`ELECTRICAL ROOM / B5`)가
들어갑니다.

**PN(DP)·RACK 값은 여전히 가정입니다.** 원천 RACK 이 전 행 0 이라
`STATION_MAP` 으로 부여했습니다. 실제 번호를 알려주시면 그 표 한 곳만
고치면 되고, 조회·평가·도면이 전부 따라옵니다.

## selfcheck 26 → 27

```
IO List 표준 헤더 [주입]   1~24열이 STANDARD_ORDER 와 정확히 같은가
                          확장 열에 모르는 이름이 섞이지 않았는가
```

구 표기로 바꿔 검출되는 것을 확인했습니다.

```
5번 열이 표준과 다릅니다: 'DP(PN)' ≠ 'PN(DP)' — 완전일치 매핑에서 빗나갑니다
```

`공통원인 점검 [주입]` 도 손봤습니다. 카드 식별에 PN(DP) 가 들어가면서
주입이 배선 열을 하나 빠뜨려 성립하지 않았는데, 검사는 통과한 것처럼
보였습니다. 배선 4열(PANEL·PN(DP)·RACK·SLOT)을 함께 옮기도록 고쳤습니다.
**점검기 자신이 이번 변경에서 먼저 깨져서 잡혔습니다.**

## 확인 결과

| 항목 | 결과 |
|---|---|
| 판넬·카드 평가 | 204/204 |
| 변이 시험 4종 | 모두 의도대로 무너짐 (no-card-split 44/204) |
| 인터락 평가 | 72/72 |
| 공통원인 점검 | 지적 2건 유지 |
| 표준 헤더 대조 | 24종 일치 / 확장 14종 |
| 스테이션·랙 유일성 | 카드 33장 모두 유일 |
| 전 모듈 임포트 25개 | 실패 없음 |
| 계기 상세·매뉴얼 연결 | SERVICE·MAKER·FAULT MODE 정상 |

## 적용

```cmd
python data\make_arrangement.py
python data\make_io_list.py
python -m eval.make_eval_panel
python -m eval.run_eval_panel --mutate --md eval\scorecard_panel.md
python -m eval.selfcheck --skip-llm
```

배치도를 먼저 만들어야 `LOCATION` 열이 채워집니다.

## 확인 부탁드릴 것

`STATION_MAP` 의 PN(DP)·RACK 값입니다. 중앙 큐비클은 PN(DP) 를 비우고
RACK 0/1/2 로, 원격은 PN(DP) 11/12 로 두었습니다. ET200SP HA 가 판넬당
랙 2개라고 하셨으니 실물에서는 한 판넬이 랙 두 개로 갈릴 텐데, 그 번호
규칙을 알려주시면 그대로 맞추겠습니다.
