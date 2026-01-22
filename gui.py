import os
import json
import base64
import zipfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import sounddevice as sd
import requests
import tarfile
import shutil
import tempfile
import sys
import webbrowser
import subprocess
import datetime
import time
import re
from urllib.parse import quote, urlparse
from main import CaptionEngine
import main as mainmod
from voice_profiles import VoiceProfileManager
from parse_vosk_headless import parse_vosk_models
from parse_hance_headless import parse_hance_models
import resources
import noise_cancel
import startup_options as startup_options_mod
from automations import AutomationManager, ShowAutomation
# Lightweight fallback logger used by some async download/extract codepaths.
# The GUI also defines a more specific `_hlog` in scopes where a per-download
# log path is available; this module-level helper ensures static checks pass
# and provides a best-effort append to `hance_install.log` in the current
# working directory when a scoped logger is not present.
def _hlog(msg: str):
    try:
        with open(os.path.join(os.getcwd(), 'hance_install.log'), 'a', encoding='utf-8') as lf:
            lf.write(msg + '\n')
    except Exception:
        pass
# Import our local serial helpers. `serial_helper` itself handles the
# absence of the `pyserial` package (it sets `serial=None`), so we can
# import it directly. Previous attempts to temporarily remove the
# package directory from `sys.path` prevented importing the local
# helper module, causing serial support to be reported as missing.
try:
    from serial_helper import list_serial_ports, SerialManager
except Exception:
    def list_serial_ports():
        return []

    SerialManager = None
from gui_splash import Splash


