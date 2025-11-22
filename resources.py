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
    base = os.getenv('APPDATA') or os.getenv('LOCALAPPDATA') or os.path.expanduser('~')
    path = os.path.join(base, app_name)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


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
