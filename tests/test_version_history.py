"""Earlier saved versions must survive later Save and never mix projects."""
from datetime import date

import pytest

from core.casting_item import CastingItem
from core.project import Project
from core.project_io import write_project
from core.version_history import VersionHistoryStore


def project(title, molds, uid="shared-id"):
    p = Project(name=title, project_uid=uid, created_at=date(2026, 10, 30))
    p.castings = [CastingItem(name=title, molds_per_year=molds)]
    p.molding_park_mode = "manual"
    p.molding_line_counts = {"IL-225": 2}
    return p


def test_prior_file_saved_as_exact_version_and_source_untouched(tmp_path):
    store = VersionHistoryStore(tmp_path / "history")
    source = tmp_path / "diploma.fpro.json"
    assert store.preserve_before_save(source) is None
    p = project("Первый диплом", 100)
    write_project(source, p, {"molding_line": {"equipment_id": "IL-225"}})
    old_bytes = source.read_bytes()
    entry = store.preserve_before_save(source)
    assert entry is not None
    assert source.read_bytes() == old_bytes
    assert entry.file_path.read_bytes() == old_bytes
    p.castings[0].molds_per_year = 300
    write_project(source, p)
    versions = store.list_versions(source)
    assert len(versions) == 1
    assert store.load_version(versions[0]).project.castings[0].molds_per_year == 100
    assert store.load_version(versions[0]).choices["molding_line"]["equipment_id"] == "IL-225"
    assert source.read_bytes() != old_bytes
    assert store.load_version(versions[0]).project.molding_line_counts == {"IL-225": 2}
    # Versions are discoverable after application restart.
    assert len(VersionHistoryStore(tmp_path / "history").list_versions(source)) == 1


def test_independent_files_with_same_project_uid_have_separate_histories(tmp_path):
    store = VersionHistoryStore(tmp_path / "history")
    one, two = tmp_path / "one.fpro.json", tmp_path / "two.fpro.json"
    write_project(one, project("A", 10))
    write_project(two, project("B", 50))
    first = store.preserve_before_save(one)
    second = store.preserve_before_save(two)
    assert first.file_path != second.file_path
    assert [x.project_name for x in store.list_versions(one)] == ["A"]
    assert [x.project_name for x in store.list_versions(two)] == ["B"]
    assert store.load_version(first).project.name == "A"


def test_invalid_saved_file_blocks_archiving_and_is_not_erased(tmp_path):
    store = VersionHistoryStore(tmp_path / "history")
    source = tmp_path / "broken.fpro.json"
    source.write_text('{"broken":true}', encoding="utf-8")
    initial = source.read_bytes()
    with pytest.raises(ValueError):
        store.preserve_before_save(source)
    assert source.read_bytes() == initial
    assert store.list_versions(source) == []


def test_damaged_history_file_is_kept_but_not_offered(tmp_path):
    store = VersionHistoryStore(tmp_path / "history")
    source = tmp_path / "project.fpro.json"
    write_project(source, project("A", 12))
    entry = store.preserve_before_save(source)
    entry.file_path.write_text('{"broken":true}', encoding="utf-8")
    assert store.list_versions(source) == []
    assert entry.file_path.exists()
    with pytest.raises(ValueError):
        store.load_version(entry)


def test_history_rejects_entry_from_other_source_or_forged_path(tmp_path):
    from dataclasses import replace
    store = VersionHistoryStore(tmp_path / "history")
    source = tmp_path / "first.fpro.json"
    write_project(source, project("A", 1))
    entry = store.preserve_before_save(source)
    with pytest.raises(ValueError):
        store.load_version(replace(entry, source_path=tmp_path / "other.fpro.json"))
    with pytest.raises(ValueError):
        store.load_version(replace(entry, file_path=source))
