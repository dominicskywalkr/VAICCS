import threading, time, os, shutil
from parse_vosk_headless import parse_vosk_models
import gui
import re
import requests

# find smallest model by parsing size
m = parse_vosk_models()
all_models = []
size_re = re.compile(r'(\d+(?:\.\d+)?)\s*(GB|GiB|MB|MiB|KB|KiB|G|M|K)', re.IGNORECASE)
mult = {'gb':1024**3, 'gib':1024**3, 'mb':1024**2, 'mib':1024**2, 'kb':1024, 'kib':1024, 'g':1024**3, 'm':1024**2, 'k':1024}
for lang, items in m.items():
    for it in items:
        size_str = it.get('size') or ''
        msz = None
        mo = size_re.search(size_str)
        if mo:
            num = float(mo.group(1))
            unit = mo.group(2).lower()
            msz = int(num * mult.get(unit, 1))
        else:
            # unknown size: prefer later
            msz = None
        all_models.append((msz or float('inf'), it))

all_models.sort(key=lambda x: x[0])
# pick first with url
candidate = None
for s,it in all_models:
    if it.get('url'):
        candidate = (s,it)
        break

if not candidate:
    print('No candidate model found')
    raise SystemExit(1)

s,it = candidate
print('Selected model:', it.get('name'), 'size:', it.get('size'), 'url:', it.get('url'))

# instantiate GUI app just to get models_root path
app = gui.App()
models_root = app.models_root
print('Models root:', models_root)

url = it.get('url')
fname = os.path.basename(url.split('?')[0])
dest_path = os.path.join(models_root, fname)
part_path = dest_path + '.part'

cancel_event = threading.Event()

def downloader():
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(part_path, 'wb') as outf:
                for chunk in r.iter_content(chunk_size=8192):
                    if cancel_event.is_set():
                        print('Cancellation requested: aborting download')
                        try:
                            outf.close()
                        except Exception:
                            pass
                        try:
                            os.remove(part_path)
                        except Exception:
                            pass
                        return
                    if not chunk:
                        continue
                    outf.write(chunk)
        try:
            os.replace(part_path, dest_path)
        except Exception:
            shutil.move(part_path, dest_path)
        print('Download completed (unexpected)')
    except Exception as e:
        print('Download failed:', e)

thr = threading.Thread(target=downloader, daemon=True)
thr.start()

# wait a bit then cancel
time.sleep(2)
print('Setting cancel')
cancel_event.set()
thr.join(timeout=10)
print('Done')
app.destroy()
