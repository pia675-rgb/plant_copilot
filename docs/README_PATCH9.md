# 패치 9 — selfcheck 가 찾아낸 실제 버그 수정

패치 8 위에 덮으십시오. 패치 7·8 내용을 모두 포함합니다.

## selfcheck 가 바로 일을 했습니다

```
[실패] 규칙 엔진 명령 인식  ImportError: cannot import name 'rule_intent'
```

`rule_intent()` 가 챗봇 엔드포인트 **안에 중첩**되어 있었고, 바깥의
`req` 를 직접 참조하고 있었습니다. 그래서 밖에서 불러 시험할 수
없었습니다.

이것은 사소한 구조 문제가 아닙니다. `rule_intent` 는

- 모델이 없을 때의 **유일한** 챗봇 경로이고
- 챗봇이 지어낸 태그를 대조하는 기준입니다

즉 가장 중요한 안전망인데 **점검할 수 없는 위치**에 있었습니다.
점검할 수 없는 코드는 조용히 깨집니다.

모듈 레벨로 꺼내고 `req` 대신 인자로 받게 고쳤습니다.

```python
rule_intent("AIT-4002 산 잔량 알람 조회해줘")  -> diagnose
rule_intent("XV-4101 인터락 조회")             -> interlock
rule_intent("안녕")                            -> chat
rule_intent("사용법")                          -> help
```

## 나머지 실패는 환경 문제였습니다

그 창에 환경변수가 안 잡혀 있었습니다.

```
[강등] 임베딩(azure/text-embedding-3-large) 사용 불가 — ENDPOINT/API_KEY 없음
```

`COPILOT_EMBED_PROVIDER` 가 없어 기본값 `azure` 로 갔고, 키가 없으니
dense 가 죽고, 그 결과 한글 질의·거절 사유·캐시 서명·조치 생성이
줄줄이 실패했습니다. **연쇄 실패이지 각각의 버그가 아닙니다.**

주목할 점은 selfcheck 가 이 상황을 정확히 진단했다는 것입니다.

- `근거 없을 때 거절` → "검색이 죽어서 생긴 거절일 수 있습니다"
- `임베딩 캐시 신원` → "서명 불일치: ollama/bge-m3 ≠ azure/..."

이전 같으면 화면에 그럴듯한 결과가 나오고 아무도 몰랐을 상황입니다.

## 올바른 실행 방법

`run_claude.bat` 과 **같은 환경변수 블록**을 넣고 돌리십시오.
평가·점검용 배치를 따로 두시는 편이 확실합니다.

```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"

set COPILOT_V1_DIR=D:\00. AI TOOL\01. Hackerton\GROK\project
set COPILOT_EMBED_PROVIDER=ollama
set COPILOT_EMBED_MODEL=bge-m3
set COPILOT_EMBED_BATCH=8
set COPILOT_PROVIDER=ollama
set COPILOT_MODEL=qwen2.5:7b-instruct
set COPILOT_DIVERSIFY=off
set AZURE_OPENAI_ENDPOINT=
set AZURE_OPENAI_API_KEY=
set AZURE_OPENAI_EMBED_DEPLOYMENT=

python -m eval.preflight
python -m eval.selfcheck
pause
```

## 인터락 평가셋은 한 번 생성해야 합니다

새 노트북에는 아직 없습니다.

```cmd
python -m eval.make_eval_interlock
```
