import test from 'node:test';
import assert from 'node:assert/strict';
import {generateKeyPair, SignJWT, createLocalJWKSet, exportJWK} from 'jose';
import {createHandler} from '../cloudflare/worker.mjs';

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
