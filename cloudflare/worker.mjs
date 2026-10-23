// Every asset, including JSON on deployment aliases, requires the existing Access app JWT.
import { createRemoteJWKSet, jwtVerify } from 'jose';

const keySets = new Map();
export function createHandler(resolveKeys = issuer => {
  if (!keySets.has(issuer)) keySets.set(issuer, createRemoteJWKSet(new URL(`${issuer}/cdn-cgi/access/certs`)));
  return keySets.get(issuer);
}) {
  return async (request, env) => {
    const issuer = env.CF_ACCESS_TEAM_DOMAIN?.replace(/\/$/, '');
    const audience = env.CF_ACCESS_AUD;
    const headers = {'Cache-Control': 'private, no-store', 'Vary': 'Cf-Access-Jwt-Assertion, Cookie'};
    if (!/^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/.test(issuer || '') || !audience) {
      return new Response('Access verification is not configured', {status: 503, headers});
    }
    try {
      await jwtVerify(request.headers.get('Cf-Access-Jwt-Assertion') || '', resolveKeys(issuer), {
        issuer, audience, algorithms: ['RS256'], requiredClaims: ['exp', 'iat', 'sub'],
      });
    } catch {
      return new Response('Forbidden', {status: 403, headers});
    }
    const asset = await env.ASSETS.fetch(request);
    const response = new Response(asset.body, asset);
    for (const [key, value] of Object.entries(headers)) response.headers.set(key, value);
    response.headers.set('X-Content-Type-Options', 'nosniff');
    return response;
  };
}

export default {fetch: createHandler()};
