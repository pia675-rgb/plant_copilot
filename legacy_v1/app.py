#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Plant Maintenance Copilot 시연 웹 인터페이스

기획서 3주 MVP의 마지막 두 항목:
  · 시연용 웹 UI
  · 조치 결과 피드백을 통한 이력 축적 (사용할수록 데이터가 늘어나는 구조)

실행:
    pip install streamlit openpyxl
    streamlit run app.py -- --src demo_data

핵심 원칙은 copilot_core 와 동일하다.
매뉴얼(권위)과 현장 이력(경험)을 합성하지 않고 끝까지 분리해 표기한다.
"""

import datetime as dt
import json
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from copilot_core import Copilot   # noqa: E402
from advisor import (advise, MODEL as DEFAULT_MODEL,
                     PROVIDER as DEFAULT_PROVIDER,
                     provider_status)   # noqa: E402
import manuals as mn   # noqa: E402

SRC = os.environ.get("COPILOT_SRC", "demo_data")
for i, a in enumerate(sys.argv):
    if a == "--src" and i + 1 < len(sys.argv):
        SRC = sys.argv[i + 1]

MANUAL_DIR = os.environ.get("COPILOT_MANUALS", "manuals")
DRAWING_ARG = os.environ.get("COPILOT_DRAWINGS", "")
for i, a in enumerate(sys.argv):
    if a == "--manuals" and i + 1 < len(sys.argv):
        MANUAL_DIR = sys.argv[i + 1]
    if a == "--drawings" and i + 1 < len(sys.argv):
        DRAWING_ARG = sys.argv[i + 1]

HIST = os.path.join(SRC, "maintenance_history.json")
MATCHES = ["일치", "부분일치", "불일치"]

st.set_page_config(page_title="Plant Maintenance Copilot",
                   page_icon="⚙️",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
:root{
  --bg:#f0f2f5;
  --panel:#ffffff;
  --line:#e2e6eb;
  --line-soft:#eef1f4;
  --ink:#0f172a;
  --ink-2:#334155;
  --muted:#64748b;
  --faint:#94a3b8;
  --accent:#0e7490;
  --accent-hover:#0c5f73;
  --accent-soft:#ecfeff;
  --accent-line:#a5f3fc;
  --accent-deep:#155e75;
  --warn:#b45309;
  --warn-soft:#fffbeb;
  --warn-line:#fcd34d;
  --ok:#047857;
  --ok-soft:#ecfdf5;
  --ok-line:#a7f3d0;
  --danger:#b91c1c;
  --danger-soft:#fef2f2;
  --danger-line:#fecaca;
  --shadow-sm:0 1px 2px rgba(15,23,42,.04);
  --shadow:0 1px 3px rgba(15,23,42,.06), 0 4px 12px rgba(15,23,42,.04);
  --shadow-lg:0 4px 6px -1px rgba(15,23,42,.06), 0 10px 24px -4px rgba(15,23,42,.08);
  --radius:10px;
  --radius-sm:6px;
  --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;
  --sans:"Noto Sans KR","Malgun Gothic",system-ui,sans-serif;
}
.stApp{background:var(--bg)}
html,body,[class*="st-"]{font-family:var(--sans)}
[data-testid="stIconMaterial"],
span[class*="material-symbols"],
span[class*="material-icons"],
.material-symbols-rounded{font-family:"Material Symbols Rounded",
  "Material Icons" !important}
.block-container{padding-top:2.8rem;padding-bottom:3.5rem;max-width:1380px}
h1,h2,h3,h4{color:var(--ink);letter-spacing:-.02em}

/* ---------- 사이드바 ---------- */
section[data-testid="stSidebar"]{
  background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%);
  border-right:1px solid var(--line);
  width:340px !important}
section[data-testid="stSidebar"]>div{width:340px !important}
[role="option"],[role="option"] *,[data-baseweb="popover"] li{
  white-space:normal !important;line-height:1.45 !important;
  font-size:12.5px !important}
[role="listbox"]{max-height:360px}
section[data-testid="stSidebar"] .stMarkdown h4{
  font-size:12px;font-weight:700;margin:6px 0 8px;
  letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
section[data-testid="stSidebar"] label{
  font-size:11.5px !important;color:var(--muted) !important;font-weight:500}
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] div[data-baseweb="select"]>div{
  background:#fff !important;border:1px solid var(--line) !important;
  border-radius:var(--radius-sm) !important;font-size:13px !important;
  box-shadow:var(--shadow-sm) !important}
section[data-testid="stSidebar"] .stButton>button{
  width:100%;text-align:left;justify-content:flex-start;
  background:#fff;border:1px solid var(--line-soft);border-radius:var(--radius-sm);
  padding:8px 10px;font-family:var(--mono);font-size:12px;font-weight:500;
  color:var(--ink-2);line-height:1.35;min-height:0;
  transition:all .15s ease}
section[data-testid="stSidebar"] .stButton>button:hover{
  border-color:var(--accent-line);color:var(--accent);background:var(--accent-soft);
  box-shadow:var(--shadow-sm)}
section[data-testid="stSidebar"] .stButton>button[kind="primary"]{
  background:var(--accent-soft);border-color:var(--accent-line);
  color:var(--accent-deep);box-shadow:inset 3px 0 0 var(--accent)}

/* ---------- 본문 위젯 ---------- */
.stButton>button{
  font-family:var(--sans);font-size:13px;font-weight:600;
  border-radius:var(--radius-sm);padding:9px 18px;border:1px solid var(--line);
  background:#fff;color:var(--ink);box-shadow:var(--shadow-sm);
  transition:all .15s ease}
.stButton>button:hover{
  background:#f8fafc;color:var(--ink);border-color:#cbd5e1;
  box-shadow:var(--shadow)}
.stButton>button[kind="primary"]{
  background:linear-gradient(180deg,var(--accent) 0%,var(--accent-deep) 100%);
  border-color:var(--accent-deep);color:#fff;
  box-shadow:0 1px 2px rgba(14,116,144,.25),0 2px 6px rgba(14,116,144,.15)}
.stButton>button[kind="primary"]:hover{
  background:linear-gradient(180deg,var(--accent-hover) 0%,#0a4f61 100%);
  border-color:#0a4f61;box-shadow:0 2px 4px rgba(14,116,144,.3)}
div[role="radiogroup"] label{font-size:12.5px !important;color:var(--ink-2) !important}
.stCheckbox label{font-size:12.5px !important;color:var(--ink-2) !important}

/* ---------- 헤더 ---------- */
.stApp::before{
  content:"";position:fixed;top:0;left:0;right:0;height:3px;z-index:9999;
  background:linear-gradient(90deg,var(--accent) 0%,#22d3ee 45%,#67e8f9 55%,var(--accent) 100%)}
.hdr{
  display:flex;align-items:center;gap:14px;padding:0 0 16px;
  border-bottom:1px solid var(--line);margin-bottom:20px}
.hdr b{font-size:18px;font-weight:700;letter-spacing:-.03em;color:var(--ink)}
.hdr span{font-size:13px;color:var(--muted);font-weight:500}
.hdr .stamp{margin-left:auto;font:500 11.5px var(--mono);color:var(--faint);
  background:var(--line-soft);padding:4px 10px;border-radius:20px}

/* ---------- 태그 카드 ---------- */
.tagcard{
  display:flex;flex-wrap:wrap;align-items:flex-end;gap:24px;
  padding:22px 24px;background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);margin-bottom:20px;
  box-shadow:var(--shadow);position:relative;overflow:hidden}
.tagcard::before{
  content:"";position:absolute;left:0;top:0;bottom:0;width:4px;
  background:linear-gradient(180deg,var(--accent) 0%,#22d3ee 100%)}
.tagcard .tag-no{
  font:600 32px/1 var(--mono);letter-spacing:-.03em;color:var(--ink);
  padding-left:8px}
.tagcard .tag-name{
  font-size:14px;color:var(--ink-2);margin-top:8px;font-weight:500;
  padding-left:8px}
.tag-meta{display:flex;gap:28px;margin-left:auto;flex-wrap:wrap}
.meta{display:flex;flex-direction:column;gap:4px}
.meta dt{font-size:10px;color:var(--faint);letter-spacing:.06em;
  margin:0;text-transform:uppercase;font-weight:600}
.meta dd{margin:0;font:600 13.5px var(--mono);color:var(--ink)}
.chips{display:flex;gap:8px;flex-basis:100%;padding-left:8px;margin-top:4px}
.chip{font:600 11px var(--mono);padding:4px 10px;border-radius:20px;
  background:var(--line-soft);color:var(--ink-2);border:1px solid transparent}
.chip.is-alarm{
  background:var(--warn-soft);border-color:var(--warn-line);color:var(--warn)}

/* ---------- 패널 ---------- */
.panel{
  background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;margin-bottom:10px;box-shadow:var(--shadow-sm)}
.panel-head{
  display:flex;align-items:baseline;gap:10px;padding:14px 18px;
  border-bottom:1px solid var(--line-soft);
  background:linear-gradient(180deg,#fafbfc 0%,#fff 100%)}
.panel-head h3{margin:0;font-size:13px;font-weight:700;letter-spacing:-.01em;
  color:var(--ink)}
.panel-head .hint{font-size:11px;color:var(--faint);font-weight:500}
.panel-head .cnt{margin-left:auto;font:600 11px var(--mono);color:var(--faint);
  background:var(--line-soft);padding:2px 8px;border-radius:10px}
.item{padding:14px 16px;border-bottom:1px solid var(--line-soft);
  display:flex;flex-direction:column;gap:7px}
.item:last-child{border-bottom:0}
.item-title{font-size:13.5px;font-weight:600;line-height:1.5;margin:0;color:var(--ink)}
.item-body{font-size:12.5px;line-height:1.65;color:var(--ink-2);margin:0}
.item-foot{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.badge{font:600 10.5px var(--mono);padding:3px 8px;border-radius:4px;
  border:1px solid var(--line);background:#f8fafc;color:var(--muted)}
.badge-src{background:var(--accent-soft);border-color:var(--accent-line);color:var(--accent-deep)}
.badge-hist{background:var(--ok-soft);border-color:var(--ok-line);color:var(--ok)}
.badge-warn{background:var(--warn-soft);border-color:var(--warn-line);color:var(--warn)}
.b0{background:var(--ok-soft);border-color:var(--ok-line);color:var(--ok)}
.b1{background:var(--warn-soft);border-color:var(--warn-line);color:var(--warn)}
.b2{background:var(--danger-soft);border-color:var(--danger-line);color:var(--danger)}
.none{padding:20px;color:var(--muted);font-size:13px;text-align:center}

/* 한 패널 안에 항목을 구분선으로 나열 */
div[data-testid="stLayoutWrapper"]:has(.mi){
  background:var(--panel) !important;border:1px solid var(--line) !important;
  border-radius:var(--radius);margin-bottom:10px;box-shadow:var(--shadow-sm)}
div[data-testid="stLayoutWrapper"]:has(.mi)>div{padding:0 !important}
div[data-testid="stLayoutWrapper"]:has(.mi) div[data-testid="stVerticalBlock"]{
  gap:0.3rem}
div[data-testid="stLayoutWrapper"]:has(.mi) div[data-testid="stHorizontalBlock"]{
  gap:0;align-items:flex-start}
div[data-testid="stLayoutWrapper"]:has(.mi) .stButton{padding:14px 14px 0 0}
.mi{padding:14px 18px 13px 18px}
.mi .item-title{font-size:13.5px;font-weight:600;line-height:1.45;margin:0 0 5px 0;
  color:var(--ink)}
.mi .item-body{font-size:12.5px;line-height:1.65;color:var(--ink-2);margin:0}
.mi-foot{margin-top:10px;display:flex;gap:6px;
  align-items:center;flex-wrap:wrap}
.mi-sep{height:1px;background:var(--line-soft) !important;margin:0}
div[data-testid="stLayoutWrapper"]:has(.mi) .stButton>button{
  font-family:var(--mono);font-size:10.5px;font-weight:600;
  padding:3px 9px;min-height:0;border-radius:4px;
  background:transparent;border:1px solid var(--line);color:var(--muted);
  transition:all .12s ease}
div[data-testid="stLayoutWrapper"]:has(.mi) .stButton>button:hover{
  background:var(--accent-soft);border-color:var(--accent-line);color:var(--accent)}

/* 조치 결과 입력 — 투명 배경 제거 */
div[data-testid="stExpander"]{
  background:var(--panel);
  border:1px solid var(--line) !important;border-radius:var(--radius);
  overflow:hidden;box-shadow:var(--shadow-sm)}
div[data-testid="stExpander"] summary,
div[data-testid="stExpander"] details>div:first-child{
  background:var(--panel);font-size:13px;font-weight:600}
div[data-testid="stExpander"] details{background:var(--panel);border:0}
div[data-testid="stExpander"] input,
div[data-testid="stExpander"] textarea,
div[data-testid="stExpander"] div[data-baseweb="input"],
div[data-testid="stExpander"] div[data-baseweb="input"]>div,
div[data-testid="stExpander"] div[data-baseweb="base-input"],
div[data-testid="stExpander"] div[data-baseweb="select"]>div{
  background:#fff !important;border-radius:var(--radius-sm) !important}
div[data-testid="stExpander"] div[data-baseweb="input"],
div[data-testid="stExpander"] div[data-baseweb="select"]>div{
  border:1px solid var(--line) !important;box-shadow:var(--shadow-sm) !important}
div[data-testid="stExpander"] div[data-baseweb="input"]>div{border:0 !important}
div[data-testid="stExpander"] input,
div[data-testid="stExpander"] textarea{border:0 !important}

/* ---------- 대비 바 ---------- */
.diffbar{
  display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:14px 18px;
  background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  margin:12px 0 18px;box-shadow:var(--shadow-sm)}
.diffbar .dl{font-size:12px;font-weight:700;color:var(--ink);
  letter-spacing:.02em}
.diffbar .dtext{font-size:12.5px;color:var(--ink-2)}
.badge-diff{font:600 11px var(--mono);padding:3px 10px;border-radius:20px;
  border:1px solid var(--warn-line);background:var(--warn-soft);color:var(--warn)}
.badge-same{font:600 11px var(--mono);padding:3px 10px;border-radius:20px;
  border:1px solid var(--ok-line);background:var(--ok-soft);color:var(--ok)}

/* ---------- 위치 바 ---------- */
.locbar{
  display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:13px 18px;
  background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);
  border-radius:var(--radius);color:#f1f5f9;margin:16px 0 12px;
  box-shadow:var(--shadow)}
.locbar .lk{font:600 10px var(--mono);color:#64748b;letter-spacing:.08em;
  text-transform:uppercase}
.locbar .lv{font:600 12.5px var(--mono);color:#f1f5f9}
.locbar .sep{color:#334155;margin:0 2px}

/* ---------- 조치 순서 ---------- */
.judgement{
  font-size:14px;line-height:1.65;color:var(--ink-2);
  border-left:3px solid var(--accent);padding:6px 0 6px 16px;margin:12px 0 8px;
  background:linear-gradient(90deg,var(--accent-soft) 0%,transparent 100%);
  border-radius:0 var(--radius-sm) var(--radius-sm) 0}
.step{
  border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;
  background:var(--panel);display:flex;flex-direction:column;gap:8px;
  margin-bottom:12px;box-shadow:var(--shadow-sm);
  transition:box-shadow .15s ease,border-color .15s ease}
.step:hover{box-shadow:var(--shadow);border-color:#cbd5e1}
.step-title{margin:0;font-size:15.5px;font-weight:700;line-height:1.4;
  letter-spacing:-.02em;color:var(--ink)}
.step-body{margin:0;font-size:13px;line-height:1.65;color:var(--muted)}
.step-src{font:500 11px var(--mono);color:var(--faint);
  border-top:1px dashed var(--line);padding-top:9px;margin-top:2px}
.notice{margin-top:8px;font-size:12.5px;color:var(--warn);
  background:var(--warn-soft);border:1px solid var(--warn-line);
  border-radius:var(--radius-sm);padding:11px 14px;font-weight:500}
.verify{margin-top:10px;font:500 11.5px/1.6 var(--mono);color:var(--muted);
  background:#f8fafc;border:1px solid var(--line-soft);
  border-radius:var(--radius-sm);padding:10px 14px}
.drawing-cap{font:500 12px var(--mono);color:var(--muted);margin:12px 0 8px}
.disclaimer{
  font-size:11.5px;line-height:1.7;color:var(--faint);
  border-top:1px solid var(--line);margin-top:28px;padding:14px 2px 0;
  text-align:center}
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def load(_stamp):
    return Copilot(SRC)


def hist_stamp():
    try:
        return os.path.getmtime(HIST)
    except OSError:
        return 0


def append_feedback(rec):
    """조치 결과를 이력에 추가한다. 다음 조회부터 근거로 사용된다."""
    data = json.load(open(HIST, encoding="utf-8"))
    year = rec["date"][:4]
    n = sum(1 for r in data if r["wo_no"].startswith("WO-%s" % year)) + 1
    rec["wo_no"] = "WO-%s-%03d" % (year, n)
    data.append(rec)
    data.sort(key=lambda r: r["date"])
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return rec["wo_no"]


DOC_ALIAS = [("sievers", "M9e OM"), ("m300", "M300 IM"),
             ("et200sp", "ET200SP HA IM"), ("c35", "SDC35 UM")]


def doc_short(fname):
    low = (fname or "").lower()
    for k, v in DOC_ALIAS:
        if k in low:
            return v
    return (fname or "").split(".")[0][:14]


cp = load(hist_stamp())

st.markdown('<div class="hdr"><b>Plant Maintenance Copilot</b>'
            '<span> · 알람 상세 조회</span>'
            '<span class="stamp">%s</span></div>'
            % dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            unsafe_allow_html=True)

# ── 입력 ────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:2px 0 12px;border-bottom:1px solid #e2e6eb;margin-bottom:12px">
      <div style="font:700 14px 'Noto Sans KR',sans-serif;color:#0f172a;letter-spacing:-.02em">PMC</div>
      <div style="font:500 11px 'IBM Plex Mono',monospace;color:#94a3b8;margin-top:2px">Plant Maintenance Copilot</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("#### 알람 조회")

    all_tags = sorted(cp.instruments)
    sysv = sorted({str(cp.instruments[t].get("SYSTEM", "")) for t in all_tags})
    fsys = st.selectbox("계통 좁히기", ["(전체)"] + sysv)
    tags = ([t for t in all_tags
             if str(cp.instruments[t].get("SYSTEM")) == fsys]
            if fsys != "(전체)" else all_tags)

    def hay(t):
        r = cp.instruments[t]
        return " ".join(str(r.get(k, "")) for k in
                        ("TAG", "SERVICE", "SYSTEM", "LOOP GROUP", "MODEL",
                         "MAKER", "PANEL", "TERMINAL", "PLC")).upper()

    q = st.text_input("검색 (선택)", "",
                      placeholder="판넬 · 단자 · 서비스 · 모델",
                      help="태그 외의 조건으로 후보를 줄일 때 씁니다. "
                           "입력 후 Enter")
    for w in q.upper().split():
        tags = [t for t in tags if w in hay(t)]
    if not tags:
        st.warning("조건에 맞는 설비가 없습니다.")
        st.stop()

    prev = st.session_state.get("tag_sel")
    tag = st.selectbox(
        "설비 태그  (입력하면 아래에 후보가 나옵니다)", tags,
        index=tags.index(prev) if prev in tags else 0,
        help="태그를 입력하면 후보가 좁혀집니다")
    if tag != prev:
        st.session_state["tag_sel"] = tag
        st.session_state.pop("dwgview", None)
        st.session_state.pop("pageview", None)

    inst = cp.instruments[tag]
    st.caption("%d / %d 점 · %s %s · %s"
               % (len(tags), len(all_tags), inst["MAKER"], inst["MODEL"],
                  inst["SYSTEM"]))

    alarm = st.text_input("알람 문구 / 증상", "셀 단선",
                          help="한글로 입력해도 됩니다")
    code = st.text_input("계기 화면 코드 (선택)", "",
                         help="예: 10084")
    st.divider()
    st.markdown("#### 조치 제안 생성")
    provs = ["ollama", "azure", "openai"]
    provider = st.selectbox(
        "모델 제공자", provs,
        index=provs.index(DEFAULT_PROVIDER) if DEFAULT_PROVIDER in provs else 0)
    model = st.text_input("모델 / 배포명", DEFAULT_MODEL,
                          help="Azure 는 AZURE_OPENAI_DEPLOYMENT 값이 우선입니다")
    st.caption(provider_status(provider))
    mock = st.checkbox("모의 응답 (모델 없이 검증 경로만)", value=False)
    st.divider()
    st.caption(mn.status(MANUAL_DIR))
    st.caption("시연용 합성 데이터입니다. 실제 설비 데이터가 아닙니다.")

a = cp.answer(tag=tag, alarm=alarm, code=code or None)
i = a["instrument"]

# ── 태그 카드 ────────────────────────────────────────────────
_meta = [("MAKER / MODEL", "%s %s" % (i["maker"], i["model"])),
         ("계통", i["system"]),
         ("LOOP GROUP", i["loop_group"]),
         ("결함 거동", i["fault_mode"])]
st.markdown(
    '<div class="tagcard"><div><div class="tag-no">%s</div>'
    '<div class="tag-name">%s</div></div>'
    '<div class="tag-meta">%s</div>'
    '<div class="chips"><span class="chip is-alarm">%s</span>'
    '<span class="chip">%s</span><span class="chip">%s</span></div></div>'
    % (tag, i["service"],
       "".join('<dl class="meta"><dt>%s</dt><dd>%s</dd></dl>' % kv
               for kv in _meta),
       (alarm or "알람 미입력"),
       "판넬 %s" % inst["PANEL"], "단자 %s" % inst["TERMINAL"]),
    unsafe_allow_html=True)

# ── 좌우 2단 ────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    _dev = (i or {}).get("model") or ""
    st.markdown('<div class="panel"><div class="panel-head">'
                '<h3>매뉴얼 근거</h3><span class="hint">%s</span>'
                '<span class="cnt">· %d건</span></div></div>'
                % (_dev, len(a["manual"])), unsafe_allow_html=True)
    if not a["manual"]:
        st.markdown('<div class="panel"><div class="none">이 계기에 연결된 벤더 '
                    '문서가 없습니다. 근거 없는 조치는 제안하지 않습니다.</div>'
                    '</div>', unsafe_allow_html=True)
    else:
        with st.container(border=True):
            for n, m in enumerate(a["manual"]):
                fn, pg, sec = mn.parse_cite(m["cite"])
                has = bool(pg and mn.resolve(fn, MANUAL_DIR))
                # 줄바꿈 보존 + 조치(remedy)까지 함께 보여 목업처럼 읽기 좋게
                desc = (m.get("description") or "").replace("\n", "<br>")
                rem = (m.get("remedy") or "").replace("\n", "<br>")
                if rem:
                    body = (desc + ("<br><br>" if desc else "") + rem)[:320]
                else:
                    body = desc[:280]
                c_l, c_r = st.columns([2.55, 1])
                c_l.markdown(
                    '<div class="mi"><p class="item-title">%s</p>'
                    '<p class="item-body">%s</p>'
                    '<div class="mi-foot">'
                    '<span class="badge badge-src">%s · p.%s</span>'
                    '<span class="badge">%s</span></div></div>'
                    % (m["name"] or m["id"], body,
                       doc_short(fn), pg if pg else "-",
                       m["code"] or m["id"]), unsafe_allow_html=True)
                if has and c_r.button("p.%d 원문 보기" % pg,
                                      key="pv_" + m["id"],
                                      use_container_width=True):
                    st.session_state["pageview"] = (fn, pg, sec or "", m["id"])
                    st.rerun()
                if n < len(a["manual"]) - 1:
                    st.markdown('<div class="mi-sep"></div>',
                                unsafe_allow_html=True)

with right:
    st.markdown('<div class="panel"><div class="panel-head">'
                '<h3>정비 이력</h3><span class="hint">이 태그</span>'
                '<span class="cnt">· %d건</span></div></div>'
                % len(a["history"]), unsafe_allow_html=True)
    if not a["history"]:
        st.markdown('<div class="panel"><div class="none">관련 보수 이력이 '
                    '없습니다.</div></div>', unsafe_allow_html=True)
    else:
        h = ['<div class="panel">']
        for n, r in enumerate(a["history"]):
            b = "b%d" % MATCHES.index(r["match"])
            # mi 안에 foot를 넣어 패딩·정렬이 목업처럼 일치하도록
            title = (r["root_cause"] or "").replace("\n", "<br>")
            body = (r["action"] or "").replace("\n", "<br>")
            parts_badge = ("" if r["parts"] in ("-", "") else
                           '<span class="badge">%s</span>' % r["parts"])
            h.append(
                '<div class="mi">'
                '<p class="item-title">%s</p>'
                '<p class="item-body">%s</p>'
                '<div class="mi-foot">'
                '<span class="badge %s">%s</span>'
                '<span class="badge badge-hist">%s</span>'
                '<span class="badge">%s</span>'
                '<span class="badge">소요 %d 분</span>%s'
                '</div></div>'
                % (title, body, b, r["match"],
                   r["wo_no"], r["date"], r["duration_min"], parts_badge)
            )
            if n < len(a["history"]) - 1:
                h.append('<div class="mi-sep"></div>')
        h.append('</div>')
        st.markdown("".join(h), unsafe_allow_html=True)

# ── 매뉴얼 원문 페이지 ───────────────────────────────────────
pv = st.session_state.get("pageview")
if pv:
    fn, pg, sec, _id = pv
    path = mn.resolve(fn, MANUAL_DIR)
    total = mn.page_count(path)
    st.write("")
    c1, c2, c3, c4 = st.columns([1, 1, 6, 1])
    if c1.button("← 이전", disabled=pg <= 1):
        st.session_state["pageview"] = (fn, pg - 1, sec, _id)
        st.rerun()
    if c2.button("다음 →", disabled=total and pg >= total):
        st.session_state["pageview"] = (fn, pg + 1, sec, _id)
        st.rerun()
    c3.caption("%s · p.%d / %d%s" % (fn, pg, total, " · " + sec if sec else ""))
    if c4.button("닫기"):
        del st.session_state["pageview"]
        st.rerun()
    png = mn.render_page(path, pg)
    if png:
        st.image(png, use_container_width=True)
    else:
        st.warning("페이지를 불러오지 못했습니다. manuals 폴더와 pymupdf 설치를 "
                   "확인하십시오.")

# ── 대비 ────────────────────────────────────────────────────
c = a["comparison"]
_bcls = {"일치": "badge-same", "부분일치": "badge-diff", "불일치": "badge-diff"}
st.markdown('<div class="diffbar"><span class="dl">대비</span>'
            '<span class="dtext">%s</span>%s</div>'
            % (c["note"],
               "".join('<span class="%s">%s %d</span>'
                       % (_bcls.get(k, "badge"), k, v)
                       for k, v in c["counts"].items())),
            unsafe_allow_html=True)

# ── 조치 제안 (LLM) ──────────────────────────────────────────
st.write("")
key = (tag, alarm, code, provider, model, mock)
if st.button("조치 순서 생성", type="primary"):
    with st.spinner("근거를 바탕으로 점검 순서를 만드는 중"):
        _, out, rep = advise(cp, tag, alarm, code or None,
                             model=model, mock=mock, provider=provider)
    st.session_state["advice"] = (key, out, rep)

adv = st.session_state.get("advice")
if adv and adv[0] == key:
    _, out, rep = adv
    if out is None:
        st.warning("조치 제안을 생성하지 못했습니다 — %s\n\n"
                   "Ollama 가 기동 중인지 확인하십시오. 근거 목록은 위에 그대로 "
                   "표시됩니다." % rep.get("error", "응답 파싱 실패"))
    else:
        st.markdown('<p class="judgement">%s</p>' % out.get("summary", ""),
                    unsafe_allow_html=True)
        if out.get("insufficient") or not out.get("steps"):
            st.markdown('<div class="notice">근거가 부족하여 점검 순서를 '
                        '제안하지 않습니다.</div>', unsafe_allow_html=True)
        for stp in out.get("steps", []):
            st.markdown(
                '<div class="step"><p class="step-title">%d. %s</p>'
                '<p class="step-body">%s</p>'
                '<div class="step-src">근거 %s · %s</div></div>'
                % (stp["order"], stp["action"], stp.get("why", ""),
                   ", ".join(stp.get("refs", [])), stp.get("source", "")),
                unsafe_allow_html=True)
        for c_ in out.get("cautions", []):
            st.markdown('<div class="notice">주의 · %s</div>' % c_,
                        unsafe_allow_html=True)
        st.markdown(
            '<div class="verify">검증 · 생성 %d단계 → 채택 %d단계 / '
            '미검증 근거 인용 %d건 / 근거 누락 %d건%s</div>'
            % (rep.get("steps_in", 0), rep.get("steps_out", 0),
               rep.get("hallucinated", 0), rep.get("no_ref", 0),
               (" / 제거된 참조 " + ", ".join(sorted(set(rep["bad_refs"]))))
               if rep.get("bad_refs") else ""), unsafe_allow_html=True)

# ── 위치 ────────────────────────────────────────────────────
if a["location"]:
    l = a["location"]
    _lp = [("도면", l["dwg_no"]), ("PDF", "%s p" % l["pdf_page"]),
           ("판넬", l["panel"]), ("단자", l["terminal"]),
           ("PLC", l["plc"]), ("슬롯 / 채널", l["slot_ch"])]
    st.markdown('<div class="locbar">%s</div>'
                % '<span class="sep">|</span>'.join(
                    '<span class="lk">%s</span><span class="lv">%s</span>' % kv
                    for kv in _lp), unsafe_allow_html=True)

    dwgs = l.get("drawings") or []
    if dwgs:
        LABEL = {"P&ID": "P&ID · 공정상 위치",
                 "SCHEMATIC": "SCHEMATIC · 결선",
                 "OUTLINE": "OUTLINE · 판넬 내 위치"}
        d1, d2 = st.columns([1, 5])
        if d1.button("도면 보기"):
            st.session_state["dwgview"] = tag
            st.rerun()
        if st.session_state.get("dwgview") == tag:
            kinds = [d["type"] for d in dwgs]
            pick = d2.radio("도면 종류", kinds, horizontal=True,
                            format_func=lambda k: LABEL.get(k, k),
                            label_visibility="collapsed")
            d = next(x for x in dwgs if x["type"] == pick)
            path = os.path.join(DRAWING_ARG or SRC, d["file"])
            if not os.path.exists(path):
                path = os.path.join(SRC, d["file"])
            whole = st.checkbox("전체 도면 보기", value=False)
            band = d["type"] in ("SCHEMATIC", "OUTLINE")
            full, crop, hits = mn.render_drawing(
                path, d["page"], d["find"],
                margin=58 if d["type"] == "SCHEMATIC" else
                       (70 if band else 110), band=band)
            if full is None:
                st.warning("도면을 불러오지 못했습니다. %s 를 확인하십시오." % path)
            else:
                st.markdown('<div class="drawing-cap">%s · %s · %d 매 중 '
                            '%d 매 · 검출 %d 곳</div>'
                            % (LABEL.get(d["type"], d["type"]), d["sheet_no"],
                               mn.page_count(path), d["page"], hits),
                            unsafe_allow_html=True)
                st.image(full if (whole or not crop) else crop,
                         use_container_width=True)
            if st.button("도면 닫기"):
                del st.session_state["dwgview"]
                st.rerun()

# ── 조치 결과 피드백 ─────────────────────────────────────────
st.write("")
with st.expander("조치 결과 입력 — 다음 조회부터 근거로 사용됩니다"):
    NOSEL = "(선택 안 함)"
    refs = [NOSEL] + [m["id"] for m in a["manual"]]
    f1, f2 = st.columns(2)
    with f1:
        f_date = st.date_input("발생일", dt.date.today())
        f_symptom = st.text_input("증상", alarm or "")
        f_ref = st.selectbox("관련 매뉴얼 코드", refs,
                             help="조치한 원인과 실제로 맞는 코드를 고르십시오. "
                                  "확실하지 않으면 선택하지 않아도 됩니다.")
        f_match = st.radio("매뉴얼 일치도", MATCHES, horizontal=True,
                           help="매뉴얼이 지목한 원인과 실제 원인이 같았는지")
    with f2:
        f_cause = st.text_area("실제 원인", height=80)
        f_action = st.text_area("조치 내용", height=80)
        f3, f4 = st.columns(2)
        f_min = f3.number_input("소요(분)", 5, 1440, 60, step=5)
        f_parts = f4.text_input("사용 부품", "-")
    f_tech = st.text_input("담당 (이니셜)", "")

    if st.button("이력에 저장", type="primary"):
        if not f_cause.strip() or not f_action.strip():
            st.warning("실제 원인과 조치 내용은 반드시 입력해 주세요.")
        elif f_ref == NOSEL and not st.session_state.get("ok_noref"):
            st.session_state["ok_noref"] = True
            st.warning("관련 매뉴얼 코드를 고르지 않았습니다. 코드 없이 저장하면 "
                       "이 이력은 태그로만 검색됩니다. 그대로 저장하려면 "
                       "한 번 더 누르십시오.")
        else:
            wo = append_feedback({
                "wo_no": "", "date": f_date.isoformat(), "tag": tag,
                "system": i["system"], "device": i["model"],
                "symptom": f_symptom,
                "code_ref": "" if f_ref == NOSEL else f_ref,
                "first_action": "", "root_cause": f_cause.strip(),
                "action_taken": f_action.strip(), "manual_match": f_match,
                "duration_min": int(f_min), "parts": f_parts or "-",
                "tech": f_tech or "-",
            })
            st.session_state.pop("ok_noref", None)
            st.cache_resource.clear()
            st.success("%s 로 저장했습니다. 같은 태그를 다시 조회하면 "
                       "근거 목록에 포함됩니다." % wo)
            st.rerun()

st.markdown('<div class="disclaimer">본 화면의 출력은 참고 정보이며 작업 지시가 아닙니다. '
            '실제 작업은 정비 절차서와 안전 절차(LOTO)를 따르십시오.</div>',
            unsafe_allow_html=True)
