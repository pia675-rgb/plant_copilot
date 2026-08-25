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
| 과잉거절 없음 | 7/7 |
| 본문 적중 | 0/2 |
| 출처 정확 | 2/2 |
| 거절 | 0/3 |

## 실패 문항 (hybrid 기준, 8건)

| 문항 | 유형 | 질의 | 기대 | 실제 상위 | 실패 항목 | 판정 |
|---|---|---|---|---|---|---|
| H01 | syn | Acid reagent bottle is almos | M9E-300 | M9e#Modbus_Map#16, M9E-5601, M9E-5600 | Top-3 | advise 0.90 |
| H02 | body | How do I replace the UV lamp | To replace the UV Lamp, Replacin | M9e#Replacing_other_Consumables#5, M9E | 본문 적중 | advise 1.00 |
| H03 | typo | Oxidzer reagent is almost go | M9E-400 | M9e#Replacing_the_Chemical_Reagents#11 | Top-3 | advise 0.79 |
| H04 | abstain | Cooling fan inside the analy | - | M9e#Cleaning_the_Analyzer#0, M9e#Overv | 거절 | advise 0.78 |
| H05 | abstain | Where is the setting that au | - | M9e#Offsetting_the_Acid_s_TOC_contribu | 거절 | advise 0.90 |
| H06 | syn | UV lamp life is done, warnin | M9E-502 | M9e#Modbus_Map#17, M9E-500, M9e#Consum | Top-3 | advise 0.89 |
| H09 | body | How do I bleed the air after | Step 8: Prime the DI Pump, To pr | M9e#Sievers_Autosampler_System#15, M9e | 본문 적중 | advise 0.86 |
| H10 | abstain | Is there a battery backup th | - | M9e#Sievers_Autosampler_System#13, M9e | 거절 | advise 0.89 |

실험 조건: `bm25=40 dense=40 rrf_k=60 fused=30 final=5 rerank=BAAI/bge-reranker-v2-m3 embed=ollama/bge-m3 grade_thr=0.50 max_rewrites=2 diversify=off`
