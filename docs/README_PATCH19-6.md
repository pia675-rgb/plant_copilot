# 패치 19-6 — IO List 는 표준 24종만, 계기 사양은 별도 문서로

패치 19-5 위에 덮으십시오.

```
data/make_io_list.py        IO List + 계기 리스트 두 문서 생성
data/IO_LIST.xlsx           표준 24종만 (확장 열 제거)
data/INSTRUMENT_LIST.xlsx   (신규) 계기 사양 18열
ingest/lists.py             (신규) 두 문서 TAG 조인 — 유일한 조인 지점
config.py                   INSTRUMENT_SPEC 경로
retrieval/panel_index.py    조인 사용 (자체 로더 제거)
api/server.py               조인 사용 (자체 로더 제거)
retrieval/pipeline.py       조인 사용 (자체 로더 제거)
eval/selfcheck.py           헤더·원천 대조 검사를 두 문서 기준으로
```

## 잘못 만든 것을 되돌립니다

패치 19-5 에서 IO List 25번 열부터 계기 정보를 붙였습니다. 실물 IO List
에는 그런 열이 없습니다. 제조사·모델·레인지·고장모드·알람 설정은
**계기 리스트(Instrument List)** 에 있는 정보입니다. 두 문서를 한 파일에
섞으면 실물과 모양이 달라 그대로 갈아 끼울 수 없습니다.

```
IO_LIST.xlsx          24열  배선 — mastertool/MAXIS 표준, 그것만
INSTRUMENT_LIST.xlsx  18열  계기 사양 — 제조사·레인지·고장모드·알람·매뉴얼
```

두 문서는 **TAG 로 조인**합니다. 실제로 사람이 하는 것과 같습니다.

## 조인 지점을 하나로

읽는 쪽이 세 군데(`panel_index`, `api/server`, `retrieval/pipeline`)라
각자 조인하면 규칙이 갈라집니다. `ingest/lists.py` 한 곳에서만 합치고
셋 다 그것을 부릅니다. 세 파일에 있던 엑셀 헤더 스캔 코드도 함께
없어졌습니다.

조인 규칙은 네 줄입니다.

```
키는 TAG
배선은 IO List 가 원본 — 계기 리스트가 덮어쓰지 않는다
계기 리스트에만 있는 태그는 배선 없는 점으로 싣는다
SERVICE 는 표준 24종에 없다 — DESCRIPTION 에서 받는다
```

## selfcheck 를 반대 방향으로 바꿨습니다

전에는 "확장 열에 모르는 이름이 섞였는가" 를 봤는데, 이제 **확장 열이
하나라도 있으면 실패**합니다.

```
IO List 에 표준 밖의 열이 있습니다: … — 계기 사양은 INSTRUMENT_LIST.xlsx 에 두십시오
```

원천 대조도 두 문서가 같은 시점의 원천에서 나왔는지 함께 봅니다. 계기
리스트가 없으면 실패합니다 — 있는 줄 알고 매뉴얼 연결이 통째로 비는
상태를 막으려는 것입니다.

## 확인 결과

| 항목 | 결과 |
|---|---|
| IO List 헤더 | 표준 24종만, 확장 열 없음 |
| 계기 리스트 | 18열 76점, IO List 와 원천 일치 |
| 판넬·카드 평가 | 204/204 |
| 변이 시험 4종 | 모두 의도대로 무너짐 |
| 인터락 평가 | 72/72 |
| 계기 상세 | SERVICE·MAKER·FAULT MODE·MANUAL FILE 정상 |
| 전 모듈 임포트 26개 | 실패 없음 |

## 적용

```cmd
python data\make_arrangement.py
python data\make_io_list.py
python -m eval.make_eval_panel
python -m eval.run_eval_panel --mutate --md eval\scorecard_panel.md
python -m eval.selfcheck --skip-llm
```

## 아직 정리하지 않은 것 — 확인 부탁드립니다

`DEMO_OUTPUT_LIST.xlsx` 는 제가 만든 것이 아니라 이전부터 있던 데모
파일입니다(생성 스크립트 없음). 말씀하신 대로 실제 프로젝트에 "output
list" 라는 문서는 없습니다. 그런데 이 파일이 지금 두 가지를 대고
있습니다.

```
출력 태그 24종        인터락이 동작시키는 대상 (XV·P·UV)
FAIL POSITION·DRIVE   인터락 조회에서 "고장 시 위치" 로 표시
```

실물이라면 이 정보가 어디 있는지에 따라 처리가 달라집니다.

- 밸브·펌프도 **계기 리스트**에 함께 있다면 → INSTRUMENT_LIST 에 흡수하고
  파일을 지웁니다
- **인터락 리스트**에 출력 사양이 적혀 있다면 → 거기서 읽고 파일을 지웁니다
- 별도 **Motor List / Valve List** 로 관리하신다면 → 그 이름과 열 구성을
  알려주시면 그 양식으로 바꾸겠습니다

어느 쪽인지 알려주시면 그에 맞춰 정리하겠습니다. 지금 상태로도 동작은
하지만, 실물에 없는 문서를 남겨 두면 시연에서 그대로 질문이 나올
자리입니다.
