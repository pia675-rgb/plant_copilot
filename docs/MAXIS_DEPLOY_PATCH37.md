# 패치 37 — MAXIS AGENT 노드 반영 절차

대상: Plant Copilot AGENT 노드 (Gitea 리포 `ce6d92ed-…`)

## 먼저 알아둘 것 — 노드 리포는 로컬 plant_copilot 과 다릅니다

노드 이식 때 노드 전용으로 바꾼 곳이 있습니다.

- `api/server.py` · `App.jsx` — 15초 게이트웨이 우회용 비동기 start/result
- `Dockerfile` — 베이스 이미지 `maxis.azurecr.io/...`
- `k8s/deployment.yaml` · `Jenkinsfile`

그래서 **패치 zip 을 노드 리포에 통째로 덮으면 안 됩니다.** 비동기 우회가 사라져
챗봇·진단이 15초에 끊깁니다. 아래처럼 「그대로 복사」 와 「손으로 합치기」 를 나눕니다.

---

## 0. 준비

```cmd
cd /d "<노드 리포 폴더>\ce6d92ed-734c-4860-ade2-86fac918a9cd"
git pull
git status                      :: 깨끗해야 합니다
git tag before-patch37          :: 되돌릴 지점
```

## 1. 그대로 복사 (새 파일)

패치 zip 의 `plant_copilot\` 아래에서 노드 리포 같은 경로로 복사합니다.

```
sim\                                (폴더 전체)
api\sim_routes.py
ingest\io_standard.py
tools\convert_io_to_l1.py
demo\sim\                           (폴더 전체)
demo\IO_LIST_L1.xlsx
demo\L1_IO_LIST_표준양식_Rev0_1.xlsx
ui\react\public\sim_studio.html
docs\README_PATCH37.md
docs\MAXIS_DEPLOY_PATCH37.md
```

## 2. 덮어쓰고 확인 (노드에서 안 건드렸을 파일)

```
ingest\lists.py
ingest\repair.py
ingest\inspect.py
eval\selfcheck.py
CLAUDE.md
```

덮은 뒤 **반드시** 확인합니다.

```cmd
git diff --stat
git diff ingest\lists.py
```

**더해진 줄만 있어야 정상입니다.** 패치가 이 파일들에서 지운 줄은 거의 없습니다.
노드 전용 코드가 빨간 줄(삭제)로 보이면 그 파일은 되돌립니다.

```cmd
git checkout -- ingest\lists.py
```

되돌린 파일은 알려주시면 합칠 부분만 뽑아 드리겠습니다.

## 3. 손으로 합치기 — `api/server.py` (한 곳)

`# ── 정적 파일 (빌드된 React UI)` 줄을 찾아 **그 바로 위에** 넣습니다.
정적 마운트보다 뒤에 두면 `/` 마운트가 요청을 가로챕니다.

```python
# ── 공정 모의 화면 (패치 37) ─────────────────────────────────
from api.sim_routes import build_router as _build_sim_router  # noqa: E402
app.include_router(_build_sim_router(_require_edit))
```

`_require_edit` 이 그 위에 정의돼 있어야 합니다. 노드 리포에 이 함수가 없으면
`lambda request: None` 으로 대신하십시오. 다만 그러면 열쇠 없이 누구나 화면을 만들 수 있습니다.

## 4. 손으로 합치기 — `ui/react/src/App.jsx` (세 곳)

**① 탭 버튼** — `자료 반입` 버튼 뒤에 추가합니다.

```jsx
          <button className={`nav-tab ${tab === 'sim' ? 'active' : ''}`} onClick={() => setTab('sim')}>
            공정 화면
          </button>
```

**② 탭 내용** — `{tab === 'ingest' && <IngestView ... />}` 줄 뒤에 추가합니다.

```jsx
        {tab === 'sim' && (
          <iframe src="sim_studio.html" title="공정 모의 화면 관리"
            style={{ width: '100%', height: 'calc(100vh - 40px)', border: 0, display: 'block' }} />
        )}
```

**③ 인터락 조회 연결** — `InterlockView` 안의 다음 한 줄을 찾습니다.

