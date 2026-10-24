'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = s => s ? new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(s)) : '데이터 없음';
const hm = s => s ? new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(s)) : '--:--';
const day = s => s ? new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(s)) : '';
const link = url => {try {const u=new URL(url); return ['https:','http:'].includes(u.protocol)?esc(u.href):'#';}catch{return '#';}};
const empty = text => `<div class="empty">${esc(text)}</div>`;
const labels = {major:'취재 가치 TOP 10',spread:'언론 확산도',rising:'급상승 이슈',industry:'취재 가치'};
const WEIGHTS = [['impact','산업 영향',35],['spread','매체 확산',25],['novelty','신규성·변화',25],['timeliness','시의성',15]];
const SEG = {impact:'s-impact',spread:'s-spread',novelty:'s-novel',timeliness:'s-time'};
let data, issueMap=new Map(), articleMap=new Map(), page=30, ranking='major';

function sanitize(raw, now=Date.now()) {
  const valid = a => {const time=Date.parse(a.published_at || a.first_collected_at);return Number.isFinite(time)&&time<=now&&time>now-168*3600000;};
  const articles=raw.articles.filter(valid), ids=new Set(articles.map(a=>a.id));
  const issues=raw.issues.map(i=>{const live=i.article_ids.filter(id=>ids.has(id));return {...i,article_ids:live};}).filter(i=>i.article_ids.length);
  const liveIssues=new Set(issues.map(i=>i.id));
  const briefings=raw.briefings.filter(b=>Date.parse(b.expires_at)>now);
  const alerts=raw.alerts.filter(a=>liveIssues.has(a.issue_id)&&Date.parse(a.created_at)>now-168*3600000);
  const errors=(raw.errors||[]).filter(e=>Date.parse(e.created_at)>now-168*3600000);
  const publishers=(raw.publishers||[]).map(p=>p.checked_at&&Date.parse(p.checked_at)<=now-168*3600000?{...p,status:'not_verified',error:null}:p);
  return {...raw,articles,issues,briefings,alerts,errors,publishers};
}

function coverageStatus(i) {
 const c=i.carmgz||{};
 if(c.display_status)return c.display_status;
 if(['보도 완료','후속 보도 검토','확인 필요'].includes(c.status))return c.status;
 if(!c.checked_at)return '검색 대기';
 if(c.errors?.length||c.search_outcome==='partial_error')return '검색 실패';
 return c.search_success?'검색 범위 내 미발견':'검색 실패';
}
function coverageMatches(i, status) {
  const current=coverageStatus(i);
  return !status || (status==='uncertain'?['확인 필요','검색 대기','검색 실패'].includes(current):current===status);
}
// Shape as well as color: filled = evidence found, outline = searched without a match, dashed = not searched.
function pill(i) {
  const s=coverageStatus(i);
  const cls={'보도 완료':'ok','확인 필요':'warn','후속 보도 검토':'follow','검색 범위 내 미발견':'none','검색 실패':'fail'}[s]||'wait';
  return `<span class="pill ${cls}">${esc(s==='검색 범위 내 미발견'?'미발견':s)}</span>`;
}
function coverageDetail(i) {
 const c=i.carmgz||{status:'확인 불가',reason:'검색 결과 없음',matches:[]};
 return `<h3>CARMGZ: ${esc(coverageStatus(i))}</h3><p>${esc(c.reason)}<br><span class="meta">마지막 확인 ${fmt(c.checked_at)} · 보도 여부는 편집자가 최종 확인<br>${esc(c.scope)}</span></p><ul>${(c.matches||[]).map(a=>`<li><a href="${link(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a><div class="meta">${fmt(a.published_at)} · ${esc(a.assessment)} · ${esc(a.reason)}</div></li>`).join('')}</ul>`;
}

