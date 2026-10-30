"""GUI: confirming genuine zero-core castings is explicit and reversible."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.casting_item import CastingItem
from core.project import Project
from gui.tabs.core_tab import CoreTab


def app():
    return QApplication.instance() or QApplication([])


def test_gui_requires_explicit_zero_core_confirmation():
    app()
    project = Project()
    project.castings = [
        CastingItem(name="Стержни", molds_per_year=100, cores_count=2),
        CastingItem(name="Без стержней?", molds_per_year=300, cores_count=0),
    ]
    tab = CoreTab(project)
    assert tab.confirm_zero_cores.isVisible() is False or not tab.isVisible()
    assert not tab.confirm_zero_cores.isChecked()
    assert tab.get_summary()["core_data_complete"] is False
    assert tab.get_summary()["annual_cores"] is None
    assert tab.get_summary()["annual_cores_lower_bound"] == 200
    assert "не подтверждено" in tab._prog_labels["annual_cores"].text()

    tab.confirm_zero_cores.setChecked(True)
    assert project.cores_zero_confirmed
    assert tab.get_summary()["core_data_complete"] is True
    assert tab.get_summary()["annual_cores"] == 200
    assert tab._prog_labels["annual_cores"].text().startswith("200")

    tab.confirm_zero_cores.setChecked(False)
    assert not project.cores_zero_confirmed
    assert tab.get_summary()["annual_cores"] is None
    tab.close()
