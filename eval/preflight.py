#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preflight.py — 데모/평가 직전 환경 점검

무엇 하나가 빠지면 어디서 조용히 무너지는지 미리 알려준다. 특히
Ollama 가 안 떠 있으면 hybrid/full 이 렉시컬로 강등되는데, 그 상태로
스코어카드를 뽑으면 v2 를 v1 보다 못한 것으로 증명하게 된다.

    python -m eval.preflight
    python -m eval.preflight --strict     # 하나라도 실패하면 종료코드 1
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

OK, WARN, FAIL = "OK  ", "주의", "실패"
_rows = []


def check(name, fn, fix="", critical=True):
    try:
        ok, detail = fn()
    except Exception as e:                                  # noqa: BLE001
        ok, detail = False, "%s: %s" % (type(e).__name__, e)
    status = OK if ok else (FAIL if critical else WARN)
    _rows.append((status, name, detail, "" if ok else fix))
    return ok


# ── 개별 점검 ───────────────────────────────────────────────
def c_data_dir():
    """자료 폴더 — 이제 data/ 한 곳이다."""
    missing = []
    for label, path in (("IO List", config.IO_LIST),
                        ("계기 리스트", config.INSTRUMENT_SPEC),
                        ("인터락 리스트", config.INTERLOCK_XLSX)):
        if not os.path.isfile(path):
            missing.append("%s(%s)" % (label, os.path.basename(path)))
    if missing:
        return False, "%s — 없음: %s" % (config.DATA_DIR, ", ".join(missing))
    return True, config.DATA_DIR


def c_manuals():
    d = config.MANUAL_DIR
    if not os.path.isdir(d):
        return False, "폴더 없음: %s" % d
    n = len([f for f in os.listdir(d) if f.lower().endswith(".pdf")])
    return n >= 4, "%s (PDF %d개)" % (d, n)


def c_index():
    p = config.CHUNKS_JSONL
    if not os.path.isfile(p):
        return False, "없음"
    import json
    kinds = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            k = json.loads(line).get("kind")
            kinds[k] = kinds.get(k, 0) + 1
    body = kinds.get("manual_text", 0)
    return body > 0, ", ".join("%s %d" % kv for kv in sorted(kinds.items()))


def c_embed_conf():
    """자격증명이 갖춰졌는가 — 네트워크를 건드리기 전에 먼저 본다."""
    p = config.EMBED_PROVIDER
    if p == "azure":
        miss = []
        if not config.AOAI_ENDPOINT:
            miss.append("AZURE_OPENAI_ENDPOINT")
        if not config.AOAI_API_KEY:
            miss.append("AZURE_OPENAI_API_KEY")
        if not config.AOAI_EMBED_DEPLOYMENT:
            miss.append("AZURE_OPENAI_EMBED_DEPLOYMENT")
        if miss:
            return False, "미설정: " + ", ".join(miss)
        return True, "%s / 배포 %s / api-version %s" % (
            config.AOAI_ENDPOINT, config.AOAI_EMBED_DEPLOYMENT,
            config.AOAI_API_VERSION)
    if p == "openai":
        if not config.OPENAI_API_KEY:
            return False, "미설정: OPENAI_API_KEY"
        return True, "%s / %s" % (config.OPENAI_BASE_URL, config.EMBED_MODEL)
    if p == "ollama":
        return True, "%s / %s" % (config.OLLAMA_URL, config.EMBED_MODEL)
    return False, "알 수 없는 제공자: %s" % p


def c_embed():
    from retrieval.dense import embed_batch
    v = embed_batch(["점검"], timeout=60, retries=1)
    return v.shape[1] > 0, "%s dim=%d" % (config.embed_signature(), v.shape[1])


def c_embed_multilingual():
    """
    다국어인지 실제로 확인한다.

    v2 의 논지는 '사전 없이 한글 질의가 영문 매뉴얼에 붙는다'이다.
    영어 전용 임베딩으로 바뀌면 논지가 무너지는데, 오류는 안 나고
    검색 품질만 조용히 떨어진다. 같은 뜻의 한/영 문장 유사도가 무관한
    문장보다 확실히 높은지 한 번 재 둔다.
    """
    import numpy as np
    from retrieval.dense import embed_batch, l2norm
    v = l2norm(embed_batch([
        "산화제 용기의 잔량이 부족합니다",
        "The estimated volume of oxidizer is low",
        "Pin assignment of the analog input card",
    ], timeout=60, retries=1))
    same = float(v[0] @ v[1])
    diff = float(v[0] @ v[2])
    return same > diff + 0.05, "한↔영 동의 %.3f / 무관 %.3f" % (same, diff)


