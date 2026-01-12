import threading
import tkinter as tk
import time
import sys
import os
import shlex
from gui_splash import Splash
# When launched from a macOS .app bundle, the current working directory
# may not be the application bundle's Resources/ or MacOS/ directory.
# Set the process CWD to the executable directory so relative paths
# (os.getcwd(), open('transcripts', ...), etc.) resolve consistently
# whether running the standalone executable or the .app bundle.
try:
    _exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    if _exe_dir:
        os.chdir(_exe_dir)
except Exception:
    pass
try:
    # If running as a ``onedir`` frozen app, PyInstaller may place data
    # under an ``_internal`` folder. Ensure a real libvosk.dyld exists at
    # `<exe>/_internal/vosk/libvosk.dyld` so `vosk` can dlopen() it. If it's
    # missing, search common candidate locations packaged by the spec or
    # created during build and copy the real dylib into place.
    if _exe_dir and getattr(sys, 'frozen', False):
        try:
            import shutil
            target_dir = os.path.join(_exe_dir, '_internal', 'vosk')
            target_file = os.path.join(target_dir, 'libvosk.dyld')
            if not os.path.exists(target_file):
                # candidate locations to search for a real libvosk file
                candidates = []
                # sys._MEIPASS when present (onefile/onedir staging)
                meipass = getattr(sys, '_MEIPASS', None)
                if meipass:
                    candidates.append(os.path.join(meipass, 'vosk', 'libvosk.dyld'))
                    candidates.append(os.path.join(meipass, 'vosk', 'libvosk.dylib'))

                # common datas placement next to exe
                candidates.append(os.path.join(_exe_dir, 'vosk', 'libvosk.dyld'))
                candidates.append(os.path.join(_exe_dir, 'vosk', 'libvosk.dylib'))

                # Resources/_internal or Resources/vosk (packaging fallbacks)
                parent = os.path.abspath(os.path.join(_exe_dir, '..'))
                candidates.append(os.path.join(parent, 'Resources', '_internal', 'vosk', 'libvosk.dyld'))
                candidates.append(os.path.join(parent, 'Resources', '_internal', 'vosk', 'libvosk.dylib'))
                candidates.append(os.path.join(parent, 'Resources', 'vosk', 'libvosk.dyld'))
                candidates.append(os.path.join(parent, 'Resources', 'vosk', 'libvosk.dylib'))

                # Frameworks location (macOS .app builds)
                candidates.append(os.path.join(parent, 'Frameworks', 'vosk', 'libvosk.dyld'))
                candidates.append(os.path.join(parent, 'Frameworks', 'vosk', 'libvosk.dylib'))

                found = None
                for c in candidates:
                    try:
                        if c and os.path.exists(c) and os.path.isfile(c) and not os.path.islink(c):
                            found = c
                            break
                        # if candidate is a directory containing the real file
                        if c and os.path.isdir(c):
                            inner = os.path.join(c, 'libvosk.dyld')
                            if os.path.exists(inner) and os.path.isfile(inner):
                                found = inner
                                break
                    except Exception:
                        continue

                if found:
                    try:
                        os.makedirs(target_dir, exist_ok=True)
                        shutil.copyfile(found, target_file)
                        try:
                            os.chmod(target_file, 0o755)
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception:
            pass
except Exception:
    pass
