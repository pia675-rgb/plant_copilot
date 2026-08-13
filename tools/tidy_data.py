# -*- coding: utf-8 -*-
"""
tidy_data.py — data/ 를 업로드 자료만 남게 정리한다.

data/ 는 **사람이 넣는 문서만** 두는 자리다. 생성물이 섞여 있으면
"무엇을 넣어야 하나" 에 한 줄로 답할 수 없고, 생성물을 원본으로 착각해
엑셀에서 손으로 고쳤다가 재생성에서 잃는다. 임시 파일(엑셀을 열어 둔 채
생성기를 돌리면 생기는 확장자 없는 파일)도 여기서 걸러낸다.

지우기 전에 무엇을 어디로 보낼지 먼저 보여 준다. --apply 를 붙여야
실제로 옮기고 지운다.

    python -m tools.tidy_data           # 무엇을 할지 보기만
    python -m tools.tidy_data --apply   # 실제 정리
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

# derived/ 로 가야 할 생성물
GENERATED = ["PANEL_LOCATIONS.csv", "drawings_index.csv", "error_codes.json",
             "maintenance_history.json", "maintenance_history.xlsx",
             "eval_set.json"]

# tools/ 에 있어야 할 생성기
GENERATORS = ["make_arrangement.py", "make_interlock_list.py",
              "make_io_list.py", "make_tb_list.py"]

# 패치 26 에서 폐지된 부속 데이터 — 되살아나면 출처 추적이 흐려진다
ABOLISHED = ["TAG_ATTRIBUTES.xlsx"]

# data/ 를 파이썬 패키지처럼 만들던 흔적
STRAY = ["__init__.py", "__pycache__", "sources"]


def plan():
    d, der = config.DATA_DIR, config.DERIVED_DIR
    moves, deletes = [], []
    if not os.path.isdir(d):
        return moves, deletes

    for name in GENERATED:
        src = os.path.join(d, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(der, name)
        if os.path.isfile(dst):
            deletes.append((src, "derived/ 에 같은 이름이 이미 있음"))
        else:
            moves.append((src, dst))

    for name in GENERATORS:
        src = os.path.join(d, name)
        if os.path.isfile(src):
            where = "tools/ 에 있음" if os.path.isfile(
                os.path.join(os.path.dirname(der), "tools", name)) else "생성기"
            deletes.append((src, where))

    for name in ABOLISHED:
        for base in (d, der):
            src = os.path.join(base, name)
            if os.path.isfile(src):
                deletes.append((src, "패치 26 에서 폐지된 부속 데이터"))

    for name in STRAY:
        src = os.path.join(d, name)
        if os.path.exists(src):
            deletes.append((src, "자료가 아닌 것"))

    # 확장자 없는 파일 = 엑셀을 열어 둔 채 생성기를 돌린 잔재
    for name in sorted(os.listdir(d)):
        src = os.path.join(d, name)
        if os.path.isfile(src) and "." not in name:
            deletes.append((src, "엑셀 임시 파일"))
        elif name.startswith("~$"):
            deletes.append((src, "엑셀 임시 파일"))

    return moves, deletes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="실제로 옮기고 지운다 (없으면 보여 주기만)")
    a = ap.parse_args()

    moves, deletes = plan()
    if not moves and not deletes:
        print("data/ 에 정리할 것이 없습니다: %s" % config.DATA_DIR)
        return

    for src, dst in moves:
        print("옮김  %s → derived/" % os.path.basename(src))
    for src, why in deletes:
        print("지움  %s  (%s)" % (os.path.relpath(src, os.path.dirname(
            config.DATA_DIR)), why))

    if not a.apply:
        print("\n보여 주기만 했습니다. 실제로 정리하려면 --apply 를 붙이십시오.")
        return

    os.makedirs(config.DERIVED_DIR, exist_ok=True)
    for src, dst in moves:
        shutil.move(src, dst)
    for src, _why in deletes:
        if os.path.isdir(src):
            shutil.rmtree(src)
        else:
            os.remove(src)
    print("\n정리했습니다. python -m eval.selfcheck 로 확인하십시오.")


if __name__ == "__main__":
    main()
