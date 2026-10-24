"""Read-only Pages deployment metadata. Never print binding values or API bodies."""
import os
import sys
if __package__:
    from .check_cloudflare import query, PROJECT, EXPECTED_ACCOUNT
else:
    from check_cloudflare import query, PROJECT, EXPECTED_ACCOUNT


def binding_flags(config):
    config = config if isinstance(config, dict) else {}
    variables = config.get('env_vars') or {}
    variables = variables if isinstance(variables, dict) else {}
    return {name: {'present': name in variables,
                   'secret': isinstance(variables.get(name), dict) and variables[name].get('type') == 'secret_text'}
            for name in ('CF_ACCESS_TEAM_DOMAIN', 'CF_ACCESS_AUD')}


def main():
    account = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    token = os.environ.get('CLOUDFLARE_API_TOKEN', '')
    if account != EXPECTED_ACCOUNT or not token:
        return 1
    root = f'/accounts/{account}/pages/projects/{PROJECT}'
    status, payload = query(root, token, 'Runtime project metadata')
    if status != 200 or not payload.get('success'):
        return 1
    project = payload['result']
    import json
    for environment in ('production', 'preview'):
        config = (project.get('deployment_configs') or {}).get(environment)
        print(environment+' binding metadata: '+json.dumps(binding_flags(config)))
    canonical = project.get('canonical_deployment') or {}
    print('Canonical deployment environment: '+str(canonical.get('environment')))
    print('Canonical deployment binding metadata: '+json.dumps(binding_flags(canonical)))
    identifier = canonical.get('id')
    if identifier:
        status, payload = query(root+'/deployments/'+identifier, token, 'Canonical deployment metadata')
        if status == 200 and payload.get('success'):
            deployment = payload['result']
            print('Deployed binding metadata: '+json.dumps(binding_flags(deployment)))
            print('Production branch matches main: '+str((deployment.get('deployment_trigger') or {}).get('metadata', {}).get('branch') == 'main'))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('Runtime metadata inspection failed; remote details withheld')
        sys.exit(1)
