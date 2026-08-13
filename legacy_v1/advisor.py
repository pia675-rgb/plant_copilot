#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
advisor.py — 조치 제안 생성 계층 (Ollama)

copilot_core 가 확정한 근거 위에서만 동작한다. 역할 분담은 다음과 같다.

    근거 검색·확정   copilot_core   결정론적. 같은 입력이면 같은 근거.
    조치 순서 생성   advisor        LLM. 근거를 재료로 점검 순서를 만든다.

LLM 은 원인을 새로 만들지 않는다. 제공된 근거 안에서 골라 순서를 정하고,
현장 이력이 매뉴얼과 어긋나면 그 점을 반영해 순서를 조정하는 것이 전부다.

모든 단계는 근거 ID 를 달아야 하며, 제공되지 않은 ID 를 인용한 단계는
출력에서 제거된다. 제거 건수는 hallucinated 로 보고되므로 그대로
환각 지표가 된다.

사용:
    python advisor.py --src demo_data --tag AIT-5001 --alarm "셀 단선"
    python advisor.py --src demo_data --tag AIT-5001 --alarm "셀 단선" --mock
    python advisor.py --selftest

준비:
    ollama pull qwen2.5:7b-instruct
    ollama serve
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from copilot_core import Copilot   # noqa: E402

# ── 모델 제공자 설정 ─────────────────────────────────────────
# 키는 코드에 적지 않는다. 환경변수로만 받는다.
#
#   ollama (기본)
#     OLLAMA_URL          기본 http://localhost:11434
#     COPILOT_MODEL       기본 qwen2.5:7b-instruct
#
#   azure — 사내 Azure OpenAI
#     COPILOT_PROVIDER=azure
#     AZURE_OPENAI_ENDPOINT      https://<리소스>.openai.azure.com
#     AZURE_OPENAI_API_KEY       발급받은 키
#     AZURE_OPENAI_DEPLOYMENT    배포(deployment) 이름
#     AZURE_OPENAI_API_VERSION   기본 2024-10-21
#
#   openai — OpenAI 호환 사내 게이트웨이 (Bearer 인증)
#     COPILOT_PROVIDER=openai
#     OPENAI_BASE_URL     https://gateway.example.com/v1
#     OPENAI_API_KEY      발급받은 키
#     COPILOT_MODEL       게이트웨이에 등록된 모델명
PROVIDER = os.environ.get("COPILOT_PROVIDER", "ollama").lower()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("COPILOT_MODEL", "qwen2.5:7b-instruct")

AZURE_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
AZURE_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

SYSTEM = """당신은 플랜트 계장 설비의 정비 지원 도구입니다.
아래 규칙을 어기면 출력은 폐기됩니다.

1. 제공된 근거에 없는 원인, 조치, 부품, 수치를 만들어내지 마십시오.
   추론으로 보충하지 말고, 근거에 있는 내용만 사용하십시오.
2. 모든 단계에 refs 를 답니다. refs 값은 제공된 근거의 id 또는 wo_no 와
   글자 그대로 일치해야 합니다. 새 ID를 만들지 마십시오.
3. 매뉴얼과 현장 이력이 다른 원인을 지목하면, 현장 이력을 우선 확인하도록
   순서를 조정하고 그 이유를 why 에 적으십시오. 다만 매뉴얼 근거를 삭제하지는
   마십시오.
4. 근거가 부족해 순서를 정할 수 없으면 insufficient 를 true 로 두고
   steps 를 비우십시오. 추측하지 마십시오.
5. 작업 지시가 아니라 점검 순서 제안입니다. 단정적 표현을 쓰지 마십시오.

JSON 만 출력하십시오. 코드펜스나 설명 문장을 붙이지 마십시오.

{
  "summary": "한 문장 판단",
  "steps": [
    {"order": 1, "action": "확인할 것", "why": "이 순서인 이유",
     "refs": ["근거 id"], "source": "manual 또는 history"}
  ],
  "cautions": ["주의할 점"],
  "insufficient": false
}"""


