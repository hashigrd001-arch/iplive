#!/usr/bin/env bash
# IP LIVE -- one-command macOS .dmg build.
#
# Run this on macOS with create-dmg installed:
#
#   brew install create-dmg
#   python tools/build_pyinstaller.py    # produces dist/pyinstaller/IP-LIVE.app
#   bash tools/build_dmg.sh
#
# Output:
#   vcam-pc/dist/installer/IP-LIVE-<version>.dmg
#
# Why .dmg, not just a .zip
# -------------------------
# macOS users are conditioned to drag-to-Applications via .dmg --
# it's the platform's "installer" UX (see Discord, OBS, Notion).
# A .zip works but customers often run the app from ~/Downloads
# and then macOS Gatekeeper quarantines it on every launch. Dropping
# into /Applications via .dmg clears the quarantine flag once and
# the customer never sees "is from the internet" warnings again.

set -euo pipefail

# Force C locale before any tool invocation. ``create-dmg`` greps
# the literal English string "Resource busy" out of ``hdiutil``
# stderr to decide whether to retry an unmount; on machines whose
# system locale is Thai (or any non-English one) ``hdiutil`` emits
# the localized phrase ("แหล่งข้อมูลไม่ว่าง" etc.), the grep
# misses, and the build aborts with exit 16 on the first transient
# busy mount. ``LC_ALL=C`` keeps both ``hdiutil`` and any of its
# child tools speaking English so the heuristic works.
export LC_ALL=C
export LANG=C

cd "$(dirname "$0")/.."
PROJECT="$(pwd)"
WORKSPACE="$(cd "$PROJECT/.." && pwd)"

APP="$PROJECT/dist/pyinstaller/IP-LIVE.app"
# We inject the toolchain into a *staging copy* of the .app rather
# than the PyInstaller output itself, because build_release.py (the
# portable .zip) runs AFTER this script in CI and re-packs the same
# dist/pyinstaller/IP-LIVE.app. Mutating it in place would make the
# .zip ship .tools/ twice (once inside the .app, once at the bundle
# root) — doubling it from ~316 MB to ~600 MB. Staging keeps the
# PyInstaller artifact pristine for the .zip step.
STAGE_DIR="$PROJECT/dist/dmg-staging"
STAGE_APP="$STAGE_DIR/IP-LIVE.app"
APP_MACOS="$STAGE_APP/Contents/MacOS"
OUT_DIR="$PROJECT/dist/installer"
VERSION="$(python3 -c 'import sys; sys.path.insert(0, "src"); from branding import BRAND; print(BRAND.version)')"
DMG="$OUT_DIR/IP-LIVE-${VERSION}.dmg"
VOL_NAME="IP LIVE ${VERSION}"

echo
echo " ============================================================"
echo "  IP LIVE -- macOS .dmg Build"
echo "  version: ${VERSION}"
echo " ============================================================"

if [[ ! -d "$APP" ]]; then
    echo "[!] $APP not found."
    echo "    Run: python3 tools/build_pyinstaller.py"
    exit 1
fi

if ! command -v create-dmg >/dev/null 2>&1; then
    echo "[!] create-dmg not installed."
    echo "    Run: brew install create-dmg"
    exit 1
fi

# ---------------------------------------------------------------------
# Inject the portable toolchain INTO the .app bundle.
#
# Why this exists (the bug that shipped to every Mac customer)
# -----------------------------------------------------------
# PyInstaller deliberately does NOT bundle .tools/ (see
# build_pyinstaller.py _add_data_args). The installer is responsible
# for placing adb / ffmpeg / JDK 21 / lspatch next to the binary.
# On Windows, installer.iss does that. On macOS this script previously
# packaged ONLY IP-LIVE.app — so the resulting .dmg (~28 MB vs the
# .zip's ~316 MB) had no adb/ffmpeg/JDK at all. At runtime
# platform_tools.find_adb() returned None, AdbController fell back to
# the bare string "adb" (not on a customer's PATH), is_available()
# failed, and the wizard hung forever on "รอเครื่อง..." — on EVERY
# Mac installed via .dmg. The v1.8.28 quarantine self-heal couldn't
# help because there was no file on disk to heal.
#
# The fix: drop .tools/macos/ + apk/ into Contents/MacOS/ — exactly
# where the frozen-mode resolver expects them. In a frozen .app
# config.PROJECT_ROOT = Path(sys.executable).parent = Contents/MacOS/,
# and platform_tools._tools_root_base() finds .tools/ as a direct
# child there. Mirrors the Inno Setup {app}\.tools\ layout on Windows.
# ---------------------------------------------------------------------
TOOLS_SRC="$WORKSPACE/.tools/macos"
DEST_TOOLS="$APP_MACOS/.tools/macos"

