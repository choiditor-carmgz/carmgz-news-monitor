"""Read-only API diagnostics. Never log secrets, raw response bodies or exceptions."""
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = 'https://api.cloudflare.com/client/v4'
PROJECT = 'carmgz-news-monitor'
EXPECTED_ACCOUNT = '76fdbe3d5abb7c6e7799a2292271ce6b'  # Public account identifier, not a credential.


class PreflightError(RuntimeError):
    """Messages must contain only application-controlled text."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def query(path, token, label):
    request = urllib.request.Request(API+path, headers={
        'Authorization': 'Bearer '+token, 'Accept': 'application/json',
        'User-Agent': 'CARMGZ-Cloudflare-preflight'})
    try:
        response = urllib.request.build_opener(NoRedirect()).open(request, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    except (urllib.error.URLError, OSError, ValueError):
        print(f'{label}: transport failure (TLS, DNS, timeout or connection); details withheld')
        return None, {}
    with response:
        status = response.code
        try:
            payload = json.loads(response.read(2_000_001))
        except (ValueError, OSError):
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    errors = payload.get('errors', [])
    codes = [e['code'] for e in errors[:10] if isinstance(e, dict) and type(e.get('code')) is int] if isinstance(errors, list) else []
    print(f'{label}: HTTP {status}; error_codes={codes}')
    return status, payload


def active(status, payload):
    result = payload.get('result')
    return status == 200 and payload.get('success') is True and isinstance(result, dict) and result.get('status') == 'active'


def main():
    account = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
    token = os.environ.get('CLOUDFLARE_API_TOKEN', '')
    if not re.fullmatch(r'[a-f0-9]{32}', account):
        raise PreflightError('Invalid CLOUDFLARE_ACCOUNT_ID format; value withheld')
    if account != EXPECTED_ACCOUNT:
        raise PreflightError('Account ID does not match the existing Pages account; value withheld')
    # Reject instead of trimming: Wrangler must use exactly the same Secret value.
    if not token or not re.fullmatch(r'[A-Za-z0-9_.~-]+', token):
        raise PreflightError('Invalid API token format: store only the raw token, without Bearer prefix, quotes or whitespace; value withheld')
    print(f'Target: expected Account ID matched; project={PROJECT}; authentication=Bearer API token')
    print('API: GET /user/tokens/verify; fallback GET /accounts/{account_id}/tokens/verify; GET /accounts/{account_id}/pages/projects/'+PROJECT)
    status, payload = query('/user/tokens/verify', token, 'User token verification')
    verified = active(status, payload)
    if not verified:
        status, payload = query(f'/accounts/{account}/tokens/verify', token, 'Account token verification')
        verified = active(status, payload)
    print('Token verification: '+('active' if verified else 'not confirmed; Pages access is checked separately'))
    status, payload = query(f'/accounts/{account}/pages/projects/{PROJECT}', token, 'Pages project lookup')
    if status != 200 or payload.get('success') is not True:
        if verified:
            raise PreflightError('Active token, but Pages lookup failed: check account resource scope, Pages permission, project name and token restrictions')
        raise PreflightError('API authentication/access not confirmed: check effective GitHub Secret, token value/type, expiry, revocation and IP restrictions')
    project = payload.get('result')
    if not isinstance(project, dict) or project.get('name') != PROJECT:
        raise PreflightError('Pages response project name does not match the deployment target')
    print('Pages API authentication and project lookup succeeded (this does not test deployment write access)')
    if project.get('production_branch') != 'main':
        raise PreflightError('Existing Pages production branch must be main; refuse preview with production data')
    variables = project.get('deployment_configs', {}).get('production', {}).get('env_vars', {})
    for name in ('CF_ACCESS_TEAM_DOMAIN', 'CF_ACCESS_AUD'):
        item = variables.get(name, {})
        if not item or (item.get('type') != 'secret_text' and not item.get('value')):
            raise PreflightError('Configure existing Access verification variable in Pages production: '+name)
    print('Existing Pages project and Access verification bindings confirmed')


def cli():
    try:
        main()
    except PreflightError as exc:
        print('Cloudflare preflight failed: '+str(exc), file=sys.stderr)
        return 1
    except Exception:
        print('Cloudflare preflight failed: unexpected response or local error; details withheld', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(cli())
