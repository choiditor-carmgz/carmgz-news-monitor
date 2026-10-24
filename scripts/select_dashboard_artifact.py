"""Allow runtime-only redeployment of a successful main News operations snapshot."""
import json
import os
import re
import urllib.request


def main():
    run_id = os.environ.get('SOURCE_RUN_ID', '')
    if not re.fullmatch(r'[0-9]+', run_id):
        raise ValueError('A numeric successful main run ID is required')
    request = urllib.request.Request(
        f'https://api.github.com/repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{run_id}',
        headers={'Authorization': 'Bearer '+os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        run = json.load(response)
    if (run.get('head_branch') != 'main' or run.get('conclusion') != 'success'
            or run.get('path') != '.github/workflows/operations.yml'):
        raise ValueError('Source must be a successful main News operations run')
    print('Verified existing main dashboard artifact source run: '+run_id)


if __name__ == '__main__':
    main()
