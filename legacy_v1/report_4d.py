# -*- coding: utf-8 -*-
"""4D 트러블 리포트 PDF 생성 (A4)."""

from __future__ import annotations

import io
import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ORANGE = (0.90, 0.27, 0.10)
INK = (0.10, 0.10, 0.12)
MUTED = (0.40, 0.40, 0.45)
LINE = (0.85, 0.85, 0.88)
SOFT = (0.18, 0.18, 0.22)

_FONT_REG = None
_FONT_BOLD = None


def _register_fonts():
    """Windows/macOS/Linux에서 한글 TTF를 찾아 등록."""
    global _FONT_REG, _FONT_BOLD
    if _FONT_REG:
        return

    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    fonts_dir = os.path.join(windir, "Fonts")
    here = os.path.dirname(os.path.abspath(__file__))

    # 경로를 넉넉히 나열 (Windows 맑은 고딕 최우선)
    pairs = [
        (os.path.join(fonts_dir, "malgun.ttf"),
         os.path.join(fonts_dir, "malgunbd.ttf")),
        (r"C:\Windows\Fonts\malgun.ttf",
         r"C:\Windows\Fonts\malgunbd.ttf"),
        (r"C:\WINDOWS\Fonts\malgun.ttf",
         r"C:\WINDOWS\Fonts\malgunbd.ttf"),
        (os.path.join(fonts_dir, "malgun.ttf"),
         os.path.join(fonts_dir, "malgun.ttf")),
        (r"C:\Windows\Fonts\malgun.ttf",
         r"C:\Windows\Fonts\malgun.ttf"),
        (os.path.join(fonts_dir, "NanumGothic.ttf"),
         os.path.join(fonts_dir, "NanumGothicBold.ttf")),
        (os.path.join(here, "fonts", "NanumGothic.ttf"),
         os.path.join(here, "fonts", "NanumGothicBold.ttf")),
        (os.path.join(here, "fonts", "malgun.ttf"),
         os.path.join(here, "fonts", "malgunbd.ttf")),
        ("/usr/share/fonts/SlidesCarnival/google/Nanum Gothic/NanumGothic-Regular.ttf",
         "/usr/share/fonts/SlidesCarnival/google/Nanum Gothic/NanumGothic-Bold.ttf"),
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
         "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    ]

    errors = []
    for reg, bold in pairs:
        if not os.path.isfile(reg):
            errors.append("missing: %s" % reg)
            continue
        if not os.path.isfile(bold):
            bold = reg  # bold 없으면 regular로 대체
        try:
            if reg.lower().endswith(".ttc"):
                pdfmetrics.registerFont(TTFont("KR", reg, subfontIndex=0))
                pdfmetrics.registerFont(TTFont("KR-Bold", bold, subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont("KR", reg))
                pdfmetrics.registerFont(TTFont("KR-Bold", bold))
            _FONT_REG, _FONT_BOLD = "KR", "KR-Bold"
            # 성공 경로를 환경변수로 남김(디버그용)
            os.environ["PMC_KR_FONT"] = reg
            return
        except Exception as e:
            errors.append("%s -> %s: %s" % (reg, bold, e))
            continue

    _FONT_REG = _FONT_BOLD = "Helvetica"
    os.environ["PMC_KR_FONT_ERRORS"] = " | ".join(errors[:8])


def _wrap(c, text, font, size, max_w):
    """Simple character-based wrap for CJK + Latin."""
    if not text:
        return []
    text = str(text).replace("\r", "")
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        buf = ""
        for ch in para:
            trial = buf + ch
            if c.stringWidth(trial, font, size) <= max_w:
                buf = trial
            else:
                if buf:
                    lines.append(buf)
                buf = ch
        if buf:
            lines.append(buf)
    return lines


def build_4d_pdf(payload: dict) -> bytes:
    """A4 4D 트러블 리포트 PDF. 여백·헤더·섹션 정렬 최적화."""
    _register_fonts()
    FR, FB = _FONT_REG, _FONT_BOLD

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # ---- 레이아웃 상수 (A4 mm 기준) ----
    M = 12 * mm              # 페이지 좌우 여백
    SPINE = 10 * mm          # D1~D4 왼쪽 화살표 칸
    card_l = M + SPINE
    card_r = W - M
    FOOTER_H = 16 * mm

    def set_fill(rgb):
        c.setFillColorRGB(*rgb)

    def set_stroke(rgb):
        c.setStrokeColorRGB(*rgb)

    def fit_text(val, font, size, max_w, min_size=7.5):
        """칸 폭에 맞게 글자 크기 축소 후 말줄임."""
        val = str(val or "-")
        s = float(size)
        while s > min_size and c.stringWidth(val, font, s) > max_w:
            s -= 0.5
        while c.stringWidth(val, font, s) > max_w and len(val) > 4:
            val = val[:-2] + "…"
        return val, s

    # 상단 액센트
    c.setStrokeColorRGB(0.75, 0.35, 0.15)
    c.setLineWidth(1.4)
    c.line(M, H - 7 * mm, card_r, H - 7 * mm)
    set_fill(ORANGE)
    path = c.beginPath()
    path.moveTo(W - 16 * mm, H)
    path.lineTo(W, H)
    path.lineTo(W, H - 11 * mm)
    path.close()
    c.drawPath(path, fill=1, stroke=0)

    # 제목 (페이지 왼쪽)
    set_fill(INK)
    c.setFont(FB, 17)
    c.drawString(M, H - 16 * mm, "4D 트러블 리포트")
    c.setFont(FR, 8.5)
    set_fill(MUTED)
    c.drawString(M, H - 20.5 * mm, "4D Trouble Report  ·  Plant Maintenance Copilot")

    # ---- 헤더 카드 (전체 폭, 3행이 박스 안에 수납) ----
    hy1 = H - 24 * mm
    hy0 = H - 58 * mm
    set_stroke(LINE)
    c.setLineWidth(0.7)
    set_fill((1, 1, 1))
    c.roundRect(M, hy0, card_r - M, hy1 - hy0, 3.5, fill=1, stroke=1)

    maker = (payload.get("maker") or "").strip()
    model = (payload.get("model") or "").strip()
    mm_val = ("%s %s" % (maker, model)).strip() or "-"

    headers = [
        ("문서번호", payload.get("doc_no") or "-"),
        ("작성일시", payload.get("date_str") or "-"),
        ("담당", payload.get("tech") or "-"),
        ("설비 태그", payload.get("tag") or "-"),
        ("계통", payload.get("system") or "-"),
        ("알람 / 증상", payload.get("alarm") or "-"),
        ("Maker / Model", mm_val),
        ("판넬 / 단자", "%s / %s" % (
            payload.get("panel") or "-", payload.get("terminal") or "-")),
        ("상태", payload.get("status") or "조회"),
    ]
    col_w = (card_r - M) / 3.0
    max_val_w = col_w - 5 * mm
    row_pitch = 10 * mm
    for i, (lab, val) in enumerate(headers):
        col, row = i % 3, i // 3
        x = M + 3 * mm + col * col_w
        y = hy1 - 5.5 * mm - row * row_pitch
        set_fill(MUTED)
        c.setFont(FR, 7)
        c.drawString(x, y, lab)
        set_fill(INK)
        val, sz = fit_text(val, FB, 9.5, max_val_w)
        c.setFont(FB, sz)
        c.drawString(x, y - 3.8 * mm, val)

    # ---- 섹션 본문 ----
    manuals = payload.get("manual") or []
    history = payload.get("history") or []
    steps = payload.get("advice_steps") or []

    d1_lines = [
        "• 태그 %s에서 「%s」 알람 발생" % (
            payload.get("tag") or "-", payload.get("alarm") or "미입력"),
        "• 계통 %s · 계기 %s %s" % (
            payload.get("system") or "-",
            payload.get("maker") or "",
            payload.get("model") or ""),
    ]
    if payload.get("code"):
        d1_lines.append("• 계기 화면 코드: %s" % payload["code"])
    d1_lines.append(
        "• 동일 태그 과거 이력 %d건 확인" % len(history)
        if history else "• 동일 태그 과거 이력 없음")

    if steps:
        d2_lines = ["[v] %d. %s" % (i + 1, s) for i, s in enumerate(steps[:5])]
    else:
        d2_lines = [
            "[v] 1. 현장 계기 표시 및 센서 배선 상태 육안 확인",
            "[v] 2. 관련 루프 수동 감시 / 필요 시 절차에 따른 안전 조치",
            "[v] 3. 동일 계통 연관 알람 여부 확인",
        ]
    d2_lines.append("※ 실제 작업은 정비 절차서 및 LOTO를 준수한다")

    d3_lines = []
    for m in manuals[:2]:
        name = m.get("name") or m.get("id") or ""
        desc = (m.get("description") or "").replace("●", "·").replace("•", "·")
        if len(desc) > 70:
            desc = desc[:67] + "…"
        cite = m.get("cite_short") or m.get("cite") or ""
        d3_lines.append("• 매뉴얼 근거: %s" % name)
        if desc:
            d3_lines.append("    %s" % desc)
        if cite:
            d3_lines.append("    출처  %s" % cite)
    for h in history[:2]:
        d3_lines.append(
            "• 현장 이력: %s → %s" % (
                (h.get("root_cause") or "")[:48],
                (h.get("action") or "")[:36]))
        d3_lines.append(
            "    %s · %s · 소요 %s분" % (
                h.get("wo_no") or "-",
                h.get("match") or "-",
                h.get("duration_min") if h.get("duration_min") is not None else "-"))
    if not d3_lines:
        d3_lines = ["• 검색된 매뉴얼 근거 및 현장 이력이 없습니다."]
    if payload.get("confirmed_cause"):
        d3_lines.append("• 확정 원인: %s" % payload["confirmed_cause"])
    else:
        d3_lines.append("• 확정 원인: (조치 후 기입)")

    d4_lines = []
    if payload.get("final_action"):
        d4_lines.append("• 실시 조치: %s" % payload["final_action"])
    else:
        d4_lines.append("• 실시 조치: (조치 후 기입)")
    d4_lines.append(
        "• 부품: %s  ·  소요: %s분  ·  담당: %s" % (
            payload.get("parts") or "-",
            payload.get("duration_min") if payload.get("duration_min") is not None else "-",
            payload.get("tech") or "-"))
    d4_lines.append("[ ] 알람 해제 및 측정값 정상 확인")
    d4_lines.append("[ ] 재발 방지 조치 반영")
    d4_lines.append("• Copilot 이력 등록 후 다음 조회의 근거로 사용")

    sections = [
        ("D1. 문제 기술 (Problem Description)", d1_lines, "D1"),
        ("D2. 즉시 조치 (Interim Actions)", d2_lines, "D2"),
        ("D3. 원인 (Root Cause)", d3_lines, "D3"),
        ("D4. 시정 및 재발 방지 (Corrective Actions)", d4_lines, "D4"),
    ]

    # 내용량 기반 높이 (최소 높이 보장 + 남는 공간 분배)
    body_top = hy0 - 3.5 * mm
    body_bot = FOOTER_H + 2 * mm
    gap = 2.2 * mm
    avail = body_top - body_bot - gap * 3
    line_h = 3.9 * mm
    title_h = 7 * mm
    pad = 5 * mm
    mins = []
    for _, lines, _ in sections:
        mins.append(title_h + pad + max(3, len(lines)) * line_h)
    # 최소 합이 avail 초과하면 비율 축소
    total_min = sum(mins)
    if total_min <= avail:
        extra = avail - total_min
        # 남는 공간은 내용 많은 섹션에 더 배분
        weights = [max(1, len(s[1])) for s in sections]
        sw = float(sum(weights))
        heights = [mins[i] + extra * (weights[i] / sw) for i in range(4)]
    else:
        heights = [avail * (m / total_min) for m in mins]

    centers = []
    y = body_top
    for (title, lines, label), h in zip(sections, heights):
        y1 = y - h
        set_stroke(LINE)
        c.setLineWidth(0.65)
        set_fill((1, 1, 1))
        c.roundRect(card_l, y1, card_r - card_l, h, 3.5, fill=1, stroke=1)
        set_fill(ORANGE)
        c.rect(card_l, y1 + 1 * mm, 1.5 * mm, h - 2 * mm, fill=1, stroke=0)

        set_fill(ORANGE)
        c.setFont(FB, 10.5)
        c.drawString(card_l + 3.5 * mm, y - 5 * mm, title)

        set_fill(SOFT)
        c.setFont(FR, 8.5)
        text_w = card_r - card_l - 8 * mm
        ty = y - 10 * mm
        for line in lines:
            for wline in _wrap(c, line, FR, 8.5, text_w):
                if ty < y1 + 3 * mm:
                    break
                c.drawString(card_l + 3.5 * mm, ty, wline)
                ty -= line_h
        centers.append((y1 + h / 2.0, label))
        y = y1 - gap

    # 왼쪽 D1→D4 스파인
    spine_x = M + SPINE / 2.0
    for i, (cy, label) in enumerate(centers):
        r = 4.8 * mm
        set_fill(ORANGE)
        c.circle(spine_x, cy, r, fill=1, stroke=0)
        set_fill((1, 1, 1))
        c.setFont(FB, 7.5)
        c.drawCentredString(spine_x, cy - 1.1 * mm, label)
        if i < len(centers) - 1:
            next_cy = centers[i + 1][0]
            set_stroke(ORANGE)
            c.setLineWidth(1.8)
            c.line(spine_x, cy - r - 0.4 * mm, spine_x, next_cy + r + 2.2 * mm)
            set_fill(ORANGE)
            path = c.beginPath()
            path.moveTo(spine_x, next_cy + r)
            path.lineTo(spine_x - 1.8 * mm, next_cy + r + 2.6 * mm)
            path.lineTo(spine_x + 1.8 * mm, next_cy + r + 2.6 * mm)
            path.close()
            c.drawPath(path, fill=1, stroke=0)

    # 푸터 (헤더와 같은 왼쪽 기준 M)
    set_stroke(LINE)
    c.setLineWidth(0.55)
    c.line(M, FOOTER_H - 1 * mm, card_r, FOOTER_H - 1 * mm)
    set_fill(ORANGE)
    c.setFont(FB, 8.5)
    c.drawString(M, 8.5 * mm, "SK AX")
    set_fill(MUTED)
    c.setFont(FR, 7.5)
    c.drawString(M + 13 * mm, 8.5 * mm, "Plant Maintenance Copilot")
    c.setFont(FR, 6.5)
    c.drawString(
        M, 4.5 * mm,
        "본 보고서는 참고 정보이며 공식 작업지시가 아닙니다. "
        "실제 작업은 승인된 절차서와 안전 절차(LOTO)를 따르십시오.")

    c.showPage()
    c.save()
    return buf.getvalue()


def payload_from_query(tag, alarm, code, inst_row, answer, tech="",
                       advice_out=None, feedback=None):
    """Streamlit 조회 결과 → build_4d_pdf payload."""
    i = answer.get("instrument") or {}
    manuals = []
    for m in answer.get("manual") or []:
        cite = m.get("cite") or ""
        # 파일명만 + 페이지 (긴 경로 제거)
        base = cite.replace("\\", "/").split("/")[-1]
        short = base
        if " p." in base:
            name_part, _, rest = base.partition(" p.")
            # 파일명 축약
            if len(name_part) > 28:
                name_part = name_part[:12] + "…" + name_part[-10:]
            pg = rest.split()[0] if rest.strip() else ""
            short = "%s p.%s" % (name_part, pg)
        elif len(short) > 40:
            short = short[:37] + "…"
        desc = (m.get("description") or "")
        desc = desc.replace("●", "·").replace("•", "·")
        if len(desc) > 80:
            desc = desc[:77] + "…"
        manuals.append({
            "name": m.get("name") or m.get("id") or "",
            "description": desc,
            "cite_short": short,
            "cite": cite,
            "id": m.get("id"),
        })
    history = []
    for h in answer.get("history") or []:
        history.append({
            "root_cause": h.get("root_cause") or "",
            "action": h.get("action") or "",
            "wo_no": h.get("wo_no") or "",
            "match": h.get("match") or "",
            "duration_min": h.get("duration_min"),
            "date": h.get("date") or "",
        })
    steps = []
    if advice_out and isinstance(advice_out, dict):
        for s in advice_out.get("steps") or advice_out.get("checklist") or []:
            if isinstance(s, dict):
                steps.append(s.get("action") or s.get("text") or str(s))
            else:
                steps.append(str(s))

    fb = feedback or {}
    now = datetime.now()
    doc_no = "TR-%s-%s" % (now.strftime("%Y%m%d"), (tag or "TAG")[-4:])
    return {
        "doc_no": doc_no,
        "date_str": now.strftime("%Y-%m-%d %H:%M"),
        "tag": tag,
        "alarm": alarm or "",
        "code": code or "",
        "tech": tech or fb.get("tech") or "-",
        "maker": i.get("maker") or (inst_row or {}).get("MAKER") or "",
        "model": i.get("model") or (inst_row or {}).get("MODEL") or "",
        "system": i.get("system") or (inst_row or {}).get("SYSTEM") or "",
        "panel": (inst_row or {}).get("PANEL") or "-",
        "terminal": (inst_row or {}).get("TERMINAL") or "-",
        "service": i.get("service") or "",
        "status": "조회",
        "manual": manuals,
        "history": history,
        "advice_steps": steps,
        "confirmed_cause": fb.get("root_cause") or "",
        "final_action": fb.get("action_taken") or "",
        "parts": fb.get("parts") or "-",
        "duration_min": fb.get("duration_min"),
    }
