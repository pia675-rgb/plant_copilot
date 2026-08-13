#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dense.py — 벡터 검색 (다국어 임베딩)

이 계층이 v2 의 핵심 논거다. v1 은 한글 질의를 KO_EN 사전으로 영문에
번역해 넘겼고, 그 사전이 평가셋 용어에 맞춰져 있었다. 사전에 없는
동의어("누수", "새는", "흘러내림")는 전부 실패한다.

다국어 임베딩은 사전 없이 한글 질의를 영문 매뉴얼 청크에 직접 매칭한다.
사전을 지우는 것이 목적이지 특정 벤더의 임베딩을 붙이는 것이 목적이 아니다.
그래서 제공자를 갈아끼울 수 있게 두고, 무엇을 썼는지는 스코어카드에
`embed=azure/text-embedding-3-large` 형태로 기록된다.

제공자 (COPILOT_EMBED_PROVIDER)
    azure    사내 Azure OpenAI — 기본
    openai   OpenAI 호환 엔드포인트
    ollama   로컬 (외부망에서 임시로 쓸 때)

환경변수 (azure):
    AZURE_OPENAI_ENDPOINT           https://<리소스>.openai.azure.com
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_EMBED_DEPLOYMENT   임베딩 배포 이름
    AZURE_OPENAI_API_VERSION        (기본 2024-02-01)

인덱스는 한 번만 만들고 index/embeddings.npy 에 저장한다. 사내망에서만
API 가 열린다면 **사내망에서 캐시를 굽고 .npy 파일을 들고 나오면** 외부망
데모에서도 벡터 검색이 그대로 동작한다. 질의 임베딩만 API 가 필요하므로,
시연 질의를 미리 정해 두면 그것까지 캐시해 둘 수 있다(QueryCache).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def _match_device(record_device, allowed):
    """allowed 가 str 또는 list 일 수 있다. 부분 일치 허용."""
    if not allowed:
        return True
    if isinstance(allowed, str):
        allowed = [allowed]
    rd = (record_device or "").upper()
    for a in allowed:
        au = (a or "").upper()
        if not au:
            continue
        if rd == au or au in rd or rd in au:
            return True
    if getattr(config, "CARD_DEVICE", None) and rd == str(config.CARD_DEVICE).upper():
        return True
    return False



class EmbedError(RuntimeError):
    pass


# ── 제공자별 호출 ───────────────────────────────────────────
def _post_json(url, payload, headers, timeout):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers,
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _embed_openai_style(texts, url, headers, model, timeout):
    payload = {"input": texts}
    if model:
        payload["model"] = model
    data = _post_json(url, payload, headers, timeout)
    # index 순서를 신뢰하지 않고 명시적으로 정렬한다.
    items = sorted(data["data"], key=lambda d: d.get("index", 0))
    return np.asarray([d["embedding"] for d in items], dtype="float32")


def _embed_azure(texts, timeout):
    if not config.AOAI_ENDPOINT or not config.AOAI_API_KEY:
        raise EmbedError(
            "AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY 가 설정되지 않았습니다.")
    url = "%s/openai/deployments/%s/embeddings?api-version=%s" % (
        config.AOAI_ENDPOINT, config.AOAI_EMBED_DEPLOYMENT,
        config.AOAI_API_VERSION)
    headers = {"Content-Type": "application/json",
               "api-key": config.AOAI_API_KEY}
    # Azure 는 배포에 모델이 묶여 있어 model 을 보내지 않는다.
    return _embed_openai_style(texts, url, headers, None, timeout)


def _embed_openai(texts, timeout):
    if not config.OPENAI_API_KEY:
        raise EmbedError("OPENAI_API_KEY 가 설정되지 않았습니다.")
    url = config.OPENAI_BASE_URL + "/embeddings"
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer %s" % config.OPENAI_API_KEY}
    return _embed_openai_style(texts, url, headers, config.EMBED_MODEL,
                               timeout)


def _embed_ollama(texts, timeout):
    url = config.OLLAMA_URL.rstrip("/") + "/api/embed"
    data = _post_json(url, {"model": config.EMBED_MODEL, "input": texts},
                      {"Content-Type": "application/json"}, timeout)
    vecs = data.get("embeddings") or [data["embedding"]]
    return np.asarray(vecs, dtype="float32")


_PROVIDERS = {"azure": _embed_azure,
              "openai": _embed_openai,
              "ollama": _embed_ollama}


