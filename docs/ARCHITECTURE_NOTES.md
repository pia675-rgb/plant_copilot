# Plant Maintenance Copilot v2

v1(Grok 작업본)은 **건드리지 않는다.** v2는 별도 디렉토리에서 v1의
산출 데이터(매뉴얼 PDF, 코드표, 계기 리스트, 보수 이력, 합성 도면)만
읽어 쓴다. 같은 평가셋으로 둘을 나란히 채점하는 것이 목표다.

## v1과 무엇이 다른가

| | v1 | v2 |
|---|---|---|
| 검색 대상 | 코드표 306건 | 코드표 306건 + **매뉴얼 본문 1,520청크** |
| 어휘 검색 | IDF 가중 키워드 | BM25 (문서 길이 정규화) |
| 한글 질의 | `KO_EN` 수동 사전 | **다국어 임베딩** — 사전 없음 |
| 순위 융합 | 없음 | RRF |
| 재정렬 | 없음 | cross-encoder (bge-reranker-v2-m3) |
| 검색 실패 시 | 그대로 진행 | **채점 → 재질의 → 거절** (CRAG) |
| 인터락 | 없음 | 태그 기준 조회 (층 분리) |
| 판넬 | 없음 | **위치 배치도 + 상실 영향 역조회** |

가장 큰 변화는 첫 줄이다. v1은 코드표만 검색해서 "코드표에 없는 증상"에
구조적으로 답할 수 없었다. 본문을 넣으면 검색 대상이 6배가 되고,
그때부터 임베딩과 리랭커가 **필요해진다.**

두 번째로 중요한 것은 `KO_EN` 사전 제거다. v1의 사전은 평가셋 용어에
맞춰져 있어 20/20이 나올 수밖에 없는 구조였다. 사전을 지우고 다국어
임베딩에 맡기면 그 의혹이 구조적으로 사라진다.

임베딩 제공자는 갈아끼울 수 있다(`COPILOT_EMBED_PROVIDER`). 특정 벤더를
붙이는 것이 목적이 아니라 사전을 지우는 것이 목적이기 때문이다.

## 디렉토리

```
copilot_v2/
  config.py              모든 경로·하이퍼파라미터·모델명 (실험 조건 기록용)
  ingest/
    chunker.py           매뉴얼 PDF → 목차 기반 섹션 청크, 머리말/꼬리말 제거
    build_index.py       코드표 + 본문청크 → index/chunks.jsonl
  retrieval/
    bm25.py              BM25 + 코드 완전일치 조회
    dense.py             다국어 임베딩 (azure / openai / ollama 전환)
    fusion.py            RRF + cross-encoder 재정렬
    pipeline.py          Retriever — mode 로 lexical/hybrid/full 전환
  graph/
    nodes.py             CRAG 상태·노드 (retrieve/grade/rewrite/advise/abstain)
    app_graph.py         LangGraph 조립 + CLI
    panel_index.py       판넬 역인덱스 — 위치·상실 영향·단품 고장
  data/
    make_arrangement.py  합성 배치도 + PANEL_LOCATIONS.csv (같은 원천)
  eval/                  평가셋 및 채점
  data/                  자료 — DATA_README.md 참고
  docs/                  패치 노트
  legacy_v1/             v1 원본 코드 (A/B 비교용 보존)
  ui/                    Streamlit (다음 단계)
  index/                 생성물 — 커밋하지 않음
```

## 준비

```bash
pip install -r requirements.txt
```

임베딩은 사내 Azure OpenAI 를 쓴다. 키는 코드에 적지 않고 환경변수로만 받는다.

```
AZURE_OPENAI_ENDPOINT           https://<리소스>.openai.azure.com
AZURE_OPENAI_API_KEY
AZURE_OPENAI_EMBED_DEPLOYMENT   임베딩 배포 이름
AZURE_OPENAI_API_VERSION        (기본 2024-02-01)
```

외부망에서 임시로 돌려야 하면 `COPILOT_EMBED_PROVIDER=ollama` 로 바꾼다.
어느 쪽을 썼는지는 스코어카드의 `embed=` 항목에 그대로 기록된다.

`bge-reranker-v2-m3`는 최초 실행 시 자동으로 내려받는다(약 2.2GB).
CPU에서 후보 30건 재정렬에 수 초 걸린다. 느리면
`COPILOT_RERANK=0`으로 끄고 hybrid 모드로 비교한다.

