@echo off
chcp 949 >nul
REM  이 파일은 cp949 로 저장돼 있다. 콘솔 코드페이지를
REM  65001(UTF-8) 로 바꾸면 여기 적힌 한글이 깨져 나온다.
cd /d "%~dp0"

REM -- 자료 폴더는 data/ 한 곳 --

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

echo DATA      = %CD%\data
echo EMBED     = %COPILOT_EMBED_PROVIDER%/%COPILOT_EMBED_MODEL%
echo LLM       = %COPILOT_PROVIDER%/%COPILOT_MODEL%
echo DIVERSIFY = %COPILOT_DIVERSIFY%
echo.

REM -- search 45 + interlock 72 --
if not exist "eval\eval_set_interlock.json" (
  echo 인터락 평가셋을 생성합니다...
  python -m eval.make_eval_interlock
)

echo.
echo === 검색 45문항 / 4구성 (full 은 10~20분) ===
python -m eval.run_eval_v2 --md eval/scorecard_v2.md --dump-grades

echo.
echo === 인터락 72문항 ===
python -m eval.run_eval_interlock --md eval/scorecard_interlock.md

echo.
echo 스코어카드: eval\scorecard_v2.md / eval\scorecard_interlock.md
pause
