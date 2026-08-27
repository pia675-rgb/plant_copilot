# Plant Maintenance Copilot — 검색 정확도 스코어카드 v2

평가셋 10문항. 같은 문항을 v1 과 v2 각 구성에 돌린 결과입니다.

> **작성** 도남진 (검증 담당) — 영문 대조군 — 한국어 홀드아웃 10문항을 같은 내용의 영문으로 다시 물은 대조군. 한국어판에서 낮은 점수가 나온 원인이 한국어→영문 구간에 있는지 확인한다.

## 유형별

| 유형 | 문항 | hybrid |
|---|---|---|
| syn | 4 | 2/4 |
| body | 2 | 0/2 |
| typo | 1 | 0/1 |
| abstain | 3 | 0/3 |
| **전체** | **10** | **2/10** |

## 채점 항목별

| 항목 | hybrid |
|---|---|
| Top-3 | 2/5 |
| 과잉거절 없음 | 6/7 |
| 본문 적중 | 0/2 |
| 출처 정확 | 2/2 |
| 거절 | 0/3 |

## 실패 문항 (hybrid 기준, 8건)

| 문항 | 유형 | 질의 | 기대 | 실제 상위 | 실패 항목 | 판정 |
|---|---|---|---|---|---|---|
| H01 | syn | 산 시약 통이 거의 바닥나서 경고 떠 | M9E-300 | M9e#Modbus_Map#33, M9e#Modbus_Map#32,  | Top-3, 과잉거절 없음 | abstain 0.49 |
| H02 | body | 자외선 램프 어떻게 교체해? | To replace the UV Lamp, Replacin | M9e#Cleaning_the_Analyzer#0, M9e#Repla | 본문 적중 | advise 0.55 |
| H03 | typo | 산회제 시약 양이 거의 없다고 경고마 나왔어 교체해 | M9E-400 | M9e#Configuring_the_Data_I_O_Optional_ | Top-3 | advise 0.63 |
| H04 | abstain | 분석기 안에서 냉각팬이 너무 시끄럽게 돌아가는데 팬 | - | M9e#Operational_Cautions#7, M9e#Perfor | 거절 | advise 0.51 |
| H05 | abstain | 샘플 온도가 45도 넘으면 자동으로 분석 멈추는 설 | - | M9e#Offsetting_the_Acid_s_TOC_contribu | 거절 | advise 0.67 |
| H07 | syn | 레진 필터 수명이 거의 끝나가서 경고 나와 | M9E-700 | M9e#Modbus_Map#18, M9e#Modbus_Map#16,  | Top-3 | advise 0.51 |
| H09 | body | DI 물 펌프 처음 설치하고 나서 공기 빼는 작업  | Step 8: Prime the DI Pump, To pr | M9e#Maintaining_the_DI_Water_Reservoir | 본문 적중 | advise 0.70 |
| H10 | abstain | 분석기 전원 끄고 나서 배터리로 한 시간 정도 더  | - | M9e#Operational_Cautions#7, M9e#Operat | 거절 | advise 0.55 |

실험 조건: `bm25=40 dense=40 rrf_k=60 fused=30 final=5 rerank=BAAI/bge-reranker-v2-m3 embed=ollama/bge-m3 grade_thr=0.50 max_rewrites=2 diversify=off`
