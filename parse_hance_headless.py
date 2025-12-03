import requests
import os
import json
from typing import Dict, List


def _human_size(bytesize: int) -> str:
    if bytesize is None:
        return ''
    try:
        b = int(bytesize)
        if b <= 0:
            return '0 B'
        for unit in ['B', 'KB', 'MB', 'GB']:
            if b < 1024 or unit == 'GB':
                if unit == 'B':
                    return f"{b} {unit}"
                return f"{b/1024.0:.2f} {unit}"
            b = b / 1024.0
    except Exception:
        return ''


def parse_hance_models():
    """Return a mapping of 'Hance Models' -> list of model dicts found in
    the GitHub repository `hance-engine/hance-api` under `Models/`.

    Uses the GitHub git/trees API to recursively find files under Models/.
    """
    owner = 'hance-engine'
    repo = 'hance-api'
    branch = 'main'
    api_tree = f'https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1'
    # Try the tree endpoint for a single recursive listing
    headers = {'User-Agent': 'VAICCS-Hance-Parser/1.0'}
    gh_token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if gh_token:
        headers['Authorization'] = f'token {gh_token}'
    try:
        r = requests.get(api_tree, timeout=20, headers=headers)
        r.raise_for_status()
        data = r.json()
    except Exception:
        # Fallback to contents API (non-recursive) with manual recursion
        data = None
    items = []
    allowed_exts = ('.hance', '.onnx', '.tflite', '.pt', '.pth', '.pb', '.tar.gz', '.tgz', '.zip', '.tar', '.tar.bz2', '.tar.xz', '.7z', '.bin', '.gz')
    items = []
    if isinstance(data, dict) and data.get('tree'):
        # Parse git tree objects
        for entry in data.get('tree', []):
            if entry.get('type') != 'blob':
                continue
            path = entry.get('path', '')
            if not path.lower().startswith('models/'):
                continue
            name = os.path.basename(path)
            lower = name.lower()
            if not any(lower.endswith(ext) for ext in allowed_exts):
                continue
            # Build raw download URL
            url = f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}'
            size = _human_size(entry.get('size'))
            items.append({'name': name, 'url': url, 'size': size})
    elif isinstance(data, list):
        # fallback to contents API (non-recursive)
        for item in data:
            # We only care about files (not subfolders). Some model files may be archives
            if item.get('type') != 'file':
                continue
            name = item.get('name')
            if not name:
                continue
            lower = name.lower()
            # Accept only plausible model artifacts; otherwise skip (e.g., README.md)
            if not any(lower.endswith(ext) for ext in allowed_exts):
                continue
            url = item.get('download_url') or item.get('html_url')
            size = _human_size(item.get('size'))
            items.append({'name': name, 'url': url, 'size': size})

    # Single category 'Hance Models' to match the user's request of a simple list
    return {'Hance Models': items}


if __name__ == '__main__':
    try:
        print(json.dumps(parse_hance_models(), indent=2))
    except Exception as e:
        print('Error:', e)
