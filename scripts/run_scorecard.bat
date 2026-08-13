@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo === Plant Maintenance Copilot v2 scorecard ===
echo.
echo [1] 임베딩 백엔드
echo   A) Ollama:  ollama pull bge-m3  후 ollama serve
echo   B) ST:      pip install sentence-transformers
echo               set COPILOT_EMBED_BACKEND=st
echo.

if "%COPILOT_EMBED_BACKEND%"=="" (
  echo COPILOT_EMBED_BACKEND 미설정 - auto (Ollama 실패 시 ST 시도)
) else (
  echo COPILOT_EMBED_BACKEND=%COPILOT_EMBED_BACKEND%
)

echo.
echo [2] 벡터 인덱스 구축 (최초 1회, 수 분 소요)
python -c "from ingest.build_index import load; from retrieval.dense import DenseIndex, available; r=load(); print('chunks', len(r), 'available', available()); DenseIndex(r).ensure(); print('OK')"
if errorlevel 1 (
  echo 임베딩 실패 - hybrid/full 은 lexical 과 동일하게 나올 수 있습니다.
  pause
)

echo.
echo [3] 평가 실행 v1,lexical,hybrid,full
python -m eval.run_eval_v2 --systems v1,lexical,hybrid,full --md eval/scorecard_v2.md
echo.
echo 결과: eval\scorecard_v2.md
pause
