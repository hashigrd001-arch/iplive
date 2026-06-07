"""``DeviceEntry.zoom`` persistence + clamping (v1.8.27 live zoom)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.customer_devices import (  # noqa: E402
    ZOOM_MAX,
    ZOOM_MIN,
    DeviceLibrary,
    clamp_zoom,
)


def test_zoom_defaults_to_one(tmp_path: Path):
    lib = DeviceLibrary()
    lib.upsert("SER1", model="Redmi 13C")
    assert lib.get("SER1").zoom == 1.0


def test_update_transform_zoom_roundtrips(tmp_path: Path):
    path = tmp_path / "devices.json"
    lib = DeviceLibrary()
    lib.upsert("SER1", model="Redmi 13C")
    lib.update_transform("SER1", zoom=0.7)
    assert lib.get("SER1").zoom == 0.7
    lib.save(path)

    reloaded = DeviceLibrary.load(path)
    assert reloaded.get("SER1").zoom == 0.7


def test_zoom_is_clamped_on_update():
    lib = DeviceLibrary()
    lib.upsert("SER1", model="Redmi 13C")
    lib.update_transform("SER1", zoom=99.0)
    assert lib.get("SER1").zoom == ZOOM_MAX
    lib.update_transform("SER1", zoom=0.01)
    assert lib.get("SER1").zoom == ZOOM_MIN


def test_zoom_update_keeps_other_transform_fields():
    lib = DeviceLibrary()
    lib.upsert("SER1", model="Redmi 13C")
    lib.update_transform("SER1", rotation=90, mirror_h=True)
    lib.update_transform("SER1", zoom=1.5)
    e = lib.get("SER1")
    assert e.rotation == 90
    assert e.mirror_h is True
    assert e.zoom == 1.5


def test_clamp_zoom_handles_garbage():
    assert clamp_zoom(None) == 1.0
    assert clamp_zoom("not-a-number") == 1.0
    assert clamp_zoom(float("nan")) == 1.0
    assert clamp_zoom(1.25) == 1.25


def test_legacy_devices_json_without_zoom_loads_default(tmp_path: Path):
    path = tmp_path / "devices.json"
    path.write_text(
        '{"entries": {"SER1": {"model": "Redmi 13C"}}}', encoding="utf-8"
    )
    lib = DeviceLibrary.load(path)
    assert lib.get("SER1").zoom == 1.0


def test_corrupt_zoom_in_json_clamps_on_load(tmp_path: Path):
    path = tmp_path / "devices.json"
    path.write_text(
        '{"entries": {"SER1": {"model": "X", "zoom": 50}}}', encoding="utf-8"
    )
    lib = DeviceLibrary.load(path)
    assert lib.get("SER1").zoom == ZOOM_MAX
