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


# ── temperature 를 받지 않는 모델 (패치 38) ─────────────────
# GPT-5 계열·o 계열(추론형)은 temperature 기본값(1) 말고는 거절한다 —
# 0 을 보내면 400 Bad Request. 모델을 GPT-5.5 로 바꾼 뒤 조치 순서·추측이
# 전부 "HTTP Error 400" 으로 떨어진 원인이 이것이었다.
#
# 이름으로 먼저 거르고, 이름이 사내 별칭(esg-… 등)이라 못 알아봐도 400
# 본문에 temperature 가 적혀 있으면 빼고 한 번 더 보낸다. 한 번 거절된
# 모델은 기억해 두고 다음부터는 처음부터 뺀다.
#
# 재현성(temperature 0)은 이 모델들에서 보장되지 않는다. 평가 수치를
# 이 모델로 다시 잴 때는 그 점을 적는다.
_NO_TEMP_RE = re.compile(r"(^|[^a-z])(gpt-5|o1|o3|o4)", re.I)
_NO_TEMP = set()
if os.environ.get("COPILOT_LLM_NO_TEMPERATURE", "").strip() in ("1", "true", "yes"):
    _NO_TEMP.add("*")


def _temp_ok(model):
    return not ("*" in _NO_TEMP or model in _NO_TEMP
                or _NO_TEMP_RE.search(str(model or "")))


def _post_chat(url, payload, headers, timeout, model):
    """chat/completions 호출. temperature 거절이면 빼고 한 번 더.

    실패하면 응답 본문 앞부분을 오류에 싣는다. 'HTTP Error 400: Bad
    Request' 만으로는 모델 이름이 틀렸는지, 파라미터가 틀렸는지 모른다.
    """
    body = dict(payload)
    if _temp_ok(model):
        body["temperature"] = 0
    for attempt in (1, 2):
        try:
            return _post(url, body, headers, timeout)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")
            except Exception:                               # noqa: BLE001
                detail = ""
            if attempt == 1 and e.code == 400 and "temperature" in body \
                    and "temperature" in detail.lower():
                _NO_TEMP.add(model)
                body.pop("temperature", None)
                sys.stderr.write("[advisor] %s 는 temperature 를 받지 않음 — "
                                 "빼고 재시도\n" % model)
                continue
            raise AdvisorError("모델 호출 실패 HTTP %s (%s): %s"
                               % (e.code, model, re.sub(r"\s+", " ", detail)[:240]))


def _chat_azure(messages, timeout):
    dep = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", config.LLM_MODEL)
    if not config.AOAI_ENDPOINT or not config.AOAI_API_KEY:
        raise AdvisorError("AZURE_OPENAI_ENDPOINT / API_KEY 가 없습니다.")
    url = "%s/openai/deployments/%s/chat/completions?api-version=%s" % (
        config.AOAI_ENDPOINT, dep, config.AOAI_API_VERSION)
    d = _post_chat(url, {"messages": messages},
                   {"Content-Type": "application/json",
                    "api-key": config.AOAI_API_KEY}, timeout, dep)
    return d["choices"][0]["message"]["content"]


