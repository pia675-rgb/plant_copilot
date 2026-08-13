# demo_data — 시연·공개용 가상 자료

이 폴더의 자료는 **전부 생성기로 만든 가상 데이터**입니다.
실제 프로젝트 문서가 아니며, 고객사 정보가 들어 있지 않습니다.

| 파일 | 내용 | 출처 |
|---|---|---|
| `IO_LIST.xlsx` | 입력 76 + 출력 24 = 100점 | `tools/make_io_list.py` |
| `INSTRUMENT_LIST.xlsx` | 계기 사양 100건 | `tools/make_io_list.py` |
| `TB_LIST.xlsx` | 판넬 6 · TB 블록 36 | `tools/make_tb_list.py` |
| `interlock/DEMO_INTERLOCK_LIST.xlsx` | 인터락 33건 / 조건 92행 | `tools/make_interlock_list.py` |
| `drawings/DEMO_*.pdf` | P&ID · 배치도 · 외형도 · 결선도 | 합성 도면 |
| `manuals/*.pdf` | 공개 벤더 카탈로그 3종 | 제조사 공개 자료 |

재생성이 필요하면 프로젝트 최상위에서:

    set COPILOT_DATA_DIR=%CD%\demo_data
    set COPILOT_DERIVED_DIR=%CD%\demo_derived
    set COPILOT_INDEX_DIR=%CD%\demo_index
    python -m tools.make_io_list
    python -m tools.make_interlock_list --out demo_data\interlock
    python -m tools.make_tb_list
    python -m tools.make_arrangement
    python -m ingest.build_index
    python -m retrieval.dense
    python -m eval.make_eval_interlock
    python -m eval.make_eval_panel
