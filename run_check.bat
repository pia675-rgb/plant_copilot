@echo off
chcp 949 >nul
REM  이 파일은 cp949 로 저장돼 있다. 콘솔 코드페이지를
REM  65001(UTF-8) 로 바꾸면 여기 적힌 한글이 깨져 나온다.
cd /d "%~dp0"

REM ============================================================
REM  이 배치는 **실물 자료(data/)** 로 돈다.
REM
REM  경로를 설정하지 않고 기본값에 기대면, 데모 변수가 살아 있는
REM  창에서 실행했을 때 그것을 물려받는다. 그런데 아래 echo 는
REM  data/ 라고 찍는다 - 표시가 사실과 달라진다. 실제로 이 혼선으로
REM  데모 색인이 실물 자료로 덮이는 사고가 났다.
REM  그래서 물려받지 않도록 여기서 못 박는다.
REM ============================================================
set COPILOT_DATA_DIR=%CD%\data
set COPILOT_INDEX_DIR=%CD%\index
set COPILOT_DERIVED_DIR=%CD%\derived

if not exist "data\IO_LIST.xlsx" (
  echo [ERROR] data\IO_LIST.xlsx 가 없습니다.
  echo         python -m tools.make_io_list 를 먼저 실행하십시오.
  pause ^& exit /b 1
)


REM -- embedding (search) --
set COPILOT_EMBED_PROVIDER=ollama
set COPILOT_EMBED_MODEL=bge-m3
set COPILOT_EMBED_BATCH=8

REM -- action-step LLM --
set COPILOT_PROVIDER=ollama
set COPILOT_MODEL=qwen2.5:7b-instruct

REM -- 근거 한국어 요약 (화면 표시용) --
REM    검색·판정은 즉시 끝나고, 이 요약이 대기 시간의 거의 전부다.
REM    병렬로 던지므로 대기는 가장 느린 한 건 수준이다.
set COPILOT_SUMMARY=on
set COPILOT_SUMMARY_MAX=3
set COPILOT_SUMMARY_TOKENS=120
set COPILOT_SUMMARY_TIMEOUT=20
REM    더 빠르게: 요약만 작은 모델로 (먼저 ollama pull qwen2.5:3b-instruct)
REM set COPILOT_SUMMARY_MODEL=qwen2.5:3b-instruct
REM    아예 끄기: 근거 원문·출처는 그대로 나오고 요약 한 줄만 빠진다
REM set COPILOT_SUMMARY=off

REM -- diversify: off scored best (33/45) --
set COPILOT_DIVERSIFY=off

REM -- clear AOAI placeholders --
set AZURE_OPENAI_ENDPOINT=
set AZURE_OPENAI_API_KEY=
set AZURE_OPENAI_EMBED_DEPLOYMENT=

echo DATA      = %COPILOT_DATA_DIR%
echo INDEX     = %COPILOT_INDEX_DIR%
echo EMBED     = %COPILOT_EMBED_PROVIDER%/%COPILOT_EMBED_MODEL%
echo LLM       = %COPILOT_PROVIDER%/%COPILOT_MODEL%
echo DIVERSIFY = %COPILOT_DIVERSIFY%
echo.

REM -- preflight then selfcheck --
python -m eval.preflight
if errorlevel 1 (
  echo.
  echo [중단] preflight 실패 - 위 항목을 먼저 해결하십시오.
  pause & exit /b 1
)

echo.
python -m eval.selfcheck
pause