try:
    # Fix packaging oddities where the Vosk dylib ends up inside a nested
    # directory (PyInstaller sometimes creates a dir named like
    # libvosk__dot__dyld containing the dylib). Create a direct file
    # `Contents/Frameworks/vosk/libvosk.dyld` pointing to the real dylib
    # so `vosk` can dlopen() it.
    if _exe_dir:
        frameworks_vosk = os.path.abspath(os.path.join(_exe_dir, '..', 'Frameworks', 'vosk'))
        # Ensure the Frameworks/vosk directory exists so we can create a
        # direct file or symlink at Contents/Frameworks/vosk/libvosk.dyld.
        try:
            os.makedirs(frameworks_vosk, exist_ok=True)
        except Exception:
            pass
        target = os.path.join(frameworks_vosk, 'libvosk.dyld')
        # If target exists and is a symlink to a dir, attempt to repair
        if os.path.exists(target) and os.path.islink(target):
            try:
                link = os.readlink(target)
                # resolve relative links against frameworks_vosk
                link_abs = os.path.join(frameworks_vosk, link) if not os.path.isabs(link) else link
                if os.path.isdir(link_abs):
                    # find inner real file
                    candidate = os.path.join(link_abs, 'libvosk.dyld')
                    if os.path.exists(candidate) and os.path.isfile(candidate):
                        try:
                            os.remove(target)
                        except Exception:
                            pass
                        try:
                            os.symlink(candidate, target)
                        except Exception:
                            try:
                                import shutil
                                shutil.copyfile(candidate, target)
                            except Exception:
                                pass
            except Exception:
                pass
        # If the direct file is missing but an inner directory exists, create a symlink
        if not os.path.exists(target):
            try:
                for name in os.listdir(frameworks_vosk):
                    p = os.path.join(frameworks_vosk, name)
                    candidate = os.path.join(p, 'libvosk.dyld')
                    if os.path.exists(candidate) and os.path.isfile(candidate):
                        try:
                            os.symlink(candidate, target)
                        except Exception:
                            try:
                                import shutil
                                shutil.copyfile(candidate, target)
                            except Exception:
                                pass
                        break
            except Exception:
                pass
        # If still missing (PyInstaller may have placed the library under
        # Resources/_internal/vosk/... ), search common resource locations
        # and try to create a symlink from Frameworks/vosk/libvosk.dyld -> real file.
        if not os.path.exists(target):
            try:
                parent = os.path.abspath(os.path.join(_exe_dir, '..'))
                candidates = [
                    os.path.join(parent, 'Resources', '_internal', 'vosk'),
                    os.path.join(parent, 'Resources', 'vosk'),
                    os.path.join(parent, 'Resources', 'vendor_vosk'),
                    os.path.join(parent, 'Resources', '_internal'),
                    os.path.join(parent, 'Resources'),
                    os.path.join(parent, 'MacOS', '_internal', 'vosk'),
                ]
                found = None
                for base in candidates:
                    try:
                        if not base or not os.path.isdir(base):
                            continue
                        # direct file
                        direct = os.path.join(base, 'libvosk.dyld')
                        if os.path.exists(direct) and os.path.isfile(direct):
                            found = direct
                            break
                        # nested directory containing file
                        for entry in os.listdir(base):
                            p = os.path.join(base, entry)
                            inner = os.path.join(p, 'libvosk.dyld')
                            if os.path.exists(inner) and os.path.isfile(inner):
                                found = inner
                                break
                        if found:
                            break
                    except Exception:
                        continue
                if found:
                    try:
                        os.symlink(found, target)
                    except Exception:
                        try:
                            import shutil
                            shutil.copyfile(found, target)
                        except Exception:
                            pass
            except Exception:
                pass
except Exception:
    pass
# read license state to annotate splash title
try:
    import license_manager
    _lic_type = ''
    try:
        # if there's a saved license and we have a pubkey, validate it offline
        pub = os.environ.get('CRYPTOLENS_RSA_PUBKEY', '')
        if not pub:
            # try local config file like activate.py
            try:
                base = os.path.abspath(os.path.dirname(__file__))
                cfg = os.path.join(base, 'cryptolens_config.json')
                if os.path.exists(cfg):
                    import json
                    with open(cfg, 'r', encoding='utf-8') as f:
                        j = json.load(f)
                    pub = j.get('rsa_pubkey', '') or pub
            except Exception:
                pass

        if pub:
            try:
                ok, msg = license_manager.validate_saved_license(pub, v=2)
                if ok:
                    _lic_type = 'commercial' if license_manager.license_type() == 'commercial' else ''
                else:
                    # fallback to license_type (may be stale)
                    _lic_type = license_manager.license_type()
            except Exception:
                _lic_type = license_manager.license_type()
        else:
            _lic_type = license_manager.license_type()
    except Exception:
        _lic_type = license_manager.license_type()
except Exception:
    _lic_type = ''
from startup_options import parse_modifiers, apply_startup_options
import tkinter.messagebox as messagebox
import threading
import time
import json

# Importer thread will import the heavy GUI module
info = {}
loaded_event = threading.Event()
# record start time so we can enforce a minimum splash display duration
start_time = time.time()

def importer():
    try:
        import gui as gui_mod
        info['module'] = gui_mod
    except Exception as e:
        info['error'] = str(e)
    finally:
        loaded_event.set()

# Start the importer thread
t = threading.Thread(target=importer, daemon=True)
t.start()

# parse modifiers early so we can use them after launch
# If a VAICCS/startup.txt exists, read it and append its arguments.
# Candidates checked: executable dir, cwd, and module directory.
startup_args = []
try:
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
except Exception:
    exe_dir = None
candidates = []
if exe_dir:
    candidates.append(os.path.join(exe_dir, 'VAICCS', 'startup.txt'))
