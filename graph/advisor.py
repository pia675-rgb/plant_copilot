#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
advisor.py — 조치 순서 생성 (근거 ID 검증 포함)

검색이 찾아온 근거를 **정비원이 따라갈 수 있는 순서**로 바꾼다.
지금까지는 근거 5건에 번호만 붙여 나열했는데, 그건 조치 순서가
아니다. "Acid Motor / Acid container / Acid Valve" 를 나란히 놓으면
무엇을 먼저 확인해야 하는지 알 수 없다.

## 환각을 막는 방식

이 계층은 안전과 직결되므로 LLM 을 자유롭게 두지 않는다.

1. **근거 밖의 내용을 쓰지 못한다.** 프롬프트에 근거만 넣고, 각
   단계는 반드시 근거 ID 를 인용하게 한다.
2. **인용 ID 를 코드로 검증한다.** 검색 결과에 없는 ID 를 단 단계는
   버린다. 모델이 지어낸 근거를 화면까지 보내지 않기 위해서다.
3. **남는 단계가 없으면 템플릿으로 되돌아간다.** LLM 이 실패했을 때
   빈 화면이나 근거 없는 조치를 보여주는 것보다 낫다.
4. **temperature 0.** 같은 질의에 같은 조치가 나와야 평가가 성립한다.

거절(abstain) 경로에서는 호출되지 않는다. 근거가 부족하다고 판정한
뒤에 조치를 만들면 판정이 의미가 없어진다.

## 제공자

    COPILOT_PROVIDER = ollama | azure | openai | off      (기본 ollama)
    COPILOT_MODEL    = 모델 이름 (ollama 기본 qwen2.5:7b-instruct)

off 이면 LLM 없이 템플릿만 쓴다. 임베딩 제공자와 별개로 설정한다 —
임베딩은 사내 API 로 가고 조치 생성은 로컬로 두는 구성이 가능하다.
"""

import json
import os
import time
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

MAX_EVIDENCE = 6          # 프롬프트에 넣을 근거 수
MAX_CHARS = 700           # 근거 하나당 본문 길이 상한

SYSTEM = """당신은 플랜트 계장제어 정비를 지원합니다.

주어진 근거만 사용해 정비원이 순서대로 따라갈 수 있는 확인 절차를 만드십시오.

가장 중요한 규칙:
- 근거는 관련도 순으로 정렬되어 있습니다. 1번 근거가 현장 증상과 가장
  가깝습니다. 1번을 반드시 다루고, 그것을 중심에 두십시오.
- 현장 증상과 관련 없는 근거는 **쓰지 마십시오**. 검색이 함께 가져온
  것일 뿐 답이 아닐 수 있습니다. 쓸 근거가 1~2건뿐이면 단계도 1~2개만
  만드십시오. 개수를 채우려고 무관한 근거를 넣지 마십시오.
- 증상에 나온 대상(예: 산, 오존, UV 램프, 수지)과 다른 대상을 다루는
  근거는 제외하십시오.

그 밖의 규칙:
- 근거에 없는 내용을 쓰지 마십시오. 일반 상식이나 추측을 넣지 마십시오.
- 각 단계에 사용한 근거를 **번호로** 표기하십시오. 예: [1], [2]
- 쉬운 것부터, 안전한 것부터, 확인이 빠른 것부터 배치하십시오.
- 비슷한 근거가 여러 건이면 하나의 단계로 묶으십시오.
- 한국어로 쓰고, 각 단계는 정비원에게 말하듯 한두 문장으로 쓰십시오.
- 근거가 조치를 지시하지 않고 원인만 설명하는 경우가 많습니다. 이때는
  근거에 적힌 원인을 그대로 확인 항목으로 옮기십시오. 원인이 여러 개면
  모두 쓰십시오. 예를 들어 근거가 "셀 건조(측정액 없음) 또는 배선 단선"
  이라고 하면, 측정액 유무 확인과 배선 단선 확인을 각각 쓰십시오.
  근거에 없는 확인 방법을 새로 지어내지는 마십시오.
- 코드나 알람 이름만 되풀이하는 단계는 쓸모가 없습니다. "X 확인 — X 인지
  확인합니다" 같은 문장은 쓰지 마십시오. 제목과 본문에는 근거에 적힌
  구체적인 원인과 부위, 조건을 쓰십시오.

JSON만 출력하십시오. 설명이나 코드펜스를 붙이지 마십시오.
{"summary": "현장 증상을 다시 말하는 한 문장", "steps": [{"title": "짧은 제목",
 "detail": "정비원에게 하는 안내 한두 문장", "evidence": [1, 2]}]}
