# 패치 5 — 조치 순서 생성 (mock 제거)

```
graph/advisor.py        (신규) LLM 조치 생성 + 근거 ID 검증
api/server.py           /api/advice 를 LLM 경로로 전환, 템플릿은 폴백
eval/preflight.py       조치 생성 LLM 점검 항목 추가
ui/react/src/App.jsx    mock 플래그 제거, 헤더 표기 변경
```

## 무엇이 문제였나

화면 제목의 `(mock)` 이 그대로였습니다. `advisor_fn` 훅은 만들어져
있었는데 **아무것도 연결되지 않아**, 검색된 근거 5건에 번호만 붙여
나열하고 있었습니다.

```
1. Acid Motor      — Low current in the acid motor is detected.
2. Acid container  — The estimated volume of acid is less than 10%.
3. Acid Valve      — Low current in the acid valve is detected.
4. Acid Detector Drive ...
5. Acid motor ...
```

정비원 입장에서 "그래서 뭘 먼저 하라는 것"이 나오지 않습니다.

## 어떻게 고쳤나

`graph/advisor.py` 를 붙였습니다. 근거를 정비원이 따라갈 수 있는
2~5단계 순서로 바꿉니다. 쉬운 것·안전한 것·확인이 빠른 것부터
배치하고, 비슷한 근거는 하나로 묶습니다.

## 환각을 막는 네 가지

안전과 직결되는 계층이므로 LLM 을 자유롭게 두지 않았습니다.

1. **근거만 프롬프트에 넣습니다.** 일반 상식·추측 금지를 명시합니다.
2. **인용 ID 를 코드로 검증합니다.** 검색 결과에 없는 ID 를 단 단계는
   버립니다. 화면까지 보내지 않습니다.
3. **남는 단계가 없으면 템플릿으로 되돌아갑니다.** 빈 화면이나 근거
   없는 조치보다 낫습니다.
4. **temperature 0.** 같은 질의에 같은 조치가 나와야 합니다.

그리고 **거절(abstain) 판정에서는 호출하지 않습니다.** 근거가
부족하다고 판정한 뒤에 조치를 만들면 판정이 의미가 없어집니다.

### 검증이 실제로 작동함을 확인했습니다

없는 ID 를 인용하는 응답을 넣어 시험했습니다.

```
입력: 3단계 (마지막이 존재하지 않는 M9E-9999 인용)
출력: 2단계만 통과, "버려진 단계: 1"
```

버린 개수는 `dropped_steps` 로 API 에 실리고 화면 요약에도 표시됩니다.
모델이 근거를 지어내면 사용자가 그 사실을 압니다.

## 실행에 필요한 것

대화 모델이 하나 필요합니다. 임베딩(bge-m3)과 별개입니다.

```cmd
ollama pull qwen2.5:7b-instruct
```

약 4.7GB 입니다. `OLLAMA_MODELS` 가 D 드라이브로 잡혀 있으면 거기
들어갑니다.

```cmd
set COPILOT_PROVIDER=ollama
set COPILOT_MODEL=qwen2.5:7b-instruct
```

`COPILOT_PROVIDER=off` 로 두면 LLM 없이 기존 나열만 나옵니다.
임베딩 제공자와 별개로 설정하므로, 나중에 임베딩은 사내 API 로
가고 조치 생성은 로컬로 두는 구성도 가능합니다.

점검:

```cmd
python -m eval.preflight
python -m graph.advisor --tag AIT-4002 --alarm "산 잔량이 부족하다고 뜹니다"
```

두 번째 명령이 조치 순서를 콘솔에 찍습니다. UI 없이 먼저 확인할 수
있습니다.

## 화면 표기

헤더가 어느 경로였는지 알려줍니다.

- `조치 순서 · 근거 인용 검증됨` — LLM 이 생성하고 ID 검증을 통과
- `조치 순서 · 근거 나열 (LLM 미사용)` — 폴백

LLM 이 없거나 실패해도 앱은 그대로 동작합니다. 시연 중 모델이
안 떠 있어도 화면이 비지 않습니다.

## 평가에는 영향이 없습니다

45문항·72문항 평가는 검색과 조회를 재는 것이므로 이 계층을 거치지
않습니다. 조치 생성 품질은 아직 측정 대상이 아니며, 측정하려면
"생성된 단계가 인용한 근거를 실제로 반영하는가"를 보는 별도 평가가
필요합니다. 본선 과제로 두는 것이 맞다고 봅니다.
