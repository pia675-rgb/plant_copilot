#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py — Plant Maintenance Copilot v2 전역 설정

v1(렉시컬)과 v2(하이브리드)를 같은 평가셋으로 비교하는 것이 목표이므로,
경로와 하이퍼파라미터는 전부 여기 한 곳에 모아 실험 조건을 기록 가능하게 둔다.

환경변수로 덮어쓸 수 있다. 키는 코드에 적지 않는다.
"""

import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def _p(*a):
    return os.path.join(ROOT, *a)


# ── 입력 데이터 ──────────────────────────────────────────────
# data/ 에는 **사용자가 넣는 자료만** 둔다. 딱 이 아홉 가지다.
#
#   data/
#     INSTRUMENT_LIST.xlsx   계기 리스트
#     IO_LIST.xlsx           IO List
#     TB_LIST.xlsx           TB 리스트
#     INTERLOCK_LIST.xlsx    인터락 리스트
#     manuals/               벤더 매뉴얼 PDF
#     drawings/              P&ID · OUTLINE · SCHEMATIC · ARRANGEMENT PDF
#
# 도구가 만드는 것은 전부 derived/ 로 나간다. 두 가지를 한 폴더에 두면
# "무엇을 넣어야 하나" 에 한 줄로 답할 수 없고, 실제로 생성물을 원본으로
# 착각해 손으로 고쳤다가 재생성에서 잃을 뻔한 적이 있다.
#
#   derived/   PANEL_LOCATIONS.csv
#              drawings_index.csv · error_codes.json · maintenance_history.*
#   tools/     생성기 (make_io_list.py 등)
#   demo/      데모 원천 — 실물 자료를 쓰면 필요 없다
#
# COPILOT_DATA_DIR 로 자료 폴더를 옮길 수 있다.
DATA_DIR = os.path.abspath(os.environ.get("COPILOT_DATA_DIR", "").strip()
                           or _p("data"))
MANUAL_DIR = os.path.join(DATA_DIR, "manuals")
DRAWING_DIR = os.path.join(DATA_DIR, "drawings")

DERIVED_DIR = os.path.abspath(os.environ.get("COPILOT_DERIVED_DIR", "").strip()
                              or _p("derived"))
DEMO_DIR = _p("demo")
SOURCE_DIR = os.path.join(DEMO_DIR, "sources")

# v1 코드는 legacy_v1/ 에 보존만 한다. 경로 이름은 하위 호환으로 남긴다.
V1_DIR = ROOT


def _pick(name, *dirs):
    """여러 폴더에서 먼저 있는 것을 고른다. 없으면 첫 번째 경로."""
    for d in dirs:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return os.path.join(dirs[0], name)


# ── 사용자가 넣는 자료 ───────────────────────────────────────
IO_LIST = os.path.join(DATA_DIR, "IO_LIST.xlsx")
def _resolve_instrument_xlsx():
    env = (os.environ.get("COPILOT_INSTRUMENT_XLSX") or "").strip()
    if env and os.path.isfile(env):
        return env
    for name in (
        "INSTRUMENT_LIST.xlsx",
        "Analyzer Instrument List.xlsx",
        "ANALYZER_INSTRUMENT_LIST.xlsx",
    ):
        p = os.path.join(DATA_DIR, name)
        if os.path.isfile(p):
            return p
    return os.path.join(DATA_DIR, "INSTRUMENT_LIST.xlsx")


INSTRUMENT_SPEC = _resolve_instrument_xlsx()


def _resolve_instrument_specs():
    """계기 리스트 **전부**. 실물은 계기 종류별로 여러 통으로 들어온다.

    한 통(Analyzer)만 읽던 때는 Instrument 후보가 22건에 그쳐 P&ID 자동
    부여가 389점 중 131점에서 멈췄다. 조회는 그래도 성립하므로 빠진 줄을
    눈으로 알아채기 어렵다. 인터락 리스트와 같은 방식(폴더 전체)으로 읽는다.
    COPILOT_INSTRUMENT_XLSX 로 하나만 쓰도록 고정할 수도 있다.
    """
    import re as _re
    env = (os.environ.get("COPILOT_INSTRUMENT_XLSX") or "").strip()
    if env and os.path.isfile(env):
        return [env]
    out = []
    if os.path.isdir(DATA_DIR):
        for f in sorted(os.listdir(DATA_DIR)):
            if f.startswith("~$") or not f.lower().endswith((".xlsx", ".xlsm")):
                continue
            if f.upper() == "INSTRUMENT_LIST.XLSX" or \
                    _re.search(r"instrument\s*list", f, _re.I):
                out.append(os.path.join(DATA_DIR, f))
    return out or [INSTRUMENT_SPEC]


INSTRUMENT_SPECS = _resolve_instrument_specs()
TB_LIST = os.path.join(DATA_DIR, "TB_LIST.xlsx")
# 인터락 리스트 — data/interlock/ 안의 엑셀을 전부 읽는다.
#
# 파일 하나로 고정하지 않는 이유는, 프로젝트마다 인터락 리스트가 계통별로
# 여러 통으로 나뉘기 때문이다. 파일명을 고정했다가 이름이 어긋나 조회가
# 통째로 빈 적이 있는데, 인터락 0건은 "인터락이 없다" 로 보여서 원인을
# 찾기 어렵다.
INTERLOCK_DIR = os.path.join(DATA_DIR, "interlock")


def _resolve_interlock_xlsx():
    env = (os.environ.get("COPILOT_INTERLOCK_XLSX") or "").strip()
    if env:
        return env
    # interlock 폴더 우선 (실물 여러 파일/시트)
    if os.path.isdir(INTERLOCK_DIR):
        files = [f for f in os.listdir(INTERLOCK_DIR)
                 if f.lower().endswith((".xlsx", ".xlsm")) and not f.startswith("~$")]
        if files:
            return INTERLOCK_DIR
    preferred = os.path.join(INTERLOCK_DIR, "INTERLOCK_LIST_REALFORM.xlsx")
    if os.path.isfile(preferred):
        return preferred
    for name in ("Alarm & Interlock List.xlsx", "INTERLOCK_LIST.xlsx",
                 "INTERLOCK_SAMPLE.xlsx"):
        p = os.path.join(DATA_DIR, name)
        if os.path.isfile(p):
            return p
        p2 = os.path.join(INTERLOCK_DIR, name)
        if os.path.isfile(p2):
            return p2
    return INTERLOCK_DIR


INTERLOCK_XLSX = _resolve_interlock_xlsx()

INSTRUMENTS = IO_LIST if os.path.isfile(IO_LIST) else os.path.join(
    SOURCE_DIR, "DEMO_INSTRUMENT_LIST.xlsx")

# 출력(밸브·펌프) 사양은 계기 리스트에 있다. 별도 "output list" 문서는
# 실제 프로젝트에 없다 — 출력은 IO List 의 DO/AO 점이다.
OUTPUT_LIST_XLSX = INSTRUMENT_SPEC

# ── 도구가 만드는 것 (derived/) ──────────────────────────────
PANEL_LOCATIONS = os.path.join(DERIVED_DIR, "PANEL_LOCATIONS.csv")
DRAWINGS_INDEX = os.path.join(DERIVED_DIR, "drawings_index.csv")
ERROR_CODES = os.path.join(DERIVED_DIR, "error_codes.json")
HISTORY = os.path.join(DERIVED_DIR, "maintenance_history.json")

# 배치도는 사용자가 넣는 자료다. 데모에서는 생성기가 만들어 넣는다.
ARRANGEMENT_PDF = os.path.join(DRAWING_DIR, "DEMO_ARRANGEMENT.pdf")

# 시작 시 경로 안내 (없으면 알람 태그 목록이 비게 됨)
if not os.path.isfile(INSTRUMENTS):
    print("[config] IO List 를 찾지 못했습니다: %s" % INSTRUMENTS)
    print("[config] data/ 에 IO_LIST.xlsx 를 넣거나 "
          "COPILOT_DATA_DIR 로 자료 폴더를 지정하십시오.")
else:
    print("[config] DATA_DIR    =", DATA_DIR)
    print("[config] DERIVED_DIR =", DERIVED_DIR)

# ── 산출 인덱스 ──────────────────────────────────────────────
# 색인은 **자료 세트마다 다르다.** 한 폴더를 공유하면 실물↔데모를 오갈 때
# 서로의 색인을 덮어써서, 매번 몇 분씩 다시 만들어야 한다. 세트별로 폴더를
# 나눠 두면 자료만 바꿔 끼우고 바로 띄울 수 있다.
INDEX_DIR = os.path.abspath(os.environ.get("COPILOT_INDEX_DIR", "").strip()
                            or _p("index"))
CHUNKS_JSONL = os.path.join(INDEX_DIR, "chunks.jsonl")
EMBED_NPY = os.path.join(INDEX_DIR, "embeddings.npy")
EMBED_META = os.path.join(INDEX_DIR, "embeddings.meta.json")

# ── 매뉴얼 파일 ↔ 기기 매핑 ─────────────────────────────────
# 청크에 device 를 달아둬야 태그 기준으로 후보를 좁힐 수 있다.
MANUAL_DEVICE = {
    "im_e_sievers-m9-manual_dlm_77020-02.pdf": "M9e",
    "OM_Transmitter_M300_en_52121389_Dec14.pdf": "M300",
    "et200sp_ha_AI_16xI_2-wire_HART_HA_en-US_en-US.pdf": "AI 16xI 2-wire HART HA",
    "C35-36UM.pdf": "C35/36",
}

# I/O 카드는 어느 계기 태그에서도 근거가 될 수 있다.
# 계기 진단과 카드 채널 진단이 함께 걸려야 하는 경우가 실제로 많다.
CARD_DEVICE = "AI 16xI 2-wire HART HA"

# ── 청킹 ────────────────────────────────────────────────────
CHUNK_TARGET_CHARS = 900     # 목표 청크 길이
CHUNK_MAX_CHARS = 1600       # 이 이상이면 강제 분할
CHUNK_OVERLAP_CHARS = 150    # 문맥 유지를 위한 겹침
CHUNK_MIN_CHARS = 120        # 이보다 짧으면 앞 청크에 흡수

# ── 검색 ────────────────────────────────────────────────────
BM25_TOP_K = 40              # 어휘 검색 후보 수
DENSE_TOP_K = 40             # 벡터 검색 후보 수
RRF_K = 60                   # Reciprocal Rank Fusion 상수
FUSED_TOP_K = 30             # 리랭커에 넘길 후보 수
FINAL_TOP_K = 5              # 최종 근거 개수

# ── 모델 ────────────────────────────────────────────────────
# 임베딩 제공자. 사내 Azure OpenAI 를 쓸 것이므로 azure 가 기본이다.
#   azure   사내 Azure OpenAI  (AOAI_* 환경변수)
#   openai  OpenAI 호환 엔드포인트
#   ollama  로컬 (외부망에서 임시로 쓸 때만)
#
# 어느 쪽이든 조건은 하나다 — **다국어 임베딩일 것.** v1 의 KO_EN 사전을
# 지우고 한글 질의를 영문 매뉴얼에 직접 붙이는 것이 v2 의 논지이므로,
# 영어 전용 임베딩으로 바꾸면 그 논지가 무너진다.
def _index_embed_identity():
    """이미 만들어 둔 색인이 어느 임베딩으로 만들어졌는지 읽는다.

    기본값을 azure 로 고정해 두면, 색인은 ollama/bge-m3 로 만들어 놓고
    환경변수 없이 띄웠을 때 서명이 어긋나 dense 가 조용히 강등된다
    (run_check.bat 을 거치면 맞지만, 거치지 않는 경로가 있다).
    색인이 있으면 그 신원을 기본값으로 삼고, 환경변수가 있으면 그것이 이긴다.
    """
    try:
        import json as _json
        with open(EMBED_META, encoding="utf-8") as fh:
            m = _json.load(fh)
        return (str(m.get("provider") or "").lower() or None,
                str(m.get("model") or "") or None)
    except Exception:
        return None, None


_IDX_PROVIDER, _IDX_MODEL = _index_embed_identity()

EMBED_PROVIDER = os.environ.get("COPILOT_EMBED_PROVIDER",
                                _IDX_PROVIDER or "azure").lower()

# Azure OpenAI — 키는 코드에 적지 않는다. 환경변수로만 받는다.
AOAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
AOAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AOAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
AOAI_EMBED_DEPLOYMENT = os.environ.get(
    "AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-large")

# OpenAI 호환
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL",
                                 "https://api.openai.com/v1").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Ollama (외부망 대체용)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

_EMBED_DEFAULT = {
    "azure": AOAI_EMBED_DEPLOYMENT,
    "openai": "text-embedding-3-large",
    "ollama": "bge-m3",
}
EMBED_MODEL = os.environ.get(
    "COPILOT_EMBED_MODEL",
    (_IDX_MODEL if _IDX_PROVIDER == EMBED_PROVIDER else None)
    or _EMBED_DEFAULT.get(EMBED_PROVIDER, "bge-m3"))
# 차원은 응답에서 읽는다. 제공자마다 다르므로(bge-m3 1024,
# text-embedding-3-large 3072) 여기 박아두면 캐시가 조용히 어긋난다.
EMBED_BATCH = int(os.environ.get("COPILOT_EMBED_BATCH", "32"))

# 임베딩 캐시의 신원. 제공자나 모델이 바뀌면 캐시를 재사용하면 안 된다.
def embed_signature():
    return "%s/%s" % (EMBED_PROVIDER, EMBED_MODEL)


# 리랭커는 제공자와 무관하다 — sentence-transformers 로 로컬 실행.
#     pip install sentence-transformers
RERANK_MODEL = os.environ.get("COPILOT_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
RERANK_ENABLED = os.environ.get("COPILOT_RERANK", "1") != "0"

# 카드(ET200SP) 근거를 상위에 몇 건까지 남길지. 카드 매뉴얼은 어느 태그로
# 물어도 통과시키는데, 실물 색인에서는 분량이 커서 그냥 두면 상위를 독식한다.
# 해당 기기의 근거가 하나라도 있을 때만 이 상한이 걸린다.
CARD_MAX_HITS = int(os.environ.get("COPILOT_CARD_MAX", "1"))
# 남긴 카드 근거를 몇 번째에 끼울지 — 해당 기기 근거 뒤가 기본이다.
CARD_INSERT_AT = int(os.environ.get("COPILOT_CARD_AT", "3"))

# 조치 생성 LLM — v1 advisor.py 와 동일한 제공자 체계를 따른다.
LLM_PROVIDER = os.environ.get("COPILOT_PROVIDER", "ollama").lower()
LLM_MODEL = os.environ.get("COPILOT_MODEL", "qwen2.5:7b-instruct")

# ── 근거 한국어 요약 (화면 표시용) ──────────────────────────
# 알람 조회 응답에 붙는 한 줄 요약이다. 검색·판정은 1ms 안에 끝나는데
# 이 요약이 근거마다 LLM 을 한 번씩 부르느라 조회 전체가 1~2분씩 걸렸다.
# 요약은 **읽기 편하라고 붙이는 덤**이지 판단 근거가 아니다. 그래서
#   · 개수를 줄이고(SUMMARY_MAX)
#   · 짧게 끊고(SUMMARY_NUM_PREDICT — 한두 문장이면 충분하다)
#   · 작은 모델로 돌릴 수 있게 하고(SUMMARY_MODEL)
#   · 통째로 끌 수 있게(COPILOT_SUMMARY=off) 두었다.
# 호출 자체는 api/server.py 에서 병렬로 던진다.
SUMMARY_KO = os.environ.get("COPILOT_SUMMARY", "on").lower() != "off"
SUMMARY_MODEL = os.environ.get("COPILOT_SUMMARY_MODEL", "").strip() or LLM_MODEL
SUMMARY_TIMEOUT = int(os.environ.get("COPILOT_SUMMARY_TIMEOUT", "20"))
SUMMARY_MAX = int(os.environ.get("COPILOT_SUMMARY_MAX", "3"))
SUMMARY_NUM_PREDICT = int(os.environ.get("COPILOT_SUMMARY_TOKENS", "120"))

# ── 결과 구성 다양성 ────────────────────────────────────────
# 상위 결과에 코드표·매뉴얼 본문 두 층과, 계기·카드 두 기기 축이
# 각각 최소 1건씩 남도록 보장한다. 순위를 바꾸는 것이 아니라 잘려나갈
# 자리 하나를 빠진 계층에 내주는 방식이다. 끄면 순수 유사도 순위가 된다.
#   off   순수 유사도 순위 (기존 동작)
#   kind  코드표·본문 두 층을 확보
#   all   위 + 계기·카드 두 기기 축까지 확보
# 기본값을 kind 로 둔 것은 기기 축 확보가 득실이 갈릴 수 있기 때문이다.
# 무관한 카드 항목이 상위로 올라오면 정답을 밀어낼 수 있으므로,
# all 채택 여부는 평가로 확인한 뒤 정한다.
DIVERSIFY = os.environ.get("COPILOT_DIVERSIFY", "off").lower()
DIVERSIFY_WINDOW = int(os.environ.get("COPILOT_DIVERSIFY_WINDOW", "3"))

# 챗봇이 매뉴얼 근거로 답할지 여부. 끄면 명령 해석만 한다.
CHAT_QA = os.environ.get("COPILOT_CHAT_QA", "1") != "0"

# ── CRAG 루프 ───────────────────────────────────────────────
GRADE_THRESHOLD = float(os.environ.get("COPILOT_GRADE_THRESHOLD", "0.5"))
MAX_REWRITES = 2             # 질의 재작성 최대 횟수

# ── 근거 충분성 채점 가중치 ─────────────────────────────────
# 규칙 기반 채점기(graph/nodes.py: grade)가 쓰는 배점표.
#
# 설계 원칙: 평가셋 정답을 보고 맞춘 값이 아니라, "어떤 신호가 근거를
# 신뢰하게 만드는가"를 먼저 정하고 배점한 값이다. 값은 여기 한 곳에만
# 있고 describe() 로 스코어카드에 기록되므로 나중에 검증 가능하다.
#
# 신호를 고른 기준: **질의 언어에 의존하지 않을 것.** 이전 배점표는
# 질의어가 근거 본문에 글자 그대로 나타나는지만 봤기 때문에, 한글 질의는
# 영문 매뉴얼에서 구조적으로 0점이었다. 검색이 정답을 찾아와도 채점에서
# 떨어져 거절되는 구조였다.
GRADE_W = {
    "exact_code":      0.55,   # 코드 완전일치 — 검색이 아니라 조회다
    "top1_code":       0.20,   # 1위가 코드표 항목
    "top1_manual":     0.15,   # 1위가 매뉴얼 본문
    "dense_max":       0.30,   # 벡터 유사도 (언어 무관 신호)
    "consensus":       0.15,   # BM25 와 dense 가 같은 문서를 올림
    "rerank_max":      0.25,   # cross-encoder 점수
    "coverage_max":    0.35,   # 어휘 적중률 — 문자체계가 겹칠 때만 계산
    "device_same":     0.10,   # 상위 근거의 기기가 일치
    "device_scatter": -0.20,   # 상위 근거의 기기가 3종 이상으로 흩어짐
}
# 벡터 유사도 정규화 구간. bge-m3 의 한↔영 교차언어 유사도는 정답 매칭에서
# 대략 0.5~0.7 에 분포한다. 0.35 미만은 0점, 0.60 이상은 만점으로 본다.
GRADE_DENSE_LO, GRADE_DENSE_HI = 0.35, 0.60
# cross-encoder 는 로짓을 뱉는다. 0 부근이 경계, 4 이상이면 확신.
GRADE_RERANK_LO, GRADE_RERANK_HI = 0.0, 4.0


def describe():
    """실험 조건을 스코어카드에 박아넣기 위한 한 줄 요약."""
    return ("bm25=%d dense=%d rrf_k=%d fused=%d final=%d rerank=%s embed=%s "
            "grade_thr=%.2f max_rewrites=%d diversify=%s"
            % (BM25_TOP_K, DENSE_TOP_K, RRF_K, FUSED_TOP_K, FINAL_TOP_K,
               RERANK_MODEL if RERANK_ENABLED else "off", embed_signature(),
               GRADE_THRESHOLD, MAX_REWRITES,
               DIVERSIFY))