candidates.append(os.path.join(os.getcwd(), 'VAICCS', 'startup.txt'))
try:
    base = os.path.abspath(os.path.dirname(__file__))
    candidates.append(os.path.join(base, 'VAICCS', 'startup.txt'))
except Exception:
    pass

for p in candidates:
    try:
        if p and os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                txt = f.read()
            if txt and txt.strip():
                # Parse like a shell to allow quoted paths with spaces
                try:
                    startup_args = shlex.split(txt, comments=True)
                except Exception:
                    # fallback: simple whitespace split
                    startup_args = txt.split()
                break
    except Exception:
        continue

# Merge startup args: append them so explicit CLI args still win precedence.
if startup_args:
    sys.argv = [sys.argv[0]] + sys.argv[1:] + startup_args

options = parse_modifiers(sys.argv[1:])

# If a per-user startup.json exists in ~/Documents/VAICCS/startup.json, merge
# its values into options (CLI and startup.txt keep precedence). Also build a
# short summary string to display on the splash if present.
startup_json_summary = None
try:
    user_startup = os.path.expanduser('~/Documents/VAICCS/startup.json')
    if os.path.exists(user_startup):
        try:
            with open(user_startup, 'r', encoding='utf-8') as f:
                j = json.load(f) or {}
            # Only fill missing keys so explicit CLI args still win
            for k in ('save', 'autostart', 'show_error'):
                if options.get(k) is None and k in j:
                    options[k] = j.get(k)
            # Build a compact summary for the splash screen
            parts = []
            sv = j.get('save')
            if sv:
                try:
                    parts.append('load: ' + os.path.basename(sv))
                except Exception:
                    parts.append('load: (settings)')
            if 'autostart' in j:
                parts.append('autostart' if bool(j.get('autostart')) else 'no-autostart')
            if 'show_error' in j:
                parts.append('show_error' if bool(j.get('show_error')) else 'no-showerror')
            if parts:
                startup_json_summary = 'startup.json: ' + ', '.join(parts)
            else:
                startup_json_summary = 'startup.json found'
        except Exception:
            # ignore malformed file
            startup_json_summary = None
except Exception:
    startup_json_summary = None

# Create a small Tk root and show splash while importer runs
root = tk.Tk()
# keep root withdrawn; Splash will center on screen when parent not mapped
root.withdraw()

# Default to personal/evaluation unless we detect a commercial license
splash_title = "VAICCS (Personal/eval)"
if _lic_type == 'commercial':
    splash_title = "VAICCS (Commercial)"

splash = Splash(root, title_text=splash_title, creator="Dominic Natoli")
try:
    # Show the generic loading message immediately for at least 1s,
    # then switch to the startup.json summary (if present) while modules load.
    splash.update_status("Loading application modules...")
    def _maybe_show_startup():
        try:
            if startup_json_summary:
                splash.update_status(startup_json_summary)
        except Exception:
            pass
    # schedule after 1 second
    try:
        root.after(1000, _maybe_show_startup)
    except Exception:
        pass
except Exception:
    pass

# Poll for completion
POLL_MS = 200

# minimum display time (seconds)
MIN_DISPLAY = 3.0

