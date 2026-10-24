// Every asset, including JSON on deployment aliases, requires the existing Access app JWT.
import { createRemoteJWKSet, jwtVerify } from 'jose';

const keySets = new Map();
export function accessConfig(env) {
  const rawTeam = typeof env.CF_ACCESS_TEAM_DOMAIN === 'string' ? env.CF_ACCESS_TEAM_DOMAIN : '';
  const rawAudience = typeof env.CF_ACCESS_AUD === 'string' ? env.CF_ACCESS_AUD : '';
  const team = rawTeam.trim().replace(/\/$/, '');
  const issuer = team.startsWith('https://') ? team : `https://${team}`;
  const valid = /^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/.test(issuer);
  return {issuer, audience: rawAudience.trim(), flags: {
    team_present: Boolean(rawTeam), audience_present: Boolean(rawAudience),
    team_original_format_valid: /^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com\/?$/.test(rawTeam),
    team_normalized_valid: valid, audience_nonempty: Boolean(rawAudience.trim()),
    assets_present: typeof env.ASSETS?.fetch === 'function',
  }};
}

export function createHandler(resolveKeys = issuer => {
  if (!keySets.has(issuer)) keySets.set(issuer, createRemoteJWKSet(new URL(`${issuer}/cdn-cgi/access/certs`)));
  return keySets.get(issuer);
}) {
  return async (request, env) => {
    const {issuer, audience, flags} = accessConfig(env);
    const headers = {'Cache-Control': 'private, no-store', 'Vary': 'Cf-Access-Jwt-Assertion, Cookie'};
    if (!flags.team_normalized_valid || !audience) {
      return new Response('Access verification is not configured\n'+JSON.stringify(flags), {status: 503, headers});
    }
    try {
      await jwtVerify(request.headers.get('Cf-Access-Jwt-Assertion') || '', resolveKeys(issuer), {
        issuer, audience, algorithms: ['RS256'], requiredClaims: ['exp', 'iat', 'sub'],
      });
    } catch {
      return new Response('Forbidden', {status: 403, headers});
    }
    if (new URL(request.url).pathname === '/__diagnostics/access-config') {
      return Response.json({revision: 'access-runtime-v2', authenticated: true, ...flags}, {headers});
    }
    const asset = await env.ASSETS.fetch(request);
    const response = new Response(asset.body, asset);
    for (const [key, value] of Object.entries(headers)) response.headers.set(key, value);
    response.headers.set('X-Content-Type-Options', 'nosniff');
    return response;
  };
}

export default {fetch: createHandler()};
