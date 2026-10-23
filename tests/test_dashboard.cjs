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
