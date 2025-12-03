import os
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

# Cryptolens settings: prefer environment variables, otherwise set here
# Set these in your environment, e.g. CRYPTOLENS_TOKEN, CRYPTOLENS_RSA_PUBKEY, CRYPTOLENS_PRODUCT_ID
RSAPUBKEY = os.environ.get('CRYPTOLENS_RSA_PUBKEY', '')
CRYPTOLENS_TOKEN = os.environ.get('CRYPTOLENS_TOKEN', '')
CRYPTOLENS_PRODUCT_ID = os.environ.get('CRYPTOLENS_PRODUCT_ID', '')

# Fallback: load `cryptolens_config.json` from the project directory if any
# of the required values are missing. This file should be added to .gitignore
# and can contain: { "token": "...", "rsa_pubkey": "<RSAKeyValue>...</RSAKeyValue>", "product_id": 12345 }
if not (RSAPUBKEY and CRYPTOLENS_TOKEN and CRYPTOLENS_PRODUCT_ID):
    try:
        base = os.path.abspath(os.path.dirname(__file__))
        cfg_path = os.path.join(base, 'cryptolens_config.json')
        if os.path.exists(cfg_path):
            import json
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            # only populate values that are missing from environment
            if not CRYPTOLENS_TOKEN:
                CRYPTOLENS_TOKEN = cfg.get('token', '')
            if not RSAPUBKEY:
                RSAPUBKEY = cfg.get('rsa_pubkey', '')
            if not CRYPTOLENS_PRODUCT_ID:
                # accept either string or int
                pid = cfg.get('product_id', '')
                CRYPTOLENS_PRODUCT_ID = str(pid) if pid is not None else ''
    except Exception:
        # don't crash GUI if config loading fails
        pass

try:
    from licensing.methods import Key, Helpers
except Exception:
    Key = None
    Helpers = None


def _add_placeholder(entry: tk.Entry, placeholder: str):
    try:
        placeholder_color = 'gray'
        normal_color = entry.cget('fg') if entry.cget('fg') else 'black'
    except Exception:
        placeholder_color = 'gray'
        normal_color = 'black'

    def _on_focus_in(evt=None):
        try:
            if entry.get() == placeholder:
                entry.delete(0, tk.END)
                try:
                    entry.config(fg=normal_color)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_focus_out(evt=None):
        try:
            if not entry.get():
                entry.insert(0, placeholder)
                try:
                    entry.config(fg=placeholder_color)
                except Exception:
                    pass
        except Exception:
            pass

    # initialize
    try:
        if not entry.get():
            entry.insert(0, placeholder)
            entry.config(fg=placeholder_color)
    except Exception:
        pass
    entry.bind('<FocusIn>', _on_focus_in)
    entry.bind('<FocusOut>', _on_focus_out)


