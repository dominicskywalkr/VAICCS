#!/usr/bin/env bash
set -euo pipefail

# Copy libvosk from the development venv or installed vosk package into
# the built .app Frameworks/vosk and onedir _internal/vosk locations.

# Determine python minor version string like '3.13'
PYVER=$(python - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)

CAND1=".venv/lib/python${PYVER}/site-packages/vosk/libvosk.dyld"
CAND2=".venv/lib/python${PYVER}/site-packages/vosk/libvosk.dylib"

SRC=""
if [ -f "$CAND1" ]; then
  SRC="$CAND1"
elif [ -f "$CAND2" ]; then
  SRC="$CAND2"
else
  # Try to ask Python to resolve the installed vosk package path
  SRC=$(python - <<'PY'
try:
    import os, importlib
    spec = importlib.util.find_spec('vosk')
    if not spec or not getattr(spec, 'origin', None):
        print('')
    else:
        pkg = os.path.dirname(spec.origin)
        for name in ('libvosk.dyld','libvosk.dylib','libvosk.so'):
            p = os.path.join(pkg, name)
            if os.path.isfile(p):
                print(p)
                break
        else:
            print('')
except Exception:
    print('')
PY
)
fi

if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
  echo "ERROR: libvosk library not found in .venv or installed vosk package."
  echo "Checked: $CAND1 and $CAND2 and python-resolved path."
  exit 2
fi

echo "Found libvosk at: $SRC"

# Copy into .app Frameworks/vosk
APP_VOSK_DIR="dist/VAICCS.app/Contents/Frameworks/vosk"
mkdir -p "$APP_VOSK_DIR"
cp -f "$SRC" "$APP_VOSK_DIR/libvosk.dyld"
chmod 755 "$APP_VOSK_DIR/libvosk.dyld"

# Copy into onedir internal path
ONEDIR_VOSK_DIR="dist/VAICCS/_internal/vosk"
mkdir -p "$ONEDIR_VOSK_DIR"
cp -f "$SRC" "$ONEDIR_VOSK_DIR/libvosk.dyld"
chmod 755 "$ONEDIR_VOSK_DIR/libvosk.dyld"

echo "Copied libvosk to bundle and onedir targets."
exit 0
