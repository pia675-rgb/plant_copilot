# v2.2 개선 패치 — 무엇을 왜 고쳤나

기존 트리 위에 덮어쓰면 됩니다. 데이터·인덱스·인터락 파서는 건드리지 않았습니다.

```
config.py                 배점표 상수 추가, describe() 확장, SyntaxWarning 제거
graph/nodes.py            ★ 근거 충분성 채점기 재설계
graph/app_graph.py        strict 전달, label 노출
retrieval/fusion.py       RRF 가 검색기 원점수를 버리지 않도록
retrieval/dense.py        ★ 임베딩 제공자 전환 (azure/openai/ollama), 캐시 신원 검사
retrieval/pipeline.py     ★ 무음 강등 차단 (strict / degraded / label)
eval/run_eval_v2.py       ★ 기본 4구성, 강등 라벨링, 실패 문항 부록
eval/preflight.py         (신규) 환경 점검
api/server.py             기본 모드 hybrid, /api/health 에 강등 노출
ui/react/src/App.jsx      기본 모드 hybrid, 강등 경고 배너
ui/react/src/index.css    배너 스타일
run_claude.bat            (신규) 사내 AOAI 환경변수 + 실행
README.md / requirements.txt  임베딩 제공자 설명 갱신
.gitignore                (신규) node_modules·임베딩 캐시 제외
```

---

## 1. ★ 채점기가 한글 질의를 구조적으로 0점 처리하고 있었습니다

이게 제일 큰 문제였고, hybrid/full 을 돌린다고 해서 저절로 낫지 않는
문제였습니다. 확인한 실제 값입니다 (기존 코드, lexical):

```
abstain 0.40  "acid residual low"                 ← 정답 근거를 2~5위로 다 찾아왔는데도 거절
abstain 0.20  "UV 램프는 얼마나 자주 교체해야 하나요"
abstain 0.07  "전도도 센서 1점 교정 절차를 알려주세요"
```

원인은 `grade()` 의 배점 구조입니다. 코드 완전일치(+0.6)가 없으면
최대치가 `0.2 + 0.3 × 어휘적중률`이라, 임계값 0.5 를 넘으려면 질의어가
근거 본문에 **100%** 그대로 나타나야 했습니다. 한글 질의를 영문 매뉴얼에
대고 글자 일치를 세면 언제나 0 입니다. 검색기가 정답을 1위로 올려도
채점에서 떨어집니다.

즉 `과잉거절 없음 9/39`은 임계값 튜닝 문제가 아니라 **채점 신호가 잘못
고른 문제**였습니다. 이 상태로는 bge-m3 를 붙여도 CRAG 가 계속 거절합니다.

### 고친 방향 — 질의 언어에 의존하지 않는 신호로 교체

| 신호 | 배점 | 성격 |
|---|---|---|
| 코드 완전일치 | 0.55 | 조회 |
| 1위가 코드표 / 본문 | 0.20 / 0.15 | 구조 |
| **벡터 유사도** | 0.30 | **언어 무관** |
| **어휘·벡터 검색 합의** | 0.15 | **언어 무관** |
| 재정렬 점수 | 0.25 | 언어 무관 |
| 어휘 적중률 | 0.35 | 문자체계가 겹칠 때만 |
| 기기 일치 / 흩어짐 | +0.10 / −0.20 | 구조 |

핵심은 마지막에서 두 번째 줄입니다. 한글 질의 ↔ 영문 문서처럼 문자체계가
겹치지 않으면 어휘 적중률을 **0점이 아니라 '측정 불가'로 처리**하고,
벡터 유사도와 검색기 합의로 대신 판단합니다. 적중률 0 과 측정 불가는
다른 것인데 기존 코드가 같게 다뤘습니다.

배점표는 `config.GRADE_W` 한 곳에 있고 `describe()` 로 스코어카드에
찍히므로 나중에 검증할 수 있습니다. 평가셋 정답을 보고 맞춘 값이 아니라
"어떤 신호가 근거를 신뢰하게 만드는가"를 먼저 정하고 배점한 값입니다.

### 이 변경 후 (lexical, 실측)

