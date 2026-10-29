"""End-to-end Qt signals: changing a line count updates dependent tabs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.casting_item import CastingItem
from gui.main_window import MainWindow


def test_line_quantity_propagates_to_live_window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.project.castings = [
        CastingItem(
            name="Тестовая отливка", annual_qty_pcs=1200,
            molds_per_year=1200, mass_with_LPS_kg=10, pouring_mass_kg=12,
            flask_size_mm="900x600x200/200",
        )
    ]
    tab = win.tabs["molding_tab"]
    tab.on_project_changed()
    tab._park_mode.setCurrentIndex(1)
    # Clear possible automatically populated model before selecting exact one.
    for spin in tab._fleet_spins.values():
        spin.setValue(0)
    tab._fleet_spins["IL-225"].setValue(1)

    areas = win.tabs["areas_tab"]
    workforce = win.tabs["workforce_tab"]
    summary = win.tabs["summary_tab"]
    first_area = areas._result.production_total_m2
    first_workers = workforce._result.total
    assert tab.get_summary()["line_count"] == 1
    assert summary._result is not None

    tab._fleet_spins["IL-225"].setValue(2)
    assert tab.get_summary()["line_count"] == 2
    assert areas._result.production_total_m2 > first_area
    assert workforce._result.total > first_workers
    assert any(
        row.department == "Формовочное" and row.units == 2
        for row in summary._result.rows
    )
    win.close()
