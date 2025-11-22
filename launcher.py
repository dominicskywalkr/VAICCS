import threading
import tkinter as tk
import time
import sys
import os
from gui_splash import Splash
from startup_options import parse_modifiers, apply_startup_options
import tkinter.messagebox as messagebox

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

splash = Splash(root, title_text="VAICCS", creator="Dominic Natoli")
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
                app.mainloop()
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
