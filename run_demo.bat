@echo off
chcp 949 >nul
REM  이 파일은 cp949 로 저장돼 있다. 콘솔 코드페이지를
REM  65001(UTF-8) 로 바꾸면 여기 적힌 한글이 깨져 나온다.
cd /d "%~dp0"

REM ============================================================
REM  run_demo.bat - 데모 자료로 띄운다 (실물 폴더는 건드리지 않음)
REM
REM  실물과 데모는 자료뿐 아니라 색인·파생물도 다르다. 한 폴더를
REM  공유하면 오갈 때마다 서로를 덮어써서 매번 다시 만들어야 한다.
REM      demo_data\     사람이 넣는 문서 (IO·계기·TB·인터락·매뉴얼·도면)
REM      demo_index\    매뉴얼 색인 + 임베딩
REM      demo_derived\  생성물 (배치 위치·도면 인덱스·코드표·이력)
REM ============================================================

set COPILOT_DATA_DIR=%CD%\demo_data
set COPILOT_INDEX_DIR=%CD%\demo_index
set COPILOT_DERIVED_DIR=%CD%\demo_derived

REM -- embedding (search) --
set COPILOT_EMBED_PROVIDER=ollama
set COPILOT_EMBED_MODEL=bge-m3
set COPILOT_EMBED_BATCH=8

REM -- action-step LLM --
set COPILOT_PROVIDER=ollama
set COPILOT_MODEL=llama3.2

REM -- 근거 한국어 요약 (화면 표시용) --
set COPILOT_SUMMARY=on
set COPILOT_SUMMARY_MAX=3
set COPILOT_SUMMARY_TOKENS=120
set COPILOT_SUMMARY_TIMEOUT=20

set COPILOT_DIVERSIFY=off

set AZURE_OPENAI_ENDPOINT=
set AZURE_OPENAI_API_KEY=
set AZURE_OPENAI_EMBED_DEPLOYMENT=

if not exist "demo_data\IO_LIST.xlsx" (
  echo [ERROR] demo_data 폴더가 없습니다.
  pause ^& exit /b 1
)

REM -- ollama 살아 있는지 먼저 본다 --
curl -s -o nul --max-time 2 http://127.0.0.1:11434/api/tags
if errorlevel 1 (
  echo [WARN] ollama 서버가 응답하지 않습니다.
  echo        검색은 lexical 로 강등되고 조치 순서는 템플릿으로 나옵니다.
  echo        다른 창에서 ollama serve 를 먼저 실행하십시오.
  pause
)

REM -- 임베딩이 없으면 한 번 만든다 (몇 분 걸림) --
if not exist "demo_index\embeddings.npy" (
  echo [setup] 데모 임베딩을 만듭니다. 처음 한 번만 걸립니다...
  python -m retrieval.dense
)

echo DATA      = %COPILOT_DATA_DIR%
echo INDEX     = %COPILOT_INDEX_DIR%
echo EMBED     = %COPILOT_EMBED_PROVIDER%/%COPILOT_EMBED_MODEL%
echo LLM       = %COPILOT_PROVIDER%/%COPILOT_MODEL%
echo.
uvicorn api.server:app --port 8000
echo.
echo [exit] uvicorn 종료 코드 = %ERRORLEVEL%
pause
