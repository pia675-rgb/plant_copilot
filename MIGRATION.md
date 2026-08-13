# 폴더 통합 안내 (패치 20)

`GROK` 과 `copilot_v2_claude` 두 폴더를 **`plant_copilot` 하나로** 합쳤습니다.

## 무엇이 바뀌었나

```
전                                   후
GROK/project/manuals/*.pdf      →   plant_copilot/data/manuals/
GROK/project/demo_data/*.pdf    →   plant_copilot/data/drawings/
GROK/project/demo_data/         →   plant_copilot/data/sources/
  DEMO_INSTRUMENT_LIST.xlsx
  DEMO_OUTPUT_LIST.xlsx
GROK/project/*.py               →   plant_copilot/legacy_v1/
copilot_v2_claude/*             →   plant_copilot/*
README_PATCH*.md                →   plant_copilot/docs/
```

## 실행

```cmd
run_claude.bat      백엔드
run_check.bat       preflight + 시연 전 점검
```

`COPILOT_V1_DIR` 환경변수는 **더 이상 쓰지 않습니다.** bat 에서 제거했고,
`set_v1_path.bat` 도 지웠습니다. 자료 위치를 옮기시려면
`COPILOT_DATA_DIR` 을 쓰십시오.

## config.py

경로 정의가 한 곳으로 모였습니다. 예전에는 v1 폴더를 후보 경로 목록에서
찾아 헤매는 코드(`_find_v1_dir`)가 있었는데, 그게 없어졌습니다.

```python
DATA_DIR    = data/            (COPILOT_DATA_DIR 로 덮어쓰기 가능)
MANUAL_DIR  = data/manuals/
DRAWING_DIR = data/drawings/
SOURCE_DIR  = data/sources/    데모 원천
```

기동 시 `[config] DATA_DIR = …` 로 어디를 읽는지 찍습니다.

## v1 코드

`legacy_v1/` 에 그대로 두었습니다. 검색 평가의 **v1 열(18/42)이 이 코드를
불러 씁니다.** 지우면 A/B 비교가 사라지므로 남겨 두었습니다.

## 확인 결과

| 항목 | 결과 |
|---|---|
| preflight 자료 폴더 | data/ 한 곳에서 전부 확인 |
| 매뉴얼 PDF | data/manuals 4개 |
| 검색 인덱스 | error_code 306 · manual_text 1520 (재색인 불필요) |
| 판넬·카드 평가 | 180/180 |
| 인터락 평가 | 72/72 |
| 배치도 재생성 | data/drawings 로 출력 |

## 옮기신 뒤 하실 것

1. 압축을 풀고 폴더 이름을 원하시는 대로 바꾸십시오 (경로 의존 없음)
2. `run_check.bat` 으로 점검
3. 옛 `GROK` 폴더와 `copilot_v2_claude` 폴더는 백업 후 정리하십시오

`index/` 는 그대로 포함되어 있어 재색인 없이 바로 돕니다.


---

# TB 리스트 리더 (같은 패치)

```
ingest/tb_list.py    (신규) mastertool 격자 결선표 리더
ingest/lists.py      단자(TERMINAL)를 TB 리스트에서 받음
eval/selfcheck.py    TB 리스트 대조 [주입] (31 → 32)
```

주신 `PLC_TB_Layout_SPHA4.xlsx` 로 만들었습니다. 2,646점 중 미사용
채널 392점을 뺀 **2,254점**을 읽습니다.

```
CUB_1     1,971점 / TB 23개
FAB_CPU     283점 / TB 21개
카드   DI-32 1222 · DO-32 663 · AI-16 265 · AI-4 70 · AO-4 34
```

## 열 위치를 고정으로 잡지 않았습니다

블록 안의 열 구실이 카드 종류에 따라 다릅니다.

```
디지털   [N032] [I32.0] [    ] [태그]
아날로그 [    ] [PIW682+] [PIW682] [태그]     ← +/- 두 행이 한 채널
```

고정 열로 읽으면 아날로그에서 어긋납니다. 행 안에서 **주소처럼 생긴 값과
태그처럼 생긴 값을 찾아** 잡습니다.

## ★ 읽기 성공과 쓸모 있음은 다릅니다

주신 파일을 데모 자료로 넣어 봤더니 2,254점을 정상적으로 읽고도 **단자
조회가 통째로 비었습니다.** 실물 프로젝트 태그(`CUB_1_XA_0101`)라 데모
IO List 태그(`AIT-1001`)와 하나도 겹치지 않기 때문입니다.

읽기만 성공하면 아무 문제 없어 보이므로 점검 항목을 넣었습니다.

```
TB 리스트 2254점과 IO List 100점이 하나도 겹치지 않습니다
— 다른 프로젝트 자료로 보입니다. 단자 조회가 통째로 빕니다.
```

절반 미만만 겹쳐도 실패합니다.

## 주신 파일은 넣지 않았습니다

실물 프로젝트 자료이고 데모 태그와 맞지 않아 `data/` 에 포함하지
않았습니다. 데모는 `TAG_ATTRIBUTES.xlsx` 의 단자 값으로 돕니다.
실물 IO List 로 전환하실 때 같이 넣으시면 그때부터 TB 리스트가 원본이
됩니다.
