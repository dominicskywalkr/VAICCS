# Runtime hook to ensure Vosk native library is a file (not a nested directory)
# Runs early in frozen apps before importing `vosk`.
import sys
import os

try:
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        vosk_dir = os.path.join(meipass, 'vosk')
        for name in ('libvosk.dyld', 'libvosk.dylib'):
            dir_candidate = os.path.join(vosk_dir, name)
            inner = os.path.join(dir_candidate, name)
            try:
                if os.path.isdir(dir_candidate) and os.path.isfile(inner):
                    # read inner file bytes
                    try:
                        with open(inner, 'rb') as f:
                            data = f.read()
                    except Exception:
                        data = None
                    # remove inner file and directory so we can create a file at that path
                    try:
                        if os.path.exists(inner):
                            os.remove(inner)
                    except Exception:
                        pass
                    # attempt to remove any leftover files and the directory
                    try:
                        for root, dirs, files in os.walk(dir_candidate, topdown=False):
                            for nm in files:
                                try:
                                    os.remove(os.path.join(root, nm))
                                except Exception:
                                    pass
                            for d in dirs:
                                try:
                                    os.rmdir(os.path.join(root, d))
                                except Exception:
                                    pass
                        os.rmdir(dir_candidate)
                    except Exception:
                        pass
                    # create the file at the same path (which was formerly a dir)
                    if data is not None:
                        try:
                            with open(dir_candidate, 'wb') as f:
                                f.write(data)
                        except Exception:
                            pass
            except Exception:
                # best-effort only; do not raise
                pass
except Exception:
    pass