def c_embed_cache():
    if not os.path.isfile(config.EMBED_NPY):
        return False, "없음 — 첫 질의에서 전체 임베딩(수 분)이 돌아간다"
    import json
    import numpy as np
    m = np.load(config.EMBED_NPY, mmap_mode="r")
    meta = json.load(open(config.EMBED_META, encoding="utf-8"))
    sig = meta.get("signature")
    from ingest.build_index import load as load_index
    same_ids = meta.get("ids") == [r["id"] for r in load_index()]
    if sig is None:
        return False, "구버전 캐시(제공자 정보 없음) — 재구축 필요"
    if sig != config.embed_signature():
        return False, "다른 모델로 만들어짐: %s ≠ %s" % (
            sig, config.embed_signature())
    if not same_ids:
        return False, "색인 내용이 바뀜 — 재구축 필요"
    return True, "%s %s (%s)" % (config.EMBED_NPY, m.shape, sig)


def c_rerank():
    if not config.RERANK_ENABLED:
        return False, "COPILOT_RERANK=0 으로 꺼져 있음"
    from retrieval import fusion
    fusion.get_reranker()
    return True, config.RERANK_MODEL


def c_font():
    from api.report_4d import _register_fonts
    _register_fonts()
    p = os.environ.get("PMC_KR_FONT")
    if p:
        return True, p
    return False, os.environ.get("PMC_KR_FONT_ERRORS", "")[:120]


def c_advisor():
    """조치 생성 LLM. 없어도 근거 나열 템플릿으로 동작하므로 필수는 아니다."""
    from graph.advisor import available
    ok, why = available()
    return ok, why


def c_interlock():
    p = config.INTERLOCK_XLSX
    if not os.path.isfile(p):
        return False, "없음: %s" % p
    from ingest.interlock import load_interlocks
    items = load_interlocks()
    conds = sum(len(i.get("conditions", [])) for i in items)
    unparsed = sum(1 for i in items for c in i.get("conditions", [])
                   if not c.get("parsed"))
    return bool(items), "%d건 / 조건 %d개 (미파싱 %d)" % (
        len(items), conds, unparsed)


def c_deps():
    missing = []
    for m in ("numpy", "openpyxl", "fastapi", "uvicorn", "reportlab",
              "langgraph", "pymupdf"):
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    return not missing, "없음: %s" % ", ".join(missing) if missing else "전부 있음"


def main():
    ap = argparse.ArgumentParser(description="환경 점검")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    print("\nPlant Maintenance Copilot v2 — 환경 점검\n" + "=" * 78)

    hard = []
    hard.append(check("파이썬 패키지", c_deps,
                      "pip install -r requirements.txt"))
    hard.append(check("자료 폴더", c_data_dir,
                      "data/ 에 IO List·계기 리스트·인터락 리스트를 넣으십시오"))
    check("매뉴얼 PDF", c_manuals, "data/manuals 에 PDF 를 넣으십시오",
          critical=False)
    hard.append(check("검색 인덱스", c_index, "python -m ingest.build_index"))
    hard.append(check("임베딩 자격증명", c_embed_conf,
                      "사내 AOAI 환경변수를 설정하십시오 (run_claude.bat 참고)"))
    hard.append(check("임베딩 호출", c_embed,
                      "엔드포인트·배포 이름·사내망 접속을 확인하십시오"))
    check("임베딩 다국어성", c_embed_multilingual,
          "한↔영 유사도가 낮으면 영어 전용 모델입니다 — v2 논지가 무너집니다",
          critical=False)
    check("임베딩 캐시", c_embed_cache,
          "python -m retrieval.dense", critical=False)
    check("리랭커", c_rerank,
          "pip install sentence-transformers (최초 2.2GB 내려받음)",
          critical=False)
    check("한글 PDF 폰트", c_font,
          "api/fonts/NanumGothic.ttf 동봉 — 없으면 4D 리포트 한글이 깨진다",
          critical=False)
    check("조치 생성 LLM", c_advisor,
          "ollama pull %s — 없으면 근거 나열만 표시됩니다" % config.LLM_MODEL,
          critical=False)
    check("인터락 리스트", c_interlock,
          "python -m data.make_interlock_list --out data", critical=False)

    w = max(len(r[1]) for r in _rows)
    for status, name, detail, fix in _rows:
        print("[%s] %-*s  %s" % (status, w, name, detail))
        if fix:
            print("      → %s" % fix)
    print("=" * 78)

    bad = [r for r in _rows if r[0] == FAIL]
    warn = [r for r in _rows if r[0] == WARN]
    if bad:
        print("실패 %d건 — 이 상태로 평가를 돌리면 hybrid/full 열이 비거나 "
              "강등된 결과가 나옵니다." % len(bad))
    elif warn:
        print("필수 항목은 통과. 주의 %d건은 데모 품질에만 영향합니다." % len(warn))
    else:
        print("전부 통과. `python -m eval.run_eval_v2 --md eval/scorecard_v2.md` 진행 가능.")
    print()
    return 1 if (bad and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