echo
echo "[*] Staging IP-LIVE.app + injecting toolchain ..."

# Fresh staging copy of the pristine PyInstaller .app.
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
ditto "$APP" "$STAGE_APP"

if [[ ! -d "$TOOLS_SRC" ]]; then
    echo "[!] $TOOLS_SRC not found."
    echo "    Refusing to build a toolless .dmg — that ships adb/ffmpeg/JDK-"
    echo "    less to every Mac customer and hangs the wizard on 'รอเครื่อง...'."
    echo "    Populate the toolchain first:"
    echo "       python3 tools/setup_scrcpy.py   --os macos"
    echo "       python3 tools/setup_ci_tools.py --os macos"
    exit 1
fi

rm -rf "$APP_MACOS/.tools"
mkdir -p "$DEST_TOOLS"
# ``ditto`` is the macOS-canonical copy: it preserves symlinks (the
# JDK's Contents/Home aliases, dylib version links), POSIX exec bits,
# and resource metadata. ``cp -R`` can mangle these on macOS.
ditto "$TOOLS_SRC" "$DEST_TOOLS"

ADB_BIN="$DEST_TOOLS/platform-tools/adb"
if [[ ! -x "$ADB_BIN" ]]; then
    echo "[!] adb missing or not executable after copy:"
    echo "    $ADB_BIN"
    echo "    The .dmg would still hang the wizard — aborting."
    exit 1
fi

# Bundle the vcam-app APK (LSPatch / Patch path). Same candidate order
# as platform_tools.find_vcam_apk(). Optional: Phase 5 screen-share
# works without it, so a missing APK only warns.
APK_SRC=""
for cand in \
    "$WORKSPACE/apk/vcam-app-release.apk" \
    "$WORKSPACE/apk/vcam-app-debug.apk" \
    "$WORKSPACE/vcam-app/app/build/outputs/apk/release/app-release.apk" \
    "$WORKSPACE/vcam-app/app/build/outputs/apk/debug/app-debug.apk"; do
    if [[ -f "$cand" ]]; then APK_SRC="$cand"; break; fi
done
if [[ -n "$APK_SRC" ]]; then
    mkdir -p "$APP_MACOS/apk"
    cp "$APK_SRC" "$APP_MACOS/apk/vcam-app-release.apk"
    echo "    apk     : $(basename "$APK_SRC")"
else
    echo "    [!] vcam-app APK not found — Patch/LSPatch path will be"
    echo "        unavailable (Phase 5 screen-share still works)."
fi

# Strip any quarantine xattr now so the first launch is clean — the
# runtime self-heal (v1.8.28) is a backstop, not a substitute.
xattr -cr "$STAGE_APP" 2>/dev/null || true

TOOLS_SIZE=$(du -sh "$APP_MACOS/.tools" | awk '{print $1}')
echo "    .tools/ : $TOOLS_SIZE (adb + ffmpeg + JDK 21 + lspatch + scrcpy + mediamtx)"
echo "    adb     : OK ($ADB_BIN)"

mkdir -p "$OUT_DIR"
rm -f "$DMG"

# Optional background image (logo on light/dark gradient). Falls
# back to plain white if the asset hasn't been authored yet --
# create-dmg accepts a missing --background gracefully via the
# --no-internet-enable trick we use below.
BG_ARGS=()
if [[ -f "$PROJECT/assets/dmg-background.png" ]]; then
    BG_ARGS=(--background "$PROJECT/assets/dmg-background.png")
fi

# create-dmg wraps `hdiutil` with a sane DSL. Window geometry
# values below place the .app icon to the left of the Applications
# alias so the customer's natural left-to-right read = "drag NP
# Create -> Applications".
create-dmg \
    --volname "$VOL_NAME" \
    --volicon "$PROJECT/assets/logo.icns" \
    --window-pos 200 120 \
    --window-size 720 400 \
    --icon-size 128 \
    --icon "IP-LIVE.app" 180 200 \
    --hide-extension "IP-LIVE.app" \
    --app-drop-link 540 200 \
    "${BG_ARGS[@]+"${BG_ARGS[@]}"}" \
    --no-internet-enable \
    "$DMG" \
    "$STAGE_APP"
# The ``${BG_ARGS[@]+...}`` indirection above is the standard
# bash-3.2 idiom for "expand only if the array has elements".
# Without it, ``set -u`` plus an empty BG_ARGS triggers an
# "unbound variable" abort BEFORE create-dmg even starts —
# painful because the asset (assets/dmg-background.png) is
# optional by design.

echo
echo " DONE."
SIZE=$(du -h "$DMG" | awk '{print $1}')
echo "  Output: $DMG"
echo "  Size:   $SIZE"
echo
