"""Search/fetch adapter. Default: DeepSeek POST /v1/tools/search + /v1/tools/fetch (verified to exist
in api-docs.deepseek.com, Oct 2026). Language extraction via deepseek-chat (OpenAI-compatible).
Rule: structured APIs for numbers; LLM output here is LANGUAGE ONLY (stance/tone labels + quote)."""
from __future__ import annotations
import json, os, urllib.request

BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
QUERIES = {
    "rbi_stance": "RBI monetary policy statement {my} stance",
    "rbi_minutes_tone": "RBI MPC minutes {my} hawkish dovish",
}


def _post(path, body, timeout=60):
    key = os.environ["DEEPSEEK_API_KEY"]
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    # urlopen raises HTTPError on 4xx/5xx (raise_for_status equivalent); timeout=60
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def search(query, count=5):
    return _post("/v1/tools/search", {"query": query[:128], "count": count, "need_content": False}).get("results", [])


def plain_fetch(url):
    """Secondary: plain HTTP GET + tag strip (no DeepSeek billing)."""
    import re, html as h
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        t = r.read().decode("utf-8", "ignore")
    return {"title": "", "content": h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))), "via": "plain-http"}


def fetch(url):
    try:
        return _post("/v1/tools/fetch", {"url": url})
    except Exception as e:  # noqa: BLE001  4xx/5xx/timeout -> plain HTTP fallback
        out = plain_fetch(url)
        out["deepseek_error"] = str(e)
        return out


def chat_json(system, user):
    r = _post("/v1/chat/completions", {"model": "deepseek-chat", "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    return json.loads(r["choices"][0]["message"]["content"])


# ---- Spec 4.3 mandatory prompt (data extraction, never analysis)
SYSTEM_PROMPT = ("You are a data extraction tool, not an analyst. Do not infer numbers not explicitly in the text. "
                 "Return JSON only. If the value is not present, return null.")
OFFICIAL = ("rbi.org.in", "mospi.gov.in", "pib.gov.in")
STANCES = ("tightening", "neutral", "easing")


def normalise_stance(s):
    s = (s or "").lower()
    if "tighten" in s or "withdrawal" in s:
        return "tightening"
    if "accommodat" in s or "eas" in s:
        return "easing"
    return "neutral" if "neutral" in s else None


def verify_keywords(keywords, text):
    """Spec 4.2: every keyword the LLM cites must appear verbatim in the source text."""
    kws = [k for k in (keywords or []) if isinstance(k, str) and k.strip()]
    return bool(kws) and all(k.lower() in text.lower() for k in kws)


def policy_language(job: str) -> dict:
    """RBI stance as JSON {stance, keywords[]}; cross-check only (rule-based MPC parse stays primary).
    Always news_llm / unverified, never scored."""
    from datetime import date
    q = QUERIES[job].format(my=date.today().strftime("%B %Y"))
    results = sorted(search(q), key=lambda r: (-(r.get("authority") or 0), -(r.get("rerank_score") or 0)))
    if not results:
        return {"query": q, "stance": None, "error": "no search results"}
    top = results[0]
    try:
        page = fetch(top["url"]).get("content", "")[:12000]
    except Exception:  # noqa: BLE001
        page = top.get("summary", "")
    out = chat_json(SYSTEM_PROMPT,
        "From the text, return JSON {\"stance\": \"tightening\"|\"neutral\"|\"easing\"|null, \"keywords\": [exact phrases "
        f"copied from the text that state the stance]}}.\nSource: {top['url']}\n\n{page}")
    stance = out.get("stance") if out.get("stance") in STANCES else None
    ok = verify_keywords(out.get("keywords"), page)
    return {"query": q, "source_url": top["url"], "stance": stance if ok else None, "keywords": out.get("keywords"),
            "keywords_verbatim": ok, "evidence": "llm cross-check (display only)",
            "error": None if stance and ok else ("keywords not verbatim in source" if stance else "stance null")}


def extract_number(indicator: str, url: str, text: str) -> dict:
    """Spec 4.3 extraction call. Result is NEVER official_primary: official domain -> official_secondary,
    else news_llm; always is_verified=False and not scored until a structured source matches."""
    out = chat_json(SYSTEM_PROMPT,
        f"Extract: indicator={indicator}. Return JSON {{\"indicator\": str, \"value\": number|null, \"period\": str|null, "
        f"\"source_url\": str, \"is_official\": bool}}.\nSource: {url}\n\n{text[:12000]}")
    v = out.get("value")
    if v is not None and str(v) not in text:
        v = None  # not explicitly in the text
    tier = "official_secondary" if any(d in url for d in OFFICIAL) else "news_llm"
    return {"indicator": indicator, "value": v, "period": out.get("period"), "source_url": url,
            "source_tier": tier, "is_verified": False, "scored": False}


def consensus(values: list[dict], tol=0.1) -> dict:
    """Spec 4.2: consensus CPI/GDP needs >=2 independent sources (distinct domains) that agree."""
    from urllib.parse import urlparse
    by = {}
    for r in values:
        if r.get("value") is not None:
            by.setdefault(urlparse(r["source_url"]).netloc, float(r["value"]))
    vals = list(by.values())
    if len(vals) < 2:
        return {"value": None, "reason": "fewer than 2 independent sources", "sources": list(by)}
    if max(vals) - min(vals) > tol:
        return {"value": None, "reason": f"sources disagree {vals}", "sources": list(by)}
    return {"value": round(sum(vals) / len(vals), 2), "sources": list(by), "source_tier": "news_llm", "scored": False}


def commentary(topic: str, text: str, url: str) -> dict:
    """Capex commentary / earnings revisions: news_llm, display only, never scored."""
    out = chat_json(SYSTEM_PROMPT, f"Summarise {topic} statements as JSON {{\"points\": [exact sentences]}}.\nSource: {url}\n\n{text[:12000]}")
    return {"topic": topic, "points": out.get("points"), "source_url": url, "source_tier": "news_llm", "scored": False}


# Numeric indicators never go through DeepSeek (spec 4.4).
def get_indicator_via_deepseek(*a, **k):
    raise RuntimeError("disabled by spec 4.4: numeric indicators come only from structured sources")
