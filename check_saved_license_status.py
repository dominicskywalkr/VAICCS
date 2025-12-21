#!/usr/bin/env python3
import os, json, sys
sys.path.insert(0, os.path.dirname(__file__))
import license_manager

# Determine RSAPUBKEY like activate.py
RSAPUBKEY = os.environ.get('CRYPTOLENS_RSA_PUBKEY','')
if not RSAPUBKEY:
    try:
        base = os.path.abspath(os.path.dirname(__file__))
        cfg_path = os.path.join(base, 'cryptolens_config.json')
        if os.path.exists(cfg_path):
            with open(cfg_path,'r',encoding='utf-8') as f:
                cfg = json.load(f)
            RSAPUBKEY = cfg.get('rsa_pubkey','') or RSAPUBKEY
    except Exception:
        pass

print('RSA PUBKEY present:', bool(RSAPUBKEY))
try:
    st = license_manager.get_saved_license_status(RSAPUBKEY, v=2)
    print('get_saved_license_status:', st)
except Exception as e:
    print('error calling get_saved_license_status:', e)

print('\nLoaded license via load_license():')
print(license_manager.load_license())
print('\nlicense_debug.log (tail):')
try:
    d = license_manager._get_writable_data_dir()
    log = os.path.join(d,'license_debug.log')
    if os.path.exists(log):
        with open(log,'r',encoding='utf-8') as f:
            data = f.read().splitlines()
        for line in data[-40:]:
            print(line)
    else:
        print('(no log)')
except Exception as e:
    print('log read error:', e)
