# Plant Maintenance Copilot v2 — 배포 이미지
#
# 로컬 실행과 다른 점
#   · 리랭커 없음 (품질 동일, torch 2GB 제거)
#   · 임베딩은 Ollama 가 아니라 클라우드 REST
#   · 자료는 demo_data 만 — 실물 프로젝트 자료는 이미지에 들어가지 않는다
#
# 임베딩 제공자를 왜 DeepInfra 로 두었나
#   OpenAI 임베딩은 한글 질의로 영문 매뉴얼을 찾는 유형(syn)에서
#   bge-m3 대비 8/14 -> 3/14 로 무너졌다(2026-08-22 측정).
#   DeepInfra 가 OpenAI 호환 엔드포인트로 bge-m3 를 제공하므로
#   같은 모델을 그대로 쓴다. 28/45, syn 8/14 로 로컬과 동일함을 확인했다.
#
# 색인은 demo_index_bgeapi/ 를 싣는다
#   배포와 같은 제공자(DeepInfra bge-m3, 1024차원)로 만든 색인이다.
#   색인과 질의의 임베딩 모델이 다르면 검색이 무의미해진다.
#   색인을 다시 만들 때는:
#     source env_deploy.sh
#     python -m retrieval.dense
#
# 빌드
#   docker build -t plant-copilot .
# 실행
#   docker run -p 8000:8000 -e OPENAI_API_KEY=<DeepInfra 키> plant-copilot
#
# 호스팅에 올릴 때 대시보드에 넣어야 하는 환경변수는 OPENAI_API_KEY 하나뿐이다.
# 나머지는 아래 ENV 에 박혀 있다.

# ── 1단계: React UI 빌드 ─────────────────────────────────────
FROM node:20-slim AS ui

WORKDIR /ui
COPY ui/react/package.json ui/react/package-lock.json ./
RUN npm ci
COPY ui/react/ ./
RUN npm run build


# ── 2단계: 실행 이미지 ───────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# 파이썬 기본값. 로그가 버퍼에 묶이면 배포 로그에서 기동 실패 원인이 안 보인다.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

# 코드
COPY api/ ./api/
COPY config.py ./
COPY graph/ ./graph/
COPY ingest/ ./ingest/
COPY retrieval/ ./retrieval/
COPY tools/ ./tools/

# 데모 자료와 색인 (실물 자료는 넣지 않는다)
COPY demo_data/ ./demo_data/
COPY demo_index_bgeapi/ ./demo_index/
COPY demo_derived/ ./demo_derived/

# 1단계에서 빌드한 UI
COPY ui/react/dist/ ./ui/react/dist/

# 배포 구성
ENV COPILOT_DATA_DIR=/app/demo_data \
    COPILOT_INDEX_DIR=/app/demo_index \
    COPILOT_DERIVED_DIR=/app/demo_derived \
    COPILOT_RERANK=0 \
    COPILOT_EMBED_PROVIDER=openai \
    COPILOT_EMBED_MODEL=BAAI/bge-m3 \
    COPILOT_EMBED_BATCH=32 \
    OPENAI_BASE_URL=https://api.deepinfra.com/v1/openai \
    COPILOT_PROVIDER=openai \
    COPILOT_MODEL=deepseek-ai/DeepSeek-V4-Flash-0731 \
    COPILOT_UI_MODE=hybrid \
    PORT=8000

EXPOSE 8000

# 호스팅 업체는 대개 PORT 환경변수로 포트를 지정한다.
# 고정 포트로 박아 두면 배포는 성공하는데 접속이 안 되는 형태로 실패한다.
CMD ["sh", "-c", "uvicorn api.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
