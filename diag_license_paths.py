#!/usr/bin/env python3
"""Diagnostic: show license paths and existing files."""
import os
import json
import time
import sys

sys.path.insert(0, os.path.dirname(__file__))

try:
    import license_manager
except Exception as e:
    print("Could not import license_manager:", e)
    raise

print("\n== License Manager Diagnostic ==\n")

try:
    primary = license_manager._license_path()
except Exception as e:
    primary = f"(error getting primary path: {e})"
print("Primary license path:", primary)

try:
    module_p = license_manager._module_license_path()
except Exception as e:
    module_p = f"(error getting module path: {e})"
print("Module license path:", module_p)

# APPDATA VAICCS path explicitly
appdata = os.environ.get('APPDATA')
if appdata:
    appdata_vaiccs = os.path.join(appdata, 'VAICCS', 'license.json')
else:
    appdata_vaiccs = '(APPDATA not set)'
print("APPDATA VAICCS candidate:", appdata_vaiccs)

candidates = []
try:
    candidates = license_manager._candidate_paths()
except Exception:
    pass
print("\nCandidate paths (search order):")
for p in candidates:
    print(" -", p)

print('\nExisting files:')
checked = set()
for p in [primary, module_p, appdata_vaiccs] + list(candidates):
    try:
        if isinstance(p, str) and p and p not in checked:
            checked.add(p)
            exists = os.path.exists(p)
            if exists:
                try:
                    st = os.stat(p)
                    mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
                    size = st.st_size
                except Exception:
                    mtime = 'unknown'
                    size = 'unknown'
            else:
                mtime = None
                size = None
            print(f" - {p}: exists={exists}, mtime={mtime}, size={size}")
    except Exception:
        pass

print('\nLoaded license (load_license()):')
try:
    data = license_manager.load_license()
    print(json.dumps(data, indent=2))
except Exception as e:
    print(' load_license() error:', e)

print('\nlicense_type():', license_manager.license_type())

print('\nDone.')
