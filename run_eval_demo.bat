@echo off
chcp 949 >nul
REM  이 파일은 cp949 로 저장돼 있다. 콘솔 코드페이지를
REM  65001(UTF-8) 로 바꾸면 여기 적힌 한글이 깨져 나온다.
cd /d "%~dp0"

REM ============================================================
REM  run_eval_demo.bat - 제출용 데모 자료로 채점한다.
REM
REM  문서에 싣는 수치는 이 배치로 잰 값이다. 실물(run_eval.bat)과
REM  섞이지 않도록 경로를 여기서 못 박는다.
REM ============================================================
set COPILOT_DATA_DIR=%CD%\demo_data
set COPILOT_INDEX_DIR=%CD%\demo_index
set COPILOT_DERIVED_DIR=%CD%\demo_derived

set COPILOT_EMBED_PROVIDER=ollama
set COPILOT_EMBED_MODEL=bge-m3
set COPILOT_EMBED_BATCH=8
set COPILOT_PROVIDER=ollama
set COPILOT_MODEL=qwen2.5:7b-instruct
set COPILOT_DIVERSIFY=off

set AZURE_OPENAI_ENDPOINT=
set AZURE_OPENAI_API_KEY=
set AZURE_OPENAI_EMBED_DEPLOYMENT=

if not exist "demo_data\IO_LIST.xlsx" (
  echo [ERROR] demo_data 폴더가 없습니다.
  pause ^& exit /b 1
)

echo DATA      = %COPILOT_DATA_DIR%
echo INDEX     = %COPILOT_INDEX_DIR%
echo EMBED     = %COPILOT_EMBED_PROVIDER%/%COPILOT_EMBED_MODEL%
echo LLM       = %COPILOT_PROVIDER%/%COPILOT_MODEL%
echo.

echo === 검색 45문항 (hybrid) ===
python -m eval.run_eval_v2 --systems hybrid --md eval/scorecard_demo.md

echo.
echo === 홀드아웃 10문항 ===
python -m eval.run_eval_v2 --eval eval/eval_set_holdout.json --systems hybrid --md eval/scorecard_holdout.md

echo.
echo === 인터락 / 판넬 / 이력 ===
python -m eval.run_eval_interlock --md eval/scorecard_interlock.md

echo.
echo 스코어카드: eval\scorecard_demo.md 외
pause