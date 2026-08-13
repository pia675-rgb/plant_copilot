# Plant Maintenance Copilot — 검색 정확도 스코어카드 v2

평가셋 45문항. 같은 문항을 v1 과 v2 각 구성에 돌린 결과입니다.

> body 유형은 v1 이 구조적으로 답할 수 없다(코드표만 색인). 이 차이는 감추지 않고 별도 열로 보고한다.

> **미실행 구성이 있습니다.** 아래 열은 이 표에 없습니다 — 강등된 결과를 원래 이름으로 싣지 않기 위해 비워 둡니다.

> - `v1` — FileNotFoundError: [Errno 2] No such file or directory: 'D:\\00. AI TOOL\\01. HACKERTON\\plant_copilot_merged_grok2\\plant_copilot\\data\\sources\\error_codes.json'

## 유형별

| 유형 | 문항 | lexical | hybrid | full |
|---|---|---|---|---|
| code | 4 | 4/4 | 4/4 | 4/4 |
| syn | 14 | 0/14 | 10/14 | 9/14 |
| en | 5 | 5/5 | 5/5 | 5/5 |
| body | 9 | 0/9 | 7/9 | 7/9 |
| typo | 4 | 0/4 | 1/4 | 2/4 |
| wrongdev | 3 | 2/3 | 3/3 | 3/3 |
| abstain | 6 | 6/6 | 3/6 | 3/6 |
| **전체** | **45** | **17/45** | **33/45** | **33/45** |

## 채점 항목별

| 항목 | lexical | hybrid | full |
|---|---|---|---|
| Top-1 | 4/4 | 4/4 | 4/4 |
| Top-3 | 9/27 | 20/27 | 20/27 |
| 출처 정확 | 7/7 | 13/13 | 12/13 |
| 과잉거절 없음 | 11/39 | 39/39 | 39/39 |
| 본문 적중 | 0/9 | 7/9 | 7/9 |
| 오귀속 방지 | 3/3 | 3/3 | 3/3 |
| 환각 방지 | 3/3 | 3/3 | 3/3 |
| 거절 | 6/6 | 3/6 | 3/6 |

## 실패 문항 (full 기준, 12건)

| 문항 | 유형 | 질의 | 기대 | 실제 상위 | 실패 항목 | 판정 |
|---|---|---|---|---|---|---|
| Q05 | syn | 자외선등 교체 시기가 다 됐다고 뜨는데 | M9E-500 | M9e#Using_the_Environment_Preferences_ | Top-3 | advise 0.56 |
| Q07 | syn | 이온교환수지를 갈라고 나옵니다 | M9E-700 | M9e#Modbus_Map#24, M9e#Modbus_Map#36,  | Top-3 | advise 0.66 |
| Q11 | syn | 탈이온수 흐르는 게 막힌 것 같습니다 | M9E-3101, M9E-3103 | M9e#Lack_of_Flow#4, M9e#Lack_of_Flow#2 | Top-3 | advise 0.70 |
| Q13 | syn | 케이블이 합선된 것 같습니다 | M300-Cond-Cell-shorted | M300#14_4_Cond_Error_Messages_Warning_ | Top-3 | advise 0.59 |
| Q16 | syn | 선이 끊어졌다는 진단이 떴습니다 | ET200SP-6H | M9E-10055, M9E-7300, M9E-10083 | Top-3 | advise 0.58 |
| Q28 | body | 전원 결선은 어떻게 하나요 | Connection of power supply | M300#8_5_2_Clean#0, M300#8_6_Display#0 | 본문 적중 | advise 0.61 |
| Q32 | body | 카드 채널 핀 배치가 어떻게 되나요 | Pin assignment | M9e#Wiring_4_20_mA_and_Alarm_Outputs#1 | 본문 적중, 출처 정확 | advise 0.53 |
| Q35 | typo | 산 시린지 기표 감지 | M9E-2403 | ET200SP-6H, M9e#Step_1_Review_Failures | Top-3 | advise 0.53 |
| Q36 | typo | 산화제 통 잔랑이 부족합니다 | M9E-400 | M9e#Lack_of_Flow#4, M9e#Lack_of_Flow#2 | Top-3 | advise 0.68 |
| Q43 | abstain | 장비에서 쿵쿵거리는 소리가 납니다 | - | M9E-10339, M9E-10337, M9E-10342 | 거절 | advise 0.55 |
| Q44 | abstain | 화면에 웃는 얼굴 아이콘이 떠 있습니다 | - | M9e#Using_the_Environment_Preferences_ | 거절 | advise 0.57 |
| Q45 | abstain | 장비에서 커피 냄새가 납니다 | - | M9e#Step_1_Review_Failures_Warnings_an | 거절 | advise 0.58 |

실험 조건: `bm25=40 dense=40 rrf_k=60 fused=30 final=5 rerank=BAAI/bge-reranker-v2-m3 embed=ollama/bge-m3 grade_thr=0.50 max_rewrites=2 diversify=off`
