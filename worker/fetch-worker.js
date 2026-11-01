// Optional upgrade: Cloudflare Worker that triggers fetch-note.yml without a GitHub account for the user.
// Secrets/vars: GH_TOKEN (fine-grained PAT, this repo only, Actions: read & write), REPO="cakashoza-cmyk/india-regime-engine",
// ALLOW_ORIGIN="https://cakashoza-cmyk.github.io". KV binding: RL.
const ID = /^[a-z0-9_]{2,40}$/;
export default {
  async fetch(req, env) {
    const cors = { "Access-Control-Allow-Origin": env.ALLOW_ORIGIN, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
    const out = (code, body) => new Response(JSON.stringify(body), { status: code, headers: { ...cors, "Content-Type": "application/json" } });
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    if (req.method !== "POST") return out(405, { error: "POST only" });
    let b; try { b = await req.json(); } catch { return out(400, { error: "bad JSON" }); }
    const { state, city, ind } = b || {};
    if (!/^[A-Z]{2}$/.test(state || "") || !ID.test(city || "") || !ID.test(ind || "")) return out(400, { error: "bad input" });
    const pair = `pair:${state}|${city}|${ind}`, day = `day:${new Date().toISOString().slice(0, 10)}`;
    if (await env.RL.get(pair)) return out(429, { error: "This pick was refreshed in the last 6 hours. Showing the saved note." });
    const used = parseInt((await env.RL.get(day)) || "0", 10);
    if (used >= 30) return out(429, { error: "Daily fetch limit (30) reached. Try tomorrow." });
    const r = await fetch(`https://api.github.com/repos/${env.REPO}/actions/workflows/fetch-note.yml/dispatches`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "lending-radar-worker" },
      body: JSON.stringify({ ref: "main", inputs: { state, city, industry: ind } }) });
    if (r.status !== 204) return out(502, { error: `GitHub refused (${r.status})` });
    await env.RL.put(pair, "1", { expirationTtl: 6 * 3600 });
    await env.RL.put(day, String(used + 1), { expirationTtl: 2 * 86400 });
    return out(202, { ok: true, message: "Request sent" });
  },
};
