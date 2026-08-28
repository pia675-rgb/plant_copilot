import React, { useEffect, useState } from 'react'

const API = '/api'

async function get(path) {
  const res = await fetch(`${API}${path}`)
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  return res.json()
}

async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  return res.json()
}

async function del(path) {
  const res = await fetch(`${API}${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  return res.json()
}

const MATCH_COLOR = {
  '일치': { bg: 'var(--match-bg)', color: 'var(--match)', border: 'transparent' },
  '부분일치': { bg: 'var(--partial-bg)', color: 'var(--partial)', border: 'transparent' },
  '불일치': { bg: 'var(--nomatch-bg)', color: 'var(--nomatch)', border: 'var(--line-strong)' },
  '판정하지 않음': { bg: 'transparent', color: 'var(--fg-4)', border: 'var(--line-strong)' },
}

export default function App() {
  const [tab, setTab] = useState('alarm') // alarm | interlock
  const [tags, setTags] = useState([])
  const [tagQ, setTagQ] = useState('')
  const [tag, setTag] = useState('AIT-4002')
  const [alarm, setAlarm] = useState('')
  const [code, setCode] = useState('')
  // lexical 은 한글 질의를 구조적으로 못 푼다. 시연 기본값으로 두면
  // 가장 약한 구성이 첫 화면이 된다. 서버 기본값과 맞춘다.
  const [mode, setMode] = useState('hybrid')
  const [health, setHealth] = useState(null)
  const [ilAction, setIlAction] = useState('OPEN')
  const [panelSel, setPanelSel] = useState(null)
  const [cardSel, setCardSel] = useState(null)
  const [asInput, setAsInput] = useState(false)
  // 자유 모드. 새로고침하면 근거 모드로 돌아간다 — 일부러 저장하지
  // 않는다. 모르는 채 자유 모드 화면을 보는 것이 가장 위험하다.
  const [freeMode, setFreeMode] = useState(false)
  // 챗봇 → 화면 제어
  const [botPending, setBotPending] = useState(null) // { type, ... }
  // 사이드바 접기 — 도면·인터락 표를 넓게 보여줘야 할 때가 있다
  const [navOpen, setNavOpen] = useState(true)
  // 화면에 떠 있는 조회 결과. 챗봇 후속 질문("조회된 내용을 보고 …")에
  // 답하려면 챗봇이 이것을 알아야 한다.
  const [screen, setScreen] = useState(null)


  // Ctrl+B 로 토글. 시연 중 마우스로 작은 버튼을 찾지 않아도 되게 둔다.
  useEffect(() => {
    const onKey = e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault()
        setNavOpen(v => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // 백엔드 구성 확인 — hybrid 를 골랐는데 실제로 렉시컬로 돌고 있으면
  // 무대에서 알아채기 전에 화면에 띄운다.
  useEffect(() => {
    // health 가 실패하면 강등 배너가 영원히 안 뜬다. 그것도 표시한다.
    get('/health')
      .then(setHealth)
      .catch(e => setHealth({ error: e.message || '상태 확인 실패' }))
  }, [])

  // load tag list (계기 + 인터락 출력 태그)
  //
  // 실패를 삼키지 않는다. 이전에는 catch 에서 아무것도 하지 않아,
  // 백엔드가 죽어 있거나 경로가 틀려도 화면에는 그냥 "태그가 안 보이는"
  // 상태로만 나타났다. 원인을 알 방법이 없었다.
  const [tagsError, setTagsError] = useState(null)
  useEffect(() => {
    get('/tags?kind=all').then(d => {
      setTags(d.tags || [])
      setTagsError((d.tags || []).length ? null : '태그 목록이 비어 있습니다.')
    }).catch(e => setTagsError(e.message || '태그 목록을 불러오지 못했습니다.'))
  }, [])

  const filteredTags = tags.filter(t => {
    if (tab === 'interlock') {
      // 조회 방향에 따라 고를 수 있는 태그가 다르다.
      //
      // 출력 기준은 "이 기기가 왜 안 도나" 이므로 출력 장비를 고르고,
      // 입력 기준은 "이 계기를 빼면 뭐가 서나" 이므로 인터락 조건에
      // 등장하는 태그를 고른다. 종류(계기/출력)로 거르면 안 된다 —
      // 조건에는 다른 출력 기기의 상태도 들어오고, 계기 리스트에 있는
      // 태그가 전부 인터락에 걸려 있는 것도 아니다. 서버가 실제 조건을
      // 훑어 표시해 준 in_interlock 을 쓴다.
      if (asInput) return !!t.in_interlock
      return t.kind === 'output'
    }
    // 알람 탭은 계기 태그만. 인터락에만 등장하는 태그는 벤더 매뉴얼을
    // 붙일 수 없으므로 여기서 고르게 하면 안 된다.
    if (tab === 'alarm') return t.kind === 'instrument'
    return true
  }).filter(t => {
    if (!tagQ) return true
    const hay = `${t.tag} ${t.service} ${t.model} ${t.maker}`.toLowerCase()
    return hay.includes(tagQ.toLowerCase())
  })

  // 탭 전환이나 조회 방향 전환 시 해당 목록의 첫 태그로 맞춤.
  // asInput 을 넣지 않으면 체크박스를 켜도 출력 태그가 그대로 남는다.
  useEffect(() => {
    if (!filteredTags.length) return
    if (!filteredTags.some(t => t.tag === tag)) {
      setTag(filteredTags[0].tag)
    }
  }, [tab, tagQ, tags, asInput])

  return (
    <div className={`app-shell ${navOpen ? '' : 'nav-collapsed'}`}>
      <aside className="sidebar">
        <div className="sidebar-title">
          Plant Maintenance Copilot
          <button className="nav-toggle" onClick={() => setNavOpen(false)}
            title="사이드바 숨기기 (Ctrl+B)" aria-label="사이드바 숨기기">‹</button>
        </div>

        <button
          onClick={() => setFreeMode(f => !f)}
          title="자유 모드: 근거를 찾은 조회에도 모델 추측을 함께 표시하고, 도우미가 자유 대화에 답합니다. 추측은 조치 순서와 4D 리포트에는 어느 모드에서도 들어가지 않습니다."
          style={{
            margin: '4px 12px 10px', padding: '0 10px', width: 'calc(100% - 24px)',
            height: 34, lineHeight: '34px', whiteSpace: 'nowrap',
            borderRadius: 6, cursor: 'pointer', fontSize: '0.82rem',
            border: freeMode ? '1px solid #d9a441' : '1px solid var(--line-strong)',
            background: freeMode ? 'rgba(217,164,65,0.12)' : 'transparent',
            color: freeMode ? '#d9a441' : 'var(--faint)',
          }}
        >
          {freeMode ? '자유 모드' : '근거 모드'}
        </button>

        <nav className="nav-tabs">
          <button className={`nav-tab ${tab === 'alarm' ? 'active' : ''}`} onClick={() => setTab('alarm')}>
            알람 조회
          </button>
          <button className={`nav-tab ${tab === 'interlock' ? 'active' : ''}`} onClick={() => setTab('interlock')}>
            인터락 조회
          </button>
          <button className={`nav-tab ${tab === 'panel' ? 'active' : ''}`} onClick={() => setTab('panel')}>
            판넬 조회
          </button>
          <button className={`nav-tab ${tab === 'ingest' ? 'active' : ''}`} onClick={() => setTab('ingest')}>
            자료 반입
          </button>
        </nav>

        <div className="sidebar-section">
          <h3>설비 태그</h3>
          <div className="field">
            <label>검색 (선택)</label>
            <input value={tagQ} onChange={e => setTagQ(e.target.value)} placeholder="태그 / 서비스 / 모델" />
          </div>
          <div className="field">
            <label>태그 선택</label>
            {tagsError && (
              <div className="mode-warn">
                ⚠ {tagsError}
                <br />백엔드가 떠 있는지, 계기 리스트 경로가 맞는지 확인하십시오.
              </div>
            )}
            <select value={tag} onChange={e => setTag(e.target.value)}>
              {filteredTags.map(t => (
                <option key={t.tag + (t.kind || '')} value={t.tag}>
                  {/* 입력 기준 조회에서는 종류를 붙이지 않는다. 목록에
                      계기와 출력이 섞여 있는 것이 정상인데(펌프가 도는
                      상태가 밸브 개방의 조건이 되는 식), '· 출력' 이
                      붙어 있으면 잘못 걸러진 것처럼 읽힌다. */}
                  {t.kind === 'output' && !(tab === 'interlock' && asInput)
                    ? `${t.tag} · 출력`
                    : `${t.tag}${t.service ? ' — ' + t.service : ''}`}
                </option>
              ))}
            </select>
          </div>
          {filteredTags.find(t => t.tag === tag) && (
            <div className="field-hint" style={{ marginBottom: 10, lineHeight: 1.4 }}>
              {(() => {
                const t = filteredTags.find(x => x.tag === tag)
                // 인터락에만 등장하는 태그는 계기 리스트에 없어 제조사·
                // 모델이 비어 있다. 비어 있는 칸을 구분자로 잇지 않는다 —
                // '· ' 만 덩그러니 남으면 자료가 깨진 것처럼 보인다.
                const parts = [t.maker, t.model].filter(Boolean).join(' ')
                const line = [parts, t.service].filter(Boolean).join(' · ')
                return line || '인터락 리스트에만 등장하는 태그입니다.'
              })()}
            </div>
          )}
        </div>

        {tab === 'alarm' && (
          <div className="sidebar-section">
            <h3>알람 조건</h3>
            <div className="field">
              <label>알람 문구 / 증상</label>
              <input value={alarm} onChange={e => setAlarm(e.target.value)}
                placeholder="예: acid residual low · 산 잔량 10% 미만 경고" />
            </div>
            <div className="field">
              <label>계기 화면 코드 (선택)</label>
              <input value={code} onChange={e => setCode(e.target.value)} placeholder="선택" />
            </div>
            <div className="field">
              <label>검색 모드</label>
              <select value={mode} onChange={e => setMode(e.target.value)}>
                <option value="lexical">lexical (BM25)</option>
                <option value="hybrid">hybrid</option>
                <option value="full">full + rerank</option>
              </select>
              {health?.error && (
                <div className="mode-warn">⚠ 백엔드 상태 확인 실패 — {health.error}</div>
              )}
              {health?.degraded?.length > 0 && mode !== 'lexical' && (
                <div className="mode-warn">
                  ⚠ 실제 구성 <b>{health.effective_mode}</b> (강등: {health.degraded.join(', ')})
                  <br />Ollama / 리랭커를 확인하십시오.
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'interlock' && (
          <div className="sidebar-section">
            <h3>인터락 조건</h3>
            <div className="field">
              <label>동작</label>
              <select value={ilAction} onChange={e => setIlAction(e.target.value)} disabled={asInput}>
                {['OPEN','CLOSE','START','STOP','ON','OFF'].map(a => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>
            <label className="check-row">
              <input type="checkbox" checked={asInput} onChange={e => setAsInput(e.target.checked)} />
              입력 태그 기준 조회
            </label>
          </div>
        )}

        <div className="sidebar-footer">
          시연용 합성 데이터입니다.
          <br />실제 설비 데이터가 아닙니다.
        </div>
      </aside>

      {/* 접혔을 때만 보이는 복귀 버튼 */}
      <button className="nav-reopen" onClick={() => setNavOpen(true)}
        title="사이드바 보이기 (Ctrl+B)" aria-label="사이드바 보이기">›</button>

      <main className={`main ${freeMode ? 'free-frame' : ''}`}>
        {/* 강등 배너 — 탭·모드와 무관하게 항상 보인다.
            벡터 검색이 꺼지면 대부분의 질의가 거절로 끝나는데, 거절은
            정상 동작처럼 보여서 원인을 짚을 수 없다. 실제로 "모든 태그가
            abstain" 으로 관찰됐다. 사유와 결과를 같이 띄운다. */}
        {health?.degraded?.length > 0 && (
          <div className="degrade-banner">
            <div className="degrade-head">
              ⚠ 검색이 강등되었습니다 — {health.label || health.effective_mode}
            </div>
            {(health.degrade_detail || []).map(d => (
              <div className="degrade-item" key={d.component}>
                <b>{d.component}</b> · {d.reason}
                {d.impact && <div className="degrade-impact">{d.impact}</div>}
              </div>
            ))}
            <div className="degrade-fix">
              run_claude.bat 으로 실행했는지, Ollama 가 떠 있는지
              (<code>ollama list</code> 에 bge-m3) 확인하십시오.
            </div>
          </div>
        )}

        {tab === 'alarm' && (
          <AlarmView
            key={`alarm-${tag}`}
            tag={tag} alarm={alarm} code={code} mode={mode} free={freeMode}
            onResult={setScreen}
            botPending={botPending}
            onBotHandled={() => setBotPending(null)}
            onAlarmChange={setAlarm}
            onPickTag={setTag}
          />
        )}
        {tab === 'interlock' && (
          <InterlockView
            key={`il-${tag}-${ilAction}-${asInput}`}
            tag={tag} action={ilAction} asInput={asInput} free={freeMode}
            botPending={botPending}
            onBotHandled={() => setBotPending(null)}
          />
        )}
        {tab === 'panel' && (
          <PanelView key="panel" tag={tag} panelSel={panelSel} cardSel={cardSel} onPickTag={setTag} free={freeMode} />
        )}
        {tab === 'ingest' && <IngestView free={freeMode} />}
      </main>

      <HelpBot
        screen={screen}
        free={freeMode}
        tags={tags}
        currentTag={tag}
        currentTab={tab}
        onCommand={(cmd) => {
          // 공통: 태그/탭 전환
          if (cmd.tag) setTag(cmd.tag)
          if (cmd.tab) setTab(cmd.tab)
          if (cmd.alarm != null) setAlarm(cmd.alarm)
          if (cmd.action) setIlAction(cmd.action)
          if (cmd.panel) setPanelSel(cmd.panel)
          if (cmd.card) setCardSel(cmd.card)
          if (cmd.asInput != null) setAsInput(cmd.asInput)
          // 화면 액션은 해당 뷰에서 처리
          if (cmd.type && cmd.type !== 'navigate') {
            setBotPending(cmd)
          }
        }}
      />
    </div>
  )
}

/* ══════════════════════════════════════════════════════════
   알람 조회 (v1 메인 화면)
   ══════════════════════════════════════════════════════════ */
/* 태그별 조치 이력 통계 — 말썽 많은 순 상위만.
 *
 * 세는 것은 조회 횟수가 아니라 「조치 결과 입력」으로 저장된 작업
 * 기록(WO) 건수다. 조회는 흔적을 남기지 않는다. 오경보 판정도 사람이
 * 출동해 확인한 기록이므로 포함된다 — 그래서 이름이 "고장 건수" 가
 * 아니라 "조치 이력" 이다. 판정하지 않고 세기만 한다. */
function HistoryStats({ onPickTag }) {
  const [st, setSt] = useState(null)
  useEffect(() => {
    get('/history/stats').then(setSt).catch(() => setSt(null))
  }, [])
  if (!st || !st.top?.length) return null
  const max = st.top[0].total
  const SEG = [
    ['불일치', 'var(--bad, #f87171)'],
    ['부분일치', '#d9a441'],
    ['일치', 'var(--match, #34d399)'],
  ]
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-head" style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6 }}>
        <span>조치 이력 많은 태그</span>
        <span style={{ fontSize: '0.74rem', color: 'var(--faint)', fontWeight: 400 }}>
          저장된 작업 기록 {st.total_records}건 기준 · 조회 횟수 아님 · 오경보 포함
        </span>
      </div>
      <div className="panel-body">
        {st.top.map(row => (
          <div key={row.tag}
            onClick={() => onPickTag?.(row.tag)}
            title={`${row.tag} 선택 — 일치 ${row.일치} · 부분일치 ${row.부분일치} · 불일치 ${row.불일치}`}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '4px 2px', cursor: 'pointer',
            }}>
            <span style={{ width: 86, fontFamily: 'monospace', fontSize: '0.82rem' }}>
              {row.tag}
            </span>
            <span style={{ flex: 1, display: 'flex', height: 14, borderRadius: 4, overflow: 'hidden', background: 'rgba(148,163,184,0.10)' }}>
              {SEG.map(([k, color]) => row[k] > 0 && (
                <span key={k} style={{
                  width: `${(row[k] / max) * 100}%`,
                  background: color, opacity: 0.85,
                }} />
              ))}
            </span>
            <span style={{ width: 76, fontSize: '0.78rem', color: 'var(--faint)', textAlign: 'right' }}>
              {row.total}건 · {row.last?.slice(2) || ''}
            </span>
          </div>
        ))}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: '0.74rem', color: 'var(--faint)' }}>
          <span>
            <span style={{ color: 'var(--bad, #f87171)' }}>■</span> 매뉴얼과 불일치{' '}
            <span style={{ color: '#d9a441' }}>■</span> 부분일치{' '}
            <span style={{ color: 'var(--match, #34d399)' }}>■</span> 일치
          </span>
          {st.rest_tags > 0 && <span>그 외 {st.rest_tags}개 태그 · {st.rest_records}건</span>}
        </div>
      </div>
    </div>
  )
}


function AlarmView({ tag, alarm, code, mode, free, botPending, onBotHandled, onAlarmChange, onResult, onPickTag }) {
  const [inst, setInst] = useState(null)
  const [diag, setDiag] = useState(null)
  const [advice, setAdvice] = useState(null)

  // 조회 결과가 바뀌면 챗봇이 볼 수 있게 위로 올린다.
  React.useEffect(() => {
    if (!onResult) return
    if (!diag) { onResult(null); return }
    onResult({
      tag,
      alarm,
      decision: diag.decision,
      grade: diag.grade,
      evidence: (diag.evidence || []).slice(0, 6).map(e => ({
        id: e.id, title: e.title, text: e.text, cite: e.cite, kind: e.kind,
        summary_ko: e.summary_ko || '',
      })),
      steps: (advice?.steps || []).map(s => ({
        title: s.title, detail: s.detail,
      })),
    })
  }, [diag, advice, tag, alarm])
  const [loading, setLoading] = useState(false)
  const [advLoading, setAdvLoading] = useState(false)
  const [repLoading, setRepLoading] = useState(false)
  // 4D 리포트의 D3(확정 원인)·D4(실시 조치)는 「조치 결과 입력」에서
  // 저장한 값을 그대로 쓴다. 예전에는 별도의 4D 기입란이 있어 같은
  // 내용을 두 번 입력해야 했다 — 실제 원인과 확정 원인, 조치 내용과
  // 실시 조치는 같은 것이다. 저장 전에 PDF 를 뽑으면 '(조치 후 기입)'
  // 으로 남아, 종이로 뽑아 현장에서 손으로 채우는 흐름도 그대로 된다.
  const [fb4d, setFb4d] = useState(null)
  const [error, setError] = useState(null)
  const [citeOpen, setCiteOpen] = useState(null)
  const [dwgOpen, setDwgOpen] = useState(null)
  const [fbOpen, setFbOpen] = useState(false)

  // 태그 바뀌면 기기 정보 + 이력 로드 (이전 태그 잔상·늦은 응답 차단)
  useEffect(() => {
    if (!tag) return
    let cancelled = false
    setInst(null)
    setDiag(null)
    setAdvice(null)
    setFb4d(null)   // 다른 태그의 조치 결과가 리포트에 실리지 않게
    setCiteOpen(null)
    setDwgOpen(null)
    setError(null)
    get(`/instrument/${encodeURIComponent(tag)}`)
      .then(d => { if (!cancelled) setInst(d) })
      .catch(() => { if (!cancelled) setInst(null) })
    return () => { cancelled = true }
  }, [tag])

  // 챗봇 명령 실행
  useEffect(() => {
    if (!botPending) return
    const cmd = botPending
    if (cmd.type === 'diagnose') {
      // 알람 문구가 명령에 있으면 반영 후 조회
      const run = async () => {
        setLoading(true)
        setError(null)
        setDiag(null)
        try {
          const body = {
            tag: cmd.tag || tag,
            alarm: cmd.alarm != null ? cmd.alarm : alarm,
            code: cmd.code || code,
            mode,
          }
          setDiag(await post('/diagnose', body))
          if (cmd.openDrawing) {
            // 조회 후 도면 자동 오픈은 inst 로드 후 처리
          }
        } catch (e) {
          setError(e.message)
        } finally {
          setLoading(false)
          onBotHandled && onBotHandled()
        }
      }
      run()
    } else if (cmd.type === 'drawing') {
      // 계기 정보에서 도면 열어보기
      const open = async () => {
        try {
          const data = await get(`/instrument/${encodeURIComponent(cmd.tag || tag)}`)
          setInst(data)
          const dwgs = data?.drawings || []
          if (dwgs.length) {
            // P&ID 우선
            const prefer = dwgs.find(d => /p\s*&\s*i\s*d|pid/i.test(`${d.type} ${d.file} ${d.sheet_no}`)) || dwgs[0]
            setDwgOpen(prefer)
          } else {
            setError('이 태그에 연결된 도면이 없습니다.')
          }
        } catch (e) {
          setError(e.message)
        } finally {
          onBotHandled && onBotHandled()
        }
      }
      open()
    } else if (cmd.type === 'advice') {
      setAdvLoading(true)
      post('/advice', { tag, alarm, code, mode, free })
        .then(setAdvice)
        .catch(e => setError(e.message))
        .finally(() => { setAdvLoading(false); onBotHandled && onBotHandled() })
    } else if (cmd.type === 'report') {
      // 리포트는 버튼 로직 재사용
      onBotHandled && onBotHandled()
    } else {
      onBotHandled && onBotHandled()
    }
  }, [botPending])

  async function runDiagnose() {
    setLoading(true)
    setError(null)
    setDiag(null)
    setAdvice(null)
    try {
      setDiag(await post('/diagnose', { tag, alarm, code, mode }))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function runAdvice() {
    setAdvLoading(true)
    setError(null)
    try {
      setAdvice(await post('/advice', { tag, alarm, code, mode, free }))
    } catch (e) {
      setError(e.message)
    } finally {
      setAdvLoading(false)
    }
  }

  async function deleteHistory(woNo) {
    if (!woNo) return
    if (!window.confirm(`이력 ${woNo} 을(를) 삭제할까요?\n이 작업은 되돌릴 수 없습니다.`)) return
    try {
      await del(`/history/${encodeURIComponent(woNo)}`)
      // 삭제 후 계기 정보(이력 포함) 다시 로드
      const data = await get(`/instrument/${encodeURIComponent(tag)}`)
      setInst(data)
    } catch (e) {
      setError(e.message || '이력 삭제에 실패했습니다.')
    }
  }

  async function runReport() {
    setRepLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tag, alarm, code, mode,
          tech: fb4d?.tech || '',
          confirmed_cause: fb4d?.confirmed_cause || '',
          final_action: fb4d?.final_action || '',
          parts: fb4d?.parts || '-',
          duration_min: fb4d?.duration_min ?? null,
          // 화면에 떠 있는 조치 순서를 그대로 넘긴다. 리포트가 서버에서
          // 조치를 다시 만들면 화면과 다른 문장이 나올 수 있고, LLM 을
          // 한 번 더 부르느라 즉시 나오지도 않는다. 이력 카드는 근거이지
          // 조치 단계가 아니므로 뺀다 — D3 에 따로 실린다.
          steps: (advice?.steps || [])
            .filter(s => s.kind !== 'history')
            .map(s => s.title)
            .filter(Boolean),
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || res.statusText)
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `4D_Report_${tag}_${new Date().toISOString().slice(0,10)}.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e.message)
    } finally {
      setRepLoading(false)
    }
  }

  const manuals = (diag?.evidence || []).filter(e => e.kind === 'manual_text')
  const codes = (diag?.evidence || []).filter(e => e.kind === 'error_code')
  const history = inst?.history || []
  const instrument = inst?.instrument || {}
  const drawings = inst?.drawings || []

  return (
    <>
      <div className="main-header">
        <h1>Plant Maintenance Copilot <span>· 알람 상세</span><FreeBadge show={free} /></h1>
      </div>

      {/* 태그 메타 */}
      <div className="tag-header">
        <div className="item">
          <span className="label">TAG</span>
          <span className="value tag">{tag}</span>
        </div>
        <div className="item">
          <span className="label">Maker / Model</span>
          <span className="value">{[instrument.maker, instrument.model].filter(Boolean).join(' ') || '—'}</span>
        </div>
        <div className="item">
          <span className="label">Service</span>
          <span className="value">{instrument.service || '—'}</span>
        </div>
        <div className="item">
          <span className="label">신호 / 계측</span>
          <span className="value">{[instrument.signal, instrument.meas_type].filter(Boolean).join(' · ') || '—'}</span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        <button className="btn primary" style={{ width: 'auto', padding: '8px 16px' }}
          onClick={runDiagnose} disabled={loading || !alarm.trim()}>
          {loading ? '조회 중…' : '알람 조회'}
        </button>
        <button className="btn" style={{ width: 'auto', padding: '8px 16px' }}
          onClick={runAdvice} disabled={advLoading || !alarm.trim()}>
          {advLoading ? '생성 중…' : '조치 순서 생성'}
        </button>
        <button className="btn" style={{ width: 'auto', padding: '8px 16px', borderColor: 'var(--safety)', color: 'var(--safety)' }}
          onClick={runReport} disabled={repLoading || !tag}>
          {repLoading ? 'PDF 생성 중…' : '4D 리포트 PDF'}
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {/* CRAG 판정 */}
      {diag && (
        <>
          <div className="result-bar">
            <span className={`badge ${diag.decision}`}>{diag.decision}</span>
            <span className="grade-text">충분성 {diag.grade?.toFixed(2)} · {diag.grade_reason}</span>
          </div>
          {diag.trace?.length > 0 && (
            <div className="trace-box">
              {diag.trace.map((t, i) => <div key={i}>{t}</div>)}
            </div>
          )}
        </>
      )}

      {/* 조회 전 초기 화면 — 어디부터 볼지 알려주는 이력 통계.
          조회가 실행되면 자리를 비켜 준다. */}
      {!diag && !loading && <HistoryStats onPickTag={onPickTag} />}

      {/* 2열: 매뉴얼 | 현장 이력 */}
      <div className="two-col">
        <div className="panel">
          <div className="panel-head">
            매뉴얼 · 벤더 문서
            {diag ? ` · ${manuals.length + codes.length}건` : ''}
          </div>
          <div className="panel-body">
            {!diag && !loading && <div className="empty" style={{ padding: 12 }}>알람 조회를 실행하세요</div>}
            {diag && manuals.length === 0 && codes.length === 0 && (
              <div className="empty" style={{ padding: 12 }}>관련 매뉴얼/코드 없음</div>
            )}
            <div className="ev-list">
              {[...codes, ...manuals].map((e, i) => (
                <div className="ev-item" key={i}>
                  <div className="ev-meta">
                    <span className={`kind-pill ${e.kind}`}>
                      {e.kind === 'error_code' ? 'CODE' : 'MANUAL'}
                    </span>
                    <span className="ev-title">{e.title}</span>
                    {e.score != null && <span className="ev-score">{Number(e.score).toFixed(3)}</span>}
                  </div>
                  {e.summary_ko ? (
                    <>
                      <div className="ev-text ev-summary-ko">{e.summary_ko}</div>
                      <details className="ev-orig">
                        <summary>원문 (영문)</summary>
                        <div className="ev-text ev-orig-text">{e.text}</div>
                      </details>
                    </>
                  ) : (
                    <div className="ev-text">{e.text}</div>
                  )}
                  <div className="ev-cite">{e.cite}</div>
                  {e.cite && (
                    <button
                      className="link-btn"
                      onClick={() => setCiteOpen(citeOpen?.idx === i ? null : { idx: i, cite: e.cite, source: e.source })}
                    >
                      원문 보기
                    </button>
                  )}
                  {citeOpen && citeOpen.idx === i && (
                    <ManualPageView cite={citeOpen.cite} source={citeOpen.source} text={e.text} />
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">현장 이력 · 우리 경험 · {history.length}건</div>
          <div className="panel-body">
            {history.length === 0 ? (
              <div className="empty" style={{ padding: 12 }}>관련 보수 이력이 없습니다</div>
            ) : (
              <div className="ev-list">
                {history.map((h, i) => {
                  const mc = MATCH_COLOR[h.manual_match] || MATCH_COLOR['부분일치']
                  return (
                    <div className="ev-item" key={h.wo_no || i}>
                      <div className="ev-meta">
                        <span style={{ fontFamily: 'var(--mono)', fontSize: '0.78rem', color: 'var(--muted)' }}>
                          {h.date} · {h.wo_no}
                        </span>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{
                            fontSize: '0.68rem', fontWeight: 700, padding: '2px 7px',
                            borderRadius: 4, background: mc.bg, color: mc.color, border: `1px solid ${mc.border}`,
                          }}>{h.manual_match}</span>
                          {h.wo_no && (
                            <button
                              type="button"
                              className="btn-ghost"
                              title="이 이력 삭제"
                              style={{
                                fontSize: '0.68rem', padding: '1px 6px',
                                color: 'var(--danger)', border: '1px solid var(--danger-line)',
                                borderRadius: 3, background: 'var(--danger-soft)', cursor: 'pointer',
                              }}
                              onClick={() => deleteHistory(h.wo_no)}
                            >
                              삭제
                            </button>
                          )}
                        </span>
                      </div>
                      <div className="ev-text">
                        <strong>실제원인</strong> {h.root_cause}
                      </div>
                      <div className="ev-text">
                        <strong>조치</strong> {h.action_taken}
                        {h.duration_min ? ` · ${h.duration_min}분` : ''}
                        {h.parts && h.parts !== '-' ? ` · ${h.parts}` : ''}
                      </div>
                      {h.symptom && <div className="ev-cite">증상: {h.symptom}</div>}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 이력 vs 매뉴얼 불일치 안내 */}
      {history.some(h => h.manual_match === '불일치') && (
        <div className="info-banner">
          현장 이력이 매뉴얼과 다른 원인을 기록한 사례가 있습니다.
          (불일치 {history.filter(h => h.manual_match === '불일치').length}건 /
          일치 {history.filter(h => h.manual_match === '일치').length}건 /
          부분일치 {history.filter(h => h.manual_match === '부분일치').length}건)
        </div>
      )}

      {/* 도면 / 패널 정보 바 */}
      <div className="dwg-bar">
        <div className="dwg-item"><span>도면</span><b>{drawings[0]?.sheet_no || instrument.dwg_no || '—'}</b></div>
        <div className="dwg-item"><span>PDF</span><b>{drawings[0] ? `${drawings[0].page} p` : '—'}</b></div>
        <div className="dwg-item"><span>패널</span><b>{instrument.panel || '—'}</b></div>
        <div className="dwg-item"><span>단자</span><b>{instrument.terminal || '—'}</b></div>
        <div className="dwg-item"><span>PLC</span><b>{instrument.plc || '—'}</b></div>
        <div className="dwg-item"><span>슬롯/채널</span><b>{[instrument.slot, instrument.channel].filter(Boolean).join(' / ') || '—'}</b></div>
      </div>

      {drawings.length > 0 && (
        <div className="panel" style={{ marginTop: 12 }}>
          <div className="panel-head">도면 목록</div>
          <div className="panel-body">
            {drawings.map((d, i) => (
              <div key={i}>
                <div className="dwg-row">
                  <span className="kind-pill error_code">{d.type}</span>
                  <span style={{ fontWeight: 600 }}>{d.sheet_no}</span>
                  <span className="ev-cite">{d.file} p.{d.page} · find: {d.find}</span>
                  <button className="link-btn" style={{ marginLeft: 'auto' }}
                    onClick={() => setDwgOpen(dwgOpen && dwgOpen.file === d.file && dwgOpen.page === d.page ? null : d)}>
                    {dwgOpen && dwgOpen.file === d.file && dwgOpen.page === d.page ? '도면 닫기' : '도면 보기'}
                  </button>
                </div>
                {dwgOpen && dwgOpen.file === d.file && dwgOpen.page === d.page && (
                  <DrawingView d={d} />
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 조치 순서 */}
      {advice && (
        <div className="panel" style={{ marginTop: 14 }}>
          <div className="panel-head">
            조치 순서 {advice.mock ? '· 근거 나열 (LLM 미사용)' : '· 근거 인용 검증됨'}
          </div>
          <div className="panel-body">
            <div style={{ fontSize: '0.88rem', color: 'var(--ink-2)', marginBottom: 12 }}>
              {advice.summary}
            </div>
            {advice.steps?.map(s => (
              s.kind === 'history'
                ? <HistoryCard key="hist" card={s} />
                : (
                  <div className="step-item" key={s.n}>
                    <div className="step-n">{s.n}</div>
                    <div>
                      <div className="step-title">{s.title}</div>
                      <div className="step-detail">{s.detail}</div>
                      <div className="ev-cite">근거 {s.source} · {s.kind}</div>
                    </div>
                  </div>
                )
            ))}
          </div>
        </div>
      )}

      {advice?.guess && <GuessPanel guess={advice.guess} />}
      {!advice?.guess && advice?.guess_note && (
        <div className="panel" style={{ marginTop: 14 }}>
          <div className="panel-body" style={{
            fontSize: '0.8rem', color: 'var(--faint)', lineHeight: 1.5,
          }}>
            모델 추측을 붙이지 않았습니다 — {advice.guess_note}
          </div>
        </div>
      )}

      {/* 조치 결과 피드백 */}
      <div className="panel" style={{ marginTop: 14 }}>
        <div
          className="panel-head"
          style={{ cursor: 'pointer' }}
          onClick={() => setFbOpen(!fbOpen)}
        >
          {fbOpen ? '▾' : '▸'} 조치 결과 입력 — 다음 조회의 근거가 되고, 4D 리포트 D3·D4 에 실립니다
        </div>
        {fbOpen && (
          <div className="panel-body">
            <FeedbackForm tag={tag} alarm={alarm} onSaved={(saved) => {
              if (saved) setFb4d(saved)
              get(`/instrument/${encodeURIComponent(tag)}`).then(setInst)
            }} />
          </div>
        )}
      </div>

      <div style={{ marginTop: 16, fontSize: '0.75rem', color: 'var(--faint)' }}>
        본 화면의 출력은 참고 정보이며 작업 지시가 아닙니다. 실제 작업은 정비 절차서와 안전 절차(LOTO)를 따르십시오.
      </div>
    </>
  )
}


function parseCite(cite, source) {
  if (source?.file && source?.pdf_page) {
    return { file: source.file, page: Number(source.pdf_page) || 1 }
  }
  const m = String(cite || '').match(/^(.*?\.pdf)\s+p\.(\d+)/i)
  if (m) return { file: m[1], page: Number(m[2]) }
  return null
}

function dpiForScale(scale) {
  // 화면 배율에 비례해 PDF를 다시 래스터라이즈 → 글자 선명
  if (scale >= 3.2) return 400
  if (scale >= 2.2) return 320
  if (scale >= 1.5) return 240
  if (scale >= 1.15) return 200
  return 160
}

function ZoomableImage({ buildSrc, alt }) {
  const [scale, setScale] = useState(1)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const [dpi, setDpi] = useState(160)
  const [imgSrc, setImgSrc] = useState(() => buildSrc(160))
  const [loadingHi, setLoadingHi] = useState(false)
  const dragging = React.useRef(false)
  const last = React.useRef({ x: 0, y: 0 })
  const viewportRef = React.useRef(null)
  const debounceRef = React.useRef(null)

  // 기준 소스 문자열. 이것이 바뀌면 다른 도면·페이지를 보는 것이다.
  const baseSrc = buildSrc(160)

  // 배율 변경 → 고해상도 재요청 (디바운스)
  React.useEffect(() => {
    const want = dpiForScale(scale)
    if (want === dpi) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setLoadingHi(true)
      const next = buildSrc(want)
      const probe = new Image()
      probe.onload = () => {
        setImgSrc(next)
        setDpi(want)
        setLoadingHi(false)
      }
      probe.onerror = () => setLoadingHi(false)
      probe.src = next
    }, 180)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [scale, baseSrc, dpi])   // eslint-disable-line react-hooks/exhaustive-deps

  // 소스가 실제로 바뀌었을 때만 리셋한다 (전체/크롭 전환 등).
  //
  // 이전에는 buildSrc 함수 자체를 의존성으로 삼았다. 호출부에서 인라인
  // 화살표 함수로 넘기므로 렌더마다 새 함수가 되고, 그래서 드래그로
  // setPos 가 불릴 때마다 이 효과가 다시 돌아 위치를 0,0 으로
  // 되돌렸다. 확대는 디바운스 뒤에 적용돼 살아남았지만 드래그는
  // 매 프레임 초기화되어 "잘 안 되는" 것처럼 보였다.
  React.useEffect(() => {
    setScale(1)
    setPos({ x: 0, y: 0 })
    setDpi(160)
    setImgSrc(baseSrc)
  }, [baseSrc])

  React.useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const onWheel = (e) => {
      e.preventDefault()
      e.stopPropagation()
      const delta = e.deltaY > 0 ? -0.12 : 0.12
      setScale(s => {
        const next = Math.min(5, Math.max(0.5, s + delta * s))
        return Math.round(next * 100) / 100
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  function onPointerDown(e) {
    if (e.button !== 0) return
    // 텍스트 선택이 시작되면 드래그가 끊긴다.
    e.preventDefault()
    dragging.current = true
    last.current = { x: e.clientX, y: e.clientY }
    try { e.currentTarget.setPointerCapture(e.pointerId) } catch (_) {}
  }
  function onPointerMove(e) {
    if (!dragging.current) return
    const dx = e.clientX - last.current.x
    const dy = e.clientY - last.current.y
    last.current = { x: e.clientX, y: e.clientY }
    setPos(p => ({ x: p.x + dx, y: p.y + dy }))
  }
  function onPointerUp(e) {
    dragging.current = false
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch (_) {}
  }
  function reset() {
    setScale(1)
    setPos({ x: 0, y: 0 })
  }

  return (
    <div className="zoom-wrap">
      <div className="zoom-toolbar">
        <button type="button" className="zoom-btn" onClick={() => setScale(s => Math.min(5, Math.round((s + 0.25) * 100) / 100))}>＋</button>
        <button type="button" className="zoom-btn" onClick={() => setScale(s => Math.max(0.5, Math.round((s - 0.25) * 100) / 100))}>－</button>
        <button type="button" className="zoom-btn" onClick={reset}>맞춤</button>
        <span className="zoom-label">{Math.round(scale * 100)}%</span>
        <span className="zoom-dpi">{dpi} dpi{loadingHi ? ' · 선명화…' : ''}</span>
        <span className="zoom-hint">휠 확대 시 PDF 재렌더 · 드래그 이동</span>
      </div>
      <div
        ref={viewportRef}
        className="zoom-viewport"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div
          className="zoom-stage"
          style={{
            transform: `translate(${pos.x}px, ${pos.y}px)`,
            width: `${scale * 100}%`,
            height: `${scale * 100}%`,
          }}
        >
          <img src={imgSrc} alt={alt || 'page'} draggable={false} />
        </div>
      </div>
    </div>
  )
}

function ManualPageView({ cite, source, text }) {
  const info = parseCite(cite, source)
  const src = info
    ? `${API}/manual-page?file=${encodeURIComponent(info.file)}&page=${info.page}`
    : null
  return (
    <div className="cite-box">
      <div className="cite-box-title">원문 · {info ? `${info.file} p.${info.page}` : cite}</div>
      {text && <div style={{ marginBottom: 10 }}>{text}</div>}
      {src ? (
        <ZoomableImage
          buildSrc={(dpi) => `${API}/manual-page?file=${encodeURIComponent(info.file)}&page=${info.page}&dpi=${dpi}`}
          alt="manual page"
        />
      ) : null}
      {!src && (
        <div style={{ fontSize: '0.8rem', color: 'var(--danger)', marginTop: 8 }}>
          페이지를 불러오지 못했습니다. 매뉴얼 PDF 경로와 pymupdf를 확인하세요.
        </div>
      )}
    </div>
  )
}

function DrawingView({ d }) {
  const src = `${API}/drawing-page?file=${encodeURIComponent(d.file)}&page=${d.page}&find=${encodeURIComponent(d.find || '')}&crop=1`
  const full = `${API}/drawing-page?file=${encodeURIComponent(d.file)}&page=${d.page}&find=${encodeURIComponent(d.find || '')}&crop=0`
  const [mode, setMode] = useState('crop')
  return (
    <div className="cite-box" style={{ marginTop: 8 }}>
      <div className="cite-box-title">
        {d.type} · {d.sheet_no} · {d.file} p.{d.page}
        <button className="link-btn" style={{ marginLeft: 12 }} onClick={() => setMode(mode === 'crop' ? 'full' : 'crop')}>
          {mode === 'crop' ? '전체 도면' : '태그 확대'}
        </button>
      </div>
      <ZoomableImage
        key={mode}
        buildSrc={(dpi) =>
          `${API}/drawing-page?file=${encodeURIComponent(d.file)}&page=${d.page}&find=${encodeURIComponent(d.find || '')}&crop=${mode === 'crop' ? 1 : 0}&dpi=${dpi}`
        }
        alt="drawing"
      />
    </div>
  )
}


/* ══════════════════════════════════════════════════════════
   판넬·카드 조회 — 위치와 카드 상실 영향

   판넬은 위치·구성 조회 대상이다. 상실 영향은 **카드 단위로만** 낸다.
   이중화(S7-400H/410H) 구성에서는 CPU·전원·통신이 이중화되고 랙 증설도
   스위칭으로 대응하므로, 판넬 전체가 한 번에 죽는 상황이 성립하지
   않는다. 성립하지 않는 시나리오에 숫자를 붙이면 현장 판단을 왜곡한다.

   트립 여부도 표시하지 않는다 — 대체값 정책이 리스트에 없기 때문이다.
   말할 수 있는 것은 '무엇에 의존하는가'와 '남는 보호가 있는가'까지다.
   ══════════════════════════════════════════════════════════ */
function ioTypeFamily(t) {
  const u = String(t || '').toUpperCase()
  if (u.includes('DO')) return 'do'
  if (u.includes('AO')) return 'ao'
  if (u.includes('DI')) return 'di'
  if (u.includes('AI')) return 'ai'
  return 'xx'
}

/** PLC 랙 배치 — 슬롯 카드만 간단히 (채널 점 없음) */
function RackLayout({ cards, selected, onSelect }) {
  const byRack = {}
  for (const c of cards || []) {
    const r = String(c.rack != null && c.rack !== '' ? c.rack : '0')
    if (!byRack[r]) byRack[r] = []
    byRack[r].push(c)
  }
  const racks = Object.keys(byRack).sort((a, b) => (Number(a) || 0) - (Number(b) || 0))

  return (
    <div className="rack-board">
      {racks.map(rack => (
        <div key={rack} className="rack-row">
          <div className="rack-label">R{rack}</div>
          <div className="rack-slots">
            {byRack[rack]
              .slice()
              .sort((a, b) => (Number(a.slot) || 0) - (Number(b.slot) || 0))
              .map(c => {
                const fam = ioTypeFamily(c.io_type)
                return (
                  <button
                    key={c.card}
                    type="button"
                    className={`rack-module fam-${fam} ${selected === c.card ? 'selected' : ''}`}
                    onClick={() => onSelect(c.card)}
                    title={`${c.card} · ${c.io_type || 'IO'} · ${c.points || 0}점`}
                  >
                    <span className="rack-mod-type">{c.io_type || 'IO'}</span>
                    <span className="rack-mod-slot">S{c.slot}</span>
                    <span className="rack-mod-pts">{c.points || 0}</span>
                  </button>
                )
              })}
          </div>
        </div>
      ))}
    </div>
  )
}

function PanelView({ tag, panelSel, cardSel, onPickTag, free }) {
  const [panels, setPanels] = useState([])
  const [sel, setSel] = useState(null)
  const [data, setData] = useState(null)
  const [cards, setCards] = useState([])
  const [card, setCard] = useState(null)
  const [cardImpact, setCardImpact] = useState(null)
  const [cc, setCc] = useState(null)
  const [dwgOpen, setDwgOpen] = useState(false)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  // 늦게 도착한 이전 요청이 화면을 덮어쓰지 못하게 순번 가드
  const panelReq = React.useRef(0)
  const cardReq = React.useRef(0)

  useEffect(() => {
    get('/panels')
      .then(r => {
        setPanels(r.panels || [])
        if (r.panels?.length) setSel(prev => prev || r.panels[0].panel)
      })
      .catch(e => setError(`판넬 목록을 불러오지 못했습니다 — ${e.message}`))
  }, [])

  // 챗봇이 판넬/카드를 지정했으면 그쪽이 우선이다
  useEffect(() => {
    if (panelSel) setSel(panelSel)
  }, [panelSel])

  useEffect(() => {
    if (cardSel) setCard(cardSel)
  }, [cardSel])

  // 다른 탭에서 고른 태그가 있으면 그 태그가 물린 판넬로 맞춰 준다
  useEffect(() => {
    if (!tag) return
    let cancelled = false
    get(`/panel-of/${encodeURIComponent(tag)}`)
      .then(r => { if (!cancelled && r?.panel) setSel(r.panel) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [tag])

  useEffect(() => {
    if (!sel) return
    const reqId = ++panelReq.current
    // 이전 판넬 잔상 제거 — 로딩 전에 전부 비운다
    setLoading(true)
    setError(null)
    setDwgOpen(false)
    setData(null)
    setCards([])
    setCard(null)
    setCardImpact(null)
    Promise.all([get(`/panel/${encodeURIComponent(sel)}`),
                 get(`/cards?panel=${encodeURIComponent(sel)}`)])
      .then(([d, c]) => {
        if (reqId !== panelReq.current) return  // 오래된 응답 무시
        setData(d)
        setCards(c.cards || [])
        if (c.cards?.length) setCard(c.cards[0].card)
      })
      .catch(e => {
        if (reqId !== panelReq.current) return
        setError(e.message)
        setData(null)
        setCards([])
      })
      .finally(() => {
        if (reqId === panelReq.current) setLoading(false)
      })
  }, [sel])

  // 카드가 실제 단일 고장 단위다. 판넬을 고르면 카드부터 보여준다.
  useEffect(() => {
    if (!card) { setCardImpact(null); return }
    const reqId = ++cardReq.current
    setCardImpact(null)  // 이전 카드 영향 잔상 제거
    get(`/card?id=${encodeURIComponent(card)}&impact=1`)
      .then(r => { if (reqId === cardReq.current) setCardImpact(r) })
      .catch(() => { if (reqId === cardReq.current) setCardImpact(null) })
  }, [card])

  useEffect(() => {
    get('/common-cause').then(setCc).catch(() => setCc(null))
  }, [])

  const loc = data?.location
  const dwg = loc ? {
    type: 'ARRANGEMENT', sheet_no: loc.sheet_no,
    file: loc.file, page: loc.page, find: loc.find,
  } : null

  return (
    <>
      <div className="main-header">
        <h1>Plant Maintenance Copilot <span>· 판넬 조회</span><FreeBadge show={free} /></h1>
      </div>

      <div className="panel-chips">
        {panels.map(p => (
          <button key={p.panel} type="button"
            className={`panel-chip ${sel === p.panel ? 'active' : ''}`}
            onClick={() => setSel(p.panel)}>
            <b>{p.panel}</b>
            <span>{p.points}점 · {p.grid || '위치 없음'}</span>
          </button>
        ))}
      </div>

      {!loading && !error && panels.length === 0 && (
        <div className="banner-warn">
          판넬 목록이 비어 있습니다. IO List 에 PANEL / RACK / SLOT 열이 채워져 있는지,
          서버 로그의 API <code>/api/panels</code> 응답을 확인하십시오.
        </div>
      )}

      {error && <div className="error-box">{error}</div>}
      {loading && <div className="loading">조회 중…</div>}

      {!loading && data && (
        <>
          <div className="tag-header">
            <div className="item"><span className="label">판넬</span><span className="value tag">{data.panel}</span></div>
            <div className="item"><span className="label">종류</span><span className="value">{loc?.kind || '—'}</span></div>
            <div className="item"><span className="label">구역</span><span className="value">{loc?.area || '—'}</span></div>
            <div className="item"><span className="label">도면 그리드</span><span className="value">{loc?.grid || '—'}</span></div>
            <div className="item"><span className="label">설치</span><span className="value">{loc ? (loc.indoor ? '실내' : '옥외') : '—'}</span></div>
            <div className="item"><span className="label">계기</span><span className="value">{data.points}점</span></div>
          </div>

          {!loc && (
            <div className="banner-warn">
              {data.panel} 의 배치 정보가 없습니다. data/make_arrangement.py 를 실행해
              PANEL_LOCATIONS.csv 를 생성하십시오.
            </div>
          )}

          {dwg && (
            <div className="panel">
              <div className="panel-head">
                배치 도면 · {dwg.sheet_no} · p.{dwg.page}
                <button className="link-btn" style={{ marginLeft: 12 }}
                  onClick={() => setDwgOpen(!dwgOpen)}>
                  {dwgOpen ? '도면 닫기' : '도면 보기'}
                </button>
              </div>
              {dwgOpen && <div className="panel-body"><DrawingView d={dwg} /></div>}
            </div>
          )}

          {cards.length === 0 && (
            <div className="banner-warn">
              이 판넬에 카드(RACK/SLOT) 정보가 없습니다. IO List 의 RACK·SLOT 값을 확인하십시오.
            </div>
          )}

          {cards.length > 0 && (
            <div className="panel">
              <div className="panel-head">
                IO 카드 {cards.length}장 — Rack / Slot 배치
              </div>
              <div className="panel-body">
                <div className="panel-note" style={{ marginTop: 0, marginBottom: 12 }}>
                  슬롯 카드를 클릭하면 아래에 채널·인터락 영향이 표시됩니다.
                </div>
                <RackLayout cards={cards} selected={card} onSelect={setCard} />

                {cardImpact && (!cardImpact.card || cardImpact.card === card) && (
                  <>
                    <div className="impact-summary">
                      <div>카드 <b>{cardImpact.card || card}</b></div>
                      <div><b>{cardImpact.points}</b>점 상실</div>
                      <div>의존 인터락 <b>{cardImpact.dependencies.length}</b>건 · 안전 <b className="warn">{cardImpact.safety_count}</b>건</div>
                      <div>영향 출력 <b>{cardImpact.affected_outputs.length}</b>건</div>
                    </div>

                    {/* 잃는 채널 — 인터락 표에는 조건에 걸린 태그만 나오므로
                        이 표가 없으면 인터락 무관 계기가 화면에서 사라진다.
                        "이 카드 내리면 뭘 잃나" 의 답은 여기가 전부다. */}
                    <div className="panel-sub">잃는 채널 {cardImpact.points}점</div>
                    <table className="impact-table">
                      <thead>
                        <tr><th>Ch</th><th>태그</th><th>서비스</th><th>단자</th><th>신호</th><th>인터락</th></tr>
                      </thead>
                      <tbody>
                        {(cardImpact.channels || []).map(ch => (
                          <tr key={ch.tag} className={ch.safety ? 'row-safety' : ''}>
                            <td>{ch.ch}</td>
                            <td>
                              {ch.safety && <span className="star">★</span>}
                              <button type="button" className="tag-pill"
                                onClick={() => onPickTag?.(ch.tag)}>{ch.tag}</button>
                            </td>
                            <td>{ch.service || '—'}</td>
                            <td>{ch.terminal || '—'}</td>
                            <td className="dim">{ch.signal || '—'}</td>
                            <td className={ch.interlocks?.length ? '' : 'dim'}>
                              {ch.interlocks?.length
                                ? ch.interlocks.join(', ')
                                : '지시·기록만'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>

                    {cardImpact.dependencies.length > 0 ? (
                      <>
                      <div className="panel-sub">의존 인터락</div>
                      <table className="impact-table">
                        <thead>
                          <tr><th>인터락</th><th>출력</th><th>동작</th><th>잃는 조건</th><th>남는 보호</th><th>바이패스</th></tr>
                        </thead>
                        <tbody>
                          {cardImpact.dependencies.map(r => (
                            <tr key={r.il_no} className={r.safety ? 'row-safety' : ''}>
                              <td>{r.safety && <span className="star">★</span>}{r.il_no}</td>
                              <td>{r.output_tag}</td>
                              <td>{r.kind} → {r.action}</td>
                              <td>{r.lost_tags.join(', ')} <em className="dim">/ {r.logic || '논리 없음'}</em></td>
                              <td className={r.remaining_protection.startsWith('없음') ? 'warn' : ''}>{r.remaining_protection}</td>
                              <td>{r.bypassable ? '가능' : '불가'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      </>
                    ) : (
                      <div className="panel-note">
                        이 카드의 계기는 인터락 조건에 걸려 있지 않습니다 —
                        지시·기록만 상실합니다.
                      </div>
                    )}
                    <div className="caveat">※ {cardImpact.caveat}</div>
                  </>
                )}
              </div>
            </div>
          )}

          {cc && cc.loaded && (
            <div className="panel">
              <div className="panel-head">
                공통원인 점검 — 한 인터락의 조건이 같은 카드에 몰려 있는가
              </div>
              <div className="panel-body">
                <div className="impact-summary">
                  <div>인터락 <b>{cc.checked}</b>건 점검</div>
                  <div>지적 <b className={cc.findings.length ? 'warn' : ''}>{cc.findings.length}</b>건</div>
                </div>
                {cc.findings.length > 0 ? (
                  <table className="impact-table">
                    <thead>
                      <tr><th>인터락</th><th>출력</th><th>결합</th><th>같은 카드</th><th>영향</th></tr>
                    </thead>
                    <tbody>
                      {cc.findings.map(f => (
                        <tr key={f.il_no} className={f.safety ? 'row-safety' : ''}>
                          <td>{f.safety && <span className="star">★</span>}{f.il_no}</td>
                          <td>{f.output_tag}</td>
                          <td>{f.logic || '—'}</td>
                          <td>{Object.entries(f.shared_cards).map(([c, t]) => `${c} ← ${t.join(', ')}`).join(' / ')}</td>
                          <td className="warn">{f.severity}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="panel-note">지적 없음.</div>
                )}
                <div className="caveat">※ {cc.note}</div>
              </div>
            </div>
          )}

        </>
      )}

      <FloodPanel />
    </>
  )
}


function RepairPanel({ hdrs, onApplied }) {
  // 반입 수리 보조 (패치 28). 제안은 서버가 계산하고, 반영은 여기서
  // 고른 것만 열쇠와 함께 보낸다 — 자동 전체 반영 버튼은 만들지 않는다.
  const [plan, setPlan] = useState(null)
  const [sel, setSel] = useState(() => new Set())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [result, setResult] = useState(null)

  const load = async () => {
    setBusy(true); setErr(''); setResult(null); setSel(new Set())
    try { setPlan(await get('/ingest/repair-plan')) }
    catch (e) { setErr(String(e.message || e)) }
    setBusy(false)
  }

  const toggle = (id) => setSel(prev => {
    const n = new Set(prev)
    n.has(id) ? n.delete(id) : n.add(id)
    return n
  })

  const applySel = async () => {
    if (!sel.size) return
    setBusy(true); setErr('')
    try {
      const res = await fetch(`${API}/ingest/repair-apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...hdrs() },
        body: JSON.stringify({ ids: [...sel] }),
      })
      const j = await res.json()
      if (!res.ok) throw new Error(j.detail || `HTTP ${res.status}`)
      setResult(j)
      onApplied && onApplied()
      // 반영 후 제안을 새로 계산 — 남은 것이 0이어야 정상이다
      setPlan(await get('/ingest/repair-plan'))
      setSel(new Set())
    } catch (e) { setErr(String(e.message || e)) }
    setBusy(false)
  }

  const props_ = plan?.proposals || []
  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <div className="panel-head" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span>수리안 — 점검이 짚은 것 중 고칠 수 있는 형태</span>
        <button className="btn" onClick={load} disabled={busy}
                style={{ width: 'auto', padding: '4px 12px', fontSize: '0.78rem' }}>
          {plan ? '다시 계산' : '수리안 보기'}
        </button>
      </div>
      <div className="panel-body">
        {err && <div style={{ color: 'var(--bad, #f87171)', fontSize: '0.85rem' }}>{err}</div>}
        {!plan && !busy && !err && (
          <div style={{ color: 'var(--faint)', fontSize: '0.85rem' }}>
            버튼을 누르면 현재 자료를 검사해 수리안을 계산합니다. 읽기만 하며 파일은 바꾸지 않습니다.
          </div>
        )}
        {busy && <div style={{ color: 'var(--faint)' }}>계산 중…</div>}
        {plan && !busy && (
          <>
            <div style={{ fontSize: '0.82rem', color: 'var(--faint)', marginBottom: 8 }}>
              제안 {plan.counts.total}건 — 자동 반영 가능 {plan.counts.auto} · 수동 확인 {plan.counts.manual}.
              자동 항목만 선택할 수 있고, 반영에는 수정 열쇠가 필요합니다.
              반영 전 이전 판이 .prev 로 보존됩니다.
            </div>
            {props_.length === 0 && (
              <div className="panel-note">지적 없음 — 고칠 것이 없습니다.</div>
            )}
            {props_.map(pp => (
              <div key={pp.id} style={{
                display: 'flex', gap: 8, alignItems: 'flex-start',
                padding: '6px 0', borderTop: '1px solid var(--line, #333)' }}>
                <input type="checkbox" disabled={!pp.auto}
                       checked={sel.has(pp.id)} onChange={() => toggle(pp.id)}
                       style={{ marginTop: 3 }} />
                <div style={{ fontSize: '0.84rem' }}>
                  <div>{pp.before}
                    {pp.after && <span style={{ color: 'var(--match, #34d399)' }}> → {pp.after}</span>}
                    {!pp.auto && <span style={{ color: 'var(--warn-ink, #d9a441)' }}> (수동)</span>}
                  </div>
                  <div style={{ color: 'var(--faint)', fontSize: '0.78rem' }}>{pp.rationale}</div>
                </div>
              </div>
            ))}
            {plan.counts.auto > 0 && (
              <button className="btn" onClick={applySel} disabled={busy || !sel.size}
                      style={{ marginTop: 10 }}>
                선택 {sel.size}건 반영 (열쇠 필요)
              </button>
            )}
            {result && (
              <div className="caveat" style={{ marginTop: 8 }}>
                반영 {result.applied.length}건 · 건너뜀 {result.skipped.length}건
                · 채널 중복 {result.before.channel_dup} → {result.after.channel_dup}
                {result.prev && <> · 이전 판 {result.prev}</>}
                <div>{result.note}</div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function FloodPanel() {
  // 동시 알람 조사 (패치 28). SCADA 미연결이라 태그는 사람이 넣는다 —
  // 그 입력 이후의 조사 절차(공통 조상→반례→코드 근거→결론)를 대신한다.
  const [tags, setTags] = useState('')
  const [codes, setCodes] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [r, setR] = useState(null)

  const run = async () => {
    setBusy(true); setErr(''); setR(null)
    try {
      const q = new URLSearchParams({ tags, codes })
      setR(await get(`/investigate-flood?${q}`))
    } catch (e) { setErr(String(e.message || e)) }
    setBusy(false)
  }

  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <div className="panel-head">동시 알람 조사 — 여러 태그가 같이 울 때</div>
      <div className="panel-body">
        <div style={{ fontSize: '0.8rem', color: 'var(--faint)', marginBottom: 6 }}>
          SCADA 알람 목록에서 동시에 뜬 태그를 쉼표로 옮겨 넣으십시오.
          공통 조상 판정 → 안 운 동반 태그(반례) → 진단 코드 근거 → 결론
          순으로 조사하고, 밟은 단계가 전부 아래에 남습니다.
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <input value={tags} onChange={e => setTags(e.target.value)}
                 placeholder="AIT-4002, AIT-3002, FIT-2009"
                 style={{ flex: '2 1 240px' }} />
          <input value={codes} onChange={e => setCodes(e.target.value)}
                 placeholder="진단 코드 (선택) — 11H"
                 style={{ flex: '1 1 140px' }} />
          <button className="btn" onClick={run} disabled={busy || !tags.trim()}
                  style={{ width: 'auto', padding: '4px 14px' }}>
            조사
          </button>
        </div>
        {err && <div style={{ color: 'var(--bad, #f87171)', fontSize: '0.85rem', marginTop: 8 }}>{err}</div>}
        {busy && <div style={{ color: 'var(--faint)', marginTop: 8 }}>조사 중…</div>}
        {r && (
          <div style={{ marginTop: 10 }}>
            {(r.steps || []).map(st => (
              <div key={st.n} className="step-detail">
                {st.n}. {st.what} — {st.result}
              </div>
            ))}
            <div className="caveat" style={{ marginTop: 8 }}>{r.conclusion}</div>
            {(r.code_evidence || []).map((e, i) => (
              <div key={i} className="step-detail" style={{ color: 'var(--match, #34d399)' }}>
                코드 근거: {e.title} — {e.cite}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


function FeedbackForm({ tag, alarm, onSaved }) {
  const [root, setRoot] = useState('')
  const [action, setAction] = useState('')
  const [match, setMatch] = useState('부분일치')
  const [mins, setMins] = useState(30)
  const [parts, setParts] = useState('-')
  const [tech, setTech] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function save() {
    if (!root.trim() || !action.trim()) {
      setMsg('실제 원인과 조치 내용은 필수입니다.')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const res = await post('/feedback', {
        tag,
        symptom: alarm,
        root_cause: root,
        action_taken: action,
        manual_match: match,
        duration_min: Number(mins) || 0,
        parts,
        tech,
      })
      setMsg(`저장됨: ${res.record.wo_no} — 4D 리포트 D3·D4 에도 이 내용이 들어갑니다`)
      // 4D 리포트가 쓸 수 있게 저장한 값을 위로 올린다. 실제 원인이
      // 곧 D3 확정 원인이고 조치 내용이 곧 D4 실시 조치다 — 같은 것을
      // 두 번 입력하게 하지 않는다.
      onSaved?.({
        confirmed_cause: root,
        final_action: action,
        parts,
        duration_min: Number(mins) || 0,
        tech,
      })
      setRoot('')
      setAction('')
    } catch (e) {
      setMsg(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="field">
        <label>실제 원인</label>
        <input value={root} onChange={e => setRoot(e.target.value)} />
      </div>
      <div className="field">
        <label>조치 내용</label>
        <input value={action} onChange={e => setAction(e.target.value)} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
        <div className="field">
          <label>매뉴얼 일치</label>
          <select value={match} onChange={e => setMatch(e.target.value)}>
            <option>일치</option>
            <option>부분일치</option>
            <option>불일치</option>
          </select>
        </div>
        <div className="field">
          <label>소요(분)</label>
          <input type="number" value={mins} onChange={e => setMins(e.target.value)} />
        </div>
        <div className="field">
          <label>부품</label>
          <input value={parts} onChange={e => setParts(e.target.value)} />
        </div>
      </div>
      <div className="field">
        <label>작업자</label>
        <input value={tech} onChange={e => setTech(e.target.value)} />
      </div>
      <button className="btn" style={{ width: 'auto', padding: '9px 18px' }} onClick={save} disabled={busy}>
        {busy ? '저장 중…' : '이력에 저장'}
      </button>
      {msg && <div style={{ marginTop: 8, fontSize: '0.84rem', color: 'var(--muted)' }}>{msg}</div>}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════
   인터락
   ══════════════════════════════════════════════════════════ */
function InterlockView({ tag, action, asInput, botPending, onBotHandled, free }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)
  const [sourceBlock, setSourceBlock] = useState(null)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [sourceLoading, setSourceLoading] = useState(false)
  const [sourceError, setSourceError] = useState(null)
  // 공정 화면(작화 전사본)이 준비된 태그만. 없는 태그는 패널 자체를 띄우지 않는다.
  const GRAPHIC_PAGES = { 'P-5101A': '/interlock_P-5101A.html?embed=1' }
  const [graphicOpen, setGraphicOpen] = useState(false)  // 기본은 접힘
  const graphicRef = React.useRef(null)
  // 챗봇 명령("시나리오 재생해줘")이 공정 화면의 재생 버튼까지 잇는다.
  // 화면(iframe)이 뜬 뒤에 신호를 보내야 하므로 예약해 두었다가
  // iframe onLoad 에서 보낸다.
  const [playWhenReady, setPlayWhenReady] = useState(false)

  useEffect(() => {
    if (!botPending) return
    if (botPending.type === 'interlock' || botPending.type === 'interlock_source') {
      if (botPending.openGraphic) {
        setGraphicOpen(true)
        setPlayWhenReady(!!botPending.playScenario)
      }
      const run = async () => {
        setLoading(true)
        setError(null)
        setData(null)
        setSourceBlock(null)
        setSourceOpen(false)
        setSourceError(null)
        try {
          const body = {
            tag: botPending.tag || tag,
            action: botPending.action || action,
            as_input: !!botPending.asInput,
          }
          const res = await post('/interlock', body)
          setData(res)
          // 원본 블록은 항상 함께 불러온다.
          setSourceLoading(true)
          try {
            const src = await get(`/interlock-source?tag=${encodeURIComponent(body.tag)}`)
            setSourceBlock(src)
            setSourceOpen(true)
          } catch (e) {
            setSourceBlock(null)
            setSourceError(e.message || '원본을 불러오지 못했습니다')
          } finally { setSourceLoading(false) }
        } catch (e) {
          setError(e.message)
        } finally {
          setLoading(false)
          onBotHandled && onBotHandled()
        }
      }
      run()
    } else {
      onBotHandled && onBotHandled()
    }
  }, [botPending])

  async function run() {
    setLoading(true)
    setError(null)
    setData(null)
    setSourceBlock(null)
    setSourceOpen(false)
    setSourceError(null)
    try {
      setData(await post('/interlock', { tag, action: asInput ? null : action, as_input: asInput }))
      // 원본 블록 병렬 로드 — 조회 성공 시 자동으로 펼침
      setSourceLoading(true)
      try {
        const src = await get(`/interlock-source?tag=${encodeURIComponent(tag)}`)
        setSourceBlock(src)
        setSourceOpen(true)
      } catch (e) {
        console.warn('interlock-source 실패:', e.message)
        setSourceBlock(null)
        setSourceError(e.message || '원본을 불러오지 못했습니다')
      } finally {
        setSourceLoading(false)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className="main-header">
        <h1>Plant Maintenance Copilot <span>· 인터락 조회</span><FreeBadge show={free} /></h1>
      </div>

      <button className="btn" style={{ width: 'auto', padding: '10px 20px', marginBottom: 16 }}
        onClick={run} disabled={loading || !tag.trim()}>
        {loading ? '조회 중…' : '인터락 조회'}
      </button>

      {error && <div className="error-box">{error}</div>}
      {loading && <div className="loading">조회 중…</div>}

      {data && !data.found && (
        <div className="panel"><div className="panel-body"><div className="empty">{data.message}</div></div></div>
      )}

      {data?.found && data.as_input && (
        <div className="panel">
          <div className="panel-head">{data.tag} 가 걸린 인터락</div>
          <div className="panel-body">
            <div className="il-output">영향 출력: <strong>{data.affected_outputs?.join(', ') || '—'}</strong></div>
            {data.hits?.map((h, i) => (
              <div className="il-card" key={i}>
                <div className="il-card-head">
                  <span className="il-no">{h.il_no}</span>
                  <span className={`kind-badge ${h.kind}`}>{h.kind}</span>
                  <span style={{ fontSize: '0.86rem' }}>{h.output_tag} → {h.action}</span>
                </div>
                <ul className="cond-list"><li>{h.condition?.raw}</li></ul>
                <div className="il-meta">바이패스 {h.bypassable ? '가능' : '불가'} · 리셋 {h.reset} · {h.dwg_no}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {data?.found && !data.as_input && (
        <>
          {data.output && (
            <div className="tag-header">
              <div className="item"><span className="label">TAG</span><span className="value tag">{data.output.tag}</span></div>
              <div className="item"><span className="label">Service</span><span className="value">{data.output.service || '—'}</span></div>
              <div className="item"><span className="label">Type / Fail</span>
                <span className="value">{[data.output.type, data.output.fail].filter(Boolean).join(' · ') || '—'}</span>
              </div>
            </div>
          )}
          {GRAPHIC_PAGES[data.output?.tag] && (
            <div className="panel">
              <div className="panel-head" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                공정 화면
                <span style={{ fontSize: '0.76rem', opacity: 0.6 }}>오프라인 시뮬레이션</span>
                <button className="btn"
                  style={{ width: 'auto', padding: '4px 12px', marginLeft: 'auto', fontSize: '0.8rem' }}
                  onClick={() => setGraphicOpen(v => !v)}>
                  {graphicOpen ? '접기' : '펼치기'}
                </button>
              </div>
              {graphicOpen && (
                <div className="panel-body" style={{ padding: 0 }}>
                  <iframe src={GRAPHIC_PAGES[data.output.tag]}
                    ref={graphicRef}
                    title={`${data.output.tag} 공정 화면`}
                    onLoad={() => {
                      if (!playWhenReady) return
                      setPlayWhenReady(false)
                      // 같은 서버에서 내려주는 페이지라 postMessage 로 잇는다.
                      graphicRef.current?.contentWindow?.postMessage(
                        'play-scenario', window.location.origin)
                    }}
                    style={{ width: '100%', height: 640, border: 0, display: 'block' }} />
                </div>
              )}
            </div>
          )}
          <div className="panel">
            <div className="panel-body">
              {data.blocking?.length > 0 && (
                <div className="il-section blocking">
                  <div className="il-section-title"><span className="dot" />{data.action}을(를) 막는 조건</div>
                  {data.blocking.map((it, i) => <IlCard key={i} item={it} />)}
                </div>
              )}
              {data.enabling?.length > 0 && (
                <div className="il-section enabling">
                  <div className="il-section-title"><span className="dot" />{data.action} 조건</div>
                  {data.enabling.map((it, i) => <IlCard key={i} item={it} />)}
                </div>
              )}
              {data.other?.length > 0 && (
                <div className="il-section">
                  <div className="il-section-title">그 밖의 항목</div>
                  {data.other.map((it, i) => <IlCard key={i} item={it} />)}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {(sourceBlock || sourceLoading || sourceError) && data?.found && (
        <div className="panel" style={{ marginTop: 14 }}>
          <div
            className="panel-head"
            style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            onClick={() => setSourceOpen(!sourceOpen)}
          >
            <span>
              {sourceOpen ? '▾' : '▸'} 인터락 리스트 원본
              {sourceBlock ? ` · ${sourceBlock.file} (행 ${sourceBlock.row_start}–${sourceBlock.row_end})` : ''}
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--muted)', fontWeight: 500 }}>
              사람이 대조할 수 있는 원본 구간
            </span>
          </div>
          {sourceOpen && (
            <div className="panel-body">
              {sourceLoading && <div className="loading">원본 로드 중…</div>}
              {sourceError && !sourceBlock && (
                <div className="mode-warn">원본을 불러오지 못했습니다 — {sourceError}</div>
              )}
              {sourceBlock && (
                <div className="il-doc">
                  <div className="il-doc-top">
                    <div className="il-doc-title">{sourceBlock.header || sourceBlock.tag}</div>
                    <div className="il-doc-meta">{sourceBlock.file} · 행 {sourceBlock.row_start}–{sourceBlock.row_end}</div>
                  </div>

                  {sourceBlock.action && (
                    <div className="il-doc-action">{sourceBlock.action}</div>
                  )}

                  {sourceBlock.conditions?.length > 0 ? (
                    <div className="src-table-wrap">
                      <table className="il-form-table">
                        <thead>
                          <tr>
                            <th className="col-no">No</th>
                            <th>INTERLOCK SET CONDITION</th>
                            <th>STATUS</th>
                            <th>RESET CONDITION</th>
                            <th>SET DELAY</th>
                            <th>SELECT</th>
                            <th>SIGNAL SOURCE</th>
                            <th>NOTE</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sourceBlock.conditions.map((c, i) => (
                            <tr key={i}>
                              <td className="col-no">{c.no}</td>
                              <td className="col-set">{c.set}</td>
                              <td className="col-status">{c.status}</td>
                              <td>{c.reset}</td>
                              <td className="col-center">{c.delay}</td>
                              <td>{c.select}</td>
                              <td className="col-source">{c.source}</td>
                              <td className="col-note">{c.note}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="src-table-wrap">
                      <table className="src-table">
                        <tbody>
                          {sourceBlock.rows?.map((r, i) => (
                            <tr key={i}>
                              <td className="src-rowno">{r.row}</td>
                              {r.cells?.map((cell, j) => (
                                <td key={j}>{cell}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {sourceBlock.remarks?.length > 0 && (
                    <div className="il-doc-remark">
                      <div className="il-doc-remark-title">REMARK</div>
                      <ul>
                        {sourceBlock.remarks.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div style={{ marginTop: 10, fontSize: '0.72rem', color: 'var(--faint)' }}>
                    엑셀 원본 구간을 열 구조에 맞춰 재구성한 보기입니다. 값은 원문 그대로이며 해석·요약이 아닙니다.
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {!data && !loading && !error && (
        <div className="empty">왼쪽에서 태그를 확인하고 인터락 조회를 눌러 주세요.</div>
      )}
    </>
  )
}


function formatCond(c) {
  if (!c) return ''
  if (!c.parsed) return (c.raw || '') + ' ※ 구조화 실패'
  const parts = []
  if (c.tags?.length) {
    const j = c.multi === 'OR' ? ' 또는 ' : (c.multi === 'AND' ? ' 및 ' : ', ')
    parts.push(c.tags.join(j))
  }
  if (c.kind === 'ANALOG' || (c.op && c.setpoint != null)) {
    parts.push(`${c.op} ${c.setpoint}${c.unit ? ' ' + c.unit : ''}`)
    if (c.level) parts.push(`(${c.level})`)
  }
  if (c.state || c.state_label) {
    const raw = c.raw || ''
    let detail = c.state_label || c.state
    if (!c.state_label) {
      const hints = ['Loop Error', 'EOCR Trip', 'Block Stop', 'All Stop', 'Stand-by Select', 'Trip', 'Fault']
      for (const h of hints) {
        if (raw.toLowerCase().includes(h.toLowerCase())) { detail = h; break }
      }
    }
    parts.push(detail)
  }
  if (c.delay != null && c.delay !== '') parts.push(`[${c.delay}초]`)
  return parts.filter(Boolean).join(' · ') || c.raw || ''
}

function IlCard({ item }) {
  return (
    <div className="il-card">
      <div className="il-card-head">
        <span className="il-no">{item.il_no}</span>
        <span className={`kind-badge ${item.kind}`}>{item.kind}</span>
        <span style={{ fontSize: '0.84rem' }}>→ {item.action}</span>
        <span className="il-logic">
          {item.logic === 'OR' ? 'OR · 하나라도' : 'AND · 전부'} · 리셋 {item.reset} · 바이패스 {item.bypassable ? '가능' : '불가'}
        </span>
      </div>
      <ul className="cond-list">
        {item.conditions?.map((c, i) => (
          <li key={i}>
            {formatCond(c)}
            {c.raw && c.parsed && (
              <div style={{ fontSize: '0.78rem', color: 'var(--faint)', marginTop: 2 }}>
                원문: {c.raw}
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="il-meta">
        {item.plc_block} · 도면 {item.dwg_no} Sh.{item.sheet}
        {item.remark ? ` · ${item.remark}` : ''}
      </div>
    </div>
  )
}


/* ══════════════════════════════════════════════════════════
   도움 챗봇 — 가이드 + 자연어 화면 제어
   ══════════════════════════════════════════════════════════ */
const TAG_RE_BOT = /\b([A-Za-z]{1,8}-[A-Za-z0-9]{1,8})\b/i

function parseBotIntent(text, tags) {
  const raw = (text || '').trim()
  const low = raw.toLowerCase()
  const tagMatch = raw.match(TAG_RE_BOT)
  let tag = tagMatch ? tagMatch[1].toUpperCase() : null
  // 태그 목록에 있으면 정규화
  if (tag && tags?.length) {
    const hit = tags.find(t => t.tag.toUpperCase() === tag)
    if (hit) tag = hit.tag
  }

  // 도움
  if (/^(도움|help|사용법|어떻게|가이드)/i.test(low) || low === '?' ) {
    return { type: 'help', reply: null }
  }

  // 도면
  if (/도면|p\s*&\s*i\s*d|pid|p&id|drawing/i.test(low)) {
    if (!tag) return { type: 'chat', reply: '어느 태그의 도면을 볼까요? 예: AIT-1001 P&ID 도면 보여줘' }
    return {
      type: 'drawing',
      tag,
      tab: 'alarm',
      reply: `${tag} 도면을 열어둘게요.`,
    }
  }

  // 인터락 원본
  if (/인터락.*원본|원본.*인터락|리스트 원본/i.test(low)) {
    if (!tag) return { type: 'chat', reply: '태그를 알려주세요. 예: LCV-01 인터락 원본 보여줘' }
    const act = /open|열/i.test(low) ? 'OPEN' : /close|닫/i.test(low) ? 'CLOSE' : /start|기동/i.test(low) ? 'START' : /stop|정지/i.test(low) ? 'STOP' : 'OPEN'
    return { type: 'interlock_source', tag, tab: 'interlock', action: act, openSource: true, reply: `${tag} 인터락 리스트 원본을 펼칠게요.` }
  }

  // 인터락
  if (/인터락|interlock|퍼미시브|왜\s*안\s*(열|닫|기동|정지)/i.test(low)) {
    if (!tag) return { type: 'chat', reply: '출력 태그를 알려주세요. 예: XV-4101 인터락 조회해줘 / LCV-01 OPEN 조건' }
    let action = 'OPEN'
    if (/close|닫/i.test(low)) action = 'CLOSE'
    else if (/start|기동|운전/i.test(low)) action = 'START'
    else if (/stop|정지/i.test(low)) action = 'STOP'
    else if (/\bopen\b|열/i.test(low)) action = 'OPEN'
    return {
      type: 'interlock',
      tag,
      tab: 'interlock',
      action,
      reply: `${tag} 의 ${action} 인터락 조건을 조회합니다.`,
    }
  }

  // 조치 순서
  if (/조치\s*순서|advice|점검\s*순서/i.test(low)) {
    return {
      type: 'advice',
      tag: tag || undefined,
      tab: 'alarm',
      reply: '조치 순서를 생성합니다.',
    }
  }

  // 알람 조회
  if (/알람|조회|검색|diagnose|고장|트러블/i.test(low) || (tag && /해줘|해주세요|보여/i.test(low))) {
    // 알람 문구: 태그/동사 제거 후 남은 한글·영문
    let alarm = raw
      .replace(TAG_RE_BOT, ' ')
      .replace(/알람|조회|해줘|해주세요|검색|좀|제발|바로|관련/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    if (!alarm || alarm.length < 2) alarm = 'alarm'
    if (!tag) return { type: 'chat', reply: '태그를 포함해 주세요. 예: AIT-4002 acid residual low 알람 조회해줘' }
    return {
      type: 'diagnose',
      tag,
      tab: 'alarm',
      alarm,
      reply: `${tag} 알람 조회를 실행합니다.` + (alarm !== 'alarm' ? ` (증상: ${alarm})` : ''),
    }
  }

  // 태그 전환만
  if (tag && /선택|바꿔|이동|가자/i.test(low)) {
    return { type: 'navigate', tag, reply: `${tag} 태그로 전환했습니다.` }
  }

  return {
    type: 'chat',
    reply: '이렇게 말해 보세요:\n· AIT-4002 acid residual low 알람 조회해줘\n· AIT-1001 P&ID 도면 보여줘\n· XV-4101 인터락 조회해줘\n· LCV-01 인터락 원본 보여줘\n· 사용법 알려줘',
  }
}

function helpReply() {
  return (
    'Plant Maintenance Copilot 사용 가이드입니다.\n\n' +
    '① 알람 조회 — 왼쪽에서 계기 태그 선택 후 증상 입력 → 알람 조회\n' +
    '② 근거 확인 — 매뉴얼·코드표 / 현장 이력 두 칸\n' +
    '③ 원문·도면 — 원문 보기, 도면 보기 (휠 확대)\n' +
    '④ 4D 리포트 — PDF 다운로드\n' +
    '⑤ 인터락 조회 — 탭 전환 후 XV/LCV 등 출력 태그\n' +
    '⑥ 자료 반입 — 파일 올리기 → 반입 점검 리포트 확인\n' +
    '⑦ 자유 모드 — 사이드바 토글, 근거 없는 답변은 라벨 표시\n\n' +
    '저에게 자연어로 시킬 수도 있습니다.\n' +
    '예: 「AIT-4002 low acid 알람 조회해줘」'
  )
}

function HelpBot({ tags, currentTag, currentTab, onCommand, screen, free }) {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState([
    {
      role: 'bot',
      text: '현장 유지보수 코파일럿 도우미입니다. 사용법이 궁금하면 물어보거나, 자연어로 바로 실행해 보세요.',
    },
  ])
  const [engine, setEngine] = useState('rule')
  // 응답을 기다리는 동안의 상태. 0 이면 대기, 아니면 요청 시작 시각.
  // 규칙 응답은 1초 안에 오고 모델 응답은 수십 초가 걸리는데, 그동안
  // 화면이 조용하면 죽은 것과 구분이 안 된다.
  const [thinking, setThinking] = useState(0)
  const [nowTick, setNowTick] = useState(0)
  useEffect(() => {
    if (!thinking) return
    const t = setInterval(() => setNowTick(Date.now()), 500)
    return () => clearInterval(t)
  }, [thinking])
  const thinkSec = thinking ? Math.floor(((nowTick || Date.now()) - thinking) / 1000) : 0
  const listRef = React.useRef(null)

  useEffect(() => {
    get('/chat/status').then(s => {
      setEngine(s.llm_ready ? `llm:${s.provider}` : 'rule')
    }).catch(() => setEngine('rule'))
  }, [])

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [msgs, open])

  function push(role, text, citations) {
    setMsgs(m => [...m, { role, text, citations }])
  }

  async function runText(text) {
    if (!text.trim()) return
    push('user', text)
    setInput('')
    setThinking(Date.now())
    let intent = null
    try {
      intent = await post('/chat', {
        message: text,
        tag: currentTag || '',
        tab: currentTab || 'alarm',
        use_llm: true,
        free: !!free,
        // 화면에 떠 있는 결과. 후속 질문은 이것을 근거로 답한다.
        context: screen || null,
      })
    } catch (e) {
      // 백엔드에 못 닿으면 화면 안의 간이 파서로 내려간다. 조용히
      // 내려가면 왜 답이 달라졌는지 알 수 없으므로 표시한다.
      intent = parseBotIntent(text, tags)
      if (intent.type === 'help') intent.reply = helpReply()
      intent.reply = (intent.reply || '') + '\n(오프라인 해석 — 서버에 연결하지 못했습니다)'
    } finally {
      setThinking(0)
    }
    if (!intent) return
    if (intent.type === 'help' && !intent.reply) intent.reply = helpReply()
    if (intent.reply) {
      // 자유 모드의 근거 없는 답변에는 라벨을 붙인다. 근거 기반
      // 답변(조회·후속·QA)과 같은 말풍선 모양으로 나오면 구분이 안 된다.
      // 근거 답변 실패 뒤에 자유 답변을 덧붙인 경우에는 라벨이 본문에
      // 이미 들어 있다. 두 번 붙이지 않는다.
      const has = (intent.reply || '').includes('〔모델 답변')
      const label = intent.free && intent.grounded === false && !has
        ? '〔모델 답변 · 문서 근거 아님〕\n' : ''
      push('bot', label + intent.reply, intent.citations)
    }
    if (intent.type && intent.type !== 'chat' && intent.type !== 'help') {
      onCommand && onCommand(intent)
    }
  }

  const chips = [
    { label: '사용법', q: '사용법 알려줘' },
    { label: '알람 조회', q: 'AIT-4002 acid residual low 알람 조회해줘' },
    { label: '도면', q: 'AIT-4002 도면 보여줘' },
    { label: '인터락', q: 'XV-4101 인터락 조회해줘' },
    { label: '실물 인터락', q: 'LCV-01 OPEN 인터락 조회해줘' },
    { label: '원본 리스트', q: 'LCV-01 인터락 원본 보여줘' },
  ]

  // 창 높이 조절. 근거 인용이 붙은 답변은 길어서 기본 높이로는 한
  // 답변을 보려고 계속 스크롤해야 한다. 그렇다고 늘 크면 화면을 가린다.
  // 사용자가 그때그때 잡아 늘리게 하되 한도를 둔다.
  const H_MIN = 320
  const hMax = () => Math.max(H_MIN, Math.min(900, window.innerHeight - 72))
  const [panelH, setPanelH] = useState(() =>
    Math.min(560, Math.max(H_MIN, window.innerHeight - 72)))

  function startResize(e) {
    e.preventDefault()
    const y0 = e.clientY
    const h0 = panelH
    const max = hMax()
    const move = ev => {
      // 위로 끌면 커진다. 창이 아래에 붙어 있으므로 방향을 뒤집는다.
      const next = h0 + (y0 - ev.clientY)
      setPanelH(Math.max(H_MIN, Math.min(max, next)))
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  return (
    <div className={`helpbot ${open ? 'open' : ''}`}>
      {open && (
        <div
          className="helpbot-panel"
          style={{ height: Math.min(panelH, hMax()) }}
        >
          <div
            onPointerDown={startResize}
            onDoubleClick={() => setPanelH(Math.min(560, hMax()))}
            title="끌어서 높이 조절 · 두 번 누르면 기본 크기"
            style={{
              height: 14, flex: '0 0 14px', cursor: 'ns-resize',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              touchAction: 'none',
            }}
          >
            <div style={{
              width: 38, height: 4, borderRadius: 999,
              background: 'rgba(148,163,184,0.45)',
            }} />
          </div>
          <div className="helpbot-head">
            <div className="helpbot-brand">
              <div
                className={`helpbot-avatar ${thinking ? 'pulsing' : ''} ${free ? 'free' : ''}`}
                aria-hidden
              >
                <BotIcon size={36} />
              </div>
              <div>
                <div className="helpbot-title">Copilot Assistant</div>
                <div className="helpbot-sub">
                  가이드 · 자연어 실행 · {engine}
                  {free && (
                    <span style={{ color: '#d9a441', fontWeight: 600 }}>
                      {' '}· 자유 모드
                    </span>
                  )}
                </div>
              </div>
            </div>
            <button type="button" className="helpbot-x" onClick={() => setOpen(false)} aria-label="닫기">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 6l12 12M18 6L6 18"/>
              </svg>
            </button>
          </div>

          <div className="helpbot-msgs" ref={listRef}>
            {msgs.map((m, i) => (
              <div key={i} className={`helpbot-row ${m.role}`}>
                {m.role === 'bot' && (
                  <div className="helpbot-mini-av" aria-hidden>
                    <BotIcon size={22} />
                  </div>
                )}
                <div className={`helpbot-msg ${m.role}`}>
                  {m.text}
                  {m.citations?.length > 0 && (
                    <div className="helpbot-cites">
                      {m.citations.map((c, k) => (
                        <div key={k} className="helpbot-cite">
                          <b>[{k + 1}]</b> {c.title} · {c.cite}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {thinking > 0 && (
              <div className="helpbot-row bot">
                <div className="helpbot-mini-av" aria-hidden>
                  <BotIcon size={22} />
                </div>
                <div className="helpbot-msg bot helpbot-thinking">
                  <span className="hb-wave" aria-hidden>
                    <i /><i /><i /><i /><i />
                  </span>
                  <span className="hb-stage">
                    {thinkSec < 2
                      ? '요청 처리 중'
                      : `모델 답변 생성 중 · ${thinkSec}초`}
                  </span>
                </div>
              </div>
            )}
          </div>

          <div className="helpbot-chips">
            {chips.map((c, i) => (
              <button type="button" key={i} onClick={() => runText(c.q)}>{c.label}</button>
            ))}
          </div>

          <form
            className="helpbot-input"
            onSubmit={(e) => { e.preventDefault(); runText(input) }}
          >
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="메시지를 입력하세요…"
            />
            <button type="submit" className="helpbot-send" aria-label="전송">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3.2 12.1L20.5 3.4c.6-.3 1.2.3.9.9L13.6 20c-.2.5-.9.5-1.1 0l-2.4-6.3-6.3-2.4c-.5-.2-.5-.9 0-1.1z"/>
              </svg>
            </button>
          </form>

          <div className="helpbot-foot">
            <span>{currentTab === 'alarm' ? '알람' : '인터락'}</span>
            <span className="dot">·</span>
            <span>{currentTag || '—'}</span>
          </div>
        </div>
      )}

      <button
        type="button"
        className={`helpbot-fab ${open ? 'is-open' : ''}`}
        onClick={() => setOpen(o => !o)}
        title="Copilot Assistant"
        aria-label="도우미 열기"
      >
        {open ? (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M6 6l12 12M18 6L6 18"/>
          </svg>
        ) : (
          <BotIcon size={64} />
        )}
      </button>
    </div>
  )
}

/* 현장 이력 카드 — 조치 순서 맨 앞에 꽂힌다.
   매뉴얼 근거와 달리 "우리가 겪은 일"이므로 시각적으로 구분한다.
   특히 매뉴얼과 원인이 다른 건(불일치)은 이 도구의 존재 이유라
   가장 눈에 띄어야 한다. */
const HIST_TONE = {
  경고: { bd: 'var(--warn, #b45309)', bg: 'rgba(180,83,9,0.08)' },
  참고: { bd: 'var(--ink-3, #64748b)', bg: 'rgba(100,116,139,0.06)' },
  확인: { bd: 'var(--ink-3, #64748b)', bg: 'transparent' },
}

/* ── 자료 반입 ──────────────────────────────────────────────
 *
 * 본체는 파일 받기가 아니라 반입 직후 점검이다. 결함 여섯 종이 전부
 * 자료를 넣는 시점에 생겼고, 답이 안 나오는 형태가 아니라 그럴듯한
 * 답이 나오되 틀린 형태였다. 그래서 넣자마자 리포트를 사람 앞에 놓는다.
 * 판정하지 않는다 — 어느 쪽이 맞는지는 데이터 주인이 안다. */
const INGEST_KINDS = [
  { k: 'io',         label: 'IO List (.xlsx)',        hint: 'IO_LIST.xlsx 자리에 놓입니다' },
  { k: 'instrument', label: '계기 리스트 (.xlsx)',     hint: 'INSTRUMENT_LIST.xlsx 자리에 놓입니다' },
  { k: 'tb',         label: 'TB List (.xlsx)',        hint: 'TB_LIST.xlsx 자리에 놓입니다' },
  { k: 'interlock',  label: '인터락 리스트 (.xlsx)',   hint: 'interlock/ 폴더에 원래 이름으로' },
  { k: 'manual',     label: '벤더 매뉴얼 (.pdf)',      hint: 'manuals/ 폴더에 원래 이름으로 · 색인 재생성 필요' },
  { k: 'drawing',    label: '도면 (.pdf)',            hint: 'drawings/ 폴더에 원래 이름으로' },
]

const FOLDER_LABEL = {
  root: '리스트 (루트)', interlock: 'interlock/',
  manuals: 'manuals/', drawings: 'drawings/',
}

function fmtBytes(n) {
  if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB'
  if (n >= 1024) return Math.round(n / 1024) + ' KB'
  return n + ' B'
}

function FolderFiles({ files, onOp, busy }) {
  return (
    <>
      {Object.entries(FOLDER_LABEL).map(([key, label]) => {
        const d = files[key]
        if (!d) return null
        return (
          <div key={key} style={{ marginBottom: 12 }}>
            <div className="step-title">{label}</div>
            {d.files.length === 0 && (
              <div className="step-detail" style={{ color: 'var(--faint)' }}>· 비어 있음</div>
            )}
            {d.files.map(f => (
              <div key={f.name} className="step-detail"
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                  opacity: f.state === 'active' ? 1 : 0.55,
                }}>
                <span style={{ flex: '1 1 auto', minWidth: 200 }}>
                  · {f.name}
                  {f.state === 'deleted' && ' (삭제됨)'}
                  {f.state === 'prev' && ' (덮어쓰기 전 보존본)'}
                </span>
                <span style={{ color: 'var(--faint)', fontSize: '0.76rem' }}>
                  {fmtBytes(f.bytes)} · {f.mtime}
                </span>
                <a className="btn" style={{ width: 'auto', padding: '2px 10px', fontSize: '0.76rem', textDecoration: 'none' }}
                  href={`${API}/ingest/download?folder=${key}&name=${encodeURIComponent(f.name)}`}>
                  받기
                </a>
                {f.state === 'active' && (
                  <button className="btn" disabled={busy}
                    style={{ width: 'auto', padding: '2px 10px', fontSize: '0.76rem' }}
                    onClick={() => onOp(key, f.name, 'delete')}>삭제</button>
                )}
                {f.state !== 'active' && (
                  <>
                    <button className="btn" disabled={busy}
                      style={{ width: 'auto', padding: '2px 10px', fontSize: '0.76rem' }}
                      onClick={() => onOp(key, f.name, 'restore')}>되살리기</button>
                    <button className="btn" disabled={busy}
                      style={{ width: 'auto', padding: '2px 10px', fontSize: '0.76rem',
                               borderColor: 'var(--bad, #f87171)', color: 'var(--bad, #f87171)' }}
                      onClick={() => onOp(key, f.name, 'purge')}>영구 삭제</button>
                  </>
                )}
              </div>
            ))}
          </div>
        )
      })}
      <div style={{ fontSize: '0.76rem', color: 'var(--faint)', lineHeight: 1.5 }}>
        삭제는 두 단계입니다 — 삭제하면 .deleted 로 남아 앱이 읽지 않고,
        영구 삭제는 그 상태에서만 됩니다. 실수 한 번으로 되돌릴 수 없게 되는
        조작을 만들지 않습니다.
      </div>
    </>
  )
}

function IngestView({ free }) {
  const [report, setReport] = useState(null)
  const [err, setErr] = useState('')
  const [kind, setKind] = useState('manual')
  const [busy, setBusy] = useState(false)
  const [uploaded, setUploaded] = useState([])
  const [st, setSt] = useState(null)       // 색인 재생성 상태
  const fileRef = React.useRef(null)
  const pollRef = React.useRef(null)

  const [files, setFiles] = useState(null)
  // 편집 열쇠·세션. 열쇠는 저장하지 않는다 — 화면을 닫으면 사라진다.
  const [editKey, setEditKey] = useState('')
  const [edit, setEdit] = useState(null)
  const sessRef = React.useRef(
    'w' + Math.random().toString(36).slice(2, 10))
  const hdrs = () => ({
    'X-Ingest-Key': editKey, 'X-Ingest-Session': sessRef.current })

  const loadEdit = async (k) => {
    try {
      const res = await fetch(`${API}/ingest/edit-state`, {
        headers: { 'X-Ingest-Key': k ?? editKey,
                   'X-Ingest-Session': sessRef.current } })
      setEdit(await res.json())
    } catch { /* 다음에 */ }
  }
  useEffect(() => {
    loadEdit()
    const t = setInterval(loadEdit, 15000)
    return () => clearInterval(t)
  }, [editKey])

  const loadReport = async () => {
    setErr('')
    try { setReport(await get('/ingest/report')) }
    catch (e) { setErr(String(e.message || e)) }
    try { setFiles(await get('/ingest/files')) } catch { /* 목록만 실패 */ }
  }
  useEffect(() => { loadReport() }, [])

  const fileOp = async (folder, name, op) => {
    // 삭제·영구 삭제는 확인을 거친다. 특히 매뉴얼 삭제는 색인과
    // 어긋나므로 그 사실을 먼저 말한다.
    if (op === 'delete') {
      const extra = folder === 'manuals'
        ? '\n\n매뉴얼은 색인을 다시 만들어야 검색에서도 빠집니다.' : ''
      if (!window.confirm(`${name} 을(를) 삭제합니다.\n앱에서 더 이상 읽지 않으며, 파일은 .deleted 로 남아 되살릴 수 있습니다.${extra}`)) return
    }
    if (op === 'purge') {
      if (!window.confirm(`${name} 을(를) 영구 삭제합니다.\n되돌릴 수 없습니다.`)) return
    }
    setErr('')
    try {
      const res = await fetch(
        `${API}/ingest/file-op?folder=${folder}&name=${encodeURIComponent(name)}&op=${op}`,
        { method: 'POST', headers: { ...hdrs(), 'Content-Type': 'application/json' }, body: '{}' })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
      await loadReport()
    } catch (e) { setErr(String(e.message || e)) }
  }

  // 재생성 상태 폴링. 돌고 있을 때만 1초 간격으로 본다.
  const poll = async () => {
    try {
      const d = await get('/ingest/status')
      setSt(d)
      if (!d.running && pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
        loadReport()
      }
    } catch { /* 다음 턴에 다시 */ }
  }
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const upload = async () => {
    const files = fileRef.current?.files
    if (!files || files.length === 0) { setErr('파일을 먼저 고르십시오'); return }
    // 종류와 확장자가 어긋난 채 보내면 서버가 400 으로 거부하는데,
    // 그 사실을 사용자가 놓치기 쉽다. 보내기 전에 여기서 말한다.
    const wantPdf = kind === 'manual' || kind === 'drawing'
    for (const f of files) {
      const isPdf = f.name.toLowerCase().endsWith('.pdf')
      if (wantPdf !== isPdf) {
        setErr(`선택한 종류(${kindInfo?.label})와 파일(${f.name})의 형식이 다릅니다 — 위의 종류 선택을 확인하십시오`)
        return
      }
    }
    setBusy(true); setErr('')
    const done = []
    try {
      for (const f of files) {
        const res = await fetch(
          `${API}/ingest/upload?kind=${kind}&name=${encodeURIComponent(f.name)}`,
          { method: 'POST', body: f, headers: hdrs() })
        const d = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(d.detail || res.statusText)
        done.push(`${d.saved}${d.replaced ? ' (기존 파일은 .prev 로 보존)' : ''}`)
      }
      setUploaded(done)
      fileRef.current.value = ''
      await loadReport()
    } catch (e) { setErr(String(e.message || e)) }
    setBusy(false)
  }

  const rebuild = async () => {
    setErr('')
    try {
      {
        const res = await fetch(`${API}/ingest/rebuild`, {
          method: 'POST',
          headers: { ...hdrs(), 'Content-Type': 'application/json' }, body: '{}' })
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
      }
      setSt({ running: true, stage: '시작', done: 0, total: 0 })
      pollRef.current = setInterval(poll, 1000)
    } catch (e) { setErr(String(e.message || e)) }
  }

  const kindInfo = INGEST_KINDS.find(x => x.k === kind)
  const pct = st && st.total > 0 ? Math.round(100 * st.done / st.total) : 0

  return (
    <>
      <div className="main-header">
        <h1>Plant Maintenance Copilot <span>· 자료 반입</span><FreeBadge show={free} /></h1>
      </div>

      {/* 넣기 */}
      <div className="panel">
        <div className="panel-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
          <span>자료 넣기</span>
          {edit && edit.protected && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 400 }}>
              <span style={{ fontSize: '0.76rem', color: edit.key_ok ? 'var(--match, #34d399)' : 'var(--faint)' }}>
                {edit.key_ok
                  ? (edit.locked_by_other
                      ? `다른 편집자 작업 중 · ${edit.remain}초 후 해제`
                      : '편집 가능')
                  : '보기 전용 — 수정하려면 열쇠 입력'}
              </span>
              <input type="password" value={editKey} placeholder="수정 열쇠"
                onChange={e => setEditKey(e.target.value)}
                style={{
                  width: 110, height: 26, padding: '0 8px',
                  background: 'var(--bg)', color: 'var(--fg)',
                  border: '1px solid var(--line-strong, #3b4a5e)',
                  borderRadius: 6, fontSize: '0.78rem',
                }} />
              {edit.key_ok && edit.editing && !edit.locked_by_other && (
                <button className="btn"
                  style={{ width: 'auto', padding: '2px 10px', fontSize: '0.74rem' }}
                  onClick={async () => {
                    await fetch(`${API}/ingest/edit-release`, { method: 'POST', headers: hdrs() })
                    loadEdit()
                  }}>편집 마침</button>
              )}
            </span>
          )}
        </div>
        <div className="panel-body">
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <select value={kind} onChange={e => setKind(e.target.value)}
              style={{
                height: 34, padding: '0 10px',
                background: 'var(--bg)', color: 'var(--fg)',
                border: '1px solid var(--line-strong, #3b4a5e)',
                borderRadius: 6, fontSize: '0.85rem', cursor: 'pointer',
              }}>
              {INGEST_KINDS.map(x => (
                <option key={x.k} value={x.k}>{x.label}</option>
              ))}
            </select>
            <input type="file" ref={fileRef}
              multiple={kind === 'manual' || kind === 'drawing' || kind === 'interlock'}
              accept={kind === 'manual' || kind === 'drawing' ? '.pdf' : '.xlsx'}
              style={{ fontSize: '0.85rem' }} />
            <button className="btn" onClick={upload} disabled={busy || (st && st.running)}>
              {busy ? '올리는 중…' : '올리기'}
            </button>
          </div>
          {err && (
            <div style={{ color: 'var(--bad, #f87171)', fontSize: '0.84rem', marginTop: 8 }}>
              {err}
            </div>
          )}
          <div style={{ fontSize: '0.78rem', color: 'var(--faint)', marginTop: 8 }}>
            {kindInfo?.hint}. 같은 자리에 파일이 있으면 덮어쓰기 전에 .prev 로 한 벌 남깁니다.
          </div>
          {uploaded.length > 0 && (
            <div style={{ fontSize: '0.82rem', marginTop: 8 }}>
              반입됨: {uploaded.join(' · ')}
            </div>
          )}
        </div>
      </div>

      {/* 들어 있는 자료 */}
      <div className="panel" style={{ marginTop: 14 }}>
        <div className="panel-head">들어 있는 자료</div>
        <div className="panel-body">
          {!files && <div style={{ color: 'var(--faint)' }}>읽는 중…</div>}
          {files && <FolderFiles files={files} onOp={fileOp} busy={st && st.running} />}
        </div>
      </div>

      {/* 색인 재생성 */}
      <div className="panel" style={{ marginTop: 14 }}>
        <div className="panel-head">색인 재생성</div>
        <div className="panel-body">
          <div style={{ fontSize: '0.82rem', color: 'var(--faint)', marginBottom: 10, lineHeight: 1.5 }}>
            매뉴얼을 넣거나 바꿨을 때만 필요합니다. 리스트류(IO·계기·TB·인터락)는
            올리는 즉시 조회에 반영됩니다. 재생성은 몇 분이 걸리며, 도는 동안
            검색 결과가 잠시 예전 색인으로 나올 수 있습니다.
            도는 동안에는 조치 생성·도우미 사용을 피하십시오 — 로컬 실행에서는
            같은 GPU 를 써서 임베딩이 중단될 수 있습니다.
          </div>
          <button className="btn" onClick={rebuild} disabled={st && st.running}>
            {st && st.running ? '재생성 중…' : '색인 다시 만들기'}
          </button>
          {st && (st.running || st.stage) && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: '0.82rem', marginBottom: 6 }}>
                단계: {st.stage}
                {st.total > 0 && ` — 임베딩 ${st.done}/${st.total} (${pct}%)`}
                {st.finished_at && ` · ${st.finished_at} 완료`}
              </div>
              {st.total > 0 && (
                <div style={{ height: 8, borderRadius: 999, background: 'rgba(148,163,184,0.18)' }}>
                  <div style={{
                    height: 8, borderRadius: 999, width: `${pct}%`,
                    background: 'var(--accent, #22d3ee)', transition: 'width .4s',
                  }} />
                </div>
              )}
              {st.error && (
                <div style={{ fontSize: '0.82rem', color: 'var(--bad, #f87171)', marginTop: 6 }}>
                  실패 — {st.error}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 점검 리포트 */}
      <div className="panel" style={{ marginTop: 14 }}>
        <div className="panel-head" style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>반입 점검</span>
          <button className="btn" onClick={loadReport} style={{ width: 'auto', padding: '4px 12px', fontSize: '0.78rem' }}>
            다시 점검
          </button>
        </div>
        <div className="panel-body">
          {err && <div style={{ color: 'var(--bad, #f87171)', fontSize: '0.85rem' }}>{err}</div>}
          {!report && !err && <div style={{ color: 'var(--faint)' }}>점검 중…</div>}
          {report && <IngestReport r={report} />}
        </div>
      </div>

      {/* 수리안 — 패치 28 */}
      <RepairPanel hdrs={hdrs} onApplied={loadReport} />
    </>
  )
}

function RowStat({ name, d }) {
  // 파일 하나의 읽기 결과 한 줄. 판정 대신 사실만 — 몇 행, 못 읽은 열.
  if (!d) return null
  if (d.present === false) {
    return <div className="step-detail" style={{ color: 'var(--faint)' }}>· {name} — 없음</div>
  }
  if (d.error) {
    return <div className="step-detail" style={{ color: 'var(--warn-ink, #d9a441)' }}>
      · {name} — 읽기 실패: {d.error}</div>
  }
  const std = d.standard
  return (
    <div className="step-detail">
      · {d.file || name} — {d.rows}행
      {d.free_form && ` (${d.note})`}
      {d.header_row && !d.free_form && `, ${d.header_row}행이 헤더`}
      {std && (
        <span style={{ color: std.matched === std.expected && std.order_ok ? 'var(--match, #34d399)' : 'var(--warn-ink, #d9a441)' }}>
          {' '}· 표준 열 {std.matched}/{std.expected}
          {std.missing.length > 0 && ` · 빠짐: ${std.missing.join(', ')}`}
          {std.unrecognized.length > 0 && ` · 인식 못함: ${std.unrecognized.join(', ')}`}
          {!std.order_ok && std.matched === std.expected && ' · 열 순서가 표준과 다름'}
        </span>
      )}
    </div>
  )
}

function IngestReport({ r }) {
  const cr = r.cross || {}
  const mans = r.manuals || {}
  const il = r.interlock || {}
  return (
    <>
      <div className="step-title">문서별 읽기</div>
      <RowStat name="IO List" d={r.io_list} />
      <RowStat name="계기 리스트" d={r.instrument_list} />
      <RowStat name="TB List" d={r.tb_list} />
      {il.present === false
        ? <div className="step-detail" style={{ color: 'var(--faint)' }}>· 인터락 — 없음</div>
        : il.error
          ? <div className="step-detail" style={{ color: 'var(--warn-ink, #d9a441)' }}>· 인터락 — 읽기 실패: {il.error}</div>
          : <div className="step-detail">· {(il.files || []).join(', ')} — 규칙 {il.rules}건
              {il.unparsed > 0 && (
                <span style={{ color: 'var(--warn-ink, #d9a441)' }}>
                  {' '}· 미파싱 {il.unparsed}건 (원문 보존 — 임의 해석하지 않습니다)
                </span>
              )}
              {typeof il.input_tags === 'number' && ` · 입력 조건 태그 ${il.input_tags}건`}
            </div>}

      <div className="step-title" style={{ marginTop: 14 }}>매뉴얼 ↔ 기종 연결</div>
      {(mans.models || []).map((m, i) => (
        <div className="step-detail" key={i}>
          · {m.model} (계기 {m.tags}대) — {m.manual
            ? m.manual
            : <span style={{ color: 'var(--warn-ink, #d9a441)' }}>
                연결된 매뉴얼 없음 — 이 기종의 알람 조회는 근거 부족(ABSTAIN)이 됩니다
              </span>}
        </div>
      ))}
      {(mans.card_files || []).map((c, i) => (
        <div className="step-detail" key={`c${i}`}
          style={c.points > 0 ? {} : { color: 'var(--warn-ink, #d9a441)' }}>
          · {c.file} — IO 카드 문서({c.io_type}) — {c.points > 0
            ? `${c.io_type} 포인트 ${c.points}점에 해당 · 색인에 포함되어 검색에 쓰입니다`
            : `이 자료에는 ${c.io_type} 포인트가 없습니다 — 잘못 올렸을 수 있습니다`}
        </div>
      ))}
      {(mans.orphan_files || []).map((n, i) => (
        <div className="step-detail" key={`o${i}`} style={{ color: 'var(--warn-ink, #d9a441)' }}>
          · {n} — 계기 리스트의 어느 기종과도 이어지지 않습니다.
          IO 카드·공용 문서라면 정상이고, 계기 매뉴얼이라면 잘못
          올렸거나 계기 리스트에 그 기종이 없는 경우입니다.
        </div>
      ))}

      <div className="step-title" style={{ marginTop: 14 }}>문서 사이 태그 맞물림</div>
      {cr.error
        ? <div className="step-detail" style={{ color: 'var(--warn-ink, #d9a441)' }}>대조 실패: {cr.error}</div>
        : <>
            <div className="step-detail">
              · IO {cr.counts?.io}점 · 계기 {cr.counts?.spec}대 · 인터락 입력 {cr.counts?.interlock_input} / 출력 {cr.counts?.interlock_output}
            </div>
            {Object.entries(cr.finding_counts || {}).map(([k, n]) => (
              <div className="step-detail" key={k} style={{ color: 'var(--warn-ink, #d9a441)' }}>
                · {k} {n}건
                {(cr.findings?.[k] || []).slice(0, 5).map(f =>
                  ` — ${f.tag}(${f.missing_from} 에 없음)`).join('')}
              </div>
            ))}
            {(!cr.total || cr.total === 0) && (
              <div className="step-detail">· 지적 없음</div>
            )}
            {cr.note && (
              <div style={{ fontSize: '0.76rem', color: 'var(--faint)', marginTop: 8, lineHeight: 1.5 }}>
                {cr.note}
              </div>
            )}
          </>}
    </>
  )
}


function FreeBadge({ show }) {
  // 자유 모드 표시는 화면마다 제목 옆에 붙인다. 모드는 챗봇을 포함해
  // 전 화면에 걸리므로, 알람 화면에만 두면 다른 탭에서 켜져 있는 줄
  // 모른 채 쓰게 된다.
  if (!show) return null
  return (
    <span
      title="근거 없는 모델 추측이 함께 표시됩니다. 조치 순서와 4D 리포트에는 들어가지 않습니다."
      style={{
        marginLeft: 10, padding: '2px 9px', borderRadius: 999,
        border: '1px solid #d9a441', color: '#d9a441',
        background: 'rgba(217,164,65,0.10)',
        fontSize: '0.72rem', fontWeight: 600, whiteSpace: 'nowrap',
        verticalAlign: 'middle',
      }}
    >
      자유 모드 · 근거 없는 내용 포함
    </span>
  )
}


/* 도우미 아이콘.
 *
 * 이미지 파일 대신 도형으로 그린다. 파일이면 배경 여백이 함께 따라와
 * 어두운 화면에서 흰 테두리가 생기고, 크기마다 다시 만들어야 한다.
 * 색은 화면의 도우미 계열(청록)에 맞춘다 - 파랑은 조회 버튼 색이라
 * 기능과 도우미가 섞여 보인다. */
function BotIcon({ size = 36 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden>
      <defs>
        <linearGradient id="botg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#22d3ee" />
          <stop offset="100%" stopColor="#0e7490" />
        </linearGradient>
      </defs>
      <circle cx="24" cy="24" r="24" fill="url(#botg)" />
      <text
        x="24" y="24" textAnchor="middle" dominantBaseline="central"
        fill="#ffffff" fontSize="19" fontWeight="700"
        fontFamily="Inter, 'Segoe UI', system-ui, sans-serif"
        letterSpacing="0.5"
      >AI</text>
    </svg>
  )
}


function GuessPanel({ guess }) {
  // 기본은 접힌 상태다. 펼치는 동작 자체가 "근거 없는 내용임을 알고
  // 본다" 는 확인이 된다. 펼쳐 놓고 시작하면 근거 있는 답과 나란히
  // 읽히고, 그 순간 이 도구가 지키려는 구분이 사라진다.
  const [open, setOpen] = useState(false)
  const has = (guess.causes?.length || 0) + (guess.checks?.length || 0) > 0
  if (!has) return null

  return (
    <div className="panel" style={{ marginTop: 14, borderColor: 'var(--warn, #7a5c00)' }}>
      <div
        className="panel-head"
        style={{ cursor: 'pointer', color: 'var(--warn-ink, #d9a441)' }}
        onClick={() => setOpen(!open)}
      >
        {open ? '▾' : '▸'} {guess.label || '매뉴얼 근거 없음 · 모델 추측'}
        <span style={{ marginLeft: 8, fontSize: '0.78rem', color: 'var(--faint)' }}>
          {open ? '' : '눌러서 펼치기'}
        </span>
      </div>
      {open && (
        <div className="panel-body">
          <div style={{
            fontSize: '0.82rem', color: 'var(--warn-ink, #d9a441)',
            marginBottom: 12, lineHeight: 1.5,
          }}>
            {guess.warning}
          </div>

          {guess.causes?.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div className="step-title">짚어 볼 만한 것</div>
              {guess.causes.map((c, i) => (
                <div className="step-detail" key={'c' + i}>· {c}</div>
              ))}
            </div>
          )}

          {guess.checks?.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div className="step-title">현장에서 확인할 것</div>
              {guess.checks.map((c, i) => (
                <div className="step-detail" key={'k' + i}>· {c}</div>
              ))}
            </div>
          )}

          {guess.ask_vendor && (
            <div>
              <div className="step-title">벤더 문의 시</div>
              <div className="step-detail">{guess.ask_vendor}</div>
            </div>
          )}

          <div className="ev-cite" style={{ marginTop: 12 }}>
            근거 없음 · 모델 생성 — 4D 리포트에는 포함되지 않습니다
          </div>
        </div>
      )}
    </div>
  )
}


function HistoryCard({ card }) {
  const [open, setOpen] = useState(true)
  const tone = HIST_TONE[card.grade] || HIST_TONE.확인
  return (
    <div style={{
      border: `1px solid ${tone.bd}`, background: tone.bg,
      borderRadius: 6, padding: '10px 12px', marginBottom: 12,
    }}>
      <div
        style={{ cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'baseline' }}
        onClick={() => setOpen(!open)}
      >
        <span style={{
          fontSize: '0.72rem', fontWeight: 700, color: tone.bd,
          border: `1px solid ${tone.bd}`, borderRadius: 3, padding: '1px 5px',
        }}>{card.grade}</span>
        <span style={{ fontWeight: 600, flex: 1 }}>{card.title}</span>
        <span style={{ color: 'var(--ink-3)' }}>{open ? '▾' : '▸'}</span>
      </div>

      {open && (card.items || []).map(it => (
        <div key={it.ref} style={{
          marginTop: 10, paddingTop: 10,
          borderTop: '1px solid var(--line, rgba(128,128,128,0.25))',
          fontSize: '0.86rem',
        }}>
          <div style={{ color: 'var(--ink-2)', marginBottom: 4 }}>
            <code>{it.ref}</code> {it.date} · {it.tag} · {it.symptom}
          </div>
          <HistRow label="매뉴얼 대조" value={it.manual_match}
                   strong={it.manual_match === '불일치'} />
          <HistRow label="처음 조치" value={it.first_action} />
          <HistRow label="실제 원인" value={it.root_cause}
                   strong={it.manual_match === '불일치'} />
          <HistRow label="최종 조치" value={it.action_taken} />
          <div className="ev-cite" style={{ marginTop: 4 }}>
            {it.wo_no} · {it.why}
            {it.duration_min ? ` · ${it.duration_min}분` : ''}
            {it.tech ? ` · ${it.tech}` : ''}
          </div>
        </div>
      ))}
    </div>
  )
}

function HistRow({ label, value, strong }) {
  if (!value) return null
  return (
    <div style={{ display: 'flex', gap: 8, lineHeight: 1.5 }}>
      <span style={{ color: 'var(--ink-3)', minWidth: 68, flexShrink: 0 }}>{label}</span>
      <span style={{ fontWeight: strong ? 600 : 400 }}>{value}</span>
    </div>
  )
}
