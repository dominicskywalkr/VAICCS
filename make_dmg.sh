#!/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 /path/to/App.app [VolumeName] [output.dmg] [background.png]"
  exit 2
fi

APP_PATH="$1"
if [ ! -d "$APP_PATH" ]; then
  echo "App not found: $APP_PATH"
  exit 2
fi

APP_NAME="$(basename "$APP_PATH")"
VOL_NAME="${2:-$APP_NAME}"
OUTPUT_DMG="${3:-${APP_NAME%.app}.dmg}"
BG_IMAGE="${4:-}"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

mkdir -p "$WORKDIR/$VOL_NAME"
cp -R "$APP_PATH" "$WORKDIR/$VOL_NAME/"
ln -s /Applications "$WORKDIR/$VOL_NAME/Applications"

TMP_IMG="$WORKDIR/${APP_NAME%.app}.tmp.dmg"
# Create a temporary read/write image from the staging folder

# Create a temporary read/write image from the staging folder
hdiutil create -srcfolder "$WORKDIR/$VOL_NAME" -volname "$VOL_NAME" -fs HFS+ -ov -format UDRW -ov "$TMP_IMG"

# Attach the image so we can customize Finder window (background + icon positions)
ATTACH_OUTPUT=$(hdiutil attach -readwrite -noverify -noautoopen "$TMP_IMG")
DEVICE=$(echo "$ATTACH_OUTPUT" | awk '/\/Volumes\//{print $1; exit}')
MOUNT_POINT=$(echo "$ATTACH_OUTPUT" | awk '/\/Volumes\//{print $3; exit}')

if [ -z "$MOUNT_POINT" ] || [ -z "$DEVICE" ]; then
  echo "Failed to attach image for customization"
  exit 3
fi

if [ -n "$BG_IMAGE" ] && [ -f "$BG_IMAGE" ]; then
  mkdir -p "$MOUNT_POINT/.background"
  BG_BASENAME=$(basename "$BG_IMAGE")
  cp "$BG_IMAGE" "$MOUNT_POINT/.background/$BG_BASENAME"
else
  # If no background provided, use the repo default if present
  # Prefer a PNG background; if only a base64 PNG is present, decode it.
  if [ -f "resources/dmg_background.png" ]; then
    mkdir -p "$MOUNT_POINT/.background"
    BG_BASENAME=$(basename "resources/dmg_background.png")
    cp "resources/dmg_background.png" "$MOUNT_POINT/.background/$BG_BASENAME"
  elif [ -f "resources/dmg_background.png.b64" ]; then
    mkdir -p "$MOUNT_POINT/.background"
    BG_BASENAME="dmg_background.png"
    # macOS base64 uses -D to decode; support both by trying macOS form first
    if base64 -D -i "resources/dmg_background.png.b64" -o "$MOUNT_POINT/.background/$BG_BASENAME" 2>/dev/null; then
      :
    else
      base64 --decode "resources/dmg_background.png.b64" > "$MOUNT_POINT/.background/$BG_BASENAME"
    fi
  elif [ -f "resources/dmg_background.svg" ]; then
    # SVG may not be supported by Finder as a background image; copy it but background setting might fail.
    mkdir -p "$MOUNT_POINT/.background"
    BG_BASENAME=$(basename "resources/dmg_background.svg")
    cp "resources/dmg_background.svg" "$MOUNT_POINT/.background/$BG_BASENAME"
  else
    BG_BASENAME=""
  fi
fi

# Build the AppleScript into a temporary file, then run it to avoid heredoc truncation issues
/usr/bin/printf 'tell application "Finder"\n' > "$WORKDIR/.applescript"
/usr/bin/printf '  delay 0.5\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '  open POSIX file "%s"\n' "$MOUNT_POINT" >> "$WORKDIR/.applescript"
/usr/bin/printf '  delay 0.5\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '  tell window 1\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '    set current view to icon view\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '    set toolbar visible to false\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '    set statusbar visible to false\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '    set the bounds to {100, 100, 700, 500}\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '  end tell\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '  set theViewOptions to icon view options of window 1\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '  set icon size of theViewOptions to 128\n' >> "$WORKDIR/.applescript"

if [ -n "$BG_BASENAME" ]; then
  /usr/bin/printf '  set bgFile to (POSIX file "%s/.background/%s") as alias\n' "$MOUNT_POINT" "$BG_BASENAME" >> "$WORKDIR/.applescript"
  /usr/bin/printf '  set background picture of theViewOptions to bgFile\n' >> "$WORKDIR/.applescript"
fi

/usr/bin/printf '  set position of item "%s" of window 1 to {140,150}\n' "$APP_NAME" >> "$WORKDIR/.applescript"
/usr/bin/printf '  set position of item "Applications" of window 1 to {420,150}\n' >> "$WORKDIR/.applescript"
/usr/bin/printf '  close window 1\n' >> "$WORKDIR/.applescript"
/usr/bin/printf 'end tell\n' >> "$WORKDIR/.applescript"

osascript "$WORKDIR/.applescript"
rm -f "$WORKDIR/.applescript"

# Detach the image
hdiutil detach "$DEVICE"

# Convert to compressed, read-only UDZO
hdiutil convert "$TMP_IMG" -format UDZO -imagekey zlib-level=9 -o "$OUTPUT_DMG"

echo "Created $OUTPUT_DMG"

#this is the command to run the script in the terminal for VAICCS.
#sudo ./scripts/make_dmg.sh "/Users/dominic/closed captioning Mac/dist/VAICCS.app" "VAICCS" VAICCS Mac AMD64.dmg