def build_context(a):
    """검색 결과를 LLM 입력용 근거 블록으로 변환한다."""
    L = ["[설비]"]
    i = a["instrument"] or {}
    L.append("태그 %s / %s %s / %s / 계통 %s"
             % (a["tag"], i.get("maker"), i.get("model"),
                i.get("service"), i.get("system")))
    if i.get("fault_mode"):
        L.append("결함 거동: %s" % i["fault_mode"])

    L.append("")
    L.append("[매뉴얼 근거]")
    if not a["manual"]:
        L.append("없음")
    for m in a["manual"]:
        L.append("- id: %s | %s | %s" % (m["id"], m["severity"], m["name"]))
        L.append("  설명: %s" % m["description"])
        if m["remedy"]:
            L.append("  매뉴얼 조치: %s" % m["remedy"])

    L.append("")
    L.append("[현장 이력]")
    if not a["history"]:
        L.append("없음")
    for h in a["history"]:
        L.append("- id: %s | %s | 태그 %s | 매뉴얼 일치도: %s"
                 % (h["wo_no"], h["date"], h["tag"], h["match"]))
        L.append("  실제 원인: %s" % h["root_cause"])
        L.append("  조치: %s (%d분)" % (h["action"], h["duration_min"]))

    c = a["comparison"]
    L.append("")
    L.append("[대비] %s" % c["note"])
    return "\n".join(L)


def allowed_refs(a):
    return {m["id"] for m in a["manual"]} | {h["wo_no"] for h in a["history"]}


