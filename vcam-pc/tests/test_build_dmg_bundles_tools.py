"""Regression guard for the v1.8.28 macOS .dmg toolchain bug.

The bug
-------
``tools/build_dmg.sh`` used to package *only* ``IP-LIVE.app`` into the
disk image. PyInstaller deliberately does NOT bundle ``.tools/`` (adb,
ffmpeg, JDK 21, lspatch) — the installer is supposed to place it next
to the binary. The Windows installer (``installer.iss``) did; the macOS
.dmg builder never did. Result: every Mac customer who installed via
.dmg got a binary with no adb on disk, ``platform_tools.find_adb()``
returned None, ``AdbController.is_available()`` failed, and the "เพิ่ม
เครื่อง" wizard hung forever on "รอเครื่อง...". The tell-tale was the
28 MB .dmg next to the 316 MB portable .zip.

Why a text-level test
---------------------
Actually invoking ``build_dmg.sh`` needs macOS + ``create-dmg`` +
``ditto`` + a real PyInstaller .app, none of which exist in the
cross-platform CI matrix this repo's tests must pass on. So we pin the
*shape* of the build script instead: it must copy the toolchain into
the app bundle at the location the frozen-mode resolver expects, and
it must refuse to build a toolless .dmg. If someone deletes that step,
this test breaks before another broken .dmg reaches a customer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "build_dmg.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_script_exists():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"


def test_copies_tools_into_app_macos_dir(script_text: str):
    """Tools must land in Contents/MacOS/.tools/macos — exactly where
    config.PROJECT_ROOT (= Path(sys.executable).parent) anchors the
    resolver in a frozen .app."""
    assert ".tools/macos" in script_text
    assert "Contents/MacOS" in script_text
    # The copy itself (ditto preserves symlinks + exec bits).
    assert "ditto" in script_text


def test_sources_tools_from_workspace(script_text: str):
    """Toolchain comes from the repo-root .tools/macos populated by
    setup_ci_tools.py / setup_scrcpy.py."""
    assert 'WORKSPACE="$(cd "$PROJECT/.." && pwd)"' in script_text
    assert 'TOOLS_SRC="$WORKSPACE/.tools/macos"' in script_text


def test_fails_hard_when_toolchain_missing(script_text: str):
    """A missing toolchain must abort the build, not silently ship a
    toolless .dmg (the original regression)."""
    idx = script_text.find('if [[ ! -d "$TOOLS_SRC" ]]; then')
    assert idx != -1, "no guard for a missing toolchain"
    # The guard block must exit non-zero.
    guard = script_text[idx:idx + 600]
    assert "exit 1" in guard


def test_verifies_adb_is_executable_after_copy(script_text: str):
    """adb must be present + executable in the bundle or the build
    aborts — catches a copy that dropped the exec bit."""
    assert 'ADB_BIN="$DEST_TOOLS/platform-tools/adb"' in script_text
    assert 'if [[ ! -x "$ADB_BIN" ]]; then' in script_text


def test_bundles_vcam_apk(script_text: str):
    """LSPatch/Patch path needs the APK shipped under apk/."""
    assert "vcam-app-release.apk" in script_text
    assert "$APP_MACOS/apk" in script_text


def test_uses_staging_copy_to_keep_zip_lean(script_text: str):
    """Injection happens on a staging copy so build_release.py's .zip
    doesn't end up shipping .tools/ twice."""
    assert "STAGE_APP" in script_text
    # create-dmg must package the staged app, not the pristine one.
    assert '"$STAGE_APP"' in script_text
