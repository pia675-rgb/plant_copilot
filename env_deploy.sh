#!/usr/bin/env bash
# 배포 구성 — DeepInfra (임베딩 bge-m3 + LLM DeepSeek)
#
# 사용법
#   source env_deploy.sh
#
# 키는 이 파일에 넣지 않는다. .env.local 에서 읽어 온다.
# .env.local 은 .gitignore 에 있어야 한다.
#
# .env.local 만드는 법 (최초 1회):
#   echo 'export OPENAI_API_KEY="여기에DeepInfra키"' > .env.local
#
# 이 구성은 배포 컨테이너와 동일하다. 여기서 도는 것은 배포해도 돈다.

# --- 자료와 색인 ---
export COPILOT_DATA_DIR="$PWD/demo_data"
export COPILOT_DERIVED_DIR="$PWD/demo_derived"
export COPILOT_INDEX_DIR="$PWD/demo_index_bgeapi"

# --- 임베딩 (DeepInfra) ---
# OpenAI 호환 엔드포인트라 provider 는 openai 로 두고 base URL 만 돌린다.
export COPILOT_EMBED_PROVIDER=openai
export OPENAI_BASE_URL="https://api.deepinfra.com/v1/openai"
export COPILOT_EMBED_MODEL="BAAI/bge-m3"
export COPILOT_EMBED_BATCH=32

# --- LLM (DeepInfra) ---
# 임베딩과 같은 BASE_URL / API_KEY 를 공유한다.
export COPILOT_PROVIDER=openai
export COPILOT_MODEL="deepseek-ai/DeepSeek-V4-Flash-0731"

# --- 리랭커 ---
# on/off 가 45문항에서 28/45 로 동일했다. 배포 이미지에서 torch 2GB 를 뺀다.
export COPILOT_RERANK=0

# --- 키 ---
if [ -f .env.local ]; then
  . ./.env.local
else
  echo "[warn] .env.local 이 없습니다. OPENAI_API_KEY 를 직접 넣으십시오."
fi

# --- 확인 ---
echo "DATA   = $COPILOT_DATA_DIR"
echo "INDEX  = $COPILOT_INDEX_DIR"
echo "EMBED  = $COPILOT_EMBED_PROVIDER/$COPILOT_EMBED_MODEL"
echo "LLM    = $COPILOT_PROVIDER/$COPILOT_MODEL"
echo "RERANK = $COPILOT_RERANK"
if [ -n "$OPENAI_API_KEY" ]; then
  echo "KEY    = 설정됨"
else
  echo "KEY    = 없음"
fi
