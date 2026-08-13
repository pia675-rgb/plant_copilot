# 패치 23 — data/ 에 업로드 자료만

## 무엇이 문제였나

`data/` 에 세 가지가 섞여 있었습니다.

```
넣는 것    IO_LIST · INSTRUMENT_LIST · INTERLOCK · manuals/ · drawings/
만드는 것  PANEL_LOCATIONS.csv · TAG_ATTRIBUTES.xlsx · error_codes.json
           drawings_index.csv · maintenance_history.*
코드       make_io_list.py · make_arrangement.py · make_interlock_list.py
데모 원천  sources/DEMO_INSTRUMENT_LIST.xlsx · DEMO_OUTPUT_LIST.xlsx
```

이러면 "무엇을 넣어야 하나" 에 한 줄로 답할 수 없습니다. 실제로 지난
패치에서 생성물인 IO_LIST 를 원본으로 보고 엑셀에서 CUB-D 배선을
채우셨고, 그대로 뒀으면 다음 재생성에서 24점을 잃을 뻔했습니다.

## 새 구조

```
data/          ← 업로드 자료만 (9종)
  INSTRUMENT_LIST.xlsx · IO_LIST.xlsx · TB_LIST.xlsx
  interlock/ · manuals/ · drawings/

derived/       ← 도구가 만드는 것
tools/         ← 생성기
demo/          ← 데모 원천
legacy_v1/     ← v1 코드
```

`config.py` 가 `DATA_DIR` 과 `DERIVED_DIR` 을 나눠 가리키고, 기동 시 둘 다
찍습니다. `COPILOT_DERIVED_DIR` 로 생성물 위치도 옮길 수 있습니다.

## 인터락 리스트를 폴더로

`data/interlock/` 안의 엑셀을 전부 읽습니다. 프로젝트마다 계통별로 여러
통으로 나뉘기 때문입니다. 데모 양식과 실물 양식은 자동으로 가려 읽습니다.

## ★ 작업 중 제가 낸 고장

`INTERLOCK_SAMPLE.xlsx` 를 `INTERLOCK_LIST.xlsx` 로 개명했는데, 실제
39건 중 33건은 `DEMO_INTERLOCK_LIST.xlsx` 에 있었습니다. 인터락이 0건이
되었고 **화면에는 "인터락 없음" 으로 보입니다.**

`ingest/interlock.py` 가 파일명을 하드코딩하고 있던 것이 원인입니다.
config 경로를 보도록 고쳤습니다. 이제 이름을 바꿔도 안 깨집니다.

**인터락 평가가 이걸 잡았습니다** — `IL72 attr RWP-01 출력 태그를 찾지 못함`.

## selfcheck 33 → 34

```
data 폴더 정결 [주입]   업로드 자료 말고 다른 것이 섞였는가
                       생성물 · 임시 파일 · 모르는 폴더를 구분해 알려줌
```

검출 확인:

```
TAG_ATTRIBUTES.xlsx (생성물 — derived/ 로)
46C7A000 (임시 파일 — 엑셀을 닫고 생성기를 다시 실행)
```

## 확인 결과

| 항목 | 결과 |
|---|---|
| data/ 내용물 | 업로드 자료만 (매뉴얼 4 · 도면 4 · 리스트 3종) |
| 판넬·카드 평가 | 213/213 |
| 인터락 평가 | 39건 전건 통과 |
| 전 모듈 임포트 31개 | 실패 없음 |

## 적용

압축을 기존 폴더에 덮으신 뒤, 옮겨진 파일이 옛 자리에 남아 있으면
지우십시오.

```cmd
del data\PANEL_LOCATIONS.csv data\TAG_ATTRIBUTES.xlsx data\error_codes.json
del data\maintenance_history.* data\eval_set.json
del data\make_io_list.py data\make_arrangement.py data\make_interlock_list.py
rmdir /s /q data\sources
run_check.bat
```

`data 폴더 정결` 항목이 남은 것을 알려줍니다.

## 남은 확인 사항

`TAG_ATTRIBUTES.xlsx` 의 `TYPE` · `FAIL POSITION` · `DRIVE` 가 실물에서
어느 문서에 있는지 아직 모릅니다. 밸브·구동기 사양인데 업로드 자료
아홉 가지에는 없습니다. 인터락 리스트에 적혀 있다면 거기서 읽고,
아니라면 그 문서를 열 번째 자료로 추가해야 합니다.
