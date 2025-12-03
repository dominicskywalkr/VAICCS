import os
import json
import base64
import datetime
from typing import Dict, Optional, Tuple


def _license_path() -> str:
    # Primary location: same directory as this module
    try:
        base = os.path.abspath(os.path.dirname(__file__))
        return os.path.join(base, 'license.json')
    except Exception:
        return os.path.join(os.getcwd(), 'license.json')


def _candidate_paths():
    """Return candidate paths to look for or save license.json.

    Order: module dir, current working directory, user home directory.
    """
    paths = []
    try:
        base = os.path.abspath(os.path.dirname(__file__))
        paths.append(os.path.join(base, 'license.json'))
    except Exception:
        pass
    try:
        paths.append(os.path.join(os.getcwd(), 'license.json'))
    except Exception:
        pass
    try:
        home = os.path.expanduser('~')
        paths.append(os.path.join(home, '.vaiccs_license.json'))
    except Exception:
        pass
    return paths


def load_license() -> Dict[str, str]:
    """Load license.json if present; return empty dict if missing/invalid."""
    for p in _candidate_paths():
        try:
            if not os.path.exists(p):
                continue
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def save_license(data: Dict[str, str]) -> bool:
    """Write license data to `license.json`. Returns True on success."""
    # Optionally encrypt SKM per-machine if cryptography available and
    # we can compute a machine-specific key. Do not modify caller dict.
    out_data = dict(data) if isinstance(data, dict) else data

    # Try to encrypt license_skm -> license_skm_encrypted with salt
    try:
        if isinstance(out_data, dict) and out_data.get('license_skm'):
            try:
                from licensing.methods import Helpers
            except Exception:
                Helpers = None

            try:
                from cryptography.hazmat.primitives.kdf.hkdf import HKDF
                from cryptography.hazmat.primitives import hashes
                from cryptography.fernet import Fernet
            except Exception:
                HKDF = None
                Fernet = None

            if HKDF and Fernet and Helpers is not None:
                try:
                    mc = Helpers.GetMachineCode(v=2)
                except Exception:
                    mc = None

                if mc:
                    try:
                        salt = os.urandom(16)
                        hk = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b'vaiccs-license')
                        raw = hk.derive(mc.encode('utf-8'))
                        key = base64.urlsafe_b64encode(raw)
                        f = Fernet(key)
                        token = f.encrypt(out_data['license_skm'].encode('utf-8'))
                        out_data.pop('license_skm', None)
                        out_data['license_skm_encrypted'] = token.decode('utf-8')
                        out_data['skm_salt'] = base64.b64encode(salt).decode('utf-8')
                    except Exception:
                        # fall back to plaintext if something goes wrong
                        pass
    except Exception:
        pass

    # Try primary location first, then fall back to cwd and home
    candidates = _candidate_paths()
    last_exc = None
    for p in candidates:
        try:
            d = os.path.dirname(p)
            if d and not os.path.exists(d):
                try:
                    os.makedirs(d, exist_ok=True)
                except Exception:
                    pass
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(out_data, f, indent=2)
            return True
        except Exception as e:
            last_exc = e
            continue
    return False


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
        # Support encrypted SKM (per-machine) as well as plain SKM
        skm = None
        if 'license_skm' in data and data.get('license_skm'):
            skm = data.get('license_skm')
        elif 'license_skm_encrypted' in data and data.get('license_skm_encrypted'):
            # attempt to decrypt using machine code-derived key
            try:
                from licensing.methods import Helpers
            except Exception:
                Helpers = None

            try:
                from cryptography.hazmat.primitives.kdf.hkdf import HKDF
                from cryptography.hazmat.primitives import hashes
                from cryptography.fernet import Fernet
            except Exception:
                HKDF = None
                Fernet = None

            enc = data.get('license_skm_encrypted')
            salt_b64 = data.get('skm_salt')
            if HKDF and Fernet and Helpers is not None and enc and salt_b64:
                try:
                    mc = Helpers.GetMachineCode(v=2)
                    salt = base64.b64decode(salt_b64)
                    hk = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b'vaiccs-license')
                    raw = hk.derive(mc.encode('utf-8'))
                    key = base64.urlsafe_b64encode(raw)
                    f = Fernet(key)
                    skm = f.decrypt(enc.encode('utf-8')).decode('utf-8')
                except Exception:
                    # decryption failed; treat as no valid SKM
                    skm = None

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