def embed_batch(texts, timeout=300, retries=3):
    """
    현재 제공자로 임베딩. 실패 시 예외를 그대로 올린다.

    사내 API 는 레이트리밋(429)이 걸리므로 지수 백오프로 재시도한다.
    1,800여 청크를 굽는 도중에 한 번 튕겨서 처음부터 다시 하는 일을 막는다.
    """
    fn = _PROVIDERS.get(config.EMBED_PROVIDER)
    if fn is None:
        raise EmbedError("알 수 없는 임베딩 제공자: %s (가능: %s)"
                         % (config.EMBED_PROVIDER, ", ".join(_PROVIDERS)))
    last = None
    for attempt in range(retries):
        try:
            return fn(texts, timeout)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = 2 ** attempt * 5
                print("  임베딩 %d — %ds 후 재시도 (%d/%d)"
                      % (e.code, wait, attempt + 1, retries))
                time.sleep(wait)
                continue
            raise EmbedError("임베딩 요청 실패 %s: %s"
                             % (e.code, e.read()[:200])) from e
        except (urllib.error.URLError, OSError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise EmbedError("임베딩 엔드포인트에 연결할 수 없습니다: %s" % e) from e
    raise EmbedError("임베딩 실패: %s" % last)


def l2norm(m):
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


class DenseIndex:
    def __init__(self, records):
        self.records = records
        self.mat = None

    # ── 인덱스 구축 / 로드 ──────────────────────────────────
    def build(self, batch=None, verbose=True):
        batch = batch or config.EMBED_BATCH
        texts = [self._doc_text(r) for r in self.records]
        out = []
        for i in range(0, len(texts), batch):
            out.append(embed_batch(texts[i:i + batch]))
            if verbose:
                print("  임베딩 %d/%d" % (min(i + batch, len(texts)), len(texts)),
                      end="\r")
        self.mat = l2norm(np.vstack(out))
        os.makedirs(config.INDEX_DIR, exist_ok=True)
        np.save(config.EMBED_NPY, self.mat)
        with open(config.EMBED_META, "w", encoding="utf-8") as f:
            json.dump({"signature": config.embed_signature(),
                       "provider": config.EMBED_PROVIDER,
                       "model": config.EMBED_MODEL,
                       "dim": int(self.mat.shape[1]),
                       "ids": [r["id"] for r in self.records]}, f)
        if verbose:
            print("\n  벡터 저장: %s %s (%s)"
                  % (config.EMBED_NPY, self.mat.shape,
                     config.embed_signature()))
        return self

    def load(self, verbose=True):
        """
        저장된 벡터를 읽는다.

        id 뿐 아니라 **제공자·모델 서명도 대조한다.** 이전 버전은 id 만
        봤기 때문에, 임베딩 모델을 바꾸고 나서도 예전 벡터를 그대로
        재사용했다. 차원이 같으면 오류도 안 나고 검색 품질만 조용히
        무너진다 — 원인을 찾기 가장 어려운 종류의 고장이다.
        """
        if not (os.path.exists(config.EMBED_NPY)
                and os.path.exists(config.EMBED_META)):
            return None
        with open(config.EMBED_META, encoding="utf-8") as f:
            meta = json.load(f)

        sig = meta.get("signature")
        if sig is None:                     # 구버전 캐시 — 신원을 알 수 없다
            if verbose:
                print("  경고: 임베딩 캐시에 제공자 정보가 없습니다(구버전). "
                      "재구축합니다.")
            return None
        if sig != config.embed_signature():
            if verbose:
                print("  경고: 임베딩 캐시가 다른 모델로 만들어졌습니다 "
                      "(%s → %s). 재구축합니다." % (sig, config.embed_signature()))
            return None
        if meta.get("ids") != [r["id"] for r in self.records]:
            if verbose:
                print("  경고: 색인 내용이 바뀌었습니다. 재구축합니다.")
            return None

        self.mat = np.load(config.EMBED_NPY)
        return self

    def ensure(self):
        return self.load() or self.build()

    @staticmethod
    def _doc_text(r):
        # 섹션 제목을 붙여야 본문만으로는 모호한 청크가 구분된다.
        return (r["title"] + "\n" + r["text"])[:2000]

    # ── 검색 ────────────────────────────────────────────────
    def search(self, query, top_k=None, device=None):
        if self.mat is None:
            raise RuntimeError("벡터 인덱스가 없습니다. ensure() 를 먼저 호출하십시오.")
        top_k = top_k or config.DENSE_TOP_K
        qv = l2norm(embed_batch([query]))[0]
        if qv.shape[0] != self.mat.shape[1]:
            raise RuntimeError(
                "질의 벡터 차원(%d)이 인덱스(%d)와 다릅니다. "
                "임베딩 모델이 바뀌었습니다 — 인덱스를 재구축하십시오."
                % (qv.shape[0], self.mat.shape[1]))
        sims = self.mat @ qv
        if device:
            mask = np.array([_match_device(r["device"], device) for r in self.records])
            sims = np.where(mask, sims, -1.0)
        idx = np.argsort(-sims)[:top_k]
        return [(self.records[i], float(sims[i])) for i in idx if sims[i] > 0]


def available():
    """현재 제공자로 임베딩이 실제로 되는지 확인."""
    try:
        embed_batch(["ping"], timeout=20, retries=1)
        return True
    except Exception:                                       # noqa: BLE001
        return False


def why_unavailable():
    """실패 사유 문자열. 강등 메시지에 그대로 쓴다."""
    try:
        embed_batch(["ping"], timeout=20, retries=1)
        return None
    except Exception as e:                                  # noqa: BLE001
        return str(e)


def main():
    import argparse
    from ingest.build_index import load as load_index
    ap = argparse.ArgumentParser(description="임베딩 인덱스 구축")
    ap.add_argument("--rebuild", action="store_true",
                    help="캐시가 유효해도 다시 만든다")
    args = ap.parse_args()
    print("제공자: %s" % config.embed_signature())
    recs = load_index()
    di = DenseIndex(recs)
    if args.rebuild:
        di.build()
    else:
        di.ensure()
    print("완료: %s" % (di.mat.shape,))


if __name__ == "__main__":
    main()
