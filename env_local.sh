#!/usr/bin/env bash
# 로컬 오프라인 구성 — Ollama (결선 현장 시연용)
#
# 사용법
#   source env_local.sh
#
# 인터넷 없이 도는 구성이다. 결선은 오프라인 시연이므로 이쪽을 쓴다.
# 배포(본선 심사)는 env_deploy.sh 를 쓴다.

# --- 자료와 색인 ---
export COPILOT_DATA_DIR="$PWD/demo_data"
export COPILOT_DERIVED_DIR="$PWD/demo_derived"
export COPILOT_INDEX_DIR="$PWD/demo_index"

# --- 임베딩 (로컬 Ollama) ---
export COPILOT_EMBED_PROVIDER=ollama
export COPILOT_EMBED_MODEL="bge-m3"
export COPILOT_EMBED_BATCH=32

# --- LLM (로컬 Ollama) ---
export COPILOT_PROVIDER=ollama
export COPILOT_MODEL="qwen2.5:7b-instruct"

# --- 리랭커 ---
export COPILOT_RERANK=1

# 클라우드 설정이 남아 있으면 로컬 구성을 오염시킨다. 지운다.
unset OPENAI_BASE_URL
unset OPENAI_API_KEY

# --- 확인 ---
echo "DATA   = $COPILOT_DATA_DIR"
echo "INDEX  = $COPILOT_INDEX_DIR"
echo "EMBED  = $COPILOT_EMBED_PROVIDER/$COPILOT_EMBED_MODEL"
echo "LLM    = $COPILOT_PROVIDER/$COPILOT_MODEL"
echo "RERANK = $COPILOT_RERANK"
