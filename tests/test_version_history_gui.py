"""GUI regression: history picker and safe restore never overwrite newest save."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from core.casting_item import CastingItem
from core.version_history import VersionHistoryStore
from gui.dialogs.version_history_dialog import VersionHistoryDialog
from gui.main_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


def test_save_twice_then_restore_older_version_as_unsaved_copy(tmp_path):
    app()
    window = MainWindow()
    window._version_history = VersionHistoryStore(tmp_path / "history")
    file = tmp_path / "diploma.fpro.json"
    window.project.castings = [CastingItem(name="Блок", molds_per_year=100)]
    window.project.molding_park_mode = "manual"
    window.project.molding_line_counts = {"IL-225": 2}
    assert window._write_project_to(file)
    old_file = file.read_bytes()

    window.project.castings[0].molds_per_year = 200
    assert window._save_project()
    assert file.read_bytes() != old_file
    versions = window._version_history.list_versions(file)
    assert len(versions) == 1
    assert versions[0].file_path.read_bytes() == old_file

    dialog = VersionHistoryDialog(versions)
    assert dialog.list.count() == 1
    dialog.open_button.click()
    assert dialog.selected_entry == versions[0]
    dialog.close()

    newest = file.read_bytes()
    assert window._restore_version_entry(versions[0])
    assert window.project.castings[0].molds_per_year == 100
    assert window.project.molding_line_counts == {"IL-225": 2}
    assert window._project_path is None
    assert window._is_project_dirty()
    assert file.read_bytes() == newest
    window.close()


def test_save_refuses_to_overwrite_when_history_unavailable(tmp_path, monkeypatch):
    app()
    window = MainWindow()
    window._version_history = VersionHistoryStore(tmp_path / "history")
    file = tmp_path / "diploma.fpro.json"
    assert window._write_project_to(file)
    original = file.read_bytes()
    window.project.castings = [CastingItem(name="Новое", molds_per_year=200)]
    errors = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *args, **kwargs: errors.append(args))

    def failed_history(_path):
        raise OSError("History storage is unavailable")

    monkeypatch.setattr(window._version_history, "preserve_before_save",
                        failed_history)
    assert not window._save_project()
    assert errors
    assert file.read_bytes() == original
    window.close()


def test_historical_copy_cannot_change_source_equipment_choices(tmp_path, monkeypatch):
    import config
    import gui.main_window as window_module
    from core.user_choices import UserChoices
    from uuid import uuid4

    profile = tmp_path / "profile"
    monkeypatch.setattr(config, "USER_DATA_DIR", profile)
    monkeypatch.setattr(window_module, "USER_DATA_DIR", profile)
    app()
    window = MainWindow()
    window._version_history = VersionHistoryStore(tmp_path / "history")
    original_uid = uuid4().hex
    window.project.project_uid = original_uid
    manager = UserChoices()
    manager.replace_project_choices(
        original_uid, {"molding_line": {"equipment_id": "IL-225"}})
    filename = tmp_path / "study.fpro.json"
    assert window._write_project_to(filename)

    manager.replace_project_choices(
        original_uid, {"molding_line": {"equipment_id": "KV301"}})
    window.project.castings = [CastingItem(name="Updated", molds_per_year=55)]
    assert window._save_project()
    history = window._version_history.list_versions(filename)
    assert len(history) == 1

    latest_bytes = filename.read_bytes()
    assert window._restore_version_entry(history[0])
    assert window.project.project_uid != original_uid
    original = UserChoices().get_project_choices(original_uid)
    copy = UserChoices().get_project_choices(window.project.project_id)
    assert original["molding_line"]["equipment_id"] == "KV301"
    assert copy["molding_line"]["equipment_id"] == "IL-225"
    assert filename.read_bytes() == latest_bytes
    window.close()
