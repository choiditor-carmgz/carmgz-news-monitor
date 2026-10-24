// Pure browser-data tests; all fixtures are synthetic and stay out of deployments.
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code=fs.readFileSync('web/app.js','utf8').split("document.addEventListener('click'")[0];
const ctx=vm.createContext({document:{querySelector:()=>null},Intl,URL,console});
vm.runInContext(code,ctx);
test('expired and future articles, expired briefings, stale alert references are hidden',()=>{
  ctx.fixture={articles:[{id:'live',published_at:'2026-10-23T00:00:00Z'},{id:'old',published_at:'2026-10-16T00:00:00Z'},{id:'future',published_at:'2026-10-24T00:00:00Z'}],
    issues:[{id:'yes',article_ids:['live','old']},{id:'no',article_ids:['old']}],
    briefings:[{expires_at:'2026-10-23T01:00:00Z'},{expires_at:'2026-10-23T00:00:00Z'}],
    alerts:[{issue_id:'yes',created_at:'2026-10-23T00:00:00Z'},{issue_id:'no',created_at:'2026-10-23T00:00:00Z'}]};
  const out=vm.runInContext("sanitize(fixture,Date.parse('2026-10-23T00:00:00Z'))",ctx);
  assert.deepEqual(Array.from(out.articles,a=>a.id),['live']);
  assert.equal(out.issues.length,1);assert.equal(out.issues[0].article_ids.length,1);
  assert.equal(out.briefings.length,1);assert.equal(out.alerts.length,1);
});
test('untrusted feed titles and unsafe URLs cannot insert executable HTML',()=>{
  assert.equal(vm.runInContext("esc('<script>\"&')",ctx),'&lt;script&gt;&quot;&amp;');
  assert.equal(vm.runInContext("link('javascript:alert(1)')",ctx),'#');
  assert.equal(vm.runInContext("link('https://example.org/a')",ctx),'https://example.org/a');
});
test('dates are filtered using KST across a UTC day boundary',()=>{
  assert.equal(vm.runInContext("day('2026-10-22T16:00:00Z')",ctx),'2026-10-23');
});
test('coverage filters preserve uncertain and not-checked issues',()=>{
  assert.equal(vm.runInContext("coverageMatches({},'uncertain')",ctx),true);
  assert.equal(vm.runInContext("coverageMatches({carmgz:{status:'확인 필요'}},'uncertain')",ctx),true);
  assert.equal(vm.runInContext("coverageMatches({carmgz:{status:'확인 불가'}},'미보도')",ctx),false);
  assert.equal(vm.runInContext("coverageMatches({carmgz:{status:'보도 완료'}},'보도 완료')",ctx),true);
});
test('coverage evidence renders safe source links and no raw HTML',()=>{
  ctx.item={carmgz:{status:'확인 필요',reason:'<script>alert(1)</script>',matches:[{title:'<img>',url:'javascript:alert(1)',reason:'fixture'}]}};
  const html=vm.runInContext('coverageDetail(item)',ctx);
  assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('href="#"'));
  assert.equal(html.includes('<script>'),false);
});

test('search waiting, failure and bounded absence are distinct without asserting uncovered',()=>{
  assert.equal(vm.runInContext('coverageStatus({})',ctx),'검색 대기');
  assert.equal(vm.runInContext("coverageStatus({carmgz:{checked_at:'2026-10-23',search_success:false}})",ctx),'검색 실패');
  assert.equal(vm.runInContext("coverageStatus({carmgz:{checked_at:'2026-10-23',search_success:true}})",ctx),'검색 범위 내 미발견');
  assert.equal(vm.runInContext("coverageStatus({carmgz:{checked_at:'2026-10-23',search_success:true,errors:['fixture']}})",ctx),'검색 실패');
});

test('coverage filter cannot hide top candidates and selection reasons remain escaped',()=>{
  const elements=new Map();
  const local=vm.createContext({Intl,URL,console,document:{querySelectorAll:()=>[],querySelector:s=>{
    if(!elements.has(s))elements.set(s,{value:''});return elements.get(s);
  }}});
  vm.runInContext(code,local);
  vm.runInContext(`data={generated_at:'2026-10-23T00:00:00Z',rankings:{major:['x']}};
    issueMap=new Map([['x',{id:'x',label:'important',article_ids:[],volume_3h:0,importance_score:80,
    selection_reasons:['<img src=x onerror=alert(1)>'],carmgz:{display_status:'검색 실패'}}]]);
    renderRankings();`,local);
  const first=elements.get('#rankings').innerHTML;
  elements.set('#coverage-filter',{value:'보도 완료'});
  vm.runInContext('renderRankings()',local);
  assert.equal(elements.get('#rankings').innerHTML,first);
  assert.ok(first.includes('important'));assert.ok(first.includes('&lt;img'));
  assert.equal(first.includes('<img'),false);
});

test('missing JSON and Pages HTML fallback show actionable diagnostics',async()=>{
  for(const [status,type,expected] of [[404,'text/html','HTTP 404'],[200,'text/html','JSON 대신 HTML']]) {
    const elements=new Map();
    const local=vm.createContext({Intl,URL,console,window:{location:{href:'https://example.pages.dev/'}},
      document:{querySelector:s=>{if(!elements.has(s))elements.set(s,{});return elements.get(s);}},
      fetch:async(url,options)=>{
        assert.equal(String(url),'https://example.pages.dev/dashboard.json');
        assert.equal(options.credentials,'same-origin');
        return {ok:status===200,status,headers:{get:()=>type}};
      }});
    vm.runInContext(code,local);await vm.runInContext('load()',local);
    assert.ok(elements.get('#notice').textContent.includes(expected));
  }
});
