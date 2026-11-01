// Lending Radar fetch worker: generates the v8-lean credit note in-Worker (DeepSeek), stores in KV, returns JSON.
// Secrets: GH_TOKEN, DEEPSEEK_API_KEY. Vars: REPO, ALLOW_ORIGIN, SITE. KV: RL (rate limits + notes + industry cache).
const SYSTEM = "You are a credit head at an Indian bank with 20 years of SME lending, writing a note to a ground-level credit manager about one industry in one city.\nWrite ONE flowing note, not a form. Build from first principles: what the business physically is and how it turns inputs into cash, where value and cash sit\n(cost structure, pricing power, working-capital cycle, capex), what has broken or changed now, where the GROWTH opportunity is (which borrower types to pursue now),\nhow to grow safely (structure, covenants, what to take every month), and early-warning signs. Put guidance inline exactly where it follows from a fact\n(\"so when a proposal lands, check X; if Y, ask Z\"). Plain, confident language; short paragraphs; bold the key line of each paragraph with **...**.\nHARD RULES: (1) Use ONLY numbers that appear verbatim in the SOURCES or DATA PACK, and cite each with [n] (source number). Never compute, convert or estimate.\n(2) Where a needed figure is missing, write 'collect from customer'. (3) Separate local news from peer results from rating reports, and say when a source is old.\n(4) No generic filler; banned: monitor closely, headwinds, exercise caution, going forward, challenging environment, robust, navigate, landscape.\n(5) If sources say little about this city, say so plainly and lean on first principles plus peers. (6) Keep the note to 380-480 words, 4-5 headers. (7) Cite the official data pack as [D]. (8) Prefer Indian sources; if you use a foreign price, say which market it is and keep its unit. (9) Decide news_direction first. FINAL CALL = the data call, except OK becomes Caution when news_direction is Worse; the verdict must state the FINAL CALL, never a higher one; do not write the words 'FINAL CALL' and do not explain score bands or thresholds to the reader. Stay balanced: name who to pursue and who to avoid.\nReturn JSON: {\"verdict\":\"one line credit-head call\",\"title\":\"<city> <industry>: a note to the credit manager\",\n\"narrative\":[\"paragraph strings; headers start with '## ' ; bullets start with '- '\"],\n\"watch\":[[\"monitorable (frequency)\",\"trigger -> action\"] x 3-5],\"news_direction\":\"Worse|In line|Better\",\"news_why\":\"<=20 words\",\"sources_used\":[n]}";
const BANNED = ["monitor closely", "macro headwinds", "headwinds", "exercise caution", "going forward", "challenging environment", "robust", "remains to be seen", "cautious optimism", "mixed bag", "evolving situation", "stay vigilant", "navigate", "landscape", "in conclusion"];
const LOCAL_TERMS = {"GJ": "ઉદ્યોગ મંદી પેમેન્ટ", "TN": "தொழில் நெருக்கடி ஆர்டர்", "UP": "उद्योग मंदी भुगतान", "HR": "उद्योग मंदी भुगतान", "RJ": "उद्योग मंदी भुगतान", "MP": "उद्योग मंदी भुगतान", "BR": "उद्योग मंदी भुगतान", "HP": "उद्योग मंदी भुगतान", "DL": "उद्योग मंदी भुगतान", "MH": "उद्योग मंदी पेमेंट"};
const ID = /^[a-z0-9_]{2,40}$/, DS = "https://api.deepseek.com";
const istNow = () => new Date(Date.now() + 5.5 * 3600e3);
const istStr = d => d.toISOString().slice(0, 16).replace("T", " ") + " IST";
const ymd = d => d.toISOString().slice(0, 10);
const dateOf = r => { for (const k of ["published_date","published","date","publish_time","time","publishedDate"]) { const m = String(r[k] || "").match(/20\d\d-\d\d-\d\d/); if (m) return m[0]; } return null; };
const nums = t => (t.match(/\d[\d,]*(?:\.\d+)?/g) || []).map(n => n.replace(/,/g, ""));
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

