import re
import sys
import os
import json
from typing import Dict, Any

MOD_RE = re.compile(r'''(?xi)
    ^-(?P<key>save|autostart|show_error)  # supported keys
    (?:\s*:\s*
        (?P<val>
            "(?P<dq>[^"]+)" |           # double-quoted
            '(?P<sq>[^']+)'   |           # single-quoted
            (?P<raw>[^\s]+)              # unquoted
        )
    )?$
''')


def parse_modifiers(argv=None) -> Dict[str, Any]:
    """Parse command-line modifiers of the form:
    -save:"settings.json" -autostart:true -show_error

    Returns a dict with keys: 'save' (str|None), 'autostart' (bool|None), 'show_error' (bool|None)
    """
    if argv is None:
        argv = sys.argv[1:]
    out = {'save': None, 'autostart': None, 'show_error': None}
    for a in argv:
        m = MOD_RE.match(a)
        if not m:
            # also accept --key=value or /key:value
            if a.startswith('--') and '=' in a:
                k, v = a[2:].split('=', 1)
                k = k.lower()
                if k in out:
                    if k in ('autostart', 'show_error'):
                        out[k] = _parse_bool(v)
                    else:
                        out[k] = v
            continue
        key = m.group('key').lower()
        val = m.group('dq') or m.group('sq') or m.group('raw')
        if val is None:
            # flag without value -> True for boolean flags
            if key in ('autostart', 'show_error'):
                out[key] = True
            else:
                out[key] = None
            continue
        if key in ('autostart', 'show_error'):
            out[key] = _parse_bool(val)
        else:
            # save value: normalize ~ to user home
            v = val
            if v.startswith('~'):
                v = os.path.expanduser(v)
            out[key] = v
    return out


def _parse_bool(s: str) -> bool:
    s = s.strip().lower()
    return s in ('1', 'true', 'yes', 'y', 'on')