def _chat_openai(messages, timeout):
    if not config.OPENAI_API_KEY:
        raise AdvisorError("OPENAI_API_KEY 가 없습니다.")
    d = _post_chat(config.OPENAI_BASE_URL + "/chat/completions",
                   {"model": config.LLM_MODEL, "messages": messages},
                   {"Content-Type": "application/json",
                    "Authorization": "Bearer %s" % config.OPENAI_API_KEY},
                   timeout, config.LLM_MODEL)
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
# 이력이 있을 때만 덧붙이는 규칙.
#
# 매뉴얼은 일반적인 경우를 쓰고, 현장은 그 배관 그 판넬의 사정이 있다.
# "매뉴얼대로 했는데 아니었다" 가 기록된 건은 매뉴얼 근거보다 먼저
# 확인해야 한다. 그렇지 않으면 이미 한 번 헛수고한 경로를 다시 밟는다.
HISTORY_RULES = """
현장 이력 사용 규칙:
- "매뉴얼 대조: 불일치" 인 이력이 있으면, 매뉴얼 근거가 지시하는 조치를
  첫 단계로 쓰지 마십시오. 그 이력의 실제 원인을 먼저 확인 항목으로
  올리십시오. 매뉴얼대로 해서 이미 실패한 기록이기 때문입니다.
- 이력을 근거로 쓴 단계는 [H1] 처럼 이력 번호를 표기하십시오.
- 이력에 적힌 것만 쓰십시오. 이력에 없는 원인이나 조치를 이력인 것처럼
  쓰지 마십시오.
- 다른 태그의 이력이라도 같은 기종에서 같은 증상이 있었다면 유용합니다.
  다만 어느 태그의 기록인지 단계 본문에 밝히십시오."""


def _history_block(history):
    """LLM 에 넘길 이력 절. 근거 번호와 겹치지 않게 H 접두를 쓴다."""
    if not history:
        return ""
    out = ["", "현장 이력 (같은 태그·같은 기종의 유사 증상):"]
    for i, h in enumerate(history, 1):
        out.append("[H%d] %s · %s · %s | 매뉴얼 대조: %s" % (
            i, h.get("date", ""), h.get("tag", ""),
            h.get("symptom", ""), h.get("manual_match", "")))
        for label, key in (("처음 조치", "first_action"),
                           ("실제 원인", "root_cause"),
                           ("최종 조치", "action_taken")):
            if h.get(key):
                out.append("     %s: %s" % (label, h[key]))
    return "\n".join(out)


def _prompt(tag, alarm, evidence, history=None):
    lines = ["설비 태그: %s" % (tag or "-"),
             "현장 증상: %s" % (alarm or "-"), "",
             "근거 (관련도 순, 1번이 가장 가까움):"]
    for i, e in enumerate(evidence[:MAX_EVIDENCE], 1):
        lines.append("[%d] %s — %s" % (
            i, e.get("title", ""),
            re.sub(r"\s+", " ", e.get("text", ""))[:MAX_CHARS]))
    blk = _history_block(history)
    if blk:
        lines.append(blk)
        lines.append(HISTORY_RULES)
    return "\n".join(lines)


def _parse(raw):
    t = (raw or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise AdvisorError("JSON 을 찾지 못했습니다: %s" % t[:120])
    return json.loads(t[i:j + 1])


def generate(tag, alarm, evidence, timeout=120, history=None):
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
              {"role": "user",
               "content": _prompt(tag, alarm, evidence, history)}],
             timeout)
    data = _parse(raw)

    used = evidence[:MAX_EVIDENCE]
    by_num = {str(i): e["id"] for i, e in enumerate(used, 1)}
    by_id = {e["id"]: e["id"] for e in used}
    by_title = {(e.get("title") or "").strip().lower(): e["id"]
                for e in used if e.get("title")}
    cite = {e["id"]: e.get("cite", "") for e in used}

    # 이력 인용(H1, H2…). 근거 목록과 같은 원칙이다 — 실재하는 것만
    # 통과시킨다. 없는 이력 번호를 쓴 단계는 근거와 똑같이 버려진다.
    hist_used = list(history or [])[:MAX_EVIDENCE]
    by_hist = {}
    for i, h in enumerate(hist_used, 1):
        hid = "H:%s" % (h.get("wo_no") or i)
        by_hist["h%d" % i] = hid
        cite[hid] = "현장 이력 %s (%s)" % (h.get("wo_no", ""), h.get("date", ""))

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
        if t.lower() in by_hist:
            return by_hist[t.lower()]
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


