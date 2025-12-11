import threading
import tkinter as tk
import time
import sys
import os
from gui_splash import Splash
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
options = parse_modifiers(sys.argv[1:])

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
    splash.update_status("Loading application modules...")
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