class AudioSpectrumVisualizer(tk.Canvas):
    def __init__(
        self,
        parent,
        *,
        bar_count: int = 32,
        fft_size: int = 1024,
        update_ms: int = 50,
        min_hz: float = 60.0,
        max_hz: float = 8000.0,
        height: int = 64,
        **kwargs,
    ):
        kwargs.setdefault('bg', '#0b0b0b')
        kwargs.setdefault('highlightthickness', 1)
        kwargs.setdefault('highlightbackground', '#2a2a2a')
        super().__init__(parent, height=height, **kwargs)

        self._bar_count = max(8, int(bar_count))
        self._fft_size = int(fft_size)
        if self._fft_size < 256:
            self._fft_size = 256
        if (self._fft_size & (self._fft_size - 1)) != 0:
            # force power of two for speed
            p = 1
            while p < self._fft_size:
                p <<= 1
            self._fft_size = p

        self._update_ms = max(16, int(update_ms))
        self._min_hz = float(min_hz)
        self._max_hz = float(max_hz)

        self._running = False
        self._after_id = None
        self._rects = []
        self._smoothed = [0.0] * self._bar_count
        self._bands = None

        try:
            self.bind('<Configure>', lambda e: self._ensure_rects())
        except Exception:
            pass

    def start(self):
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self):
        self._running = False
        try:
            if self._after_id is not None:
                self.after_cancel(self._after_id)
        except Exception:
            pass
        self._after_id = None

    def _ensure_bands(self, sr: int):
        try:
            import numpy as np
        except Exception:
            self._bands = None
            return

        sr = int(sr) if sr else 16000
        max_hz = min(float(self._max_hz), sr / 2.0)
        min_hz = max(1.0, float(self._min_hz))
        if max_hz <= min_hz:
            max_hz = min_hz + 1.0

        freqs = np.geomspace(min_hz, max_hz, num=self._bar_count + 1)
        bin_freq = sr / float(self._fft_size)
        bands = []
        for i in range(self._bar_count):
            start_bin = int(freqs[i] / bin_freq)
            end_bin = int(freqs[i + 1] / bin_freq)
            start_bin = max(1, start_bin)  # skip DC
            end_bin = max(start_bin + 1, end_bin)
            # rfft has (fft_size/2 + 1) bins
            end_bin = min(end_bin, (self._fft_size // 2) + 1)
            bands.append((start_bin, end_bin))
        self._bands = bands

    def _ensure_rects(self):
        try:
            w = int(self.winfo_width())
            h = int(self.winfo_height())
        except Exception:
            return
        if w <= 4 or h <= 4:
            return

        if len(self._rects) == self._bar_count:
            return

        try:
            self.delete('all')
        except Exception:
            pass
        self._rects = []

        gap = 2
        bar_w = max(1, (w - (self._bar_count - 1) * gap) // self._bar_count)
        x = 0
        for _ in range(self._bar_count):
            rid = self.create_rectangle(x, h - 2, x + bar_w, h - 2, fill='#00c853', width=0)
            self._rects.append(rid)
            x += bar_w + gap

    def _draw_message(self, msg: str):
        try:
            self.delete('all')
        except Exception:
            pass
        try:
            self.create_text(6, 6, anchor='nw', fill='#bdbdbd', text=msg)
        except Exception:
            pass

    def _tick(self):
        if not self._running:
            return
        try:
            if not self.winfo_exists():
                self._running = False
                return
        except Exception:
            pass

        try:
            self._render()
        except Exception:
            # never let the UI crash from visualization
            pass

        try:
            self._after_id = self.after(self._update_ms, self._tick)
        except Exception:
            self._after_id = None

    def _render(self):
        try:
            import numpy as np
        except Exception:
            self._draw_message('Spectrum: numpy missing')
            return

        # Pull recent audio without consuming recognition queue.
        try:
            sr = int(getattr(mainmod, 'SAMPLE_RATE', 16000))
        except Exception:
            sr = 16000

        try:
            get_bytes = getattr(mainmod, 'get_recent_audio_tap_bytes', None)
            if get_bytes is None:
                self._draw_message('Spectrum: tap unavailable')
                return
            b = get_bytes(self._fft_size * 2)
        except Exception:
            b = b''

        if not b or len(b) < 256:
            self._ensure_rects()
            self._update_bars([0.0] * self._bar_count)
            return

        x = np.frombuffer(b, dtype=np.int16).astype(np.float32)
        if x.size < self._fft_size:
            pad = np.zeros((self._fft_size - x.size,), dtype=np.float32)
            x = np.concatenate([pad, x])
        elif x.size > self._fft_size:
            x = x[-self._fft_size:]

        x = x / 32768.0
        win = np.hanning(self._fft_size).astype(np.float32)
        spec = np.abs(np.fft.rfft(x * win)).astype(np.float32)

        if spec.size <= 2:
            self._ensure_rects()
            self._update_bars([0.0] * self._bar_count)
            return

        # normalize per-frame to make it usable across mic gain levels
        denom = float(spec.max())
        if denom <= 1e-9:
            spec = spec * 0.0
        else:
            spec = spec / denom

        if self._bands is None:
            self._ensure_bands(sr)
        if self._bands is None:
            self._ensure_rects()
            self._update_bars([0.0] * self._bar_count)
            return

        vals = []
        for (s, e) in self._bands:
            if e <= s or s >= spec.size:
                vals.append(0.0)
                continue
            e = min(e, int(spec.size))
            band = float(spec[s:e].mean())
            # perceptual-ish response: sqrt
            v = band ** 0.5
            vals.append(v)

        self._ensure_rects()
        self._update_bars(vals)

    def _update_bars(self, vals):
        try:
            w = int(self.winfo_width())
            h = int(self.winfo_height())
        except Exception:
            return
        if h <= 6:
            return

        # smooth a bit to reduce flicker
        alpha = 0.35
        for i in range(min(self._bar_count, len(vals))):
            try:
                v = float(vals[i])
            except Exception:
                v = 0.0
            if v < 0.0:
                v = 0.0
            if v > 1.0:
                v = 1.0
            self._smoothed[i] = (1.0 - alpha) * self._smoothed[i] + alpha * v

        gap = 2
        bar_w = max(1, (w - (self._bar_count - 1) * gap) // self._bar_count)
        x0 = 0
        for i, rid in enumerate(self._rects[:self._bar_count]):
            v = self._smoothed[i]
            top = int((h - 4) * (1.0 - v)) + 2
            if top < 2:
                top = 2
            if top > h - 2:
                top = h - 2
            x1 = x0 + bar_w
            # simple green->yellow->red ramp
            if v < 0.6:
                fill = '#00c853'
            elif v < 0.85:
                fill = '#ffd600'
            else:
                fill = '#ff1744'
            try:
                self.coords(rid, x0, top, x1, h - 2)
                self.itemconfig(rid, fill=fill)
            except Exception:
                pass
            x0 = x1 + gap


class App(tk.Tk):
    def __init__(self, simulate_automation: bool = False):
        super().__init__()
        self._mic_permission_probe_started = False
        try:
            self._splash = Splash(self, title_text="VAICCS (Beta)", creator="Dominic Natoli")
            self._splash.update_status("Starting...")
        except Exception:
            self._splash = None

        # Hide main window while splash shows
        try:
            self.withdraw()
        except Exception:
            pass

        # Set up the main window (kept hidden until splash is closed)
        self.title("VAICCS on MacOS (Beta)")
        self.geometry("900x850")

        # Replace the default Tk icon (feather) with bundled `icon.ico` if available
        try:
            try:
                icon_path = resources._resource_path('icon.ico')
            except Exception:
                icon_path = 'icon.ico'
            if icon_path and os.path.exists(icon_path):
                try:
                    # Preferred on Windows: .ico via iconbitmap
                    self.iconbitmap(icon_path)
                except Exception:
                    try:
                        # Fallback: use PhotoImage (works for some formats)
                        img = tk.PhotoImage(file=icon_path)
                        self.iconphoto(False, img)
                        # Keep reference to avoid GC
                        self._app_icon_image = img
                    except Exception:
                        pass
        except Exception:
            pass

        # shared UI state
        self.auto_scroll_var = tk.BooleanVar(value=True)
        # record of highlight events (for testing/diagnostics)
        self._highlight_log = []
        # whether a bad words file has been loaded for this session (controls menu check)
        self._bad_words_loaded_var = tk.BooleanVar(value=False)
        # Auto-save transcript option
        self.auto_save_txt_var = tk.BooleanVar(value=False)
        self.auto_save_txt_path = os.path.join(os.getcwd(), 'transcripts')
        # Create transcripts directory if it doesn't exist (for auto-save feature)
        try:
            os.makedirs(self.auto_save_txt_path, exist_ok=True)
        except Exception:
            pass
        # SRT caption duration (seconds) -- default; used by Export SRT and Options
        try:
            self.srt_duration_var = tk.DoubleVar(value=2.0)
        except Exception:
            # fallback initialization
            self.srt_duration_var = tk.DoubleVar()
            try:
                self.srt_duration_var.set(2.0)
            except Exception:
                pass
        # keep the menu label in sync whenever this var changes
        try:
            self._bad_words_loaded_var.trace_add("write", lambda *a: self._update_bad_words_menu_label())
        except Exception:
            try:
                self._bad_words_loaded_var.trace("w", lambda *a: self._update_bad_words_menu_label())
            except Exception:
                pass

        # Menubar: File / View / Help
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Save Settings", accelerator="Command-S", command=lambda: self._on_save_clicked())
        file_menu.add_command(label="Save Settings As...", accelerator="Command-Shift-S", command=lambda: self._on_save_as())
        file_menu.add_command(label="Options...", command=lambda: self._open_options_dialog())
        file_menu.add_command(label="Startup Options", command=lambda: self._open_startup_options())
    # Transcript export/save options
        file_menu.add_command(label="Save Transcript As...", command=lambda: self._save_transcript_txt())
        file_menu.add_command(label="Export Transcript as SRT", command=lambda: self._export_transcript_srt())
        # show a checkmark when a bad-words file is loaded; selecting this still
        # opens the file chooser so the user can change the file
        file_menu.add_checkbutton(label="Load Restricted Words File",
                      variable=self._bad_words_loaded_var,
                      command=self._on_load_bad_words)
        # remember menu and index so we can update the label between Load/Unload
        self._file_menu = file_menu
        try:
            self._bad_words_menu_index = file_menu.index("end")
        except Exception:
            self._bad_words_menu_index = None
        file_menu.add_command(label="Load Settings...", accelerator="Command-O", command=lambda: self._on_open_settings())
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Command-Q", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        # Bleep/replacement UI state: allow user to choose how bad words are replaced
        try:
            # initialize from main module if available
            bcfg = getattr(mainmod, 'BLEEP_SETTINGS', None) or {}
            mode = bcfg.get('mode', 'fixed')
            custom = bcfg.get('custom_text', '****')
            mask = bcfg.get('mask_char', '*')
        except Exception:
            mode = 'fixed'
            custom = '****'
            mask = '*'
        self.bleep_mode_var = tk.StringVar(value=mode)
        self.bleep_custom_var = tk.StringVar(value=custom)
        self.bleep_mask_var = tk.StringVar(value=mask)
        # Noise cancelation enabled state (shared so main tab can toggle it)
        self.noise_enabled_var = tk.BooleanVar(value=False)

        # Models menu: Vosk models + future Hance models placeholder
        models_menu = tk.Menu(menubar, tearoff=0)
        models_menu.add_command(label="Vosk Models...", command=lambda: self._open_vosk_model_manager())
        # Placeholder entry for future Hance models manager
        models_menu.add_command(label="Hance Models...", command=lambda: self._open_hance_model_manager())
        menubar.add_cascade(label="Models", menu=models_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        # Auto-scroll menu item bound to the shared variable
        view_menu.add_checkbutton(label="Auto-scroll", variable=self.auto_scroll_var)
        view_menu.add_command(label="Jump to latest", command=self._jump_to_latest)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        # Activate dialog (personal free / commercial paid). Placeholder UI.
        help_menu.add_command(label="Activate", command=lambda: self._open_activate())
        help_menu.add_command(label="Check for Updates...", command=lambda: self._check_for_updates(manual=True))
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo("About",
                                               f"VAICCS (Vosk AI Closed Captioning System)\n\nProvides live captions using Vosk (or demo mode).\n\nDeveloped by Dominic Natoli. 2026 \n\nVersion: {getattr(mainmod, '__version__', 'unknown') }"))
        menubar.add_cascade(label="Help", menu=help_menu)

        try:
            self.config(menu=menubar)
        except Exception:
            # some tkinter variants may not support menu on this platform
            pass

        # Keyboard shortcuts
        try:
            # Support both Control (Windows/Linux) and Command (macOS) shortcuts
            self.bind_all('<Control-s>', lambda e: self._on_save_clicked())
            self.bind_all('<Control-S>', lambda e: self._on_save_as())
            self.bind_all('<Control-Shift-S>', lambda e: self._on_save_as())
            self.bind_all('<Control-o>', lambda e: self._on_open_settings())

            # macOS Command key equivalents
            try:
                self.bind_all('<Command-s>', lambda e: self._on_save_clicked())
                self.bind_all('<Command-S>', lambda e: self._on_save_as())
                self.bind_all('<Command-Shift-S>', lambda e: self._on_save_as())
                self.bind_all('<Command-o>', lambda e: self._on_open_settings())
            except Exception:
                pass
                # Provide Command-Q binding on macOS; Alt-F4 fallback removed
            try:
                self.bind_all('<Command-q>', lambda e: self.quit())
            except Exception:
                pass
        except Exception:
            pass

        try:
            if self._splash:
                self._splash.update_status("Creating UI tabs...")
        except Exception:
            pass

        # Load GUI settings (including update prefs) and possibly auto-check
        try:
            self._gui_settings = self._load_gui_settings()
        except Exception:
            self._gui_settings = {}

        try:
            # Create a BooleanVar for the auto-update preference (Options dialog will expose it)
            ups = (self._gui_settings or {}).get('updates', {})
            auto = bool(ups.get('auto_check', False))
            try:
                self.auto_check_updates_var = tk.BooleanVar(value=auto)
            except Exception:
                self.auto_check_updates_var = tk.BooleanVar()
                try:
                    self.auto_check_updates_var.set(auto)
                except Exception:
                    pass
        except Exception:
            pass

        # Serial word delay (ms) - adjustable in Options dialog. Keep as IntVar
        try:
            default_ms = int((self._gui_settings or {}).get('serial_word_delay_ms', 200))
        except Exception:
            default_ms = 200
        try:
            self.serial_word_delay_ms = tk.IntVar(value=default_ms)
        except Exception:
            self.serial_word_delay_ms = tk.IntVar()
            try:
                self.serial_word_delay_ms.set(default_ms)
            except Exception:
                pass

        # Serial highlight color setting (name); map names to bg/fg
        try:
            default_color = str((self._gui_settings or {}).get('serial_highlight_color', 'yellow'))
        except Exception:
            default_color = 'yellow'
        try:
            self.serial_highlight_color = tk.StringVar(value=default_color)
        except Exception:
            self.serial_highlight_color = tk.StringVar()
            try:
                self.serial_highlight_color.set(default_color)
            except Exception:
                pass

        # mapping of friendly names to (bg, fg)
        try:
            self._serial_highlight_color_map = {
                'gray': ('#808080', 'white'),
                'dark red': ('#8B0000', 'white'),
                'red': ('#FF0000', 'white'),
                'orange': ('#FFA500', 'black'),
                'yellow': ('#FFFF00', 'black'),
                'green': ('#00AA00', 'white'),
                'light blue': ('#ADD8E6', 'black'),
                'blue': ('#0000FF', 'white'),
                'indigo': ('#4B0082', 'white'),
                'purple': ('#800080', 'white'),
            }
        except Exception:
            self._serial_highlight_color_map = {}


        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.main_frame = ttk.Frame(self.notebook)
        self.profiles_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.main_frame, text="Main")
        self.notebook.add(self.profiles_frame, text="Voice Profiles")

        # Custom vocab tab will let users manage runtime vocabulary used to bias Vosk
        self.vocab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.vocab_frame, text="Custom Words")

        # License gating: determine if commercial features should be enabled
        try:
            try:
                import license_manager
                self._is_commercial = (license_manager.license_type() == 'commercial')
            except Exception:
                self._is_commercial = False
        except Exception:
            self._is_commercial = False
        # Convenience flag controlling Automations UI/behavior
        self._automations_allowed = bool(self._is_commercial)

        try:
            if self._splash:
                self._splash.update_status("Building main tab...")
        except Exception:
            pass
        self._build_main_tab()

        try:
            if self._splash:
                self._splash.update_status("Building profiles tab...")
        except Exception:
            pass
        self._build_profiles_tab()

        try:
            if self._splash:
                self._splash.update_status("Building custom vocab tab...")
        except Exception:
            pass
        self._build_vocab_tab()

        self.engine: CaptionEngine | None = None
        # session state for opened/saved settings file (no automatic persistence)
        self._current_settings_file = None
        self._bad_words_path = None
        
        # Initialize automation manager BEFORE building the tab
        self.automation_manager = AutomationManager()
        self.automation_manager.set_callbacks(
            on_start=self._on_automation_start,
            on_stop=self._on_automation_stop
        )

        # If the GUI was started with simulation enabled, schedule a
        # synthetic automation start/stop to demonstrate UI feedback.
        self._simulate_automation = bool(simulate_automation)
        if self._simulate_automation:
            try:
                # Start after 1 second, stop after 7 seconds (gives time
                # for model start UI to be visible).
                self.safe_after(1000, lambda: self._on_automation_start())
                self.safe_after(7000, lambda: self._on_automation_stop())
            except Exception:
                pass

        # Noise cancellation tab (Hance integration)
        self.noise_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.noise_frame, text="Noise Cancelation")

        try:
            if self._splash:
                self._splash.update_status("Building noise cancelation tab...")
        except Exception:
            pass
        self._build_noise_tab()

        # Automations tab
        self.automations_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.automations_frame, text="Automations")

        try:
            if self._splash:
                self._splash.update_status("Building automations tab...")
        except Exception:
            pass
        self._build_automations_tab()

    def quit(self):
        """Override quit to ensure clean shutdown of automation scheduler and engine."""
        try:
            # Stop the capture engine if running
            if getattr(self, 'engine', None):
                try:
                    if self.engine and self.engine.running:
                        self.engine.stop()
                except Exception:
                    pass
        except Exception:
            pass
        
        try:
            # Stop automation scheduler gracefully
            if getattr(self, 'automation_manager', None):
                try:
                    self.automation_manager.stop_scheduler()
                except Exception:
                    pass
        except Exception:
            pass
        
        # Give threads a moment to finish
        try:
            import time
            time.sleep(0.5)
        except Exception:
            pass
        
        # Destroy the window to fully close the app
        try:
            self.destroy()
        except Exception:
            # Fallback to quit if destroy fails
            super().quit()

    def safe_after(self, delay, func, *args):
        """Call after() only if the window still exists."""
        try:
            if self.winfo_exists():
                return tk.Tk.after(self, delay, func, *args)
        except Exception:
            pass
        return None

    def _set_window_icon(self, win):
        """Set the application icon on a given window (Toplevel or root).
        Uses the bundled icon.ico when available; falls back to PhotoImage.
        """
        try:
            try:
                icon_path = resources._resource_path('icon.ico')
            except Exception:
                icon_path = 'icon.ico'
            if icon_path and os.path.exists(icon_path):
                try:
                    win.iconbitmap(icon_path)
                except Exception:
                    try:
                        img = tk.PhotoImage(file=icon_path)
                        win.iconphoto(False, img)
                        # keep a reference so it isn't garbage-collected
                        self._app_icon_image = img
                    except Exception:
                        pass
        except Exception:
            pass

    def _startup_json_path(self):
        try:
            return os.path.expanduser('~/Documents/VAICCS/startup.json')
        except Exception:
            return os.path.join(os.getcwd(), 'VAICCS', 'startup.json')

    def _load_startup_json(self):
        p = self._startup_json_path()
        try:
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_startup_json(self, data: dict):
        p = self._startup_json_path()
        try:
            d = os.path.dirname(p)
            os.makedirs(d, exist_ok=True)
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False

    def _open_startup_options(self):
        """Open a small dialog to choose startup options and persist to
        ~/Documents/VAICCS/startup.json. The file will be automatically applied
        at program start when present."""
        dlg = tk.Toplevel(self)
        try:
            dlg.transient(self)
        except Exception:
            pass
        dlg.title("Startup Options")
        try:
            dlg.grab_set()
        except Exception:
            pass

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        # load existing values
        cur = self._load_startup_json() or {}
        save_val = cur.get('save', '')
        auto_val = bool(cur.get('autostart', False))
        show_val = bool(cur.get('show_error', False))

        save_var = tk.StringVar(value=save_val)
        auto_var = tk.BooleanVar(value=auto_val)
        show_var = tk.BooleanVar(value=show_val)

        # Save file chooser
        ttk.Label(frm, text='Settings file to load at startup:').pack(anchor=tk.W)
        sf = ttk.Frame(frm)
        sf.pack(fill=tk.X, pady=(4,6))
        try:
            ttk.Entry(sf, textvariable=save_var, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True)
        except Exception:
            pass
        def _choose_file():
            try:
                fn = filedialog.askopenfilename(title='Choose settings JSON', filetypes=[('JSON','*.json'),('All','*')])
                if fn:
                    save_var.set(fn)
            except Exception:
                pass
        ttk.Button(sf, text='Browse...', command=_choose_file).pack(side=tk.LEFT, padx=(6,0))

        # checkboxes
        ttk.Checkbutton(frm, text='Autostart model at launch', variable=auto_var).pack(anchor=tk.W)
        ttk.Checkbutton(frm, text='Show import/errors dialog on failure', variable=show_var).pack(anchor=tk.W)

        # explanatory text
        txt = ('If a startup.json file exists in your Documents/VAICCS folder, its options '
               'will be automatically applied at program start. This dialog writes that file.')
        ttk.Label(frm, text=txt, wraplength=480).pack(anchor=tk.W, pady=(8,6))

        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill=tk.X, pady=(8,0))
        def _on_save():
            data = {'save': save_var.get() or None, 'autostart': bool(auto_var.get()), 'show_error': bool(show_var.get())}
            ok = self._save_startup_json(data)
            try:
                if ok:
                    # immediately apply to current app (respecting license checks)
                    try:
                        startup_options_mod.apply_startup_options(self, data)
                    except Exception:
                        pass
                else:
                    messagebox.showerror('Startup Options', 'Failed to save startup.json')
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        ttk.Button(btn_frm, text='Save', command=_on_save).pack(side=tk.RIGHT, padx=(6,0))
        ttk.Button(btn_frm, text='Cancel', command=lambda: dlg.destroy()).pack(side=tk.RIGHT)

    def _log_button_states(self, reason: str = ""):
        """Lightweight debug print of Start/Stop button states."""
        try:
            s = self.start_btn['state']
        except Exception:
            s = 'unknown'
        try:
            t = self.stop_btn['state']
        except Exception:
            t = 'unknown'
        try:
            print(f"[UI] {reason} start={s} stop={t}")
        except Exception:
            pass

    def _build_main_tab(self):
        # Left: transcript (3/4)
        left = ttk.Frame(self.main_frame)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Transcript area with vertical scrollbar
        trans_frame = ttk.Frame(left)
        trans_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.transcript = tk.Text(trans_frame, wrap=tk.WORD)
        self.transcript.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.transcript_scroll = ttk.Scrollbar(trans_frame, orient=tk.VERTICAL, command=self.transcript.yview)
        self.transcript_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.transcript.config(yscrollcommand=self.transcript_scroll.set)

        # Right: controls (1/4) -- use a scrollable canvas so narrow windows can access all controls
        right_container = ttk.Frame(self.main_frame, width=250)
        right_container.pack(side=tk.RIGHT, fill=tk.Y)

        # Canvas + scrollbar
        right_canvas = tk.Canvas(right_container, width=250, highlightthickness=0)
        right_vscroll = ttk.Scrollbar(right_container, orient=tk.VERTICAL, command=right_canvas.yview)
        right_canvas.configure(yscrollcommand=right_vscroll.set)
        right_vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Inner frame that will hold the actual controls
        right = ttk.Frame(right_canvas)
        right_window = right_canvas.create_window((0, 0), window=right, anchor='nw')

        # Ensure scrollregion is updated when inner frame changes size
        def _update_right_scrollregion(event=None):
            try:
                right_canvas.configure(scrollregion=right_canvas.bbox('all'))
            except Exception:
                pass

        right.bind('<Configure>', lambda e: _update_right_scrollregion())
        # Ensure inner frame width matches canvas width
        def _on_canvas_config(event):
            try:
                right_canvas.itemconfigure(right_window, width=event.width)
            except Exception:
                pass

        right_canvas.bind('<Configure>', _on_canvas_config)

        # Mousewheel scrolling when over the right pane
        def _on_right_mousewheel(event):
            try:
                delta = getattr(event, 'delta', 0)
                if delta:
                    # On Windows delta is multiple of 120; on macOS trackpad often gives small values
                    if abs(delta) >= 120:
                        lines = int(-1 * (delta / 120))
                    else:
                        lines = -1 if delta > 0 else 1
                    right_canvas.yview_scroll(lines, 'units')
                    return
                # X11 wheel events may come as Button-4 (up) / Button-5 (down)
                num = getattr(event, 'num', None)
                if num == 4:
                    right_canvas.yview_scroll(-1, 'units')
                elif num == 5:
                    right_canvas.yview_scroll(1, 'units')
            except Exception:
                pass

        # Bind wheel events on both the canvas and the inner frame so scrolling works
        right_canvas.bind('<MouseWheel>', _on_right_mousewheel)
        right.bind('<MouseWheel>', _on_right_mousewheel)
        # X11 Linux
        right_canvas.bind('<Button-4>', _on_right_mousewheel)
        right_canvas.bind('<Button-5>', _on_right_mousewheel)
        right.bind('<Button-4>', _on_right_mousewheel)
        right.bind('<Button-5>', _on_right_mousewheel)

        self.start_btn = ttk.Button(right, text="Start", command=self.start_capture)
        self.start_btn.pack(pady=(20, 6), padx=8, fill=tk.X)

        self.stop_btn = ttk.Button(right, text="Stop", command=self.stop_capture, state=tk.DISABLED)
        self.stop_btn.pack(pady=6, padx=8, fill=tk.X)

        # Model selection
        ttk.Label(right, text="VOSK Model:").pack(pady=(12, 2), padx=8, anchor=tk.W)
        model_frame = ttk.Frame(right)
        model_frame.pack(padx=8, fill=tk.X)
        self.model_path_var = tk.StringVar()
        self.model_entry = ttk.Entry(model_frame, textvariable=self.model_path_var)
        self.model_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(model_frame, text="Browse...", command=self._browse_model).pack(side=tk.RIGHT, padx=(6, 0))
        # Punctuator selection (optional) - look for folders starting with 'vosk-recasepunc'
        ttk.Label(right, text="Punctuator (vosk-recasepunc...):").pack(pady=(8, 2), padx=8, anchor=tk.W)
        punct_frame = ttk.Frame(right)
        punct_frame.pack(padx=8, fill=tk.X)
        self.punctuator_var = tk.StringVar()
        self.punctuator_entry = ttk.Entry(punct_frame, textvariable=self.punctuator_var)
        self.punctuator_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(punct_frame, text="Browse...", command=self._browse_punctuator).pack(side=tk.RIGHT, padx=(6, 0))
        # Model status label
        self.model_status_var = tk.StringVar(value="Model: (not selected) - Demo mode")
        ttk.Label(right, textvariable=self.model_status_var, wraplength=220).pack(padx=8, pady=(6, 0), anchor=tk.W)
        # (Optional recase/punctuation UI removed - using plain Vosk model selection)
        # CPU threads control
        ttk.Label(right, text="CPU threads:").pack(pady=(8, 2), padx=8, anchor=tk.W)
        self.cpu_threads_var = tk.IntVar(value=0)
        self.cpu_threads_spin = ttk.Spinbox(right, from_=0, to=64, textvariable=self.cpu_threads_var)
        self.cpu_threads_spin.pack(padx=8, fill=tk.X)
        # Thread status label
        self.thread_status_var = tk.StringVar(value="Threads: auto (not applied)")
        ttk.Label(right, textvariable=self.thread_status_var).pack(padx=8, pady=(4, 8), anchor=tk.W)
        # Speaker ID / profile matching controls
        ttk.Label(right, text="Speaker ID (Voice Profiles):").pack(pady=(8, 2), padx=8, anchor=tk.W)
        self.profile_matching_var = tk.BooleanVar(value=False)
        self.profile_matching_chk = ttk.Checkbutton(right, text="Enable speaker matching", variable=self.profile_matching_var)
        self.profile_matching_chk.pack(padx=8, anchor=tk.W)

        # Threshold slider (0.0 - 1.0)
        self.profile_threshold_var = tk.DoubleVar(value=0.7)
        thr_frame = ttk.Frame(right)
        thr_frame.pack(padx=8, fill=tk.X, pady=(4, 8))
        ttk.Label(thr_frame, text="Match threshold:").pack(side=tk.LEFT)
        try:
            self.threshold_scale = ttk.Scale(thr_frame, from_=0.0, to=1.0, variable=self.profile_threshold_var, orient='horizontal')
            self.threshold_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6,6))
        except Exception:
            # fallback to entry if Scale not available
            self.threshold_entry = ttk.Entry(thr_frame, textvariable=self.profile_threshold_var)
            self.threshold_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6,6))
        # show percentage (e.g. 70%) while keeping internal var in [0.0..1.0]
        self.threshold_val_label = ttk.Label(thr_frame, text=f"{self.profile_threshold_var.get()*100:.0f}%")
        self.threshold_val_label.pack(side=tk.RIGHT)
        # update label when var changes
        try:
            self.profile_threshold_var.trace_add("write", lambda *a: self.threshold_val_label.config(text=f"{self.profile_threshold_var.get()*100:.0f}%"))
        except Exception:
            try:
                self.profile_threshold_var.trace("w", lambda *a: self.threshold_val_label.config(text=f"{self.profile_threshold_var.get()*100:.0f}%"))
            except Exception:
                pass
        # (Auto-scroll controlled from View menu)
        # Jump to latest button
        self.jump_btn = ttk.Button(right, text="Jump to latest", command=self._jump_to_latest)
        self.jump_btn.pack(padx=8, pady=(0, 8), fill=tk.X)

        # Clear and Save buttons for the transcript (side-by-side, half width each)
        btn_row = ttk.Frame(right)
        btn_row.pack(padx=8, pady=(0, 8), fill=tk.X)
        self.clear_btn = ttk.Button(btn_row, text="Clear", command=self._clear_transcript)
        self.clear_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,4))
        self.save_txt_btn = ttk.Button(btn_row, text="Save to TXT", command=self._save_transcript_txt)
        self.save_txt_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4,0))
        

        # Audio spectrum (visual aid) - sits above the Audio Input dropdown.
        try:
            self.spectrum_viz_main = AudioSpectrumVisualizer(right, height=64)
            self.spectrum_viz_main.pack(padx=8, pady=(10, 6), fill=tk.X)
            self.spectrum_viz_main.start()
        except Exception:
            self.spectrum_viz_main = None

        ttk.Label(right, text="Audio Input:").pack(pady=(6, 6), padx=8, anchor=tk.W)
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(right, textvariable=self.device_var, state="readonly")
        self.device_combo.pack(padx=8, fill=tk.X)

        try:
            if self._splash:
                self._splash.update_status("Detecting audio devices...")
        except Exception:
            pass
        self._populate_audio_devices()

        # Noise cancelation quick toggle (main page)
        try:
            self.noise_chk = ttk.Checkbutton(right, text="Enable Noise Cancelation", variable=self.noise_enabled_var, command=self._on_toggle_noise)
            self.noise_chk.pack(padx=8, anchor=tk.W, pady=(6,8))
            # Disable noise controls for non-commercial (personal/eval) mode
            try:
                if not getattr(self, '_is_commercial', False):
                    self.noise_chk.config(state=tk.DISABLED)
            except Exception:
                pass
        except Exception:
            pass

        # Serial output controls
        ttk.Label(right, text="Serial Output:").pack(pady=(12, 2), padx=8, anchor=tk.W)
        self.serial_enabled_var = tk.BooleanVar(value=False)
        self.serial_chk = ttk.Checkbutton(right, text="Enable Serial Output", variable=self.serial_enabled_var)
        self.serial_chk.pack(padx=8, anchor=tk.W)

        serial_frame = ttk.Frame(right)
        serial_frame.pack(padx=8, fill=tk.X)
        self.serial_port_var = tk.StringVar()
        # allow manual typing of a COM port (e.g., COM5) in case the adapter isn't detected
        self.serial_port_combo = ttk.Combobox(serial_frame, textvariable=self.serial_port_var, state="normal")
        self.serial_port_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(serial_frame, text="Refresh", command=self._populate_serial_ports).pack(side=tk.RIGHT, padx=(6,0))

        # Note: manual port entry removed — users should pick a port from the combobox

        baud_frame = ttk.Frame(right)
        baud_frame.pack(padx=8, fill=tk.X, pady=(6,0))
        ttk.Label(baud_frame, text="Baud:").pack(side=tk.LEFT)
        self.baud_var = tk.IntVar(value=9600)
        self.baud_spin = ttk.Spinbox(baud_frame, from_=1200, to=115200, increment=300, textvariable=self.baud_var)
        self.baud_spin.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6,0))

        self.serial_connect_btn = ttk.Button(right, text="Connect Serial", command=lambda: self._toggle_serial_connect())
        self.serial_connect_btn.pack(padx=8, pady=(6,4), fill=tk.X)
        self.serial_test_btn = ttk.Button(right, text="Send Test", command=lambda: self._send_test_serial())
        self.serial_test_btn.pack(padx=8, pady=(0,8), fill=tk.X)

        self.serial_status_var = tk.StringVar(value="Serial: disconnected")
        ttk.Label(right, textvariable=self.serial_status_var, wraplength=220).pack(padx=8, anchor=tk.W)

        # serial manager
        self.serial_manager = None
        # queue and worker for serial word-by-word sending
        try:
            self._serial_send_queue = queue.Queue()
        except Exception:
            self._serial_send_queue = None
        self._serial_send_worker = None
        self._serial_send_stop_event = None
        # mapping display -> device name (e.g. "COM3 - FTDI" -> "COM3")
        self._serial_display_map = {}
        # saved device loaded from settings (actual device name) to try to select after populating
        self._saved_serial_device = None
        try:
            if self._splash:
                self._splash.update_status("Detecting serial ports...")
        except Exception:
            pass
        self._populate_serial_ports()

        # custom vocab manager (persisted to custom_vocab.json)
        try:
            from custom_vocab import CustomVocabManager
            self.vocab_mgr = CustomVocabManager()
        except Exception:
            self.vocab_mgr = None
        # model download control state
        self._model_download_cancel_event = None
        self._model_download_thread = None
        # models folder where downloaded models are installed
        try:
            # Allow explicit override via environment variable for packaged
            # builds or tests: `VAICCS_MODELS_ROOT` or `VOSK_MODELS_ROOT`.
            env_root = os.environ.get('VAICCS_MODELS_ROOT') or os.environ.get('VOSK_MODELS_ROOT')

            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            try:
                script_dir = os.path.abspath(os.path.dirname(__file__))
            except Exception:
                script_dir = exe_dir

            # Determine OS temp dir for detection of onefile extraction
            try:
                tmpdir = os.path.abspath(tempfile.gettempdir())
            except Exception:
                tmpdir = None

            def _is_under_tmp(p: str) -> bool:
                try:
                    if not p or not tmpdir:
                        return False
                    return os.path.abspath(p).lower().startswith(tmpdir.lower())
                except Exception:
                    return False

            # Resolve preferred root in order of preference:
            # 1) explicit env var
            # 2) script_dir if it's not under temp (running from source) — prefer project folder while running from VSCode/IDE
            # 3) exe_dir if it's not under temp (packaged)
            # 4) per-user LOCALAPPDATA under 'VAICCS' (persistent)
            # 5) exe_dir (last resort)
            chosen = None
            if env_root:
                chosen = env_root
            else:
                # On macOS:
                # - If packaged/frozen (.app), prefer a Models folder next to the executable
                #   at <App>.app/Contents/MacOS/Models.
                # - Otherwise (running from source), keep using the per-user VAICCS folder.
                if sys.platform == 'darwin':
                    if getattr(sys, 'frozen', False):
                        chosen = exe_dir
                    else:
                        try:
                            chosen = resources.get_vaiccs_root()
                        except Exception:
                            chosen = os.path.join(os.path.expanduser('~'), 'Documents', 'VAICCS')
                else:
                    if script_dir and not _is_under_tmp(script_dir):
                        chosen = script_dir
                    elif exe_dir and not _is_under_tmp(exe_dir):
                        chosen = exe_dir
                    else:
                        # Use a platform-appropriate per-user folder for persistent data
                        try:
                            if sys.platform.startswith('win'):
                                local = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
                            else:
                                local = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
                        except Exception:
                            local = None
                        if local:
                            chosen = os.path.join(local, 'VAICCS')
                        else:
                            chosen = exe_dir
            # Save the resolved application root path and models folder location.
            # Use platform-specific naming for models folder on macOS (Documents/VAICCS/Models)
            self.app_root = os.path.abspath(chosen)
            models_dir_name = 'Models' if sys.platform == 'darwin' else 'models'
            self.models_root = os.path.join(self.app_root, models_dir_name)
            os.makedirs(self.models_root, exist_ok=True)
            # Write startup log in models folder so packaged builds can report where the app writes models
            try:
                app_log = os.path.join(self.models_root, 'app_install.log')
                with open(app_log, 'a', encoding='utf-8') as lf:
                    lf.write(f"App root: {self.app_root}\nModels root: {self.models_root}\nWriteable: {os.access(self.models_root, os.W_OK)}\n\n")
            except Exception:
                pass
        except Exception:
            try:
                exe_app_root = os.path.dirname(os.path.abspath(sys.executable))
                self.app_root = exe_app_root
                models_dir_name = 'Models' if sys.platform == 'darwin' else 'models'
                self.models_root = os.path.join(exe_app_root, models_dir_name)
            except Exception:
                try:
                    script_app_root = os.path.abspath(os.path.dirname(__file__))
                    self.app_root = script_app_root
                    models_dir_name = 'Models' if sys.platform == 'darwin' else 'models'
                    self.models_root = os.path.join(script_app_root, models_dir_name)
                except Exception:
                    # final fallback: use current working directory
                    self.app_root = os.path.abspath(os.getcwd())
                    models_dir_name = 'Models' if sys.platform == 'darwin' else 'models'
                    self.models_root = os.path.join(self.app_root, models_dir_name)
            try:
                os.makedirs(self.models_root, exist_ok=True)
                try:
                    # write log similarly in fallback branch
                    app_log = os.path.join(self.models_root, 'app_install.log')
                    with open(app_log, 'a', encoding='utf-8') as lf:
                        lf.write(f"App fallback root: {self.app_root}\nModels root: {self.models_root}\nWriteable: {os.access(self.models_root, os.W_OK)}\n\n")
                except Exception:
                    pass
            except Exception:
                pass

        # Finalize splash and show main window
        try:
            if getattr(self, '_splash', None):
                try:
                    self._splash.update_status("Ready")
                except Exception:
                    pass
                try:
                    self._splash.close()
                except Exception:
                    pass
            try:
                self.deiconify()
            except Exception:
                pass
        except Exception:
            pass

        # On macOS, proactively trigger the microphone permission prompt by
        # briefly opening an input stream at launch.
        try:
            self.after(250, self._request_microphone_permission)
        except Exception:
            try:
                self.safe_after(250, self._request_microphone_permission)
            except Exception:
                pass

    def _request_microphone_permission(self):
        """Best-effort macOS mic permission prompt.

        macOS only shows the prompt after the app actually attempts to access
        the microphone, and only if the bundle Info.plist contains
        NSMicrophoneUsageDescription.
        """
        try:
            if sys.platform != 'darwin':
                return
        except Exception:
            return

        # Run once per app start.
        try:
            if getattr(self, '_mic_permission_probe_started', False):
                return
            self._mic_permission_probe_started = True
        except Exception:
            pass

        def _probe():
            try:
                # Respect current UI selection if one is set.
                try:
                    sel = self.device_combo.get() if getattr(self, 'device_combo', None) is not None else ''
                    if sel and ':' in sel:
                        idx = int(sel.split(':', 1)[0])
                        try:
                            sd.default.device = idx
                        except Exception:
                            pass
                except Exception:
                    pass

                # Open a tiny stream; this is what triggers the OS permission prompt.
                def _cb(indata, frames, time_info, status):
                    return

                try:
                    with sd.InputStream(samplerate=16000, channels=1, dtype='int16', callback=_cb):
                        time.sleep(0.25)
                except Exception as e:
                    msg = str(e)
                    # If permission was denied, guide the user to Settings.
                    if any(k in msg.lower() for k in ('not authorized', 'permission', 'denied', 'tcc')):
                        try:
                            self.safe_after(
                                0,
                                lambda: messagebox.showwarning(
                                    "Microphone Permission",
                                    "VAICCS could not access the microphone.\n\n"
                                    "Go to System Settings → Privacy & Security → Microphone and enable VAICCS, then restart the app.",
                                ),
                            )
                        except Exception:
                            pass
            except Exception:
                # Never block startup for this.
                return

        try:
            threading.Thread(target=_probe, daemon=True).start()
        except Exception:
            pass

    def _populate_audio_devices(self):
        try:
            devices = sd.query_devices()
            names = [f"{i}: {d['name']}" for i, d in enumerate(devices)]
            self.device_combo['values'] = names
            if names:
                self.device_combo.current(0)
        except Exception:
            self.device_combo['values'] = ["Default"]
            self.device_combo.current(0)

        # Bind user scroll interactions to pause auto-scroll
        try:
            # Mouse wheel (Windows)
            self.transcript.bind('<MouseWheel>', self._on_user_scroll)
            # Linux scroll
            # self.transcript.bind('<Button-4>', self._on_user_scroll)
            # self.transcript.bind('<Button-5>', self._on_user_scroll)
            # Scrollbar drag
            self.transcript_scroll.bind('<ButtonPress-1>', self._on_user_scroll)
            self.transcript_scroll.bind('<B1-Motion>', self._on_user_scroll)
        except Exception:
            pass

    def _populate_serial_ports(self):
        ports = []
        try:
            ports = list_serial_ports()
        except Exception:
            ports = []

        # ports may be list of dicts (new) or simple strings (old); normalize
        display_values = []
        self._serial_display_map.clear()
        for p in ports:
            if isinstance(p, dict):
                dev = p.get("device") or ""
                desc = p.get("description") or p.get("manufacturer") or ""
                vid = p.get("vid")
                pid = p.get("pid")
                vidpid = f" VID:0x{vid:04x}" if vid is not None else ""
                pidstr = f" PID:0x{pid:04x}" if pid is not None else ""
                extra = (vidpid + pidstr).strip()
                if extra:
                    label = f"{dev} - {desc} ({extra})"
                elif desc:
                    label = f"{dev} - {desc}"
                else:
                    label = f"{dev}"
                display_values.append(label)
                self._serial_display_map[label] = dev
            else:
                # assume string like 'COM3'
                display_values.append(p)
                self._serial_display_map[p] = p

        # preserve current selection if available, or try saved device
        cur_display = self.serial_port_var.get()
        vals = display_values
        if cur_display and cur_display not in vals:
            vals = [cur_display] + vals
        self.serial_port_combo['values'] = vals

        # try to select the saved device if present
        try:
            if self._saved_serial_device:
                # find display whose mapped device matches the saved device
                for disp, dev in self._serial_display_map.items():
                    if dev == self._saved_serial_device:
                        self.serial_port_combo.set(disp)
                        break
                else:
                    # fallback to saved plain name (user can type it)
                    self.serial_port_combo.set(self._saved_serial_device)
            else:
                if vals:
                    if cur_display and cur_display in vals:
                        self.serial_port_combo.set(cur_display)
                    else:
                        self.serial_port_combo.current(0)
        except Exception:
            pass

        # update status with number of detected ports (helpful for debugging adapters)
        try:
            self.serial_status_var.set(f"Serial: {len(display_values)} ports detected")
        except Exception:
            pass

    def _toggle_serial_connect(self):
        enabled = bool(self.serial_enabled_var.get())
        # resolve selection from combobox to actual device name (e.g., 'COM3')
        selected_display = self.serial_port_var.get().strip()
        port = selected_display
        try:
            if selected_display in self._serial_display_map:
                port = self._serial_display_map[selected_display]
        except Exception:
            pass
        try:
            baud = int(self.baud_var.get())
        except Exception:
            baud = 9600
        if not enabled:
            # disconnect
            try:
                if self.serial_manager:
                    self.serial_manager.close()
            except Exception:
                pass
            # stop worker and clear queue
            try:
                self._stop_serial_worker()
            except Exception:
                pass
            try:
                self.serial_manager = None
            except Exception:
                self.serial_manager = None
            try:
                self.serial_status_var.set("Serial: disabled")
            except Exception:
                pass
            # no automatic persistence
            return

        # connect
        if not port:
            messagebox.showwarning("Serial", "Select a serial port first")
            self.serial_enabled_var.set(False)
            return

        if SerialManager is None:
            messagebox.showerror("Serial", "Serial support not available (pyserial or helper missing)")
            self.serial_enabled_var.set(False)
            return

        try:
            self.serial_manager = SerialManager(port, baud)
            opened = False
            try:
                opened = bool(self.serial_manager.open())
            except Exception:
                opened = False

            if not opened:
                try:
                    self.serial_manager.close()
                except Exception:
                    pass
                self.serial_manager = None
                # show detailed error if available
                err = getattr(self.serial_manager, 'last_error', None)
                if not err:
                    err = f"failed to open {port}@{baud}"
                try:
                    self.serial_status_var.set(f"Serial error: {err}")
                except Exception:
                    pass
                try:
                    messagebox.showerror("Serial", f"Failed to open serial port: {err}")
                except Exception:
                    pass
                self.serial_enabled_var.set(False)
                return

            self.serial_status_var.set(f"Serial: connected {port}@{baud}")
            try:
                # ensure worker is running to process queued captions
                self._start_serial_worker()
            except Exception:
                pass
        except Exception as e:
            try:
                self.serial_manager = None
            except Exception:
                pass
            try:
                self.serial_status_var.set(f"Serial error: {e}")
            except Exception:
                pass
            try:
                messagebox.showerror("Serial", f"Failed to open serial port: {e}")
            except Exception:
                pass
            self.serial_enabled_var.set(False)
            return
        # no automatic persistence

    #send a test line over serial button
    def _send_test_serial(self):
        try:
            if not self.serial_manager:
                messagebox.showwarning("Serial", "Not connected")
                return
            ok = False
            try:
                ok = bool(self.serial_manager.send_line("TEST: Hello from Caption GUI"))
            except Exception:
                ok = False

            if ok:
                messagebox.showinfo("Serial", "Test sent")
            else:
                try:
                    messagebox.showerror("Serial", "Serial send failed (port closed or write error)")
                except Exception:
                    pass
        except Exception as e:
            messagebox.showerror("Serial", f"Serial send failed: {e}")

    def _start_serial_worker(self):
        """Start a background worker that processes `self._serial_send_queue` sequentially.
        The worker will finish each queued caption (all words) before taking the next.
        """
        try:
            if getattr(self, '_serial_send_queue', None) is None:
                self._serial_send_queue = queue.Queue()
        except Exception:
            self._serial_send_queue = queue.Queue()

        if getattr(self, '_serial_send_worker', None) is not None:
            # already running
            return

        stop_evt = threading.Event()
        self._serial_send_stop_event = stop_evt

        def _worker_loop():
            try:
                while not stop_evt.is_set():
                    try:
                        item = self._serial_send_queue.get(timeout=0.25)
                    except Exception:
                        continue
                    if item is None:
                        continue
                    text = item or ''
                    sm = getattr(self, 'serial_manager', None)
                    if not sm:
                        # drop until reconnected
                        continue

                    # compute base_char_offset by locating the inserted text in the transcript
                    try:
                        buf = self.transcript.get('1.0', 'end-1c')
                        pos = buf.rfind(text)
                        base_pos = pos if pos >= 0 else None
                    except Exception:
                        base_pos = None

                    # build word ranges
                    ranges = []
                    try:
                        for m in re.finditer(r'\S+', text):
                            ranges.append((m.start(), m.end(), m.group(0)))
                    except Exception:
                        offs = 0
                        for w in (text or '').split():
                            i = (text or '').find(w, offs)
                            if i >= 0:
                                ranges.append((i, i + len(w), w))
                                offs = i + len(w)

                    try:
                        delay_ms = int(getattr(self, 'serial_word_delay_ms', tk.IntVar(value=200)).get())
                    except Exception:
                        delay_ms = 200

                    # process every word in this caption fully
                    for (st, ed, w) in ranges:
                        if stop_evt.is_set():
                            break

                        # compute absolute indices relative to 1.0 if base_pos known
                        sidx = None
                        eidx = None
                        try:
                            if base_pos is not None:
                                sidx = f"1.0 + {base_pos + st}c"
                                eidx = f"1.0 + {base_pos + ed}c"
                        except Exception:
                            sidx = None
                            eidx = None

                        # schedule highlight on main thread
                        try:
                            if sidx is not None and eidx is not None:
                                try:
                                    self.safe_after(0, lambda si=sidx, ei=eidx, w=w: self._apply_serial_highlight(si, ei, w))
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # send word
                        try:
                            ok = bool(sm.send_line(w))
                            if not ok:
                                try:
                                    self.serial_status_var.set("Serial send failed (port closed or write error)")
                                except Exception:
                                    pass
                        except Exception as e:
                            try:
                                self.serial_status_var.set(f"Serial send error: {e}")
                            except Exception:
                                pass

                        # wait configured delay
                        waited = 0.0
                        step = 0.05
                        total = max(0.0, float(delay_ms) / 1000.0)
                        while waited < total:
                            if stop_evt.is_set():
                                break
                            time.sleep(min(step, total - waited))
                            waited += step

                    # done with this caption; loop to next queued caption
            finally:
                try:
                    # clear worker ref
                    self._serial_send_worker = None
                except Exception:
                    pass

        th = threading.Thread(target=_worker_loop, daemon=True)
        self._serial_send_worker = th
        th.start()

    def _stop_serial_worker(self):
        try:
            evt = getattr(self, '_serial_send_stop_event', None)
            if evt is not None:
                try:
                    evt.set()
                except Exception:
                    pass
            try:
                if getattr(self, '_serial_send_queue', None) is not None:
                    # drain queue
                    try:
                        while True:
                            self._serial_send_queue.get_nowait()
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass

    def _browse_model(self):
        try:
            start = self.model_path_var.get().strip() if getattr(self, 'model_path_var', None) is not None else ''
        except Exception:
            start = ''
        if not start:
            try:
                start = self.models_root
            except Exception:
                start = ''
        if not start:
            try:
                start = os.path.join(os.path.expanduser('~'), 'Documents')
            except Exception:
                start = ''

        path = filedialog.askdirectory(title="Select VOSK model directory", initialdir=start if start else None)
        if path:
            try:
                path = os.path.abspath(os.path.expanduser(path))
            except Exception:
                pass
            self.model_path_var.set(path)
            self._update_model_status()
    # recase UI and helpers removed

    def _is_valid_punctuator(self, path: str) -> bool:
        """Return True if `path` is a directory and its basename starts with 'vosk-recasepunc'."""
        try:
            if not path:
                return False
            if not os.path.isdir(path):
                return False
            base = os.path.basename(os.path.normpath(path))
            return base.lower().startswith('vosk-recasepunc')
        except Exception:
            return False

    def _browse_punctuator(self):
        try:
            start = self.punctuator_var.get().strip() if getattr(self, 'punctuator_var', None) is not None else self.models_root
            if not start:
                start = self.models_root
            path = filedialog.askdirectory(title="Select punctuator folder (vosk-recasepunc...)", initialdir=start)
            if not path:
                return
            if not self._is_valid_punctuator(path):
                messagebox.showerror("Punctuator", "Selected folder does not appear to be a 'vosk-recasepunc' model folder.")
                return
            self.punctuator_var.set(path)
        except Exception as e:
            try:
                messagebox.showerror("Punctuator", f"Failed to select punctuator: {e}")
            except Exception:
                pass

    def _is_valid_model(self, path: str) -> bool:
        """Quick heuristic: check for common VOSK model files/folders."""
        if not path or not os.path.isdir(path):
            return False
        # common indicators
        checks = [
            os.path.join(path, "am"),
            os.path.join(path, "model.conf"),
            os.path.join(path, "final.mdl"),
            os.path.join(path, "HCLG.fst"),
            os.path.join(path, "conf"),
        ]
        for c in checks:
            if os.path.exists(c):
                return True
        # also allow if directory contains many files (fallback)
        try:
            if any(os.scandir(path)):
                return True
        except Exception:
            pass
        return False

    def _update_model_status(self):
        path = self.model_path_var.get().strip()
        if path and self._is_valid_model(path):
            self.model_status_var.set(f"Model: {os.path.basename(path)}")
        elif path:
            self.model_status_var.set(f"Model: {os.path.basename(path)} (invalid)")
        else:
            self.model_status_var.set("Model: (not selected) - Demo mode")

    def _on_user_scroll(self, event=None):
        """Called when the user scrolls the transcript; pause auto-scroll unless user is at bottom."""
        try:
            top, bottom = self.transcript.yview()
            # if bottom very close to 1.0, consider at bottom
            at_bottom = bottom >= 0.999
            if at_bottom:
                # if user scrolled to bottom, re-enable auto-scroll
                self.auto_scroll_var.set(True)
            else:
                # user scrolled up, disable auto-scroll
                self.auto_scroll_var.set(False)
        except Exception:
            pass

    def _jump_to_latest(self):
        try:
            # enable auto-scroll and move to end
            self.auto_scroll_var.set(True)
            self.transcript.see(tk.END)
        except Exception:
            pass

    def _clear_transcript(self):
        """Clear the transcript area after user confirmation."""
        try:
            ok = messagebox.askyesno("Clear Transcript", "Clear the closed captioning terminal? This cannot be undone.")
            if not ok:
                return
            try:
                self.transcript.delete('1.0', tk.END)
            except Exception:
                pass
        except Exception:
            pass

    def _save_transcript_txt(self):
        """Save the transcript contents to a text file (Save As dialog)."""
        try:
            path = filedialog.asksaveasfilename(title="Save transcript as", defaultextension='.txt', filetypes=[('Text files', '*.txt'), ('All files', '*')])
            if not path:
                return
            try:
                text = self.transcript.get('1.0', tk.END)
            except Exception:
                text = ''
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(text)
                try:
                    messagebox.showinfo("Save Transcript", f"Saved transcript to {path}")
                except Exception:
                    pass
            except Exception as e:
                try:
                    messagebox.showerror("Save Transcript", f"Failed to save transcript: {e}")
                except Exception:
                    pass
        except Exception:
            pass

    def _export_transcript_srt(self):
        """Export the transcript as a simple SRT file.

        This is a best-effort export: each non-empty line becomes a caption
        with a fixed duration (2s). If you want real timestamps, we would
        need to capture timestamps at insertion time.
        """
        try:
            path = filedialog.asksaveasfilename(title="Export transcript as SRT", defaultextension='.srt', filetypes=[('SRT files', '*.srt'), ('All files', '*')])
            if not path:
                return
            try:
                raw = self.transcript.get('1.0', tk.END)
            except Exception:
                raw = ''
            # build simple SRT using configurable duration per caption
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            def fmt_time(ms: int) -> str:
                h = ms // 3600000
                m = (ms % 3600000) // 60000
                s = (ms % 60000) // 1000
                ms_rem = ms % 1000
                return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"

            out_lines = []
            # duration in milliseconds from UI (default 2s)
            try:
                dur_s = float(getattr(self, 'srt_duration_var', tk.DoubleVar(value=2.0)).get())
            except Exception:
                dur_s = 2.0
            dur_ms = max(100, int(dur_s * 1000))
            for i, ln in enumerate(lines, start=1):
                start_ms = (i - 1) * dur_ms
                end_ms = start_ms + dur_ms
                out_lines.append(str(i))
                out_lines.append(f"{fmt_time(start_ms)} --> {fmt_time(end_ms)}")
                out_lines.append(ln)
                out_lines.append("")

            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(out_lines))
                try:
                    messagebox.showinfo("Export SRT", f"Exported {len(lines)} captions to {path}")
                except Exception:
                    pass
            except Exception as e:
                try:
                    messagebox.showerror("Export SRT", f"Failed to export SRT: {e}")
                except Exception:
                    pass
        except Exception:
            pass

    def _load_settings(self):
        # legacy: load settings from a file provided by caller via _on_open_settings
        # this method will be called with a path by _on_open_settings; if no
        # path is provided, do nothing.
        pass

    def _load_gui_settings(self):
        try:
            here = os.path.dirname(__file__)
            local_path = os.path.join(here, 'gui_settings.json')
            if os.path.exists(local_path):
                with open(local_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_gui_settings(self):
        try:
            here = os.path.dirname(__file__)
            local_path = os.path.join(here, 'gui_settings.json')
            with open(local_path, 'w', encoding='utf-8') as lf:
                json.dump(self._gui_settings or {}, lf, indent=2)
        except Exception:
            pass

    def _apply_serial_highlight(self, sidx, eidx, word=None):
        """Apply the serial highlight tag on the main thread using normalized indices."""
        try:
            # normalize/validate indices
            try:
                ns = self.transcript.index(sidx)
                ne = self.transcript.index(eidx)
            except Exception:
                ns = None
                ne = None
            if ns and ne:
                try:
                    # configure tag colors
                    try:
                        sel = str(getattr(self, 'serial_highlight_color', tk.StringVar(value='yellow')).get())
                    except Exception:
                        sel = 'yellow'
                    bg, fg = self._serial_highlight_color_map.get(sel, (sel, 'black'))
                    self.transcript.tag_config('serial_send', background=bg, foreground=fg)
                except Exception:
                    pass
                try:
                    # remove prev then add
                    try:
                        self.transcript.tag_remove('serial_send', '1.0', tk.END)
                    except Exception:
                        pass
                    self.transcript.tag_add('serial_send', ns, ne)
                except Exception:
                    pass
                try:
                    if word:
                        self.serial_status_var.set(f"Highlight: {word}")
                        try:
                            self.safe_after(500, lambda: self.serial_status_var.set(f"Serial: connected" if getattr(self, 'serial_manager', None) else "Serial: disconnected"))
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

    def _on_toggle_auto_check_updates(self):
        """Persist the user's preference for automatic update checks."""
        try:
            s = self._gui_settings or {}
            ups = s.get('updates')
            if ups is None:
                ups = {}
                s['updates'] = ups
            ups['auto_check'] = bool(getattr(self, 'auto_check_updates_var', tk.BooleanVar(value=False)).get())
            self._gui_settings = s
            self._save_gui_settings()
        except Exception:
            pass

    def _maybe_auto_check_updates(self):
        try:
            s = self._gui_settings or {}
            ups = s.get('updates', {})
            auto = bool(ups.get('auto_check', False))
            if not auto:
                return
            last = ups.get('last_checked')
            if last:
                try:
                    last_dt = datetime.datetime.fromisoformat(last)
                except Exception:
                    last_dt = None
            else:
                last_dt = None
            now = datetime.datetime.now(datetime.timezone.utc)
            do_check = False
            if last_dt is None:
                do_check = True
            else:
                try:
                    delta = now - last_dt
                    if delta.total_seconds() > 24 * 3600:
                        do_check = True
                except Exception:
                    do_check = True

            if do_check:
                # run check in background
                self._check_for_updates(manual=False)
        except Exception:
            pass

    def _check_for_updates(self, manual: bool = True):
        # Kick off a background thread to query GitHub Releases
        try:
            t = threading.Thread(target=self._check_for_updates_thread, args=(manual,), daemon=True)
            t.start()
        except Exception:
            pass

    def _check_for_updates_thread(self, manual: bool = False):
        try:
            repo_api = 'https://api.github.com/repos/dominicskywalkr/VAICCS/releases/latest'
            headers = {'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'VAICCS-Updater/1.0'}
            try:
                resp = requests.get(repo_api, headers=headers, timeout=10)
            except Exception:
                # network error
                if manual:
                    try:
                        messagebox.showinfo('Updates', 'Failed to check for updates (network error).')
                    except Exception:
                        pass
                return

            if resp.status_code != 200:
                # The `/releases/latest` endpoint will not return pre-releases or drafts.
                # Try the releases list API (includes published prereleases) and pick
                # the most-recent entry. Fall back to the original HTML-scrape behavior
                # if the API list call fails.
                try:
                    list_api = 'https://api.github.com/repos/dominicskywalkr/VAICCS/releases'
                    rlist = requests.get(list_api, headers=headers, timeout=10)
                    if rlist.status_code == 200 and rlist.text:
                        try:
                            ldata = rlist.json() or []
                            if isinstance(ldata, list) and len(ldata) > 0:
                                # Choose the first release in the list (most-recent).
                                data = ldata[0]
                            else:
                                data = None
                        except Exception:
                            data = None
                    else:
                        data = None

                    if not data:
                        # Attempt a web-fallback: fetch the releases page HTML and find the first
                        # occurrence of "/releases/tag/<tag>" which usually points to the latest release.
                        releases_page = 'https://github.com/dominicskywalkr/VAICCS/releases'
                        try:
                            r3 = requests.get(releases_page, timeout=10)
                            tag = ''
                            if r3.status_code == 200 and r3.text:
                                try:
                                    # look for links to releases with tag in href
                                    m = re.search(r'/releases?/tag/([^"\'\s>]+)', r3.text)
                                    if m:
                                        tag = m.group(1)
                                except Exception:
                                    tag = ''

                            if tag:
                                latest_ver = re.sub(r'^v', '', tag, flags=re.IGNORECASE)
                                data = {'name': tag, 'body': ''}
                            else:
                                if manual:
                                    reason = f'HTTP {resp.status_code}'
                                    try:
                                        rl = resp.headers.get('X-RateLimit-Remaining')
                                        if rl is not None:
                                            reason += f' (rate limit remaining: {rl})'
                                    except Exception:
                                        pass
                                    try:
                                        messagebox.showinfo('Updates', f'Failed to determine latest release from GitHub (API {reason}).\nOpening releases page in your browser.')
                                    except Exception:
                                        pass
                                    try:
                                        webbrowser.open(releases_page)
                                    except Exception:
                                        pass
                                return
                        except Exception:
                            if manual:
                                try:
                                    messagebox.showinfo('Updates', 'Failed to check for updates (web fallback error).')
                                except Exception:
                                    pass
                            return
                except Exception:
                    if manual:
                        try:
                            messagebox.showinfo('Updates', 'Failed to check for updates (releases list error).')
                        except Exception:
                            pass
                    return
            else:
                data = resp.json()
            # Prefer the release "name" (e.g. "VAICCS 1.0 beta-1"); fall back to tag_name
            release_name = str(data.get('name') or data.get('tag_name') or '')
            # If the release name starts with the product name, strip it ("VAICCS 1.0 beta-1" -> "1.0 beta-1")
            m = re.match(r'^(?:VAICCS\s*)?(.*)$', release_name, flags=re.IGNORECASE)
            latest_ver = m.group(1).strip() if m else release_name
            # normalize leading v if present
            latest_ver = re.sub(r'^v', '', latest_ver, flags=re.IGNORECASE)
            changelog = data.get('body', '') or ''
            html_url = data.get('html_url') or f'https://github.com/dominicskywalkr/VAICCS/releases'
            assets = data.get('assets', []) or []
            asset_url = None
            asset_name = None
            # Look specifically for the known Mac installer filename first
            desired_asset = 'VAICCS.MacOS.AMD64.dmg'
            for a in assets:
                name = a.get('name', '') or ''
                if name == desired_asset:
                    asset_url = a.get('browser_download_url')
                    asset_name = name
                    break
            # fallback: pick first common Mac installer-like asset
            if not asset_url:
                for a in assets:
                    name = a.get('name', '') or ''
                    if name.lower().endswith('.dmg'):
                        asset_url = a.get('browser_download_url')
                        asset_name = name
                        break

            # If no assets were provided (e.g., API rate-limited or initial call failed),
            # try the releases-by-tag API if we can determine a tag. Also attempt
            # to construct a direct download URL for the known installer filename
            # (GitHub releases download URL pattern) and verify it with HEAD.
            try:
                if not assets:
                    tag = data.get('tag_name') or ''
                    if not tag:
                        # try to extract from html_url
                        try:
                            from urllib.parse import unquote, urlparse
                            p = urlparse(html_url).path
                            p = unquote(p or '')
                            mtag = re.search(r'/releases?/tag/([^/]+)', p)
                            if mtag:
                                tag = mtag.group(1)
                            else:
                                seg = p.rstrip('/').split('/')[-1] if p else ''
                                if re.search(r'\d', seg):
                                    tag = seg
                        except Exception:
                            tag = ''

                    if tag:
                        tag_api = f'https://api.github.com/repos/dominicskywalkr/VAICCS/releases/tags/{tag}'
                        try:
                            rtag = requests.get(tag_api, headers=headers, timeout=10)
                            if rtag.status_code == 200:
                                tdata = rtag.json()
                                tassets = tdata.get('assets', []) or []
                                if tassets:
                                    assets = tassets
                                    data = tdata
                                    # re-run asset selection for updated assets
                                    for a in assets:
                                        name = a.get('name', '') or ''
                                        if name == desired_asset:
                                            asset_url = a.get('browser_download_url')
                                            asset_name = name
                                            break
                                    if not asset_url:
                                        for a in assets:
                                            name = a.get('name', '') or ''
                                            if name.lower().endswith('.dmg'):
                                                asset_url = a.get('browser_download_url')
                                                asset_name = name
                                                break
                                    if not asset_url:
                                        for a in assets:
                                            name = a.get('name', '') or ''
                                            if name.lower().endswith(('.exe', '.msi', '.zip')):
                                                asset_url = a.get('browser_download_url')
                                                asset_name = name
                                                break
                        except Exception:
                            pass
            except Exception:
                pass

            # If still no asset_url, try constructing a direct download URL using
            # likely tag candidates and check with a HEAD request.
            try:
                if not asset_url:
                    tag_candidates = []
                    # prefer explicit tag_name from API if present
                    tname = data.get('tag_name') or ''
                    if tname:
                        tag_candidates.append(tname)
                    # also try release_name (raw) and latest_ver (normalized)
                    if release_name:
                        tag_candidates.append(release_name)
                    if latest_ver:
                        tag_candidates.append(latest_ver)

                    # normalize and try variants (with/without leading v)
                    tried = set()
                    for t in tag_candidates:
                        if not t:
                            continue
                        for candidate in (t, f'v{t}' if not str(t).lower().startswith('v') else t):
                            if candidate in tried:
                                continue
                            tried.add(candidate)
                            try:
                                safe_tag = quote(str(candidate), safe='')
                                test_url = f'https://github.com/dominicskywalkr/VAICCS/releases/download/{safe_tag}/{desired_asset}'
                                h = requests.head(test_url, allow_redirects=True, timeout=10, headers=headers)
                                if h.status_code == 200:
                                    asset_url = test_url
                                    asset_name = desired_asset
                                    break
                            except Exception:
                                pass
                        if asset_url:
                            break
            except Exception:
                pass

            current = getattr(mainmod, '__version__', '0.0.0')

            # For manual checks, prepare debug info to help diagnose mismatch
            try:
                ln_norm = _normalize_for_parse(latest_ver)
            except Exception:
                ln_norm = latest_ver
            try:
                cn_norm = _normalize_for_parse(current)
            except Exception:
                cn_norm = current

            def _normalize_for_parse(s: str) -> str:
                if not s:
                    return s
                s = s.strip()
                # remove leading product name if present and leading v
                s = re.sub(r'^(?:vaiccs\s*)', '', s, flags=re.IGNORECASE)
                s = re.sub(r'^v', '', s, flags=re.IGNORECASE)
                # Normalize common pre-release words to PEP 440 short forms
                s = re.sub(r'(?i)\balpha[-\s]?(\d+)\b', r'a\1', s)
                s = re.sub(r'(?i)\bbeta[-\s]?(\d+)\b', r'b\1', s)
                s = re.sub(r'(?i)\brc[-\s]?(\d+)\b', r'rc\1', s)
                # Replace stray spaces and hyphens between numeric and pre-release
                s = re.sub(r'\s*[-\s]\s*', '', s)
                return s

            def _is_newer(latest, current):
                try:
                    from packaging import version as _pv
                    ln = _normalize_for_parse(str(latest))
                    cn = _normalize_for_parse(str(current))
                    return _pv.parse(ln) > _pv.parse(cn)
                except Exception:
                    # fallback: semver-like compare with pre-release handling
                    def _parse_simple(s: str):
                        s = str(s or '')
                        s = s.strip()
                        # split main numeric and prerelease parts
                        m = re.match(r"^([0-9]+(?:\.[0-9]+)*)(?:[-_\s]?([ab]|rc|alpha|beta|pre|c|b|a)[-_.]?(\d+)?)?$", s, flags=re.IGNORECASE)
                        if not m:
                            # try to extract numbers only
                            nums = tuple(int(x) for x in re.findall(r'\d+', s))
                            return (nums, None, 0)
                        nums = tuple(int(x) for x in m.group(1).split('.'))
                        pr_type = m.group(2)
                        pr_num = m.group(3)
                        if pr_type:
                            pr_type = pr_type.lower()
                            # normalize common aliases
                            if pr_type in ('a', 'alpha'):
                                pr_type = 'a'
                            elif pr_type in ('b', 'beta'):
                                pr_type = 'b'
                            elif pr_type in ('c', 'rc'):
                                pr_type = 'rc'
                        if pr_num:
                            try:
                                pr_num = int(pr_num)
                            except Exception:
                                pr_num = 0
                        else:
                            pr_num = 0
                        return (nums, pr_type, pr_num)

                    def _cmp(a, b):
                        # compare numeric tuples
                        an, atype, anum = _parse_simple(a)
                        bn, btype, bnum = _parse_simple(b)
                        if an != bn:
                            # pad shorter with zeros
                            la = list(an)
                            lb = list(bn)
                            L = max(len(la), len(lb))
                            la += [0] * (L - len(la))
                            lb += [0] * (L - len(lb))
                            if tuple(la) != tuple(lb):
                                return 1 if tuple(la) > tuple(lb) else -1
                        # numeric equal; handle prerelease: None means final release (greater)
                        order = {None: 3, 'rc': 2, 'b': 1, 'a': 0}
                        ao = order.get(atype, -1)
                        bo = order.get(btype, -1)
                        if ao != bo:
                            return 1 if ao > bo else -1
                        # same prerelease type: compare numbers
                        if anum != bnum:
                            return 1 if anum > bnum else -1
                        return 0

                    return _cmp(latest, current) == 1

            newer = False
            try:
                newer = _is_newer(latest_ver, current)
            except Exception:
                newer = False

            # Debug info removed for production. Manual checks will show the
            # updates dialog (or a simple "you're up to date" message).

            # update last_checked
            try:
                s = self._gui_settings or {}
                ups = s.setdefault('updates', {})
                ups['last_checked'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                self._gui_settings = s
                self._save_gui_settings()
            except Exception:
                pass

            # check ignore list
            try:
                s = self._gui_settings or {}
                ignore = set(s.get('updates', {}).get('ignore_versions', []) or [])
                if latest_ver in ignore:
                    return
            except Exception:
                pass

            if newer:
                # show dialog on main thread
                try:
                    # pass asset_url separately so dialog can decide whether a direct
                    # download is available. If not, Download will open the releases page.
                    self.after(0, lambda: self._show_update_dialog(current, latest_ver, changelog, asset_url, html_url, asset_name))
                except Exception:
                    pass
            else:
                if manual:
                    try:
                        messagebox.showinfo('Updates', f'You are running the latest version ({current}).')
                    except Exception:
                        pass
        except Exception:
            if manual:
                try:
                    messagebox.showinfo('Updates', 'Failed to check for updates.')
                except Exception:
                    pass

    def _show_update_dialog(self, current, latest, changelog, asset_url, releases_page, asset_name=None):
        try:
            w = tk.Toplevel(self)
            try:
                self._set_window_icon(w)
            except Exception:
                pass
            # Make dialog transient/modal above the main window
            try:
                w.transient(self)
                w.grab_set()
                w.lift()
                w.focus_force()
                # briefly force topmost so it appears above other windows
                try:
                    w.attributes('-topmost', True)
                    self.after(100, lambda: w.attributes('-topmost', False))
                except Exception:
                    pass
            except Exception:
                pass
            w.title('Updates')
            w.geometry('600x400')
            ttk.Label(w, text=f'Current version: {current}').pack(anchor='w', padx=10, pady=4)
            ttk.Label(w, text=f'Latest version: {latest}').pack(anchor='w', padx=10, pady=4)
            txt = tk.Text(w, height=12, wrap='word')
            txt.pack(fill='both', expand=True, padx=10, pady=4)
            try:
                txt.insert('1.0', changelog or '(no changelog provided)')
            except Exception:
                pass
            txt.config(state='disabled')

            btn_frame = ttk.Frame(w)
            btn_frame.pack(fill='x', padx=10, pady=6)

            def _open_releases():
                try:
                    webbrowser.open(releases_page)
                except Exception:
                    pass

            def _download_and_run_cb():
                # If an actual asset URL is provided, download it; otherwise open releases page
                if asset_url:
                    try:
                        # if the update dialog is modal (grab_set), release it so the
                        # download dialog can accept events.
                        try:
                            w.grab_release()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    self._download_and_run(asset_url, asset_name)
                else:
                    try:
                        webbrowser.open(releases_page)
                    except Exception:
                        pass

            def _ignore_cb():
                try:
                    s = self._gui_settings or {}
                    ups = s.setdefault('updates', {})
                    lst = ups.setdefault('ignore_versions', [])
                    if latest not in lst:
                        lst.append(latest)
                    self._gui_settings = s
                    self._save_gui_settings()
                except Exception:
                    pass
                try:
                    w.destroy()
                except Exception:
                    pass

            # If no direct installer asset is available, label button accordingly
            download_label = 'Download' if asset_url else 'Open Releases Page'
            ttk.Button(btn_frame, text=download_label, command=_download_and_run_cb).pack(side='left')
            if asset_url:
                ttk.Button(btn_frame, text='Open Releases Page', command=_open_releases).pack(side='left', padx=6)
            ttk.Button(btn_frame, text='Ignore this version', command=_ignore_cb).pack(side='right')
            ttk.Button(btn_frame, text='Remind Me Later', command=lambda: w.destroy()).pack(side='right', padx=6)
        except Exception:
            pass

    def _download_and_run(self, url, suggested_name=None):
        # Show a progress dialog and perform the download in a background thread
        try:
            if not url:
                try:
                    messagebox.showerror('Download', 'No downloadable asset available for this release.')
                except Exception:
                    pass
                return

            confirm = messagebox.askyesno('Download', f'Download installer from {url}?')
            if not confirm:
                return

            # Prepare progress dialog
            dlg = tk.Toplevel(self)
            try:
                self._set_window_icon(dlg)
            except Exception:
                pass
            try:
                dlg.transient(self)
                dlg.grab_set()
            except Exception:
                pass
            dlg.title('Downloading')
            dlg.geometry('500x140')
            ttk.Label(dlg, text='Downloading installer...').pack(anchor='w', padx=10, pady=(10, 2))
            progress_var = tk.DoubleVar(value=0.0)
            pb = ttk.Progressbar(dlg, variable=progress_var, maximum=100.0)
            pb.pack(fill='x', padx=10, pady=6)
            status_lbl = ttk.Label(dlg, text='Starting...')
            status_lbl.pack(anchor='w', padx=10)

            btn_frame = ttk.Frame(dlg)
            btn_frame.pack(fill='x', padx=10, pady=8)
            run_btn = ttk.Button(btn_frame, text='Run Installer', state='disabled')
            run_btn.pack(side='right')
            cancel_btn = ttk.Button(btn_frame, text='Cancel')
            cancel_btn.pack(side='right', padx=6)

            cancel_event = threading.Event()

            def on_cancel():
                cancel_event.set()
                try:
                    status_lbl.config(text='Cancelling...')
                except Exception:
                    pass

            cancel_btn.config(command=on_cancel)

            # determine extension to preserve
            try:
                if suggested_name:
                    ext = os.path.splitext(suggested_name)[1] or ''
                else:
                    ext = os.path.splitext(urlparse(url).path)[1] or ''
            except Exception:
                ext = os.path.splitext(url)[1] if isinstance(url, str) else ''

            def _dl_thread():
                fd = None
                tmp_path = None
                try:
                    # Helper functions to safely update UI widgets from background thread
                    def _safe_set_status(text):
                        try:
                            if status_lbl and status_lbl.winfo_exists():
                                status_lbl.config(text=text)
                        except Exception:
                            pass

                    def _safe_set_pb_mode(mode):
                        try:
                            if pb and pb.winfo_exists():
                                pb.config(mode=mode)
                        except Exception:
                            pass

                    def _safe_start_pb():
                        try:
                            if pb and pb.winfo_exists():
                                pb.start(10)
                        except Exception:
                            pass

                    def _safe_stop_pb():
                        try:
                            if pb and pb.winfo_exists():
                                pb.stop()
                        except Exception:
                            pass

                    def _safe_set_progress(val):
                        try:
                            if progress_var is not None:
                                progress_var.set(val)
                        except Exception:
                            pass

                    def _safe_enable_run(cmd):
                        try:
                            if run_btn and run_btn.winfo_exists():
                                run_btn.config(state='normal', command=cmd)
                        except Exception:
                            pass

                    with requests.get(url, stream=True, timeout=30) as r:
                        if r.status_code != 200:
                            self.after(0, lambda: messagebox.showerror('Download', f'Failed to download: HTTP {r.status_code}'))
                            try:
                                dlg.destroy()
                            except Exception:
                                pass
                            return

                        total = 0
                        try:
                            total = int(r.headers.get('Content-Length') or 0)
                        except Exception:
                            total = 0

                        # create temp file
                        fd, tmp_path = tempfile.mkstemp(suffix=ext)
                        downloaded = 0
                        # choose determinate or indeterminate
                        if total > 0:
                            # set maximum to total bytes and update in bytes
                            self.after(0, lambda: _safe_set_pb_mode('determinate'))
                        else:
                            self.after(0, lambda: (_safe_set_pb_mode('indeterminate'), _safe_start_pb()))

                        with os.fdopen(fd, 'wb') as outf:
                            for chunk in r.iter_content(8192):
                                if cancel_event.is_set():
                                    # abort
                                    try:
                                        outf.flush()
                                    except Exception:
                                        pass
                                    break
                                if chunk:
                                    outf.write(chunk)
                                    downloaded += len(chunk)
                                    if total > 0:
                                        percent = (downloaded / total) * 100.0
                                        self.after(0, lambda p=percent: _safe_set_progress(p))
                                        self.after(0, lambda d=downloaded: _safe_set_status(f'{d} / {total} bytes'))
                        # if indeterminate, stop the animation
                        if total <= 0:
                            try:
                                self.after(0, lambda: _safe_stop_pb())
                            except Exception:
                                pass

                        if cancel_event.is_set():
                            # remove partial file
                            try:
                                if tmp_path and os.path.exists(tmp_path):
                                    os.remove(tmp_path)
                            except Exception:
                                pass
                            try:
                                dlg.destroy()
                            except Exception:
                                pass
                            return

                        # finished successfully
                        try:
                            # Update UI on main thread
                            self.after(0, lambda: _safe_set_status(f'Download complete: {tmp_path}'))
                        except Exception:
                            pass

                        def _run_installer():
                            try:
                                if sys.platform.startswith('win'):
                                    os.startfile(tmp_path)
                                else:
                                    subprocess.Popen(['chmod', '+x', tmp_path])
                                    subprocess.Popen([tmp_path])
                            except Exception:
                                try:
                                    messagebox.showinfo('Run Installer', f'Installer saved to: {tmp_path}')
                                except Exception:
                                    pass

                        # enable run button
                        try:
                            self.after(0, lambda: _safe_enable_run(_run_installer))
                        except Exception:
                            pass

                except Exception:
                    try:
                        self.after(0, lambda: messagebox.showerror('Download', 'Download failed.'))
                    except Exception:
                        pass
                    try:
                        if fd:
                            os.close(fd)
                    except Exception:
                        pass
                finally:
                    pass

            th = threading.Thread(target=_dl_thread, daemon=True)
            th.start()

        except Exception:
            pass

    def _save_settings(self):
        # Deprecated: persistence removed. Use Save Settings (Save As) menu to
        # explicitly write settings to a JSON file. This helper now just
        # returns the settings dict so callers can decide where to write it.
        try:
            selected = self.serial_port_var.get().strip()
            device_name = selected
            try:
                if selected in self._serial_display_map:
                    device_name = self._serial_display_map[selected]
            except Exception:
                pass

            try:
                model_path = self.model_path_var.get().strip()
            except Exception:
                model_path = ''
            try:
                model_path = os.path.abspath(os.path.expanduser(model_path)) if model_path else ''
            except Exception:
                pass

            data = {"model_path": model_path, "cpu_threads": int(self.cpu_threads_var.get()),
                    "serial_enabled": bool(self.serial_enabled_var.get()),
                    "serial_port": device_name,
                    "baud": int(self.baud_var.get()),
                    "serial_word_delay_ms": int(getattr(self, 'serial_word_delay_ms', tk.IntVar(value=200)).get()),
                    "serial_highlight_color": str(getattr(self, 'serial_highlight_color', tk.StringVar(value='yellow')).get()),
                "profile_matching": bool(self.profile_matching_var.get()),
                "profile_threshold": float(self.profile_threshold_var.get()),
                "srt_caption_duration": float(getattr(self, 'srt_duration_var', tk.DoubleVar(value=2.0)).get() if getattr(self, 'srt_duration_var', None) is not None else 2.0),
                # bleep / replacement settings
                "bleep_mode": str(getattr(self, 'bleep_mode_var', tk.StringVar(value='fixed')).get() if getattr(self, 'bleep_mode_var', None) is not None else 'fixed'),
                "bleep_custom_text": str(getattr(self, 'bleep_custom_var', tk.StringVar(value='****')).get() if getattr(self, 'bleep_custom_var', None) is not None else '****'),
                "bleep_mask_char": str(getattr(self, 'bleep_mask_var', tk.StringVar(value='*')).get() if getattr(self, 'bleep_mask_var', None) is not None else '*')}
            # include custom vocab data (words -> pronunciation) so a single settings file
            # can capture the user's configured custom words for later restore
            try:
                if getattr(self, 'vocab_mgr', None):
                    # access underlying entries dict (safe for our manager)
                    try:
                        vocab_map = {str(k): str(v) for k, v in getattr(self.vocab_mgr, '_entries', {}).items()}
                        data['custom_vocab'] = vocab_map
                        data['custom_vocab_data_dir'] = getattr(self.vocab_mgr, 'data_dir', '')
                        # include per-word sample metadata (filename + base64 payload)
                        try:
                            samples = {}
                            for w in vocab_map.keys():
                                sfiles = []
                                try:
                                    for fn in self.vocab_mgr.list_samples(w):
                                        p = self.vocab_mgr.sample_path(w, fn)
                                        try:
                                            with open(p, 'rb') as sf:
                                                b = sf.read()
                                            sfiles.append({'filename': fn, 'data_b64': base64.b64encode(b).decode('ascii')})
                                        except Exception:
                                            # skip unreadable files
                                            pass
                                except Exception:
                                    pass
                                if sfiles:
                                    samples[w] = sfiles
                            if samples:
                                data['custom_vocab_samples'] = samples
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass
            # include bad words file path if loaded in this session
            try:
                data['bad_words'] = self._bad_words_path if getattr(self, '_bad_words_path', None) else ''
            except Exception:
                data['bad_words'] = ''
            # include punctuator path if set (optional)
            try:
                data['punctuator_path'] = self.punctuator_var.get().strip() if getattr(self, 'punctuator_var', None) is not None else ''
            except Exception:
                data['punctuator_path'] = ''
            # Keep paths absolute in saved settings. Finder-launched apps can
            # have a different working directory/environment, and relative
            # paths are a common source of "works in Terminal, fails in .app".
            try:
                def _norm_abs(p: str) -> str:
                    if not p:
                        return ''
                    try:
                        p = os.path.expanduser(p)
                    except Exception:
                        pass
                    try:
                        return os.path.abspath(p)
                    except Exception:
                        return p

                for k in ('model_path', 'punctuator_path', 'custom_vocab_data_dir', 'bad_words', 'auto_save_txt_path'):
                    if k in data:
                        data[k] = _norm_abs(data.get(k, ''))
            except Exception:
                pass
            
            # include automation data
            try:
                if getattr(self, 'automation_manager', None):
                    data['automations'] = self.automation_manager.to_dict()
            except Exception:
                pass
            
            # include auto-save settings
            try:
                data['auto_save_txt'] = bool(self.auto_save_txt_var.get()) if getattr(self, 'auto_save_txt_var', None) is not None else False
                data['auto_save_txt_path'] = self.auto_save_txt_path if getattr(self, 'auto_save_txt_path', None) else ''
            except Exception:
                pass
            
            return data
        except Exception:
            return {}

    def _on_save_clicked(self):
        try:
            data = self._save_settings()
            if not data:
                try:
                    messagebox.showwarning("Settings", "Nothing to save.")
                except Exception:
                    pass
                return

            # If a file was previously opened/saved this session, overwrite it
            if getattr(self, '_current_settings_file', None):
                try:
                    with open(self._current_settings_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)
                    try:
                        messagebox.showinfo("Settings", f"Settings saved to {self._current_settings_file}.")
                    except Exception:
                        pass
                    return
                except Exception as e:
                    try:
                        messagebox.showerror("Settings", f"Failed to save to current file: {e}")
                    except Exception:
                        pass
                    # fall through to Save As on failure

            # No current file -> prompt Save As
            path = filedialog.asksaveasfilename(title="Save Settings As", defaultextension='.json', filetypes=[('JSON files', '*.json'), ('All files', '*')])
            if not path:
                return
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
                self._current_settings_file = path
                try:
                    messagebox.showinfo("Settings", "Settings saved.")
                except Exception:
                    pass
            except Exception as e:
                try:
                    messagebox.showerror("Settings", f"Failed to save settings: {e}")
                except Exception:
                    pass
        except Exception:
            try:
                messagebox.showwarning("Settings", "Failed to save settings.")
            except Exception:
                pass

    def _on_open_settings(self):
        try:
            path = filedialog.askopenfilename(title="Load Settings", filetypes=[("JSON files", "*.json"), ("All files", "*")])
            if not path:
                return
            # load settings from chosen file (session only — no automatic persistence)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                try:
                    messagebox.showerror("Load Settings", f"Failed to read settings: {e}")
                except Exception:
                    pass
                return

            # apply settings to UI (do not write to disk automatically)
            try:
                # Resolve saved paths. Prefer:
                # 1) absolute path as-is
                # 2) relative to settings file directory
                # 3) relative to app_root/models_root
                settings_dir = os.path.abspath(os.path.dirname(path))

                def _resolve_path(p: str) -> str:
                    if not p:
                        return ''
                    try:
                        p = os.path.expanduser(p)
                    except Exception:
                        pass
                    try:
                        if os.path.isabs(p):
                            return os.path.abspath(p)
                    except Exception:
                        pass

                    candidates = []
                    try:
                        candidates.append(os.path.join(settings_dir, p))
                    except Exception:
                        pass
                    try:
                        candidates.append(os.path.join(self.app_root, p))
                    except Exception:
                        pass
                    try:
                        candidates.append(os.path.join(self.models_root, p))
                    except Exception:
                        pass
                    for c in candidates:
                        try:
                            if c and os.path.exists(c):
                                return os.path.abspath(c)
                        except Exception:
                            continue
                    # fallback: just absolutize against settings dir
                    try:
                        return os.path.abspath(os.path.join(settings_dir, p))
                    except Exception:
                        return p

                model = _resolve_path(data.get('model_path') or '')
                if model:
                    self.model_path_var.set(model)

                punc = _resolve_path(data.get('punctuator_path') or '')
                if punc and getattr(self, 'punctuator_var', None) is not None:
                    self.punctuator_var.set(punc)

                self.cpu_threads_var.set(int(data.get("cpu_threads", 0)))
                self.serial_enabled_var.set(bool(data.get("serial_enabled", False)))
                # profile matching settings (optional)
                try:
                    self.profile_matching_var.set(bool(data.get("profile_matching", True)))
                except Exception:
                    pass
                try:
                    self.profile_threshold_var.set(float(data.get("profile_threshold", 0.7)))
                except Exception:
                    pass
                sp = data.get("serial_port")
                if sp:
                    self._saved_serial_device = sp
                self.baud_var.set(int(data.get("baud", 9600)))
                # serial word delay (ms) if present
                try:
                    ms = data.get('serial_word_delay_ms')
                    if ms is not None:
                        try:
                            if getattr(self, 'serial_word_delay_ms', None) is None:
                                self.serial_word_delay_ms = tk.IntVar()
                            self.serial_word_delay_ms.set(int(ms))
                        except Exception:
                            try:
                                self.serial_word_delay_ms = tk.IntVar(value=int(ms))
                            except Exception:
                                pass
                except Exception:
                    pass
                    # serial highlight color if present
                    try:
                        col = data.get('serial_highlight_color')
                        if col is not None:
                            try:
                                if getattr(self, 'serial_highlight_color', None) is None:
                                    self.serial_highlight_color = tk.StringVar()
                                self.serial_highlight_color.set(str(col))
                            except Exception:
                                try:
                                    self.serial_highlight_color = tk.StringVar(value=str(col))
                                except Exception:
                                    pass
                    except Exception:
                        pass
                # restore SRT duration if present
                try:
                    if getattr(self, 'srt_duration_var', None) is None:
                        self.srt_duration_var = tk.DoubleVar()
                    self.srt_duration_var.set(float(data.get('srt_caption_duration', 2.0)))
                except Exception:
                    try:
                        self.srt_duration_var.set(2.0)
                    except Exception:
                        pass
                # restore bleep/replacement settings if present
                try:
                    bm = data.get('bleep_mode')
                    btext = data.get('bleep_custom_text')
                    bmask = data.get('bleep_mask_char')
                    if bm is not None:
                        try:
                            if getattr(self, 'bleep_mode_var', None) is None:
                                self.bleep_mode_var = tk.StringVar()
                            self.bleep_mode_var.set(str(bm))
                        except Exception:
                            pass
                    if btext is not None:
                        try:
                            if getattr(self, 'bleep_custom_var', None) is None:
                                self.bleep_custom_var = tk.StringVar()
                            self.bleep_custom_var.set(str(btext))
                        except Exception:
                            pass
                    if bmask is not None:
                        try:
                            if getattr(self, 'bleep_mask_var', None) is None:
                                self.bleep_mask_var = tk.StringVar()
                            self.bleep_mask_var.set(str(bmask))
                        except Exception:
                            pass
                    # apply to main module so live engine uses updated settings
                    try:
                        mainmod.BLEEP_SETTINGS = {
                            'mode': str(getattr(self, 'bleep_mode_var', tk.StringVar(value='fixed')).get()),
                            'custom_text': str(getattr(self, 'bleep_custom_var', tk.StringVar(value='****')).get()),
                            'mask_char': str(getattr(self, 'bleep_mask_var', tk.StringVar(value='*')).get())[:1] or '*'
                        }
                    except Exception:
                        pass
                except Exception:
                    pass
                # If the settings file contains a bad_words path, attempt to load
                # it now so the UI reflects the loaded state. This preserves the
                # user's expectation when they open a saved settings file.
                bw_path = data.get("bad_words") or ''
                if bw_path:
                    try:
                        # resolve saved path (may be absolute or relative)
                        try:
                            bw_path = _resolve_path(bw_path)
                        except Exception:
                            pass
                        loaded = mainmod.load_bad_words(bw_path)
                        mainmod.BAD_WORDS = loaded
                        self._bad_words_path = bw_path
                        try:
                            if getattr(self, '_bad_words_loaded_var', None) is not None:
                                self._bad_words_loaded_var.set(True)
                        except Exception:
                            pass
                    except Exception as e:
                        try:
                            messagebox.showwarning("Bad Words", f"Failed to load bad words from settings: {e}")
                        except Exception:
                            pass
                        self._bad_words_path = None
                        try:
                            if getattr(self, '_bad_words_loaded_var', None) is not None:
                                self._bad_words_loaded_var.set(False)
                        except Exception:
                            pass
                else:
                    # ensure no stale state
                    self._bad_words_path = None
                    try:
                        if getattr(self, '_bad_words_loaded_var', None) is not None:
                            self._bad_words_loaded_var.set(False)
                    except Exception:
                        pass
                self._current_settings_file = path
                # update dependent UI pieces
                try:
                    self._update_model_status()
                except Exception:
                    pass
                try:
                    self._update_thread_status()
                except Exception:
                    pass
                # repopulate serial ports so saved device selection can be applied
                try:
                    self._populate_serial_ports()
                except Exception:
                    pass
                try:
                    messagebox.showinfo("Settings", "Settings loaded (session only). Use Save Settings to write to a file.")
                except Exception:
                    pass
                # If the settings file contained custom vocab, restore it into the manager
                try:
                    cv = data.get('custom_vocab')
                    if cv is not None:
                        from custom_vocab import CustomVocabManager
                        if not getattr(self, 'vocab_mgr', None):
                            self.vocab_mgr = CustomVocabManager()
                        try:
                            # replace entries in-memory; do not force-write to disk unless user saves
                            self.vocab_mgr._entries = {str(k): str(v) for k, v in cv.items()}
                            # if settings stored a custom data dir, restore it (best-effort)
                            dd = data.get('custom_vocab_data_dir')
                            if dd:
                                try:
                                    # resolve saved path (may be absolute or relative)
                                    try:
                                        dd = _resolve_path(dd)
                                    except Exception:
                                        pass
                                    self.vocab_mgr.data_dir = str(dd)
                                    os.makedirs(self.vocab_mgr.data_dir, exist_ok=True)
                                except Exception:
                                    pass
                                # refresh the UI list
                                try:
                                    self._refresh_vocab_list()
                                except Exception:
                                    pass
                            # If settings included embedded samples, restore them into the data_dir
                            try:
                                samples_map = data.get('custom_vocab_samples')
                                if samples_map and getattr(self, 'vocab_mgr', None):
                                    for w, items in samples_map.items():
                                        try:
                                            wd = self.vocab_mgr._word_dir(w)
                                        except Exception:
                                            wd = None
                                        if not wd:
                                            continue
                                        for item in items:
                                            fn = item.get('filename')
                                            b64 = item.get('data_b64')
                                            if not fn or not b64:
                                                continue
                                            try:
                                                data_bytes = base64.b64decode(b64)
                                            except Exception:
                                                continue
                                            dest_path = os.path.join(wd, fn)
                                            # avoid overwriting existing file by adding suffix
                                            if os.path.exists(dest_path):
                                                name, ext = os.path.splitext(fn)
                                                i = 1
                                                while True:
                                                    cand = os.path.join(wd, f"{name}_{i}{ext}")
                                                    if not os.path.exists(cand):
                                                        dest_path = cand
                                                        break
                                                    i += 1
                                            try:
                                                with open(dest_path, 'wb') as outf:
                                                    outf.write(data_bytes)
                                            except Exception:
                                                pass
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    pass
                
                # If the settings file contained automations, restore them
                try:
                    automations_data = data.get('automations')
                    if automations_data and getattr(self, 'automation_manager', None):
                        self.automation_manager = AutomationManager.from_dict(automations_data)
                        self.automation_manager.set_callbacks(
                            on_start=self._on_automation_start,
                            on_stop=self._on_automation_stop
                        )
                        # Refresh the automations tab UI to show loaded automations
                        try:
                            self._refresh_automations_display()
                        except Exception:
                            pass
                except Exception:
                    pass
                
                # Restore auto-save settings if present
                try:
                    auto_save_enabled = data.get('auto_save_txt', False)
                    if getattr(self, 'auto_save_txt_var', None) is not None:
                        self.auto_save_txt_var.set(bool(auto_save_enabled))
                    auto_save_path = data.get('auto_save_txt_path', '')
                    if auto_save_path:
                        try:
                            auto_save_path = _resolve_path(auto_save_path)
                        except Exception:
                            pass
                        self.auto_save_txt_path = auto_save_path
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            try:
                messagebox.showwarning("Settings", "Failed to open settings file.")
            except Exception:
                pass

    def _on_save_as(self):
        try:
            data = self._save_settings()
            if not data:
                try:
                    messagebox.showwarning("Settings", "Nothing to save.")
                except Exception:
                    pass
                return
            path = filedialog.asksaveasfilename(title="Save Settings As", defaultextension='.json', filetypes=[('JSON files', '*.json'), ('All files', '*')])
            if not path:
                return
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
                self._current_settings_file = path
                try:
                    messagebox.showinfo("Settings", "Settings saved.")
                except Exception:
                    pass
                # Also write a copy to the local gui_settings.json so the GUI
                # can be launched with a default settings file present.
                try:
                    here = os.path.dirname(__file__)
                    local_path = os.path.join(here, 'gui_settings.json')
                    with open(local_path, 'w', encoding='utf-8') as lf:
                        json.dump(data, lf, indent=2)
                except Exception:
                    pass
            except Exception as e:
                try:
                    messagebox.showerror("Settings", f"Failed to save settings: {e}")
                except Exception:
                    pass
        except Exception:
            try:
                messagebox.showwarning("Settings", "Failed to save settings.")
            except Exception:
                pass

    def _on_load_bad_words(self):
        # If a file is already loaded, ask whether to unload, replace, or cancel.
        prev = False
        try:
            prev = bool(getattr(self, '_bad_words_loaded_var').get())
        except Exception:
            prev = False

        try:
            # Only consider 'loaded' if we have a recorded file path. If the
            # path is None/empty, skip the unload/replace prompt and go
            # straight to the file selection dialog.
            loaded = bool(getattr(self, '_bad_words_path', None))
        except Exception:
            loaded = False

        if loaded:
            # Ask user: Unload=Unload, Replace=Choose different file, Cancel=Do nothing
            # Use a custom dialog so we can show the desired button labels.
            try:
                res = self._ask_unload_replace(self._bad_words_path)
            except Exception:
                # fallback to standard dialog if custom fails
                try:
                    res = messagebox.askyesnocancel(
                        "Restricted Words",
                        f"A restricted words file is currently loaded:\n{self._bad_words_path}\n\nChoose 'Yes' to unload it, 'No' to select a different file, or 'Cancel' to keep the current file."
                    )
                except Exception:
                    res = None

            if res is True:
                # Unload
                try:
                    mainmod.BAD_WORDS = set()
                except Exception:
                    try:
                        mainmod.BAD_WORDS = set()
                    except Exception:
                        pass
                self._bad_words_path = None
                try:
                    if getattr(self, '_bad_words_loaded_var', None) is not None:
                        self._bad_words_loaded_var.set(False)
                except Exception:
                    pass
                try:
                    messagebox.showinfo("Bad Words", "Restricted words file unloaded for this session.")
                except Exception:
                    pass
                return
            if res is None:
                # Cancel: restore previous state
                try:
                    if getattr(self, '_bad_words_loaded_var', None) is not None:
                        self._bad_words_loaded_var.set(prev)
                except Exception:
                    pass
                return
            # else: res is False -> user wants to select a different file; fall through to open dialog

        # User chose to load/replace file (or none was loaded before)
        try:
            path = filedialog.askopenfilename(title="Select bad words file", filetypes=[("Text files", "*.txt"), ("All files", "*")])
            if not path:
                # user cancelled: restore previous check state
                try:
                    if getattr(self, '_bad_words_loaded_var', None) is not None:
                        self._bad_words_loaded_var.set(prev)
                except Exception:
                    pass
                return

            # Load bad words for this session only (do not persist automatically)
            try:
                mainmod.BAD_WORDS = mainmod.load_bad_words(path)
                self._bad_words_path = path
                try:
                    messagebox.showinfo("Bad Words", "Bad words file loaded for this session.")
                except Exception:
                    pass
                try:
                    if getattr(self, '_bad_words_loaded_var', None) is not None:
                        self._bad_words_loaded_var.set(True)
                except Exception:
                    pass
            except Exception as e:
                # loading failed: inform user and restore check state
                try:
                    messagebox.showerror("Bad Words", f"Failed to load bad words file: {e}")
                except Exception:
                    pass
                try:
                    if getattr(self, '_bad_words_loaded_var', None) is not None:
                        self._bad_words_loaded_var.set(prev)
                except Exception:
                    pass
        except Exception:
            try:
                messagebox.showwarning("Bad Words", "Failed to load bad words file.")
            except Exception:
                pass
            try:
                if getattr(self, '_bad_words_loaded_var', None) is not None:
                    self._bad_words_loaded_var.set(prev)
            except Exception:
                pass

    def _open_options_dialog(self):
        """Open a modal Options dialog for configurable settings like SRT duration."""
        dlg = tk.Toplevel(self)
        try:
            dlg.transient(self)
        except Exception:
            pass
        # set dialog icon to bundled icon.ico if available
        try:
            try:
                dlg_icon = resources._resource_path('icon.ico')
            except Exception:
                dlg_icon = 'icon.ico'
            if dlg_icon and os.path.exists(dlg_icon):
                try:
                    dlg.iconbitmap(dlg_icon)
                except Exception:
                    try:
                        img = tk.PhotoImage(file=dlg_icon)
                        dlg.iconphoto(False, img)
                        dlg._icon_image = img
                    except Exception:
                        pass
        except Exception:
            pass
        dlg.title("Options")
        try:
            dlg.grab_set()
        except Exception:
            pass

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        # SRT duration control
        ttk.Label(frm, text="SRT caption duration (seconds):").pack(anchor=tk.W)
        tmp_var = tk.DoubleVar(value=float(getattr(self, 'srt_duration_var', tk.DoubleVar(value=2.0)).get()))
        try:
            spin = ttk.Spinbox(frm, from_=0.1, to=60.0, increment=0.1, textvariable=tmp_var, width=8)
            spin.pack(anchor=tk.W, pady=(4,6))
        except Exception:
            ent = ttk.Entry(frm, textvariable=tmp_var, width=8)
            ent.pack(anchor=tk.W, pady=(4,6))

        # Serial send speed (ms between words)
        try:
            ttk.Label(frm, text="Serial send delay (ms):").pack(anchor=tk.W)
            tmp_serial_delay = tk.IntVar(value=int(getattr(self, 'serial_word_delay_ms', tk.IntVar(value=200)).get()))
            try:
                sd_spin = ttk.Spinbox(frm, from_=0, to=5000, increment=50, textvariable=tmp_serial_delay, width=8)
                sd_spin.pack(anchor=tk.W, pady=(4,6))
            except Exception:
                sd_ent = ttk.Entry(frm, textvariable=tmp_serial_delay, width=8)
                sd_ent.pack(anchor=tk.W, pady=(4,6))
        except Exception:
            tmp_serial_delay = None

        # Highlight color chooser (small swatches)
        try:
            ttk.Label(frm, text="Highlight color:").pack(anchor=tk.W)
            sw_frm = ttk.Frame(frm)
            sw_frm.pack(anchor=tk.W, pady=(4,6))
            tmp_serial_color = tk.StringVar(value=str(getattr(self, 'serial_highlight_color', tk.StringVar(value='yellow')).get()))
            sw_buttons = {}

            def _select_color(name):
                try:
                    tmp_serial_color.set(name)
                except Exception:
                    pass
                try:
                    # update visuals
                    for n, b in sw_buttons.items():
                        try:
                            if n == tmp_serial_color.get():
                                b.config(relief='sunken', bd=3)
                            else:
                                b.config(relief='raised', bd=1)
                        except Exception:
                            pass
                except Exception:
                    pass

            # create swatches in the requested order
            color_order = ['gray','dark red','red','orange','yellow','green','light blue','blue','indigo','purple']
            for name in color_order:
                try:
                    bg, fg = self._serial_highlight_color_map.get(name, (name, 'black'))
                    # Use a Label (frame-like) as a colored swatch; on macOS native buttons
                    # often ignore background colors. Labels reliably show background color
                    # across platforms and can be clicked.
                    b = tk.Label(sw_frm, bg=bg, width=4, height=2, bd=1, relief='raised', cursor='hand2')
                    def _on_click(event, n=name):
                        _select_color(n)
                    try:
                        b.bind('<Button-1>', _on_click)
                    except Exception:
                        pass
                    b.pack(side=tk.LEFT, padx=(2,2))
                    sw_buttons[name] = b
                except Exception:
                    pass

            # initialize visuals
            try:
                _select_color(tmp_serial_color.get())
            except Exception:
                pass
        except Exception:
            tmp_serial_color = None

        btn_frm = ttk.Frame(frm)
        # place the buttons at the bottom-right corner of the dialog
        btn_frm.pack(side=tk.BOTTOM, anchor=tk.E, fill=tk.X, pady=(8,0))

        # --- Bleep / replacement settings ---
        ttk.Separator(frm, orient='horizontal').pack(fill=tk.X, pady=(8,8))
        ttk.Label(frm, text="Restricted-word replacement:").pack(anchor=tk.W)

        modes = [
            ("Fixed text", 'fixed'),
            ("Keep first letter", 'keep_first'),
            ("Keep last letter", 'keep_last'),
            ("Keep first & last", 'keep_first_last'),
            ("Remove word", 'remove'),
        ]
        # radio buttons
        rb_frm = ttk.Frame(frm)
        rb_frm.pack(anchor=tk.W, pady=(4,4))
        for lbl, val in modes:
            try:
                ttk.Radiobutton(rb_frm, text=lbl, variable=self.bleep_mode_var, value=val).pack(side=tk.LEFT, padx=(0,6))
            except Exception:
                pass

        # Custom text entry (used for 'fixed') and mask char entry (used for keep_* modes)
        cf = ttk.Frame(frm)
        cf.pack(fill=tk.X, pady=(4,4))
        ttk.Label(cf, text="Fixed / Custom text:").pack(side=tk.LEFT)
        try:
            ttk.Entry(cf, textvariable=self.bleep_custom_var, width=20).pack(side=tk.LEFT, padx=(6,10))
        except Exception:
            pass
        ttk.Label(cf, text="Mask char:").pack(side=tk.LEFT)
        try:
            ttk.Entry(cf, textvariable=self.bleep_mask_var, width=3).pack(side=tk.LEFT, padx=(6,0))
        except Exception:
            pass

        # Preview area: show how a sample bad phrase would be transformed
        try:
            preview_lbl = ttk.Label(frm, text="Preview:")
            preview_lbl.pack(anchor=tk.W, pady=(6,0))
            preview_var = tk.StringVar(value="")
            preview_value_lbl = ttk.Label(frm, textvariable=preview_var, foreground='blue')
            preview_value_lbl.pack(anchor=tk.W, pady=(2,6))
        except Exception:
            preview_var = None

        def _update_preview(*a):
            try:
                # Build a small sample and run through mainmod.bleep_text
                samples = 'badword mother-in-law'
                badset = {'badword', 'mother-in-law'}
                # apply temporary settings matching UI without mutating global unless needed
                try:
                    tmp_mode = str(self.bleep_mode_var.get())
                except Exception:
                    tmp_mode = 'fixed'
                try:
                    tmp_custom = str(self.bleep_custom_var.get())
                except Exception:
                    tmp_custom = '****'
                try:
                    tmp_mask = str(self.bleep_mask_var.get())[:1] or '*'
                except Exception:
                    tmp_mask = '*'
                # temporarily set mainmod.BLEEP_SETTINGS for preview
                old = getattr(mainmod, 'BLEEP_SETTINGS', {}).copy() if getattr(mainmod, 'BLEEP_SETTINGS', None) is not None else {}
                try:
                    mainmod.BLEEP_SETTINGS = {'mode': tmp_mode, 'custom_text': tmp_custom, 'mask_char': tmp_mask}
                    out = mainmod.bleep_text(samples, bad_set=badset)
                except Exception:
                    out = samples
                finally:
                    try:
                        mainmod.BLEEP_SETTINGS = old
                    except Exception:
                        pass
                if preview_var is not None:
                    preview_var.set(out)
            except Exception:
                try:
                    if preview_var is not None:
                        preview_var.set('')
                except Exception:
                    pass

        # Update preview when UI values change
        try:
            if getattr(self, 'bleep_mode_var', None) is not None:
                try:
                    self.bleep_mode_var.trace_add('write', _update_preview)
                except Exception:
                    try:
                        self.bleep_mode_var.trace('w', _update_preview)
                    except Exception:
                        pass
            if getattr(self, 'bleep_custom_var', None) is not None:
                try:
                    self.bleep_custom_var.trace_add('write', _update_preview)
                except Exception:
                    try:
                        self.bleep_custom_var.trace('w', _update_preview)
                    except Exception:
                        pass
            if getattr(self, 'bleep_mask_var', None) is not None:
                try:
                    self.bleep_mask_var.trace_add('write', _update_preview)
                except Exception:
                    try:
                        self.bleep_mask_var.trace('w', _update_preview)
                    except Exception:
                        pass
        except Exception:
            pass
        # Populate preview immediately so it is visible when the dialog opens
        try:
            _update_preview()
        except Exception:
            pass

        # Auto-save settings section
        separator = ttk.Separator(frm, orient='horizontal')
        separator.pack(fill=tk.X, pady=(12, 6))

        # Update check preference
        try:
            upd_chk_frm = ttk.Frame(frm)
            upd_chk_frm.pack(fill=tk.X, pady=(4, 6))
            try:
                ttk.Checkbutton(upd_chk_frm, text="Automatically check for updates",
                               variable=getattr(self, 'auto_check_updates_var', tk.BooleanVar())).pack(anchor=tk.W)
            except Exception:
                pass
        except Exception:
            pass

        auto_save_lbl = ttk.Label(frm, text="Auto-Save Transcript Settings", font=('', 10, 'bold'))
        auto_save_lbl.pack(anchor=tk.W, pady=(4, 6))

        # Auto-save checkbox
        auto_save_chk_frm = ttk.Frame(frm)
        auto_save_chk_frm.pack(fill=tk.X, pady=(2, 4))
        try:
            ttk.Checkbutton(auto_save_chk_frm, text="Auto-save transcript when show completes", 
                           variable=self.auto_save_txt_var).pack(anchor=tk.W)
        except Exception:
            pass

        # Save location frame
        save_loc_frm = ttk.Frame(frm)
        save_loc_frm.pack(fill=tk.X, pady=(4, 4))
        ttk.Label(save_loc_frm, text="Save location:").pack(anchor=tk.W)

        path_frm = ttk.Frame(frm)
        path_frm.pack(fill=tk.X, pady=(2, 4))
        path_var = tk.StringVar(value=self.auto_save_txt_path)
        try:
            ttk.Entry(path_frm, textvariable=path_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        except Exception:
            pass

        def _browse_save_location():
            try:
                from tkinter import filedialog
                folder = filedialog.askdirectory(title="Select auto-save location", initialdir=self.auto_save_txt_path)
                if folder:
                    path_var.set(folder)
                    self.auto_save_txt_path = folder
            except Exception:
                pass

        try:
            ttk.Button(path_frm, text="Browse", command=_browse_save_location).pack(side=tk.LEFT)
        except Exception:
            pass

        def on_cancel():
            try:
                dlg.destroy()
            except Exception:
                pass

        def on_ok():
            try:
                val = float(tmp_var.get())
            except Exception:
                val = 2.0
            try:
                if getattr(self, 'srt_duration_var', None) is None:
                    self.srt_duration_var = tk.DoubleVar()
                self.srt_duration_var.set(max(0.1, val))
            except Exception:
                pass
            # apply bleep settings to the main module so running engine honors them
            try:
                mode = str(getattr(self, 'bleep_mode_var', tk.StringVar(value='fixed')).get() if getattr(self, 'bleep_mode_var', None) is not None else 'fixed')
            except Exception:
                mode = 'fixed'
            try:
                custom_text = str(getattr(self, 'bleep_custom_var', tk.StringVar(value='****')).get() if getattr(self, 'bleep_custom_var', None) is not None else '****')
            except Exception:
                custom_text = '****'
            try:
                mask_char = str(getattr(self, 'bleep_mask_var', tk.StringVar(value='*')).get() if getattr(self, 'bleep_mask_var', None) is not None else '*')[:1] or '*'
            except Exception:
                mask_char = '*'
            try:
                mainmod.BLEEP_SETTINGS = {'mode': mode, 'custom_text': custom_text, 'mask_char': mask_char}
            except Exception:
                pass
            # Save auto-save settings
            try:
                self.auto_save_txt_var.set(path_var.get() != '')  # checkbox tied to whether path is set
                self.auto_save_txt_path = path_var.get()
            except Exception:
                pass
            # Persist update-check preference
            try:
                try:
                    # call the handler which saves the var into gui settings
                    self._on_toggle_auto_check_updates()
                except Exception:
                    pass
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass
            # persist serial word delay into GUI settings
            try:
                if tmp_serial_delay is not None:
                    try:
                        ms = int(tmp_serial_delay.get())
                    except Exception:
                        ms = int(getattr(self, 'serial_word_delay_ms', tk.IntVar(value=200)).get())
                    try:
                        # update runtime var
                        self.serial_word_delay_ms.set(max(0, ms))
                    except Exception:
                        try:
                            self.serial_word_delay_ms = tk.IntVar(value=max(0, ms))
                        except Exception:
                            pass
                    # persist into gui settings
                    try:
                        s = self._gui_settings or {}
                        s['serial_word_delay_ms'] = int(ms)
                        self._gui_settings = s
                        self._save_gui_settings()
                    except Exception:
                        pass
            except Exception:
                pass
            # persist serial highlight color
            try:
                if tmp_serial_color is not None:
                    try:
                        sel = str(tmp_serial_color.get())
                    except Exception:
                        sel = str(getattr(self, 'serial_highlight_color', tk.StringVar(value='yellow')).get())
                    try:
                        if getattr(self, 'serial_highlight_color', None) is None:
                            self.serial_highlight_color = tk.StringVar()
                        self.serial_highlight_color.set(sel)
                    except Exception:
                        try:
                            self.serial_highlight_color = tk.StringVar(value=sel)
                        except Exception:
                            pass
                    try:
                        s = self._gui_settings or {}
                        s['serial_highlight_color'] = sel
                        self._gui_settings = s
                        self._save_gui_settings()
                    except Exception:
                        pass
            except Exception:
                pass

        # OK on the far right, Cancel to its left
        ttk.Button(btn_frm, text="OK", command=on_ok).pack(side=tk.RIGHT)
        ttk.Button(btn_frm, text="Cancel", command=on_cancel).pack(side=tk.RIGHT, padx=(6,0))

        # center dialog
        try:
            self.update_idletasks()
            dlg.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 2
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass

        try:
            self.wait_window(dlg)
        except Exception:
            pass

    def _open_activate(self):
        """Open the activation dialog (placeholder UI)."""
        try:
            # import lazily to keep startup lightweight
            import activate as activate_mod
            try:
                activate_mod.show_activate_dialog(self)
            except Exception as e:
                try:
                    messagebox.showerror("Activate", f"Activation dialog failed: {e}")
                except Exception:
                    pass
        except Exception as e:
            try:
                messagebox.showerror("Activate", f"Failed to open activation module: {e}")
            except Exception:
                pass
    # Vosk model manager dialog (languages -> models with sizes)
    def _open_vosk_model_manager(self):
        dlg = tk.Toplevel(self)
        try:
            dlg.transient(self)
        except Exception:
            pass
        # set dialog icon to bundled icon.ico if available
        try:
            try:
                dlg_icon = resources._resource_path('icon.ico')
            except Exception:
                dlg_icon = 'icon.ico'
            if dlg_icon and os.path.exists(dlg_icon):
                try:
                    dlg.iconbitmap(dlg_icon)
                except Exception:
                    try:
                        img = tk.PhotoImage(file=dlg_icon)
                        dlg.iconphoto(False, img)
                        dlg._icon_image = img
                    except Exception:
                        pass
        except Exception:
            pass
        dlg.title("Vosk Model Manager")
        try:
            dlg.grab_set()
        except Exception:
            pass

        frm = ttk.Frame(dlg, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Available Vosk Models:").pack(anchor=tk.W)
        # search / filter
        search_var = tk.StringVar()
        search_entry = ttk.Entry(frm, textvariable=search_var)
        search_entry.pack(fill=tk.X, pady=(4,4))

        split = ttk.Frame(frm)
        split.pack(fill=tk.BOTH, expand=True)

        # Left: languages list
        left = ttk.Frame(split, width=200)
        left.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left, text="Languages:").pack(anchor=tk.W)
        lang_listbox = tk.Listbox(left, exportselection=False, height=12)
        lang_listbox.pack(fill=tk.BOTH, expand=True, pady=(4,4))

        # Right: models for selected language (tree with columns)
        right = ttk.Frame(split)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8,0))
        ttk.Label(right, text="Models:").pack(anchor=tk.W)
        cols = ('installed', 'model', 'size')
        models_tree = ttk.Treeview(right, columns=cols, show='headings', height=12)
        models_tree.heading('installed', text='')
        models_tree.heading('model', text='Model')
        models_tree.heading('size', text='Size')
        models_tree.column('installed', anchor=tk.CENTER, width=30)
        models_tree.column('model', anchor=tk.W, width=350)
        models_tree.column('size', anchor=tk.CENTER, width=80)
        models_tree.pack(fill=tk.BOTH, expand=True, pady=(4,4))

        status_var = tk.StringVar(value="Click Refresh to load models from https://alphacephei.com/vosk/models")
        ttk.Label(frm, textvariable=status_var, wraplength=500).pack(anchor=tk.W, pady=(6,4))
        # Show where models will be installed (helpful for packaged builds)
        try:
            self._models_root_var = tk.StringVar(value=self.models_root)
            ttk.Label(frm, text="Install path:", foreground='gray').pack(anchor=tk.W)
            ttk.Label(frm, textvariable=self._models_root_var, wraplength=500).pack(anchor=tk.W, pady=(0,6))
        except Exception:
            pass

        progress = ttk.Progressbar(frm, orient='horizontal', length=400, mode='determinate')
        progress.pack(fill=tk.X, pady=(4,4))

        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill=tk.X, pady=(6,0))

        # cache: mapping language -> list of model dicts
        models_by_lang = {}

        def _clear_models_view():
            lang_listbox.delete(0, tk.END)
            for i in models_tree.get_children():
                models_tree.delete(i)

        def _populate_languages(langs):
            lang_listbox.delete(0, tk.END)
            for L in langs:
                lang_listbox.insert(tk.END, L)

        def _get_installed_dirs():
            try:
                return [d for d in os.listdir(self.models_root) if os.path.isdir(os.path.join(self.models_root, d))]
            except Exception:
                return []

        def _find_installed_model_dir(disp_name: str):
            if not disp_name:
                return None
            dn = disp_name.lower().strip()
            for inst in _get_installed_dirs():
                try:
                    if inst.lower().strip() == dn:
                        return os.path.join(self.models_root, inst)
                except Exception:
                    continue
            return None

        def _populate_models_for(lang, filter_q=None):
            for i in models_tree.get_children():
                models_tree.delete(i)
            if lang not in models_by_lang:
                return
            items = models_by_lang.get(lang, [])
            if filter_q:
                fq = filter_q.lower()
                items = [it for it in items if fq in (it.get('name') or '').lower() or fq in (it.get('url') or '').lower()]
            # Determine installed models in models_root (via helper)
            def is_installed(disp_name: str) -> bool:
                return _find_installed_model_dir(disp_name) is not None

            for it in items:
                name = it.get('name')
                size = it.get('size','')
                mark = '✓' if is_installed(name) else ''
                models_tree.insert('', tk.END, values=(mark, name, size))

        def _on_lang_select(evt=None):
            sel = lang_listbox.curselection()
            q = (search_var.get() or '').strip()
            if not sel:
                # clear
                for i in models_tree.get_children():
                    models_tree.delete(i)
                return
            lang = lang_listbox.get(sel[0])
            _populate_models_for(lang, filter_q=q)

        lang_listbox.bind('<<ListboxSelect>>', _on_lang_select)

        def _refresh_models():
            status_var.set("Fetching model list...")
            progress.config(mode='indeterminate')
            progress.start(10)

            def worker():
                nonlocal models_by_lang
                try:
                    # Delegate parsing to the headless parser to keep parsing logic
                    # consistent and easier to maintain/test.
                    models_by_lang = parse_vosk_models()
                except Exception as e:
                    models_by_lang = {}
                    status = f"Failed to fetch models: {e}"
                    self.safe_after(0, lambda: status_var.set(status))
                finally:
                    def ui_done():
                        progress.stop()
                        progress.config(mode='determinate', value=0)
                        _clear_models_view()
                        langs = sorted(models_by_lang.keys())
                        _populate_languages(langs)
                        status_var.set(f"Loaded {sum(len(v) for v in models_by_lang.values())} models across {len(langs)} languages")
                    self.safe_after(0, ui_done)

            threading.Thread(target=worker, daemon=True).start()

        def _on_search(*a):
            q = (search_var.get() or '').strip()
            sel = lang_listbox.curselection()
            if sel:
                lang = lang_listbox.get(sel[0])
                _populate_models_for(lang, filter_q=q)

        # trace safely
        try:
            search_var.trace_add('write', lambda *a: _on_search())
        except Exception:
            try:
                search_var.trace('w', lambda *a: _on_search())
            except Exception:
                pass

        def _download_selected():
            sel = models_tree.selection()
            if not sel:
                messagebox.showwarning('Vosk Models', 'Select a model to download')
                return
            item_id = sel[0]
            vals = models_tree.item(item_id, 'values')
            if not vals:
                messagebox.showerror('Vosk Models', 'No model selected')
                return
            # values = (installed, name, size)
            name = vals[1]
            size = vals[2] if len(vals) > 2 else ''
            # find URL from cache by matching name under selected language
            lsel = lang_listbox.curselection()
            if not lsel:
                messagebox.showwarning('Vosk Models', 'Select a language and model')
                return
            lang = lang_listbox.get(lsel[0])
            candidates = [m for m in models_by_lang.get(lang, []) if m.get('name') == name]
            if not candidates:
                messagebox.showerror('Vosk Models', 'Model metadata not found')
                return
            item = candidates[0]
            url = item.get('url')
            if not url:
                messagebox.showerror('Vosk Models', 'No download URL found')
                return
            # confirm
            if not messagebox.askyesno('Download', f"Download and install Vosk model '{name}' to application models directory? This may be large."):
                return

            # Download into a temporary file under models_root
            dest_dir = self.models_root
            # Verify writeability of dest_dir; packaged installs (Program Files) may not be writable.
            try:
                test_path = os.path.join(dest_dir, '.write_test')
                with open(test_path, 'w', encoding='utf-8') as tf:
                    tf.write('test')
                try:
                    os.remove(test_path)
                except Exception:
                    pass
            except Exception:
                # Not writeable -> try a platform-appropriate per-user folder as a fallback
                try:
                    # Prefer the resources helper which on macOS returns ~/Documents/VAICCS/Models
                    fallback = None
                    try:
                        fallback = resources.get_models_dir()
                    except Exception:
                        # last-resort: mimic previous fallback behavior
                        try:
                            if sys.platform.startswith('win'):
                                local = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
                            elif sys.platform == 'darwin':
                                local = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
                            else:
                                local = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
                        except Exception:
                            local = os.path.expanduser('~')
                        fallback = os.path.join(local, 'VAICCS', 'models')
                    os.makedirs(fallback, exist_ok=True)
                    old_dest = dest_dir
                    dest_dir = fallback
                    try:
                        self.models_root = dest_dir
                    except Exception:
                        pass
                    try:
                        # update UI var so the user can see where the model was saved
                        if getattr(self, '_models_root_var', None):
                            self._models_root_var.set(dest_dir)
                    except Exception:
                        pass
                except Exception:
                    # if fallback also fails, leave dest_dir as original and attempt to proceed
                    try:
                        _hlog(f"Write test failed for {self.models_root} and fallback creation failed")
                    except Exception:
                        pass
            try:
                log_dir = dest_dir
                os.makedirs(log_dir, exist_ok=True)
                hance_log = os.path.join(log_dir, 'hance_install.log')
            except Exception:
                hance_log = None
            def _hlog(msg: str):
                try:
                    if hance_log:
                        with open(hance_log, 'a', encoding='utf-8') as lf:
                            lf.write(msg + '\n')
                except Exception:
                    pass
            fname = os.path.basename(url.split('?')[0])
            dest_path = os.path.join(dest_dir, fname)

            progress.config(mode='determinate', value=0, maximum=100)
            status_var.set('Starting download...')

            def worker_download():
                try:
                    try:
                        _hlog(f"Hance download worker starting for {name} URL={url} dest={dest_dir} dest_path={dest_path}")
                    except Exception:
                        pass
                    # Setup cancel event so user can cancel this download
                    self._model_download_cancel_event = threading.Event()
                    self._model_download_thread = threading.current_thread()
                    with requests.get(url, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        total = r.headers.get('Content-Length')
                        if total is None:
                            total = 0
                        else:
                            total = int(total)
                        written = 0
                        tmp_path = dest_path + '.part'
                        with open(tmp_path, 'wb') as outf:
                            for chunk in r.iter_content(chunk_size=8192):
                                # check cancellation
                                if self._model_download_cancel_event is not None and self._model_download_cancel_event.is_set():
                                    # remove partial file and abort
                                    try:
                                        outf.close()
                                    except Exception:
                                        pass
                                    try:
                                        os.remove(tmp_path)
                                    except Exception:
                                        pass
                                    self.safe_after(0, lambda: status_var.set('Download cancelled'))
                                    return
                                if not chunk:
                                    continue
                                outf.write(chunk)
                                written += len(chunk)
                                if total:
                                    pct = int(written * 100 / total)
                                else:
                                    pct = 0
                                self.safe_after(0, lambda p=pct: progress.config(value=p))
                        try:
                            os.replace(tmp_path, dest_path)
                        except Exception:
                            shutil.move(tmp_path, dest_path)
                        try:
                            _hlog(f"Downloaded file saved to: {dest_path}")
                        except Exception:
                            pass
                    # extraction
                    status = 'Download complete. Extracting...'
                    self.safe_after(0, lambda: status_var.set(status))
                    extract_to = dest_dir
                    try:
                        self._extract_archive(dest_path, extract_to)
                    except Exception as e:
                        self.safe_after(0, lambda: messagebox.showerror('Vosk Models', f'Extraction failed: {e}'))
                        return
                    # Only remove the downloaded archive if extraction succeeded;
                    # otherwise keep the model file (e.g., .hance) in place.
                    was_extracted = False
                    try:
                        # detect archive-like extensions and attempt extraction
                        archive_exts = ('.zip', '.tar.gz', '.tgz', '.tar', '.tar.bz2', '.tar.xz', '.7z')
                        if any(dest_path.lower().endswith(ext) for ext in archive_exts):
                            try:
                                self._extract_archive(dest_path, dest_dir)
                                was_extracted = True
                            except Exception:
                                was_extracted = False
                    except Exception:
                        was_extracted = False
                    if was_extracted:
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
                    # set model path to extracted folder
                    found_folder = None
                    for nm in os.listdir(extract_to):
                        pth = os.path.join(extract_to, nm)
                        if os.path.isdir(pth) and nm.startswith('vosk-model'):
                            found_folder = pth
                            break
                    if not found_folder:
                        for nm in os.listdir(extract_to):
                            pth = os.path.join(extract_to, nm)
                            if os.path.isdir(pth) and 'model' in nm:
                                found_folder = pth
                                break
                    if found_folder:
                        # Move model folder into models_root if extraction placed elsewhere
                        try:
                            target = os.path.join(self.models_root, os.path.basename(found_folder))
                            if os.path.abspath(found_folder) != os.path.abspath(target):
                                try:
                                    # if target already exists, choose target as found_folder
                                    if not os.path.exists(target):
                                        shutil.move(found_folder, target)
                                    else:
                                        # existing target, remove extracted folder if safe
                                        try:
                                            shutil.rmtree(found_folder)
                                        except Exception:
                                            pass
                                except Exception:
                                    target = found_folder
                        except Exception:
                            target = found_folder
                        self.safe_after(0, lambda: [self.model_path_var.set(target), self._update_model_status(), status_var.set(f'Installed: {os.path.basename(target)}')])
                    else:
                        self.safe_after(0, lambda: status_var.set('Extraction complete but model folder not found; please browse manually'))
                except Exception as e:
                    self.safe_after(0, lambda: messagebox.showerror('Vosk Models', f'Download failed: {e}'))
                    self.safe_after(0, lambda: status_var.set('Download failed'))
                finally:
                    # clear cancel event and thread
                    try:
                        self._model_download_thread = None
                        if self._model_download_cancel_event is not None:
                            self._model_download_cancel_event = None
                    except Exception:
                        pass
                    self.safe_after(0, lambda: progress.config(value=0))

            threading.Thread(target=worker_download, daemon=True).start()

        def _cancel_download():
            try:
                if self._model_download_cancel_event is not None:
                    self._model_download_cancel_event.set()
                    status_var.set('Cancelling download...')
                else:
                    status_var.set('No active download')
            except Exception:
                pass

        def _select_installed():
            sel = models_tree.selection()
            if not sel:
                messagebox.showwarning('Vosk Models', 'Select a model to choose')
                return
            item_id = sel[0]
            vals = models_tree.item(item_id, 'values')
            if not vals:
                messagebox.showerror('Vosk Models', 'No model selected')
                return
            name = vals[1]
            target = _find_installed_model_dir(name)
            if not target:
                messagebox.showerror('Vosk Models', 'Selected model is not installed')
                return
            # Set model path to installed folder and update status
            self.safe_after(0, lambda: [self.model_path_var.set(target), self._update_model_status(), status_var.set(f'Selected installed: {os.path.basename(target)}'), dlg.destroy()])

        def _on_tree_select(evt=None):
            # enable/disable select button depending on whether the selected
            # model is already installed
            sel = models_tree.selection()
            if not sel:
                try:
                    select_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                return
            item_id = sel[0]
            vals = models_tree.item(item_id, 'values')
            name = (vals[1] if vals and len(vals) > 1 else '')
            if _find_installed_model_dir(name):
                try:
                    select_btn.config(state=tk.NORMAL)
                except Exception:
                    pass
            else:
                try:
                    select_btn.config(state=tk.DISABLED)
                except Exception:
                    pass

        def _on_tree_doubleclick(evt=None):
            # If double-clicked on an installed model, select it.
            sel = models_tree.selection()
            if not sel:
                return
            item_id = sel[0]
            vals = models_tree.item(item_id, 'values')
            name = (vals[1] if vals and len(vals) > 1 else '')
            if _find_installed_model_dir(name):
                _select_installed()

        def _close():
            try:
                dlg.destroy()
            except Exception:
                pass

        ttk.Button(btn_frm, text="Refresh", command=_refresh_models).pack(side=tk.LEFT)
        ttk.Button(btn_frm, text="Download Selected", command=_download_selected).pack(side=tk.LEFT, padx=(6,0))
        select_btn = ttk.Button(btn_frm, text="Select Installed", command=_select_installed)
        select_btn.pack(side=tk.LEFT, padx=(6,0))
        select_btn.config(state=tk.DISABLED)
        ttk.Button(btn_frm, text="Cancel Download", command=_cancel_download).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(btn_frm, text="Close", command=_close).pack(side=tk.RIGHT)

        # center and open
        try:
            # hook selection change and double-click events to the tree
            models_tree.bind('<<TreeviewSelect>>', lambda e: _on_tree_select(e))
            models_tree.bind('<Double-1>', lambda e: _on_tree_doubleclick(e))

            self.update_idletasks()
            dlg.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 2
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass

        try:
            self.wait_window(dlg)
        except Exception:
            pass

    # Hance model manager dialog (simple single-list)
    def _open_hance_model_manager(self):
        dlg = tk.Toplevel(self)
        try:
            dlg.transient(self)
        except Exception:
            pass
        try:
            dlg_icon = resources._resource_path('icon.ico')
        except Exception:
            dlg_icon = 'icon.ico'
        try:
            if dlg_icon and os.path.exists(dlg_icon):
                try:
                    dlg.iconbitmap(dlg_icon)
                except Exception:
                    try:
                        img = tk.PhotoImage(file=dlg_icon)
                        dlg.iconphoto(False, img)
                        dlg._icon_image = img
                    except Exception:
                        pass
        except Exception:
            pass
        dlg.title("Hance Model Manager")
        try:
            dlg.grab_set()
        except Exception:
            pass

        frm = ttk.Frame(dlg, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Available Hance Models:").pack(anchor=tk.W)
        # search / filter
        search_var = tk.StringVar()
        search_entry = ttk.Entry(frm, textvariable=search_var)
        search_entry.pack(fill=tk.X, pady=(4,4))

        # models list only (no languages)
        cols = ('installed', 'model', 'size')
        models_tree = ttk.Treeview(frm, columns=cols, show='headings', height=12)
        models_tree.heading('installed', text='')
        models_tree.heading('model', text='Model')
        models_tree.heading('size', text='Size')
        models_tree.column('installed', anchor=tk.CENTER, width=30)
        models_tree.column('model', anchor=tk.W, width=350)
        models_tree.column('size', anchor=tk.CENTER, width=80)
        models_tree.pack(fill=tk.BOTH, expand=True, pady=(4,4))

        status_var = tk.StringVar(value="Click Refresh to load models from GitHub: hance-engine/hance-api/Models")
        ttk.Label(frm, textvariable=status_var, wraplength=500).pack(anchor=tk.W, pady=(6,4))
        # Show where models will be installed
        try:
            self._models_root_var = tk.StringVar(value=self.models_root)
            ttk.Label(frm, text="Install path:", foreground='gray').pack(anchor=tk.W)
            ttk.Label(frm, textvariable=self._models_root_var, wraplength=500).pack(anchor=tk.W, pady=(0,6))
        except Exception:
            pass

        progress = ttk.Progressbar(frm, orient='horizontal', length=400, mode='determinate')
        progress.pack(fill=tk.X, pady=(4,4))

        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill=tk.X, pady=(6,0))

        models_list = []

        def _clear_models_view():
            for i in models_tree.get_children():
                models_tree.delete(i)

        def _get_installed_entries():
            try:
                return [d for d in os.listdir(self.models_root)]
            except Exception:
                return []

        def _find_installed_model_path(disp_name: str):
            if not disp_name:
                return None
            dn = disp_name.strip().lower()
            for candidate in _get_installed_entries():
                try:
                    if candidate.lower().strip() == dn:
                        p = os.path.join(self.models_root, candidate)
                        return p
                    # also check filename matches
                    if os.path.splitext(candidate)[0].lower().strip() == os.path.splitext(dn)[0]:
                        return os.path.join(self.models_root, candidate)
                except Exception:
                    continue
            return None

        def _populate_models(filter_q=None):
            _clear_models_view()
            items = list(models_list)
            if filter_q:
                fq = filter_q.lower()
                items = [it for it in items if fq in (it.get('name') or '').lower() or fq in (it.get('url') or '').lower()]

            def is_installed(disp_name: str) -> bool:
                return _find_installed_model_path(disp_name) is not None

            for it in items:
                name = it.get('name')
                size = it.get('size','')
                mark = '✓' if is_installed(name) else ''
                models_tree.insert('', tk.END, values=(mark, name, size))

        def _on_search(*a):
            q = (search_var.get() or '').strip()
            _populate_models(filter_q=q)

        try:
            search_var.trace_add('write', lambda *a: _on_search())
        except Exception:
            try:
                search_var.trace('w', lambda *a: _on_search())
            except Exception:
                pass

        def _refresh_models():
            status_var.set('Fetching model list...')
            progress.config(mode='indeterminate')
            progress.start(10)

            def worker():
                nonlocal models_list
                try:
                    models_map = parse_hance_models()
                    # flatten
                    items = []
                    for v in models_map.values():
                        items.extend(v)
                    models_list = items
                except Exception as e:
                    models_list = []
                    self.safe_after(0, lambda: status_var.set(f"Failed to fetch models: {e}"))
                finally:
                    def ui_done():
                        progress.stop()
                        progress.config(mode='determinate', value=0)
                        _clear_models_view()
                        _populate_models()
                        status_var.set(f"Loaded {len(models_list)} Hance model(s)")
                    self.safe_after(0, ui_done)

            threading.Thread(target=worker, daemon=True).start()

        def _download_selected():
            sel = models_tree.selection()
            if not sel:
                messagebox.showwarning('Hance Models', 'Select a model to download')
                return
            item_id = sel[0]
            vals = models_tree.item(item_id, 'values')
            if not vals:
                messagebox.showerror('Hance Models', 'No model selected')
                return
            name = vals[1]
            # find URL by matching name
            candidates = [m for m in models_list if m.get('name') == name]
            if not candidates:
                messagebox.showerror('Hance Models', 'Model metadata not found')
                return
            item = candidates[0]
            url = item.get('url')
            if not url:
                messagebox.showerror('Hance Models', 'No download URL found')
                return
            if not messagebox.askyesno('Download', f"Download and install Hance model '{name}' to application models directory? This may be large."):
                return

            dest_dir = self.models_root
            # Ensure dest_dir is writeable; if not, prefer resources.get_models_dir()
            try:
                os.makedirs(dest_dir, exist_ok=True)
            except Exception:
                try:
                    dest_dir = resources.get_models_dir()
                    os.makedirs(dest_dir, exist_ok=True)
                    try:
                        self.models_root = dest_dir
                        if getattr(self, '_models_root_var', None):
                            self._models_root_var.set(dest_dir)
                    except Exception:
                        pass
                except Exception:
                    # fallback to original and let the download fail later
                    pass

            fname = os.path.basename(url.split('?')[0])
            dest_path = os.path.join(dest_dir, fname)

            progress.config(mode='determinate', value=0, maximum=100)
            status_var.set('Starting download...')

            def worker_download():
                try:
                    self._model_download_cancel_event = threading.Event()
                    self._model_download_thread = threading.current_thread()
                    with requests.get(url, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        total = r.headers.get('Content-Length')
                        if total is None:
                            total = 0
                        else:
                            total = int(total)
                        written = 0
                        tmp_path = dest_path + '.part'
                        with open(tmp_path, 'wb') as outf:
                            for chunk in r.iter_content(chunk_size=8192):
                                if self._model_download_cancel_event is not None and self._model_download_cancel_event.is_set():
                                    try:
                                        outf.close()
                                    except Exception:
                                        pass
                                    try:
                                        os.remove(tmp_path)
                                    except Exception:
                                        pass
                                    self.safe_after(0, lambda: status_var.set('Download cancelled'))
                                    return
                                if not chunk:
                                    continue
                                outf.write(chunk)
                                written += len(chunk)
                                if total:
                                    pct = int(written * 100 / total)
                                else:
                                    pct = 0
                                self.safe_after(0, lambda p=pct: progress.config(value=p))
                        try:
                            os.replace(tmp_path, dest_path)
                        except Exception:
                            shutil.move(tmp_path, dest_path)
                    # extraction if archive
                    status = 'Download complete. Extracting if needed...'
                    self.safe_after(0, lambda: status_var.set(status))
                    was_extracted = False
                    try:
                        archive_exts = ('.zip', '.tar.gz', '.tgz', '.tar', '.tar.bz2', '.tar.xz', '.7z')
                        if any(dest_path.lower().endswith(ext) for ext in archive_exts):
                            try:
                                self._extract_archive(dest_path, dest_dir)
                                was_extracted = True
                                try:
                                    _hlog(f"File extracted: {dest_path} -> {dest_dir}")
                                except Exception:
                                    pass
                            except Exception as e:
                                try:
                                    _hlog(f"Extraction failed: {e}")
                                except Exception:
                                    pass
                                was_extracted = False
                        else:
                            try:
                                _hlog(f"Not an archive; skipping extraction: {dest_path}")
                            except Exception:
                                pass
                    except Exception as e:
                        try:
                            _hlog(f"Extraction check error: {e}")
                        except Exception:
                            pass
                        was_extracted = False
                    if was_extracted:
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
                    # Find installed path
                    found = None
                    # If we extracted into a folder, prefer that
                    for nm in os.listdir(dest_dir):
                        pth = os.path.join(dest_dir, nm)
                        try:
                            if os.path.isdir(pth) and nm.lower().startswith(os.path.splitext(name)[0].lower()):
                                found = pth
                                break
                        except Exception:
                            continue
                    # If not found by folder match, check for file by filename
                    if not found:
                        fpth = os.path.join(dest_dir, fname)
                        if os.path.exists(fpth):
                            found = fpth
                    # As a final fallback search recursively for matching files (e.g., .hance files inside a directory)
                    if not found:
                        base_no_ext = os.path.splitext(name)[0].lower()
                        for root, dirs, files in os.walk(dest_dir):
                            for file in files:
                                try:
                                    if file.lower().startswith(base_no_ext) or os.path.splitext(file)[0].lower() == base_no_ext:
                                        found = os.path.join(root, file)
                                        break
                                except Exception:
                                    continue
                            if found:
                                break
                    if found:
                        try:
                            _hlog(f"Found installed model path: {found}")
                        except Exception:
                            pass
                        self.safe_after(0, lambda: [self.hance_model_var.set(found), status_var.set(f'Installed: {os.path.basename(found)}')])
                    else:
                        self.safe_after(0, lambda: status_var.set('Installed but model file not found; please browse manually'))
                        try:
                            _hlog(f"Model install not found after download. dest_dir={dest_dir}, fname={fname}, name={name}")
                            _hlog(f"Models dir listing: {list(os.listdir(dest_dir))}")
                        except Exception:
                            pass
                except Exception as e:
                    self.safe_after(0, lambda: messagebox.showerror('Hance Models', f'Download failed: {e}'))
                    self.safe_after(0, lambda: status_var.set('Download failed'))
                finally:
                    try:
                        self._model_download_thread = None
                        if self._model_download_cancel_event is not None:
                            self._model_download_cancel_event = None
                    except Exception:
                        pass
                    self.safe_after(0, lambda: progress.config(value=0))

            threading.Thread(target=worker_download, daemon=True).start()

        def _cancel_download():
            try:
                if self._model_download_cancel_event is not None:
                    self._model_download_cancel_event.set()
                    status_var.set('Cancelling download...')
                else:
                    status_var.set('No active download')
            except Exception:
                pass

        def _select_installed():
            sel = models_tree.selection()
            if not sel:
                messagebox.showwarning('Hance Models', 'Select a model to choose')
                return
            item_id = sel[0]
            vals = models_tree.item(item_id, 'values')
            if not vals:
                messagebox.showerror('Hance Models', 'No model selected')
                return
            name = vals[1]
            target = _find_installed_model_path(name)
            if not target:
                messagebox.showerror('Hance Models', 'Selected model is not installed')
                return
            self.safe_after(0, lambda: [self.hance_model_var.set(target), self.noise_status_var.set(f"Installed (model:{os.path.basename(target)})"), dlg.destroy()])

        def _on_tree_select(evt=None):
            sel = models_tree.selection()
            if not sel:
                try:
                    select_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                return
            item_id = sel[0]
            vals = models_tree.item(item_id, 'values')
            name = (vals[1] if vals and len(vals) > 1 else '')
            if _find_installed_model_path(name):
                try:
                    select_btn.config(state=tk.NORMAL)
                except Exception:
                    pass
            else:
                try:
                    select_btn.config(state=tk.DISABLED)
                except Exception:
                    pass

        def _on_tree_doubleclick(evt=None):
            sel = models_tree.selection()
            if not sel:
                return
            item_id = sel[0]
            vals = models_tree.item(item_id, 'values')
            name = (vals[1] if vals and len(vals) > 1 else '')
            if _find_installed_model_path(name):
                _select_installed()

        def _close():
            try:
                dlg.destroy()
            except Exception:
                pass

        ttk.Button(btn_frm, text="Refresh", command=_refresh_models).pack(side=tk.LEFT)
        ttk.Button(btn_frm, text="Download Selected", command=_download_selected).pack(side=tk.LEFT, padx=(6,0))
        select_btn = ttk.Button(btn_frm, text="Select Installed", command=_select_installed)
        select_btn.pack(side=tk.LEFT, padx=(6,0))
        select_btn.config(state=tk.DISABLED)
        ttk.Button(btn_frm, text="Cancel Download", command=_cancel_download).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(btn_frm, text="Close", command=_close).pack(side=tk.RIGHT)

        try:
            models_tree.bind('<<TreeviewSelect>>', lambda e: _on_tree_select(e))
            models_tree.bind('<Double-1>', lambda e: _on_tree_doubleclick(e))
            self.update_idletasks()
            dlg.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 2
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass

        try:
            self.wait_window(dlg)
        except Exception:
            pass

    def _extract_archive(self, path: str, extract_to: str):
        # Support zip and tar(.gz/.bz2/.xz)
        if path.lower().endswith('.zip'):
            with zipfile.ZipFile(path, 'r') as zf:
                zf.extractall(extract_to)
            return
        # tar-like
        if any(path.lower().endswith(s) for s in ['.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tar.xz']):
            with tarfile.open(path, 'r:*') as tfh:
                tfh.extractall(extract_to)
            return
        # unknown format: raise
        raise ValueError('Unsupported archive format')

    def _update_thread_status(self, applied: bool = False):
        try:
            cpu = int(self.cpu_threads_var.get() or 0)
        except Exception:
            cpu = 0
        if cpu <= 0:
            self.thread_status_var.set("Threads: auto (not applied)")
            return

        # check environment variables to see if they match
        omp = os.environ.get("OMP_NUM_THREADS")
        mkl = os.environ.get("MKL_NUM_THREADS")
        openblas = os.environ.get("OPENBLAS_NUM_THREADS")
        matches = (str(cpu) == omp) or (str(cpu) == mkl) or (str(cpu) == openblas)
        if applied or matches:
            self.thread_status_var.set(f"Threads: {cpu} (applied)")
        else:
            self.thread_status_var.set(f"Threads: {cpu} (not applied)")

    def _update_bad_words_menu_label(self):
        """Update the File menu label for the bad-words entry to Load/Unload."""
        try:
            menu = getattr(self, '_file_menu', None)
            idx = getattr(self, '_bad_words_menu_index', None)
            if menu is None or idx is None:
                return
            try:
                loaded = bool(self._bad_words_loaded_var.get())
            except Exception:
                loaded = False
            label = "Unload Restricted Words File" if loaded else "Load Restricted Words File"
            try:
                menu.entryconfig(idx, label=label)
            except Exception:
                # some Tk implementations may want the index as a string
                try:
                    menu.entryconfig(str(idx), label=label)
                except Exception:
                    pass
        except Exception:
            pass

    def _ask_unload_replace(self, path: str):
        """Show a small modal dialog with buttons 'Unload', 'Replace', 'Cancel'.

        Returns:
          True  -> Unload
          False -> Replace (choose different file)
          None  -> Cancel
        """
        # Attempt to create a custom dialog; if anything goes wrong, raise so
        # the caller can fall back to the standard messagebox.
        dlg = tk.Toplevel(self)
        try:
            dlg.transient(self)
        except Exception:
            pass
        dlg.title("Restricted Words")
        # make window modal
        try:
            dlg.grab_set()
        except Exception:
            pass

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        msg = tk.Text(frm, wrap=tk.WORD, height=6, width=60)
        msg.insert(tk.END, f"A restricted words file is currently loaded:\n{path}\n\nChoose 'Unload' to unload it, 'Replace' to select a different file, or 'Cancel' to keep the current file.")
        msg.config(state=tk.DISABLED, borderwidth=0, background=self.cget('background'))
        msg.pack(fill=tk.BOTH, expand=True)

        result = {'value': None}

        def on_unload():
            result['value'] = True
            try:
                dlg.destroy()
            except Exception:
                pass

        def on_replace():
            result['value'] = False
            try:
                dlg.destroy()
            except Exception:
                pass

        def on_cancel():
            result['value'] = None
            try:
                dlg.destroy()
            except Exception:
                pass

        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_frm, text="Unload", command=on_unload).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frm, text="Replace", command=on_replace).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frm, text="Cancel", command=on_cancel).pack(side=tk.RIGHT, padx=4)

        # center dialog over parent
        try:
            self.update_idletasks()
            dlg.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 2
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass

        # Wait for dialog to be closed
        try:
            self.wait_window(dlg)
        except Exception:
            pass

        return result['value']

    # --- Async model loader helpers ---
    def _show_loading_dialog(self, title: str = "Loading", text: str = "Please wait while the model loads..."):
        dlg = tk.Toplevel(self)
        try:
            dlg.transient(self)
        except Exception:
            pass
        dlg.title(title)
        try:
            dlg.grab_set()
        except Exception:
            pass

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        lbl = ttk.Label(frm, text=text, wraplength=400)
        lbl.pack(anchor=tk.W, pady=(0,8))
        pb = ttk.Progressbar(frm, mode='indeterminate', length=360)
        pb.pack(fill=tk.X)
        pb.start(12)

        # Cancel flag - GUI can't reliably interrupt native model load, but we
        # expose a cancellation flag so the UI can ignore the result if user
        # cancels while load completes.
        cancel_event = threading.Event()

        def on_cancel():
            try:
                cancel_event.set()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill=tk.X, pady=(8,0))
        ttk.Button(btn_frm, text="Cancel", command=on_cancel).pack(side=tk.RIGHT)

        # center dialog
        try:
            self.update_idletasks()
            dlg.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 2
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass

        return dlg, pb, cancel_event

    def _start_engine_async(self, engine: 'CaptionEngine', on_started=None, on_error=None, cancel_event: threading.Event = None):
        """Start the CaptionEngine in a worker thread so model loading doesn't block the Tk mainloop.

        The engine.start(...) call performs model import/loading; running it in
        a background thread keeps the UI responsive. `on_started` and
        `on_error` are called on the main thread via `after`.
        """
        def worker():
            try:
                # start the engine (this will call _init_recognizer which may be slow)
                engine.start(self._on_caption)
                # If user cancelled while loading, stop engine and report cancel
                if cancel_event is not None and cancel_event.is_set():
                    try:
                        engine.stop()
                    except Exception:
                        pass
                    # notify main thread of cancellation via on_error if provided
                    if on_error:
                        self.safe_after(0, lambda: on_error("cancelled"))
                    return

                # otherwise notify success on main thread
                if on_started:
                    self.safe_after(0, lambda: on_started())
            except Exception as e:
                # pass exception message to UI thread
                if on_error:
                    self.safe_after(0, lambda: on_error(str(e)))
                else:
                    try:
                        self.safe_after(0, lambda: messagebox.showerror("Engine start failed", str(e)))
                    except Exception:
                        pass

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def start_capture(self):
        # set device if selected
        sel = self.device_combo.get()
        if sel and ":" in sel:
            idx = int(sel.split(":", 1)[0])
            try:
                sd.default.device = idx
            except Exception:
                pass

        try:
            self._log_button_states("start_capture entry - after device selection")
        except Exception:
            pass

        if self.engine and getattr(self.engine, "_thread", None) and self.engine._thread.is_alive():
            try:
                print("[UI] start_capture: engine already running, returning")
            except Exception:
                pass
            return
        # Determine model selection
        model_path = self.model_path_var.get().strip()
        try:
            print(f"[UI] start_capture: model_path='{model_path}', suppress_demo={getattr(self, '_suppress_demo_prompt', False)}")
        except Exception:
            pass
        demo = False
        cpu_threads = int(self.cpu_threads_var.get() or 0)
        if not model_path or not os.path.isdir(model_path) or not self._is_valid_model(model_path):
            # If this start was initiated by an automation, silently
            # enable demo mode instead of prompting the user.
            if getattr(self, '_suppress_demo_prompt', False):
                demo = True
            else:
                # Ask the user whether to run demo mode
                use_demo = messagebox.askyesno(
                    "No valid model selected",
                    "No valid VOSK model selected or path not found/invalid. Do you want to use demo mode?",
                )
                if not use_demo:
                    return
                demo = True

        # Create engine instance (heavy work happens in engine.start())
        self.engine = CaptionEngine(
            model_path=mainmod._resource_path(model_path) if not demo else None,
            demo=demo,
            cpu_threads=(cpu_threads if cpu_threads > 0 else None),
            enable_profile_matching=bool(self.profile_matching_var.get()),
            profile_match_threshold=float(self.profile_threshold_var.get()),
            punctuator=(self.punctuator_var.get().strip() if getattr(self, 'punctuator_var', None) is not None else None),
        )

        # If punctuator failed to initialize with diagnostics, surface a warning
        try:
            p = getattr(self.engine, '_punctuator', None)
            init_err = getattr(p, 'init_error', None)
            if init_err:
                try:
                    messagebox.showwarning("Punctuator initialization", f"Punctuator warning:\n{init_err}")
                except Exception:
                    try:
                        print("Punctuator init warning:\n", init_err)
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            print("[UI] start_capture: created CaptionEngine, about to show loading dialog and start async")
        except Exception:
            pass

        # Recase subprocess integration removed (using plain Vosk model only)

        # Show a modal loading dialog and start the engine in a background thread
        try:
            dlg, pb, cancel_evt = self._show_loading_dialog(title="Loading model", text=(f"Loading: {os.path.basename(model_path)}\nThis may take a few minutes..." if model_path else "Starting demo mode..."))
        except Exception:
            dlg = None
            pb = None
            cancel_evt = None

        # Flag to indicate the on_started callback ran
        _started_flag = {'ok': False}

        def _on_started():
            _started_flag['ok'] = True
            try:
                if pb:
                    pb.stop()
            except Exception:
                pass
            try:
                if dlg:
                    dlg.destroy()
            except Exception:
                pass
            # update UI now that engine thread is running
            try:
                self._update_model_status()
            except Exception:
                pass
            try:
                self._update_thread_status(applied=True)
            except Exception:
                pass
            try:
                self.start_btn.config(state=tk.DISABLED)
                self.stop_btn.config(state=tk.NORMAL)
                self.device_combo.config(state=tk.DISABLED)
            except Exception:
                pass
            try:
                self._log_button_states("engine started (_on_started)")
            except Exception:
                pass
            # If the engine's punctuator had initialization diagnostics, show them now
            try:
                p_err = None
                if getattr(self, 'engine', None) is not None:
                    p_err = getattr(self.engine, '_punctuator_init_error', None)
                if p_err:
                    try:
                        messagebox.showwarning("Punctuator initialization", f"Punctuator warning:\n{p_err}")
                    except Exception:
                        print("Punctuator init warning:\n", p_err)
            except Exception:
                pass

        def _on_error(err):
            try:
                if pb:
                    pb.stop()
            except Exception:
                pass
            try:
                if dlg:
                    dlg.destroy()
            except Exception:
                pass
            try:
                if err == "cancelled":
                    messagebox.showinfo("Cancelled", "Model load cancelled.")
                else:
                    messagebox.showerror("Model load failed", f"Failed to load model: {err}")
            except Exception:
                pass
            try:
                self.start_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.DISABLED)
                self.device_combo.config(state="readonly")
            except Exception:
                pass
            try:
                self._log_button_states("engine scheduling failed (start exception)")
            except Exception:
                pass
            try:
                self._log_button_states("engine start error (_on_error)")
            except Exception:
                pass
            try:
                self.engine = None
            except Exception:
                pass
        # start engine asynchronously; _start_engine_async will call engine.start()
        try:
            self._start_engine_async(self.engine, on_started=_on_started, on_error=_on_error, cancel_event=cancel_evt)
        except Exception:
            # If scheduling the start failed immediately, ensure UI is not left disabled
            try:
                self.start_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.DISABLED)
                self.device_combo.config(state="readonly")
            except Exception:
                pass

        # Watchdog: if model start doesn't call _on_started within 30s, restore UI
        def _start_watchdog():
            try:
                if not _started_flag.get('ok'):
                    # Attempt to stop any partially-started engine
                    try:
                        if getattr(self, 'engine', None) is not None:
                            try:
                                self.engine.stop()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Restore controls so user can try again
                    try:
                        self.start_btn.config(state=tk.NORMAL)
                        self.stop_btn.config(state=tk.DISABLED)
                        self.device_combo.config(state="readonly")
                    except Exception:
                        pass
                    try:
                        self._log_button_states("engine start watchdog restored UI")
                    except Exception:
                        pass
                    try:
                        # update status so user knows something went wrong
                        self.model_status_var.set("Model: start timed out or failed")
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            # 30s timeout to detect stuck loads
            self.safe_after(30000, _start_watchdog)
        except Exception:
            pass

    def stop_capture(self):
        if self.engine:
            try:
                self.engine.stop()
            except Exception:
                pass
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.device_combo.config(state="readonly")
        try:
            self._log_button_states("stop_capture")
        except Exception:
            pass

    def _on_caption(self, text: str):
        # ensure called in main thread
        def _handle():
            # If the engine reported an error, show it and stop
            if isinstance(text, str) and text.startswith("[ERROR]"):
                messagebox.showerror("Audio Error", text)
                # stop engine and re-enable controls
                try:
                    if self.engine:
                        self.engine.stop()
                except Exception:
                    pass
                self.start_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.DISABLED)
                self.device_combo.config(state="readonly")
                try:
                    self._log_button_states("_on_caption reported [ERROR]")
                except Exception:
                    pass
                return

            # Insert the text and compute its absolute character offset within the widget
            try:
                self.transcript.insert(tk.END, text + "\n")
            except Exception:
                try:
                    self.transcript.insert('end', text + "\n")
                except Exception:
                    pass
            # Compute the base character index (offset from 1.0) where this inserted text appears
            base_char_offset = None
            try:
                buf = self.transcript.get('1.0', 'end-1c')
                # prefer the last occurrence in case same line appears earlier
                pos = buf.rfind(text)
                if pos >= 0:
                    base_char_offset = pos
            except Exception:
                base_char_offset = None
            try:
                # auto-scroll to the end so new captions are visible (if enabled)
                if getattr(self, 'auto_scroll_var', None) and self.auto_scroll_var.get():
                    self.transcript.see(tk.END)
            except Exception:
                pass

            # forward to serial if enabled
            try:
                sm = getattr(self, 'serial_manager', None)
                if sm and getattr(self, 'serial_enabled_var', None) and self.serial_enabled_var.get():
                    try:
                        # enqueue caption text for the serial worker which will finish lines sequentially
                        try:
                            if getattr(self, '_serial_send_queue', None) is None:
                                self._serial_send_queue = queue.Queue()
                        except Exception:
                            self._serial_send_queue = queue.Queue()
                        try:
                            self._serial_send_queue.put(text)
                            # ensure a worker is running to process the queue
                            try:
                                self._start_serial_worker()
                            except Exception:
                                pass
                        except Exception as e:
                            try:
                                self.serial_status_var.set(f"Serial enqueue error: {e}")
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            # If called from the main thread, run handler directly for immediate UI updates
            if threading.current_thread() is threading.main_thread():
                try:
                    _handle()
                except Exception:
                    pass
            else:
                try:
                    self.safe_after(0, _handle)
                except RuntimeError:
                    try:
                        _handle()
                    except Exception:
                        pass
        except Exception:
            try:
                _handle()
            except Exception:
                pass

    # Voice Profiles tab
    def _build_profiles_tab(self):
        frm = ttk.Frame(self.profiles_frame)
        frm.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(frm)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Profile Name:").pack(anchor=tk.W)
        self.profile_name = tk.Entry(left)
        self.profile_name.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(left, text="Add WAV files", command=self._add_wavs).pack(anchor=tk.W)
        self.wav_listbox = tk.Listbox(left, height=8)
        self.wav_listbox.pack(fill=tk.BOTH, expand=False, pady=(6, 6))

        ttk.Button(left, text="Create Profile", command=self._create_profile).pack(pady=(6, 6))

        self.profile_status = ttk.Label(left, text="")
        self.profile_status.pack(anchor=tk.W)

        # (Operation buttons for selected profiles are shown on the right column
        # below the profiles list; remove duplicate buttons from the left column.)

        # right: existing profiles
        right = ttk.Frame(frm, width=250)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(right, text="Existing Profiles:").pack(anchor=tk.W)
        self.profiles_box = tk.Listbox(right)
        self.profiles_box.pack(fill=tk.BOTH, expand=True, pady=(6, 6))

        self.profile_mgr = VoiceProfileManager()
        self._refresh_profiles_list()
        # Edit / Delete buttons for selected profile
        btns = ttk.Frame(right)
        btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btns, text="Edit Selected", command=self._on_edit_selected).pack(side=tk.LEFT, padx=(0,4))
        ttk.Button(btns, text="Delete Selected", command=self._on_delete_selected).pack(side=tk.LEFT)

    def _build_vocab_tab(self):
        frm = ttk.Frame(self.vocab_frame, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(frm)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Custom Words (runtime vocabulary):").pack(anchor=tk.W)
        self.vocab_listbox = tk.Listbox(left)
        self.vocab_listbox.pack(fill=tk.BOTH, expand=True, pady=(6,6))

        ttk.Label(left, text="Audio samples for selected word:").pack(anchor=tk.W, pady=(6,0))
        self.samples_listbox = tk.Listbox(left, height=6)
        self.samples_listbox.pack(fill=tk.BOTH, expand=False, pady=(4,6))

        # right column: editor
        right = ttk.Frame(frm, width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(right, text="Word:").pack(anchor=tk.W)
        self.vocab_word_var = tk.StringVar()
        self.vocab_word_entry = ttk.Entry(right, textvariable=self.vocab_word_var)
        self.vocab_word_entry.pack(fill=tk.X, pady=(0,6))

        ttk.Label(right, text="Pronunciation (optional):").pack(anchor=tk.W)
        self.vocab_pron_var = tk.StringVar()
        self.vocab_pron_entry = ttk.Entry(right, textvariable=self.vocab_pron_var)
        self.vocab_pron_entry.pack(fill=tk.X, pady=(0,6))

        btn_frm = ttk.Frame(right)
        btn_frm.pack(fill=tk.X, pady=(6,6))
        ttk.Button(btn_frm, text="Add / Update", command=self._on_add_update_vocab).pack(side=tk.LEFT)
        ttk.Button(btn_frm, text="Remove", command=self._on_remove_vocab).pack(side=tk.LEFT, padx=(6,0))

        # recording controls below
        ttk.Separator(right, orient='horizontal').pack(fill=tk.X, pady=(8,8))

        ttk.Label(right, text="Audio Controls:").pack(anchor=tk.W)
        audio_btns = ttk.Frame(right)
        audio_btns.pack(fill=tk.X, pady=(4,4))
        # store buttons so we can enable/disable them during recording/playback
        self.record_btn = ttk.Button(audio_btns, text="Record", command=self._start_recording)
        self.record_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.vocab_stop_btn = ttk.Button(audio_btns, text="Stop", command=self._stop_recording, state=tk.DISABLED)
        self.vocab_stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6,0))
        self.play_btn = ttk.Button(audio_btns, text="Play", command=self._play_selected_sample)
        self.play_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6,0))
        self.delete_sample_btn = ttk.Button(audio_btns, text="Delete", command=self._delete_selected_sample)
        self.delete_sample_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6,0))

        # status label for audio operations
        self.audio_status_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.audio_status_var).pack(anchor=tk.W, pady=(6,0))

        self._recording = False
        self._record_stream = None
        self._record_buffer = []
        self._play_thread = None

        ttk.Separator(right, orient='horizontal').pack(fill=tk.X, pady=(8,8))

        ttk.Button(right, text="Apply to running engine", command=self._apply_vocab_to_engine).pack(fill=tk.X, pady=(0,6))
        ttk.Button(right, text="Load from file...", command=self._load_vocab_file).pack(fill=tk.X, pady=(0,6))
        ttk.Button(right, text="Save to file...", command=self._save_vocab_file).pack(fill=tk.X, pady=(0,6))
        ttk.Button(right, text="Save bundle (.zip)", command=self._save_bundle).pack(fill=tk.X, pady=(0,6))
        ttk.Button(right, text="Export Lexicon...", command=self._export_lexicon).pack(fill=tk.X, pady=(0,6))
        ttk.Button(right, text="Clear all", command=self._clear_vocab).pack(fill=tk.X, pady=(6,6))

        # populate listbox from manager if available
        self._refresh_vocab_list()

        # bind selection to populate editor
        try:
            self.vocab_listbox.bind('<<ListboxSelect>>', lambda e: self._on_vocab_selected())
            # allow play on double-click and keep listbox selection event (no-op)
            self.samples_listbox.bind('<<ListboxSelect>>', lambda e: None)
            self.samples_listbox.bind('<Double-Button-1>', lambda e: self._play_selected_sample())
        except Exception:
            pass

    def _build_noise_tab(self):
        frm = ttk.Frame(self.noise_frame, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(frm)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Noise Cancelation (Hance)").pack(anchor=tk.W)

        # Note: quick enable/disable control is on the Main tab; keep Noise
        # tab focused on model and installation controls.

        # Hance model selection
        ttk.Label(left, text="Hance model file:").pack(anchor=tk.W, pady=(8,2))
        model_frame = ttk.Frame(left)
        model_frame.pack(fill=tk.X)
        self.hance_model_var = tk.StringVar()
        self.hance_model_entry = ttk.Entry(model_frame, textvariable=self.hance_model_var)
        self.hance_model_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(model_frame, text="Browse...", command=self._browse_hance_model).pack(side=tk.RIGHT, padx=(6,0))

        # Load / Unload buttons and status
        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=(8,6))
        self.load_hance_btn = ttk.Button(btn_row, text="Install Noise Filter", command=self._install_noise)
        self.load_hance_btn.pack(side=tk.LEFT)
        self.unload_hance_btn = ttk.Button(btn_row, text="Uninstall", command=self._uninstall_noise)
        self.unload_hance_btn.pack(side=tk.LEFT, padx=(6,0))

        self.noise_status_var = tk.StringVar(value="Not installed")
        ttk.Label(left, textvariable=self.noise_status_var, foreground='blue').pack(anchor=tk.W)

        # Helpful note
        ttk.Label(left, text="Note: Hance SDK integration is attempted if available; otherwise a simple fallback noise gate is used.").pack(anchor=tk.W, pady=(6,0))

        # If not commercial, disable Hance/Noise controls and mark as unavailable
        try:
            if not getattr(self, '_is_commercial', False):
                try:
                    self.hance_model_entry.config(state='disabled')
                except Exception:
                    pass
                try:
                    self.load_hance_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    self.unload_hance_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    # ensure noise is off
                    self.noise_enabled_var.set(False)
                except Exception:
                    pass
                try:
                    self.noise_status_var.set("Disabled in Personal/Eval mode")
                except Exception:
                    pass
        except Exception:
            pass

    def _browse_hance_model(self):
        path = filedialog.askopenfilename(title="Select Hance model file", filetypes=[('All files','*.*')])
        if path:
            self.hance_model_var.set(path)

    def _install_noise(self):
        path = (self.hance_model_var.get() or '').strip() or None
        try:
            ok = noise_cancel.install(path)
            if ok:
                self.noise_status_var.set(f"Installed (model:{os.path.basename(path) if path else 'fallback'})")
                self.noise_enabled_var.set(True)
            else:
                self.noise_status_var.set("Failed to install")
                self.noise_enabled_var.set(False)
        except Exception as e:
            try:
                messagebox.showerror("Noise Cancel", f"Failed to install noise filter: {e}")
            except Exception:
                pass

    def _uninstall_noise(self):
        try:
            ok = noise_cancel.uninstall()
            if ok:
                self.noise_status_var.set("Not installed")
                self.noise_enabled_var.set(False)
            else:
                self.noise_status_var.set("Not installed")
        except Exception:
            try:
                messagebox.showwarning("Noise Cancel", "Failed to uninstall noise filter")
            except Exception:
                pass

    def _on_toggle_noise(self):
        if self.noise_enabled_var.get():
            self._install_noise()
        else:
            self._uninstall_noise()

    def refresh_license_state(self):
        """Refresh license status at runtime and enable/disable gated features.

        Call this after activation to enable commercial features without restart.
        """
        try:
            import license_manager
            is_commercial = (license_manager.license_type() == 'commercial')
        except Exception:
            is_commercial = False
        try:
            old = getattr(self, '_is_commercial', False)
            self._is_commercial = bool(is_commercial)
            self._automations_allowed = bool(is_commercial)
        except Exception:
            pass

        # Noise controls
        try:
            if is_commercial:
                try:
                    self.noise_chk.config(state=tk.NORMAL)
                except Exception:
                    pass
                try:
                    self.hance_model_entry.config(state='normal')
                except Exception:
                    pass
                try:
                    self.load_hance_btn.config(state=tk.NORMAL)
                except Exception:
                    pass
                try:
                    self.unload_hance_btn.config(state=tk.NORMAL)
                except Exception:
                    pass
                # if previously disabled, clear status message
                try:
                    if (not old) and (not self.noise_status_var.get() or 'Disabled in Personal' in self.noise_status_var.get()):
                        self.noise_status_var.set('Not installed')
                except Exception:
                    pass
            else:
                try:
                    self.noise_chk.config(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    self.hance_model_entry.config(state='disabled')
                except Exception:
                    pass
                try:
                    self.load_hance_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    self.unload_hance_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    self.noise_enabled_var.set(False)
                except Exception:
                    pass
                try:
                    self.noise_status_var.set('Disabled in Personal/Eval mode')
                except Exception:
                    pass
        except Exception:
            pass

        # Automations controls
        try:
            if is_commercial:
                try:
                    self.add_automation_btn.config(state=tk.NORMAL)
                except Exception:
                    pass
                try:
                    self.apply_automations_btn.config(state=tk.NORMAL)
                except Exception:
                    pass
                # Remove the "disabled in Personal/Eval mode" label if present
                try:
                    if getattr(self, '_automations_disabled_label', None):
                        self._automations_disabled_label.destroy()
                        self._automations_disabled_label = None
                except Exception:
                    pass
                # refresh display and start scheduler if automations present
                try:
                    self._refresh_automations_display()
                except Exception:
                    pass
                try:
                    if self.automation_manager.get_automations():
                        try:
                            self.automation_manager.start_scheduler()
                        except Exception:
                            pass
                except Exception:
                    pass
            else:
                try:
                    self.add_automation_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    self.apply_automations_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    self.automation_manager.stop_scheduler()
                except Exception:
                    pass
        except Exception:
            pass

    def _build_automations_tab(self):
        """Build the Automations tab for scheduling show automation."""
        frm = ttk.Frame(self.automations_frame, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        # Top controls frame
        controls_frm = ttk.Frame(frm)
        controls_frm.pack(fill=tk.X, pady=(0, 6))
        
        ttk.Label(controls_frm, text="Show Automations:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        
        # Add show button
        self.add_automation_btn = ttk.Button(controls_frm, text="+ Add Show", command=self._on_add_automation)
        self.add_automation_btn.pack(side=tk.LEFT, padx=(0, 4))
        
        self.apply_automations_btn = ttk.Button(controls_frm, text="Apply", command=self._on_apply_automations)
        self.apply_automations_btn.pack(side=tk.LEFT)

        # If automations are not allowed for this license, disable controls
        self._automations_disabled_label = None
        try:
            if not getattr(self, '_automations_allowed', False):
                try:
                    self.add_automation_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    self.apply_automations_btn.config(state=tk.DISABLED)
                except Exception:
                    pass
                try:
                    self._automations_disabled_label = ttk.Label(frm, text="Automations disabled in Personal/Eval mode.")
                    self._automations_disabled_label.pack(pady=(8,8))
                except Exception:
                    pass
                # further UI population will still run but controls are disabled
        except Exception:
            pass

        # Main scrollable frame for automations
        canvas_frm = ttk.Frame(frm)
        canvas_frm.pack(fill=tk.BOTH, expand=True)
        
        # Use the ttk frame background so the canvas matches light/dark mode on macOS
        try:
            style = ttk.Style()
            frame_bg = style.lookup('TFrame', 'background') or canvas_frm.cget('background')
        except Exception:
            frame_bg = canvas_frm.cget('background')
        self.automations_canvas = tk.Canvas(canvas_frm, bg=frame_bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frm, orient=tk.VERTICAL, command=self.automations_canvas.yview)
        self.automations_scrollable_frm = ttk.Frame(self.automations_canvas)
        
        self.automations_scrollable_frm.bind(
            "<Configure>",
            lambda e: self._on_automations_configure(e)
        )
        
        self.automations_canvas.create_window((0, 0), window=self.automations_scrollable_frm, anchor="nw")
        self.automations_canvas.configure(yscrollcommand=scrollbar.set)
        
        self.automations_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.automations_scrollbar = scrollbar
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind mouse wheel to canvas (only scroll if content overflows)
        def _on_mousewheel(event):
            try:
                canvas_height = self.automations_canvas.winfo_height()
                bbox = self.automations_canvas.bbox("all")
                scroll_height = bbox[3] if bbox else 0
                # Only scroll if content is taller than canvas
                if scroll_height > canvas_height:
                    self.automations_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except Exception:
                pass
        self.automations_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Store automation entry widgets for easy access
        self.automation_entries = []
        
        # Initialize with empty list
        self._refresh_automations_display()

    def _on_automations_configure(self, event):
        """Handle canvas configuration and update scrollbar visibility."""
        self.automations_canvas.configure(scrollregion=self.automations_canvas.bbox("all"))
        # Check if scrolling is needed
        try:
            canvas_height = self.automations_canvas.winfo_height()
            scroll_height = self.automations_canvas.bbox("all")[3] if self.automations_canvas.bbox("all") else 0
            if scroll_height <= canvas_height:
                # No scrolling needed, hide scrollbar and disable scrolling
                self.automations_scrollbar.pack_forget()
            else:
                # Scrolling needed, show scrollbar
                self.automations_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        except Exception:
            pass

    def _refresh_automations_display(self):
        """Refresh the display of automation entries."""
        # Clear existing entries
        for child in self.automations_scrollable_frm.winfo_children():
            child.destroy()
        self.automation_entries = []
        
        # Add entries for each automation
        for i, automation in enumerate(self.automation_manager.get_automations()):
            self._add_automation_entry_widget(automation, i)
        
        # If no automations, show placeholder
        if not self.automation_manager.get_automations():
            # Avoid forcing a hardcoded foreground color so the label adapts to theme
            placeholder = ttk.Label(self.automations_scrollable_frm, text="No shows configured. Click '+ Add Show' to get started.")
            placeholder.pack(fill=tk.X, padx=4, pady=4)
            try:
                # Ensure the scrollregion is updated and widgets are drawn immediately
                self.automations_scrollable_frm.update_idletasks()
                self.automations_canvas.configure(scrollregion=self.automations_canvas.bbox("all"))
                self.automations_canvas.update_idletasks()
            except Exception:
                pass

    def _add_automation_entry_widget(self, automation: ShowAutomation | None = None, index: int | None = None):
        """Add a single automation entry widget to the display."""
        if index is None:
            index = len(self.automation_entries)
        
        entry_frm = ttk.LabelFrame(self.automations_scrollable_frm, text=f"Show {index + 1}", padding=8)
        entry_frm.pack(fill=tk.X, padx=4, pady=4)
        
        # Show name
        name_frm = ttk.Frame(entry_frm)
        name_frm.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(name_frm, text="Show Name:").pack(side=tk.LEFT, padx=(0, 4))
        name_var = tk.StringVar(value=automation.name if automation else "")
        name_entry = ttk.Entry(name_frm, textvariable=name_var, width=20)
        name_entry.pack(side=tk.LEFT, padx=(0, 10))
        
        # Days of week checkboxes
        days_frm = ttk.Frame(entry_frm)
        days_frm.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(days_frm, text="Days:").pack(side=tk.LEFT, padx=(0, 4))
        
        days_list = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_vars = {}
        for day in days_list:
            var = tk.BooleanVar(value=(day in automation.days if automation else False))
            day_vars[day] = var
            chk = ttk.Checkbutton(days_frm, text=day[:3], variable=var)
            chk.pack(side=tk.LEFT, padx=2)
        
        # Time selection - Start time (3 dropdowns)
        start_time_frm = ttk.Frame(entry_frm)
        start_time_frm.pack(fill=tk.X, pady=(0, 6))
        
        ttk.Label(start_time_frm, text="Start:").pack(side=tk.LEFT, padx=(0, 4))
        
        # Parse existing start time or use defaults
        if automation and automation.start_time:
            start_parts = self._parse_time_string(automation.start_time)
        else:
            start_parts = {'hour': '12', 'minute': '00', 'period': 'PM'}
        
        start_hour_var = tk.StringVar(value=start_parts['hour'])
        start_hour_combo = ttk.Combobox(start_time_frm, textvariable=start_hour_var, values=self._get_hour_options(), width=2, state="readonly")
        start_hour_combo.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(start_time_frm, text=":").pack(side=tk.LEFT, padx=2)
        
        start_minute_var = tk.StringVar(value=start_parts['minute'])
        start_minute_combo = ttk.Combobox(start_time_frm, textvariable=start_minute_var, values=self._get_minute_options(), width=2, state="readonly")
        start_minute_combo.pack(side=tk.LEFT, padx=2)
        
        start_period_var = tk.StringVar(value=start_parts['period'])
        start_period_combo = ttk.Combobox(start_time_frm, textvariable=start_period_var, values=['AM', 'PM'], width=2, state="readonly")
        start_period_combo.pack(side=tk.LEFT, padx=(2, 20))
        
        # Time selection - End time (3 dropdowns)
        end_time_frm = ttk.Frame(entry_frm)
        end_time_frm.pack(fill=tk.X, pady=(0, 6))
        
        ttk.Label(end_time_frm, text="End:").pack(side=tk.LEFT, padx=(0, 4))
        
        # Parse existing end time or use defaults
        if automation and automation.end_time:
            end_parts = self._parse_time_string(automation.end_time)
        else:
            end_parts = {'hour': '1', 'minute': '00', 'period': 'PM'}
        
        end_hour_var = tk.StringVar(value=end_parts['hour'])
        end_hour_combo = ttk.Combobox(end_time_frm, textvariable=end_hour_var, values=self._get_hour_options(), width=2, state="readonly")
        end_hour_combo.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(end_time_frm, text=":").pack(side=tk.LEFT, padx=2)
        
        end_minute_var = tk.StringVar(value=end_parts['minute'])
        end_minute_combo = ttk.Combobox(end_time_frm, textvariable=end_minute_var, values=self._get_minute_options(), width=2, state="readonly")
        end_minute_combo.pack(side=tk.LEFT, padx=2)
        
        end_period_var = tk.StringVar(value=end_parts['period'])
        end_period_combo = ttk.Combobox(end_time_frm, textvariable=end_period_var, values=['AM', 'PM'], width=2, state="readonly")
        end_period_combo.pack(side=tk.LEFT, padx=(2, 20))
        
        # Remove button
        def on_remove():
            if index < len(self.automation_manager.get_automations()):
                self.automation_manager.remove_automation(index)
                self._refresh_automations_display()
        
        remove_btn = ttk.Button(end_time_frm, text="Remove", command=on_remove)
        remove_btn.pack(side=tk.LEFT)
        
        # Store entry data
        entry_data = {
            'frame': entry_frm,
            'name_var': name_var,
            'day_vars': day_vars,
            'start_hour_var': start_hour_var,
            'start_minute_var': start_minute_var,
            'start_period_var': start_period_var,
            'end_hour_var': end_hour_var,
            'end_minute_var': end_minute_var,
            'end_period_var': end_period_var,
            'index': index
        }
        self.automation_entries.append(entry_data)

    def _get_hour_options(self) -> list[str]:
        """Generate hour options (1-12)."""
        return [f"{i}" for i in range(1, 13)]
    
    def _get_minute_options(self) -> list[str]:
        """Generate minute options in 5-minute intervals."""
        return [f"{i:02d}" for i in range(0, 60, 5)]
    
    def _parse_time_string(self, time_str: str) -> dict:
        """Parse time string like '9:30 AM' into components."""
        try:
            parts = time_str.split()
            period = parts[-1] if parts[-1] in ('AM', 'PM') else 'PM'
            time_part = parts[0]
            hour, minute = time_part.split(':')
            return {'hour': hour, 'minute': minute, 'period': period}
        except Exception:
            return {'hour': '12', 'minute': '00', 'period': 'PM'}
    
    def _time_from_components(self, hour: str, minute: str, period: str) -> str:
        """Convert time components back to string format."""
        return f"{hour}:{minute} {period}"

    def _on_add_automation(self):
        """Add a new blank automation entry."""
        new_automation = ShowAutomation("New Show", [], "12:00 PM", "1:00 PM")
        self.automation_manager.add_automation(new_automation)
        self._refresh_automations_display()

    def _on_apply_automations(self):
        """Apply the automations from the UI."""
        try:
            # Collect automation data from UI
            new_automations = []
            for entry in self.automation_entries:
                name = entry['name_var'].get().strip()
                if not name:
                    try:
                        messagebox.showwarning("Automations", "All shows must have a name")
                    except Exception:
                        pass
                    return
                
                # Collect selected days
                days = [day for day, var in entry['day_vars'].items() if var.get()]
                if not days:
                    try:
                        messagebox.showwarning("Automations", f"'{name}' must have at least one day selected")
                    except Exception:
                        pass
                    return
                
                # Build time strings from components
                start_time = self._time_from_components(
                    entry['start_hour_var'].get(),
                    entry['start_minute_var'].get(),
                    entry['start_period_var'].get()
                )
                end_time = self._time_from_components(
                    entry['end_hour_var'].get(),
                    entry['end_minute_var'].get(),
                    entry['end_period_var'].get()
                )
                
                new_automations.append(ShowAutomation(name, days, start_time, end_time))
            
            # Replace automations
            self.automation_manager.set_automations(new_automations)
            
            try:
                messagebox.showinfo("Automations", f"Applied {len(new_automations)} show(s)")
            except Exception:
                pass
            # If we've just applied automations, ensure the scheduler is running
            # (respect license gating). Stop any existing scheduler first to
            # reset internal state, then start if allowed and automations exist.
            try:
                try:
                    import license_manager
                    is_commercial = (license_manager.license_type() == 'commercial')
                except Exception:
                    is_commercial = False

                try:
                    # Stop existing scheduler to avoid duplicate threads
                    self.automation_manager.stop_scheduler()
                except Exception:
                    pass

                if is_commercial and self.automation_manager.get_automations():
                    try:
                        self.automation_manager.start_scheduler()
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception as e:
            try:
                messagebox.showerror("Automations", f"Error applying automations: {e}")
            except Exception:
                pass

    def _on_automation_start(self):
        """Callback when an automation triggers start."""
        try:
            # Schedule `start_capture` on the Tk main thread so UI operations
            # are performed safely. Automation callbacks run in a background
            # scheduler thread and must not touch Tk widgets directly.
            def _do_start():
                try:
                    # Give immediate visual feedback that the automation
                    # is starting the capture/engine. This helps when model
                    # load takes time so user sees activity.
                    try:
                        self.model_status_var.set("Model: starting (automation)...")
                    except Exception:
                        pass
                    # Do not disable the Start button before invoking it; some
                    # ttk implementations prevent `invoke()` from calling the
                    # command when the widget state is disabled. Rely on the
                    # engine start success handler (`_on_started`) to update
                    # button states so the UI wiring behaves the same as a
                    # manual click.
                    try:
                        self._log_button_states("_on_automation_start - before invoke/start")
                    except Exception:
                        pass
                    # Mark that this start was automation-initiated so
                    # `start_capture` can skip the demo prompt and then
                    # simulate pressing the visible Start button so any
                    # associated UI wiring runs exactly as a manual click.
                    try:
                        self._suppress_demo_prompt = True
                    except Exception:
                        pass
                    # For automation-initiated starts, call the start routine
                    # directly rather than relying on `invoke()` which may be
                    # ignored if the button widget is disabled. `start_capture`
                    # already handles thread-safety and will update the UI on
                    # success via its `_on_started` handler.
                    try:
                        if not getattr(self, 'engine', None) or not getattr(self.engine, 'running', False):
                            try:
                                self.start_capture()
                                try:
                                    self._log_button_states("_on_automation_start - direct start_capture called")
                                except Exception:
                                    pass
                            except Exception as e:
                                try:
                                    print(f"[UI] _on_automation_start: direct start_capture raised: {e}")
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    finally:
                        try:
                            # clear the flag so manual starts still prompt
                            self._suppress_demo_prompt = False
                        except Exception:
                            pass
                    try:
                        self._log_button_states("_on_automation_start - after invoke/fallback and suppress cleared")
                    except Exception:
                        pass
                except Exception as e:
                    print(f"Error in scheduled automation start: {e}")

            try:
                self.safe_after(0, _do_start)
            except Exception:
                # Fallback: call directly if scheduling fails
                _do_start()
        except Exception as e:
            print(f"Error starting automation: {e}")

    def _on_automation_stop(self):
        """Callback when an automation triggers stop."""
        try:
            # Schedule `stop_capture` on the Tk main thread to avoid
            # manipulating Tk widgets from the scheduler thread.
            def _do_stop():
                try:
                    # Prefer invoking the Stop button so any UI wiring runs
                    # the same as a manual click. Fall back to direct call.
                    try:
                        print("[UI] _do_stop: entered (automation stop handler)")
                    except Exception:
                        pass

                    if hasattr(self, 'stop_btn') and getattr(self.stop_btn, 'invoke', None):
                        try:
                            try:
                                state = self.stop_btn['state']
                            except Exception:
                                state = 'unknown'
                            try:
                                print(f"[UI] _do_stop: about to invoke stop_btn (state={state})")
                            except Exception:
                                pass
                            try:
                                self.stop_btn.invoke()
                            except Exception as e:
                                try:
                                    print(f"[UI] _do_stop: stop_btn.invoke raised: {e}")
                                except Exception:
                                    pass
                                if self.engine and getattr(self.engine, 'running', False):
                                    self.stop_capture()
                        except Exception:
                            # Best-effort fallback
                            if self.engine and getattr(self.engine, 'running', False):
                                self.stop_capture()
                    else:
                        if self.engine and getattr(self.engine, 'running', False):
                            self.stop_capture()

                    # Auto-save transcript if enabled
                    try:
                        if self.auto_save_txt_var.get():
                            self._auto_save_transcript()
                    except Exception as e:
                        print(f"Error in auto-save: {e}")

                    # Update model status to reflect stopped state so user has
                    # a clear visual indication the engine is not running.
                    try:
                        cur = None
                        try:
                            cur = self.model_status_var.get()
                        except Exception:
                            cur = None
                        if cur:
                            if '(stopped)' not in cur:
                                self.model_status_var.set(f"{cur} (stopped)")
                        else:
                            self.model_status_var.set("Model: (stopped)")
                    except Exception:
                        pass

                    # Ensure UI controls are restored regardless of engine state
                    try:
                        self.start_btn.config(state=tk.NORMAL)
                        self.stop_btn.config(state=tk.DISABLED)
                        try:
                            self.device_combo.config(state="readonly")
                        except Exception:
                            try:
                                self.device_combo.config(state=tk.NORMAL)
                            except Exception:
                                pass
                    except Exception:
                        pass

                    try:
                        self._log_button_states("_on_automation_stop restored UI")
                    except Exception:
                        pass

                    # schedule a short check after invoking the stop button to
                    # verify the UI updated; if not, force stop_capture().
                    try:
                        def _check_stop_effect():
                            try:
                                s = self.start_btn['state'] if getattr(self, 'start_btn', None) is not None else 'unknown'
                            except Exception:
                                s = 'unknown'
                            try:
                                t = self.stop_btn['state'] if getattr(self, 'stop_btn', None) is not None else 'unknown'
                            except Exception:
                                t = 'unknown'
                            try:
                                print(f"[UI] _do_stop: post-invoke check start={s} stop={t}")
                            except Exception:
                                pass
                            try:
                                # Diagnose exact values
                                try:
                                    print(f"[UI] _do_stop: post-invoke values repr(s)={repr(s)} type(s)={type(s)} repr(t)={repr(t)} type(t)={type(t)}")
                                except Exception:
                                    pass
                                try:
                                    has_instate = getattr(self.stop_btn, 'instate', None) is not None and getattr(self.start_btn, 'instate', None) is not None
                                except Exception:
                                    has_instate = False
                                try:
                                    if has_instate:
                                        start_ok = not self.start_btn.instate(['disabled'])
                                        stop_ok = self.stop_btn.instate(['disabled'])
                                    else:
                                        start_ok = ('normal' in str(s))
                                        stop_ok = ('disabled' in str(t))
                                except Exception:
                                    start_ok = False
                                    stop_ok = False
                                try:
                                    print(f"[UI] _do_stop: interpreted start_ok={start_ok} stop_ok={stop_ok} engine_running={getattr(self.engine, 'running', False) if getattr(self, 'engine', None) is not None else False}")
                                except Exception:
                                    pass
                                if (not start_ok) or (not stop_ok):
                                    try:
                                        print("[UI] _do_stop: post-invoke check forcing stop_capture()")
                                    except Exception:
                                        pass
                                    try:
                                        self.stop_capture()
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        try:
                            self.safe_after(200, _check_stop_effect)
                        except Exception:
                            pass
                    except Exception:
                        pass

                    # Final safety restore: after a short delay, force UI controls
                    # back to a sane state. This defends against races where the
                    # stop command ran but UI state was not updated due to a timing
                    # issue in some Tk/Ttk environments.
                    try:
                        def _final_restore():
                            try:
                                self.start_btn.config(state=tk.NORMAL)
                                self.stop_btn.config(state=tk.DISABLED)
                                try:
                                    self.device_combo.config(state="readonly")
                                except Exception:
                                    try:
                                        self.device_combo.config(state=tk.NORMAL)
                                    except Exception:
                                        pass
                                try:
                                    self._log_button_states("_on_automation_stop - final_restore")
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        try:
                            self.safe_after(300, _final_restore)
                        except Exception:
                            pass
                    except Exception:
                        pass

                except Exception as e:
                    print(f"Error in scheduled automation stop: {e}")

            try:
                self.safe_after(0, _do_stop)
            except Exception:
                _do_stop()
        except Exception as e:
            print(f"Error stopping automation: {e}")
    
    def _auto_save_transcript(self):
        """Auto-save transcript to default location and clear main tab."""
        try:
            # Get transcript text
            transcript_text = self.transcript.get("1.0", tk.END).strip()
            if not transcript_text:
                return
            
            # Create default directory if needed
            os.makedirs(self.auto_save_txt_path, exist_ok=True)
            
            # Generate filename with timestamp and optionally include show name
            from datetime import datetime
            import re

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Try to get the active show's name from the automation manager (if present)
            show_name = None
            try:
                mgr = getattr(self, 'automation_manager', None)
                active = getattr(mgr, '_active_automation', None) if mgr else None
                if active and getattr(active, 'name', None):
                    show_name = str(active.name).strip()
            except Exception:
                show_name = None

            if show_name:
                # Sanitize show name for a safe filename: remove invalid filesystem chars and replace spaces with underscores
                safe = re.sub(r'[<>:"/\\|?*]', '', show_name)
                safe = safe.strip().replace(' ', '_') or 'transcript'
                base_name = safe
            else:
                base_name = 'transcript'

            filename = os.path.join(self.auto_save_txt_path, f"{base_name}_{timestamp}.txt")
            
            # Save transcript
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(transcript_text)
            
            # Clear transcript in main tab
            self.transcript.delete("1.0", tk.END)
            
            print(f"Auto-saved transcript to: {filename}")
        except Exception as e:
            print(f"Error auto-saving transcript: {e}")

    def _refresh_vocab_list(self):
        self.vocab_listbox.delete(0, tk.END)
        if not getattr(self, 'vocab_mgr', None):
            return
        for w in self.vocab_mgr.list_words():
            self.vocab_listbox.insert(tk.END, w)

    def _refresh_samples_list(self, word: str | None = None):
        try:
            self.samples_listbox.delete(0, tk.END)
        except Exception:
            return
        if not word:
            return
        if not getattr(self, 'vocab_mgr', None):
            return
        for f in self.vocab_mgr.list_samples(word):
            self.samples_listbox.insert(tk.END, f)

    def _on_vocab_selected(self):
        sel = self.vocab_listbox.curselection()
        if not sel:
            return
        w = self.vocab_listbox.get(sel[0])
        if not getattr(self, 'vocab_mgr', None):
            return
        self.vocab_word_var.set(w)
        try:
            self.vocab_pron_var.set(self.vocab_mgr.get_pron(w) or "")
        except Exception:
            self.vocab_pron_var.set("")
        # refresh samples list for this word
        try:
            self._refresh_samples_list(w)
        except Exception:
            pass

    def _on_add_update_vocab(self):
        w = (self.vocab_word_var.get() or "").strip()
        if not w:
            try:
                messagebox.showwarning("Custom Words", "Enter a word to add")
            except Exception:
                pass
            return
        p = (self.vocab_pron_var.get() or "").strip()
        try:
            if self.vocab_mgr:
                self.vocab_mgr.set_word(w, p)
        except Exception as e:
            try:
                messagebox.showerror("Custom Words", f"Failed to save word: {e}")
            except Exception:
                pass
            return
        self._refresh_vocab_list()

    def _on_remove_vocab(self):
        sel = self.vocab_listbox.curselection()
        if not sel:
            try:
                messagebox.showwarning("Custom Words", "Select a word to remove")
            except Exception:
                pass
            return
        w = self.vocab_listbox.get(sel[0])
        try:
            if self.vocab_mgr:
                self.vocab_mgr.remove_word(w)
        except Exception as e:
            try:
                messagebox.showerror("Custom Words", f"Failed to remove word: {e}")
            except Exception:
                pass
            return
        self._refresh_vocab_list()

    # ---------------- audio actions ----------------
    def _start_recording(self):
        # Start streaming from default mic into buffer until stopped
        sel = self.vocab_listbox.curselection()
        if not sel:
            try:
                messagebox.showwarning("Record", "Select a word first")
            except Exception:
                pass
            return
        word = self.vocab_listbox.get(sel[0])
        try:
            import sounddevice as sd
            import numpy as np
        except Exception as e:
            messagebox.showerror("Record", f"Recording requires sounddevice and numpy: {e}")
            return

        if self._recording:
            return
        # disable controls that shouldn't be used while recording
        try:
            self.record_btn.config(state=tk.DISABLED)
            self.play_btn.config(state=tk.DISABLED)
            self.delete_sample_btn.config(state=tk.DISABLED)
            self.vocab_stop_btn.config(state=tk.NORMAL)
            self.audio_status_var.set("Recording...")
        except Exception:
            pass

        self._recording = True
        self._record_buffer = []

        def callback(indata, frames, time, status):
            try:
                # indata is a numpy array of shape (frames, channels)
                self._record_buffer.append(indata.copy())
            except Exception:
                pass

        try:
            # use float32 for broad device compatibility and convert on save
            self._record_stream = sd.InputStream(samplerate=16000, channels=1, dtype='float32', callback=callback)
            self._record_stream.start()
        except Exception as e:
            self._recording = False
            try:
                self.record_btn.config(state=tk.NORMAL)
                self.play_btn.config(state=tk.NORMAL)
                self.delete_sample_btn.config(state=tk.NORMAL)
                self.vocab_stop_btn.config(state=tk.DISABLED)
                self.audio_status_var.set("")
            except Exception:
                pass
            messagebox.showerror("Record", f"Failed to start recording: {e}")
            return

        try:
            # non-blocking status; user will click Stop
            self.audio_status_var.set("Recording... Click Stop to finish.")
        except Exception:
            pass

    def _stop_recording(self):
        if not getattr(self, '_recording', False):
            return
        self._recording = False
        try:
            if getattr(self, '_record_stream', None):
                try:
                    self._record_stream.stop()
                    self._record_stream.close()
                except Exception:
                    pass
                self._record_stream = None
        except Exception:
            pass

        sel = self.vocab_listbox.curselection()
        if not sel:
            return
        word = self.vocab_listbox.get(sel[0])

        # assemble numpy arrays and write WAV to manager folder
        try:
            import numpy as np
            import wave
        except Exception:
            messagebox.showerror("Record", "Missing numpy or wave module")
            return

        try:
            # re-enable/disable buttons appropriately
            try:
                self.record_btn.config(state=tk.NORMAL)
                self.play_btn.config(state=tk.NORMAL)
                self.delete_sample_btn.config(state=tk.NORMAL)
                self.vocab_stop_btn.config(state=tk.DISABLED)
            except Exception:
                pass

            if not self._record_buffer:
                try:
                    messagebox.showwarning("Record", "No audio captured")
                except Exception:
                    pass
                self.audio_status_var.set("")
                return

            arr = np.concatenate(self._record_buffer, axis=0)
            # ensure shape (-1,)
            if arr.ndim > 1:
                arr = arr.reshape(-1)

            # convert float -> int16 if needed
            if np.issubdtype(arr.dtype, np.floating):
                # assume floats in -1.0..1.0 range; clip then scale
                arr = np.clip(arr, -1.0, 1.0)
                int16 = (arr * 32767.0).astype(np.int16)
            elif np.issubdtype(arr.dtype, np.integer):
                # ensure int16
                int16 = arr.astype(np.int16)
            else:
                int16 = arr.astype(np.int16)

            # write to file
            import time as _time
            fname = f"sample_{int(_time.time())}.wav"
            # save to temp file then copy via manager
            tmp = os.path.join(os.getcwd(), fname)
            with wave.open(tmp, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(int16.tobytes())
            # copy into manager
            if self.vocab_mgr:
                dest = self.vocab_mgr.add_sample_from_path(word, tmp)
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                if dest:
                    self._refresh_samples_list(word)
                    try:
                        messagebox.showinfo("Record", "Saved sample: " + dest)
                    except Exception:
                        pass
                else:
                    try:
                        messagebox.showerror("Record", "Failed to save sample into data folder")
                    except Exception:
                        pass
        except Exception as e:
            try:
                messagebox.showerror("Record", f"Failed to save recording: {e}")
            except Exception:
                pass
        finally:
            try:
                self.audio_status_var.set("")
            except Exception:
                pass

    def _play_selected_sample(self):
        selw = self.vocab_listbox.curselection()
        sels = self.samples_listbox.curselection()
        # require at least a sample selection
        if not sels:
            try:
                messagebox.showwarning("Play", "Select a sample to play")
            except Exception:
                pass
            return

        fname = self.samples_listbox.get(sels[0])
        word = None
        # prefer explicit word selection if present
        if selw:
            try:
                word = self.vocab_listbox.get(selw[0])
            except Exception:
                word = None

        path = None
        # if we have a manager and a word, use it
        if getattr(self, 'vocab_mgr', None) and word:
            try:
                path = self.vocab_mgr.sample_path(word, fname)
            except Exception:
                path = None

        # if we don't have a word, try to find which word owns this sample
        if not path and getattr(self, 'vocab_mgr', None):
            try:
                for w in self.vocab_mgr.list_words():
                    if fname in self.vocab_mgr.list_samples(w):
                        word = w
                        path = self.vocab_mgr.sample_path(w, fname)
                        break
            except Exception:
                path = None

        # as a fallback, if the listbox contains an absolute path, play it directly
        if not path:
            try:
                # if fname looks like an absolute path and exists, play that
                if os.path.isabs(fname) and os.path.exists(fname):
                    path = fname
            except Exception:
                pass

        if not path:
            try:
                messagebox.showwarning("Play", "Select a word and a sample to play")
            except Exception:
                pass
            return
        # Play in background so UI stays responsive and disable buttons
        try:
            import sounddevice as sd
            import wave
            import numpy as np
        except Exception as e:
            try:
                messagebox.showerror("Play", f"Playback requires sounddevice and numpy: {e}")
            except Exception:
                pass
            return

        def _player():
            try:
                try:
                    self.record_btn.config(state=tk.DISABLED)
                    self.play_btn.config(state=tk.DISABLED)
                    self.delete_sample_btn.config(state=tk.DISABLED)
                    self.vocab_stop_btn.config(state=tk.DISABLED)
                    self.audio_status_var.set("Playing...")
                except Exception:
                    pass
                with wave.open(path, 'rb') as wf:
                    sr = wf.getframerate()
                    frames = wf.readframes(wf.getnframes())
                # detect sample width
                data = np.frombuffer(frames, dtype=np.int16)
                sd.play(data, samplerate=sr)
                sd.wait()
            except Exception as e:
                try:
                    messagebox.showerror("Play", f"Playback failed: {e}")
                except Exception:
                    pass
            finally:
                try:
                    self.record_btn.config(state=tk.NORMAL)
                    self.play_btn.config(state=tk.NORMAL)
                    self.delete_sample_btn.config(state=tk.NORMAL)
                    self.audio_status_var.set("")
                except Exception:
                    pass

        t = threading.Thread(target=_player, daemon=True)
        t.start()
        self._play_thread = t

    def _delete_selected_sample(self):
        selw = self.vocab_listbox.curselection()
        sels = self.samples_listbox.curselection()
        if not selw or not sels:
            try:
                messagebox.showwarning("Delete", "Select a word and a sample to delete")
            except Exception:
                pass
            return
        word = self.vocab_listbox.get(selw[0])
        fname = self.samples_listbox.get(sels[0])
        if not self.vocab_mgr:
            return
        if not messagebox.askyesno("Delete sample", f"Delete sample '{fname}' for word '{word}'?"):
            return
        try:
            ok = self.vocab_mgr.remove_sample(word, fname)
            if ok:
                self._refresh_samples_list(word)
        except Exception as e:
            try:
                messagebox.showerror("Delete", f"Failed to delete sample: {e}")
            except Exception:
                pass

    def _apply_vocab_to_engine(self):
        # gather word list and call engine.update_vocab
        words = []
        if self.vocab_mgr:
            words = self.vocab_mgr.as_word_list()

        # apply to engine if running
        try:
            if getattr(self, 'engine', None):
                try:
                    self.engine.update_vocab(words)
                    messagebox.showinfo("Custom Words", "Vocabulary applied to running engine.")
                except Exception as e:
                    messagebox.showerror("Custom Words", f"Failed to apply vocabulary: {e}")
            else:
                messagebox.showinfo("Custom Words", "Vocabulary saved. Start the engine and it will use the configured words.")
        except Exception:
            pass

    def _load_vocab_file(self):
        path = filedialog.askopenfilename(title="Load custom vocab (JSON)", filetypes=[('JSON files','*.json'), ('All files','*')])
        if not path:
            return
        try:
            # replace manager if possible
            from custom_vocab import CustomVocabManager
            mgr = CustomVocabManager(path)
            self.vocab_mgr = mgr
            self._refresh_vocab_list()
        except Exception as e:
            try:
                messagebox.showerror("Custom Words", f"Failed to load vocab file: {e}")
            except Exception:
                pass

    def _save_vocab_file(self):
        path = filedialog.asksaveasfilename(title="Save custom vocab (JSON)", defaultextension='.json', filetypes=[('JSON files','*.json'), ('All files','*')])
        if not path:
            return
        try:
            # write a simple dict of word->pron
            if self.vocab_mgr:
                old = self.vocab_mgr.path
                self.vocab_mgr.path = path
                self.vocab_mgr.save()
                self.vocab_mgr.path = old
                messagebox.showinfo("Custom Words", "Saved vocabulary file.")
        except Exception as e:
            try:
                messagebox.showerror("Custom Words", f"Failed to save vocab file: {e}")
            except Exception:
                pass

    def _export_lexicon(self):
        if not getattr(self, 'vocab_mgr', None):
            try:
                messagebox.showwarning("Export Lexicon", "No vocabulary manager available")
            except Exception:
                pass
            return
        lines = self.vocab_mgr.export_lexicon_lines()
        if not lines:
            try:
                messagebox.showinfo("Export Lexicon", "No pronunciations to export")
            except Exception:
                pass
            return
        path = filedialog.asksaveasfilename(title="Export lexicon", defaultextension='.txt', filetypes=[('Text files','*.txt'), ('All files','*')])
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                for ln in lines:
                    f.write(ln + '\n')
            try:
                messagebox.showinfo("Export Lexicon", f"Exported {len(lines)} lines to {path}")
            except Exception:
                pass
        except Exception as e:
            try:
                messagebox.showerror("Export Lexicon", f"Failed to write file: {e}")
            except Exception:
                pass

    def _save_bundle(self):
        """Save settings JSON plus all per-word sample files into a single ZIP bundle."""
        try:
            data = self._save_settings()
        except Exception as e:
            messagebox.showerror("Save Bundle", f"Failed to prepare settings: {e}")
            return

        path = filedialog.asksaveasfilename(title="Save bundle (ZIP)", defaultextension='.zip', filetypes=[('ZIP archive','*.zip')])
        if not path:
            return

        try:
            # create temporary settings JSON text
            settings_json = json.dumps(data, indent=2)
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                # write settings.json at top-level
                zf.writestr('settings.json', settings_json)
                # include per-word sample files from vocab_mgr.data_dir
                if getattr(self, 'vocab_mgr', None):
                    base = getattr(self.vocab_mgr, 'data_dir', None)
                    if base and os.path.isdir(base):
                        for root, dirs, files in os.walk(base):
                            for fn in files:
                                full = os.path.join(root, fn)
                                # store under samples/<relative path from base>
                                rel = os.path.relpath(full, base)
                                arcname = os.path.join('samples', rel).replace('\\', '/')
                                try:
                                    zf.write(full, arcname=arcname)
                                except Exception:
                                    pass
            messagebox.showinfo("Save Bundle", f"Saved bundle to {path}")
        except Exception as e:
            try:
                messagebox.showerror("Save Bundle", f"Failed to write bundle: {e}")
            except Exception:
                pass

    def _clear_vocab(self):
        if not getattr(self, 'vocab_mgr', None):
            return
        if not messagebox.askyesno("Clear custom words", "Remove all custom words? This cannot be undone."):
            return
        try:
            self.vocab_mgr.clear()
            self._refresh_vocab_list()
        except Exception as e:
            try:
                messagebox.showerror("Custom Words", f"Failed to clear words: {e}")
            except Exception:
                pass

    def _add_wavs(self):
        paths = filedialog.askopenfilenames(title="Select WAV files", filetypes=[("WAV files", "*.wav;*.WAV"), ("All files", "*")])
        for p in paths:
            self.wav_listbox.insert(tk.END, p)

    def _create_profile(self):
        name = self.profile_name.get().strip()
        if not name:
            messagebox.showerror("Error", "Please enter a profile name")
            return
        wavs = list(self.wav_listbox.get(0, tk.END))
        if not wavs:
            messagebox.showerror("Error", "Please add at least one WAV file")
            return

        def worker():
            try:
                meta = self.profile_mgr.create_profile(name, wavs)
            except Exception as e:
                self.safe_after(0, lambda: messagebox.showerror("Error", f"Could not create profile: {e}"))
                return
            self.safe_after(0, lambda: self._on_profile_created(meta))

        threading.Thread(target=worker, daemon=True).start()

    def _on_profile_created(self, meta):
        self.profile_status.config(text=f"Created: {meta.get('name')}")
        self.profile_name.delete(0, tk.END)
        self.wav_listbox.delete(0, tk.END)
        self._refresh_profiles_list()

    def _refresh_profiles_list(self):
        self.profiles_box.delete(0, tk.END)
        for p in self.profile_mgr.list_profiles():
            self.profiles_box.insert(tk.END, p)

    def _get_profile_meta(self, name: str) -> dict:
        """Load profile.json for a profile name from the profile manager index."""
        if name not in self.profile_mgr._index:
            raise KeyError(f"Profile '{name}' not found")
        meta = self.profile_mgr._index[name]
        folder = meta.get("folder") or meta.get("slug")
        if not folder:
            raise KeyError("Profile folder missing in index")
        profile_dir = self.profile_mgr.profiles_dir / folder
        profile_meta_path = profile_dir / "profile.json"
        if profile_meta_path.exists():
            try:
                with open(profile_meta_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {"name": name, "source_files": []}
        return {"name": name, "source_files": []}

    def _on_delete_selected(self):
        sel = self.profiles_box.curselection()
        if not sel:
            messagebox.showwarning("Delete Profile", "Select a profile to delete")
            return
        name = self.profiles_box.get(sel[0])
        if not messagebox.askyesno("Delete Profile", f"Delete profile '{name}' and all its files? This cannot be undone."):
            return

        def worker():
            try:
                ok = self.profile_mgr.delete_profile(name)
            except Exception as e:
                self.safe_after(0, lambda: messagebox.showerror("Delete Profile", f"Failed to delete profile: {e}"))
                return
            if ok:
                self.safe_after(0, lambda: [self._refresh_profiles_list(), self.profile_status.config(text=f"Deleted: {name}")])
            else:
                self.safe_after(0, lambda: messagebox.showwarning("Delete Profile", "Profile not found"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_edit_selected(self):
        sel = self.profiles_box.curselection()
        if not sel:
            messagebox.showwarning("Edit Profile", "Select a profile to edit")
            return
        name = self.profiles_box.get(sel[0])
        try:
            meta = self._get_profile_meta(name)
        except Exception as e:
            messagebox.showerror("Edit Profile", f"Failed to load profile: {e}")
            return
        self._open_edit_profile_dialog(name, meta)

    def _on_addwav_selected(self):
        sel = self.profiles_box.curselection()
        if not sel:
            messagebox.showwarning("Add/Change WAVs", "Select a profile to modify")
            return
        name = self.profiles_box.get(sel[0])
        paths = filedialog.askopenfilenames(title="Select WAV files to add/replace", filetypes=[("WAV files", "*.wav;*.WAV"), ("All files", "*")])
        if not paths:
            return
        # Ask whether to replace existing source files or add to them
        replace = messagebox.askyesno("Replace files?", "Replace existing source files with the selected files?\nYes = Replace All, No = Add to existing")

        def worker():
            try:
                if replace:
                    res = self.profile_mgr.edit_profile(name, replace_wav_paths=list(paths))
                else:
                    res = self.profile_mgr.edit_profile(name, add_wav_paths=list(paths))
            except Exception as e:
                self.safe_after(0, lambda: messagebox.showerror("Add/Change WAVs", f"Failed to update profile: {e}"))
                return
            self.safe_after(0, lambda: [self._refresh_profiles_list(), self.profile_status.config(text=f"Updated: {res.get('name')}")])

        threading.Thread(target=worker, daemon=True).start()

    def _open_edit_profile_dialog(self, name: str, meta: dict):
        """Open a modal dialog to rename and manage WAVs for the profile.

        Supports: rename, add wavs, remove selected, replace all wavs.
        """
        dlg = tk.Toplevel(self)
        try:
            dlg.transient(self)
        except Exception:
            pass
        dlg.title(f"Edit Profile: {name}")
        try:
            dlg.grab_set()
        except Exception:
            pass

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        # Name
        ttk.Label(frm, text="Profile Name:").pack(anchor=tk.W)
        name_var = tk.StringVar(value=meta.get('name', name))
        name_entry = ttk.Entry(frm, textvariable=name_var)
        name_entry.pack(fill=tk.X, pady=(0,8))

        # Source files list
        ttk.Label(frm, text="Source WAV files (basename):").pack(anchor=tk.W)
        files_lb = tk.Listbox(frm, height=8)
        files_lb.pack(fill=tk.BOTH, expand=False, pady=(4,6))
        for fn in meta.get('source_files', []):
            files_lb.insert(tk.END, fn)

        file_btn_frm = ttk.Frame(frm)
        file_btn_frm.pack(fill=tk.X)
        def on_add_wavs():
            paths = filedialog.askopenfilenames(title="Select WAV files to add", filetypes=[("WAV files", "*.wav;*.WAV"), ("All files", "*")])
            if not paths:
                return
            for p in paths:
                b = os.path.basename(p)
                if b not in files_lb.get(0, tk.END):
                    files_lb.insert(tk.END, b)

        def on_remove_selected():
            sel = list(files_lb.curselection())
            if not sel:
                return
            for i in reversed(sel):
                files_lb.delete(i)

        def on_replace_all():
            paths = filedialog.askopenfilenames(title="Select WAV files to replace with", filetypes=[("WAV files", "*.wav;*.WAV"), ("All files", "*")])
            if not paths:
                return
            files_lb.delete(0, tk.END)
            for p in paths:
                files_lb.insert(tk.END, os.path.basename(p))
            # store full paths temporarily in dialog object for replace
            dlg._replace_paths = list(paths)

        ttk.Button(file_btn_frm, text="Add WAVs...", command=on_add_wavs).pack(side=tk.LEFT)
        ttk.Button(file_btn_frm, text="Remove Selected", command=on_remove_selected).pack(side=tk.LEFT, padx=(6,4))
        ttk.Button(file_btn_frm, text="Replace All...", command=on_replace_all).pack(side=tk.RIGHT)

        status_lbl = ttk.Label(frm, text="")
        status_lbl.pack(anchor=tk.W, pady=(6,0))

        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill=tk.X, pady=(8,0))

        def on_cancel():
            try:
                dlg.destroy()
            except Exception:
                pass

        def on_save():
            new_name = name_var.get().strip()
            # build add list: we only know basenames in the listbox; prefer to ask user for full paths when adding.
            # For added entries we don't have original full paths (unless replaced via Replace All), so we will
            # treat these as basenames already present in profile dir (no-op) unless user used Add WAVs which
            # also populated basenames only; therefore prefer to prompt for files when adding.

            # Determine which files were removed by comparing to original meta
            new_files = list(files_lb.get(0, tk.END))
            orig_files = meta.get('source_files', [])
            removed = [f for f in orig_files if f not in new_files]

            # If dialog has _replace_paths attribute then user selected Replace All and we will pass replace_wav_paths
            replace_paths = getattr(dlg, '_replace_paths', None)

            # For added files not present in orig, we need full paths. Prompt user to locate them.
            added_basenames = [f for f in new_files if f not in orig_files]
            add_paths = []
            if added_basenames and not replace_paths:
                # Ask user to locate the files they added (match by basename)
                for bn in added_basenames:
                    p = filedialog.askopenfilename(title=f"Locate file for '{bn}'", initialfile=bn, filetypes=[("WAV files", "*.wav;*.WAV"), ("All files", "*")])
                    if p:
                        add_paths.append(p)

            def worker_save():
                try:
                    res = self.profile_mgr.edit_profile(name, new_name=(new_name if new_name != name else None),
                                                         add_wav_paths=(add_paths if add_paths else None),
                                                         remove_wav_filenames=(removed if removed else None),
                                                         replace_wav_paths=(replace_paths if replace_paths else None))
                except Exception as e:
                    self.safe_after(0, lambda: messagebox.showerror("Edit Profile", f"Failed to save profile: {e}"))
                    return
                # refresh UI
                self.safe_after(0, lambda: [self._refresh_profiles_list(), self.profile_status.config(text=f"Updated: {res.get('name')}")])
                try:
                    dlg.destroy()
                except Exception:
                    pass

            threading.Thread(target=worker_save, daemon=True).start()

        ttk.Button(btn_frm, text="Cancel", command=on_cancel).pack(side=tk.RIGHT, padx=(6,0))
        ttk.Button(btn_frm, text="Save", command=on_save).pack(side=tk.RIGHT)

        # center dialog
        try:
            self.update_idletasks()
            dlg.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 2
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Start VAICCS GUI")
    parser.add_argument('--simulate-automation', action='store_true', help='Simulate an automation start/stop for demo purposes')
    args = parser.parse_args()

    app = App(simulate_automation=args.simulate_automation)
    app.mainloop()
