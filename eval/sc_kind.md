# Plant Maintenance Copilot — 검색 정확도 스코어카드 v2

평가셋 45문항. 같은 문항을 v1 과 v2 각 구성에 돌린 결과입니다.

> body 유형은 v1 이 구조적으로 답할 수 없다(코드표만 색인). 이 차이는 감추지 않고 별도 열로 보고한다.

## 유형별

| 유형 | 문항 | hybrid |
|---|---|---|
| code | 4 | 4/4 |
| syn | 14 | 7/14 |
| en | 5 | 5/5 |
| body | 9 | 6/9 |
| typo | 4 | 1/4 |
| wrongdev | 3 | 3/3 |
| abstain | 6 | 3/6 |
| **전체** | **45** | **29/45** |

## 채점 항목별

| 항목 | hybrid |
|---|---|
| Top-1 | 4/4 |
| Top-3 | 17/27 |
| 출처 정확 | 13/13 |
| 과잉거절 없음 | 39/39 |
| 본문 적중 | 6/9 |
| 오귀속 방지 | 3/3 |
| 환각 방지 | 3/3 |
| 거절 | 3/6 |

## 실패 문항 (hybrid 기준, 16건)

| 문항 | 유형 | 질의 | 기대 | 실제 상위 | 실패 항목 | 판정 |
|---|---|---|---|---|---|---|
| Q05 | syn | 자외선등 교체 시기가 다 됐다고 뜨는데 | M9E-500 | M9e#Cleaning_the_Analyzer#0, M9E-502,  | Top-3 | advise 0.55 |
| Q07 | syn | 이온교환수지를 갈라고 나옵니다 | M9E-700 | M9E-1204, M9E-1203, M9e#Modbus_Map#25 | Top-3 | advise 0.57 |
| Q08 | syn | 샘플수가 안 흐른다고 합니다 | M9E-10084, M9E-10122, M9E-10125 | M9E-800, M9E-801, M9e#Lack_of_Flow#0 | Top-3 | advise 0.60 |
| Q09 | syn | 주사기에 공기가 들어간 것 같습니다 | M9E-2403 | M9E-5506, M9E-5602, M9e#Operational_Ca | Top-3 | advise 0.55 |
| Q13 | syn | 케이블이 합선된 것 같습니다 | M300-Cond-Cell-shorted | M300#14_Troubleshooting#0, M300#14_1_C | Top-3 | advise 0.66 |
| Q14 | syn | 자동 영점 조정이 실패했다고 나옵니다 | M9E-7300 | M9E-10010, M9E-10307, M9e#Negative_Mea | Top-3 | advise 0.59 |
| Q16 | syn | 선이 끊어졌다는 진단이 떴습니다 | ET200SP-6H | M9E-7300, M9E-800, M9E-1204 | Top-3 | advise 0.58 |
| Q28 | body | 전원 결선은 어떻게 하나요 | Connection of power supply | M300#14_Troubleshooting#0, M300#8_5_1_ | 본문 적중 | advise 0.63 |
| Q30 | body | 유량이 부족할 때 점검 순서를 알려주세요 | Lack of Flow | M9e#Step_1_Review_Failures_Warnings_an | 본문 적중 | advise 0.60 |
| Q32 | body | 카드 채널 핀 배치가 어떻게 되나요 | Pin assignment | AI 16xI 2-wire HART HA#6_1_Status_and_ | 본문 적중 | advise 0.68 |
| Q33 | typo | 샘프 유량이 없다고 나옵니다 | M9E-10084, M9E-10122, M9E-10125 | M9e#Lack_of_Flow#0, M9e#Lack_of_Flow#2 | Top-3 | advise 0.55 |
| Q35 | typo | 산 시린지 기표 감지 | M9E-2403 | M9e#Step_1_Review_Failures_Warnings_an | Top-3 | advise 0.60 |
| Q36 | typo | 산화제 통 잔랑이 부족합니다 | M9E-400 | AI 16xI 2-wire HART HA#6_1_Status_and_ | Top-3 | advise 0.55 |
| Q43 | abstain | 장비에서 쿵쿵거리는 소리가 납니다 | - | M9E-10077, M9E-10057, M9E-10081 | 거절 | advise 0.56 |
| Q44 | abstain | 화면에 웃는 얼굴 아이콘이 떠 있습니다 | - | AI 16xI 2-wire HART HA#6_1_Status_and_ | 거절 | advise 0.50 |
| Q45 | abstain | 장비에서 커피 냄새가 납니다 | - | M9e#Configuring_the_Data_I_O_Optional_ | 거절 | advise 0.53 |

실험 조건: `bm25=40 dense=40 rrf_k=60 fused=30 final=5 rerank=BAAI/bge-reranker-v2-m3 embed=ollama/bge-m3 grade_thr=0.50 max_rewrites=2 diversify=kind`
