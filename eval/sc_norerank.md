# Plant Maintenance Copilot — 검색 정확도 스코어카드 v2

평가셋 45문항. 같은 문항을 v1 과 v2 각 구성에 돌린 결과입니다.

> body 유형은 v1 이 구조적으로 답할 수 없다(코드표만 색인). 이 차이는 감추지 않고 별도 열로 보고한다.

## 유형별

| 유형 | 문항 | hybrid |
|---|---|---|
| code | 4 | 0/4 |
| syn | 14 | 1/14 |
| en | 5 | 2/5 |
| body | 9 | 0/9 |
| typo | 4 | 0/4 |
| wrongdev | 3 | 3/3 |
| abstain | 6 | 3/6 |
| **전체** | **45** | **9/45** |

## 채점 항목별

| 항목 | hybrid |
|---|---|
| Top-1 | 0/4 |
| Top-3 | 3/27 |
| 출처 정확 | 5/13 |
| 과잉거절 없음 | 37/39 |
| 본문 적중 | 0/9 |
| 오귀속 방지 | 3/3 |
| 환각 방지 | 3/3 |
| 거절 | 3/6 |

## 실패 문항 (hybrid 기준, 36건)

| 문항 | 유형 | 질의 | 기대 | 실제 상위 | 실패 항목 | 판정 |
|---|---|---|---|---|---|---|
| Q01 | code | 10084 | M9E-10084 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-1, Top-3, 출처 정확 | advise 0.67 |
| Q02 | code | 2403 | M9E-2403 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-1, Top-3, 출처 정확 | advise 0.64 |
| Q03 | code | 3101 | M9E-3101 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-1, Top-3, 출처 정확 | advise 0.65 |
| Q04 | code | 7200 | M9E-7200 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-1, Top-3, 출처 정확 | advise 0.72 |
| Q05 | syn | 자외선등 교체 시기가 다 됐다고 뜨는데 | M9E-500 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.67 |
| Q06 | syn | 옥시다이저 통 잔량이 부족하답니다 | M9E-400 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.62 |
| Q07 | syn | 이온교환수지를 갈라고 나옵니다 | M9E-700 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.72 |
| Q08 | syn | 샘플수가 안 흐른다고 합니다 | M9E-10084, M9E-10122, M9E-10125 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.61 |
| Q09 | syn | 주사기에 공기가 들어간 것 같습니다 | M9E-2403 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.60 |
| Q10 | syn | 초순수 저장조 수위가 낮다고 뜹니다 | M9E-3100 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.60 |
| Q11 | syn | 탈이온수 흐르는 게 막힌 것 같습니다 | M9E-3101, M9E-3103 | M9e#_전체_#1, M9e#_전체_#9, M9e#_전체_#2 | Top-3 | advise 0.51 |
| Q12 | syn | 측정 용액이 없어서 비어 있는 상태입니다 | M300-Cond-Cell-open | M300-Warning-DO-ZeroPt-15-V, M300-Erro | Top-3, 과잉거절 없음 | abstain 0.47 |
| Q13 | syn | 케이블이 합선된 것 같습니다 | M300-Cond-Cell-shorted | M300-Watchdog-time-out, M300#_전체_#2, A | Top-3 | advise 0.68 |
| Q14 | syn | 자동 영점 조정이 실패했다고 나옵니다 | M9E-7300 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.61 |
| Q15 | syn | 산 주입 모터 전류가 낮다고 뜹니다 | M9E-5603, M9E-5606 | ET200SP-8H, ET200SP-10EH, ET200SP-11H | Top-3 | advise 0.51 |
| Q17 | syn | 모듈이 너무 뜨겁다고 나옵니다 | ET200SP-5H | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.69 |
| Q18 | syn | TC 유로에 공기가 있다고 합니다 | M9E-7200 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.60 |
| Q19 | en | no sample flow detected | M9E-10084, M9E-10122, M9E-10125 | M9e#_전체_#8, M9e#_전체_#9, M9e#_전체_#2 | Top-3 | advise 0.76 |
| Q21 | en | bubble detected in acid syri | M9E-2403 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.70 |
| Q22 | en | resin bed remaining life | M9E-700 | M9e#_전체_#7, M9e#_전체_#2, M9e#_전체_#8 | Top-3, 과잉거절 없음 | abstain 0.40 |
| Q24 | body | UV 램프는 얼마나 자주 교체해야 하나요 | Consumables Replacement Schedule | M9e#_전체_#9, M9e#_전체_#8, M9e#_전체_#3 | 본문 적중, 출처 정확 | advise 0.63 |
| Q25 | body | 전도도 센서 1점 교정 절차를 알려주세요 | One-point Sensor Calibration, Co | M300-Watchdog-time-out, M300#_전체_#2, A | 본문 적중 | advise 0.69 |
| Q26 | body | pH 교정은 어떤 순서로 하나요 | pH Calibration, One-Point Sensor | M300-Warning-pH-Zero-7-5-pH, M300-Erro | 본문 적중 | advise 0.62 |
| Q27 | body | 보관 온도와 습도 사양이 어떻게 되나요 | Environmental specifications, Me | M300-Watchdog-time-out, M300#_전체_#2, A | 본문 적중 | advise 0.65 |
| Q28 | body | 전원 결선은 어떻게 하나요 | Connection of power supply | M300-Watchdog-time-out, M300#_전체_#2, A | 본문 적중 | advise 0.64 |
| Q29 | body | 시약 라인에 기포가 있을 때 조치 방법 | Bubbles in Reagent Lines | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | 본문 적중, 출처 정확 | advise 0.58 |
| Q30 | body | 유량이 부족할 때 점검 순서를 알려주세요 | Lack of Flow | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | 본문 적중, 출처 정확 | advise 0.64 |
| Q31 | body | 시린지 리필 설정은 어떻게 하나요 | Turbo Refill Setup, Refill | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | 본문 적중, 출처 정확 | advise 0.61 |
| Q32 | body | 카드 채널 핀 배치가 어떻게 되나요 | Pin assignment | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | 본문 적중 | advise 0.71 |
| Q33 | typo | 샘프 유량이 없다고 나옵니다 | M9E-10084, M9E-10122, M9E-10125 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.65 |
| Q34 | typo | UB 램프 수명이 얼마 안 남았답니다 | M9E-500 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.66 |
| Q35 | typo | 산 시린지 기표 감지 | M9E-2403 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.60 |
| Q36 | typo | 산화제 통 잔랑이 부족합니다 | M9E-400 | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | Top-3 | advise 0.62 |
| Q43 | abstain | 장비에서 쿵쿵거리는 소리가 납니다 | - | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | 거절 | advise 0.61 |
| Q44 | abstain | 화면에 웃는 얼굴 아이콘이 떠 있습니다 | - | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | 거절 | advise 0.63 |
| Q45 | abstain | 장비에서 커피 냄새가 납니다 | - | M9e#_전체_#2, M9e#_전체_#8, AI 16xI 2-wire | 거절 | advise 0.67 |

실험 조건: `bm25=40 dense=40 rrf_k=60 fused=30 final=5 rerank=off embed=ollama/bge-m3 grade_thr=0.50 max_rewrites=2 diversify=off`