// Title-cue category and stated scale become chips; any other reason is shown as-is (escaped).
function chips(i) {
  const out=[];
  for (const r of (i.selection_reasons||[]).slice(0,2)) {
    const cue=/^제목 단서: (.+)$/.exec(r), size=/^제목상 규모: (.+?)(?: \(원문 확인 필요\))?$/.exec(r);
    if (cue) out.push(`<span class="chip${/정책|안전|리콜/.test(cue[1])?' hot':''}">${esc(cue[1])}</span>`);
    else if (size) out.push(`<span class="chip">${esc(size[1])}</span>`);
    else if (!/등록 매체|최초 발행/.test(r)) out.push(`<span class="chip">${esc(r)}</span>`);
  }
  return out.join('');
}
function publisherCount(i) {
  return i.independent_publishers ?? new Set((i.article_ids||[]).map(id=>articleMap.get(id)?.publisher).filter(Boolean)).size;
}
function scoreCell(i, max) {
  if (ranking==='major' || ranking==='industry') {
    const c=i.score_components;
    const segs=c?WEIGHTS.map(([k])=>`<i class="${SEG[k]}" style="width:${Math.max(0,c[k]||0)}%"></i>`).join(''):`<i class="s-spread" style="width:${Math.min(100,i.importance_score||0)}%"></i>`;
    return `<span class="score"><span class="stack" title="산업 영향·확산·신규성·시의성">${segs}</span>${Number(i.importance_score||0).toFixed(1)}</span>`;
  }
  const v=ranking==='spread'?i.spread_score:i.rising_score;
  return `<span class="score"><span class="stack"><i class="s-spread" style="width:${max?Math.round(100*v/max):0}%"></i></span>${esc(ranking==='spread'?v:Number(v||0).toFixed(1))}</span>`;
}
function spark(i) {
  const v=[...(i.hourly_volumes||[])].reverse();
  const max=Math.max(2,...v);
  return `<span class="spark" aria-label="24시간 보도 ${v.reduce((a,b)=>a+b,0)}건">${v.map(n=>`<i class="${n?'on':''}" style="height:${2+Math.round(n/max*14)}px"></i>`).join('')}</span>`;
}
function row(i, rank, max) {
  const pubs=publisherCount(i);
  return `<button type="button" class="row" data-issue="${esc(i.id)}"><span class="rank">${rank}</span><span class="title"><b>${esc(i.label)}</b><span class="chips">${chips(i)}</span></span><span class="pubs"><span class="dots" aria-hidden="true">${Array.from({length:10},(_,k)=>`<i class="${k<pubs?'on':''}"></i>`).join('')}</span>${pubs}<span class="mobile-only">개 매체</span></span>${scoreCell(i,max)}${spark(i)}${pill(i)}</button>`;
}
function renderRankings() {
  document.querySelectorAll('[data-ranking]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.ranking===ranking)));
  const notes={major:'최근 7일 전체 자동차 이슈를 취재 가치 순으로 정렬했습니다. CARMGZ 보도 상태는 순위에 영향을 주지 않습니다.',spread:'서로 다른 등록 매체 수 × 10 + 기사 수. 자체 취재 독립성은 검증하지 않았습니다.',rising:'최근 1시간 보도가 있고 직전 2시간 대비 시간당 보도량이 늘어난 이슈입니다.',industry:'영향·규모 35 / 확산 25 / 표본 신규성·변화 단서 25 / 시의성·증가 15. 제목 기반 편집 검토용이며 사실 검증 점수가 아닙니다.'};
  $('#ranking-note').textContent=notes[ranking]+` 집계 ${fmt(data.generated_at)}.`;
  const head=$('#score-head'); if(head)head.textContent={major:'취재 가치',industry:'취재 가치',spread:'확산 점수',rising:'급상승 점수'}[ranking];
  const items=(data.rankings[ranking]||[]).map(id=>issueMap.get(id)).filter(Boolean);
  const max=Math.max(0,...items.map(i=>ranking==='spread'?i.spread_score:i.rising_score||0));
  $('#rankings').innerHTML=items.map((i,n)=>row(i,n+1,max)).join('')||empty('선정 조건에 맞는 이슈가 없습니다. TOP 10을 임의로 채우지 않습니다.');
}
function renderCoverage() {
 const items=[...issueMap.values()].filter(i=>coverageMatches(i,$('#coverage-filter').value)).sort((a,b)=>b.importance_score-a.importance_score||a.id.localeCompare(b.id));
 const keep=ranking; ranking='major';
 $('#coverage-issues').innerHTML=items.slice(0,100).map(i=>row(i,'·',0)).join('')||empty('조건에 맞는 이슈가 없습니다.');
 ranking=keep;
}

function renderArticles() {
  const q=$('#query').value.trim().toLocaleLowerCase(), pub=$('#publisher').value, date=$('#date').value;
  const rows=data.articles.filter(a=>(!q||`${a.title} ${a.keywords.join(' ')}`.toLocaleLowerCase().includes(q))&&(!pub||a.publisher===pub)&&(!date||day(a.published_at)===date)).sort((a,b)=>Date.parse(b.published_at||b.first_collected_at)-Date.parse(a.published_at||a.first_collected_at));
  $('#article-count').textContent=`${rows.length}건`;
  $('#articles').innerHTML=rows.slice(0,page).map(a=>`<article class="article"><div><a href="${link(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)} ↗</a><div class="meta">${esc(a.publisher)} · ${esc(a.keywords.join(' / '))}</div></div><time datetime="${esc(a.published_at||'')}">${fmt(a.published_at)}</time></article>`).join('')||empty('검색 조건에 맞는 기사가 없습니다.');
  $('#more').hidden=rows.length<=page;
}

function chart(i) {
  const v=[...i.hourly_volumes].reverse(), max=Math.max(1,...v);
  return `<svg class="chart" viewBox="0 0 600 145" role="img" aria-label="집계 시각 이전 24시간 시간별 보도량: ${v.join(', ')}"><line x1="16" y1="118" x2="584" y2="118"/>${v.map((n,k)=>`<rect x="${17+k*23.6}" y="${118-n/max*90}" width="17" height="${n/max*90}"><title>${24-k}~${23-k}시간 전: ${n}건</title></rect>`).join('')}<text x="17" y="137">24시간 전</text><text x="530" y="137">집계 시각</text></svg>`;
}

function openDrawer(expires, html) {
  $('#detail').dataset.expires=String(expires);
  $('#detail-body').innerHTML=html;
  if(!$('#detail').open)$('#detail').showModal();
}
function showIssue(id) {
  const i=issueMap.get(id);if(!i)return;
  const articles=i.article_ids.map(id=>articleMap.get(id)).filter(Boolean).sort((a,b)=>Date.parse(a.published_at||a.first_collected_at)-Date.parse(b.published_at||b.first_collected_at));
  const expires=Math.min(...articles.map(a=>Date.parse(a.published_at||a.first_collected_at)+168*3600000));
  const position=(data.rankings.major||[]).indexOf(i.id);
  const c=i.score_components;
  const axes=c?WEIGHTS.map(([k,l,max])=>`<div class="axis"><span>${l}</span><span class="track"><i class="${SEG[k]}" style="width:${Math.round(100*(c[k]||0)/max)}%"></i></span><span>${Number(c[k]||0).toFixed(1)} / ${max}</span></div>`).join(''):`<p class="reasons">${esc(i.importance_reasons.map(r=>`${r.criterion} ${r.points}점`).join(' / ')||'해당 규칙 없음')}</p>`;
  const reaction = field => i[field]===null||i[field]===undefined?'데이터 없음':`${i[field].toLocaleString()} (${i[field+'_coverage']}/${i.article_count}건 확보)`;
  const ratio=i.growth_ratio_3h===null||i.growth_ratio_3h===undefined?'기준 보도량 없음':`${i.growth_ratio_3h.toFixed(2)}배`;
  const query=(i.carmgz?.queries||[])[0]||i.label;
  const search=`https://www.carmgz.kr/news/articleList.html?sc_area=A&view_type=sm&sc_word=${encodeURIComponent(query)}`;
  openDrawer(expires,`<div class="d-sec"><p class="d-meta">${position>=0?`TOP 10 · ${position+1}위 · `:''}${publisherCount(i)}개 매체 ${i.article_ids.length}건 · 첫 보도 ${fmt(i.first_published_at)}</p><h2 class="d-title">${esc(i.label)}</h2><div class="chips">${chips(i)}</div></div>
<div class="d-sec"><h3>취재 가치 ${Number(i.importance_score||0).toFixed(1)} / 100</h3>${axes}<p class="reasons">${esc((i.selection_reasons||[]).join(' · '))}</p></div>
<div class="d-sec"><h3>보도 흐름</h3><ol class="timeline">${articles.map(a=>`<li><small>${fmt(a.published_at)} · ${esc(a.publisher)}</small><a href="${link(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)} ↗</a></li>`).join('')}</ol>
<h3>시간별 보도량</h3>${chart(i)}
<details class="more-metrics"><summary>세부 지표</summary><p>1시간 ${i.volume_1h}건 · 3시간 ${i.volume_3h}건 · 24시간 ${i.volume_24h}건 · 직전 3시간 대비 ${ratio}<br>유사 제목 쌍 비율 ${i.similar_title_pair_ratio==null?'데이터 없음':(i.similar_title_pair_ratio*100).toFixed(1)+'%'} (전재율 아님) · 조회수 ${reaction('views')} · 댓글 ${reaction('comments')}<br>묶음 근거: ${esc(i.grouping_basis)}</p></details></div>
<div class="d-sec"><h3>CARMGZ 기존 보도</h3><div>${pill(i)}</div><div class="evidence">${coverageDetail(i)}</div><div class="actions"><a class="btn" href="${link(search)}" target="_blank" rel="noopener noreferrer">CARMGZ에서 직접 검색 ↗</a></div></div>`);
}

function showBrief(n) {
  const b=data.briefings[n]; if(!b)return;
  openDrawer(Date.parse(b.expires_at),`<div class="d-sec brief-detail"><p class="d-meta">실제 생성 ${fmt(b.generated_at)} · 지연 ${Math.round(b.delayed_minutes)}분</p><h2 class="d-title">${fmt(b.scheduled_at)} ${b.kind==='am'?'오전':'오후'} 브리핑</h2><p class="reasons">마지막 정상 수집 ${fmt(b.last_collection_at)} · 전일 기준이 없으면 변화는 비교 불가로 표시합니다.</p></div>${Object.entries(b.rankings).map(([k,ids])=>`<div class="d-sec brief-detail"><h3>${labels[k]||esc(k)}</h3><ol>${ids.map(id=>({id,...(b.entries?.[id]||{label:issueMap.get(id)?.label||'만료 이슈',article_count:issueMap.get(id)?.article_count||0,publishers:issueMap.get(id)?.independent_publishers||0})})).map(i=>`<li><button type="button" data-issue="${esc(i.id)}">${esc(i.label)}</button> <span class="caption">생성 당시 ${i.article_count}건 / ${i.publishers}매체</span></li>`).join('')||'<li>확보한 이슈 없음</li>'}</ol></div>`).join('')}<div class="d-sec brief-detail"><h3>CARMGZ 보도 검토</h3>${Object.entries(b.coverage_lists||{}).map(([status,ids])=>`<p class="reasons">${esc(status)}: ${ids.map(id=>esc(b.entries?.[id]?.label||issueMap.get(id)?.label||'만료 이슈')).join(' · ')||'해당 이슈 없음'}</p>`).join('')}</div><div class="d-sec brief-detail"><h3>전일 대비 변화</h3><ul>${b.changes.slice(0,15).map(c=>`<li>${esc(c.label)} · ${c.comparison==='전일 기준 데이터 없음'?'전일 기준 데이터 없음':`${c.new?'새 이슈 · ':''}기사 증감 ${c.article_delta>0?'+':''}${c.article_delta}`}</li>`).join('')||'<li>비교할 이슈 없음</li>'}</ul></div>`);
}

function nextRun(now=Date.now()) {
  // Mirrors collection slots in carmgz/schedule.py (KST, UTC+9, no DST): weekday 00,08..22 even hours, weekend 09/15/21.
  for (let d=0; d<3; d++) {
    const base=new Date(now+9*3600000+d*86400000), wd=base.getUTCDay(), weekend=wd===0||wd===6;
    for (const h of weekend?[9,15,21]:[0,8,10,12,14,16,18,20,22]) {
      const t=Date.UTC(base.getUTCFullYear(),base.getUTCMonth(),base.getUTCDate(),h)-9*3600000;
      if (t>now) return t;
    }
  }
  return null;
}

function isStale(generated, now=Date.now()) {
  // Overdue only when a scheduled collection passed more than 1 hour ago without a newer snapshot.
  const due=nextRun(Date.parse(generated));
  return !due || now>due+3600000;
}

function renderToday() {
  const b=data.briefings[0];
  const top=b?(b.rankings.major||[]).slice(0,3):(data.rankings.major||[]).slice(0,3);
  $('#latest-brief').innerHTML=`<div class="head"><h2>${b?`${b.kind==='am'?'오전':'오후'} 브리핑 · ${hm(b.scheduled_at)}`:'오늘의 상위 이슈'}</h2><span class="caption mono">${b?`이슈 ${Object.keys(b.entries||{}).length}건 · ${fmt(b.generated_at)} 생성`:'브리핑 생성 전'}</span></div><ol>${top.map((id,n)=>{const e=b?.entries?.[id]||issueMap.get(id)||{label:'만료 이슈'};const pubs=e.publishers??e.independent_publishers;return `<li><button type="button" data-issue="${esc(id)}"><i>${n+1}</i><span>${esc(e.label)}</span><small>${pubs??'-'}개 매체</small></button></li>`;}).join('')||'<li class="caption">확보한 이슈 없음</li>'}</ol>${b?`<button type="button" class="ghost" data-brief="0">브리핑 전체 보기</button>`:''}`;
  const multi=data.issues.filter(i=>publisherCount(i)>1).length;
  const top10=(data.rankings.major||[]).map(id=>issueMap.get(id)).filter(Boolean);
  const done=top10.filter(i=>coverageStatus(i)==='보도 완료').length, check=top10.filter(i=>coverageStatus(i)==='확인 필요').length;
  $('#stats').innerHTML=[['최근 7일 관련 기사',data.articles.length,'건'],['여러 매체가 다룬 이슈',multi,`/ ${data.issues.length} 이슈`],['TOP 10 자사 보도 확인',done,`완료 · ${check} 확인 필요`],['긴급 이슈 후보',data.alerts.length,'건']].map(([l,v,u])=>`<div><span>${l}</span><strong>${v.toLocaleString()}<small>${esc(u)}</small></strong></div>`).join('');
}

function renderChrome() {
  const stale=isStale(data.generated_at);
  const s=$('#status'); s.textContent=stale?'갱신 지연':'최신'; s.className='fresh'+(stale?' stale':'');
  const next=nextRun();
  $('#updated').textContent=`수집 ${hm(data.last_collection_at)} · 분석 ${hm(data.generated_at)}${next?` · 다음 수집 예정 ${hm(next)}`:''}`;
  $('#today-label').textContent=new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'long',day:'numeric',weekday:'long'}).format(new Date(data.generated_at));
  $('#last-success').textContent=`마지막 정상 RSS 수집 ${fmt(data.last_collection_at)}`;
  $('#notice').textContent=stale?'예정된 수집 시각이 1시간 넘게 지났는데 갱신되지 않았습니다. 지금 순위는 실시간이 아니며, 168시간이 지난 기사는 화면에서 숨깁니다.':(!data.last_collection_at?'아직 정상 수집 이력이 없습니다.':'');
  const active=data.publishers.filter(p=>!p.excluded&&!['held','no_confirmed_feed','excluded'].includes(p.status));
  const normal=active.filter(p=>p.status==='collected'||p.status==='empty_feed');
  const failed=active.filter(p=>p.status==='failed').map(p=>p.publisher);
  $('#health').innerHTML=`<span>매체 수집 ${normal.length} / ${active.length} 정상</span><span class="bar"><i style="width:${active.length?Math.round(100*normal.length/active.length):0}%"></i></span>${failed.length?`<span class="fail">실패: ${esc(failed.join(', '))}</span>`:''}`;
  $('#nav-issues').textContent=data.issues.length; $('#nav-articles').textContent=data.articles.length;
  $('#nav-briefings').textContent=data.briefings.length; $('#nav-sources').textContent=`${normal.length}/${active.length}`;
}

function render() {
  if($('#detail').open&&Number($('#detail').dataset.expires)<=Date.now())$('#detail').close();
  data=sanitize(data);articleMap=new Map(data.articles.map(a=>[a.id,a]));issueMap=new Map(data.issues.map(i=>[i.id,i]));
  renderChrome();renderToday();
  const selected=$('#publisher').value;
  $('#publisher').innerHTML='<option value="">전체 언론사</option>'+[...new Set(data.articles.map(a=>a.publisher))].sort().map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join('');$('#publisher').value=selected;
  renderRankings();renderArticles();renderCoverage();
  for(const [id,status] of [['uncovered','검색 범위 내 미발견'],['followups','후속 보도 검토']]) {
    const items=[...issueMap.values()].filter(i=>coverageStatus(i)===status).sort((a,b)=>b.importance_score-a.importance_score).slice(0,10);
    $('#'+id).innerHTML=items.map(i=>`<button type="button" class="item" data-issue="${esc(i.id)}"><strong>${esc(i.label)}</strong><span>${publisherCount(i)}개 매체 · 취재 가치 ${Number(i.importance_score||0).toFixed(1)}</span></button>`).join('')||empty('확인된 해당 이슈가 없습니다. 검색이 불완전하면 미보도로 판정하지 않습니다.');
  }
  $('#briefings').innerHTML=data.briefings.map((b,n)=>`<button type="button" class="item" data-brief="${n}"><strong>${fmt(b.scheduled_at)} ${b.kind==='am'?'오전':'오후'} 브리핑</strong><span>생성 ${fmt(b.generated_at)} · ${Math.round(b.delayed_minutes)}분 지연 · 이슈 ${Object.keys(b.entries||{}).length}건</span></button>`).join('')||empty('저장된 브리핑이 없습니다.');
  $('#alerts').innerHTML=data.alerts.slice(0,10).map(a=>`<button type="button" class="item" data-issue="${esc(a.issue_id)}"><strong>${esc(issueMap.get(a.issue_id)?.label)}</strong><span>${fmt(a.created_at)} · 후보 저장 / 미발송 · ${esc(a.reasons.join(' · '))}</span></button>`).join('')||empty('탐지 조건에 맞는 긴급 이슈 후보가 없습니다.');
  const status={deferred_budget:'시간 예산 보류',collected:'정상',empty_feed:'빈 피드',failed:'실패',held:'권한 보류',no_confirmed_feed:'RSS 미확인',stale_feed:'오래된 피드',not_verified:'미검증',excluded:'제외'};
  const order={failed:0,collected:1,empty_feed:1,stale_feed:2,deferred_budget:2,not_verified:3,held:4,no_confirmed_feed:5,excluded:6};
  $('#publishers').innerHTML=[...data.publishers].sort((a,b)=>(order[a.status]??3)-(order[b.status]??3)||a.publisher.localeCompare(b.publisher,'ko')).map(p=>`<div class="publisher" title="${esc(p.error||'')}"><span>${esc(p.publisher)}</span><span class="pill ${p.status==='failed'?'fail':['collected','empty_feed'].includes(p.status)?'ok':'wait'}">${p.excluded?'제외':status[p.status]||esc(p.status)}</span></div>`).join('');
  $('#catchup').textContent=data.catchup?.limitation||'';
  $('#errors').innerHTML=data.errors.map(e=>`<div class="item"><strong>${esc(e.phase)}</strong><span>${fmt(e.created_at)} · ${esc(e.message)}</span></div>`).join('')||empty('최근 7일 운영 오류가 없습니다.');
}

async function load() {
  let diagnostic='네트워크 연결 오류';
  try {
    const response=await fetch(new URL('dashboard.json',window.location.href),{cache:'no-store',credentials:'same-origin'});
    diagnostic=`HTTP ${response.status}`;
    if(!response.ok)throw new Error(diagnostic);
    if(!(response.headers.get('content-type')||'').includes('application/json')) {
      diagnostic='JSON 대신 HTML 응답: Access 세션 만료 또는 JSON 경로/배포 오류';throw new Error(diagnostic);
    }
    data=await response.json();render();
  }
  catch(error){const s=$('#status');s.textContent='불러오기 실패';s.className='fresh error';$('#notice').textContent=`dashboard.json 요청 실패 (${diagnostic}). 404: 데이터 배포 누락, 403: Access 인증 확인, 503: 서버 검증 설정 확인. 로그인 후 새로고침하고 문제가 계속되면 News operations 배포 결과를 확인하세요.`;}
}
function showView() {
  const view=(location.hash||'#today').slice(1);
  const known=[...document.querySelectorAll('[data-view]')].some(v=>v.dataset.view===view)?view:'today';
  document.querySelectorAll('[data-view]').forEach(v=>{v.hidden=v.dataset.view!==known;});
  document.querySelectorAll('[data-view-link]').forEach(a=>{if(a.dataset.viewLink===known)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
}
document.addEventListener('click', e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.ranking){ranking=b.dataset.ranking;renderRankings();}if(b.dataset.issue)showIssue(b.dataset.issue);if(b.dataset.brief!==undefined)showBrief(Number(b.dataset.brief));});
$('#coverage-filter').addEventListener('change',renderCoverage);
$('#close').addEventListener('click',()=>$('#detail').close());
$('#detail').addEventListener('click',e=>{if(e.target===$('#detail'))$('#detail').close();});
$('#reload').addEventListener('click',load);
$('#filters').addEventListener('input',()=>{page=30;renderArticles();});
$('#filters').addEventListener('reset',()=>setTimeout(()=>{page=30;renderArticles();},0));
$('#more').addEventListener('click',()=>{page+=30;renderArticles();});
$('#global-search').addEventListener('submit',e=>{e.preventDefault();$('#query').value=$('#global-query').value;page=30;if(data)renderArticles();location.hash='#articles';});
window.addEventListener('hashchange',showView);
showView();
setInterval(()=>{if(data)render();},60000);
setInterval(()=>{if(!document.hidden)load();},300000);
function applyTheme(theme) {
 document.documentElement.dataset.theme=theme;
 $('#theme').setAttribute('aria-pressed',String(theme==='dark'));
 $('#theme').textContent=theme==='dark'?'밝은 모드':'다크 모드';
}
let preferred;
try {preferred=localStorage.getItem('carmgz-theme');} catch {}
applyTheme(preferred==='dark'||preferred==='light'?preferred:(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'));
$('#theme').addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';applyTheme(next);try{localStorage.setItem('carmgz-theme',next);}catch{}});
load();
