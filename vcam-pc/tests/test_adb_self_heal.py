"""Tests for v1.8.27's bundled-adb self-heal (``_self_heal_bundled_adb``).

Customer bug pinned here
------------------------
macOS sellers who extract the ZIP in ``~/Downloads`` got a bundled
``adb`` with no execute bit and/or a ``com.apple.quarantine`` xattr.
``shutil.which`` then treats the binary as missing, so the wizard
hangs on "รอเครื่อง..." and support gets the "Mac doesn't connect"
ticket. The healer must:

* add the execute bit when it's missing (POSIX),
* invoke ``xattr -dr com.apple.quarantine`` on macOS only,
* never touch a system-PATH / bare ``adb`` we don't own,
* never raise.
"""

from __future__ import annotations

import os
import stat
from unittest import mock

from src import adb as adb_mod


def _make_fake_adb(tmp_path, *, executable: bool) -> str:
    pt = tmp_path / "platform-tools"
    pt.mkdir()
    binary = pt / "adb"
    binary.write_text("#!/bin/sh\necho fake\n")
    mode = 0o644 | (stat.S_IXUSR if executable else 0)
    binary.chmod(mode)
    return str(binary)


def test_adds_execute_bit_on_posix(tmp_path):
    adb_path = _make_fake_adb(tmp_path, executable=False)
    assert not os.access(adb_path, os.X_OK)

    with mock.patch.object(adb_mod.sys, "platform", "darwin"), \
            mock.patch.object(adb_mod.shutil, "which", return_value=None):
        adb_mod._self_heal_bundled_adb(adb_path)

    assert os.access(adb_path, os.X_OK)


def test_strips_quarantine_on_macos(tmp_path):
    adb_path = _make_fake_adb(tmp_path, executable=True)

    with mock.patch.object(adb_mod.sys, "platform", "darwin"), \
            mock.patch.object(adb_mod.shutil, "which", return_value="/usr/bin/xattr"), \
            mock.patch.object(adb_mod.subprocess, "run") as run:
        run.return_value = mock.Mock(returncode=0, stderr="")
        adb_mod._self_heal_bundled_adb(adb_path)

    assert run.call_count == 1
    args = run.call_args.args[0]
    assert args[0] == "/usr/bin/xattr"
    assert args[1:3] == ["-dr", "com.apple.quarantine"]
    # Strips the whole platform-tools dir so siblings are covered too.
    assert args[3] == str(tmp_path / "platform-tools")


def test_no_xattr_off_macos(tmp_path):
    adb_path = _make_fake_adb(tmp_path, executable=False)

    with mock.patch.object(adb_mod.sys, "platform", "linux"), \
            mock.patch.object(adb_mod.subprocess, "run") as run:
        adb_mod._self_heal_bundled_adb(adb_path)

    run.assert_not_called()
    # …but the exec bit is still healed on Linux.
    assert os.access(adb_path, os.X_OK)


def test_noop_on_windows(tmp_path):
    adb_path = _make_fake_adb(tmp_path, executable=False)

    with mock.patch.object(adb_mod.sys, "platform", "win32"), \
            mock.patch.object(adb_mod.subprocess, "run") as run, \
            mock.patch.object(adb_mod.os, "chmod") as chmod:
        adb_mod._self_heal_bundled_adb(adb_path)

    run.assert_not_called()
    chmod.assert_not_called()


def test_ignores_bare_system_adb():
    """A bare 'adb' (system PATH) is not ours — never chmod / xattr it."""
    with mock.patch.object(adb_mod.sys, "platform", "darwin"), \
            mock.patch.object(adb_mod.subprocess, "run") as run, \
            mock.patch.object(adb_mod.os, "chmod") as chmod:
        adb_mod._self_heal_bundled_adb("adb")

    run.assert_not_called()
    chmod.assert_not_called()


def test_never_raises_on_chmod_failure(tmp_path):
    adb_path = _make_fake_adb(tmp_path, executable=False)

    with mock.patch.object(adb_mod.sys, "platform", "linux"), \
            mock.patch.object(
                adb_mod.os, "chmod", side_effect=OSError("read-only fs")):
        # Must swallow the OSError, not propagate it.
        adb_mod._self_heal_bundled_adb(adb_path)
