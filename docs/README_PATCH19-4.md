# 패치 19-4 — 표준 양식 IO List 를 데이터 원천으로

패치 19-3 위에 덮으십시오.

```
data/make_io_list.py     (신규) 표준 양식 IO List 생성
data/IO_LIST.xlsx        (생성물) 3시트 — IO LIST / OUTPUT LIST / PROVENANCE
config.py                IO_LIST 가 있으면 그것을 INSTRUMENTS 로 사용
eval/selfcheck.py        표준 IO List 원천 대조 · 랙·슬롯 유일성 (24 → 26)
data/DEMO_ARRANGEMENT.pdf / PANEL_LOCATIONS.csv / eval_set_panel.json  재생성
```

## 왜 필요했나

원천이던 `DEMO_INSTRUMENT_LIST.xlsx` 는 **RACK 열이 전 행 0** 이었습니다.
그래서 슬롯 번호가 판넬마다 겹쳤습니다.

```
슬롯 4 → CUB-A, CUB-B, CUB-C, RIO-01, RIO-02   (다섯 판넬 모두)
```

`(PLC, RACK, SLOT)` 만으로는 카드가 구분되지 않아 카드 ID 에 판넬을
섞어 써야 했습니다. 표준 IO List 를 원천으로 두면 그 무리가 없어집니다.

## 표준 양식

한 통에 세 시트입니다.

| 시트 | 내용 |
|---|---|
| **IO LIST** | 배선이 있는 IO 점 76 — 27개 열 |
| **OUTPUT LIST** | 구동 대상 24 — 배선 정보가 리스트에 없는 점 |
| **PROVENANCE** | 어느 원천에서 몇 행을 읽어 만들었는지 |

기존 열 이름은 **그대로 유지**했습니다. 이름을 바꾸면 로더가 전부
깨집니다. 여기에 실물 IO List 에 있는 열을 더했습니다.

```
NO TAG SERVICE SYSTEM LOOP-GROUP [POINT TYPE] [IO TYPE]
MAKER MODEL MEAS-TYPE RANGE-MIN RANGE-MAX UNIT SIGNAL FAULT-MODE
PLC RACK SLOT CH [MODULE] PANEL TERMINAL
DWG-No. ALARM-L ALARM-H MANUAL-FILE REMARK
```

`POINT TYPE`(INPUT/OUTPUT), `IO TYPE`(AI/AO/DI/DO), `MODULE`(모듈 형식)이
추가분입니다. `IO TYPE` 과 `MODULE` 은 `SIGNAL` 표기에서 유도한 값이고,
지어낸 값이 아닙니다.

시트를 나눈 이유는 첫 시트를 읽는 기존 로더가 그대로 동작해야 하기
때문입니다. 출력은 배선 정보가 없으므로 IO 점에 섞으면 빈 칸만 늘어납니다.

## ★ RACK 은 가정값입니다

원천이 전 행 0 이라 판넬별로 부여했습니다. **확정된 값이 아닙니다.**

```
CUB-A 0    CUB-B 1    CUB-C 2      (중앙 큐비클)
RIO-01 11  RIO-02 12               (PROFINET 원격 스테이션)
```

가정이라는 사실은 생성 파일 2행 머리말과 PROVENANCE 시트에 적혀 있고,
실행할 때도 찍힙니다. 규칙을 바꾸시려면 `make_io_list.py` 상단의
`RACK_MAP` 한 곳만 고치면 되고, 그 아래 조회·평가·도면은 그대로
따라옵니다.

이제 카드가 유일하게 식별됩니다.

```
(PLC, RACK, SLOT) 이 여러 판넬에 걸치는 경우: 0건
카드 ID:  CUB-B/R1/S8   (전에는 CUB-B/R0/S8)
```

카드 ID 에서 판넬을 빼지는 않았습니다. 사람이 읽기 좋고, 실물 데이터에서
한 판넬에 랙이 둘이어도 그대로 갈립니다.

## 원천 단일화

`config.INSTRUMENTS` 가 `data/IO_LIST.xlsx` 를 우선하고, 없으면 v1 데모
리스트로 되돌아갑니다. 기동 시 어느 쪽을 쓰는지 찍습니다.

```
[config] IO List = IO_LIST.xlsx (표준 양식)
```

**실물 IO List 는 같은 양식으로 이 파일을 덮어쓰면 됩니다.** 조회·평가·
배치도·챗봇이 모두 `config.INSTRUMENTS` 한 곳을 보므로 다른 수정이
필요 없습니다.

## selfcheck 24 → 26

```
표준 IO List 원천 대조 [주입]  PROVENANCE 의 원천 행수와 실제 원천을 대조
                              (원천이 바뀌었는데 IO List 만 옛 상태면 실패)
랙·슬롯 유일성                (PLC, RACK, SLOT) 이 카드를 유일하게 가리키는가
```

첫 번째는 패치 19-3 에서 실제로 겪은 어긋남을 막으려는 것입니다. 계기
4점이 추가됐는데 도면만 옛 값에 머물렀고, 둘 다 그럴듯해서 드러나지
않았습니다.

## 확인 결과

| 항목 | 결과 |
|---|---|
| 판넬·카드 평가 | 203/203 |
| 변이 시험 4종 | 모두 의도대로 무너짐 (no-card-split 43/203) |
| 인터락 평가 | 72/72 |
| 공통원인 점검 | 지적 2건 (LCV-01 인터락 A/B 계통) |
| 랙·슬롯 유일성 | 카드 33장 모두 유일 |
| 전 모듈 임포트 25개 | 실패 없음 |
| 챗봇·API | 카드 ID 가 R1/S8 형태로 갱신되어 정상 |

## 적용

```cmd
python data\make_io_list.py
python data\make_arrangement.py
python -m eval.make_eval_panel
python -m eval.run_eval_panel --mutate --md eval\scorecard_panel.md
python -m eval.selfcheck --skip-llm
```

## 확인 부탁드릴 것

`RACK_MAP` 값입니다. 중앙 큐비클을 0/1/2 로, 원격 스테이션을 11/12 로
두었는데 실제 프로젝트에서 어떻게 매기시는지 알려주시면 그 값으로
바꾸겠습니다. 랙 번호가 실제 값이 되면 카드 ID 에서 판넬을 빼고
`PLC-UPW-01/R1/S8` 형태로 정리할 수도 있습니다.
