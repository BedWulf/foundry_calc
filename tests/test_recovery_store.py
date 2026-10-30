"""Crash recovery is isolated from the original file and other projects."""
import json
import os
from datetime import date

from core.casting_item import CastingItem
from core.project import Project
from core.project_io import write_project
from core.recovery import RecoveryStore


def _project(name: str, molds: int, uid: str = "") -> Project:
    p = Project(
        name=name, project_uid=uid,
        created_at=date(2026, 10, 30),
        molding_park_mode="manual",
        molding_line_counts={"IL-225": 2 if molds < 1000 else 4},
        molding_batches_per_year=6,
    )
    p.castings = [
        CastingItem(name=name + " отливка", index=1,
                    annual_qty_pcs=molds,
                    molds_per_year=molds,
                    mass_with_LPS_kg=9,
                    pouring_mass_kg=15),
    ]
    return p


def test_two_diploma_recoveries_never_touch_saved_files(tmp_path):
    store = RecoveryStore(tmp_path / "recovery")
    original = tmp_path / "diplom1.fpro.json"
    first = _project("Диплом 1", 500, "saved-id-1")
    write_project(original, first)
    original_bytes = original.read_bytes()

    first.castings[0].molds_per_year = 990
    one = store.new_session_id()
    two = store.new_session_id()
    file1 = store.save_snapshot(
        one, first, {"molding_line": {"equipment_id": "IL-225"}},
        {}, original)
    second = _project("Диплом 2", 1500)
    file2 = store.save_snapshot(two, second, {}, {}, None)

    assert file1 != file2
    assert original.read_bytes() == original_bytes
    entries = {x.snapshot_id: x for x in store.list_snapshots()}
    assert set(entries) == {one, two}
    recovered1, original_path, changed = store.load_snapshot(entries[one])
    assert not changed
    assert original_path == original
    assert recovered1.project.castings[0].molds_per_year == 990
    assert recovered1.choices["molding_line"]["equipment_id"] == "IL-225"
    recovered2, other_path, changed2 = store.load_snapshot(entries[two])
    assert not changed2
    assert other_path is None
    assert recovered2.project.name == "Диплом 2"
    assert recovered2.project.molding_line_counts == {"IL-225": 4}

    store.delete_snapshot(one)
    assert original.read_bytes() == original_bytes
    assert not file1.exists()
    assert file2.exists()


def test_modified_original_never_overwritten_by_restoration(tmp_path):
    store = RecoveryStore(tmp_path / "recovery")
    original = tmp_path / "project.fpro.json"
    project = _project("Original", 100, "stable-uid")
    write_project(original, project)
    key = store.new_session_id()
    project.castings[0].molds_per_year = 999
    store.save_snapshot(key, project, {}, {}, original)
    stat = original.stat()
    os.utime(original, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    entry = store.list_snapshots()[0]
    restored, target, changed = store.load_snapshot(entry)
    assert changed
    assert target is None
    assert restored.project.castings[0].molds_per_year == 999


def test_changed_source_with_same_mtime_must_use_save_as(tmp_path):
    store = RecoveryStore(tmp_path / "recovery")
    source = tmp_path / "diploma.fpro.json"
    base = _project("Диплом 1", 250, "uid1")
    write_project(source, base)
    base.castings[0].molds_per_year = 400
    key = store.new_session_id()
    store.save_snapshot(key, base, {}, {}, source)
    stat = source.stat()

    # A copying/syncing tool may overwrite bytes but restore the old
    # timestamp. Compare SHA256 as well as file modification time.
    modified = _project("Другая редакция", 750, "uid1")
    write_project(source, modified)
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    saved, path, changed = store.load_snapshot(store.list_snapshots()[0])
    assert changed
    assert path is None
    assert saved.project.castings[0].molds_per_year == 400


def test_broken_snapshot_is_never_deleted_automatically(tmp_path):
    store = RecoveryStore(tmp_path / "recovery")
    key = store.new_session_id()
    path = store.path_for(key)
    path.parent.mkdir(parents=True)
    path.write_text('{"version":999,"broken":true}', encoding="utf-8")
    assert store.list_snapshots() == []
    assert path.exists()
    assert store.path_for(key) == path


def test_snapshot_updates_one_session_atomically(tmp_path):
    store = RecoveryStore(tmp_path / "recovery")
    key = store.new_session_id()
    p = _project("Работа", 50)
    path = store.save_snapshot(key, p, {}, {}, None)
    original = path.read_bytes()
    p.castings[0].molds_per_year = 51
    store.save_snapshot(key, p, {}, {}, None)
    assert path.read_bytes() != original
    assert len(store.list_snapshots()) == 1
    p.annual_output_t = float("nan")
    try:
        store.save_snapshot(key, p, {}, {}, None)
    except ValueError:
        pass
    else:
        raise AssertionError("NaN must not be serializable")
    assert len(store.list_snapshots()) == 1
    assert store.load_snapshot(store.list_snapshots()[0])[0].project.castings[0].molds_per_year == 51
