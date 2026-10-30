"""GUI: restore a project without losing castings, selections or calculations."""
import os
import json
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from core.project import Project
from core.casting_item import CastingItem
from core.project_io import write_project, project_inputs
from gui.main_window import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def test_save_open_restores_entire_project_and_tabs(tmp_path, monkeypatch):
    _app()
    w = MainWindow()
    original = w.project
    original.name = "Первый диплом"
    original.customer = "Завод"
    original.molding_park_mode = "manual"
    original.molding_line_counts = {"LINE-A": 2}
    original.molding_batches_per_year = 12
    original.molding_setup_h = 1.5
    original.molding_peak_concurrent_lines = 1
    original.castings = [
        CastingItem(index=1, name="Корпус насоса",
                    annual_qty_pcs=5000, molds_per_year=2500,
                    mass_with_LPS_kg=8, pouring_mass_kg=18,
                    annual_metal_t=45.0)
    ]
    filename = tmp_path / "testing.fpro.json"
    assert w._write_project_to(filename)
    assert w._project_path == filename
    assert original.project_uid
    assert not w._is_project_dirty()

    other = Project(project_uid="different-project-uid",
                    name="Другая программа", annual_output_t=100)
    other.castings = [CastingItem(name="Чужая отливка")]
    w._activate_project(other, None)
    assert w.project.castings[0].name == "Чужая отливка"

    assert w._load_project_from_path(filename)
    assert w.project.name == "Первый диплом"
    assert w.project.customer == "Завод"
    assert w.project.molding_line_counts == {"LINE-A": 2}
    assert w.project.molding_batches_per_year == 12
    assert w.project.molding_setup_h == 1.5
    assert w.project.molding_peak_concurrent_lines == 1
    assert w.project.castings[0].name == "Корпус насоса"
    assert w.tabs["project_tab"].table.rowCount() == 1
    assert w.tabs["project_tab"].edit_name.text() == "Первый диплом"
    assert w.tabs["molding_tab"]._park_mode.currentData() == "manual"
    assert not w._is_project_dirty()
    w.close()


def test_invalid_file_never_replaces_active_project(tmp_path, monkeypatch):
    _app()
    w = MainWindow()
    w.project.name = "Работа не потеряна"
    w.project.castings = [CastingItem(name="Не потерять", molds_per_year=6)]
    bad = tmp_path / "broken.fpro.json"
    bad.write_text('{"format": "wrong"}', encoding="utf-8")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: errors.append(a))
    assert not w._load_project_from_path(bad)
    assert w.project.name == "Работа не потеряна"
    assert w.project.castings[0].name == "Не потерять"
    assert errors
    w.close()


def test_unsaved_changes_are_detected_and_cancel_blocks_discard(monkeypatch):
    _app()
    w = MainWindow()
    assert not w._is_project_dirty()
    w.tabs["project_tab"].spin_annual.setValue(50000)
    assert w._is_project_dirty()
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Cancel)
    assert not w._confirm_discard_project()
    assert w.project.annual_output_t == 50000
    w.close()


def test_save_as_uses_project_file_extension(tmp_path, monkeypatch):
    _app()
    w = MainWindow()
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "study"), ""))
    assert w._save_project_as()
    assert (tmp_path / "study.fpro.json").is_file()
    assert w._project_path.name == "study.fpro.json"
    assert not w._is_project_dirty()
    w.close()
