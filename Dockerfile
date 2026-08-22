# Plant Maintenance Copilot v2 — 배포 이미지
#
# 로컬 실행과 다른 점
#   · 리랭커 없음 (품질 동일, torch 2GB 제거)
#   · 임베딩은 Ollama 가 아니라 클라우드 REST
#   · 자료는 demo_data 만 — 실물 프로젝트 자료는 이미지에 들어가지 않는다
#
# 빌드 전 반드시 할 것
#   demo_index/embeddings.npy 를 배포와 같은 임베딩 제공자로 다시 만든다.
#   색인과 질의의 임베딩 모델이 다르면 검색이 무의미해진다.
#   (config.py 가 색인 메타의 제공자를 대조해 경고를 내지만, 믿지 말고 직접 맞출 것)
#
#   export COPILOT_EMBED_PROVIDER=openai
#   export OPENAI_API_KEY=...
#   python -m retrieval.dense
#
# 미해결 — 임베딩 제공자 재검토 필요
#   OpenAI 임베딩은 한글 질의로 영문 매뉴얼을 찾는 유형(syn)에서
#   bge-m3 대비 8/14 → 3/14 로 무너진다(2026-08-22 측정).
#   아래 EMBED_PROVIDER 설정은 잠정값이며 그대로 배포하면
#   핵심 기능이 동작하지 않는 것처럼 보인다.
#
# 빌드
#   docker build -t plant-copilot .
# 실행
#   docker run -p 8000:8000 -e OPENAI_API_KEY=... plant-copilot

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
COPY utils/ ./utils/

# 데모 자료와 색인 (실물 자료는 넣지 않는다)
COPY demo_data/ ./demo_data/
COPY demo_index/ ./demo_index/
COPY demo_derived/ ./demo_derived/

# 1단계에서 빌드한 UI
COPY --from=ui /ui/dist ./ui/react/dist

# 배포 구성
ENV COPILOT_DATA_DIR=/app/demo_data \
    COPILOT_INDEX_DIR=/app/demo_index \
    COPILOT_DERIVED_DIR=/app/demo_derived \
    COPILOT_RERANK=0 \
    COPILOT_EMBED_PROVIDER=openai \
    COPILOT_EMBED_MODEL=text-embedding-3-large \
    COPILOT_EMBED_BATCH=16 \
    COPILOT_UI_MODE=hybrid \
    PORT=8000

EXPOSE 8000

# 호스팅 업체는 대개 PORT 환경변수로 포트를 지정한다.
# 고정 포트로 박아 두면 배포는 성공하는데 접속이 안 되는 형태로 실패한다.
CMD ["sh", "-c", "uvicorn api.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
