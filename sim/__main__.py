# -*- coding: utf-8 -*-
"""
공정 모의 화면 — 명령줄

  # 캡처 이미지 → GPT-5.5 로 배치 추출 → 모의 화면 생성
  python -m sim --image 화면승인자료_NW.png --title "NW 탱크"

  # 모델 없이, 사람이 만든(또는 고친) 배치 JSON 으로 생성
  python -m sim --layout layout.json --title "NW 탱크" [--image 원본.png]

  # 리스트가 바뀐 뒤 다시 만들기 (배치는 그대로)
  python -m sim --rebuild <screen_id>

  python -m sim --list
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(prog="python -m sim")
    ap.add_argument("--image")
    ap.add_argument("--layout")
    ap.add_argument("--title", default="")
    ap.add_argument("--hint", default="", help="추출 모델에 줄 한 줄 설명")
    ap.add_argument("--rebuild")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    from sim import store
    if a.list:
        for m in store.list_screens():
            print("%-40s %s  심볼 %s  경고 %s" % (m["id"], m.get("title", ""),
                  (m.get("stats") or {}).get("objects", "-"), m.get("warnings", "-")))
        return
    if a.rebuild:
        m = store.build(a.rebuild)
        print("[sim] 재생성 %s — %s" % (a.rebuild, m["stats"]))
        print("      %s" % store.path(a.rebuild, "screen.html"))
        return

    img = open(a.image, "rb").read() if a.image else None
    title = a.title or os.path.splitext(os.path.basename(a.image or a.layout or "screen"))[0]
    if a.layout:
        from sim.extract import sanitize, image_size
        raw = json.load(open(a.layout, encoding="utf-8"))
        w, h = image_size(img) if img else ((raw.get("source") or {}).get("width"),
                                            (raw.get("source") or {}).get("height"))
        layout, warns = sanitize(raw, w, h, extractor=(raw.get("source") or {})
                                 .get("extractor") or "manual")
    elif img:
        from sim.extract import extract_layout
        layout, warns, usage = extract_layout(img, a.image, a.hint)
        print("[sim] 추출 완료 — 심볼 %d, 토큰 %s" % (len(layout["objects"]), usage))
    else:
        ap.error("--image 또는 --layout 이 필요합니다")
    for w in warns:
        print("[sim] 배치 경고:", w)
    sid = store.create(title, img, os.path.basename(a.image or "screen.png"),
                       layout, warns, (layout.get("source") or {}).get("extractor"))
    m = store.build(sid)
    print("[sim] 생성 %s — %s" % (sid, m["stats"]))
    for w in m["warnings"]:
        print("   경고:", w)
    for x in m["assumptions"]:
        print("   가정:", x)
    print("      %s" % store.path(sid, "screen.html"))


if __name__ == "__main__":
    main()