evidence 에는 위 근거 목록의 **번호만** 넣으십시오. 긴 문서 이름을 옮겨
적지 마십시오.
단계는 1~4개로 하십시오. 무관한 근거로 개수를 채우지 마십시오."""


class AdvisorError(RuntimeError):
    pass


# ── 제공자별 호출 ───────────────────────────────────────────
def _post(url, payload, headers, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url, timeout):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ── 모델 자동 해석 ──────────────────────────────────────────
# COPILOT_MODEL 에 적힌 모델이 그 노트북에 없으면 404 가 난다. 사람마다
# 받아둔 모델이 달라서 배치 파일에 이름을 박아두면 매번 깨진다. 설치된
# 목록을 보고 선호 순서대로 하나를 고른다. 고른 결과는 콘솔에 남긴다.
#
# 평가는 재현성이 있어야 하므로 COPILOT_MODEL_STRICT=1 을 주면 대체하지
# 않고 그대로 실패시킨다.
_PREFER = ("qwen2.5:7b-instruct", "qwen2.5:7b", "qwen2.5", "llama3.1", "llama3.2")
_resolved = None


def _installed_models(timeout=5):
    try:
        d = _get(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout)
        return [m.get("name", "") for m in (d.get("models") or [])]
    except Exception:                                       # noqa: BLE001
        return []


def _resolve_model():
    global _resolved
    if _resolved:
        return _resolved
    want = config.LLM_MODEL
    if os.environ.get("COPILOT_MODEL_STRICT", "").strip() == "1":
        _resolved = want
        return _resolved
    names = _installed_models()
    if not names or want in names:
        _resolved = want
        return _resolved
    pick = next((p for p in _PREFER if p in names), None)
    # 선호 목록에 없으면 임베딩 모델을 빼고 남는 첫 번째를 쓴다.
    pick = pick or next((n for n in names if "bge" not in n and "embed" not in n), None)
    if pick:
        print("[advisor] 모델 %s 없음 → %s 로 대체 (설치됨: %s)"
              % (want, pick, ", ".join(names)))
        _resolved = pick
    else:
        _resolved = want
    return _resolved


# ollama 는 기본 5분이 지나면 모델을 메모리에서 내린다. 시연 중 설명하는
# 사이에 내려가면 다음 조회에서 다시 올리느라 수십 초가 그대로 대기가 된다.
# COPILOT_KEEP_ALIVE 로 상주 시간을 바꾼다 (예: 30m, -1 은 무기한).
KEEP_ALIVE = os.environ.get("COPILOT_KEEP_ALIVE", "30m").strip() or "30m"


def _chat_ollama(messages, timeout, model=None, num_predict=None):
    opts = {"temperature": 0}
    if num_predict:
        # 생성 길이를 끊는다. 요약은 한두 문장이면 되는데 모델이 길게
        # 늘어놓으면 그만큼 그대로 대기 시간이 된다.
        opts["num_predict"] = int(num_predict)
    d = _post(config.OLLAMA_URL.rstrip("/") + "/api/chat",
              {"model": model or _resolve_model(), "messages": messages,
               "stream": False, "options": opts, "keep_alive": KEEP_ALIVE},
              {"Content-Type": "application/json"}, timeout)
    return d["message"]["content"]


def prewarm(timeout=180):
    """모델을 미리 올려둔다. 첫 조회에서 로딩 시간을 물지 않기 위함이다.

    반환: (성공 여부, 메시지). 실패해도 예외를 올리지 않는다 — 예열은
    편의 기능이라 서버 기동을 막으면 안 된다.
    """
    if config.LLM_PROVIDER != "ollama":
        return False, "ollama 가 아니라 예열하지 않습니다 (%s)" % config.LLM_PROVIDER
    model = _resolve_model()
    t0 = time.time()
    try:
        _post(config.OLLAMA_URL.rstrip("/") + "/api/chat",
              {"model": model, "messages": [{"role": "user", "content": "ping"}],
               "stream": False, "options": {"num_predict": 1},
               "keep_alive": KEEP_ALIVE},
              {"Content-Type": "application/json"}, timeout)
        return True, "%s 예열 완료 (%.1f초, 상주 %s)" % (model, time.time() - t0, KEEP_ALIVE)
    except Exception as e:                                  # noqa: BLE001
        return False, "%s 예열 실패 — %s: %s" % (model, type(e).__name__, str(e)[:120])


def _chat_azure(messages, timeout):
    dep = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", config.LLM_MODEL)
    if not config.AOAI_ENDPOINT or not config.AOAI_API_KEY:
        raise AdvisorError("AZURE_OPENAI_ENDPOINT / API_KEY 가 없습니다.")
    url = "%s/openai/deployments/%s/chat/completions?api-version=%s" % (
        config.AOAI_ENDPOINT, dep, config.AOAI_API_VERSION)
    d = _post(url, {"messages": messages, "temperature": 0},
              {"Content-Type": "application/json",
               "api-key": config.AOAI_API_KEY}, timeout)
    return d["choices"][0]["message"]["content"]


def _chat_openai(messages, timeout):
    if not config.OPENAI_API_KEY:
        raise AdvisorError("OPENAI_API_KEY 가 없습니다.")
    d = _post(config.OPENAI_BASE_URL + "/chat/completions",
              {"model": config.LLM_MODEL, "messages": messages,
               "temperature": 0},
              {"Content-Type": "application/json",
               "Authorization": "Bearer %s" % config.OPENAI_API_KEY}, timeout)
    return d["choices"][0]["message"]["content"]


_CHAT = {"ollama": _chat_ollama, "azure": _chat_azure, "openai": _chat_openai}


def available():
    """현재 제공자로 조치 생성이 가능한지."""
    if config.LLM_PROVIDER == "off":
        return False, "COPILOT_PROVIDER=off"
    fn = _CHAT.get(config.LLM_PROVIDER)
    if fn is None:
        return False, "알 수 없는 제공자: %s" % config.LLM_PROVIDER
    try:
        fn([{"role": "user", "content": "ping"}], timeout=20)
        model = _resolve_model() if config.LLM_PROVIDER == "ollama" else config.LLM_MODEL
        return True, "%s/%s" % (config.LLM_PROVIDER, model)
    except Exception as e:                                  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:120])


# ── 생성 ────────────────────────────────────────────────────
def _prompt(tag, alarm, evidence):
    lines = ["설비 태그: %s" % (tag or "-"),
             "현장 증상: %s" % (alarm or "-"), "",
             "근거 (관련도 순, 1번이 가장 가까움):"]
    for i, e in enumerate(evidence[:MAX_EVIDENCE], 1):
        lines.append("[%d] %s — %s" % (
            i, e.get("title", ""),
            re.sub(r"\s+", " ", e.get("text", ""))[:MAX_CHARS]))
    return "\n".join(lines)


def _parse(raw):
    t = (raw or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise AdvisorError("JSON 을 찾지 못했습니다: %s" % t[:120])
    return json.loads(t[i:j + 1])


def generate(tag, alarm, evidence, timeout=120):
    """
    반환: {"summary", "steps":[{title, detail, evidence_ids}], "dropped": n}

    dropped 는 근거 ID 검증에서 버린 단계 수다. 0 이 아니면 모델이
    없는 근거를 인용했다는 뜻이므로 화면과 로그에 남긴다.
    """
    fn = _CHAT.get(config.LLM_PROVIDER)
    if fn is None or config.LLM_PROVIDER == "off":
        raise AdvisorError("조치 생성 제공자가 설정되지 않았습니다.")
    if not evidence:
        raise AdvisorError("근거가 없습니다.")

    raw = fn([{"role": "system", "content": SYSTEM},
              {"role": "user", "content": _prompt(tag, alarm, evidence)}],
             timeout)
    data = _parse(raw)

    used = evidence[:MAX_EVIDENCE]
    by_num = {str(i): e["id"] for i, e in enumerate(used, 1)}
    by_id = {e["id"]: e["id"] for e in used}
    by_title = {(e.get("title") or "").strip().lower(): e["id"]
                for e in used if e.get("title")}
    cite = {e["id"]: e.get("cite", "") for e in used}

    def resolve(v):
        """
        모델이 준 인용을 실제 근거 ID 로 되돌린다.

        번호로 인용하게 했지만 모델은 ID 나 제목을 그대로 쓰기도 한다.
        어느 형태든 **검색 결과 안에 실재하는 것만** 통과시킨다는 점이
        중요하다. 여기서 느슨해지는 것은 표기 형식이지 근거의 진위가
        아니다. 목록에 없는 것은 무엇으로 써도 통과하지 못한다.
        """
        if v is None:
            return None
        t = str(v).strip().strip("[]").strip()
        if t in by_num:
            return by_num[t]
        if t in by_id:
            return by_id[t]
        low = t.lower()
        if low in by_title:
            return by_title[low]
        m = re.match(r"^(\d+)", t)
        if m and m.group(1) in by_num:
            return by_num[m.group(1)]
        return None

    steps, dropped = [], 0
    for s in data.get("steps", []):
        raw = s.get("evidence") or s.get("evidence_ids") or s.get("ids") or []
        if not isinstance(raw, list):
            raw = [raw]
        ids, seen_id = [], set()
        for v in raw:
            rid = resolve(v)
            if rid and rid not in seen_id:
                seen_id.add(rid)
                ids.append(rid)
        if not ids:
            # 검색 결과에 없는 것을 인용했다 — 버린다.
            dropped += 1
            continue
        steps.append({
            "title": (s.get("title") or "").strip()[:60],
            "detail": (s.get("detail") or "").strip(),
            "evidence_ids": ids,
            "source": " · ".join(cite[i] for i in ids if cite.get(i)),
        })
    if not steps:
        raise AdvisorError("근거 ID 검증을 통과한 단계가 없습니다 "
                           "(버려진 단계 %d개)." % dropped)
    return {"summary": (data.get("summary") or "").strip(),
            "steps": steps[:5], "dropped": dropped}


# ── 근거 한국어 요약 (표시용) ────────────────────────────────
_SUM_SYSTEM = (
    "당신은 플랜트 계장 매뉴얼을 한국어로 짧게 요약합니다. "
    "주어진 영어 매뉴얼 발췌만 사용해 1~2문장으로 핵심만 한국어로 쓰십시오. "
    "추측하거나 근거에 없는 내용을 넣지 마십시오. "
    "요약문만 출력하고 따옴표·번호·제목은 붙이지 마십시오."
)


def summarize_ko(text, title="", timeout=None):
    """
    매뉴얼 근거 텍스트를 1~2문장 한국어로 요약.
    실패하면 빈 문자열을 반환한다 (호출 측에서 조용히 무시).

    화면 표시용 덤이므로, 꺼져 있거나 늦으면 없는 채로 간다 — 근거 원문과
    출처는 요약 없이도 그대로 나온다.
    """
    if not getattr(config, "SUMMARY_KO", True):
        return ""
    timeout = timeout or getattr(config, "SUMMARY_TIMEOUT", 20)
    fn = _CHAT.get(config.LLM_PROVIDER)
    if fn is None or config.LLM_PROVIDER == "off":
        return ""
    body = re.sub(r"\s+", " ", (text or "")).strip()[:600]
    if len(body) < 40:
        return ""
    user = "섹션: %s\n\n본문:\n%s" % (title or "(제목 없음)", body)
    try:
        kw = {}
        if config.LLM_PROVIDER == "ollama":
            kw = {"model": getattr(config, "SUMMARY_MODEL", None),
                  "num_predict": getattr(config, "SUMMARY_NUM_PREDICT", None)}
        raw = fn([{"role": "system", "content": _SUM_SYSTEM},
                  {"role": "user", "content": user}], timeout, **kw)
        out = (raw or "").strip()
        out = re.sub(r'^["“]|["”]$', "", out).strip()
        # 한 줄로 정리
        out = re.sub(r"\s+", " ", out)
        if len(out) < 8 or len(out) > 400:
            return ""
        return out
    except Exception:                                       # noqa: BLE001
        return ""


def main():
    import argparse
    from graph.app_graph import Copilot2
    ap = argparse.ArgumentParser(description="조치 생성 시험")
    ap.add_argument("--tag", default="AIT-4002")
    ap.add_argument("--alarm", default="산 잔량이 부족하다고 뜹니다")
    ap.add_argument("--mode", default="hybrid")
    ap.add_argument("--show-evidence", action="store_true",
                    help="LLM 에 넘긴 근거를 먼저 보여준다 — 오답 원인 구분용")
    args = ap.parse_args()

    ok, why = available()
    print("제공자: %s" % why)
    if not ok:
        return 1
    out = Copilot2(mode=args.mode).answer(tag=args.tag, alarm=args.alarm)
    if out["decision"] != "advise":
        print("판정 %s — 조치를 생성하지 않습니다." % out["decision"])
        return 0
    if args.show_evidence:
        print("\n=== LLM 에 넘긴 근거 (관련도 순) ===")
        for i, e in enumerate(out["evidence"][:MAX_EVIDENCE], 1):
            print("%d. [%s] %s" % (i, e["id"], e.get("title", "")))
    res = generate(args.tag, args.alarm, out["evidence"])
    print("\n요약: %s" % res["summary"])
    for i, s in enumerate(res["steps"], 1):
        print("\n%d. %s\n   %s\n   근거 %s" % (i, s["title"], s["detail"],
                                             ", ".join(s["evidence_ids"])))
    if res["dropped"]:
        print("\n※ 근거 ID 검증에서 %d개 단계를 버렸습니다." % res["dropped"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
