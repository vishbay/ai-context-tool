#!/usr/bin/env bash
# Build cram-ai.app and a distributable DMG.
#
# Usage:
#   bash scripts/build_macos_app.sh [--sign "Developer ID Application: NAME (TEAMID)"]
#
# Outputs:
#   dist/cram-ai.app
#   dist/cram-ai-<version>.dmg

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

SIGN_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sign) SIGN_ID="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

VERSION=$(python -c "import cram; print(cram.__version__)")
APP="dist/cram-ai.app"
DMG="dist/cram-ai-${VERSION}.dmg"

# ── 1. Generate icon ──────────────────────────────────────────────
if [[ ! -f assets/cram-ai.icns ]]; then
  echo "==> Generating icon..."
  python scripts/generate_icns.py
else
  echo "==> Icon already exists, skipping generation."
fi

# ── 2. Install build deps ─────────────────────────────────────────
echo "==> Installing build dependencies..."
pip install pyinstaller --quiet

# ── 3. Build .app ─────────────────────────────────────────────────
echo "==> Building cram-ai.app..."
pyinstaller cram-menu.spec --clean --noconfirm

# ── 4. Code-sign (optional) ───────────────────────────────────────
if [[ -n "$SIGN_ID" ]]; then
  echo "==> Signing with: $SIGN_ID"
  codesign \
    --deep --force --options runtime \
    --entitlements assets/entitlements.plist \
    --sign "$SIGN_ID" \
    "$APP"
  echo "==> Verifying signature..."
  codesign --verify --deep --strict --verbose=2 "$APP"
  spctl --assess --type exec --verbose "$APP"
else
  echo "==> Skipping code signing (pass --sign 'Developer ID Application: ...' to sign)."
fi

# ── 5. Create DMG ────────────────────────────────────────────────
echo "==> Creating DMG..."
rm -f "$DMG"
hdiutil create \
  -volname "cram-ai ${VERSION}" \
  -srcfolder "$APP" \
  -ov -format UDZO \
  "$DMG"

echo ""
echo "Done!"
echo "  App: ${REPO}/${APP}"
echo "  DMG: ${REPO}/${DMG}"
echo ""
if [[ -z "$SIGN_ID" ]]; then
  echo "Next: sign and notarize before distributing:"
  echo "  bash scripts/build_macos_app.sh --sign 'Developer ID Application: YOUR NAME (TEAMID)'"
  echo "  bash scripts/notarize.sh  # see step 4 plan"
fi
