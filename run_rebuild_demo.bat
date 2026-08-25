@echo off
chcp 949 >nul
REM  이 파일은 cp949 로 저장돼 있다.
cd /d "%~dp0"

REM ============================================================
REM  run_rebuild_demo.bat - 데모 색인을 다시 만든다.
REM
REM  색인 재구축은 되돌리기 가장 비싼 작업이다. 측정은 잘못돼도
REM  다시 재면 그만이지만, 색인이 덮이면 임베딩까지 다시 만들어야
REM  한다. 실제로 환경변수가 풀린 창에서 build_index 를 돌려
REM  데모 색인이 실물 매뉴얼 45종으로 덮인 적이 있다.
REM
REM  그래서 경로를 눈으로 확인하고 Enter 를 눌러야 진행된다.
REM  DATA 에 demo_data 가 아닌 것이 찍히면 창을 닫으십시오.
REM ============================================================
set COPILOT_DATA_DIR=%CD%\demo_data
set COPILOT_INDEX_DIR=%CD%\demo_index
set COPILOT_DERIVED_DIR=%CD%\demo_derived
set COPILOT_EMBED_PROVIDER=ollama
set COPILOT_EMBED_MODEL=bge-m3
set COPILOT_EMBED_BATCH=8
set AZURE_OPENAI_ENDPOINT=
set AZURE_OPENAI_API_KEY=

if not exist "demo_data\manuals" (
  echo [ERROR] demo_data\manuals 가 없습니다. 경로를 확인하십시오.
  pause ^& exit /b 1
)

echo ============================================
echo  DATA  = %COPILOT_DATA_DIR%
echo  INDEX = %COPILOT_INDEX_DIR%
echo  EMBED = %COPILOT_EMBED_PROVIDER%/%COPILOT_EMBED_MODEL%
echo ============================================
echo.
echo  위 경로가 맞으면 Enter, 아니면 창을 닫으십시오.
pause

python -m ingest.build_index
if errorlevel 1 ( echo [중단] 색인 생성 실패 & pause & exit /b 1 )

python -m retrieval.dense
if errorlevel 1 ( echo [중단] 임베딩 생성 실패 & pause & exit /b 1 )

echo.
echo 완료. 확인하려면 run_eval_demo.bat 을 실행하십시오.
pause