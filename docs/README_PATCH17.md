# 패치 17 — 태그 목록이 안 보이던 문제

패치 16 위에 덮으십시오. 패치 7~16 내용을 모두 포함합니다.

## 확인된 버그

패치 8에서 예외 은폐를 없앨 때 제가 함수 이름을 잘못 짚어
`_interlock_tag_error` 전역 선언이 들어가지 않았습니다. 그런데
`/api/health` 는 그 변수를 참조합니다.

```python
if _interlock_tag_error:        # NameError
```

즉 **`/api/health` 가 500 을 냅니다.** 화면은 마운트 직후 health 를
부르므로 여기서부터 어긋납니다. 전역 선언을 추가했습니다.

백엔드 자체는 정상입니다 — 태그 96건(계기 72 + 출력 24)을 반환하는 것을
확인했습니다.

## 실패를 삼키지 않게

```jsx
get('/tags?kind=all').then(...).catch(() => {})     // ← 이전
```

백엔드가 죽어 있거나 경로가 틀려도 화면에는 그냥 "태그가 안 보이는"
상태로만 나타났습니다. 원인을 알 방법이 없었습니다. 오늘 잡은 것들과
같은 유형입니다.

이제 실패하거나 목록이 비면 태그 선택 아래에 사유가 표시됩니다.

## 그래도 안 보이면

원인을 순서대로 좁히십시오.

**1. 백엔드가 떠 있는가**

브라우저에서 직접 열어 보십시오.

```
http://localhost:8000/api/tags?kind=all
```

JSON 이 나오면 백엔드는 정상입니다. 안 나오면 `run_claude.bat` 창을
확인하십시오.

**2. 프록시 포트가 맞는가**

`ui/react/vite.config.js` 의 `target` 이 백엔드 포트와 같아야 합니다.
`run_claude.bat` 은 8000 을 씁니다.

**3. 브라우저 콘솔**

`F12` → Console / Network 탭에서 `/api/tags` 요청이 빨간색이면 그
상태 코드를 알려주십시오.

## 적용

```cmd
copy /Y "patch17\api\server.py"        "...\copilot_v2_claude\api\"
copy /Y "patch17\ui\react\src\App.jsx" "...\copilot_v2_claude\ui\react\src\"
```

**백엔드 재시작이 필요합니다** (Python 파일이 바뀌었습니다).
