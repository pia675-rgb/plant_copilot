@echo off
chcp 949 >nul
REM  이 파일은 cp949 로 저장돼 있다. 콘솔 코드페이지를
REM  65001(UTF-8) 로 바꾸면 여기 적힌 한글이 깨져 보인다.
cd /d "%~dp0"

REM ============================================================
REM  run_check_demo.bat - 시연 전 자기 점검을 데모 자료로 돌린다.
REM
REM  왜 이 파일이 생겼나 (09-02)
REM
REM  구동(run_demo)·평가(run_eval_demo)·색인(run_rebuild_demo)에는
REM  데모 전용 배치가 있는데 점검에만 없었다. 그래서 selfcheck 는
REM  손으로 환경변수를 쳐야 했고, 잊으면 기본 경로(data/, 실물)를
REM  가리켰다. 그 폴더가 없으면 폴백이 v1 원본(76점)으로 조용히
REM  갈아타 절반만 동작한다. "안 돌아간다"가 아니라 "이상하게
REM  돌아간다"로 나타나 18건의 서로 다른 결함처럼 보였다.
REM
REM  같은 함정을 하루에 세 번 밟고서야 이 파일을 만들었다.
REM  문서에 경고를 적어 두는 것으로는 막히지 않았다.
REM  주의는 그 문서를 펼친 사람에게만 작동하고,
REM  실행 경로에 박은 못은 읽지 않아도 작동한다.
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
  echo         데모 자료가 있어야 점검할 수 있습니다.
  pause ^& exit /b 1
)

if not exist "demo_index\chunks.jsonl" (
  echo [ERROR] demo_index 색인이 없습니다.
  echo         run_rebuild_demo.bat 를 먼저 실행하십시오.
  pause ^& exit /b 1
)

echo DATA      = %COPILOT_DATA_DIR%
echo INDEX     = %COPILOT_INDEX_DIR%
echo DERIVED   = %COPILOT_DERIVED_DIR%
echo EMBED     = %COPILOT_EMBED_PROVIDER%/%COPILOT_EMBED_MODEL%
echo LLM       = %COPILOT_PROVIDER%/%COPILOT_MODEL%
echo DIVERSIFY = %COPILOT_DIVERSIFY%
echo.
echo 위 DATA 경로가 demo_data 로 끝나는지 확인하십시오.
echo 뒤이어 나오는 [lists] 줄이 IO 100점이면 정상입니다.
echo.

REM -- preflight 먼저, 통과해야 selfcheck --
REM  preflight 는 실패가 있으면 종료 코드 1 을 돌려준다(패치 32).
REM  경고만 보고 넘어가려면 아래 줄에 --lenient 를 붙인다.
REM  Ollama 가 꺼져 있으면 임베딩 확인에서 오래 기다린다.
REM  멈춘 것이 아니라 응답을 기다리는 중이다. ollama serve 를 먼저.
python -m eval.preflight
if errorlevel 1 (
  echo.
  echo [중단] preflight 실패 - 위 항목을 먼저 해결하십시오.
  echo        경고만 보고 진행하려면 --lenient 를 붙이십시오.
  pause ^& exit /b 1
)

echo.
python -m eval.selfcheck
pause