_GUESS_SYSTEM = """당신은 플랜트 계장제어 정비를 지원합니다.

지금은 **벤더 매뉴얼에서 근거를 찾지 못한 상황**입니다. 그래서 당신의
답은 근거가 아니라 추측입니다. 그 사실을 감추지 마십시오.

규칙:
- 매뉴얼에 이렇게 적혀 있다는 식으로 말하지 마십시오. 근거가 없습니다.
- 문서명·페이지·코드번호를 지어내지 마십시오. 하나라도 지어내면 답 전체를 버립니다.
- 확실한 것처럼 쓰지 마십시오. "~일 수 있습니다", "~인지 확인이 필요합니다" 로 씁니다.
- 계장 정비원이 **현장에서 직접 확인할 수 있는 것**을 우선하십시오.
- 모르면 모른다고 쓰십시오. 채우려고 늘리지 마십시오.

JSON 으로만 답하십시오. 다른 말은 붙이지 마십시오.
{"causes": ["가능한 원인 1", "가능한 원인 2"],
 "checks": ["현장에서 확인할 것 1", "확인할 것 2"],
 "ask_vendor": "벤더에 문의한다면 무엇을 물어야 하는지 한 문장"}

causes 와 checks 는 각각 최대 3개입니다."""


def guess(tag, alarm, device="", service="", timeout=None):
    """
    근거를 찾지 못했을 때의 **추측**. 조치가 아니다.

    이 함수는 거절(abstain) 판정에서만 호출한다. 근거가 있는 조회에
    붙으면 사용자가 근거 있는 답과 추측을 구분하지 못하게 되고, 그러면
    "근거 없이 답하지 않는다" 는 이 도구의 전제가 무너진다.

    반환값은 조치 배열에 넣지 않는다. 별도 필드로 내보내 화면이 접힌
    상태로 따로 보여주고, 4D 리포트에는 싣지 않는다. 리포트는 조치
    기록이므로 추측이 들어갈 자리가 아니다.

    반환: (추측 dict 또는 None, 안 나온 사유 문자열)

    **사유를 함께 돌려준다.** 조용히 None 을 반환하면 왜 안 나왔는지
    알 수 없다. 이 프로젝트는 검색 강등도 화면에 사유를 남긴다 — 안 되는
    것보다 왜 안 되는지 모르는 것이 더 나쁘다.
    """
    if not getattr(config, "GUESS_ON_ABSTAIN", True):
        return None, "COPILOT_GUESS=off"
    fn = _CHAT.get(config.LLM_PROVIDER)
    if fn is None or config.LLM_PROVIDER == "off":
        return None, "LLM 제공자 없음 (%s)" % config.LLM_PROVIDER
    timeout = timeout or getattr(config, "GUESS_TIMEOUT", 60)

    who = " · ".join(x for x in (device, service) if x)
    user = "태그: %s\n기종·용도: %s\n증상: %s" % (tag, who or "(미상)", alarm)
    raw = ""
    try:
        kw = {}
        if config.LLM_PROVIDER == "ollama":
            kw = {"num_predict": getattr(config, "GUESS_NUM_PREDICT", 400)}
        raw = fn([{"role": "system", "content": _GUESS_SYSTEM},
                  {"role": "user", "content": user}], timeout, **kw)
    except Exception as e:                                  # noqa: BLE001
        return None, "모델 호출 실패 — %s: %s" % (type(e).__name__, str(e)[:90])

    try:
        d = _parse(raw)
    except Exception:                                       # noqa: BLE001
        return None, "JSON 형식이 아님 — 모델 응답 앞부분: %s" % \
            re.sub(r"\s+", " ", raw or "")[:120]

    def clean(xs):
        out = []
        for x in (xs or [])[:3]:
            t = re.sub(r"\s+", " ", str(x)).strip()
            if 4 <= len(t) <= 200:
                out.append(t)
        return out

    causes, checks = clean(d.get("causes")), clean(d.get("checks"))
    if not causes and not checks:
        return None, "내용이 비어 있음 (causes·checks 모두 없음)"

    # 근거가 없는데 근거를 인용한 것처럼 쓰면 통째로 버린다. 추측이라고
    # 밝혀 놓아도, 문서명이나 페이지가 섞이면 사용자는 근거로 읽는다.
    joined = " ".join(causes + checks)
    m = re.search(r"\.pdf|\bp\.\s*\d|매뉴얼에\s*(따르면|의하면)|\[\d+\]", joined)
    if m:
        return None, "없는 근거를 인용해 폐기 — '%s' 부근" % m.group(0)

    return {
        "kind": "guess",
        "basis": "model_only",
        "label": "모델 추측 · 문서 근거 아님",
        "warning": "이 내용은 문서 근거가 없습니다. 조치 근거로 쓰지 마십시오.",
        "causes": causes,
        "checks": checks,
        "ask_vendor": re.sub(r"\s+", " ", str(d.get("ask_vendor") or "")).strip()[:200],
    }, ""