def check():
    if loaded_event.is_set():
        # Import finished; ensure minimum splash time has elapsed
        elapsed = time.time() - start_time
        remaining = max(0.0, MIN_DISPLAY - elapsed)

        def _finish_launch():
            if 'error' in info:
                try:
                    splash.update_status("Failed to load application: " + info['error'])
                except Exception:
                    pass
                # if requested, show the import error log contents in a messagebox
                try:
                    if options.get('show_error'):
                        # look for known log locations
                        log_paths = []
                        try:
                            exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                            log_paths.append(os.path.join(exe_dir, 'vosk_import_error.log'))
                        except Exception:
                            pass
                        try:
                            log_paths.append(os.path.join(os.getcwd(), 'vosk_import_error.log'))
                        except Exception:
                            pass
                        found = None
                        for p in log_paths:
                            try:
                                if p and os.path.exists(p):
                                    found = p
                                    break
                            except Exception:
                                continue
                        if found:
                            try:
                                with open(found, 'r', encoding='utf-8') as lf:
                                    txt = lf.read()
                            except Exception:
                                txt = None
                        else:
                            txt = None
                        if txt:
                            # limit size to avoid huge messageboxes
                            msg = txt if len(txt) < 10000 else txt[-10000:]
                            try:
                                messagebox.showerror('Vosk Import Error', msg)
                            except Exception:
                                print('Vosk import error:\n', msg)
                        else:
                            try:
                                messagebox.showerror('Vosk Import Error', info.get('error'))
                            except Exception:
                                print('Vosk import error:', info.get('error'))
                except Exception:
                    pass
                # keep visible a short time so user can read the error
                root.after(4000, root.destroy)
                return

            # otherwise close splash and launch app
            try:
                splash.update_status("Starting application...")
            except Exception:
                pass
            try:
                splash.close()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass
            try:
                gui_mod = info.get('module')
                app = gui_mod.App()
                # apply startup options (load settings, autostart)
                try:
                    apply_startup_options(app, options)
                except Exception:
                    pass
                # Start background revalidation thread (attempt online re-checks)
                try:
                    def revalidate_loop(app_ref):
                        """Background thread: attempt online revalidation of saved license.

                        - On failure, retries every 5 minutes until success.
                        - After success, sleeps 24 hours between revalidations.
                        """
                        SHORT_INTERVAL = 5 * 60
                        LONG_INTERVAL = 24 * 3600
                        while True:
                            try:
                                # Check if app is still running (window is still valid)
                                try:
                                    if not app_ref.winfo_exists():
                                        return
                                except Exception:
                                    return
                                
                                # load saved license and product key
                                try:
                                    data = license_manager.load_license()
                                except Exception:
                                    data = {}
                                product_key = data.get('product_key')
                                if not product_key:
                                    # nothing to revalidate
                                    return

                                # load cryptolens config (env or config file)
                                token = os.environ.get('CRYPTOLENS_TOKEN', '')
                                rsa_pub = os.environ.get('CRYPTOLENS_RSA_PUBKEY', '')
                                product_id = os.environ.get('CRYPTOLENS_PRODUCT_ID', '')
                                if not (token and rsa_pub and product_id):
                                    # try config file
                                    try:
                                        base = os.path.abspath(os.path.dirname(__file__))
                                        cfg = os.path.join(base, 'cryptolens_config.json')
                                        if os.path.exists(cfg):
                                            with open(cfg, 'r', encoding='utf-8') as f:
                                                j = json.load(f)
                                            token = token or j.get('token', '')
                                            rsa_pub = rsa_pub or j.get('rsa_pubkey', '')
                                            product_id = product_id or str(j.get('product_id', ''))
                                    except Exception:
                                        pass

                                if not (token and rsa_pub and product_id):
                                    # cannot perform online revalidation
                                    return

                                # attempt online activation
                                try:
                                    from licensing.methods import Key, Helpers
                                except Exception:
                                    # licensing SDK not available
                                    return

                                try:
                                    mc = Helpers.GetMachineCode(v=2)
                                except Exception:
                                    mc = None

                                try:
                                    result = Key.activate(token=token, rsa_pub_key=rsa_pub, product_id=int(product_id), key=product_key, machine_code=mc)
                                except Exception:
                                    result = None

                                if result and result[0] is not None:
                                    # successful revalidation; save fresh SKM and data
                                    lk = result[0]
                                    try:
                                        skm = lk.save_as_string()
                                    except Exception:
                                        skm = None

                                    new_data = dict(data if isinstance(data, dict) else {})
                                    if skm:
                                        new_data['license_skm'] = skm
                                    # update activated_machines info if present
                                    try:
                                        new_data['activated_machines'] = getattr(lk, 'activated_machines', None)
                                    except Exception:
                                        pass
                                    # persist
                                    try:
                                        license_manager.save_license(new_data)
                                    except Exception:
                                        pass
                                    # successful: sleep longer
                                    time.sleep(LONG_INTERVAL)
                                else:
                                    # failed: retry soon
                                    time.sleep(SHORT_INTERVAL)
                            except Exception:
                                # on unexpected errors, wait and retry
                                time.sleep(SHORT_INTERVAL)

                    t_reval = threading.Thread(target=revalidate_loop, args=(app,), daemon=True)
                    t_reval.start()
                except Exception:
                    pass
                app.mainloop()
                # App closed, now destroy the root window so launcher.py can exit
                try:
                    root.destroy()
                except Exception:
                    pass
            except Exception as e:
                # If launching the GUI failed, fall back to printing error
                print("Failed to start GUI:", e)

        if remaining > 0:
            # schedule finish after remaining time
            root.after(int(remaining * 1000) + 10, _finish_launch)
        else:
            _finish_launch()
    else:
        # still loading; optionally update status
        root.after(POLL_MS, check)

root.after(100, check)
root.mainloop()
