#!/bin/bash
set -euo pipefail

# codesign_and_notarize.sh
# Signs an .app, creates a DMG (using scripts/make_dmg.sh), optionally signs the installer DMG,
# submits it to Apple's notary service, waits for completion and staples the ticket.
#
# Environment variables (preferred):
#  DEVELOPER_ID_APP       - 'Developer ID Application: Name (TEAMID)'
#  DEVELOPER_ID_INSTALLER - 'Developer ID Installer: Name (TEAMID)' (optional, for productsign)
#
# Notarization authentication options (choose one):
#  1) API key file (recommended): set NOTARY_KEY_PATH, NOTARY_KEY_ID, NOTARY_ISSUER
#     - NOTARY_KEY_PATH: path to the private API key .p8
#     - NOTARY_KEY_ID: the Key ID shown in App Store Connect
#     - NOTARY_ISSUER: the Issuer (Team) ID
#  2) Apple ID / app-specific password: set APPLE_ID and APPLE_PASSWORD
#
# Usage: ./scripts/codesign_and_notarize.sh /path/to/App.app [output-dmg]

if [ $# -lt 1 ]; then
  echo "Usage: $0 /path/to/App.app [output-dmg]"
  exit 2
fi

APP_PATH="$1"
if [ ! -d "$APP_PATH" ]; then
  echo "App not found: $APP_PATH"
  exit 2
fi

APP_NAME="$(basename "$APP_PATH")"
OUTPUT_DMG="${2:-${APP_NAME%.app}-notarized.dmg}"

if [ -z "${DEVELOPER_ID_APP:-}" ]; then
  echo "Please set DEVELOPER_ID_APP to your Developer ID Application signing identity."
  exit 2
fi

echo "Codesigning $APP_PATH with $DEVELOPER_ID_APP..."
codesign --deep --force --options runtime --timestamp --sign "$DEVELOPER_ID_APP" "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

echo "Building unsigned DMG using scripts/make_dmg.sh..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/make_dmg.sh" "$APP_PATH" "${APP_NAME%%.app}" "$OUTPUT_DMG"

SIGNED_DMG="$OUTPUT_DMG"

if [ -n "${DEVELOPER_ID_INSTALLER:-}" ]; then
  echo "Signing DMG with Developer ID Installer: $DEVELOPER_ID_INSTALLER"
  TMP_SIGNED="${OUTPUT_DMG%.dmg}-signed.dmg"
  productsign --sign "$DEVELOPER_ID_INSTALLER" "$OUTPUT_DMG" "$TMP_SIGNED"
  SIGNED_DMG="$TMP_SIGNED"
fi

echo "Notarization: submitting $SIGNED_DMG"

NOTARY_SUBMIT_CMD=(xcrun notarytool submit "$SIGNED_DMG" --wait)
if [ -n "${NOTARY_KEY_PATH:-}" ] && [ -n "${NOTARY_KEY_ID:-}" ] && [ -n "${NOTARY_ISSUER:-}" ]; then
  NOTARY_SUBMIT_CMD+=(--key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER")
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_PASSWORD:-}" ]; then
  NOTARY_SUBMIT_CMD+=(--apple-id "$APPLE_ID" --password "$APPLE_PASSWORD")
else
  echo "No notarization credentials found. Set NOTARY_KEY_PATH/NOTARY_KEY_ID/NOTARY_ISSUER or APPLE_ID/APPLE_PASSWORD"
  exit 2
fi

"${NOTARY_SUBMIT_CMD[@]}"

echo "Stapling notarization ticket to $SIGNED_DMG"
xcrun stapler staple "$SIGNED_DMG"

echo "Notarization complete. Output: $SIGNED_DMG"