_FREE_SYSTEM = """당신은 플랜트 계장제어 정비를 지원합니다.

지금은 **문서에서 근거를 찾지 못한 상황**이고, 사용자가 **자유 모드를
켠 상태**입니다 — 이 답변 자체가 자유 모드에서 생성되고 있습니다.
누가 지금 모드를 물으면 "자유 모드가 켜져 있다" 고 답하십시오.
일반 지식으로 답하되, 다음을 지키십시오.

- 이 도구의 조회 결과 — 특정 태그의 판넬 위치, 인터락 조건, 매뉴얼
  페이지, 코드번호 — 를 지어내지 마십시오. 그런 것을 물으면 해당 조회
  기능으로 확인하라고 안내하십시오.
- 문서명·페이지·코드번호를 지어내지 마십시오.
- 확실한 것처럼 단정하지 말고, 일반적으로 알려진 내용임을 밝히십시오.
- 이 답변은 아무것도 실행하지 않습니다 — "조회하겠습니다" 처럼 실행을
  약속하는 문장을 쓰지 마십시오.
- 노래·게임·역할극 등 정비 도구 범위 밖의 요청은 할 수 있는 척하지
  말고 한 줄로 사양하십시오.
- 3~5문장으로 짧게. 모르면 모른다고 하십시오.

한국어 평문으로만 답하십시오. JSON 이나 머리말을 붙이지 마십시오."""


def free_reply(question, tag="", service="", timeout=None):
    """
    자유 모드에서 문서 근거로 답하지 못했을 때의 모델 답변.

    근거를 찾지 못한 사실을 지우지 않고 **그 뒤에 덧붙이는** 용도다.
    사용자가 자유 모드를 켠 뜻은 "근거가 없어도 참고할 것을 달라" 이지
    "근거 없음을 감춰 달라" 가 아니다.

    실패하면 빈 문자열을 돌려준다 — 없는 채로 가는 편이 낫다.
    """
    fn = _CHAT.get(config.LLM_PROVIDER)
    if fn is None or config.LLM_PROVIDER == "off":
        return ""
    timeout = timeout or getattr(config, "GUESS_TIMEOUT", 60)
    who = " · ".join(x for x in (tag, service) if x)
    user = "질문: %s" % question
    if who:
        user += "\n(화면에서 보고 있는 설비: %s)" % who
    try:
        kw = {}
        if config.LLM_PROVIDER == "ollama":
            kw = {"num_predict": getattr(config, "GUESS_NUM_PREDICT", 400)}
        raw = fn([{"role": "system", "content": _FREE_SYSTEM},
                  {"role": "user", "content": user}], timeout, **kw)
    except Exception:                                       # noqa: BLE001
        return ""
    out = re.sub(r"\s+", " ", (raw or "")).strip()
    # 없는 근거를 인용하면 버린다. 추측과 같은 기준이다.
    if re.search(r"\.pdf|\bp\.\s*\d|매뉴얼에\s*(따르면|의하면)|\[\d+\]", out):
        return ""
    if len(out) < 10 or len(out) > 1200:
        return ""
    return out


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
