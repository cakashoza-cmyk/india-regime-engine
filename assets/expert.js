// Credit Expert View: renders data/expert/*.json (static, built by engine/expert.py). No AI calls in the browser.
(function(){
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=u=>/^https?:\/\//i.test(u||'')?u:'';
const ln=(u,t)=>safeUrl(u)?`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t||'source')}</a>`:esc(t||'');
const LBL={ok:'OK to lend',caution:'Caution',avoid:'Avoid',proxy:'Proxy only',dealer:'Dealer view',unknown:'Not yet known'};
const CLS=c=>c||'unknown';
const GREY=t=>`<div class="greyl"><span class="tg gr">Not yet known</span>${esc(t)}</div>`;
const num=(v,u)=>v==null?'—':(Math.round(v*10)/10).toLocaleString('en-IN')+(u==='%'?'%':(u?' '+u:''));
let IX=null,KB=null,ST={},FCFG=null,cur=null;
const P=new URLSearchParams(location.search);

function sec(n,title,digest,body,open){return `<details class="sec" id="s${n}"${open?' open':''}><summary><span class="n">${n}</span><span><span class="h">${esc(title)}</span><span class="d">${digest}</span></span></summary><div class="body">${body}</div></details>`}
function pg(html){return `<div class="pgbox"><span class="tg pg">Practice guidance</span><span class="meta">general credit practice, not a sourced fact</span>${html}</div>`}
function list(a,cls){return a&&a.length?`<ul${cls?` class="${cls}"`:''}>${a.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}
function factHtml(id){const f=KB.facts[id];if(!f)return '';const s=KB.sources[f.src]||{};const ck=s.check||{};
 const okc=ck.status==='ok'?`quote checked ${esc(ck.checked||'')}${ck.method==='cached copy'?' (saved copy)':''}`:'quote not re-checked';
 return `<li class="fact"><span class="tg src">Sourced</span>${esc(f.text)} <span class="s">— ${ln(s.url,(s.publisher||'')+(s.date?', '+s.date:''))} · ${okc} · <details><summary>quote</summary>${f.quotes.map(q=>`<span class="q">“…${esc(q)}…”</span>`).join('')}<span class="s">${esc(s.title||'')}</span></details></span></li>`}
function factsBy(ids,pred){return (ids||[]).filter(i=>KB.facts[i]&&(!pred||pred(KB.facts[i])))}
function factList(ids){return ids.length?`<ul>${ids.map(factHtml).join('')}</ul>`:''}

async function getState(st){if(!ST[st])ST[st]=await fetch(`data/expert/${st}.json`).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()});return ST[st]}

// ---------- pickers and search ----------
function fillPick(st,ct,ind){const S=$('#sst'),C=$('#sct'),I=$('#sind');
 S.innerHTML='<option value="">Choose state…</option>'+IX.states.map(s=>`<option value="${s.st}"${s.st===st?' selected':''}>${esc(s.name)}</option>`).join('');
 const cities=[...new Map(IX.pairs.filter(p=>p.st===st).map(p=>[p.ct,p.ctn])).entries()].sort((a,b)=>a[1].localeCompare(b[1]));
 C.disabled=!st;C.innerHTML='<option value="">'+(st?'Choose city…':'Pick a state first')+'</option>'+cities.map(([c,n])=>`<option value="${c}"${c===ct?' selected':''}>${esc(n)}</option>`).join('');
 const inds=IX.pairs.filter(p=>p.st===st&&p.ct===ct);
 I.disabled=!ct;I.innerHTML='<option value="">'+(ct?'Choose industry…':'Pick a city first')+'</option>'+inds.map(p=>`<option value="${p.ind}"${p.ind===ind?' selected':''}>${esc(p.indn)} — ${esc(LBL[p.call]||'not yet known')}${p.score!=null?' '+p.score:''}${p.depth==='full'?' ★':''}</option>`).join('')}
function href(p){return `expert.html?state=${encodeURIComponent(p.st)}&city=${encodeURIComponent(p.ct)}&ind=${encodeURIComponent(p.ind)}`}
function search(q){q=q.trim().toLowerCase();const R=$('#res');if(q.length<2){R.classList.remove('open');R.innerHTML='';return}
 const words=q.split(/\s+/);const hit=IX.pairs.filter(p=>{const h=(p.ctn+' '+p.indn+' '+p.stn+' '+p.ind).toLowerCase();return words.every(w=>h.includes(w))})
  .sort((a,b)=>(a.depth==='full'?0:a.depth==='partial'?1:2)-(b.depth==='full'?0:b.depth==='partial'?1:2)||a.ctn.localeCompare(b.ctn)).slice(0,40);
 R.innerHTML=hit.length?hit.map(p=>`<a href="${href(p)}"><span class="badge ${CLS(p.call)}" style="font-size:11px;padding:2px 8px">${esc(LBL[p.call]||'—')}${p.score!=null?' '+p.score:''}</span><span><b>${esc(p.ctn)}</b> · ${esc(p.indn)}<br><span class="meta">${esc(p.stn)}${p.depth==='full'?' · ★ full local depth':''}</span></span></a>`).join(''):'<div class="empty">No city or industry matches.</div>';R.classList.add('open')}

// ---------- the seven sections ----------
function verdictBox(v,S){const d=v.verdict,c=CLS(d.call);const cf=d.conf||{};
 const flags=[d.nudged?`<div class="meta">⚠️ Lowered from OK by recent news: ${esc(d.news_why||'')}</div>`:'',d.ratings_cut?'<div class="meta">⚠️ Lowered by recent rating actions in this cluster.</div>':''].join('');
 return `<div class="vbox ${c}"><div class="vtop"><span class="badge ${c} vcall">${esc(LBL[d.call]||'Not yet known')}</span>${d.score!=null?`<span class="vscore">${d.score}<small>/100</small></span>`:''}
 <span class="bas">Basis: ${esc(d.basis_label||'—')}</span>${cf.lv?`<span class="bas conf ${cf.lv}">Confidence: ${esc(cf.lv==='med'?'medium':cf.lv)}</span>`:''}<span class="depth ${v.depth}">${v.depth==='full'?'★ Full local depth':v.depth==='partial'?'Gujarat: partial depth':'Standard note'}</span></div>
 <div class="vwhy">${esc(d.reason||'No call yet for this pair: the Radar has no sector series that maps to it.')}</div>${flags}
 <div class="meta">${cf.why?'Confidence: '+esc(cf.why)+'. ':''}Cut-offs: OK ≥ ${d.thresholds.ok}, Avoid &lt; ${d.thresholds.avoid}. Radar data refreshed ${esc(d.refreshed||'—')}${d.note_at?' · city note '+esc(d.note_at):''}.</div></div>`}

function lendSec(v,F){const d=v.verdict,a=(v.lend||{}).anchors||[];
 const stance={ok:'New exposure is acceptable on normal structure; use the checks below to pick the better units.',caution:'Lend selectively: prefer existing customers with a clean track record, tighter structure and closer monitoring; avoid stretching on new-to-bank units.',avoid:'Avoid new exposure. For existing accounts, tighten monitoring, review limits at renewal, and watch for early stress.',proxy:'No industry series maps directly here: read the closest sector and judge on the unit.',dealer:'Dealer business: judge on the principal company and the dealer agreement, not on the sector cycle.'}[d.call]||'No call yet: judge on the unit and use the checklist below.';
 const anc=a.length?`<h4>Size it on listed-peer numbers <span class="tg dat">Data</span></h4><div class="tw"><table><tr><th>Metric</th><th>Peer median</th><th>Range</th><th>Peers</th></tr>${a.map(x=>`<tr><td>${esc(x.label)}</td><td><b>${num(x.median,x.unit)}</b></td><td>${num(x.lo,x.unit)} to ${num(x.hi,x.unit)}</td><td>${x.n}</td></tr>`).join('')}</table></div><p class="meta">Listed peers are larger than a typical SME borrower; a proposal projecting better numbers than these needs proof. ${ln(v.links.sensecheck,'Test a proposal against these in Sense-Check →')}</p>`
  :GREY('Peer benchmarks for sizing working capital and margins: no listed peer group mapped to this industry yet.');
 return sec(2,'How to lend',esc(LBL[d.call]||'No call')+' · facilities, tenor, security, covenants, triggers',
  pg(`<p><b>Stance.</b> ${esc(stance)}</p><h4>Facilities</h4>${list(F.facilities)}<h4>Tenor</h4><p>${esc(F.tenor)}</p><h4>Security</h4>${list(F.security)}<h4>Covenants</h4>${list(F.covenants)}<h4>Monitoring triggers</h4>${list(F.monitoring)}`)+anc)}

function econSec(v,S,F){const e=v.economics,fids=e.facts||[];const pk=e.peers&&S.peers[e.peers];
 const by=t=>factsBy(fids,f=>f.topic===t);
 const metric=(m)=>pk&&pk.metrics&&pk.metrics[m];
 const mline=(m,lbl)=>{const x=metric(m);return x&&x.median!=null?`<p><span class="tg dat">Data</span>${esc(lbl)}: peer median <b>${num(x.median,x.unit)}</b> (range ${num(x.lo,x.unit)} to ${num(x.hi,x.unit)}, ${x.n} listed peers)</p>`:''};
 const wc=mline('receivable_days','Debtor days')+mline('inventory_days_on_sales','Inventory days');
 const mg=mline('ebitda_margin_pct','EBITDA margin')+mline('revenue_yoy_pct','Sales growth');
 const inp=[...by('input_cost'),...by('energy')];
 const otherE=fids.filter(i=>!['input_cost','energy','capacity','seasonality'].includes(KB.facts[i].topic));
 const peerTbl=pk?`<details><summary class="meta" style="cursor:pointer">Peer group: ${esc(pk.label)} (${Object.keys(pk.companies||{}).length} companies) — show filings</summary><p class="meta">${esc(pk.fit||'')}</p><div class="tw"><table><tr><th>Company</th><th>Metric</th><th>Quarters (value, filing)</th></tr>${Object.entries(pk.metrics||{}).flatMap(([m,x])=>Object.entries(x.obs||{}).map(([co,ob])=>`<tr><td>${esc((pk.companies[co]||{}).name||co)}</td><td>${esc(x.label)}</td><td>${ob.map(o=>`${esc(o.fq)}: ${ln(o.source,num(o.value,x.unit))}`).join(' · ')}</td></tr>`)).join('')}</table></div></details>`:'';
 const body=`<h4>Business model</h4>${e.what?`<p><span class="tg dat">Radar</span>${esc(e.what)}</p>`:''}${pg(`<p>${esc(F.model)}</p>`)}${factList(otherE)}
 <h4>Working-capital cycle</h4>${wc||GREY('Debtor and inventory days: no listed peer benchmark for this industry.')}${GREY('Creditor days: listed filings used here do not give a clean figure.')}
 <h4>Margin band</h4>${mg||GREY('Margin band: no listed peer benchmark for this industry.')}
 <h4>Capacity utilisation and seasonality</h4>${factList(by('capacity'))}${factList(by('seasonality'))}${e.has_capacity?'':GREY('Capacity utilisation: no official or filed figure for this cluster yet.')}${e.has_seasonality?'':GREY('Seasonality: no sourced pattern for this cluster yet.')}
 <h4>Input costs</h4>${factList(inp)}${(e.margin_driver||[]).map(m=>`<p><span class="tg dat">Data</span>Input vs selling prices: ${ln(m.u,m.t)} <span class="meta">(${esc(m.st)}, ${esc(m.d||'')})</span></p>`).join('')}${(e.commodities||[]).map(c=>`<p><span class="tg dat">Market</span>${esc(c.label)}: ${ln(c.url,num(c.value,c.unit))}${c.yoy_pct!=null?`, ${c.yoy_pct>0?'+':''}${num(c.yoy_pct,'%')} on a year`:''} <span class="meta">(as of ${esc(c.as_of)}; ${esc(c.status)})</span></p>`).join('')}${inp.length||(e.margin_driver||[]).length||(e.commodities||[]).length?'':GREY('Input-cost series: none mapped to this industry yet.')}
 ${peerTbl}`;
 const dg=[metric('ebitda_margin_pct')?'margin '+num(metric('ebitda_margin_pct').median,'%'):'margin not yet known',metric('receivable_days')?'debtors '+num(metric('receivable_days').median,'days'):null,inp.length?'input costs sourced':null].filter(Boolean).join(' · ');
 return sec(3,'Industry economics',esc(dg),body)}

function localSec(v){const l=v.local,fids=l.facts||[];
 const by=ts=>factsBy(fids,f=>ts.includes(f.topic));
 const struct=by(['structure','units','scale']),mk=by(['markets','demand']),pr=by(['practice']),reg=by(['regulation','environment']),st=by(['stress']);
 const rest=fids.filter(i=>![...struct,...mk,...pr,...reg,...st].includes(i));
 const sig=(l.state_signals||[]).map(s=>`<li><span class="tg dat">Data</span>${esc(s.label)}: ${v.state} ${ln(s.url,(s.value>0?'+':'')+num(s.value,'%'))} vs India ${num(s.india,'%')} <span class="meta">(${esc(s.source)}, to ${esc(s.as_of)})</span></li>`).join('');
 const nw=(l.news||[]).length?`<h4>Recent local news <span class="tg nw">Found by search · unverified</span></h4><p class="meta">Headlines can only make the call more cautious, never better.${l.news_direction?' Read on the news: <b>'+esc(l.news_direction)+'</b>'+(l.news_why?' — '+esc(l.news_why):''):''}</p><ul>${l.news.slice(0,6).map(n=>`<li>${ln(n.url,n.title)} <span class="meta">${esc(n.date||'')}</span></li>`).join('')}</ul>`:'';
 const watch=(l.watch||[]).length?`<h4>What the Radar watches here</h4><ul>${l.watch.map(w=>`<li><b>${esc(w.name)}:</b> ${esc(w.signals)}</li>`).join('')}</ul>`:'';
 const deep=v.depth==='full';
 const body=(v.cluster_name?`<p><b>Cluster:</b> ${esc(v.cluster_name)}</p>`:'')+
  `<h4>Cluster structure and unit counts</h4>${factList(struct)||GREY('Cluster structure and unit counts: no official cluster study loaded for this city and industry.')}`+
  `<h4>Demand markets</h4>${factList(mk)||GREY('Where the cluster sells: not yet sourced.')}`+
  `<h4>Cluster practices</h4>${factList(pr)||GREY('Local trade practices: not yet sourced.')}`+
  (reg.length?`<h4>Regulation and environment</h4>${factList(reg)}`:'')+
  `<h4>Local stress</h4>${factList(st)}${st.length?'':GREY('Sourced stress episodes: none loaded.')}`+(rest.length?factList(rest):'')+
  (sig?`<h4>${esc(v.state)} activity vs India</h4><ul>${sig}</ul>`:'')+watch+nw;
 const n=fids.length;return sec(4,'Local knowledge',deep?`${n} sourced facts · ${esc(v.cluster_name||'')}`:(n?`${n} sourced facts (partial)`:'grey: no cluster study loaded yet'),body)}

function redSec(v,F){const R=F.red_flags||{},G=KB.generic_red||{};
 const grp=(k,t)=>{const a=[...(R[k]||[]),...(G[k]||[])];return a.length?`<h4>${t}</h4>${list(a,'chk')}`:''};
 const sc=(v.redflags||{}).sector_checks||[];
 const body=pg(grp('financials','Financials')+grp('gst','GST returns')+grp('bank','Bank statements')+grp('site','Site visit')+`<h4>Questions to ask the promoter</h4><ol>${[...(F.questions||[]),...(KB.generic_q||[])].map(q=>`<li>${esc(q)}</li>`).join('')}</ol>`)+
  (sc.length?`<h4>Radar sector checks <span class="tg dat">Radar</span></h4>${list(sc,'chk')}`:'');
 const n=['financials','gst','bank','site'].reduce((s,k)=>s+(R[k]||[]).length+(G[k]||[]).length,0)+sc.length;
 return sec(5,'Red flags and promoter questions',`${n} checks · ${(F.questions||[]).length+(KB.generic_q||[]).length} questions · printable checklist`,body)}

function trigSec(v,F){const t=v.triggers||{};
 const st=(t.stress||[]).length?`<h4>Stress test on this score <span class="tg dat">Radar</span></h4><div class="tw"><table><tr><th>If</th><th>Points</th><th>New score</th><th>Call changes?</th></tr>${t.stress.map(s=>`<tr><td>${esc(s.shock)}</td><td>${s.points>0?'+':''}${esc(s.points)}</td><td>${esc(s.new_score)}</td><td>${s.flip?'<b>'+esc(s.flip)+'</b>':'no'}</td></tr>`).join('')}</table></div>`:'';
 const rs={watch:'Rating actions in this cluster are on watch.',negative:'Rating actions in this cluster are net negative: the call is cut.',calm:'Rating actions in this cluster are calm.',thin:'Too few rating actions to read.'}[t.ratings_signal]||'';
 const body=`<h4>Data that would move the call</h4>${(t.wrong_if||[]).length?list(t.wrong_if):GREY('No specific data trigger recorded for this pair.')}${t.change?`<p>${esc(t.change)}</p>`:''}${t.check_back?`<p class="meta">Radar check-back date: ${esc(t.check_back)}</p>`:''}${st}${rs?`<p><span class="tg dat">Ratings</span>${esc(rs)}</p>`:''}
 <p class="meta">Signals (news, rating actions) can only lower a call; only data can raise it.</p>${pg(`<h4>Would upgrade the view</h4>${list(F.upgrade)}<h4>Would downgrade the view</h4>${list(F.downgrade)}`)}`;
 const flip=(t.stress||[]).find(s=>s.flip);
 return sec(6,'What would change the view',flip?esc(flip.shock+' flips the call to '+flip.flip):`${(t.wrong_if||[]).length} data triggers · stress test${(t.stress||[]).length?'':' n/a'}`,body)}

function evSec(v,S){const e=v.evidence||{},sx=S.sectors[e.sector]||{},rt=e.ratings&&S.ratings[e.ratings];
 const STL={verified:'verified',stale:'stale',unverified:'unverified',missing:'missing'};
 const drv=(sx.drivers||[]).length?`<h4>Sector drivers (${esc(sx.name||'')})</h4><div class="tw"><table><tr><th>Driver</th><th>Status</th><th>Data to</th></tr>${sx.drivers.map(d=>`<tr><td>${d.s>0?'▲ ':d.s<0?'▼ ':''}${ln(d.u,d.t)}</td><td>${esc(STL[d.st]||d.st||'')}${d.r?'<br><span class="meta">'+esc(d.r)+'</span>':''}</td><td>${esc(d.d||'—')}</td></tr>`).join('')}</table></div>`:GREY('No sector drivers for this pair.');
 const rs=(e.reasons||[]).length?`<h4>Why the local score differs</h4><ul>${e.reasons.map(r=>`<li>${r.sign>0?'▲ ':r.sign<0?'▼ ':''}${ln(r.u,r.t)}</li>`).join('')}</ul>`:'';
 const cr=sx.credit?`<p><span class="tg dat">RBI</span>Bank credit to ${esc(sx.credit.name)}: ₹${num(sx.credit.outstanding_cr)} Cr, ${num(sx.credit.yoy_pct,'%')} on a year (as of ${esc(sx.credit.as_of)}).</p>`:'';
 const gn=sx.gnpa&&(sx.gnpa.points||[]).length?`<p><span class="tg dat">RBI FSR</span>GNPA (${esc(sx.gnpa.fsr_category)}): ${sx.gnpa.points.map(p=>`${esc(p.period)} ${ln(p.source_url,num(p.value,'%'))}`).join(' → ')}</p>`:'';
 const ra=rt?`<h4>Rating actions: ${esc(rt.label)} <span class="meta">(${esc(rt.window||'')}, ${esc((rt.agencies_covered||[]).join(', '))})</span></h4><p class="meta">${rt.actions} actions: ${rt.upgrades} upgrades, ${rt.downgrades} downgrades, ${rt.defaults} defaults, ${rt.inc_new||0} non-cooperation. Signal: ${esc(rt.signal)}.</p><ul>${(rt.list||[]).slice(0,10).map(a=>`<li>${esc(a.date)} · ${ln(a.url,a.entity)} (${esc(a.city||'')}) — ${esc(a.action)}</li>`).join('')}</ul>`:GREY('Rating actions: no cluster watch-list mapped to this pair.');
 const ds=(S.datasets||[]).length?`<h4>Data freshness</h4><div class="tw"><table><tr><th>Dataset</th><th>Data to</th><th>Fresh?</th></tr>${S.datasets.map(d=>`<tr><td>${ln(d.url,d.label)}</td><td>${esc(d.period||'—')}</td><td>${d.fresh?'yes':'<b>stale</b>'+(d.stale_reason?'<br><span class="meta">'+esc(d.stale_reason)+'</span>':'')}</td></tr>`).join('')}</table></div>`:'';
 const nt=e.note?`<p class="meta">City note built ${esc(e.note.generated_at)} (${esc(e.note.tier)}); its score then: ${esc(e.note.score_then)} ${esc(LBL[e.note.call_then]||'')}. The verdict above is restated on today's data.</p>`:'';
 const ids=[...new Set([...(v.economics.facts||[]),...(v.local.facts||[])])];const srcs=[...new Set(ids.map(i=>KB.facts[i]&&KB.facts[i].src).filter(Boolean))];
 const sl=srcs.length?`<h4>Sources for the facts in this view</h4><ul>${srcs.map(s=>{const x=KB.sources[s];return `<li>${ln(x.url,x.title)} <span class="meta">— ${esc(x.publisher)}, ${esc(x.date)} · ${esc(x.kind)} · check: ${esc((x.check||{}).status||'—')}</span></li>`}).join('')}</ul>`:'';
 return sec(7,'Evidence and sources',`${(sx.drivers||[]).length} drivers · ${srcs.length} fact sources${rt?' · '+rt.actions+' rating actions':''}`,drv+rs+cr+gn+ra+ds+nt+sl)}

function fbBox(v){if(!FCFG||!FCFG.worker_url)return '';const d=v.verdict;return `<div class="card fb" id="fbc">
 <h3 style="margin:0 0 4px">Does this match your local credit view?</h3>
 <p class="meta" style="margin:0 0 10px">AI stance here: <b>${esc(LBL[d.call]||'—')}</b>${d.score!=null?' · score '+esc(d.score):''}. Your answer goes to the credit team's report.</p>
 <form id="fbf" novalidate>
 <div class="meta" style="margin-bottom:4px">1 = AI matches the local credit view · 10 = AI does not match</div>
 <div class="fbscale">${[...Array(10)].map((_,i)=>`<label><input type="radio" name="rating" value="${i+1}"><span>${i+1}</span></label>`).join('')}</div>
 <div class="fbrow"><label>Your view<select name="user_view"><option value="">Choose…</option><option value="ok">OK to lend</option><option value="caution">Caution</option><option value="avoid">Avoid</option></select></label>
 <label>Employee ID<input name="employee_id" maxlength="12" autocomplete="off" placeholder="e.g. E12345" pattern="[A-Za-z0-9]{3,12}"></label></div>
 <label style="display:block;margin-top:8px">Comment (optional)<textarea name="comment" maxlength="300" rows="2" placeholder="Short reason, no customer details"></textarea></label>
 <p class="fbwarn">⚠️ Do not enter customer names or account details.</p>
 <button type="submit" class="fbbtn">Submit feedback</button> <span class="meta" id="fbmsg"></span></form></div>`}
document.addEventListener('submit',async e=>{if(e.target.id!=='fbf'||!cur)return;e.preventDefault();const f=new FormData(e.target),m=$('#fbmsg'),d=cur.verdict;
 const emp=(f.get('employee_id')||'').trim(),rating=f.get('rating'),view=f.get('user_view');
 if(!rating){m.textContent='Pick a rating from 1 to 10.';return}if(!view){m.textContent='Choose your view.';return}if(!/^[A-Za-z0-9]{3,12}$/.test(emp)){m.textContent='Employee ID: 3–12 letters or digits.';return}
 const b=e.target.querySelector('button');b.disabled=true;m.textContent='Sending…';
 try{const r=await fetch(FCFG.worker_url+'/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({state:cur.st,city:cur.ct,industry:cur.ind,ai_stance:d.call,ai_score:d.score,rating:+rating,user_view:view,employee_id:emp,comment:f.get('comment')||''})});
  const j=await r.json().catch(()=>({}));if(r.ok){$('#fbc').innerHTML='<h3 style="margin:0">Thank you — feedback recorded.</h3><p class="meta">It will appear in the credit team\'s report.</p>'}else{m.textContent=j.error||('Could not save ('+r.status+')');b.disabled=false}}
 catch(err){m.textContent='Could not reach the feedback service.';b.disabled=false}});

function crumb(v){const lk=(q,t)=>`<a href="lending.html?${q}">${esc(t)}</a>`;
 $('#crumb').innerHTML=v?`${lk('','India map')} › ${lk('state='+v.st,v.state)} › ${lk('state='+v.st+'&city='+v.ct,v.city)} › <b>${esc(v.industry)}</b> › <b>Expert View</b>`:'Path: <b>State</b> › <b>City</b> › <b>Industry</b> › <b>Expert View</b>, or search above.'}

function viewHtml(v,S){const F=KB.families[v.family]||KB.families.generic_mfg;
 const tools=`<div class="tools"><button class="pri" onclick="window.print()">🖨 Print / save PDF</button><a href="${esc(v.links.sensecheck)}">Sense-Check a proposal →</a><a href="${esc(v.links.lending)}">Back to map</a><button id="cmpb">⇄ Compare with…</button><button id="openall">Expand all</button></div>`;
 return `<div class="card"><h1 style="margin:0">${esc(v.industry)}</h1><p class="sub" style="margin:2px 0 10px">${esc(v.city)}, ${esc(v.state)}${v.industry!==v.parent_name?' · read through '+esc(v.parent_name):''}${v.mapping&&v.mapping!=='direct'?' ('+esc(v.mapping)+' mapping)':''}</p>${verdictBox(v,S)}${tools}<div id="cmpp"></div></div>`+
  lendSec(v,F)+econSec(v,S,F)+localSec(v)+redSec(v,F)+trigSec(v,F)+evSec(v,S)+fbBox(v)}

async function show(st,ct,ind){fillPick(st,ct,ind);const out=$('#out');
 if(!(st&&ct&&ind)){cur=null;crumb(null);out.innerHTML=landing(st,ct);return}
 out.innerHTML='<div class="card empty">Loading…</div>';
 let S;try{S=await getState(st)}catch(e){out.innerHTML='<div class="card empty">Could not load this state\'s data.</div>';return}
 const v=S.pairs[ct+'|'+ind];if(!v){out.innerHTML='<div class="card empty">This city and industry pair is not on the Radar.</div>';return}
 cur=v;crumb(v);document.title=`${v.city} · ${v.industry} — Credit Expert View`;$('#ph').textContent=`${v.city}, ${v.state} · ${v.industry} · printed ${new Date().toLocaleDateString('en-IN')}`;
 out.innerHTML=viewHtml(v,S);$('#foot').innerHTML=`Built ${esc(S.generated||'')} from Lending Radar data and ${Object.keys(KB.sources).length} checked public sources. ${KB.rules.map(esc).join(' ')} Internal decision aid; final credit judgment stays with the sanctioning authority.`;
 $('#openall').onclick=()=>{const all=[...document.querySelectorAll('details.sec')];const o=all.some(d=>!d.open);all.forEach(d=>d.open=o);$('#openall').textContent=o?'Collapse all':'Expand all'};
 $('#cmpb').onclick=()=>cmpPicker(v)}

function landing(st,ct){const full=IX.pairs.filter(p=>p.depth==='full');
 return `<div class="card"><h3 style="margin:0 0 6px">Start here</h3><p class="meta">Search above, or pick <b>State → City → Industry</b>. ★ marks Gujarat clusters with full local depth (sourced cluster facts):</p><div class="quick">${full.map(p=>`<a href="${href(p)}">${esc(p.ctn)} · ${esc(p.indn)}</a>`).join('')}</div>
 <p class="meta" style="margin-top:12px">Compare two industries side by side: open one, then tap “Compare with…”. Or start from the ${'<a href="lending.html">India heat map</a>'}.</p></div>`}

// ---------- compare ----------
function cmpPicker(v){const box=$('#cmpp');box.innerHTML=`<div class="find" style="margin-top:10px"><input id="cq" type="search" placeholder="Second industry or city, e.g. Morbi ceramics" autocomplete="off"><div class="res" id="cres"></div></div>`;
 const q=$('#cq');q.focus();q.oninput=()=>{const s=q.value.trim().toLowerCase(),R=$('#cres');if(s.length<2){R.classList.remove('open');return}
  const w=s.split(/\s+/);const hit=IX.pairs.filter(p=>p.k!==v.key&&w.every(x=>(p.ctn+' '+p.indn+' '+p.stn).toLowerCase().includes(x))).slice(0,30);
  R.innerHTML=hit.map(p=>`<a href="expert.html?compare=${encodeURIComponent(v.key+'~'+p.k)}"><b>${esc(p.ctn)}</b>&nbsp;· ${esc(p.indn)} <span class="meta">${esc(LBL[p.call]||'—')}</span></a>`).join('')||'<div class="empty">No match.</div>';R.classList.add('open')}}
async function compare(keys){const out=$('#out');const vs=[];
 for(const k of keys){const [st,ct,ind]=k.split('|');try{const S=await getState(st);const v=S.pairs[ct+'|'+ind];if(v)vs.push([v,S])}catch(e){}}
 fillPick('', '', '');crumb(null);
 if(vs.length<2){out.innerHTML='<div class="card empty">Pick two valid pairs to compare.</div>';return}
 document.title='Compare — Credit Expert View';$('#ph').textContent='Comparison · '+vs.map(([v])=>v.city+' '+v.industry).join(' vs ');
 const pm=(v,S,m)=>{const pk=v.economics.peers&&S.peers[v.economics.peers];const x=pk&&pk.metrics&&pk.metrics[m];return x&&x.median!=null?`${num(x.median,x.unit)} <span class="meta">(${num(x.lo,x.unit)} to ${num(x.hi,x.unit)})</span>`:'<span class="tg gr">Not yet known</span>'};
 const facts=(v,ts)=>{const ids=[...(v.economics.facts||[]),...(v.local.facts||[])].filter(i=>KB.facts[i]&&ts.includes(KB.facts[i].topic));return ids.length?`<ul>${ids.slice(0,3).map(factHtml).join('')}</ul>`:'<span class="tg gr">Not yet known</span>'};
 const rows=[['Verdict',(v)=>`<span class="badge ${CLS(v.verdict.call)}">${esc(LBL[v.verdict.call]||'—')}${v.verdict.score!=null?' '+v.verdict.score:''}</span> <span class="bas conf ${v.verdict.conf&&v.verdict.conf.lv}">confidence ${esc(v.verdict.conf?(v.verdict.conf.lv==='med'?'medium':v.verdict.conf.lv):'—')}</span><p class="meta">${esc(v.verdict.reason||'')}</p>`],
  ['Facilities (practice guidance)',(v)=>list(((KB.families[v.family]||KB.families.generic_mfg).facilities||[]).slice(0,2))],
  ['Debtor days (peer median)',(v,S)=>pm(v,S,'receivable_days')],['Inventory days (peer median)',(v,S)=>pm(v,S,'inventory_days_on_sales')],['EBITDA margin (peer median)',(v,S)=>pm(v,S,'ebitda_margin_pct')],
  ['Input costs',(v)=>facts(v,['input_cost','energy'])+((v.economics.margin_driver||[])[0]?`<p class="meta">${ln(v.economics.margin_driver[0].u,v.economics.margin_driver[0].t)}</p>`:'')],
  ['Cluster structure',(v)=>facts(v,['structure','units','scale'])],['Local stress',(v)=>facts(v,['stress'])+(v.local.news_why?`<p class="meta"><span class="tg nw">News · unverified</span>${esc(v.local.news_why)}</p>`:'')],
  ['What would change it',(v)=>list(v.triggers.wrong_if||[])||'<span class="tg gr">Not yet known</span>'],
  ['Stress flips',(v)=>{const f=(v.triggers.stress||[]).filter(s=>s.flip);return f.length?list(f.map(s=>s.shock+' → '+s.flip)):'none of the standard shocks flips the call'}]];
 out.innerHTML=`<div class="card"><h1 style="margin:0 0 8px">Compare</h1><div class="tools"><button class="pri" onclick="window.print()">🖨 Print / save PDF</button>${vs.map(([v])=>`<a href="${esc(v.links.expert)}">Open ${esc(v.city)} · ${esc(v.industry)}</a>`).join('')}</div></div>
 <div class="card">${rows.map(([l,f])=>`<div class="cmprow"><b class="l">${esc(l)}</b><div class="cmp">${vs.map(([v,S])=>`<div><b>${esc(v.city)} · ${esc(v.industry)}</b><div>${f(v,S)}</div></div>`).join('')}</div></div>`).join('')}</div>`}

window.addEventListener('beforeprint',()=>document.querySelectorAll('details').forEach(d=>{d.dataset.wasOpen=d.open?'1':'';d.open=true}));
window.addEventListener('afterprint',()=>document.querySelectorAll('details').forEach(d=>{if(d.dataset.wasOpen!==undefined)d.open=d.dataset.wasOpen==='1'}));

Promise.all([fetch('data/expert/index.json').then(r=>r.json()),fetch('data/expert/kb.json').then(r=>r.json()),fetch('data/fetch_config.json').then(r=>r.ok?r.json():{}).catch(()=>({}))]).then(([ix,kb,fc])=>{IX=ix;KB=kb;FCFG=fc;
 const q=$('#q');q.addEventListener('input',()=>search(q.value));document.addEventListener('click',e=>{if(!e.target.closest('.find'))document.querySelectorAll('.res').forEach(r=>r.classList.remove('open'))});
 q.addEventListener('keydown',e=>{if(e.key==='Enter'){const a=$('#res a');if(a)location.href=a.getAttribute('href')}});
 $('#sst').onchange=e=>go(e.target.value,'','');$('#sct').onchange=e=>go($('#sst').value,e.target.value,'');$('#sind').onchange=e=>go($('#sst').value,$('#sct').value,e.target.value);
 const cp=P.get('compare');if(cp){compare(cp.split('~').slice(0,2));return}
 show(P.get('state')||'',P.get('city')||'',P.get('ind')||'')}).catch(()=>{$('#out').innerHTML='<div class="card empty">Could not load the Expert View data.</div>'});
function go(st,ct,ind){const u=new URL(location.href);u.search='';if(st)u.searchParams.set('state',st);if(ct)u.searchParams.set('city',ct);if(ind)u.searchParams.set('ind',ind);history.replaceState(null,'',u);show(st,ct,ind);if(ind)window.scrollTo(0,0)}
})();