async function ds(env, path, body, ms) {
  const r = await fetch(DS + path, { method: "POST", signal: AbortSignal.timeout(ms),
    headers: { Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error("deepseek " + path + " " + r.status);
  return r.json();
}
function stripHtml(h) {
  h = h.slice(0, 300000).replace(/<(script|style|noscript)[\s\S]*?<\/\1>/gi, " ").replace(/<[^>]+>/g, " ");
  return h.replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&#39;|&rsquo;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, " ");
}

async function build(env, state, cityId, indId) {
  const C = { search: 0, fetch: 0, chat: 0, plain_fetch_free: 0 }, t0 = Date.now();
  const radar = await (await fetch(`${env.SITE}/data/radar.json`, { cf: { cacheTtl: 3600 } })).json();
  const city = radar.cities.find(c => c.id === cityId), ind = radar.industries.find(i => i.id === indId), st = radar.states[state];
  if (!city || !ind || !st || city.state !== state) throw Object.assign(new Error("unknown pick"), { code: 400 });
  const e = radar.calls[`${state}|${ind.parent}`] || [null, null, null, null, null, []];
  const [base, score, nat, loc] = e, geo = radar.geo;
  const pack = [`Data-based call: ${(base || "unknown").toUpperCase()} score ${score} (national ${nat} x ${geo.weight_national} + ${st.name} ${loc} x ${geo.weight_local}). OK to lend at or above ${geo.ok_at_or_above}, Avoid below ${geo.avoid_below}.`]
    .concat(e[5].map(i => radar.reasons[i][0]));
  const short = ind.name.split(" (")[0].replace(" - ", " ").replace("&", "and"), c = city.name, lt = LOCAL_TERMS[state] || "उद्योग मंदी भुगतान";
  const now = istNow(), month = now.toLocaleString("en-US", { month: "long", timeZone: "UTC" });
  const search = async (q, n = 6) => { C.search++; try { return (await ds(env, "/v1/tools/search", { query: q.slice(0, 128), count: n, need_content: false }, 15000)).results || []; } catch { return []; } };
  const first = short.split(" ")[0];
  const qs = [`${c} ${short} industry news ${month} ${now.getUTCFullYear()}`, `${c} ${short} units orders payment closure ${now.getUTCFullYear()}`,
    `${c} ${ind.focus || short} ${lt}`, state === "GJ" ? `${c} ${first} ઉદ્યોગ સમાચાર` : `${c} ${first} उद्योग खबर`];
  // industry cache: KV, else Pages repo cache, else 2 searches (stored 30 days)
  const cacheP = (async () => {
    let ic = await env.RL.get(`ind:${indId}`, "json");
    if (!ic) { const r = await fetch(`${env.SITE}/data/cache/industry/${indId}.json`); if (r.ok) ic = await r.json(); }
    if (ic && (Date.now() - Date.parse(ic.fetched_at)) < 30 * 86400e3) return [ic.items, false];
    const items = [];
    const res = await Promise.all([["peer", `${short} listed companies India latest quarter results volume margin demand`], ["rating", `ICRA CARE CRISIL rating rationale ${short} India working capital`]]
      .map(async ([k, q]) => (await search(q)).slice(0, 4).map(r => ({ kind: k, url: r.url, title: r.title || "", date: dateOf(r), snip: (r.summary || r.snippet || "").slice(0, 500) }))));
    res.flat().filter(x => x.url).forEach(x => items.push(x));
    await env.RL.put(`ind:${indId}`, JSON.stringify({ fetched_at: new Date().toISOString(), industry: indId, items }), { expirationTtl: 31 * 86400 });
    return [items, true];
  })();
  const seen = new Set(), hits = [];
  for (const res of await Promise.all(qs.map(q => search(q)))) for (const r of res) if (r.url && !seen.has(r.url)) { seen.add(r.url); hits.push({ kind: "local", url: r.url, title: r.title || "", date: dateOf(r), snip: (r.summary || r.snippet || "").slice(0, 300) }); }
  const cut = ymd(new Date(Date.now() - 95 * 86400e3)), cl = c.toLowerCase();
  const rank = h => (((h.title + h.snip + h.url).toLowerCase().includes(cl)) ? 2 : 0) + ((h.date || "") >= cut ? 1 : 0) - (/\/(tag|category)\//.test(h.url) ? 2 : 0);
  const cands = hits.sort((a, b) => rank(b) - rank(a) || (b.date || "").localeCompare(a.date || "")).slice(0, 6);
  const get = async h => {
    let text = "", via = "plain-http", d2 = null;
    try { const r = await fetch(h.url, { headers: { "User-Agent": "Mozilla/5.0" }, signal: AbortSignal.timeout(8000) }); C.plain_fetch_free++; if (r.ok) text = stripHtml(await r.text()); } catch {}
    if (text.length < 400) {
      if (C.fetch >= 3) return null;
      C.fetch++; via = "deepseek";
      try { const r = await ds(env, "/v1/tools/fetch", { url: h.url }, 15000); text = (r.content || "").replace(/\s+/g, " "); d2 = r.published_date || r.date; } catch { return null; }
    }
    if (text.length < 400 || !text.toLowerCase().includes(cl)) return null;
    return { ...h, date: h.date || (String(d2 || "").match(/20\d\d-\d\d-\d\d/) || [null])[0] || "date unknown", via, text: text.slice(0, 2500) };
  };
  const docs = (await Promise.all(cands.map(get))).filter(Boolean).slice(0, 3);
  const [cached, refreshed] = await cacheP;
  for (const it of cached) docs.push({ ...it, date: it.date || "date unknown", via: "cache", text: it.snip });
  const srcs = docs.map((d, i) => `[${i + 1}] (${d.kind}; ${d.date}) ${d.title} ${d.url}\n${d.text}`).join("\n\n") || "(no sources fetched)";
  const corpus = new Set(nums(docs.map(d => d.text + " " + d.title).join(" ") + " " + pack.join(" ")));
  const user = `CITY: ${c}, ${st.name}\nINDUSTRY: ${ind.name}\nTODAY: ${ymd(now)}\n\nDATA PACK (official, verified):\n${pack.map(x => "- " + x).join("\n")}\n\nSOURCES:\n${srcs}`;
  C.chat++;
  const body = { model: "deepseek-flash", temperature: 0, response_format: { type: "json_object" }, max_tokens: 1200, thinking: { type: "disabled" },
    messages: [{ role: "system", content: SYSTEM }, { role: "user", content: user }] };
  let r = await ds(env, "/v1/chat/completions", body, 60000), txt = r.choices[0].message.content || "", usage = r.usage;
  if (!txt.trim()) { body.max_tokens = 2400; r = await ds(env, "/v1/chat/completions", body, 60000); txt = r.choices[0].message.content || ""; usage = r.usage; }
  let note = JSON.parse(txt);
  const probsOf = n => {
    const t = ((n.narrative || []).join(" ") + " " + (n.verdict || "") + " " + (n.watch || []).map(w => w.join(" ")).join(" ")).replace(/\[\d+\]/g, "");
    const bad = [...new Set(nums(t).filter(x => !corpus.has(x) && !(/^\d+$/.test(x) && +x >= 1 && +x <= 12)))].sort();
    const p = bad.length ? [`numbers not in any source: ${bad.slice(0, 20).join(", ")}`] : [];
    BANNED.filter(b => t.toLowerCase().includes(b)).forEach(b => p.push(`banned phrase '${b}'`));
    if (!((n.watch || []).length >= 3 && (n.watch || []).length <= 5)) p.push("watch list must have 3-5 items");
    return [p, bad];
  };
  let [probs, bad] = probsOf(note), stripped = false;
  if (bad.length) {
    const pat = new RegExp(`(?<![\\d.])(${bad.map(esc).join("|")})(?!\\d)`);
    note.narrative = (note.narrative || []).map(p => p.split(/(?<=[.!?])\s+/).filter(s => !pat.test(s.replace(/,/g, ""))).join(" ")).filter(Boolean);
    note.watch = (note.watch || []).filter(w => !pat.test(w.join(" ").replace(/,/g, "")));
    stripped = true; [probs, bad] = probsOf(note);
  }
  const call = base === "ok" && note.news_direction === "Worse" ? "caution" : base, used = new Set(note.sources_used || []);
  return { key: `${cityId}|${indId}`, state, city: cityId, ind: indId, version: "v6", version_engine: "v8-worker",
    generated_at: istStr(now), call, base_call: base, score, nudged_by_news: call !== base, verdict: note.verdict || "", title: note.title || "",
    narrative: (note.narrative || []).filter(x => !["##", "-", ""].includes(x.trim())), watch: note.watch || [],
    watch_note: "Trigger levels are policy suggestions (analytical framing), not data.", news_direction: note.news_direction, news_why: note.news_why,
    articles: docs.map((d, i) => ({ title: d.title || d.url, url: d.url, date: d.date, kind: d.kind, via: d.via, used: used.has(i + 1) })),
    pack, trace: { pass: !probs.length, problems: probs, synthesis_tries: 1, sentences_stripped: stripped },
    calls: C, industry_cache_refreshed: refreshed, chat_usage: usage, build_seconds: Math.round((Date.now() - t0) / 100) / 10,
    tier: "news_llm (unverified); numbers traced to fetched sources" };
}

async function commit(env, path, obj) {
  const u = `https://api.github.com/repos/${env.REPO}/contents/${path}`, h = { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "lending-radar-worker" };
  const bytes = new TextEncoder().encode(JSON.stringify(obj, null, 1)); let bin = ""; for (const b of bytes) bin += String.fromCharCode(b);
  for (let i = 0; i < 3; i++) {
    const g = await fetch(u, { headers: h }), sha = g.ok ? (await g.json()).sha : undefined;
    const p = await fetch(u, { method: "PUT", headers: h, body: JSON.stringify({ message: `note ${path} (worker)`, content: btoa(bin), sha }) });
    if (p.ok) return;
  }
}

export default {
  async fetch(req, env, ctx) {
    const origin = req.headers.get("Origin");
    const cors = { "Access-Control-Allow-Origin": env.ALLOW_ORIGIN, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type", Vary: "Origin" };
    const out = (code, body) => new Response(JSON.stringify(body), { status: code, headers: { ...cors, "Content-Type": "application/json" } });
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    const url = new URL(req.url);
    if (req.method === "GET" && url.pathname === "/index") {
      return new Response((await env.RL.get("idx")) || '{"notes":{}}', { headers: { ...cors, "Content-Type": "application/json", "Cache-Control": "max-age=15" } });
    }
    if (req.method === "GET" && url.pathname === "/note") {
      const s = url.searchParams, state = s.get("state") || "", city = s.get("city") || "", ind = s.get("ind") || "";
      if (!/^[A-Z]{2}$/.test(state) || !ID.test(city) || !ID.test(ind)) return out(400, { error: "bad input" });
      const n = await env.RL.get(`note:${state}_${city}_${ind}`);
      return n ? new Response(n, { headers: { ...cors, "Content-Type": "application/json" } }) : out(404, { error: "no note" });
    }
    if (origin !== env.ALLOW_ORIGIN) return out(403, { error: "origin not allowed" });
    if (req.method !== "POST") return out(405, { error: "POST only" });
    let b; try { b = await req.json(); } catch { return out(400, { error: "bad JSON" }); }
    const { state, city, ind } = b || {};
    if (!/^[A-Z]{2}$/.test(state || "") || !ID.test(city || "") || !ID.test(ind || "")) return out(400, { error: "bad input" });
    const pair = `pair:${state}|${city}|${ind}`, day = `day:${ymd(new Date())}`;
    if (await env.RL.get(pair)) return out(429, { error: "This pick was refreshed in the last 6 hours. Showing the saved note." });
    const used = parseInt((await env.RL.get(day)) || "0", 10);
    if (used >= 30) return out(429, { error: "Daily fetch limit (30) reached. Try tomorrow." });
    await env.RL.put(pair, "1", { expirationTtl: 6 * 3600 });
    await env.RL.put(day, String(used + 1), { expirationTtl: 2 * 86400 });
    let note;
    try { note = await build(env, state, city, ind); }
    catch (err) { await env.RL.delete(pair); return out(err.code || 502, { error: "Could not build the note: " + String(err.message).slice(0, 120) }); }
    const nk = `${state}_${city}_${ind}`;
    await env.RL.put(`note:${nk}`, JSON.stringify(note));
    if (note.call) { const idx = (await env.RL.get("idx", "json")) || { notes: {} };
      idx.notes[`${state}|${city}|${ind}`] = { call: note.call, base: note.base_call, score: note.score, at: note.generated_at };
      await env.RL.put("idx", JSON.stringify(idx)); }
    ctx.waitUntil(commit(env, `data/notes/${nk}.json`, note).catch(() => {}));
    return out(200, { ok: true, note });
  },
};