```
advise  1.00  code=10084                      ← 코드 조회
advise  0.60  "acid motor low current"
abstain 0.48  "acid residual low"             ← 1위가 Modbus Map 잡음 청크. 경계값
abstain 0.00  "옥시다이저 통 잔량이 부족하답니다"   ← BM25 는 실제로 못 찾음. 정직한 거절
abstain 0.00  "압력 지시가 이상합니다" (PIT-2003)  ← 벤더 문서 없음. 의도된 거절
```

렉시컬이 한글에 거절하는 건 **버그가 아니라 사실**입니다. hybrid 에서
같은 질의가 통과하면 모드 간 차이가 스코어카드에 성능 차이로 드러납니다.
이게 발표에서 하려던 이야기입니다.

> **hybrid/full 을 돌린 뒤 반드시 할 일**
> `--dump-grades` 로 `eval/grades_dump.json` 을 뽑아 정답 문항의 점수 분포를
> 보십시오. 정답인데 0.45~0.50 에 몰려 있으면 `COPILOT_GRADE_THRESHOLD=0.45`
> 로 조정하고 **그 값을 스코어카드에 남기십시오**(describe() 가 자동으로 찍습니다).
> 저는 Ollama 없이 검증했으므로 벡터 구간(0.35~0.60)은 실측으로 확인해야 합니다.

## 2. ★ 무음 강등이 스코어카드를 오염시키고 있었습니다

`Retriever` 는 Ollama 가 없으면 경고 한 줄 찍고 렉시컬로 내려갔습니다.
그 결과가 `hybrid` 라는 이름으로 표에 실릴 수 있는 구조였습니다.

이제 `strict=True` 면 예외를 던지고, 평가 러너는 그 열을 **'미실행'로 비워
둡니다.** 빈칸이 거짓 숫자보다 낫습니다. 실행은 되지만 일부만 강등된 경우
`hybrid→lexical(강등:dense)` 같은 라벨이 표 머리에 그대로 박힙니다.

## 3. 평가 러너 기본값을 네 구성 전부로

`--systems` 기본값이 `v1,lexical` 이라 v2 의 논지를 증명할 열이 아예 없는
표가 나왔습니다. 이제 기본이 `v1,lexical,hybrid,full` 입니다.

부수적으로 채점 버그 하나를 고쳤습니다. `거절` 항목이 `expect_abstain` 키만
봤는데 평가셋은 `type: "abstain"` 으로 표기합니다. 6문항 중 3문항이 채점에서
빠져 있었습니다 (`3/3` → `6/6`).

**실패 문항 부록**이 스코어카드 끝에 붙습니다. 문항·질의·기대·실제 상위·
실패 항목·판정을 한 표로 보여줍니다. 발표 준비 때 볼 것은 이쪽입니다.

## 3-2. ★ 임베딩을 사내 Azure OpenAI 로 (Ollama 제거)

`dense.py` 가 Ollama `/api/embed` 에 직접 묶여 있었습니다. 제공자를
갈아끼울 수 있게 바꿨습니다 — 기본은 `azure` 입니다.

```
COPILOT_EMBED_PROVIDER = azure | openai | ollama
AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY
AZURE_OPENAI_EMBED_DEPLOYMENT / AZURE_OPENAI_API_VERSION
```

특정 벤더를 붙이는 게 목적이 아니라 **KO_EN 사전을 지우는 것**이 목적이므로,
무엇을 썼는지는 스코어카드에 `embed=azure/text-embedding-3-large` 로 기록됩니다.

같이 고친 것 세 가지입니다.

- **캐시 신원 검사.** 기존 `load()` 는 청크 id 만 대조했습니다. 임베딩
  모델을 바꿔도 차원만 같으면 예전 벡터를 그대로 재사용하고, 오류 없이
  검색 품질만 무너집니다. 이제 `provider/model` 서명을 함께 저장·대조하고
  질의 벡터 차원도 검사합니다. **기존 캐시는 서명이 없어 자동 재구축됩니다.**
- **429 재시도.** 사내 API 는 레이트리밋이 걸립니다. 1,800여 청크를 굽다가
  한 번 튕겨서 처음부터 다시 하는 일이 없도록 지수 백오프를 넣었습니다.
