import tkinter as tk
from tkinter import ttk


class Splash(tk.Toplevel):
    """Simple splash window shown while the main UI initializes.

    Keeps implementation defensive so it won't break on unusual Tk builds.
    """
    def __init__(self, parent, title_text="VAICCS", creator="Dominic Natoli"):
        # create Toplevel with explicit master (parent may be withdrawn)
        try:
            super().__init__(parent)
        except Exception:
            # fallback to no-parent master
            super().__init__()
        try:
            # Remove window decorations for a cleaner splash
            self.overrideredirect(True)
        except Exception:
            pass
        # Also set the window title so the annotation is visible in the OS title bar
        try:
            self.title(title_text)
        except Exception:
            pass
        try:
            frm = ttk.Frame(self, padding=12)
            frm.pack(fill=tk.BOTH, expand=True)
        except Exception:
            frm = tk.Frame(self)
            frm.pack(fill=tk.BOTH, expand=True)

        try:
            ttk.Label(frm, text=title_text, font=(None, 14, 'bold')).pack()
            ttk.Label(frm, text=f"by {creator}", font=(None, 10)).pack()
            # Display application version (if available from main.__version__)
            try:
                import main as mainmod
                ver = getattr(mainmod, '__version__', None)
            except Exception:
                ver = None
            try:
                if ver:
                    ttk.Label(frm, text=f"Version: {ver}", font=(None, 10)).pack()
            except Exception:
                pass
        except Exception:
            tk.Label(frm, text=title_text).pack()
            tk.Label(frm, text=f"by {creator}").pack()

        self.status_var = tk.StringVar(value="Starting...")
        try:
            self.status_lbl = ttk.Label(frm, textvariable=self.status_var, wraplength=360)
            self.status_lbl.pack(pady=(8,0))
        except Exception:
            self.status_lbl = tk.Label(frm, textvariable=self.status_var)
            self.status_lbl.pack(pady=(8,0))

        try:
            self.progress = ttk.Progressbar(frm, mode='indeterminate', length=300)
            self.progress.pack(pady=(8,0))
            self.progress.start(10)
        except Exception:
            self.progress = None

        # Make sure splash is visible above other windows
        try:
            # On Windows, '-topmost' keeps it above other windows while shown
            self.attributes('-topmost', True)
        except Exception:
            pass

        self.update_idletasks()
        # Try to center on parent if it's mapped; otherwise center on screen
        try:
            mapped = False
            try:
                mapped = bool(parent and getattr(parent, 'winfo_ismapped', lambda: False)())
            except Exception:
                mapped = False
            if mapped:
                self._center_on_parent(parent)
            else:
                self._center_on_screen()
        except Exception:
            # best-effort; ignore failures
            pass
        # raise & show
        try:
            self.deiconify()
            self.lift()
        except Exception:
            pass

    def _center_on_parent(self, parent):
        try:
            parent.update_idletasks()
            self.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _center_on_screen(self):
        try:
            self.update_idletasks()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w = self.winfo_width()
            h = self.winfo_height()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def update_status(self, text: str):
        try:
            self.status_var.set(text)
            # brief UI update so user sees status change
            self.update_idletasks()
        except Exception:
            pass

    def close(self):
        try:
            if getattr(self, 'progress', None):
                try:
                    self.progress.stop()
                except Exception:
                    pass
            # remove topmost attribute before destroying to avoid focus issues
            try:
                self.attributes('-topmost', False)
            except Exception:
                pass
            self.destroy()
        except Exception:
            pass
