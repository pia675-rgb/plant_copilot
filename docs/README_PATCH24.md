# 패치 24 — DRIVE 제거, 사양 출처를 실물 문서로

## DRIVE 는 제가 만든 열이었습니다

어느 실물 문서에도 없습니다. 데모 출력 리스트를 만들면서 제가 넣은
값(`SOLENOID` / `MCC` / `AO/POSITIONER`)이고, 실물 전환 시 채울 곳이
없습니다. **실물에 없는 것을 만들어 놓고 출처를 여쭤본 셈**이라
지웠습니다.

쓰이던 곳은 출력의 IO 종류 판정 한 곳뿐이었습니다. 조절 신호(4-20mA)면
AO, 아니면 DO 로 보게 바꿨습니다.

## TYPE · FAIL POSITION 을 실물 문서에서 읽습니다

말씀하신 대로 두 항목은 이미 넣으시는 자료 안에 있습니다.

```
TYPE           계기 리스트  SENSOR TYPE
FAIL POSITION  인터락 리스트 "* Valve Action : Fail Open"
```

인터락 파서는 `Valve Action` 을 이미 읽고 있었는데, 출력 사양을 만들 때
그 값을 쓰지 않고 부속 데이터의 값을 쓰고 있었습니다. 순서를 뒤집었습니다.

```
LCV-01   FAIL OPEN     ← 인터락 리스트
XV-4101  FAIL CLOSE
AIT-1001 CONDUCTIVITY  ← 계기 리스트 SENSOR TYPE
```

부속 데이터의 값은 이제 **그 문서에서 못 읽었을 때만 쓰는 대체값**입니다.

## selfcheck 34 → 35

```
사양 출처 실물 문서 [주입]   TYPE 이 계기 리스트 값과 같은가
                            FAIL POSITION 이 인터락 리스트 값과 같은가
```

부속 데이터가 실물 값을 덮으면 실패합니다. 검출 확인했습니다.

```
LCV-01 FAIL POSITION 이 인터락 리스트와 다릅니다: 'FAIL CLOSE' ≠ 'FAIL OPEN'
```

## 부속 데이터에 남은 것

```
TERMINAL      TB List 가 원본 (없으면 대체값)
TYPE          계기 리스트가 원본 (없으면 대체값)
FAIL POSITION 인터락 리스트가 원본 (없으면 대체값)
MANUAL FILE   자동 대조 미구현
SYSTEM        확인 필요
LOOP GROUP    확인 필요
```

`MANUAL FILE` 은 계기 리스트의 MAKER·MODEL 과 매뉴얼 파일명을 대조해
도구가 잇게 할 수 있습니다. 지금 매뉴얼 파일명이 모델명을 담고 있어
가능합니다. 붙일지 알려주십시오.

`SYSTEM` 과 `LOOP GROUP` 은 실물에서 어디에 있는지 아직 모릅니다. 계기
리스트 DESCRIPTION 에서 유도할 수는 있지만 그건 추정이라, 있는 곳을
알려주시는 편이 확실합니다.

## 확인 결과

| 항목 | 결과 |
|---|---|
| 판넬·카드 평가 | 213/213 |
| 인터락 평가 | 전건 통과 |
| 사양 출처 [주입] | TYPE 76건 · FAIL POSITION 1건 실물 문서에서 |
| 전 모듈 임포트 31개 | 실패 없음 |
| JSX 번들 | 정상 |
