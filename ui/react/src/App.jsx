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
  const [alarm, setAlarm] = useState('acid residual low')
  const [code, setCode] = useState('')
  // lexical 은 한글 질의를 구조적으로 못 푼다. 시연 기본값으로 두면
  // 가장 약한 구성이 첫 화면이 된다. 서버 기본값과 맞춘다.
  const [mode, setMode] = useState('hybrid')
  const [health, setHealth] = useState(null)
  const [ilAction, setIlAction] = useState('OPEN')
  const [panelSel, setPanelSel] = useState(null)
  const [cardSel, setCardSel] = useState(null)
  const [asInput, setAsInput] = useState(false)
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
    // 인터락 탭: 출력 태그 우선, 알람 탭: 계기 태그 우선
    if (tab === 'interlock' && t.kind === 'instrument') return false
    if (tab === 'alarm' && t.kind === 'output') return false
    if (tagQ) {
      const hay = `${t.tag} ${t.service} ${t.model} ${t.maker}`.toLowerCase()
      if (!hay.includes(tagQ.toLowerCase())) return false
    }
    return true
  })

  // 탭 전환 시 해당 목록의 첫 태그로 맞춤
  useEffect(() => {
    if (!filteredTags.length) return
    if (!filteredTags.some(t => t.tag === tag)) {
      setTag(filteredTags[0].tag)
    }
  }, [tab, tagQ, tags])

  return (
    <div className={`app-shell ${navOpen ? '' : 'nav-collapsed'}`}>
      <aside className="sidebar">
        <div className="sidebar-title">
          Plant Maintenance Copilot
          <button className="nav-toggle" onClick={() => setNavOpen(false)}
            title="사이드바 숨기기 (Ctrl+B)" aria-label="사이드바 숨기기">‹</button>
        </div>

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
                  {t.kind === 'output'
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
                return `${t.maker} ${t.model} · ${t.service}`
              })()}
            </div>
          )}
        </div>

        {tab === 'alarm' && (
          <div className="sidebar-section">
            <h3>알람 조건</h3>
            <div className="field">
              <label>알람 문구 / 증상</label>
              <input value={alarm} onChange={e => setAlarm(e.target.value)} />
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

      <main className="main">
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
            tag={tag} alarm={alarm} code={code} mode={mode}
            onResult={setScreen}
            botPending={botPending}
            onBotHandled={() => setBotPending(null)}
            onAlarmChange={setAlarm}
          />
        )}
        {tab === 'interlock' && (
          <InterlockView
            key={`il-${tag}-${ilAction}-${asInput}`}
            tag={tag} action={ilAction} asInput={asInput}
            botPending={botPending}
            onBotHandled={() => setBotPending(null)}
          />
        )}
        {tab === 'panel' && (
          <PanelView key="panel" tag={tag} panelSel={panelSel} cardSel={cardSel} onPickTag={setTag} />
        )}
      </main>

      <HelpBot
        screen={screen}
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
function AlarmView({ tag, alarm, code, mode, botPending, onBotHandled, onAlarmChange, onResult }) {
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
  // 4D 리포트 기입란 — D3(확정 원인)·D4(실시 조치·부품·소요·담당).
  // API 는 처음부터 이 값들을 받고 있었는데 화면에 넣을 자리가 없어
  // 늘 빈 채로 나갔고, PDF 에는 '(조치 후 기입)' 만 찍혔다.
  const [repOpen, setRepOpen] = useState(false)
  const [rep, setRep] = useState({
    tech: '', confirmed_cause: '', final_action: '', parts: '', duration_min: '',
  })
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
      post('/advice', { tag, alarm, code, mode })
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
      setAdvice(await post('/advice', { tag, alarm, code, mode }))
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
          tech: rep.tech.trim(),
          confirmed_cause: rep.confirmed_cause.trim(),
          final_action: rep.final_action.trim(),
          parts: rep.parts.trim() || '-',
          duration_min: rep.duration_min === '' ? null : Number(rep.duration_min),
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
        <h1>Plant Maintenance Copilot <span>· 알람 상세</span></h1>
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
        <button className="btn" style={{ width: 'auto', padding: '8px 16px' }}
          onClick={() => setRepOpen(v => !v)} disabled={!tag}>
          {repOpen ? '4D 기입란 접기' : '4D 기입란'}
        </button>
        <button className="btn" style={{ width: 'auto', padding: '8px 16px', borderColor: 'var(--safety)', color: 'var(--safety)' }}
          onClick={runReport} disabled={repLoading || !tag}>
          {repLoading ? 'PDF 생성 중…' : '4D 리포트 PDF'}
        </button>
      </div>

      {/* 4D 기입란 — 비워 두면 PDF 에 '(조치 후 기입)' 으로 남는다.
          조치 전에 리포트를 뽑아 현장에서 손으로 채우는 방식도 그대로 된다.
          입력칸은 반드시 .field 로 감싼다 — 맨 input 은 앱 배색을 못 받아
          흰 배경에 밝은 글자가 얹혀 글씨가 안 보인다. */}
      {repOpen && (
        <div className="panel" style={{ marginBottom: 16, padding: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--fg-3)', marginBottom: 10 }}>
            조치 후 확인된 내용을 적으면 PDF 의 D3·D4 에 그대로 들어갑니다.
            비워 두면 '(조치 후 기입)' 으로 남습니다.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <label>D3 확정 원인</label>
              <input value={rep.confirmed_cause}
                onChange={e => setRep({ ...rep, confirmed_cause: e.target.value })}
                placeholder="예: 센서 다이어프램 스케일 고착" />
            </div>
            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <label>D4 실시 조치</label>
              <input value={rep.final_action}
                onChange={e => setRep({ ...rep, final_action: e.target.value })}
                placeholder="예: 센서 교체 후 영점 재교정" />
            </div>
            <div className="field">
              <label>사용 부품</label>
              <input value={rep.parts}
                onChange={e => setRep({ ...rep, parts: e.target.value })}
                placeholder="예: 12126957 (센서 카트리지)" />
            </div>
            <div className="field">
              <label>소요 시간 (분)</label>
              <input value={rep.duration_min} inputMode="numeric"
                onChange={e => setRep({ ...rep, duration_min: e.target.value.replace(/[^0-9]/g, '') })}
                placeholder="예: 45" />
            </div>
            <div className="field">
              <label>담당</label>
              <input value={rep.tech}
                onChange={e => setRep({ ...rep, tech: e.target.value })}
                placeholder="예: 홍길동" />
            </div>
          </div>
        </div>
      )}

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
              <div className="step-item" key={s.n}>
                <div className="step-n">{s.n}</div>
                <div>
                  <div className="step-title">{s.title}</div>
                  <div className="step-detail">{s.detail}</div>
                  <div className="ev-cite">근거 {s.source} · {s.kind}</div>
                </div>
              </div>
            ))}
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
          {fbOpen ? '▾' : '▸'} 조치 결과 입력 — 다음 조회부터 근거로 사용됩니다
        </div>
        {fbOpen && (
          <div className="panel-body">
            <FeedbackForm tag={tag} alarm={alarm} onSaved={() => {
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

function PanelView({ tag, panelSel, cardSel, onPickTag }) {
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
        <h1>Plant Maintenance Copilot <span>· 판넬 조회</span></h1>
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
    </>
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
      setMsg(`저장됨: ${res.record.wo_no}`)
      setRoot('')
      setAction('')
      onSaved?.()
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
function InterlockView({ tag, action, asInput, botPending, onBotHandled }) {
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

  useEffect(() => {
    if (!botPending) return
    if (botPending.type === 'interlock' || botPending.type === 'interlock_source') {
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
        <h1>Plant Maintenance Copilot <span>· 인터락 조회</span></h1>
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
                    title={`${data.output.tag} 공정 화면`}
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
    '⑤ 인터락 조회 — 탭 전환 후 XV/LCV 등 출력 태그\n\n' +
    '저에게 자연어로 시킬 수도 있습니다.\n' +
    '예: 「AIT-4002 low acid 알람 조회해줘」'
  )
}

function HelpBot({ tags, currentTag, currentTab, onCommand, screen }) {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState([
    {
      role: 'bot',
      text: '현장 유지보수 코파일럿 도우미입니다. 사용법이 궁금하면 물어보거나, 자연어로 바로 실행해 보세요.',
    },
  ])
  const [engine, setEngine] = useState('rule')
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
    let intent = null
    try {
      intent = await post('/chat', {
        message: text,
        tag: currentTag || '',
        tab: currentTab || 'alarm',
        use_llm: true,
        // 화면에 떠 있는 결과. 후속 질문은 이것을 근거로 답한다.
        context: screen || null,
      })
    } catch (e) {
      // 백엔드에 못 닿으면 화면 안의 간이 파서로 내려간다. 조용히
      // 내려가면 왜 답이 달라졌는지 알 수 없으므로 표시한다.
      intent = parseBotIntent(text, tags)
      if (intent.type === 'help') intent.reply = helpReply()
      intent.reply = (intent.reply || '') + '\n(오프라인 해석 — 서버에 연결하지 못했습니다)'
    }
    if (!intent) return
    if (intent.type === 'help' && !intent.reply) intent.reply = helpReply()
    if (intent.reply) push('bot', intent.reply, intent.citations)
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

  return (
    <div className={`helpbot ${open ? 'open' : ''}`}>
      {open && (
        <div className="helpbot-panel">
          <div className="helpbot-head">
            <div className="helpbot-brand">
              <div className="helpbot-avatar" aria-hidden>
                <img src="/assistant-badge.jpg" alt="" draggable={false} />
              </div>
              <div>
                <div className="helpbot-title">Copilot Assistant</div>
                <div className="helpbot-sub">가이드 · 자연어 실행 · {engine}</div>
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
                    <img src="/assistant-badge.jpg" alt="" draggable={false} />
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
          <img src="/assistant-badge.jpg" alt="" className="helpbot-fab-img" draggable={false} />
        )}
      </button>
    </div>
  )
}

