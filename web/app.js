'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = s => s ? new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(s)) : '데이터 없음';
const day = s => s ? new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(s)) : '';
const link = url => {try {const u=new URL(url); return ['https:','http:'].includes(u.protocol)?esc(u.href):'#';}catch{return '#';}};
const empty = text => `<div class="empty">${esc(text)}</div>`;
const labels = {major:'오늘의 주요 뉴스',spread:'언론 확산도',rising:'급상승 이슈',industry:'산업 중요도'};
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

function coverageMatches(i, status) {
  const current=i.carmgz?.status||'확인 불가';
  return !status || (status==='uncertain'?['확인 필요','확인 불가'].includes(current):current===status);
}
function coverageDetail(i) {
 const c=i.carmgz||{status:'확인 불가',reason:'검색 결과 없음',matches:[]};
 return `<h3>CARMGZ: ${esc(c.status)}</h3><p>${esc(c.reason)}<br><span class="meta">마지막 확인 ${fmt(c.checked_at)} · 과거 검색 날짜 제한 없음<br>${esc(c.scope)}</span></p><ul>${(c.matches||[]).map(a=>`<li><a href="${link(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a><div class="meta">${fmt(a.published_at)} · ${esc(a.assessment)} · ${esc(a.reason)}</div></li>`).join('')}</ul>`;
}
function renderCoverage() {
 const items=[...issueMap.values()].filter(i=>coverageMatches(i,$('#coverage-filter').value)).sort((a,b)=>b.importance_score-a.importance_score||a.id.localeCompare(b.id));
 $('#coverage-issues').innerHTML=items.map(i=>`<button class="brief" data-issue="${esc(i.id)}"><strong>${esc(i.label)}</strong><span class="meta">${esc(i.carmgz?.status||'확인 불가')} · ${i.article_ids.length}기사 / ${i.independent_publishers}매체 · ${esc(i.carmgz?.reason||'검색 결과 없음')}</span></button>`).join('')||empty('조건에 맞는 이슈 없음');
}
function renderRankings() {
  document.querySelectorAll('[data-ranking]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.ranking===ranking)));
  const notes={major:'오늘 발행된 기사 중 산업 중요도·24시간 보도량 순입니다.',spread:'서로 다른 매체 수 × 10 + 기사 수. 자체 취재 독립성은 미검증입니다.',rising:'최근 1시간 보도가 있고 직전 2시간 대비 시간당 보도량이 증가한 이슈입니다.',industry:'안전·정책·생산·핵심 기술·해외 확장 규칙 점수입니다. 기사 수와 별개입니다.'};
  $('#ranking-note').textContent=notes[ranking]+` 집계 시각 ${fmt(data.generated_at)}.`;
  const items=(data.rankings[ranking]||[]).map(id=>issueMap.get(id)).filter(Boolean).filter(i=>coverageMatches(i,$('#coverage-filter').value));
  $('#rankings').innerHTML=items.map((i,n)=>`<button type="button" class="issue" data-issue="${esc(i.id)}"><span class="number">${String(n+1).padStart(2,'0')}</span><div><h3>${esc(i.label)}</h3><span class="badge">CARMGZ ${esc(i.carmgz?.status||'확인 불가')}</span><div class="meta">관련 기사 <b>${i.article_ids.length}</b> · 매체 <b>${new Set(i.article_ids.map(id=>articleMap.get(id)?.publisher)).size}</b>곳 · 3시간 ${i.volume_3h}건</div><span class="score">${ranking==='industry'||ranking==='major'?`산업 중요도 ${i.importance_score}점`:ranking==='rising'?`시간당 증가 ${i.growth_per_hour}건`:`확산 점수 ${i.spread_score}`}</span></div></button>`).join('')||empty('선정 조건에 맞는 이슈가 없습니다. TOP 10을 임의로 채우지 않습니다.');
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
  return `<svg class="chart" viewBox="0 0 600 145" role="img" aria-label="집계 시각 이전 24시간 시간별 보도량: ${v.join(', ')}"><line x1="16" y1="118" x2="584" y2="118" stroke="#dce3de"/>${v.map((n,k)=>`<rect x="${17+k*23.6}" y="${118-n/max*90}" width="17" height="${n/max*90}" fill="#43806a"><title>${24-k}~${23-k}시간 전: ${n}건</title></rect>`).join('')}<text x="17" y="137" font-size="10" fill="#667574">24시간 전</text><text x="530" y="137" font-size="10" fill="#667574">집계 시각</text></svg>`;
}

function showIssue(id) {
  const i=issueMap.get(id);if(!i)return;
  $('#detail').dataset.expires=String(Math.min(...i.article_ids.map(id=>Date.parse(articleMap.get(id).published_at||articleMap.get(id).first_collected_at)+168*3600000)));
  const reaction = field => i[field]===null?'데이터 없음':`${i[field].toLocaleString()} (${i[field+'_coverage']}/${i.article_count}건 확보)`;
  const ratio=i.growth_ratio_3h===null?'기준 보도량 없음':`${i.growth_ratio_3h.toFixed(2)}배`;
  $('#detail-body').innerHTML=`<p class="eyebrow">ISSUE DETAIL</p><h2>${esc(i.label)}</h2><p class="meta">표본 내 최초 ${fmt(i.first_published_at)} · ${esc(i.publishers.join(', '))}</p><div class="metrics"><span>1시간 <b>${i.volume_1h}</b>건</span><span>3시간 <b>${i.volume_3h}</b>건</span><span>24시간 <b>${i.volume_24h}</b>건</span><span>직전 3시간 대비 ${ratio}</span><span>산업 중요도 ${i.importance_score}점</span></div><h3>시간별 보도량</h3>${chart(i)}<p class="caption">${fmt(data.generated_at)} 기준 · 실제 독자 관심도를 의미하지 않습니다.</p><p class="meta">전재율: 데이터 없음 · 유사 제목 쌍 비율: ${i.similar_title_pair_ratio===null?'데이터 없음':(i.similar_title_pair_ratio*100).toFixed(1)+'%'}<br>조회수: ${reaction('views')} · 댓글: ${reaction('comments')}</p><p class="meta">통합 근거: ${esc(i.grouping_basis)}<br>산업 중요도: ${esc(i.importance_reasons.map(r=>`${r.criterion} ${r.points}점`).join(' / ')||'해당 규칙 없음')}</p>${coverageDetail(i)}<h3>관련 기사 ${i.article_ids.length}건</h3><ul>${i.article_ids.map(id=>articleMap.get(id)).filter(Boolean).map(a=>`<li><a href="${link(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a><div class="meta">${esc(a.publisher)} · ${fmt(a.published_at)}</div></li>`).join('')}</ul>`;
  $('#detail').showModal();
}

function showBrief(n) {
  const b=data.briefings[n]; if(!b)return;
  $('#detail').dataset.expires=String(Date.parse(b.expires_at));
  $('#detail-body').innerHTML=`<p class="eyebrow">DAILY BRIEFING</p><h2>${fmt(b.scheduled_at)} ${b.kind==='am'?'오전':'오후'} 브리핑</h2><p class="meta">실제 생성 ${fmt(b.generated_at)} · 마지막 정상 수집 ${fmt(b.last_collection_at)}<br>지연 ${Math.round(b.delayed_minutes)}분 · 전일 기준이 없으면 변화는 비교 불가로 표시합니다.</p>${Object.entries(b.rankings).map(([k,ids])=>`<h3>${labels[k]}</h3><ol>${ids.map(id=>({id,...(b.entries?.[id]||{label:issueMap.get(id)?.label||'만료 이슈',article_count:issueMap.get(id)?.article_count||0,publishers:issueMap.get(id)?.independent_publishers||0})})).map(i=>`<li><button class="brief" data-issue="${esc(i.id)}">${esc(i.label)} <span class="meta">생성 당시 ${i.article_count}건 / ${i.publishers}매체</span></button></li>`).join('')||'<li>확보한 이슈 없음</li>'}</ol>`).join('')}${Object.entries(b.coverage_lists||{}).map(([status,ids])=>`<h3>CARMGZ ${esc(status)}</h3><ul>${ids.map(id=>`<li>${esc(b.entries?.[id]?.label||issueMap.get(id)?.label||'만료 이슈')}</li>`).join('')||'<li>확인된 해당 이슈 없음</li>'}</ul>`).join('')}<h3>전일 대비 변화</h3><ul>${b.changes.map(c=>`<li>${esc(c.label)} · ${c.comparison==='전일 기준 데이터 없음'?'전일 기준 데이터 없음':`${c.new?'새 이슈 · ':''}기사 증감 ${c.article_delta>0?'+':''}${c.article_delta}`}</li>`).join('')||'<li>비교할 이슈 없음</li>'}</ul><h3>후속 확인 필요</h3><ul>${b.follow_up.map(f=>`<li>${esc(issueMap.get(f.issue_id)?.label||'만료 이슈')} · ${esc(f.reason)}</li>`).join('')||'<li>해당 이슈 없음</li>'}</ul>`;
  $('#detail').showModal();
}

function render() {
  if($('#detail').open&&Number($('#detail').dataset.expires)<=Date.now())$('#detail').close();
  data=sanitize(data);articleMap=new Map(data.articles.map(a=>[a.id,a]));issueMap=new Map(data.issues.map(i=>[i.id,i]));
  const stale=Date.now()-Date.parse(data.generated_at)>6*3600000;
  $('#status').textContent=stale?'갱신 지연 · 저장된 데이터':'수집 결과 확인됨';
  $('#updated').textContent=`데이터 갱신 ${fmt(data.generated_at)} KST`;
  $('#last-success').textContent=`마지막 정상 RSS 수집 ${fmt(data.last_collection_at)}`;
  $('#notice').textContent=stale?'6시간 이상 갱신되지 않았습니다. 현재 실시간 순위가 아니며 168시간이 지난 기사는 화면에서 숨깁니다.':(!data.last_collection_at?'아직 정상 수집 이력이 없습니다.':'');
  const normal=data.publishers.filter(p=>p.status==='collected'||p.status==='empty_feed').length;
  $('#stats').innerHTML=[['최근 7일 관련 기사',data.articles.length],['추적 중인 이슈',data.issues.length],['정상 응답 매체',normal],['긴급 이슈 후보',data.alerts.length]].map(([l,v])=>`<div class="stat"><span>${l}</span><strong>${v.toLocaleString()}</strong></div>`).join('');
  const selected=$('#publisher').value;
  $('#publisher').innerHTML='<option value="">전체 언론사</option>'+[...new Set(data.articles.map(a=>a.publisher))].sort().map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join('');$('#publisher').value=selected;
  renderRankings();renderArticles();renderCoverage();
  for(const [id,status] of [['uncovered','미보도'],['followups','후속 보도 검토']]) {
    const items=[...issueMap.values()].filter(i=>i.carmgz?.status===status).sort((a,b)=>b.importance_score-a.importance_score).slice(0,10);
    $('#'+id).innerHTML=items.map(i=>`<button class="brief" data-issue="${esc(i.id)}">${esc(i.label)}</button>`).join('')||empty('확인된 해당 이슈 없음. 검색 불완전은 미보도로 판정하지 않습니다.');
  }
  $('#briefings').innerHTML=data.briefings.map((b,n)=>`<button class="brief" data-brief="${n}"><strong>${fmt(b.scheduled_at)} ${b.kind==='am'?'오전':'오후'} 브리핑 ↗</strong><span class="meta">생성 ${fmt(b.generated_at)} · ${Math.round(b.delayed_minutes)}분 지연</span></button>`).join('')||empty('저장된 브리핑이 없습니다.');
  $('#alerts').innerHTML=data.alerts.slice(0,10).map(a=>`<button class="brief" data-issue="${esc(a.issue_id)}"><strong>${esc(issueMap.get(a.issue_id)?.label)}</strong><span class="meta">${fmt(a.created_at)} · 후보 저장 / 미발송<br>${esc(a.reasons.join(' · '))}</span></button>`).join('')||empty('탐지 조건에 맞는 긴급 이슈 후보가 없습니다.');
  const status={deferred_budget:'시간 예산 보류',collected:'정상',empty_feed:'빈 피드',failed:'실패',held:'권한 보류',no_confirmed_feed:'RSS 미확인',stale_feed:'오래된 피드',not_verified:'미검증',excluded:'제외'};
  $('#publishers').innerHTML=data.publishers.map(p=>`<div class="publisher" title="${esc(p.error||'')}"><span>${esc(p.publisher)}</span><span class="badge ${p.status==='failed'?'fail':['collected','empty_feed'].includes(p.status)?'ok':''}">${p.excluded?'제외':status[p.status]||esc(p.status)}</span></div>`).join('');
  $('#catchup').textContent=data.catchup?.limitation||'';
  $('#errors').innerHTML=data.errors.map(e=>`<p>${fmt(e.created_at)} · ${esc(e.phase)} · ${esc(e.message)}</p>`).join('');
}

async function load() {
  try {const response=await fetch('dashboard.json',{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`); data=await response.json();render();}
  catch(error){$('#status').textContent='데이터를 불러오지 못했습니다';$('#notice').textContent='dashboard.json이 아직 생성되지 않았거나 네트워크 오류가 있습니다. 운영 명령을 실행한 뒤 다시 시도하세요.';}
}
document.addEventListener('click', e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.ranking){ranking=b.dataset.ranking;renderRankings();}if(b.dataset.issue){if($('#detail').open)$('#detail').close();showIssue(b.dataset.issue);}if(b.dataset.brief!==undefined)showBrief(Number(b.dataset.brief));});
$('#coverage-filter').addEventListener('change',()=>{renderRankings();renderCoverage();});
$('#close').addEventListener('click',()=>$('#detail').close());
$('#reload').addEventListener('click',load);
$('#filters').addEventListener('input',()=>{page=30;renderArticles();});
$('#filters').addEventListener('reset',()=>setTimeout(()=>{page=30;renderArticles();},0));
$('#more').addEventListener('click',()=>{page+=30;renderArticles();});
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