## 실행

```bash
# 1) 인덱스 생성 (매뉴얼 청킹 포함, 1~2분)
python -m ingest.build_index

# 2) 검색만 확인
python -m retrieval.pipeline --mode lexical --tag AIT-4002 --alarm "산 잔량 부족"
python -m retrieval.pipeline --mode full    --tag AIT-4002 --alarm "산 잔량 부족"

# 3) CRAG 루프까지
python -m graph.app_graph --mode full --tag AIT-4002 --alarm "누수가 있는 것 같다"
```

## 실험 설계

`mode` 세 가지를 같은 평가셋으로 돌려 표를 만든다.

- `lexical` — BM25 단독 (사전 없는 v1 상당)
- `hybrid` — BM25 + dense + RRF
- `full` — 위 + cross-encoder 재정렬

발표에서 말할 것은 "리랭커를 붙였습니다"가 아니라
"붙여서 Top-1이 몇 점 올랐습니다"이다. 그래서 `config.describe()`가
실험 조건 한 줄을 스코어카드에 박아 넣는다.

## 인터락 조회 (v2 추가 기능)

현장 문의의 대부분은 고장 진단이 아니라 **출력 태그의 동작 조건**이다.
"이 밸브는 언제 열리나". 그래서 인터락 리스트를 두 번째 근거 소스로 넣었다.

```bash
python -m data.make_interlock_list --out data   # 합성 리스트 생성
python -m ingest.interlock --stats --unparsed   # 파싱 결과 확인
python -m retrieval.interlock_index --tag XV-4101 --action OPEN
python -m retrieval.interlock_index --tag AIT-4002 --input
```

설계 원칙 세 가지.

1. **층을 나눈다.** 인터락 → 퍼미시브 → 시퀀스 → 수동 순.
   "조건은 다 맞는데 왜 안 열리지"의 답은 거의 항상 첫 층에 있다.
   전부 한 덩어리로 나열하면 엑셀을 직접 보는 것과 같다.
2. **LLM 이 만들지 않는다.** 인터락은 안전 로직이라 환각이 곧 사고다.
   조회 결과는 리스트에 적힌 것을 그대로 옮긴다. LLM 은 엑셀 자연어 조건을
   구조화하는 **오프라인 전처리**에만 쓴다(사람 검수 전제).
3. **못 읽은 조건은 비워둔다.** 규칙 파서가 확신 없는 조건은 `parsed=False`
   로 남기고 원문을 보존한다. 추측해서 채우지 않는다.

현재 합성 리스트 기준 조건 92건 중 91건(99%) 구조화, 1건은 원문 유지.

### 연쇄 추적

```bash
python -m retrieval.cascade --tag XV-3102 --state CLOSE --depth 5
```

전파 규칙은 두 가지뿐이다.

- `INTERLOCK(OR)` 조건 하나라도 성립 → 출력이 그 ACTION 으로 강제
- `PERMISSIVE(AND)` 조건 하나라도 불만족 → 허가 상실 → 반대 상태로 귀결

**한계를 분명히 한다.** 이 그래프는 *로직* 그래프지 *공정* 그래프가 아니다.
"밸브가 닫혀 수위가 떨어지고 그래서 펌프가 선다"는 인터락 리스트 어디에도
없다. 추정해서 그리지 않는다. 필요하면 `data/PROCESS_LINKS.csv` 에 사람이
직접 적고, 그 간선은 `※ 로직이 아닌 공정 연계`로 구분 표시된다.

여러 태그가 AND 로 묶인 조건(`P-2101A 및 P-2101B 모두 정지`)은 한쪽만
확정되면 성립을 단정하지 않고 `※ 나머지 태그 상태 확인 필요`로 표시한다.

## 남은 작업

- [ ] `eval/eval_set_v2.json` — 45문항. 사전에 없는 동의어, 오타 태그,
      코드표에 없는 증상, 벤더 간 코드번호 충돌, 거절이 정답인 문항
- [ ] `eval/run_eval_v2.py` — v1/lexical/hybrid/full 4열 비교 스코어카드
- [ ] `advisor` 연결 — v1 `advisor.py`의 근거 ID 검증을 그대로 재사용
- [ ] `ui/app.py` — trace(재질의 과정)와 인터락 층을 화면에 노출
- [ ] 실물 인터락 리스트 컬럼 구조 반영 (스키마 확정 후)
