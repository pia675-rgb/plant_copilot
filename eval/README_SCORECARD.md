# 스코어카드 재생성 (제출 전 필수)

## 왜 다시 돌리나

`lexical`만 채점하면 v2 논지(사전 제거 → 다국어 임베딩)가 **반박 표**로 읽힙니다.  
`hybrid` / `full` 열이 있어야 합니다.

## 절차

### 1) 임베딩 준비 (택 1)

**Ollama**

```bat
ollama pull bge-m3
ollama serve
```

**sentence-transformers (Ollama 없이)**

```bat
pip install sentence-transformers
set COPILOT_EMBED_BACKEND=st
```

### 2) 벡터 인덱스

```bat
python -c "from ingest.build_index import load; from retrieval.dense import DenseIndex; DenseIndex(load()).ensure()"
```

### 3) 채점

```bat
python -m eval.run_eval_v2 --systems v1,lexical,hybrid,full --md eval/scorecard_v2.md
```

또는 `scripts\run_scorecard.bat`

## 발표 해석

| 결과 | 메시지 |
|------|--------|
| hybrid/full 이 syn·body·typo 상승 | 사전 제거 + 임베딩 논지 유지 |
| 여전히 약함 | 「사전으로 못 덮는 영역 확장」+ 인터락/거절/원본 검증으로 프레임 전환 |

UI 기본 검색 모드는 **hybrid** 입니다.
