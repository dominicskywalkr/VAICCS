import os
import sys
import shutil
import json

def _resource_path(relpath: str) -> str:
    """Resolve a resource file path similar to the logic used elsewhere.

    Preference order:
    1) directory of the launched executable
    2) current working directory
    3) PyInstaller extraction folder (sys._MEIPASS)
    4) module directory
    """
    try:
        exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        p = os.path.join(exe_dir, relpath)
        if os.path.exists(p):
            return p
    except Exception:
        pass

    try:
        p = os.path.join(os.getcwd(), relpath)
        if os.path.exists(p):
            return p
    except Exception:
        pass

    try:
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            p = os.path.join(meipass, relpath)
            if os.path.exists(p):
                return p
    except Exception:
        pass

    try:
        p = os.path.join(os.path.dirname(__file__), relpath)
        return p
    except Exception:
        return relpath


def get_user_data_dir(app_name: str = "ClosedCaptioning") -> str:
    try:
        if sys.platform.startswith('win'):
            base = os.getenv('APPDATA') or os.getenv('LOCALAPPDATA') or os.path.expanduser('~')
        elif sys.platform == 'darwin':
            base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
        else:
            base = os.getenv('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    except Exception:
        base = os.path.expanduser('~')
    path = os.path.join(base, app_name)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def get_vaiccs_root() -> str:
    """Return the platform-appropriate VAICCS root folder.

    On macOS this is: ~/Documents/VAICCS
    On Windows this will prefer %LOCALAPPDATA%/VAICCS or %APPDATA%/VAICCS
    On Linux use XDG or ~/.local/share/VAICCS
    """
    try:
        if sys.platform.startswith('win'):
            base = os.getenv('LOCALAPPDATA') or os.getenv('APPDATA') or os.path.expanduser('~')
        elif sys.platform == 'darwin':
            base = os.path.join(os.path.expanduser('~'), 'Documents')
        else:
            base = os.getenv('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    except Exception:
        base = os.path.expanduser('~')
    path = os.path.join(base, 'VAICCS')
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def get_models_dir() -> str:
    root = get_vaiccs_root()
    d = os.path.join(root, 'Models')
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def get_voice_profiles_dir() -> str:
    root = get_vaiccs_root()
    d = os.path.join(root, 'Voice profiles')
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def get_custom_words_dir() -> str:
    root = get_vaiccs_root()
    d = os.path.join(root, 'Custom words')
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def ensure_user_resource(relpath: str) -> str:
    """Ensure a copy of `relpath` exists under the user's appdata folder.

    Returns the path to the user-local copy. If no bundled/source file
    exists, a minimal placeholder will be created (empty file or empty JSON
    for `.json` files) so the app can read/write safely.
    """
    app_dir = get_user_data_dir()
    dst = os.path.join(app_dir, relpath)

    # If already present in user folder, prefer it
    if os.path.exists(dst):
        return dst

    # Try to locate a bundled/source file and copy it into appdata
    src = _resource_path(relpath)
    try:
        if os.path.exists(src):
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
            except Exception:
                pass
            try:
                shutil.copy2(src, dst)
                return dst
            except Exception:
                pass
    except Exception:
        pass

    # No source found - create a safe default file so reads/writes won't fail
    try:
        if relpath.lower().endswith('.json'):
            with open(dst, 'w', encoding='utf-8') as f:
                json.dump({}, f)
        else:
            open(dst, 'a', encoding='utf-8').close()
    except Exception:
        pass

    return dst
