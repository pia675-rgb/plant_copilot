# 패치 19-10 — 계기 리스트를 실물 양식으로

패치 19-9 위에 덮으십시오.

```
data/make_io_list.py         계기 리스트를 실물 양식(2단 머리)으로 생성
data/INSTRUMENT_LIST.xlsx    16항목 23열, 배선 열 없음
data/TAG_ATTRIBUTES.xlsx     (신규) copilot 부속 데이터 — 산출물 아님
config.py                    TAG_ATTRIBUTES 경로
ingest/lists.py              2단 머리 리더 + 세 문서 TAG 조인
ingest/tag_registry.py       교차 대조도 실물 양식으로 읽음
retrieval/interlock_index.py 출력 사양을 조인 층에서 받음 (엑셀 직접 읽기 제거)
api/server.py                출력 태그 로더 동일
eval/selfcheck.py            계기 리스트 실물 양식 [주입] (30 → 31)
```

## 제가 만든 계기 리스트는 형태부터 틀렸습니다

18열 평면 양식으로 임의로 만들었는데, 실물은 **2단 머리**입니다.

```
TAG NO. │ DESCRIPTION │ Q'TY │ SENSOR TYPE │ MATERIAL  │ SCALE RANGE   │ …
        │             │      │             │ ELEM│BODY │ MIN│MAX│UNIT  │
… │ DISPLAY │ POWER │ OUTPUT SIGNAL │ CONNECTION      │ LINE      │ FLUID
  │         │       │               │ TYPE│SIZE│MAT'L │ SIZE│MAT'L│ NAME│COND
… │ MODEL │ MAKER │ LOCATION │ REMARKS
```

16항목 23열입니다. 그리고 말씀하신 대로 **랙·슬롯·채널은 여기 없습니다** —
IO List 에서 TAG 로 받아갑니다.

## 원천에 없는 열은 비웠습니다

데모 원천에서 채울 수 있는 것은 아홉 개뿐입니다.

```
채움   TAG NO. · DESCRIPTION · SENSOR TYPE · SCALE RANGE(MIN/MAX/UNIT)
       OUTPUT SIGNAL · MODEL · MAKER · REMARKS
비움   Q'TY · MATERIAL(ELEMENT/BODY) · DISPLAY · POWER
       CONNECTION(TYPE/SIZE/MATERIAL) · LINE(SIZE/MATERIAL)
       FLUID(NAME/CONDITION) · LOCATION
```

지어 넣지 않았습니다. 실물로 갈아 끼울 때 채워야 할 칸이 그대로
드러납니다.

## ★ 부속 데이터를 세 번째 파일로 뺐습니다

copilot 이 쓰는데 **실물 계기 리스트에도 IO List 에도 없는** 항목이
있습니다. 지난번처럼 실물 양식 뒤에 확장 열로 붙이면 그 양식이 다시
실물과 달라집니다.

`data/TAG_ATTRIBUTES.xlsx` — **프로젝트 산출물이 아닙니다.** SOURCE
시트에 각 항목이 실제로 어느 문서에서 와야 하는지 적어 두었습니다.

| 항목 | 쓰이는 곳 | 실제로 있는 문서 |
|---|---|---|
| FAULT MODE | 단품 고장 방향 판정 | 계기 사양서 / 설정 시트 |
| TERMINAL | OUTLINE 도면 단자대 하이라이트 | TB 리스트 (mastertool 생성) |
| ALARM L / H | 알람 임계 표시 | 알람 설정 리스트 |
| MANUAL FILE | 매뉴얼 검색 연결 | 문서 관리대장 |
| TYPE · FAIL POSITION · DRIVE | 인터락 출력 사양 | 밸브·구동기 리스트 |
| SYSTEM · LOOP GROUP | 카드 상실 시 계통 집계 | (확인 필요) |

**여쭤볼 것이 있습니다.** 이 매핑이 맞는지, 특히 `TERMINAL` 과
`FAULT MODE` 를 실제로 어느 문서에서 받아오시는지 알려주시면 그
문서 양식으로 옮기겠습니다.

## 조인은 세 문서로

`ingest/lists.py` 한 곳에서 TAG 로 합칩니다. 읽는 쪽 세 군데
(`panel_index` · `api/server` · `retrieval/pipeline`)는 그것만 부릅니다.

```
배선은 IO List 가 원본 — 계기 리스트가 덮어쓰지 않는다
계기 리스트는 2단 머리 — 전용 리더로 읽는다
부속 데이터는 마지막에 빈 칸만 채운다
```

## 작업 중 제가 낸 고장 둘

**하나.** `retrieval/interlock_index.py` 의 `load_outputs` 가 엑셀을
직접 읽고 있어서, 계기 리스트 양식이 바뀌자 `StopIteration` 으로
죽었습니다. 인터락 인덱스가 통째로 안 뜨면서 selfcheck 13건이
한꺼번에 실패했습니다. 조인 층을 부르도록 고쳤습니다 — 엑셀을 직접
읽는 곳이 남아 있으면 양식이 바뀔 때마다 같은 일이 납니다.

**둘.** 출력 태그 로더를 교체하면서 바로 뒤에 있던 `load_drawings`
함수를 같이 지웠습니다. 계기 상세의 도면 목록이 통째로 죽었습니다.
복구했습니다.

둘 다 **점검기가 먼저 잡았습니다.**

## selfcheck 30 → 31

```
계기 리스트 실물 양식 [주입]   2단 머리 16항목이 그대로인가
                             배선 열(RACK·SLOT·CH·PANEL)이 섞이지 않았는가
                             2단 머리 해석으로 행이 읽히는가
```

## 확인 결과

| 항목 | 결과 |
|---|---|
| 계기 리스트 | 실물 양식 16항목 / 100행, 배선 열 없음 |
| IO List | 표준 24종만, 100점 |
| 판넬·카드 평가 | 204/204 |
| 인터락 평가 | 72/72 |
| 교차 정합성 | 6건 (변동 없음) |
| 전 모듈 임포트 27개 | 실패 없음 |
| 계기 상세·도면·매뉴얼 연결 | 정상 |

## 적용

```cmd
python data\make_arrangement.py
python data\make_io_list.py
python -m eval.make_eval_panel
run_check.bat
```

`run_check.bat` 으로 돌리십시오. 맨 프롬프트에서 `python -m eval.selfcheck`
를 돌리면 환경변수가 없어 azure 로 떨어지고, 서버와 다른 환경을
측정하게 됩니다.
