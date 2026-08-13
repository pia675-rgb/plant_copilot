# 패치 19-11 — 업로드 가능한 자료에 맞춰 정리

패치 19-10 위에 덮으십시오.

```
retrieval/panel_index.py   fault_effect · fault_direction 제거
api/server.py              /api/fault-effect 제거, 챗봇 고장 의도 제거
eval/make_eval_panel.py    fault 문항 24개 제거 (204 → 180)
eval/run_eval_panel.py     fault 채점기·변이 no-direction 제거
data/make_io_list.py       부속 데이터에서 FAULT MODE·ALARM·TERMINAL 제거
config.py                  TB_LIST 경로 추가
```

## 넣으실 수 있는 자료 9종을 기준으로 다시 맞췄습니다

```
Instrument List · IO List · TB List · Interlock List · Manual
P&ID · Panel outline · Panel schematic · Panel arrangement 도면
```

## 1. 계기 단품 고장 판정 기능을 제거했습니다

`fault_effect()` 는 계기가 고장 났을 때 Upscale / Downscale 방향으로
어떤 인터락 조건이 성립하는지 판정했습니다. 이 판정은 `FAULT MODE`
열에 **전적으로** 의존했는데, 실물 Instrument List 에 그 열이 없습니다.

관행(4-20mA 는 NAMUR Downscale)으로 가정할 수도 있었지만, 그러면
**리스트에 없는 값을 근거로 인터락 성립을 판정**하게 됩니다. 이 프로젝트가
지켜온 원칙과 어긋나므로 기능째 뺐습니다.

없어진 것: 조회 함수, `/api/fault-effect`, 챗봇의 "…고장나면?" 의도,
평가 문항 24개, 변이 시험 `no-direction`.

계기 사양서를 받을 수 있게 되면 되살릴 수 있도록 제거 사유를 코드에
남겨 두었습니다.

## 2. 부속 데이터가 줄었습니다

```
전   SYSTEM · LOOP GROUP · FAULT MODE · TERMINAL · ALARM L/H
     MANUAL FILE · TYPE · FAIL POSITION · DRIVE
후   SYSTEM · LOOP GROUP · MANUAL FILE · TYPE · FAIL POSITION · DRIVE
```

| 항목 | 처리 |
|---|---|
| FAULT MODE | 기능 제거로 불필요 |
| ALARM L / H | 업로드 문서에 없음 — 표시 제외, SCALE RANGE 만 사용 |
| TERMINAL | **TB List 에서 받음** (config.TB_LIST 추가) |

`MANUAL FILE` 은 앞으로 Instrument List 의 `MAKER`·`MODEL` 과 매뉴얼
파일명을 대조해 도구가 자동으로 잇게 할 예정입니다. 지금은 부속 데이터에
남아 있습니다.

## 3. 정비 이력

조치 이력을 작성하면 자동으로 쌓이는 구조라고 하셨으므로, 별도 업로드
자료로 두지 않습니다. 지금 `/api/feedback` 이 그 역할을 하고 있고
`maintenance_history` 에 누적됩니다. 초기 이력이 비어 있어도 동작하며,
쓸수록 "매뉴얼 근거 ↔ 현장 이력" 2단 대조가 채워집니다.

## 평가 204 → 180문항

```
locate 76 · card 33 · cscope 33 · cdepend 17 · common 1
place 5 · roster 5 · absent 10          전체 180/180
```

| 변이 | 전체 | 무너진 항목 |
|---|---|---|
| no-location | 175/180 | place 0/5 |
| no-logic | 171/180 | cdepend 8/17 |
| no-card-split | 20/180 | locate·card·cscope·cdepend·common 전멸 |

## 다음 — TB List 양식이 필요합니다

mastertool 형태라고 하셨는데, mastertool 의 TB 리스트는 **격자 배치
결선표**(판넬 폭에 맞춰 TB 블록을 행×열로 배치)라 평면 표가 아닙니다.
태그 → 단자번호를 어떻게 읽을지가 양식에 달려 있습니다.

**샘플 파일을 하나 주시면** 그 구조에 맞춰 리더를 만들겠습니다. 지금까지
양식을 제 기억으로 재구성했다가 두 번 틀렸으므로, 실물을 보고 만드는
편이 확실합니다. ET200M 용과 ET200SP HA 용이 다르면 둘 다 필요합니다.

## 함께 정할 것

`data/` 한 곳으로 자료를 모으는 폴더 구조입니다. 지금은 매뉴얼·도면이
v1 폴더에 있어 넣을 곳이 두 군데로 갈려 있습니다.

```
data/
  INSTRUMENT_LIST.xlsx · IO_LIST.xlsx · TB_LIST.xlsx · INTERLOCK_LIST.xlsx
  manuals/    *.pdf
  drawings/   P&ID · OUTLINE · SCHEMATIC · ARRANGEMENT
```

여기 넣기만 하면 도면 색인·매뉴얼 연결·판넬 위치는 도구가 만들도록
할 예정입니다. 진행해도 될지 알려주십시오.
