# 패치 19-9 — 강등 사유를 화면에 드러내기

패치 19-8 위에 덮으십시오.

```
retrieval/pipeline.py   강등 사유·영향 기록 (degrade_reasons / degrade_detail)
api/server.py           /api/health 에 degrade_detail 추가
ui/react/src/App.jsx    강등 배너 (탭·모드와 무관하게 항상 표시)
ui/react/src/index.css  배너 스타일
eval/selfcheck.py       강등 가시성 [주입] (29 → 30)
```

## 진단 — 조치 순서가 아니라 검색이 죽어 있습니다

보내주신 `/api/health` 가 정확히 말해 줍니다.

```json
"default_mode": "hybrid", "effective_mode": "lexical",
"degraded": ["dense"], "label": "hybrid→lexical(강등:dense)"
```

벡터 검색이 꺼져 어휘 검색(BM25)만 돌고 있습니다. 그러면 어휘가 겹치지
않는 질의를 못 찾고, CRAG 가 근거 부족으로 **abstain 으로 끝냅니다.**
abstain 이면 조치 순서 생성 단계까지 가지 않습니다. 조치 생성이 고장난
것이 아니라 그 앞이 막힌 것입니다.

측정값이 그대로 설명합니다.

```
lexical  17/45   과잉거절 없음 11/39  ← 답이 있는 39문항 중 28건을 거절
hybrid   33/45
```

**회귀는 아닙니다.** 검색 평가를 다시 돌려 lexical 17/45 로 스코어카드
기록과 같은 값이 나오는 것을 확인했습니다. IO List 개편이 검색 경로를
건드리지 않았습니다.

## 왜 꺼졌는지는 화면에 없었습니다

강등 사유는 서버 콘솔에만 찍히고 있었습니다.

```
[강등] 임베딩(azure/text-embedding-3-large) 사용 불가
       — AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY 가 설정되지 않았습니다.
```

`config.py` 기본값이 `azure` 라서, 환경변수가 안 걸린 채 서버가 뜨면
여기로 떨어집니다. 인덱스 캐시 서명은 `ollama/bge-m3` 이므로 서명이
달라 그 캐시도 쓰지 못합니다.

이제 `/api/health` 가 사유와 **그 결과 무엇이 나빠지는지**까지 싣습니다.

```json
"degrade_detail": [{
  "component": "dense",
  "reason": "임베딩(azure/text-embedding-3-large) 사용 불가 — …",
  "impact": "어휘가 겹치지 않는 질의를 찾지 못해 대부분 거절(abstain)로
             끝납니다. 측정: lexical 17/45 vs hybrid 33/45"
}]
```

## 배너를 상단으로 올렸습니다

강등 배너가 이미 있었지만 **알람 탭의 모드 선택 옆**에 있었고, 조건도
`mode !== 'lexical'` 이었습니다. 다른 탭에 있거나 모드를 lexical 로
두면 보이지 않습니다.

탭·모드와 무관하게 본문 상단에 사유·영향·조치를 함께 띄웁니다. 기존
배너는 그대로 두었습니다.

## selfcheck 29 → 30

```
강등 가시성 [주입]   강등되었을 때 사유가 /api/health 에 실리는가
```

이 항목은 **강등 여부를 판정하지 않습니다.** 강등이 없으면 통과입니다.
보는 것은 "강등되었을 때 드러나는가" 이지 "강등되었는가" 가 아닙니다.
후자는 `검색 모드 구성` 항목이 이미 봅니다.

## 조치 — 서버 콘솔부터 보십시오

기동 시 `[강등]` 줄에 무엇이 찍히는지가 갈림길입니다.

| 콘솔 메시지 | 원인 | 조치 |
|---|---|---|
| `임베딩(azure/…) 사용 불가` | 환경변수가 안 걸림 | `run_claude.bat` 으로 실행 |
| `임베딩(ollama/bge-m3) 사용 불가` | Ollama 미기동 | `ollama serve` · `ollama list` 확인 |

수동으로 띄우실 때는 이 순서여야 합니다.

```cmd
set COPILOT_EMBED_PROVIDER=ollama
set COPILOT_EMBED_MODEL=bge-m3
set COPILOT_DIVERSIFY=off
uvicorn api.server:app --port 8000
```

`COPILOT_DIVERSIFY` 도 같이 보셔야 합니다. 기본값이 `kind` 인데 측정에서
`off`(33/45)가 `kind`(29)보다 높았습니다. selfcheck 가 `kind` 를 본
것으로 보아 지금 환경변수가 통째로 안 걸린 상태로 보입니다.

## 확인 결과

| 항목 | 결과 |
|---|---|
| 검색 평가 lexical | 17/45 — 스코어카드 기록과 동일 (회귀 없음) |
| health degrade_detail | 사유·영향 노출 |
| 판넬·카드 평가 | 204/204 |
| 인터락 평가 | 72/72 |
| JSX 번들 | 정상 |
