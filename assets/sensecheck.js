/* Proposal Sense-Check: pure logic (no DOM, no network, no storage). Used by sensecheck.html and by
   engine/tests/test_sensecheck.py via node. Flags can only add caution; they never upgrade a view. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SenseCheck = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  // banker input -> peer metric in data/sensecheck_peers.json (null = no listed-peer benchmark exists)
  var FIELDS = [
    { id: 'growth', label: 'Sales growth', unit: '%', metric: 'revenue_yoy_pct', min: -100, max: 500, wc: false },
    { id: 'margin', label: 'EBITDA margin', unit: '%', metric: 'ebitda_margin_pct', min: -100, max: 100, wc: false },
    { id: 'debtor', label: 'Debtor days', unit: 'days', metric: 'receivable_days', min: 0, max: 1000, wc: true },
    { id: 'inventory', label: 'Inventory days', unit: 'days', metric: 'inventory_days_on_sales', min: 0, max: 1000, wc: true },
    { id: 'creditor', label: 'Creditor days', unit: 'days', metric: null, nb: 'creditor_days', min: 0, max: 1000, wc: true },
    { id: 'capacity', label: 'Capacity utilisation', unit: '%', metric: null, nb: 'capacity_utilisation', min: 0, max: 150, wc: false },
    { id: 'dscr', label: 'DSCR', unit: 'x', metric: null, nb: 'dscr', min: 0, max: 50, wc: false }
  ];
  // Illustrative only. NOT a real borrower.
  var EXAMPLE = {
    label: 'Example numbers, not a real borrower: an illustrative Surat polyester weaving unit asking for working capital',
    state: 'GJ', city: 'gj_surat', industry: 'mmf_textiles', loan: 'wc',
    values: { growth: 22, margin: 14, debtor: 40, inventory: 45, creditor: 60, capacity: 85, dscr: 1.45 }
  };
  var RANK = { ok: 2, caution: 1, avoid: 0 };

  function lc(l) { return l.replace(/^([A-Z])(?=[a-z])/, function (c) { return c.toLowerCase(); }); }
  function num(x) { if (x === null || x === undefined || String(x).trim() === '') return null; var v = Number(x); return isFinite(v) ? v : NaN; }
  function fmt(v, unit) { if (v === null || v === undefined) return '—'; if (unit === 'x') return (Math.round(v * 100) / 100) + 'x'; var s = Math.round(v * 10) / 10; return unit === 'days' ? s + ' days' : s + '%'; }
  function rng(b, unit) { return fmt(b.lo, unit).replace(/ days$|%$|x$/, '') + '\u2013' + fmt(b.hi, unit); }

  // One flag per entered input. level: green | amber | red | grey | invalid
  function flagOne(f, value, bench, peers) {
    var out = { id: f.id, label: f.label, value: value, unit: f.unit };
    if (value === null) { out.level = 'skip'; return out; }
    if (isNaN(value) || value < f.min || value > f.max) { out.level = 'invalid'; out.text = f.label + ': enter a number between ' + f.min + ' and ' + f.max + '.'; return out; }
    if (!f.metric) { out.level = 'grey'; out.text = 'Projected ' + lc(f.label) + ' ' + fmt(value, f.unit) + ': no benchmark. ' + ((peers && peers.no_benchmark && peers.no_benchmark[f.nb]) || 'No listed-peer data for this item.'); return out; }
    var b = bench && bench[f.metric];
    if (!b || b.median === null || b.median === undefined) { out.level = 'grey'; out.text = 'Projected ' + lc(f.label) + ' ' + fmt(value, f.unit) + ': no benchmark' + (b && b.grey ? ' (' + b.grey + ').' : ' for this industry.'); return out; }
    out.median = b.median; out.lo = b.lo; out.hi = b.hi;
    var vs = 'Projected ' + lc(f.label) + ' ' + fmt(value, f.unit) + ' vs listed-peer median ' + fmt(b.median, f.unit) + ' (peer range ' + rng(b, f.unit) + ')';
    if (b.optimistic === 'high') {
      if (value > b.hi) { out.level = 'red'; out.text = vs + '. Higher than every listed peer achieved. Ask what makes this unit beat larger, better-placed firms; rebuild the projection at peer level.'; }
      else if (value > b.median) { out.level = 'amber'; out.text = vs + '. Above the typical listed peer. Needs evidence: order book, price increases, new capacity.'; }
      else { out.level = 'green'; out.text = vs + '. At or below the peer median: not an aggressive assumption.'; }
    } else {
      if (value < b.lo) { out.level = 'red'; out.text = vs + '. Faster cycle than every listed peer. Unlikely for an SME; check ageing and stock statements and size the limit on peer-level days.'; }
      else if (value < b.median) { out.level = 'amber'; out.text = vs + '. Tighter than the typical listed peer. Verify with the last 12 months\u2019 ageing or stock statements.'; }
      else if (value > b.hi) { out.level = 'amber'; out.text = vs + '. Slower than every listed peer: not optimistic, but check for slow-moving stock or stuck debtors.'; }
      else { out.level = 'green'; out.text = vs + '. At or above the peer median: not an aggressive assumption.'; }
    }
    return out;
  }

  function assess(values, peers, industry) {
    var g = peers && peers.industry_group ? peers.industry_group[industry] : null;
    var bench = g ? peers.benchmarks[g] : null;
    var flags = FIELDS.map(function (f) { return flagOne(f, num(values[f.id]), bench, peers); }).filter(function (x) { return x.level !== 'skip'; });
    var n = { red: 0, amber: 0, green: 0, grey: 0, invalid: 0 };
    flags.forEach(function (x) { n[x.level]++; });
    var judged = n.red + n.amber + n.green, verdict, line;
    if (n.invalid) { verdict = 'invalid'; line = 'Fix the highlighted inputs first.'; }
    else if (!judged) { verdict = 'unjudged'; line = flags.length ? 'No listed-peer benchmark for the numbers entered, so the assumptions cannot be judged here (grey).' : 'Enter at least one projected number.'; }
    else if (n.red >= 2) { verdict = 'unrealistic'; line = 'Assumptions look unrealistic: ' + n.red + ' numbers are better than every listed peer achieved.'; }
    else if (n.red === 1 || n.amber >= 2) { verdict = 'stretched'; line = 'Assumptions look stretched: ' + (n.red ? '1 number beats every listed peer' : '') + (n.red && n.amber ? ' and ' : '') + (n.amber ? n.amber + ' above the typical peer' : '') + '.'; }
    else { verdict = 'reasonable'; line = 'Assumptions look reasonable against listed peers' + (n.amber ? ' (1 to verify)' : '') + '.'; }
    if (judged && n.grey) line += ' ' + n.grey + ' input' + (n.grey > 1 ? 's have' : ' has') + ' no benchmark (grey).';
    return { group: g, flags: flags, counts: n, verdict: verdict, line: line };
  }

  // Combine with the Lending Radar stance. Can only keep or lower it, never raise it.
  function combine(stance, verdict) {
    if (!(stance in RANK)) return { call: stance, changed: false };
    var cap = verdict === 'stretched' || verdict === 'unrealistic' ? 'caution' : 'ok';
    var call = RANK[cap] < RANK[stance] ? cap : stance;
    return { call: call, changed: call !== stance };
  }

  return { FIELDS: FIELDS, EXAMPLE: EXAMPLE, flagOne: flagOne, assess: assess, combine: combine, num: num, fmt: fmt };
});
