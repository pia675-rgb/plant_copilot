# Plant Maintenance Copilot — 검색 정확도 스코어카드 v2

평가셋 45문항. 같은 문항을 v1 과 v2 각 구성에 돌린 결과입니다.

> body 유형은 v1 이 구조적으로 답할 수 없다(코드표만 색인). 이 차이는 감추지 않고 별도 열로 보고한다.

## 유형별

| 유형 | 문항 | hybrid |
|---|---|---|
| code | 4 | 4/4 |
| syn | 14 | 3/14 |
| en | 5 | 4/5 |
| body | 9 | 1/9 |
| typo | 4 | 1/4 |
| wrongdev | 3 | 2/3 |
| abstain | 6 | 6/6 |
| **전체** | **45** | **21/45** |

## 채점 항목별

| 항목 | hybrid |
|---|---|
| Top-1 | 4/4 |
| Top-3 | 15/27 |
| 출처 정확 | 12/13 |
| 과잉거절 없음 | 20/39 |
| 본문 적중 | 1/9 |
| 오귀속 방지 | 3/3 |
| 환각 방지 | 3/3 |
| 거절 | 6/6 |

## 실패 문항 (hybrid 기준, 24건)

| 문항 | 유형 | 질의 | 기대 | 실제 상위 | 실패 항목 | 판정 |
|---|---|---|---|---|---|---|
| Q05 | syn | 자외선등 교체 시기가 다 됐다고 뜨는데 | M9E-500 | M9E-502, M9e#Modbus_Map#17, M9E-10047 | Top-3, 과잉거절 없음 | abstain 0.40 |
| Q06 | syn | 옥시다이저 통 잔량이 부족하답니다 | M9E-400 | M9e#Step_1_Review_Failures_Warnings_an | Top-3 | advise 0.55 |
| Q07 | syn | 이온교환수지를 갈라고 나옵니다 | M9E-700 | M9e#Configuring_the_Data_I_O_Optional_ | Top-3, 과잉거절 없음 | abstain 0.46 |
| Q09 | syn | 주사기에 공기가 들어간 것 같습니다 | M9E-2403 | M9E-2403, M9E-5700, M9E-5702 | 과잉거절 없음 | abstain 0.42 |
| Q11 | syn | 탈이온수 흐르는 게 막힌 것 같습니다 | M9E-3101, M9E-3103 | M9e#Configuring_the_Data_I_O_Optional_ | Top-3 | advise 0.56 |
| Q12 | syn | 측정 용액이 없어서 비어 있는 상태입니다 | M300-Cond-Cell-open | M300#14_Troubleshooting#0, M300#13_Mai | Top-3, 과잉거절 없음 | abstain 0.46 |
| Q13 | syn | 케이블이 합선된 것 같습니다 | M300-Cond-Cell-shorted | M300-Watchdog-time-out, M300#8_5_1_Ala | Top-3, 과잉거절 없음 | abstain 0.50 |
| Q14 | syn | 자동 영점 조정이 실패했다고 나옵니다 | M9E-7300 | M9e#Step_1_Review_Failures_Warnings_an | Top-3, 과잉거절 없음 | abstain 0.47 |
| Q15 | syn | 산 주입 모터 전류가 낮다고 뜹니다 | M9E-5603, M9E-5606 | M9E-5603, M9E-5606, M9E-5502 | 과잉거절 없음 | abstain 0.44 |
| Q16 | syn | 선이 끊어졌다는 진단이 떴습니다 | ET200SP-6H | M9E-7201, M9E-10352, M9E-10353 | Top-3, 과잉거절 없음 | abstain 0.34 |
| Q17 | syn | 모듈이 너무 뜨겁다고 나옵니다 | ET200SP-5H | M9e#Modbus_Map#24, M9e#J5_Terminal_Wir | Top-3, 과잉거절 없음 | abstain 0.31 |
| Q23 | en | short circuit of analog inpu | ET200SP-105H | M9e#J5_Terminal_Wiring#1, M9e#J5_Termi | Top-3 | advise 0.52 |
| Q25 | body | 전도도 센서 1점 교정 절차를 알려주세요 | One-point Sensor Calibration, Co | M300#14_Troubleshooting#0, M300#13_1_F | 본문 적중, 과잉거절 없음 | abstain 0.42 |
| Q26 | body | pH 교정은 어떤 순서로 하나요 | pH Calibration, One-Point Sensor | M300-Warning-pH-Zero-7-5-pH, M300-Warn | 본문 적중 | advise 0.56 |
| Q27 | body | 보관 온도와 습도 사양이 어떻게 되나요 | Environmental specifications, Me | M300#8_5_1_Alarm#0, M300#8_5_Alarm_Cle | 본문 적중, 과잉거절 없음 | abstain 0.48 |
| Q28 | body | 전원 결선은 어떻게 하나요 | Connection of power supply | M300#8_5_1_Alarm#0, M300#8_5_Alarm_Cle | 본문 적중, 과잉거절 없음 | abstain 0.43 |
| Q29 | body | 시약 라인에 기포가 있을 때 조치 방법 | Bubbles in Reagent Lines | M9e#Overview#0, M9e#Configuring_the_Da | 본문 적중, 과잉거절 없음 | abstain 0.43 |
| Q30 | body | 유량이 부족할 때 점검 순서를 알려주세요 | Lack of Flow | M9e#Step_1_Review_Failures_Warnings_an | 본문 적중, 과잉거절 없음 | abstain 0.49 |
| Q31 | body | 시린지 리필 설정은 어떻게 하나요 | Turbo Refill Setup, Refill | M9e#Configuring_the_Data_I_O_Optional_ | 본문 적중, 과잉거절 없음 | abstain 0.44 |
| Q32 | body | 카드 채널 핀 배치가 어떻게 되나요 | Pin assignment | M9e#J5_Terminal_Wiring#0, M9e#J5_Termi | 본문 적중, 출처 정확, 과잉거절 없음 | abstain 0.48 |
| Q34 | typo | UB 램프 수명이 얼마 안 남았답니다 | M9E-500 | M9E-500, M9e#Modbus_Map#17, M9E-502 | 과잉거절 없음 | abstain 0.39 |
| Q35 | typo | 산 시린지 기표 감지 | M9E-2403 | M9e#Step_1_Review_Failures_Warnings_an | Top-3 | advise 0.50 |
| Q36 | typo | 산화제 통 잔랑이 부족합니다 | M9E-400 | M9e#Overview#0, M9e#Step_1_Review_Fail | Top-3, 과잉거절 없음 | abstain 0.47 |
| Q39 | wrongdev | pH slope 경고가 떴습니다 | - | M9e#Negative_Measurements#0, M9e#Possi | 과잉거절 없음 | abstain 0.47 |

실험 조건: `bm25=40 dense=40 rrf_k=60 fused=30 final=5 rerank=off embed=openai/text-embedding-3-large grade_thr=0.50 max_rewrites=2 diversify=off`
