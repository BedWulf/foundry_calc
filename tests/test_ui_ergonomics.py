"""UI ergonomics: large casting tables, selectable equipment, no white editors.

Run on Windows CI in offscreen mode, without requiring a physical display.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QDialog, QTextEdit

from config import COLORS
from core.casting_item import CastingItem
from gui.dialogs.castings_browser import CastingsBrowserDialog
from gui.dialogs.equipment_dialog import EquipmentDialog
from gui.dialogs.import_dialog import ImportDialog
from gui.dialogs.material_dialog import AddMaterialDialog
from gui.main_window import MainWindow
from gui.widgets.equipment_picker import EquipmentPicker


def _app():
    return QApplication.instance() or QApplication([])


def test_global_theme_covers_report_and_dialogs():
    app = _app()
    window = MainWindow()
    assert app.palette().color(QPalette.Base).name() == COLORS["bg_input"].lower()
    assert "QTextEdit" in app.styleSheet()
    assert "QTextBrowser" in app.styleSheet()
    assert "QDialog" in app.styleSheet()
    assert "QComboBox QAbstractItemView" in app.styleSheet()

    report = window.tabs["molding_tab"]._batch_report
    assert isinstance(report, QTextEdit)
    assert COLORS["bg_input"] in report.styleSheet()
    assert COLORS["text_primary"] in report.styleSheet()
    assert window.minimumWidth() <= 1024
    assert window.width() >= 1440
    assert window.tabs["project_tab"].table.minimumHeight() >= 400
    window.close()


def test_large_castings_browser_search_and_numeric_sort():
    app = _app()
    castings = [
        CastingItem(
            index=n + 1, name=f"Позиция {n + 1:03d}",
            mass_with_LPS_kg=8.0,
            molds_per_year=(n + 1) * 9,
            flask_size_mm="900x600x200/200",
            pouring_mass_kg=12.0,
        )
        for n in range(420)
    ]
    dialog = CastingsBrowserDialog(castings)
    assert dialog.model.rowCount() == 420
    assert dialog.table.minimumWidth() >= 0
    assert dialog.width() >= 720
    assert dialog.table.isSortingEnabled()
    assert not dialog.table.editTriggers()

    dialog.search.setText("Позиция 219")
    assert dialog.proxy.rowCount() == 1
    idx = dialog.proxy.index(0, 1)
    assert dialog.proxy.data(idx, Qt.DisplayRole) == "Позиция 219"
    dialog.search.clear()
    assert dialog.proxy.rowCount() == 420
    dialog.proxy.sort(4, Qt.DescendingOrder)
    first = dialog.proxy.data(dialog.proxy.index(0, 4), Qt.UserRole)
    assert first == 420 * 9
    dialog.close()


def test_equipment_expand_applies_exactly_one_choice(monkeypatch):
    _app()
    picker = EquipmentPicker("формовочные линии")
    opts = [
        {"id": "A", "name": "Линия А", "specs": {}},
        {"id": "B", "name": "Линия Б", "specs": {}},
    ]
    events = []
    picker.equipment_selected.connect(events.append)
    picker.set_equipment_options(opts)
    events.clear()
    assert picker.btn_expand.text()
    assert picker.scroll.minimumHeight() >= 400

    def choose_second_then_accept(dialog):
        inside = dialog.findChild(EquipmentPicker)
        assert inside is not None
        assert not inside._allow_expand
        inside.button_group.button(1).setChecked(True)
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", choose_second_then_accept)
    picker._open_expanded()
    assert picker.get_selected_equipment()["id"] == "B"
    assert [e["id"] for e in events] == ["B"]


def test_all_selection_dialogs_allow_resizing():
    _app()
    for dialog in (
        ImportDialog(), AddMaterialDialog(), EquipmentDialog(kind="furnace")
    ):
        assert dialog.minimumWidth() >= 550
        assert dialog.isSizeGripEnabled()
        assert bool(dialog.windowFlags() & Qt.WindowMaximizeButtonHint)
        dialog.close()
