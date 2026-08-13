#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manuals.py — 인용된 매뉴얼 페이지를 이미지로 뽑아 보여주기 위한 모듈

원칙: 전문을 앱에 싣지 않는다. 인용된 페이지 한 장(옵션으로 앞뒤 1장)만
렌더한다. 벤더 문서 전체를 배포하는 것과 인용 근거를 확인시키는 것은 다르다.

매뉴얼 PDF 는 manuals/ 폴더에 둔다. 파일명은 error_codes.json 의
source.file 값과 같아야 하며, 다르면 별칭으로 느슨하게 찾는다.

    manuals/
      im_e_sievers-m9-manual_dlm_77020-02.pdf
      OM_Transmitter_M300_en_52121389_Dec14.pdf
      et200sp_ha_AI_16xI_2-wire_HART_HA_en-US_en-US.pdf

의존성: pymupdf
"""

import os
import re

try:
    import fitz            # pymupdf
    HAVE_FITZ = True
except ImportError:
    HAVE_FITZ = False


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def list_manuals(manual_dir):
    if not os.path.isdir(manual_dir):
        return []
    return sorted(f for f in os.listdir(manual_dir)
                  if f.lower().endswith(".pdf"))


def resolve(file_name, manual_dir):
    """인용에 적힌 파일명으로 실제 PDF 경로를 찾는다.

    정확히 일치하면 그대로, 아니면 이름을 정규화해 부분 일치로 찾는다.
    파일명을 조금 바꿔 저장해도 동작하도록 하기 위함이다.
    """
    if not file_name or not os.path.isdir(manual_dir):
        return None
    exact = os.path.join(manual_dir, file_name)
    if os.path.exists(exact):
        return exact

    want = _norm(os.path.splitext(file_name)[0])
    best, best_len = None, 0
    for f in list_manuals(manual_dir):
        got = _norm(os.path.splitext(f)[0])
        if want and (want in got or got in want):
            n = min(len(want), len(got))
            if n > best_len:
                best, best_len = os.path.join(manual_dir, f), n
    return best


def page_count(path):
    if not (HAVE_FITZ and path and os.path.exists(path)):
        return 0
    with fitz.open(path) as d:
        return len(d)


def render_page(path, page_no, dpi=150):
    """1-based 페이지 번호를 PNG 바이트로 렌더한다. 실패하면 None."""
    if not (HAVE_FITZ and path and os.path.exists(path)):
        return None
    try:
        with fitz.open(path) as d:
            i = max(1, min(int(page_no), len(d))) - 1
            return d[i].get_pixmap(dpi=dpi).tobytes("png")
    except Exception:
        return None


def find_drawing(src, drawings=None):
    """도면 PDF 경로를 찾는다. 폴더를 주면 그 안의 첫 PDF, 아니면 src/DEMO_PID.pdf."""
    if drawings:
        if os.path.isfile(drawings):
            return drawings
        if os.path.isdir(drawings):
            files = list_manuals(drawings)
            return os.path.join(drawings, files[0]) if files else None
    cand = os.path.join(src, "DEMO_PID.pdf")
    return cand if os.path.exists(cand) else None


def render_drawing(path, page_no, tag=None, dpi=150, margin=110,
                   band=False):
    """tag 에 "A|B" 처럼 여러 검색어를 주면 모두 표시하고, 먼저 걸린 쪽을 확대한다.

    band=True 면 좌우를 자르지 않고 가로 전체 띠로 잘라낸다.
    결선도처럼 한 줄이 좌(현장)에서 우(판넬)로 이어지는 도면에 쓴다.
    """
    """도면 페이지를 렌더한다. 태그를 주면 위치를 표시하고 그 주변도 잘라 준다.

    반환: (전체 PNG, 확대 PNG 또는 None, 검출 개수)
    A3 도면을 화면 폭에 맞추면 계기 버블 글자가 안 보이므로,
    태그 주변을 잘라낸 확대본을 기본으로 쓰기 위함이다.
    """
    if not (HAVE_FITZ and path and os.path.exists(path)):
        return None, None, 0
    try:
        with fitz.open(path) as d:
            i = max(1, min(int(page_no), len(d))) - 1
            pg = d[i]
            terms = [t for t in (tag or "").split("|") if t]
            rects, focus = [], []
            for t in terms:
                got = pg.search_for(t)
                rects.extend(got)
                if got and not focus:
                    focus = got

            if rects:
                sh = pg.new_shape()
                for r in rects:
                    sh.draw_rect(fitz.Rect(r.x0 - 9, r.y0 - 9,
                                           r.x1 + 9, r.y1 + 9))
                sh.finish(color=(0.82, 0.0, 0.17), width=1.6)
                sh.commit()

            full = pg.get_pixmap(dpi=dpi).tobytes("png")

            crop = None
            if focus:
                r = focus[0]
                if band:
                    box = fitz.Rect(pg.rect.x0 + 8, r.y0 - margin,
                                    pg.rect.x1 - 8, r.y1 + margin) & pg.rect
                    scale = 1.4
                else:
                    box = fitz.Rect(r.x0 - margin, r.y0 - margin,
                                    r.x1 + margin, r.y1 + margin) & pg.rect
                    scale = 2.0
                crop = pg.get_pixmap(dpi=int(dpi * scale),
                                     clip=box).tobytes("png")
            return full, crop, len(rects)
    except Exception:
        return None, None, 0


def parse_cite(cite):
    """'파일명.pdf p.413 (Appendix F)' → ('파일명.pdf', 413, 'Appendix F')"""
    m = re.match(r"^(.*?\.pdf)\s+p\.(\d+)(?:\s*\((.*?)\))?", cite or "",
                 re.I)
    if not m:
        return None, None, None
    return m.group(1), int(m.group(2)), m.group(3)


def status(manual_dir):
    """시작 시 안내용 — 어떤 매뉴얼이 준비되어 있는지."""
    if not HAVE_FITZ:
        return "pymupdf 가 설치되지 않아 매뉴얼 페이지 보기를 쓸 수 없습니다."
    files = list_manuals(manual_dir)
    if not files:
        return "매뉴얼 PDF 없음 (%s 폴더에 넣으면 인용 페이지를 볼 수 있습니다)" % manual_dir
    return "매뉴얼 %d종 연결됨" % len(files)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="매뉴얼 페이지 렌더 확인")
    ap.add_argument("--dir", default="manuals")
    ap.add_argument("--cite", help='예: "im_e_sievers-m9-manual_dlm_77020-02.pdf p.413 (Appendix F)"')
    ap.add_argument("--out", default="page.png")
    args = ap.parse_args()

    print(status(args.dir))
    for f in list_manuals(args.dir):
        print("  %-56s %d p" % (f, page_count(os.path.join(args.dir, f))))

    if args.cite:
        fn, pg, sec = parse_cite(args.cite)
        p = resolve(fn, args.dir)
        print("\n인용: %s p.%s (%s)" % (fn, pg, sec))
        print("경로: %s" % p)
        png = render_page(p, pg)
        if png:
            open(args.out, "wb").write(png)
            print("저장: %s (%d bytes)" % (args.out, len(png)))
        else:
            print("렌더 실패")
