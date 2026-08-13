# data/ — 여기에 넣는 것

**사용자가 넣는 자료만** 둡니다. 아홉 가지입니다.

```
data/
  INSTRUMENT_LIST.xlsx      계기 리스트
  IO_LIST.xlsx              IO List
  TB_LIST.xlsx              TB 리스트
  interlock/                인터락 리스트 (여러 통이면 다 넣으십시오)
  manuals/                  벤더 매뉴얼 PDF
  drawings/                 P&ID · OUTLINE · SCHEMATIC · ARRANGEMENT PDF
```

이 폴더에 **다른 것은 넣지 마십시오.** `run_check.bat` 이 확인합니다.

```
data/ 에 업로드 자료가 아닌 것: TAG_ATTRIBUTES.xlsx (생성물 — derived/ 로)
```

## 도구가 만드는 것 — derived/

```
derived/
  PANEL_LOCATIONS.csv       판넬 위치        tools/make_arrangement.py
  drawings_index.csv        도면 색인
  error_codes.json          알람 코드표
  maintenance_history.json  조치 이력        화면에서 쓰면 쌓입니다
index/                      임베딩 캐시
```

지우셔도 됩니다. 다시 만들어집니다.

## 나머지 폴더

```
tools/       생성기 — python -m tools.make_io_list
demo/        데모 원천. 실물 자료를 쓰시면 필요 없습니다
legacy_v1/   v1 코드 (검색 평가의 v1 열이 씁니다 — 지우지 마십시오)
```

## 인터락 리스트가 폴더인 이유

프로젝트마다 계통별로 여러 통으로 나뉩니다. `data/interlock/` 안의 엑셀을
전부 읽으므로 나뉜 채로 넣으시면 됩니다. 데모 양식과 실물 양식을 자동으로
가려 읽습니다.

## 아직 도구가 못 만드는 것

| 항목 | 지금 | 필요한 것 |
|---|---|---|
| `drawings_index.csv` | 데모 도면과 함께 만든 색인 | 도면 PDF 에서 태그 추출 |
| `error_codes.json` | v1 이 매뉴얼에서 뽑은 306건 | 매뉴얼 PDF 에서 추출 |
| `TAG_ATTRIBUTES.xlsx` 의 일부 | 데모 값 | 아래 참조 |

**부속 데이터(TAG_ATTRIBUTES.xlsx)는 없앴습니다.** 네 항목이 모두
업로드 자료에서 옵니다.

| 항목 | 어디서 오나 |
|---|---|
| TERMINAL | TB List |
| TYPE | 계기 리스트 `SENSOR TYPE` |
| FAIL POSITION | 인터락 리스트 `* Valve Action : Fail Open` |
| MANUAL FILE | 계기 리스트 `MODEL` ↔ 매뉴얼 파일명 자동 대조 |

## 자료를 다른 곳에 두려면

```cmd
set COPILOT_DATA_DIR=D:\프로젝트\자료
set COPILOT_DERIVED_DIR=D:\프로젝트\생성물
```
