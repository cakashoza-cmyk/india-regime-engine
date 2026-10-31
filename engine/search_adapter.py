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


def policy_language(job: str) -> dict:
    from datetime import date
    my = date.today().strftime("%B %Y")
    q = QUERIES[job].format(my=my)
    results = search(q)
    results = sorted(results, key=lambda r: (-(r.get("authority") or 0), -(r.get("rerank_score") or 0)))
    if not results:
        return {"query": q, "stance": None, "error": "no search results"}
    top = results[0]
    try:
        page = fetch(top["url"]).get("content", "")[:12000]
    except Exception as e:  # noqa: BLE001
        page = top.get("summary", "")
    out = chat_json(
        "Classify RBI policy language. Reply JSON {stance: one of tightening|neutral|accommodative|withdrawal_of_accommodation|unknown, "
        "tone: hawkish|neutral|dovish|unknown, quote: exact sentence from the text supporting it, meeting_date: as stated or null}. "
        "Do not output any numbers you did not read verbatim. If unsure use unknown.",
        f"Source: {top['url']}\n\n{page}")
    stance = out.get("stance")
    if stance == "withdrawal_of_accommodation":
        stance = "tightening"
    return {"query": q, "source_url": top["url"], "title": top.get("title"), "stance": stance if stance != "unknown" else None,
            "tone": out.get("tone"), "quote": out.get("quote"), "meeting_date": out.get("meeting_date"),
            "evidence": "ai-language", "error": None if stance not in (None, "unknown") else "stance unknown"}


OFFICIAL = ("rbi.org.in", "mospi.gov.in", "pib.gov.in")
NAMES = {"cpi_headline": "CPI inflation", "cpi_core": "core CPI inflation", "food_inflation": "food inflation CFPI",
         "iip_yoy": "IIP growth", "gdp_yoy": "GDP growth", "gst_yoy": "GST collections growth",
         "credit_growth": "bank credit growth", "capacity_util": "OBICUS capacity utilisation"}


def get_indicator_via_deepseek(indicator: str, when: str, numeric: bool = True) -> dict:
    """Spec section 5. Returns a raw payload; caller stores it with is_verified=False."""
    name = NAMES.get(indicator, indicator)
    base = f"{name} India {when} actual official"
    hits, errors = [], []
    for site in OFFICIAL + (None,):
        q = (f"site:{site} " + base if site else base)[:128]
        try:
            hits = search(q, count=5)  # spec bug fixed: count, not max_results
        except Exception as e:  # noqa: BLE001
            errors.append(f"search {q!r}: {e}")
            continue
        off = [r for r in hits if any(d in r.get("url", "") for d in OFFICIAL)]
        if off:
            hits = off
            break
        if site is None and not numeric and hits:
            hits = hits[:1]  # language indicators may use top result
            break
        hits = []
    if not hits:
        return {"indicator": indicator, "value": None, "error": "; ".join(errors) or "no official-domain result", "evidence": "ai"}
    top = hits[0]
    page = fetch(top["url"])
    out = chat_json(
        "Extract one Indian macro data point from an official page. Reply JSON {value: number|null, unit, release_date, "
        "reference_period, prior: number|null, context: one verbatim line}. Use null if the number is not explicitly in the text.",
        f"Indicator: {name}\nSource: {top['url']}\n\n{(page.get('content') or '')[:3000]}")
    return {"indicator": indicator, "value": out.get("value"), "prior": out.get("prior"), "unit": out.get("unit"),
            "as_of": out.get("release_date"), "reference_period": out.get("reference_period"), "context": out.get("context"),
            "source_url": top["url"], "fetch_via": page.get("via", "deepseek-fetch"), "evidence": "ai-unverified",
            "error": None if out.get("value") is not None else "value not found on page"}