def show_activate_dialog(parent):
    dlg = tk.Toplevel(parent)
    # Try to set window icon (prefer project root `icon.ico`, fallback to `media/icon.ico`)
    try:
        base = os.path.abspath(os.path.dirname(__file__))
        icon_path = os.path.join(base, 'icon.ico')
        if not os.path.exists(icon_path):
            icon_path = os.path.join(base, 'media', 'icon.ico')
        if os.path.exists(icon_path):
            try:
                dlg.iconbitmap(icon_path)
            except Exception:
                pass
    except Exception:
        pass
    try:
        dlg.transient(parent)
    except Exception:
        pass
    dlg.title('Activate Product')
    try:
        dlg.grab_set()
    except Exception:
        pass

    frm = ttk.Frame(dlg, padding=12)
    frm.pack(fill=tk.BOTH, expand=True)

    # Activation status label (shows saved license info if present)
    try:
        status_var = tk.StringVar()
        status_lbl = ttk.Label(frm, textvariable=status_var, foreground='blue')
        status_lbl.pack(fill=tk.X, pady=(0,8))
        try:
            import license_manager as _lm
            if RSAPUBKEY:
                try:
                    st = _lm.get_saved_license_status(RSAPUBKEY, v=2)
                    if st and isinstance(st, dict):
                        if st.get('status') == 'invalid':
                            status_var.set('Local license: none or invalid')
                        else:
                            s = st.get('status')
                            exp = st.get('expires')
                            if exp:
                                try:
                                    exp_str = exp.isoformat()
                                except Exception:
                                    exp_str = str(exp)
                                status_var.set(f'Local license: {s} (expires: {exp_str})')
                            else:
                                status_var.set(f'Local license: {s}')
                    else:
                        status_var.set('Local license: none')
                except Exception:
                    status_var.set('Local license: check failed')
            else:
                status_var.set('Local license: RSA public key not configured')
        except Exception:
            status_var.set('Local license: unavailable')
    except Exception:
        # Fall back: don't show status if UI creation fails
        try:
            pass
        except Exception:
            pass

    ttk.Label(frm, text='Email:').pack(anchor=tk.W)
    email_entry = tk.Entry(frm, width=40)
    email_entry.pack(fill=tk.X, pady=(0,8))
    _add_placeholder(email_entry, 'you@example.com')

    ttk.Label(frm, text='Product Key:').pack(anchor=tk.W)
    key_entry = tk.Entry(frm, width=40)
    key_entry.pack(fill=tk.X, pady=(0,12))
    _add_placeholder(key_entry, 'XXXXX-XXXXX-XXXXX-XXXXX')

    btn_frm = ttk.Frame(frm)
    btn_frm.pack(fill=tk.X)

    def on_cancel():
        try:
            dlg.destroy()
        except Exception:
            pass

    def on_buy():
        # Open purchase URL. Prefer environment override or config, fallback to Cryptolens app.
        try:
            buy_url = os.environ.get('CRYPTOLENS_BUY_URL', '')
            if not buy_url:
                cfg_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'cryptolens_config.json')
                if os.path.exists(cfg_path):
                    try:
                        import json
                        with open(cfg_path, 'r', encoding='utf-8') as f:
                            cfg = json.load(f)
                        buy_url = cfg.get('buy_url', '')
                    except Exception:
                        buy_url = ''
            if not buy_url:
                buy_url = 'https://app.cryptolens.io/'
            webbrowser.open(buy_url)
        except Exception:
            try:
                messagebox.showinfo('Buy', 'Could not open purchase page. Please visit https://app.cryptolens.io/')
            except Exception:
                pass

    def on_activate():
        try:
            # Before attempting online activation, check any saved license offline
            try:
                import license_manager as _lm
                if RSAPUBKEY:
                    try:
                        ok, msg = _lm.validate_saved_license(RSAPUBKEY, v=2)
                        if ok:
                            try:
                                messagebox.showinfo('Activate', 'A valid local license was found and accepted (offline).')
                                dlg.destroy()
                                return
                            except Exception:
                                return
                    except Exception:
                        # ignore offline validation errors and fall back to online flow
                        pass
            except Exception:
                pass

            email = email_entry.get().strip()
            key = key_entry.get().strip()
            # if placeholders still present, treat as blank
            if email == 'you@example.com':
                email = ''
            if key == 'XXXXX-XXXXX-XXXXX-XXXXX':
                key = ''

            # Basic validation helpers
            def _is_valid_email(e: str) -> bool:
                try:
                    return '@' in e and '.' in e.split('@')[-1]
                except Exception:
                    return False

            import re

            def _is_valid_key(k: str) -> bool:
                # Accept patterns like XXXXX-XXXXX-XXXXX-XXXXX
                # (each group 5 alphanumeric characters)
                if not k:
                    return False
                pat = re.compile(r'^[A-Za-z0-9]{5}(?:-[A-Za-z0-9]{5}){3}$')
                return bool(pat.match(k))

            # If nothing provided, keep dialog open and prompt user
            if not email and not key:
                messagebox.showwarning('Activate', 'Please enter an email or a product key to activate.')
                try:
                    email_entry.focus_set()
                except Exception:
                    pass
                return

            # If email provided but invalid, show error and keep dialog open
            if email and not _is_valid_email(email):
                messagebox.showerror('Activate', 'Please enter a valid email address.')
                try:
                    email_entry.focus_set()
                except Exception:
                    pass
                return

            # If key provided but invalid, show error and keep dialog open
            if key and not _is_valid_key(key):
                messagebox.showerror('Activate', 'Product key format invalid. Expected format:XXXXX-XXXXX-XXXXX-XXXXX')
                try:
                    key_entry.focus_set()
                except Exception:
                    pass
                return

            # If we get here, at least the provided fields are valid.
            # Persist license locally: key => commercial, email-only => personal
            try:
                from license_manager import save_license
            except Exception:
                save_license = None

            license_data = {}

            # If a product key was provided, try to activate via Cryptolens
            if key:
                if Key is None or Helpers is None:
                    messagebox.showerror('Activate', 'Cryptolens SDK not available. Please install the `licensing` package.')
                    return

                # resolve token/product id/pubkey from env or constants
                token = CRYPTOLENS_TOKEN or None
                rsa_pub = RSAPUBKEY or None
                try:
                    product_id = int(CRYPTOLENS_PRODUCT_ID) if CRYPTOLENS_PRODUCT_ID else None
                except Exception:
                    product_id = None

                if not token or not rsa_pub or not product_id:
                    messagebox.showerror('Activate', 'Cryptolens configuration missing. Set CRYPTOLENS_TOKEN, CRYPTOLENS_RSA_PUBKEY and CRYPTOLENS_PRODUCT_ID environment variables or update activate.py.')
                    return

                try:
                    mc = Helpers.GetMachineCode(v=2)
                except Exception:
                    mc = None

                try:
                    result = Key.activate(token=token, rsa_pub_key=rsa_pub, product_id=product_id, key=key, machine_code=mc)
                except Exception as e:
                    messagebox.showerror('Activate', f'Activation call failed: {e}')
                    return

                if not result or result[0] is None:
                    # activation failed; SDK typically returns (None, message)
                    err = result[1] if result and len(result) > 1 else 'Unknown error'
                    messagebox.showerror('Activate', f'Activation failed: {err}')
                    return

                license_key = result[0]

                # Determine whether to enforce node-locking
                max_machines = getattr(license_key, 'max_no_of_machines', None)
                activated = getattr(license_key, 'activated_machines', None)

                # If server didn't register machines (max==0), treat as valid
                if activated is None or (isinstance(activated, (list, tuple)) and len(activated) == 0) and (max_machines == 0 or max_machines is None):
                    valid_on_machine = True
                else:
                    valid_on_machine = Helpers.IsOnRightMachine(license_key, v=2)

                if not valid_on_machine:
                    messagebox.showerror('Activate', 'License is not valid for this machine.')
                    return

                # Save license info: include SKM string so offline loading is possible
                skm = None
                try:
                    skm = license_key.save_as_string()
                except Exception:
                    skm = None

                license_data = {'type': 'commercial', 'email': email or '', 'product_key': key, 'license_skm': skm}

            else:
                # Email-only activation (personal). We keep same behavior: store locally
                license_data = {'type': 'personal', 'email': email or ''}

            saved = False
            if save_license:
                try:
                    saved = save_license(license_data)
                except Exception:
                    saved = False

            # Notify user
            if saved:
                messagebox.showinfo('Activate', f'Activation saved.\nType: {license_data.get("type")}.')
            else:
                messagebox.showwarning('Activate', 'Activation succeeded but saving license file failed. Application will continue in evaluation mode.')

            try:
                dlg.destroy()
            except Exception:
                pass
        except Exception as e:
            try:
                messagebox.showerror('Activate', f'Activation failed: {e}')
            except Exception:
                pass

    # Buy button on bottom-left
    try:
        ttk.Button(btn_frm, text='Buy', command=on_buy).pack(side=tk.LEFT)
    except Exception:
        pass

    ttk.Button(btn_frm, text='Activate', command=on_activate).pack(side=tk.RIGHT)
    ttk.Button(btn_frm, text='Cancel', command=on_cancel).pack(side=tk.RIGHT, padx=(6,0))

    # center dialog over parent
    try:
        parent.update_idletasks()
        dlg.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - dlg.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")
    except Exception:
        pass

    try:
        parent.wait_window(dlg)
    except Exception:
        pass