```jsx
  const GRAPHIC_PAGES = { 'P-5101A': 'interlock_P-5101A.html?embed=1' }
```

찾은 줄을 아래로 바꿉니다. **`const [data, setData]` 선언보다 아래**에 있어야 합니다.
위에 있으면 선언 전 참조로 화면이 흰색이 됩니다.

```jsx
  const GRAPHIC_STATIC = { 'P-5101A': 'interlock_P-5101A.html?embed=1' }
  const [simPage, setSimPage] = useState(null)
  const outTag = data?.output?.tag
  useEffect(() => {
    setSimPage(null)
    if (!outTag || GRAPHIC_STATIC[outTag]) return
    let alive = true
    fetch(`${API}/sim/tag/${encodeURIComponent(outTag)}`)
      .then(r => r.ok ? r.json() : null)
      .then(j => { if (alive && j?.screens?.length)
        setSimPage(`${API}/sim/screens/${encodeURIComponent(j.screens[0])}/view?embed=1&sel=${encodeURIComponent(outTag)}`) })
      .catch(() => {})
    return () => { alive = false }
  }, [outTag])
  const GRAPHIC_PAGES = outTag && simPage ? { ...GRAPHIC_STATIC, [outTag]: simPage } : GRAPHIC_STATIC
```

노드 App.jsx 가 `API` 대신 `url()` 같은 도우미로 주소를 만든다면 그 방식에 맞춥니다.
기준은 **앞 슬래시 없는 상대 경로**입니다. 게이트웨이가 `/agent/<id>` 를 떼고 넘기기 때문입니다.

## 5. Dockerfile

노드 Dockerfile 이 폴더별로 복사한다면(`COPY api/ ./api/` 식) 한 줄을 더합니다.

```dockerfile
COPY sim/ ./sim/
```

`COPY . .` 로 통째로 복사한다면 손댈 것이 없습니다.
**`sim/` 이 이미지에 빠지면 서버가 기동하다 죽습니다.** `server.py` 가 시작할 때 가져오기 때문입니다.

## 6. k8s/deployment.yaml — 화면 추출 키

`env:` 에 추가합니다.

```yaml
- name: COPILOT_SIM_MODEL
  value: "gpt-5.5"
- name: COPILOT_SIM_BASE_URL
  value: "https://api.openai.com/v1"     # 사내 엔드포인트면 그 주소
- name: COPILOT_SIM_API_KEY
  valueFrom:
    secretKeyRef: { name: copilot-sim, key: api-key }
```

- **따로 줘야 하는 이유:** 노드의 `OPENAI_API_KEY` · `OPENAI_BASE_URL` 은 DeepInfra(임베딩·챗)를
  가리킵니다. 전용 값을 주지 않으면 DeepInfra 에 `gpt-5.5` 를 요청하고 실패합니다.
- **키를 yaml 에 평문으로 넣지 마십시오.** 리포를 읽을 수 있는 사람은 모두 보게 됩니다.
  Secret 을 만들 권한이 없으면 우선 `value: "..."` 로 넣되, 커밋 전에 한 번 더 생각하십시오.
  기존 DeepInfra 키가 이미 평문으로 들어가 있어 회전이 필요한 상태입니다.
- 키가 없어도 앱은 뜹니다. 「배치 JSON 으로 생성」 은 모델 없이 동작합니다.

Azure 배포를 쓰는 경우에는 다음 세 값을 넣습니다.

```
COPILOT_SIM_PROVIDER=azure
COPILOT_SIM_MODEL=<배포 이름>
AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY
```

## 7. UI 빌드 (노드 리포에서)

노드의 App.jsx 로 빌드해야 합니다. 패치 zip 안의 `dist` 는 로컬 App.jsx 로 만든 것이라
**노드에는 쓰면 안 됩니다.** 그대로 올리면 비동기 우회가 빠진 화면이 올라갑니다.

```cmd
cd ui\react
npm ci
npm run build
cd ..\..
```

