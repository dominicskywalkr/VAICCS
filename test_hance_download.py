"""Test downloading a Hance model (raw file) and validate file output.

This script:
- Calls parse_hance_models() to find models
- Selects a model by name (default: speech-denoise-11ms.v26.1.hance)
- Downloads raw file to a temporary models dir under the project's `models` folder
- Verifies that the resulting file exists and is definitely a binary/model file (not an HTML 404 page)
"""
import os
import sys
import shutil
import requests
import re
import tempfile
from parse_hance_headless import parse_hance_models


def ensure_models_root():
    from gui import App
    app = App()
    root = app.models_root
    app.destroy()
    os.makedirs(root, exist_ok=True)
    return root


def find_model_by_name(models_map, name_part):
    for k, items in models_map.items():
        for it in items:
            if name_part in (it.get('name') or ''):
                return it
    return None


def download_model(item, dest_dir):
    url = item.get('url')
    if not url:
        raise ValueError('No download URL available')
    fname = os.path.basename(url.split('?')[0])
    dest_path = os.path.join(dest_dir, fname)
    part_path = dest_path + '.part'
    headers = {'User-Agent': 'VAICCS-Hance-Downloader/1.0'}
    # stream into file
    with requests.get(url, stream=True, timeout=30, headers=headers) as r:
        r.raise_for_status()
        ct = r.headers.get('Content-Type', '')
        print('Content-Type:', ct)
        # If content-type looks like HTML, fail early
        if 'html' in ct.lower():
            raise RuntimeError('Download returned HTML content; likely a bad URL or authorization required')
        with open(part_path, 'wb') as outf:
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                outf.write(chunk)
    # Move part to final dest
    try:
        os.replace(part_path, dest_path)
    except Exception:
        shutil.move(part_path, dest_path)
    return dest_path


def detect_html_start(path):
    try:
        with open(path, 'rb') as fh:
            head = fh.read(512).lower()
            if b'<html' in head or b'<!doctype html' in head:
                return True
    except Exception:
        return False
    return False


def main():
    root = ensure_models_root()
    print('Models root:', root)
    models = parse_hance_models()
    print('Found categories:', list(models.keys()))
    # default model to test
    target_name = 'speech-denoise-11ms.v26.1.hance'
    it = find_model_by_name(models, target_name)
    if not it:
        print('Model not found; available models:')
        for v in sum(models.values(), []):
            print(' -', v.get('name'))
        raise SystemExit(1)
    print('Selected model:', it.get('name'), 'URL:', it.get('url'))
    dest = download_model(it, root)
    print('Downloaded to:', dest)
    if detect_html_start(dest):
        print('Error: file appears to be HTML content -> likely a redirect or error page')
        raise SystemExit(2)
    size = os.path.getsize(dest)
    print('File size bytes:', size)
    # check expected extension
    if not dest.lower().endswith('.hance'):
        print('Warning: downloaded filename does not end with .hance')
    # Re-run installed search logic similar to GUI to verify discoverability
    base_no_ext = os.path.splitext(it.get('name'))[0].lower()
    print('Looking for folder match or file in models root...')
    found = None
    for nm in os.listdir(root):
        pth = os.path.join(root, nm)
        if os.path.isdir(pth) and nm.lower().startswith(base_no_ext):
            found = pth
            break
    if not found:
        fpth = os.path.join(root, os.path.basename(dest))
        if os.path.exists(fpth):
            found = fpth
    if not found:
        for r, d, files in os.walk(root):
            for file in files:
                if file.lower().startswith(base_no_ext) or os.path.splitext(file)[0].lower() == base_no_ext:
                    found = os.path.join(r, file)
                    break
            if found:
                break
    print('Install search result:', found)
    print('SUCCESS: model downloaded and appears to be a binary/model file')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('ERROR:', e)
        raise
