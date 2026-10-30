"""Qt crash-recovery tests: manual save wins; recovery is opt-in."""
import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from core.casting_item import CastingItem
from core.project import Project
from core.project_io import write_project
from core.recovery import RecoveryStore
from gui.dialogs.recovery_dialog import RecoveryDialog
from gui.main_window import MainWindow


def test_autosave_is_separate_from_original_and_removed_after_manual_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w._recovery_store = RecoveryStore(tmp_path / "recovery")
    source = tmp_path / "manual.fpro.json"
    assert w._write_project_to(source)
    first_bytes = source.read_bytes()

    w.project.castings = [
        CastingItem(index=1, name="Несохранённая отливка",
                    molds_per_year=500, pouring_mass_kg=14)
    ]
    w.project.molding_park_mode = "manual"
    w.project.molding_line_counts = {"IL-225": 2}
    assert w._is_project_dirty()
    w._autosave_snapshot()
    backup_path = w._recovery_store.path_for(w._recovery_id)
    assert backup_path.exists()
    assert source.read_bytes() == first_bytes
    assert "Несохранённая отливка" in backup_path.read_text(encoding="utf-8")
    assert w._save_project()
    assert not backup_path.exists()
    assert "Несохранённая отливка" in source.read_text(encoding="utf-8")
    assert not w._is_project_dirty()
    w.close()


def test_recovered_project_is_dirty_and_reautosaaves(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "source.fpro.json"
    original = Project(
        name="Диплом A", project_uid="fixed-uid",
        created_at=date(2026, 10, 30),
    )
    write_project(source, original)
    baseline = source.read_bytes()

    working = Project(
        name="Диплом A", project_uid="fixed-uid",
        created_at=date(2026, 10, 30),
        molding_park_mode="manual",
        molding_line_counts={"IL-225": 5},
    )
    working.castings = [
        CastingItem(index=1, name="После аварии",
                    molds_per_year=1250, pouring_mass_kg=15)
    ]
    store = RecoveryStore(tmp_path / "recovery")
    key = store.new_session_id()
    store.save_snapshot(key, working, {}, {}, source)
    entry = store.list_snapshots()[0]

    w = MainWindow()
    w._recovery_store = store
    assert w._restore_recovery_entry(entry)
    assert w.project.castings[0].name == "После аварии"
    assert w.project.molding_line_counts == {"IL-225": 5}
    assert w._project_path == source
    assert w._is_project_dirty()
    assert source.read_bytes() == baseline
    assert w._recovery_id == key
    w._autosave_snapshot()
    assert store.path_for(key).exists()
    assert source.read_bytes() == baseline
    w.close()


def test_recovery_dialog_lists_all_and_later_preserves_backups(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = RecoveryStore(tmp_path / "recovery")
    for n in (1, 2):
        p = Project(name=f"Диплом {n}", project_uid=f"uid-{n}")
        key = store.new_session_id()
        store.save_snapshot(key, p, {}, {}, None)
    entries = store.list_snapshots()
    dlg = RecoveryDialog(entries)
    assert dlg.list.count() == 2
    dlg.later_button.click()
    assert dlg.result() == 0  # QDialog.DialogCode.Rejected
    assert len(store.list_snapshots()) == 2
    dlg.close()