`dist\sim_studio.html` 이 생겼는지 확인합니다. `public\` 에 있으면 빌드가 복사합니다.
이전 `dist\assets\index-*.js` 는 빌드가 지웁니다.

## 8. push 전 로컬 확인

노드 리포 폴더에서 평소 로컬 실행 방법대로 띄우고 다음을 확인합니다.

- 「공정 화면」 탭 → 「배치 JSON 으로 생성」 → `demo\sim\layout_P5101_demo.json`
  → 화면이 뜨고 「▶ 전체 점검」 이 **FAIL 0** 인지
- 인터락 조회 → XV-5103 → 공정 화면 패널이 뜨는지
- 기존 기능: 알람 조회 한 건, 챗봇 한 번 — 비동기 우회가 살아 있는지

자기 점검은 다음으로 돌립니다.

```cmd
set COPILOT_DATA_DIR=demo_data
python eval\selfcheck.py --skip-llm
```

신규 5항목이 OK 인지 봅니다. 「공정 모의 엔진」 은 playwright 가 없으면 「주의」 로 나오며, 정상입니다.

## 9. 커밋 · push · 배포

```cmd
git add -A
git status                      :: .env 나 키가 섞이지 않았는지
git commit -m "패치 37: L1 IO LIST 표준양식 · 공정 모의 화면"
git push origin main
```

그다음 MAXIS 노드 화면에서 **배포하기**를 누릅니다. push 만으로 Jenkins 가 도는 설정이면 기다리기만 하면 됩니다.
빌드 로그에서 `COPY sim/` 단계와 `Application startup complete` 를 확인합니다.

## 10. 배포 후 확인

주소는 **끝 슬래시까지** 입력합니다: `https://node.maxis.skax.co.kr/agent/<노드ID>/`

1. 「공정 화면」 탭이 보이는지
2. 「배치 JSON 으로 생성」 → P-5101A 대조 화면 (키 불필요)
3. 「이미지로 생성」 → 진행 문구가 2초마다 바뀌다가 화면이 뜨는지

3번이 실패하면 오류 문구로 원인을 가릅니다.

| 문구 | 원인 | 조치 |
| --- | --- | --- |
| `모델 서버에 연결하지 못했습니다` | 클러스터에서 외부 API 로 나가지 못함 | 운영진에 외부 통신 허용 문의, 또는 사내 엔드포인트 사용 |
| `모델 호출 실패 401` | 키가 틀림 | Secret 값 확인 |
| `모델 호출 실패 404` / `model` | 주소·모델명이 틀림 | `COPILOT_SIM_BASE_URL` · `COPILOT_SIM_MODEL` 확인 |
| `401` (앱 자체) | 수정 열쇠가 설정됨 | 화면의 「수정 열쇠」 칸에 입력 |
| `413` | 게이트웨이 본문 크기 제한 | 화면이 1.5MB 로 줄여 올리는데도 나면 운영진 문의 |

## 노드에서의 한계 — 알고 쓰십시오

- **15초 벽:** 이미지 추출은 비동기(`/api/sim/jobs`)로 돌아 걸리지 않습니다.
  동기판 `POST /api/sim/screens` 는 노드에서 끊기므로 쓰지 마십시오. 화면은 비동기판만 씁니다.
- **재배포하면 만든 화면이 사라집니다.** PVC 가 막혀 있어 파드 디스크가 휘발됩니다.
  시연할 화면은 로컬에서 만든 뒤 `demo_derived\sim\<id>\` 폴더째 리포에 커밋하면 이미지에 실려 남습니다.
  노드의 `COPILOT_DERIVED_DIR` 가 가리키는 폴더 아래 `sim\` 이어야 합니다.
- **진행 중 작업:** 파드가 재기동되면 사라집니다. 이미 만들어진 화면은 남습니다.
- **파드가 여러 개(replica>1)라면** 작업 조회가 다른 파드로 가서 「작업이 없습니다」 가 날 수 있습니다.
  현재는 1개로 알고 있습니다.

## 되돌리기

```cmd
git reset --hard before-patch37
git push -f origin main
```

`push -f` 는 main 을 덮어씁니다. 그 사이 다른 커밋이 없을 때만 쓰십시오.
다른 커밋이 있다면 `git revert <패치 커밋>` 을 씁니다. 되돌린 뒤 배포하기를 누릅니다.
