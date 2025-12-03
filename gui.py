import os
import json
import base64
import zipfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import sounddevice as sd
import requests
import tarfile
import shutil
import tempfile
import sys
import re
import queue
from bs4 import BeautifulSoup
from main import CaptionEngine
import main as mainmod
from voice_profiles import VoiceProfileManager
from parse_vosk_headless import parse_vosk_models
from parse_hance_headless import parse_hance_models
import resources
import noise_cancel
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            self._splash = Splash(self, title_text="VAICCS (internal alpha)", creator="Dominic Natoli")
            self._splash.update_status("Starting...")
        except Exception:
            self._splash = None

        # Hide main window while splash shows
        try:
            self.withdraw()
        except Exception:
            pass

        # Set up the main window (kept hidden until splash is closed)
        self.title("VAICCS (internal alpha)")
        self.geometry("900x750")

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
        # whether a bad words file has been loaded for this session (controls menu check)
        self._bad_words_loaded_var = tk.BooleanVar(value=False)
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
        file_menu.add_command(label="Save Settings", accelerator="Ctrl+S", command=lambda: self._on_save_clicked())
        file_menu.add_command(label="Save Settings As...", accelerator="Ctrl+Shift+S", command=lambda: self._on_save_as())
        file_menu.add_command(label="Options...", command=lambda: self._open_options_dialog())
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
        file_menu.add_command(label="Open Settings...", accelerator="Ctrl+O", command=lambda: self._on_open_settings())
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Alt-F4", command=self.quit)
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
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo("About", "VAICCS (Vosk AI Closed Captioning System)\n\nProvides live captions using Vosk (or demo mode).\n\nDeveloped by Dominic Natoli. 2025 \n\nInternal Alpha Build"))
        menubar.add_cascade(label="Help", menu=help_menu)

        try:
            self.config(menu=menubar)
        except Exception:
            # some tkinter variants may not support menu on this platform
            pass

        # Keyboard shortcuts
        try:
            self.bind_all('<Control-s>', lambda e: self._on_save_clicked())
            self.bind_all('<Control-S>', lambda e: self._on_save_as())
            self.bind_all('<Control-Shift-S>', lambda e: self._on_save_as())
            self.bind_all('<Control-o>', lambda e: self._on_open_settings())
            # Alt+F4 is normally handled by the window manager; add binding to ensure menu Exit is called
            try:
                self.bind_all('<Alt-F4>', lambda e: self.quit())
            except Exception:
                pass
        except Exception:
            pass

        try:
            if self._splash:
                self._splash.update_status("Creating UI tabs...")
        except Exception:
            pass

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.main_frame = ttk.Frame(self.notebook)
        self.profiles_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.main_frame, text="Main")
        self.notebook.add(self.profiles_frame, text="Voice Profiles")

        # Custom vocab tab will let users manage runtime vocabulary used to bias Vosk
        self.vocab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.vocab_frame, text="Custom Words")

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

        # Noise cancellation tab (Hance integration)
        self.noise_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.noise_frame, text="Noise Cancelation")

        try:
            if self._splash:
                self._splash.update_status("Building noise cancelation tab...")
        except Exception:
            pass
        self._build_noise_tab()

        self.engine: CaptionEngine | None = None
        # session state for opened/saved settings file (no automatic persistence)
        self._current_settings_file = None
        self._bad_words_path = None

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

        # Right: controls (1/4)
        right = ttk.Frame(self.main_frame, width=250)
        right.pack(side=tk.RIGHT, fill=tk.Y)

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
        # Model status label
        self.model_status_var = tk.StringVar(value="Model: (not selected) - Demo mode")
        ttk.Label(right, textvariable=self.model_status_var, wraplength=220).pack(padx=8, pady=(6, 0), anchor=tk.W)
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
        self.profile_matching_var = tk.BooleanVar(value=True)
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
        

        ttk.Label(right, text="Audio Input:").pack(pady=(20, 6), padx=8, anchor=tk.W)
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
            elif script_dir and not _is_under_tmp(script_dir):
                chosen = script_dir
            elif exe_dir and not _is_under_tmp(exe_dir):
                chosen = exe_dir
            else:
                # Use LOCALAPPDATA if available for a persistent per-user folder
                local = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
                if local:
                    chosen = os.path.join(local, 'VAICCS')
                else:
                    chosen = exe_dir

            # Save the resolved application root path and models folder location.
            # We prefer `script_dir` when running from source (e.g., in VS Code) so
            # that models install next to the repository rather than under Python's
            # interpreter installation directory (e.g. AppData/Local/Programs/Python).
            self.app_root = os.path.abspath(chosen)
            self.models_root = os.path.join(self.app_root, 'models')
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
                self.models_root = os.path.join(exe_app_root, 'models')
            except Exception:
                try:
                    script_app_root = os.path.abspath(os.path.dirname(__file__))
                    self.app_root = script_app_root
                    self.models_root = os.path.join(script_app_root, 'models')
                except Exception:
                    # final fallback: use current working directory
                    self.app_root = os.path.abspath(os.getcwd())
                    self.models_root = os.path.join(self.app_root, 'models')
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
            self.transcript.bind('<Button-4>', self._on_user_scroll)
            self.transcript.bind('<Button-5>', self._on_user_scroll)
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
            self.serial_manager = None
            self.serial_status_var.set("Serial: disabled")
            # no automatic persistence
            return

        # connect
        if not port:
            messagebox.showwarning("Serial", "Select a COM port first")
            self.serial_enabled_var.set(False)
            return

        if SerialManager is None:
            messagebox.showerror("Serial", "Serial support not available (pyserial or helper missing)")
            self.serial_enabled_var.set(False)
            return

        try:
            self.serial_manager = SerialManager(port, baud)
            self.serial_manager.open()
            self.serial_status_var.set(f"Serial: connected {port}@{baud}")
        except Exception as e:
            self.serial_manager = None
            self.serial_status_var.set(f"Serial error: {e}")
            messagebox.showerror("Serial", f"Failed to open serial port: {e}")
            self.serial_enabled_var.set(False)
        # no automatic persistence

    #send a test line over serial button
    def _send_test_serial(self):
        try:
            if not self.serial_manager:
                messagebox.showwarning("Serial", "Not connected")
                return
            self.serial_manager.send_line("TEST: Hello from Caption GUI")
            messagebox.showinfo("Serial", "Test sent")
        except Exception as e:
            messagebox.showerror("Serial", f"Serial send failed: {e}")

    def _browse_model(self):
        path = filedialog.askdirectory(title="Select VOSK model directory")
        if path:
            self.model_path_var.set(path)
            self._update_model_status()

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

            data = {"model_path": self.model_path_var.get().strip(), "cpu_threads": int(self.cpu_threads_var.get()),
                    "serial_enabled": bool(self.serial_enabled_var.get()),
                    "serial_port": device_name,
                    "baud": int(self.baud_var.get()),
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
            # Convert file paths to relative when they sit under the project root
            try:
                base = os.path.abspath(os.path.dirname(__file__))
                def _maybe_rel(p):
                    if not p:
                        return ''
                    try:
                        full = os.path.abspath(p)
                        # normalize for case-insensitive filesystems
                        base_n = os.path.normcase(base)
                        full_n = os.path.normcase(full)
                        if full_n == base_n or full_n.startswith(base_n + os.sep):
                            return os.path.relpath(full, base).replace('\\', '/')
                        return full
                    except Exception:
                        return p

                # apply to known path-like keys
                if 'model_path' in data:
                    data['model_path'] = _maybe_rel(data.get('model_path', ''))
                if 'custom_vocab_data_dir' in data:
                    data['custom_vocab_data_dir'] = _maybe_rel(data.get('custom_vocab_data_dir', ''))
                if 'bad_words' in data:
                    data['bad_words'] = _maybe_rel(data.get('bad_words', ''))
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
            path = filedialog.askopenfilename(title="Open Settings", filetypes=[("JSON files", "*.json"), ("All files", "*")])
            if not path:
                return
            # load settings from chosen file (session only — no automatic persistence)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                try:
                    messagebox.showerror("Open Settings", f"Failed to read settings: {e}")
                except Exception:
                    pass
                return

            # apply settings to UI (do not write to disk automatically)
            try:
                # Resolve potentially relative paths saved against project root
                base = os.path.abspath(os.path.dirname(__file__))
                model = data.get("model_path")
                if model:
                    try:
                        if not os.path.isabs(model):
                            model = os.path.join(base, model)
                        model = os.path.abspath(model)
                    except Exception:
                        pass
                    self.model_path_var.set(model)
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
                        # resolve relative bad_words path
                        try:
                            if not os.path.isabs(bw_path):
                                bw_path = os.path.join(base, bw_path)
                            bw_path = os.path.abspath(bw_path)
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
                                    # resolve relative custom data dir against project root
                                    try:
                                        if not os.path.isabs(dd):
                                            dd = os.path.join(base, dd)
                                        dd = os.path.abspath(dd)
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
            try:
                dlg.destroy()
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
                    self.after(0, lambda: status_var.set(status))
                finally:
                    def ui_done():
                        progress.stop()
                        progress.config(mode='determinate', value=0)
                        _clear_models_view()
                        langs = sorted(models_by_lang.keys())
                        _populate_languages(langs)
                        status_var.set(f"Loaded {sum(len(v) for v in models_by_lang.values())} models across {len(langs)} languages")
                    self.after(0, ui_done)

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
            if not messagebox.askyesno('Download', f"Download and install model '{name}' to application root? This may be large."):
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
                # Not writeable -> try per-user LocalAppData path as a fallback
                try:
                    local = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
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
                                    self.after(0, lambda: status_var.set('Download cancelled'))
                                    return
                                if not chunk:
                                    continue
                                outf.write(chunk)
                                written += len(chunk)
                                if total:
                                    pct = int(written * 100 / total)
                                else:
                                    pct = 0
                                self.after(0, lambda p=pct: progress.config(value=p))
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
                    self.after(0, lambda: status_var.set(status))
                    extract_to = dest_dir
                    try:
                        self._extract_archive(dest_path, extract_to)
                    except Exception as e:
                        self.after(0, lambda: messagebox.showerror('Vosk Models', f'Extraction failed: {e}'))
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
                        self.after(0, lambda: [self.model_path_var.set(target), self._update_model_status(), status_var.set(f'Installed: {os.path.basename(target)}')])
                    else:
                        self.after(0, lambda: status_var.set('Extraction complete but model folder not found; please browse manually'))
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror('Vosk Models', f'Download failed: {e}'))
                    self.after(0, lambda: status_var.set('Download failed'))
                finally:
                    # clear cancel event and thread
                    try:
                        self._model_download_thread = None
                        if self._model_download_cancel_event is not None:
                            self._model_download_cancel_event = None
                    except Exception:
                        pass
                    self.after(0, lambda: progress.config(value=0))

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
            self.after(0, lambda: [self.model_path_var.set(target), self._update_model_status(), status_var.set(f'Selected installed: {os.path.basename(target)}'), dlg.destroy()])

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
                    self.after(0, lambda: status_var.set(f"Failed to fetch models: {e}"))
                finally:
                    def ui_done():
                        progress.stop()
                        progress.config(mode='determinate', value=0)
                        _clear_models_view()
                        _populate_models()
                        status_var.set(f"Loaded {len(models_list)} Hance model(s)")
                    self.after(0, ui_done)

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
                                    self.after(0, lambda: status_var.set('Download cancelled'))
                                    return
                                if not chunk:
                                    continue
                                outf.write(chunk)
                                written += len(chunk)
                                if total:
                                    pct = int(written * 100 / total)
                                else:
                                    pct = 0
                                self.after(0, lambda p=pct: progress.config(value=p))
                        try:
                            os.replace(tmp_path, dest_path)
                        except Exception:
                            shutil.move(tmp_path, dest_path)
                    # extraction if archive
                    status = 'Download complete. Extracting if needed...'
                    self.after(0, lambda: status_var.set(status))
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
                        self.after(0, lambda: [self.hance_model_var.set(found), status_var.set(f'Installed: {os.path.basename(found)}')])
                    else:
                        self.after(0, lambda: status_var.set('Installed but model file not found; please browse manually'))
                        try:
                            _hlog(f"Model install not found after download. dest_dir={dest_dir}, fname={fname}, name={name}")
                            _hlog(f"Models dir listing: {list(os.listdir(dest_dir))}")
                        except Exception:
                            pass
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror('Hance Models', f'Download failed: {e}'))
                    self.after(0, lambda: status_var.set('Download failed'))
                finally:
                    try:
                        self._model_download_thread = None
                        if self._model_download_cancel_event is not None:
                            self._model_download_cancel_event = None
                    except Exception:
                        pass
                    self.after(0, lambda: progress.config(value=0))

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
            self.after(0, lambda: [self.hance_model_var.set(target), self.noise_status_var.set(f"Installed (model:{os.path.basename(target)})"), dlg.destroy()])

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
                        self.after(0, lambda: on_error("cancelled"))
                    return

                # otherwise notify success on main thread
                if on_started:
                    self.after(0, lambda: on_started())
            except Exception as e:
                # pass exception message to UI thread
                if on_error:
                    self.after(0, lambda: on_error(str(e)))
                else:
                    try:
                        self.after(0, lambda: messagebox.showerror("Engine start failed", str(e)))
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

        if self.engine and getattr(self.engine, "_thread", None) and self.engine._thread.is_alive():
            return
        # Determine model selection
        model_path = self.model_path_var.get().strip()
        demo = False
        cpu_threads = int(self.cpu_threads_var.get() or 0)
        if not model_path or not os.path.isdir(model_path) or not self._is_valid_model(model_path):
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
            model_path=model_path if not demo else None,
            demo=demo,
            cpu_threads=(cpu_threads if cpu_threads > 0 else None),
            enable_profile_matching=bool(self.profile_matching_var.get()),
            profile_match_threshold=float(self.profile_threshold_var.get()),
        )

        # Show a modal loading dialog and start the engine in a background thread
        try:
            dlg, pb, cancel_evt = self._show_loading_dialog(title="Loading model", text=(f"Loading: {os.path.basename(model_path)}\nThis may take a few minutes..." if model_path else "Starting demo mode..."))
        except Exception:
            dlg = None
            pb = None
            cancel_evt = None

        def _on_started():
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
                self.engine = None
            except Exception:
                pass

        # start engine asynchronously; _start_engine_async will call engine.start()
        self._start_engine_async(self.engine, on_started=_on_started, on_error=_on_error, cancel_event=cancel_evt)

    def stop_capture(self):
        if self.engine:
            self.engine.stop()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.device_combo.config(state="readonly")

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
                return

            self.transcript.insert(tk.END, text + "\n")
            try:
                # auto-scroll to the end so new captions are visible (if enabled)
                if getattr(self, 'auto_scroll_var', None) and self.auto_scroll_var.get():
                    self.transcript.see(tk.END)
            except Exception:
                pass

            # forward to serial if enabled
            try:
                if getattr(self, 'serial_manager', None) and getattr(self, 'serial_enabled_var', None) and self.serial_enabled_var.get():
                    try:
                        self.serial_manager.send_line(text)
                    except Exception as e:
                        self.serial_status_var.set(f"Serial send error: {e}")
            except Exception:
                pass

        try:
            self.after(0, _handle)
        except RuntimeError:
            # No Tk main loop is running (headless test). Call handler directly
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
        ttk.Label(left, text="Hance model file: (optional)").pack(anchor=tk.W, pady=(8,2))
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
                self.after(0, lambda: messagebox.showerror("Error", f"Could not create profile: {e}"))
                return
            self.after(0, lambda: self._on_profile_created(meta))

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
                self.after(0, lambda: messagebox.showerror("Delete Profile", f"Failed to delete profile: {e}"))
                return
            if ok:
                self.after(0, lambda: [self._refresh_profiles_list(), self.profile_status.config(text=f"Deleted: {name}")])
            else:
                self.after(0, lambda: messagebox.showwarning("Delete Profile", "Profile not found"))

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
                self.after(0, lambda: messagebox.showerror("Add/Change WAVs", f"Failed to update profile: {e}"))
                return
            self.after(0, lambda: [self._refresh_profiles_list(), self.profile_status.config(text=f"Updated: {res.get('name')}")])

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
                    self.after(0, lambda: messagebox.showerror("Edit Profile", f"Failed to save profile: {e}"))
                    return
                # refresh UI
                self.after(0, lambda: [self._refresh_profiles_list(), self.profile_status.config(text=f"Updated: {res.get('name')}")])
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
    app = App()
    app.mainloop()
