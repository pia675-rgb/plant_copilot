# 매뉴얼을 채우는 법

이 폴더는 비어 있습니다. **벤더 매뉴얼은 제조사에 저작권이 있어
저장소에 포함하지 않습니다.** 아래 세 종을 직접 내려받아 이 폴더에
넣으시면 데모가 온전히 동작합니다.

| 파일명 | 문서 | 제조사 |
|---|---|---|
| `M300.pdf` | M300 Transmitter 사용설명서 | Mettler Toledo |
| `M9e.pdf` | Sievers M9e TOC Analyzer | Veolia Sievers |
| `et200sp_ha_AI_16xI_2-wire_HART_HA_en-US_en-US.pdf` | SIMATIC ET 200SP HA · AI 16xI 2-wire HART | Siemens |

각 제조사 홈페이지에서 모델명으로 검색하면 받을 수 있습니다.
파일명은 위와 같게 맞춰 주십시오 — 계기 리스트의 모델명과
대조해서 매뉴얼을 찾습니다.

넣은 뒤 색인을 만듭니다.

    python -m ingest.build_index
    python -m retrieval.dense

## 매뉴얼 없이 돌리려면

넣지 않아도 서버는 뜹니다. 태그 조회·판넬 조회·인터락 조회·도면
보기는 그대로 동작하고, **매뉴얼 근거만 비게 됩니다.** 알람 조회는
근거가 없으므로 거절(abstain)로 답합니다 — 이것도 의도된 동작입니다.
