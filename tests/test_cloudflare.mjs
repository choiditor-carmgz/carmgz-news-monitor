import test from 'node:test';
import assert from 'node:assert/strict';
import {generateKeyPair, SignJWT, createLocalJWKSet, exportJWK} from 'jose';
import {createHandler, accessConfig} from '../cloudflare/worker.mjs';

const {publicKey, privateKey} = await generateKeyPair('RS256');
const jwk = {...await exportJWK(publicKey), kid:'test'};
const handler = createHandler(() => createLocalJWKSet({keys:[jwk]}));
const issuer='https://test-team.cloudflareaccess.com';
let assetCalls=0;
const env={CF_ACCESS_TEAM_DOMAIN:issuer,CF_ACCESS_AUD:'test-aud',ASSETS:{fetch:async()=>{
  assetCalls++; return new Response('{"data_kind":"real_rss"}',{headers:{'Content-Type':'application/json'}});
}}};
async function token(overrides={}, key=privateKey) {
  return new SignJWT({iss:issuer,aud:'test-aud',sub:'test-user',iat:Math.floor(Date.now()/1000),exp:Math.floor(Date.now()/1000)+120,...overrides})
    .setProtectedHeader({alg:'RS256',kid:'test'}).sign(key);
}
function request(path, jwt) {
  return new Request('https://preview.example.pages.dev'+path,{headers:jwt?{'Cf-Access-Jwt-Assertion':jwt}:{}});
}
test('all asset paths and preview aliases deny unauthenticated requests before ASSETS',async()=>{
  const before=assetCalls;
  for(const path of ['/','/dashboard.json','/app.js','/nested/dashboard.json']) {
    assert.equal((await handler(request(path),env)).status,403);
  }
  assert.equal(assetCalls,before);
});
test('missing verification configuration fails closed',async()=>{
  assert.equal((await handler(request('/dashboard.json'),{...env,CF_ACCESS_AUD:''})).status,503);
});
test('signed Access token allows same-origin JSON with private no-store headers',async()=>{
  const r=await handler(request('/dashboard.json',await token()),env);
  assert.equal(r.status,200);assert.equal(r.headers.get('Cache-Control'),'private, no-store');
  assert.equal((await r.json()).data_kind,'real_rss');
});
test('forged, expired, wrong issuer/audience and future tokens cannot read assets',async()=>{
  const {privateKey:wrongKey}=await generateKeyPair('RS256');
  const before=assetCalls;
  for(const jwt of ['forged',await token({},wrongKey),await token({exp:1}),await token({iss:'https://other.cloudflareaccess.com'}),
    await token({aud:'other'}),await token({nbf:Math.floor(Date.now()/1000)+600})]) {
    assert.equal((await handler(request('/dashboard.json',jwt),env)).status,403);
  }
  assert.equal(assetCalls,before);
});

test('Pages Secret bare team domain and surrounding whitespace normalize to the exact issuer',async()=>{
  const jwt=await token();
  for(const team of ['test-team.cloudflareaccess.com',' test-team.cloudflareaccess.com\n',' https://test-team.cloudflareaccess.com/ ']) {
    const response=await handler(request('/dashboard.json',jwt),{...env,CF_ACCESS_TEAM_DOMAIN:team,CF_ACCESS_AUD:' test-aud\n'});
    assert.equal(response.status,200);
    assert.equal((await response.json()).data_kind,'real_rss');
  }
  assert.equal((await handler(request('/',jwt),{...env,CF_ACCESS_AUD:'"test-aud"'})).status,200);
});

test('normalization rejects other origins, protocols and URL paths without serving assets',async()=>{
  const before=assetCalls;
  for(const team of ['http://test-team.cloudflareaccess.com','https://test-team.cloudflareaccess.com.evil.test',
    'https://evil.test@test-team.cloudflareaccess.com','https://test-team.cloudflareaccess.com/path','https://evil.test']) {
    const response=await handler(request('/',await token()),{...env,CF_ACCESS_TEAM_DOMAIN:team});
    assert.equal(response.status,503);
    assert.equal((await response.text()).includes(team),false);
  }
  assert.equal(assetCalls,before);
});

test('runtime diagnostic requires valid Access JWT and exposes only boolean flags and revision',async()=>{
  assert.equal((await handler(request('/__diagnostics/access-config'),env)).status,403);
  const response=await handler(request('/__diagnostics/access-config',await token()),env);
  const d=await response.json();
  assert.equal(d.authenticated,true);assert.equal(d.assets_present,true);
  assert.equal(d.team_original_format_valid,true);
  assert.equal(JSON.stringify(d).includes(issuer),false);
  assert.equal(JSON.stringify(d).includes(env.CF_ACCESS_AUD),false);
  const flags=accessConfig({...env,CF_ACCESS_TEAM_DOMAIN:'test-team.cloudflareaccess.com'}).flags;
  assert.equal(flags.team_original_format_valid,false);assert.equal(flags.team_normalized_valid,true);
  const failed=await handler(request('/__diagnostics/access-config',await token({aud:'other-app'})),env);
  assert.equal(failed.status,403);
  const diagnostics=await failed.json();
  assert.equal(diagnostics.claim,'aud');assert.equal(diagnostics.assertion_present,true);
  assert.equal(JSON.stringify(diagnostics).includes('other-app'),false);
});