def load_settings_to_app(app, path: str) -> bool:
    """Load a JSON settings file and apply to the given `App` instance.

    Returns True on success.
    """
    if not path:
        return False
    try:
        # resolve relative paths in this order:
        # 1) relative to the exe directory (useful when running frozen exe)
        # 2) current working directory
        # 3) module directory (project root)
        if not os.path.isabs(path):
            tried = []
            try:
                exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                p1 = os.path.join(exe_dir, path)
                tried.append(p1)
                if os.path.exists(p1):
                    path = p1
            except Exception:
                pass
            if path == path and not os.path.isabs(path):
                try:
                    p2 = os.path.join(os.getcwd(), path)
                    tried.append(p2)
                    if os.path.exists(p2):
                        path = p2
                except Exception:
                    pass
            if path == path and not os.path.isabs(path):
                try:
                    base = os.path.abspath(os.path.dirname(__file__))
                    p3 = os.path.join(base, path)
                    tried.append(p3)
                    if os.path.exists(p3):
                        path = p3
                except Exception:
                    pass
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return False

    try:
        # apply subset of settings safely
        model = data.get('model_path')
        if model:
            try:
                if not os.path.isabs(model):
                    base = os.path.abspath(os.path.dirname(__file__))
                    model = os.path.join(base, model)
                model = os.path.abspath(model)
            except Exception:
                pass
            try:
                app.model_path_var.set(model)
            except Exception:
                pass
        try:
            app.cpu_threads_var.set(int(data.get('cpu_threads', app.cpu_threads_var.get())))
        except Exception:
            pass
        try:
            app.serial_enabled_var.set(bool(data.get('serial_enabled', app.serial_enabled_var.get())))
        except Exception:
            pass
        sp = data.get('serial_port')
        if sp:
            try:
                app._saved_serial_device = sp
            except Exception:
                pass
        try:
            app.baud_var.set(int(data.get('baud', app.baud_var.get())))
        except Exception:
            pass
        try:
            app.profile_matching_var.set(bool(data.get('profile_matching', app.profile_matching_var.get())))
        except Exception:
            pass
        try:
            app.profile_threshold_var.set(float(data.get('profile_threshold', app.profile_threshold_var.get())))
        except Exception:
            pass
        try:
            if getattr(app, 'srt_duration_var', None) is None:
                app.srt_duration_var = app.srt_duration_var = __import__('tkinter').DoubleVar()
            app.srt_duration_var.set(float(data.get('srt_caption_duration', app.srt_duration_var.get())))
        except Exception:
            pass
        # bleep settings
        try:
            bm = data.get('bleep_mode')
            btext = data.get('bleep_custom_text')
            bmask = data.get('bleep_mask_char')
            if bm is not None:
                try:
                    app.bleep_mode_var.set(str(bm))
                except Exception:
                    pass
            if btext is not None:
                try:
                    app.bleep_custom_var.set(str(btext))
                except Exception:
                    pass
            if bmask is not None:
                try:
                    app.bleep_mask_var.set(str(bmask))
                except Exception:
                    pass
            try:
                # apply to main module so running engine uses updated settings
                import main as mainmod
                mainmod.BLEEP_SETTINGS = {
                    'mode': str(getattr(app, 'bleep_mode_var', __import__('tkinter').StringVar()).get()),
                    'custom_text': str(getattr(app, 'bleep_custom_var', __import__('tkinter').StringVar()).get()),
                    'mask_char': str(getattr(app, 'bleep_mask_var', __import__('tkinter').StringVar()).get())[:1] or '*'
                }
            except Exception:
                pass
        except Exception:
            pass

        # try to refresh dependent UI
        try:
            app._update_model_status()
        except Exception:
            pass
        try:
            app._update_thread_status()
        except Exception:
            pass
        try:
            app._populate_serial_ports()
        except Exception:
            pass

        # remember current settings file
        try:
            app._current_settings_file = path
        except Exception:
            pass
        
        # Load automations if present in settings (only for commercial licenses)
        try:
            automations_data = data.get('automations')
            # check license status; if non-commercial, do not load automations from settings
            try:
                import license_manager
                is_commercial = (license_manager.license_type() == 'commercial')
            except Exception:
                is_commercial = False

            if automations_data and getattr(app, 'automation_manager', None) and is_commercial:
                from automations import AutomationManager
                app.automation_manager = AutomationManager.from_dict(automations_data)
                app.automation_manager.set_callbacks(
                    on_start=app._on_automation_start,
                    on_stop=app._on_automation_stop
                )
                # Refresh the automations tab UI to show loaded automations
                try:
                    app._refresh_automations_display()
                except Exception:
                    pass
        except Exception:
            pass

        return True
    except Exception:
        return False


def apply_startup_options(app, options: Dict[str, Any]):
    """Apply parsed startup options to the running `App` instance.

    - If options['save'] is provided, load the settings (relative paths resolved).
    - If options['autostart'] is True, call `app.start_capture()` after loading settings.
    - If options['show_error'] is True, enable any verbose error handling where appropriate (no-op here).
    """
    success = False
    if not options:
        return False
    save = options.get('save')
    try:
        if save:
            # respect license: do not allow loading settings via shortcut target in non-commercial mode
            try:
                import license_manager
                is_commercial = (license_manager.license_type() == 'commercial')
            except Exception:
                is_commercial = False

            if is_commercial:
                success = load_settings_to_app(app, save)
            else:
                # ignore save/autoload request in personal/eval mode
                success = False
    except Exception:
        success = False

    # autostart: start model if available
    try:
        if options.get('autostart'):
            # respect license: do not allow autostart via shortcut target in non-commercial mode
            try:
                import license_manager
                is_commercial = (license_manager.license_type() == 'commercial')
            except Exception:
                is_commercial = False

            if is_commercial:
                try:
                    app.start_capture()
                except Exception:
                    pass
            else:
                # ignore autostart in personal/eval mode
                pass
    except Exception:
        pass

    # show_error is handled elsewhere (launcher can display logs if desired)
    return success