- **다국어성 점검.** preflight 가 한↔영 동의문 유사도와 무관 문장 유사도를
  실제로 재 봅니다. 영어 전용 임베딩으로 바뀌면 오류 없이 v2 의 논지만
  조용히 무너지므로, 숫자로 확인하고 넘어갑니다.

> **사내망에서만 API 가 열린다면** — 사내망에서 `python -m retrieval.dense` 로
> `index\embeddings.npy` 를 굽고 그 파일을 들고 나오면, 외부망에서도 문서 쪽
> 벡터는 그대로 씁니다. 다만 **질의 임베딩은 매번 API 가 필요**하므로 외부망
> 시연은 불가합니다. 시연 장소의 망 조건을 먼저 확인하십시오.

## 4. eval/preflight.py (신규)

마감 전에 한 번 돌리십시오.

```
python -m eval.preflight
```

패키지, v1 경로, 인덱스, 임베딩 자격증명·호출·다국어성·캐시, 리랭커,
**한글 PDF 폰트**, 인터락 리스트를 점검하고 실패마다 고칠 명령을 찍습니다.
폰트가 없으면 4D 리포트 한글이 통째로 깨지는데, 지금 코드는 조용히
Helvetica 로 떨어지므로 PDF 를 열기 전까지 모릅니다.

## 5. 기본 모드 hybrid + 강등 배너

서버·UI 기본값이 `lexical` 이었습니다. 심사위원이 처음 보는 화면이 가장
약한 구성이었습니다. 둘 다 `hybrid` 로 바꾸고(`COPILOT_UI_MODE` 로 덮기
가능), `/api/health` 가 실제 구성을 반환하도록 했습니다. UI 는 강등을
감지하면 모드 선택 아래에 경고를 띄웁니다 — 무대에서 "왜 한글이 안 먹지"를
디버깅하는 상황을 막습니다.

---

## 적용 순서

```bash
# 0) 덮어쓰기 후
pip install -r requirements.txt

# 1) 환경 점검 — 여기서 실패가 없어야 의미 있는 표가 나옵니다
python -m eval.preflight

#    임베딩 자격증명 실패 시 — run_claude.bat 의 AOAI 값을 채우십시오

# 2) 임베딩 캐시 생성 (수 분). 안 하면 첫 질의가 그만큼 멈춥니다
python -m retrieval.dense

# 3) 본 평가
python -m eval.run_eval_v2 --md eval/scorecard_v2.md --dump-grades

# 4) 임계값 교정이 필요하면
#    eval/grades_dump.json 확인 → COPILOT_GRADE_THRESHOLD 조정 → 3) 재실행

# 5) 데모
uvicorn api.server:app --port 8000     # 또는 set_v1_path.bat
cd ui/react && npm install && npm run dev
```

## 남은 것 (제가 못 한 것)

- **hybrid/full 실측.** 사내 API·리랭커가 없는 환경에서 작업해서 벡터 유사도
  구간(`GRADE_DENSE_LO/HI` = 0.35~0.60)과 리랭커 구간(0~4)은 설계값입니다.
  **특히 이 구간은 bge-m3 분포를 가정한 값입니다.** text-embedding-3-large 는
  유사도 분포가 다를 수 있으니, preflight 의 '한↔영 동의 / 무관' 두 숫자를
  보고 그 사이에 경계가 오도록 조정하십시오.
- **`api/fonts/NanumGothic.ttf` 동봉.** 경로는 이미 탐색 목록에 있습니다.
  파일만 넣으면 됩니다. 데모 PC 가 바뀌어도 안전해집니다.
- **`ui/react/node_modules` 제출 zip 에서 제외.** `.gitignore` 는 넣었지만
  이미 만들어진 폴더는 직접 지우셔야 합니다 (win32 바이너리 포함, 심사자
  환경에서 깨집니다).
- **리랭커 워밍업.** `full` 모드 첫 질의가 CPU 에서 수 초 걸립니다. 시연
  시나리오 질의를 미리 한 번 돌려 두거나, 무대는 hybrid 로 돌리고 full
  점수는 표로만 보여주는 편이 안전합니다.
