"""Read-only deployment preflight; never log credentials or API response bodies."""
import json
import os
import re
import urllib.request


def main():
    account = os.environ['CLOUDFLARE_ACCOUNT_ID']
    token = os.environ['CLOUDFLARE_API_TOKEN']
    if not re.fullmatch(r'[a-f0-9]{32}', account):
        raise ValueError('Invalid CLOUDFLARE_ACCOUNT_ID')
    request = urllib.request.Request(
        f'https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects/carmgz-news-monitor',
        headers={'Authorization': 'Bearer '+token, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if not result.get('success'):
        raise RuntimeError('Cannot read existing Cloudflare Pages project')
    project = result['result']
    if project.get('production_branch') != 'main':
        raise ValueError('Existing Pages production branch must be main; refuse preview with production data')
    variables = project.get('deployment_configs', {}).get('production', {}).get('env_vars', {})
    for name in ('CF_ACCESS_TEAM_DOMAIN', 'CF_ACCESS_AUD'):
        item = variables.get(name, {})
        if not item or (item.get('type') != 'secret_text' and not item.get('value')):
            raise ValueError('Configure existing Access verification variable in Pages production: '+name)
    print('Existing Pages project and Access verification bindings confirmed')


if __name__ == '__main__':
    main()
