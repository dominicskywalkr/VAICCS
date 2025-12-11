import os
import sys
import json
import base64
import datetime
from typing import Dict, Optional, Tuple


def _is_pyinstaller_bundle():
    """Check if running inside a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def _get_writable_data_dir():
    """Get a writable directory for application data.
    
    Priority:
    1. For PyInstaller: APPDATA/VAICCS or home/.vaiccs
    2. For dev: module directory if writable, else cwd, else home
    """
    try:
        # Check if we're in a PyInstaller bundle
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # PyInstaller bundle - use user's local app data or home directory
            try:
                # Try APPDATA\VAICCS first (Windows)
                appdata = os.environ.get('APPDATA')
                if appdata:
                    vaiccs_dir = os.path.join(appdata, 'VAICCS')
                    os.makedirs(vaiccs_dir, exist_ok=True)
                    return vaiccs_dir
            except Exception:
                pass
            
            # Fallback to home directory
            try:
                home = os.path.expanduser('~')
                vaiccs_dir = os.path.join(home, '.vaiccs')
                os.makedirs(vaiccs_dir, exist_ok=True)
                return vaiccs_dir
            except Exception:
                pass
    except Exception:
        pass
    
    # Development mode: try module dir, cwd, then home
    try:
        base = os.path.abspath(os.path.dirname(__file__))
        if os.access(base, os.W_OK):
            return base
    except Exception:
        pass
    
    try:
        cwd = os.getcwd()
        if os.access(cwd, os.W_OK):
            return cwd
    except Exception:
        pass
    
    try:
        home = os.path.expanduser('~')
        if os.access(home, os.W_OK):
            return home
    except Exception:
        pass
    
    return os.getcwd()


def _license_path() -> str:
    # Get writable data directory
    data_dir = _get_writable_data_dir()
    return os.path.join(data_dir, 'license.json')


def _module_license_path() -> str:
    """Return license path in the module/project directory (for dev mode)."""
    try:
        base = os.path.abspath(os.path.dirname(__file__))
        return os.path.join(base, 'license.json')
    except Exception:
        return os.path.join(os.getcwd(), 'license.json')


def _log_message(msg: str) -> None:
    """Append a short timestamped message to a license debug log in the
    writable data directory. Best-effort; never raise."""
    try:
        d = _get_writable_data_dir()
        if not d:
            return
        lf = os.path.join(d, 'license_debug.log')
        ts = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
        with open(lf, 'a', encoding='utf-8') as f:
            f.write(f"{ts} - {msg}\n")
    except Exception:
        # never fail
        pass


def _candidate_paths():
    """Return candidate paths to search for existing license.json.
    
    Order: writable data dir, module dir, current working directory, home directory.
    """
    paths = []
    
    # Always check the primary writable location first
    try:
        data_dir = _get_writable_data_dir()
        paths.append(os.path.join(data_dir, 'license.json'))
    except Exception:
        pass
    
    # Then check module directory
    try:
        base = os.path.abspath(os.path.dirname(__file__))
        paths.append(os.path.join(base, 'license.json'))
    except Exception:
        pass
    
    # Then check current working directory
    try:
        paths.append(os.path.join(os.getcwd(), 'license.json'))
    except Exception:
        pass
    
    # Legacy locations for backward compatibility
    try:
        home = os.path.expanduser('~')
        paths.append(os.path.join(home, '.vaiccs_license.json'))
        paths.append(os.path.join(home, '.vaiccs', 'license.json'))
    except Exception:
        pass
    
    # Also check APPDATA/VAICCS for cases where user previously ran a bundled
    # (PyInstaller) build which writes into %APPDATA% even when current run
    # is the unpacked/dev version.
    try:
        appdata = os.environ.get('APPDATA')
        if appdata:
            paths.insert(0, os.path.join(appdata, 'VAICCS', 'license.json'))
    except Exception:
        pass
    
    return paths


def load_license() -> Dict[str, str]:
    """Load license.json if present; return empty dict if missing/invalid.

    Migration behavior: if a license exists in the module (project) directory
    but not the primary writable data directory, copy it into the primary
    location so both bundled and dev runs find the same file.
    """
    primary = _license_path()
    module_p = _module_license_path()

    # Try primary first
    try:
        if os.path.exists(primary):
            with open(primary, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _log_message(f"load_license: loaded primary: {primary}")
                    return data
    except Exception:
        _log_message(f"load_license: failed to load primary: {primary}")
        pass

    # If primary missing, try module path and migrate it to primary
    try:
        if module_p and os.path.exists(module_p):
            try:
                with open(module_p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = None
            if isinstance(data, dict):
                _log_message(f"load_license: found module copy: {module_p}; migrating to primary: {primary}")
                try:
                    d = os.path.dirname(primary)
                    if d and not os.path.exists(d):
                        os.makedirs(d, exist_ok=True)
                    tmp = primary + '.tmp'
                    with open(tmp, 'w', encoding='utf-8') as pf:
                        json.dump(data, pf, indent=2)
                    try:
                        os.replace(tmp, primary)
                        _log_message(f"load_license: migrated module copy into primary: {primary}")
                    except Exception:
                        _log_message(f"load_license: failed atomic replace during migration to primary: {primary}")
                        try:
                            os.remove(primary)
                        except Exception:
                            pass
                        try:
                            os.replace(tmp, primary)
                        except Exception:
                            _log_message(f"load_license: fallback replace also failed for primary: {primary}")
                except Exception:
                    _log_message(f"load_license: migration to primary raised exception for: {primary}")
                return data
    except Exception:
        _log_message(f"load_license: error while reading module copy: {module_p}")
        pass

    # Fallback to scanning candidate paths (legacy)
    # If primary existed but was corrupted/truncated, try to find a valid
    # copy elsewhere (e.g., APPDATA) and migrate it into primary.
    for p in _candidate_paths():
        try:
            if not os.path.exists(p):
                continue
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _log_message(f"load_license: loaded candidate: {p}")
                    # migrate into primary if needed
                    try:
                        # Overwrite primary (even if it exists) so a corrupt primary
                        # file is repaired by a valid candidate copy found elsewhere.
                        d = os.path.dirname(primary)
                        if d and not os.path.exists(d):
                            os.makedirs(d, exist_ok=True)
                        tmp = primary + '.tmp'
                        with open(tmp, 'w', encoding='utf-8') as pf:
                            json.dump(data, pf, indent=2)
                        try:
                            os.replace(tmp, primary)
                            _log_message(f"load_license: migrated candidate {p} into primary: {primary}")
                        except Exception:
                            _log_message(f"load_license: failed atomic replace while migrating candidate {p} to primary {primary}")
                    except Exception:
                        _log_message(f"load_license: migration attempt raised for candidate {p}")
                    return data
        except Exception:
            _log_message(f"load_license: failed to read candidate: {p}")
            continue
    return {}


def save_license(data: Dict[str, str]) -> bool:
    """Write license data to `license.json`. Returns True on success."""
    # Keep the plaintext SKM for reliable loading across restarts.
    # The SKM is already cryptographically signed by Cryptolens, so additional
    # encryption is not necessary. Machine-code dependent encryption can fail
    # on restart if machine code changes even slightly.
    out_data = dict(data) if isinstance(data, dict) else data

    # Save to the primary writable location (authoritative) using atomic write
    success_primary = False
    try:
        p = _license_path()
        d = os.path.dirname(p)
        if d and not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(out_data, f, indent=2)
        try:
            os.replace(tmp, p)
            success_primary = True
            _log_message(f"save_license: wrote primary: {p}")
        except Exception:
            # best-effort: try to remove and replace
            _log_message(f"save_license: atomic replace failed for primary: {p}")
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
            try:
                os.replace(tmp, p)
                success_primary = True
                _log_message(f"save_license: fallback replace succeeded for primary: {p}")
            except Exception:
                success_primary = False
                _log_message(f"save_license: fallback replace failed for primary: {p}")
    except Exception:
        success_primary = False
        _log_message(f"save_license: exception while writing primary: {_license_path()}")

    # Also attempt to write a copy into the module directory (best-effort)
    try:
        module_p = _module_license_path()
        if module_p and os.path.abspath(module_p) != os.path.abspath(_license_path()):
            try:
                md = os.path.dirname(module_p)
                if md and not os.path.exists(md):
                    os.makedirs(md, exist_ok=True)
                tmpm = module_p + '.tmp'
                with open(tmpm, 'w', encoding='utf-8') as mf:
                    json.dump(out_data, mf, indent=2)
                try:
                    os.replace(tmpm, module_p)
                    _log_message(f"save_license: wrote module copy: {module_p}")
                except Exception:
                    _log_message(f"save_license: failed atomic replace for module copy: {module_p}")
                    try:
                        if os.path.exists(module_p):
                            os.remove(module_p)
                    except Exception:
                        pass
                    try:
                        os.replace(tmpm, module_p)
                        _log_message(f"save_license: fallback replace succeeded for module copy: {module_p}")
                    except Exception:
                        _log_message(f"save_license: fallback replace failed for module copy: {module_p}")
            except Exception:
                _log_message(f"save_license: exception while writing module copy: {module_p}")
    except Exception:
        pass

    # Also write to APPDATA/VAICCS if available (best-effort)
    try:
        appdata = os.environ.get('APPDATA')
        if appdata:
            ap = os.path.join(appdata, 'VAICCS', 'license.json')
            if os.path.abspath(ap) != os.path.abspath(_license_path()):
                try:
                    ad = os.path.dirname(ap)
                    if ad and not os.path.exists(ad):
                        os.makedirs(ad, exist_ok=True)
                    tm = ap + '.tmp'
                    with open(tm, 'w', encoding='utf-8') as af:
                        json.dump(out_data, af, indent=2)
                    try:
                        os.replace(tm, ap)
                        _log_message(f"save_license: wrote APPDATA copy: {ap}")
                    except Exception:
                        _log_message(f"save_license: failed atomic replace for APPDATA copy: {ap}")
                        try:
                            if os.path.exists(ap):
                                os.remove(ap)
                        except Exception:
                            pass
                        try:
                            os.replace(tm, ap)
                            _log_message(f"save_license: fallback replace succeeded for APPDATA copy: {ap}")
                        except Exception:
                            _log_message(f"save_license: fallback replace failed for APPDATA copy: {ap}")
                except Exception:
                    _log_message(f"save_license: exception while writing APPDATA copy: {ap}")
    except Exception:
        pass

    return success_primary


def clear_license() -> None:
    try:
        p = _license_path()
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def license_type() -> str:
    """Return 'commercial' or 'personal' or '' if not present."""
    data = load_license()
    t = data.get('type', '') if isinstance(data, dict) else ''
    if t not in ('commercial', 'personal'):
        return ''
    return t


def load_license_key_from_saved(pubkey: str, v: int = 2):
    """If a saved license contains a SKM string, return a licensing LicenseKey.

    Returns the LicenseKey object on success, or None on failure.
    """
    try:
        data = load_license()
        if not data or not isinstance(data, dict):
            return None
        
        # Prefer plaintext SKM for reliability across restarts
        skm = None
        if 'license_skm' in data and data.get('license_skm'):
            skm = data.get('license_skm')

        if not skm:
            return None
        
        # Import here to avoid hard dependency when not used
        try:
            from licensing.models import LicenseKey
        except Exception:
            return None
        
        # load_from_string signature: LicenseKey.load_from_string(pubkey, skm_string, [max_days])
        try:
            lk = LicenseKey.load_from_string(pubkey, skm)
            return lk
        except TypeError:
            # older/newer versions may accept parameters differently
            try:
                lk = LicenseKey.load_from_string(pubkey, skm, v)
                return lk
            except Exception:
                return None
        except Exception:
            return None
    except Exception:
        return None


def validate_saved_license(pubkey: str, v: int = 2, require_machine_check: bool = True) -> Tuple[bool, str]:
    """Validate the locally saved license offline.

        - Checks signature by attempting to load the SKM string with `pubkey`.
    - If `require_machine_check` is True, enforce node-locking when the
      license has activated machines or a max_no_of_machines > 0.
    - Checks expiry via `Helpers.HasNotExpired`.
    - Checks expiry with grace period.

    Returns (True, '') when valid, or (False, message) on failure.
    """
    try:
        lk = load_license_key_from_saved(pubkey, v=v)
        if lk is None:
            return (False, 'No valid saved license found or signature check failed.')

        # Import Helpers lazily
        try:
            from licensing.methods import Helpers
        except Exception:
            return (False, 'Cryptolens SDK (licensing) not available.')

        # expiry check with grace period
        try:
            expires = getattr(lk, 'expires', None)
            if expires is not None:
                # ensure timezone-aware comparison; assume expires is aware or naive as UTC
                now = datetime.datetime.now(datetime.timezone.utc)
                try:
                    if expires.tzinfo is None:
                        # treat as UTC
                        expires_dt = expires.replace(tzinfo=datetime.timezone.utc)
                    else:
                        expires_dt = expires
                except Exception:
                    expires_dt = expires

                # valid if now <= expires_dt OR within grace_days after expiry
                if now <= expires_dt:
                    pass
                else:
                    grace_limit = expires_dt + datetime.timedelta(days=3)
                    if now <= grace_limit:
                        # within grace period: accept but warn
                        return (True, f'License expired but within 3-day grace period.')
                    else:
                        return (False, 'License has expired.')
            else:
                # no expiry information; continue
                pass
        except Exception:
            # if expiry cannot be determined, fail safe and mark invalid
            return (False, 'Could not determine license expiry.')

        # machine check: only enforce if license actually has machine locking
        try:
            max_machines = getattr(lk, 'max_no_of_machines', None)
            activated = getattr(lk, 'activated_machines', None)
            if require_machine_check and ( (max_machines and int(max_machines) > 0) or (activated and len(activated) > 0) ):
                if not Helpers.IsOnRightMachine(lk, v=v):
                    return (False, 'License not valid on this machine.')
        except Exception:
            # if machine check fails unexpectedly, be conservative and mark invalid
            return (False, 'Machine-check failed during validation.')

        return (True, '')
    except Exception as ex:
        return (False, f'Validation failed: {ex}')


def get_saved_license_status(pubkey: str, v: int = 2, require_machine_check: bool = True) -> dict:
    """Return detailed status about the saved license.

    Returns a dict with keys:
      - status: one of 'invalid', 'trial', 'subscription', 'perpetual'
      - f1,f2,f3: booleans for feature flags
      - expires: datetime or None
      - max_no_of_machines: int or None
      - activated_machines: list or None
      - machine_ok: bool or None (None if not checked)
      - message: diagnostic string when invalid

    This helps the app decide how to treat saved licenses (your mapping:
    f1=trial, f2=subscription, f3=perpetual).
    """
    out = {
        'status': 'invalid',
        'f1': False,
        'f2': False,
        'f3': False,
        'expires': None,
        'max_no_of_machines': None,
        'activated_machines': None,
        'machine_ok': None,
        'message': ''
    }
    try:
        lk = load_license_key_from_saved(pubkey, v=v)
        if lk is None:
            out['message'] = 'No saved license or signature check failed.'
            return out

        # populate feature flags and expiration
        out['f1'] = bool(getattr(lk, 'f1', False))
        out['f2'] = bool(getattr(lk, 'f2', False))
        out['f3'] = bool(getattr(lk, 'f3', False))
        out['expires'] = getattr(lk, 'expires', None)
        out['max_no_of_machines'] = getattr(lk, 'max_no_of_machines', None)
        out['activated_machines'] = getattr(lk, 'activated_machines', None)

        # signature already implicitly verified by load_from_string; now expiry
        try:
            from licensing.methods import Helpers
        except Exception:
            Helpers = None

        if Helpers is not None:
            try:
                out['machine_ok'] = None
                # only perform machine check when required and license uses locking
                if require_machine_check:
                    max_m = out['max_no_of_machines']
                    activated = out['activated_machines']
                    if (max_m and int(max_m) > 0) or (activated and len(activated) > 0):
                        out['machine_ok'] = Helpers.IsOnRightMachine(lk, v=v)
                    else:
                        # machine locking not enforced
                        out['machine_ok'] = True
            except Exception:
                out['machine_ok'] = False

            try:
                expires = getattr(lk, 'expires', None)
                if expires is not None:
                    now = datetime.datetime.now(datetime.timezone.utc)
                    try:
                        if expires.tzinfo is None:
                            expires_dt = expires.replace(tzinfo=datetime.timezone.utc)
                        else:
                            expires_dt = expires
                    except Exception:
                        expires_dt = expires

                    if now <= expires_dt:
                        # valid
                        pass
                    else:
                        grace_limit = expires_dt + datetime.timedelta(days=3)
                        if now <= grace_limit:
                            out['message'] = f'License expired but within 3-day grace period.'
                            # do not mark invalid; leave status based on features
                        else:
                            out['message'] = 'License expired.'
                            out['status'] = 'invalid'
                            return out
                else:
                    # cannot determine expiry; continue
                    pass
            except Exception:
                out['message'] = 'Could not determine expiry.'

        # Decide status by your mapping: f1=trial, f2=subscription, f3=perpetual
        if out['f1']:
            out['status'] = 'trial'
        elif out['f2']:
            out['status'] = 'subscription'
        elif out['f3']:
            out['status'] = 'perpetual'
        else:
            # no known features set; treat as invalid
            out['status'] = 'invalid'
            out['message'] = out.get('message') or 'No known license features set.'

        return out
    except Exception as ex:
        out['message'] = f'Error inspecting saved license: {ex}'
        return out