def _post(url, payload, headers, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=dict(headers, **{"Content-Type": "application/json"}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 본문에 키가 실려 돌아오지는 않지만, 길이는 잘라 둔다
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("HTTP %s — %s" % (e.code, detail))


MESSAGES = lambda ctx: [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": ctx}]


def call_ollama(context, model=MODEL, timeout=120):
    body = _post(OLLAMA_URL + "/api/chat", {
        "model": model,
        "messages": MESSAGES(context),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }, {}, timeout)
    return body["message"]["content"]


def call_azure(context, model=None, timeout=120):
    """사내 Azure OpenAI.

    Azure 는 모델명이 아니라 배포(deployment) 이름으로 호출한다.
    AZURE_OPENAI_DEPLOYMENT 가 설정되어 있으면 그 값이 우선이며,
    --model 인자는 무시된다.
    """
    dep = AZURE_DEPLOYMENT or model
    if not (AZURE_ENDPOINT and AZURE_KEY and dep):
        raise RuntimeError(
            "Azure 설정이 비어 있습니다. AZURE_OPENAI_ENDPOINT / "
            "AZURE_OPENAI_API_KEY / AZURE_OPENAI_DEPLOYMENT 를 확인하십시오.")
    url = "%s/openai/deployments/%s/chat/completions?api-version=%s" % (
        AZURE_ENDPOINT, dep, AZURE_API_VERSION)
    body = _post(url, {
        "messages": MESSAGES(context),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }, {"api-key": AZURE_KEY}, timeout)
    return body["choices"][0]["message"]["content"]


def call_openai(context, model=MODEL, timeout=120):
    """OpenAI 호환 사내 게이트웨이."""
    if not (OPENAI_BASE and OPENAI_KEY):
        raise RuntimeError(
            "게이트웨이 설정이 비어 있습니다. OPENAI_BASE_URL / "
            "OPENAI_API_KEY 를 확인하십시오.")
    body = _post(OPENAI_BASE + "/chat/completions", {
        "model": model,
        "messages": MESSAGES(context),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }, {"Authorization": "Bearer " + OPENAI_KEY}, timeout)
    return body["choices"][0]["message"]["content"]


CALLERS = {"ollama": call_ollama, "azure": call_azure, "openai": call_openai}


def call_llm(context, provider=None, model=MODEL, timeout=120):
    p = (provider or PROVIDER).lower()
    fn = CALLERS.get(p)
    if not fn:
        raise RuntimeError("알 수 없는 제공자: %s (ollama / azure / openai)" % p)
    return fn(context, model=model, timeout=timeout)


def provider_status(provider=None):
    """설정 상태를 사람이 읽을 수 있게. 키 값은 절대 노출하지 않는다."""
    p = (provider or PROVIDER).lower()
    if p == "ollama":
        return "Ollama · %s · %s" % (OLLAMA_URL, MODEL)
    if p == "azure":
        if not (AZURE_ENDPOINT and AZURE_KEY and AZURE_DEPLOYMENT):
            return "Azure OpenAI · 설정 미완료 (엔드포인트/키/배포명 확인)"
        return "Azure OpenAI · %s · 배포 %s" % (AZURE_ENDPOINT, AZURE_DEPLOYMENT)
    if p == "openai":
        if not (OPENAI_BASE and OPENAI_KEY):
            return "사내 게이트웨이 · 설정 미완료 (BASE_URL/키 확인)"
        return "사내 게이트웨이 · %s · %s" % (OPENAI_BASE, MODEL)
    return "알 수 없는 제공자: %s" % p


def parse_json(text):
    """코드펜스나 앞뒤 문장이 붙어 나와도 JSON 을 건져낸다."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def validate(out, allowed):
    """근거 ID 를 검증한다. 검증 실패한 단계는 제거하고 건수를 보고한다."""
    report = {"steps_in": 0, "steps_out": 0, "hallucinated": 0,
              "bad_refs": [], "no_ref": 0, "parse_ok": out is not None}
    if not out:
        return None, report

    steps = out.get("steps") or []
    report["steps_in"] = len(steps)
    kept = []
    for s in steps:
        refs = [r for r in (s.get("refs") or []) if isinstance(r, str)]
        bad = [r for r in refs if r not in allowed]
        if not refs:
            report["no_ref"] += 1
            continue
        if bad:
            report["hallucinated"] += 1
            report["bad_refs"].extend(bad)
            continue
        kept.append(s)

    for n, s in enumerate(kept, 1):
        s["order"] = n
    out["steps"] = kept
    report["steps_out"] = len(kept)
    if not kept:
        out["insufficient"] = True
    return out, report


MOCK = {
    "summary": "배선 계통과 설정값 두 갈래가 있으며, 이 태그의 직전 이력은 설정값 쪽입니다.",
    "steps": [
        {"order": 1, "action": "셀 상수 설정값이 센서 사양과 일치하는지 확인",
         "why": "이 태그에서 동일 증상이 설정값 오입력으로 판명된 이력이 있습니다",
         "refs": ["WO-2025-019"], "source": "history"},
        {"order": 2, "action": "측정액이 셀에 채워져 있는지, 상류 밸브가 열려 있는지 확인",
         "why": "매뉴얼은 셀 건조를 원인 중 하나로 제시합니다",
         "refs": ["M300-Cond-Cell-open"], "source": "manual"},
        {"order": 3, "action": "모듈과 센서 사이 배선 및 단자 체결 상태 점검",
         "why": "입력 모듈이 단선을 진단 항목으로 제시합니다",
         "refs": ["ET200SP-6H"], "source": "manual"},
        {"order": 4, "action": "센서 케이블을 신품으로 교체",
         "why": "근거 없이 생성된 단계 (검증 테스트용)",
         "refs": ["M300-CABLE-REPLACE"], "source": "manual"},
    ],
    "cautions": ["작업 전 해당 채널의 전원 차단 절차를 따르십시오."],
    "insufficient": False,
}


def advise(cp, tag, alarm="", code=None, model=MODEL, mock=False,
           provider=None):
    a = cp.answer(tag=tag, alarm=alarm, code=code)
    ctx = build_context(a)
    allowed = allowed_refs(a)

    if not a["manual"] and not a["history"]:
        return a, {"summary": "이 설비에 연결된 근거 문서와 이력이 없습니다.",
                   "steps": [], "cautions": [], "insufficient": True}, \
            {"parse_ok": True, "steps_in": 0, "steps_out": 0,
             "hallucinated": 0, "bad_refs": [], "no_ref": 0, "skipped": True}

    if mock:
        raw = json.dumps(MOCK, ensure_ascii=False)
    else:
        try:
            raw = call_llm(ctx, provider=provider, model=model)
        except (urllib.error.URLError, OSError, KeyError, RuntimeError) as e:
            return a, None, {"error": "%s 호출 실패: %s"
                             % ((provider or PROVIDER), e)}

    out, report = validate(parse_json(raw), allowed)
    return a, out, report


def render(a, out, rep):
    L = ["=" * 70, "TAG %s" % a["tag"], ""]
    if out is None:
        L.append("조치 제안을 생성하지 못했습니다: %s" % rep.get("error", "응답 파싱 실패"))
        L.append("근거 목록은 copilot_core 출력으로 확인하십시오.")
        return "\n".join(L + ["=" * 70])

    L.append("[판단] %s" % out.get("summary", ""))
    L.append("")
    L.append("[점검 순서]")
    if out.get("insufficient") or not out.get("steps"):
        L.append("  근거가 부족하여 순서를 제안하지 않습니다.")
    for s in out.get("steps", []):
        L.append("  %d. %s" % (s["order"], s["action"]))
        L.append("     이유: %s" % s.get("why", ""))
        L.append("     근거: %s (%s)" % (", ".join(s.get("refs", [])),
                                       s.get("source", "")))
    if out.get("cautions"):
        L.append("")
        L.append("[주의]")
        for c in out["cautions"]:
            L.append("  · %s" % c)

    L.append("")
    L.append("[검증] 생성 %d단계 → 채택 %d단계 / 미검증 근거 인용 %d건 / 근거 누락 %d건"
             % (rep.get("steps_in", 0), rep.get("steps_out", 0),
                rep.get("hallucinated", 0), rep.get("no_ref", 0)))
    if rep.get("bad_refs"):
        L.append("       제거된 참조: %s" % ", ".join(sorted(set(rep["bad_refs"]))))
    L.append("")
    L.append("본 출력은 참고 정보이며 작업 지시가 아닙니다.")
    return "\n".join(L + ["=" * 70])


def selftest():
    """LLM 없이 검증 로직만 확인한다."""
    allowed = {"M300-Cond-Cell-open", "ET200SP-6H", "WO-2025-019"}
    out, rep = validate(json.loads(json.dumps(MOCK)), allowed)
    assert rep["steps_in"] == 4, rep
    assert rep["steps_out"] == 3, rep
    assert rep["hallucinated"] == 1, rep
    assert rep["bad_refs"] == ["M300-CABLE-REPLACE"], rep
    assert [s["order"] for s in out["steps"]] == [1, 2, 3]

    # 근거 없는 단계는 제거되고, 전부 제거되면 insufficient 로 전환
    bad = {"steps": [{"order": 1, "action": "x", "refs": []},
                     {"order": 2, "action": "y", "refs": ["없는ID"]}]}
    out2, rep2 = validate(bad, allowed)
    assert rep2["no_ref"] == 1 and rep2["hallucinated"] == 1
    assert out2["insufficient"] is True

    # 코드펜스가 붙은 응답 파싱
    assert parse_json('```json\n{"a":1}\n```') == {"a": 1}
    assert parse_json('설명입니다 {"a": 2} 끝') == {"a": 2}
    assert parse_json("망가진 출력") is None
    print("selftest OK — 검증 로직 정상")


def main():
    ap = argparse.ArgumentParser(description="조치 제안 생성 (Ollama)")
    ap.add_argument("--src", default="demo_data")
    ap.add_argument("--tag")
    ap.add_argument("--alarm", default="")
    ap.add_argument("--code", default=None)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--provider", default=None,
                    choices=["ollama", "azure", "openai"],
                    help="기본은 환경변수 COPILOT_PROVIDER (없으면 ollama)")
    ap.add_argument("--mock", action="store_true",
                    help="LLM 없이 고정 응답으로 검증 경로만 확인")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--status", action="store_true",
                    help="현재 모델 제공자 설정만 출력")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    if args.status:
        print(provider_status(args.provider))
        return
    if not args.tag:
        ap.error("--tag 가 필요합니다")

    cp = Copilot(args.src)
    a, out, rep = advise(cp, args.tag, args.alarm, args.code,
                         model=args.model, mock=args.mock,
                         provider=args.provider)
    if args.json:
        print(json.dumps({"answer": a, "advice": out, "report": rep},
                         ensure_ascii=False, indent=2))
    else:
        print(render(a, out, rep))


if __name__ == "__main__":
    main()
