"""Changing installed molding lines must not start cyclic Qt refresh chains."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow
from core.casting_item import CastingItem


def test_each_downstream_tab_refreshes_once(monkeypatch):
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.project.castings = [CastingItem(
        name="Корпус", annual_qty_pcs=1000, molds_per_year=1000,
        mass_with_LPS_kg=10, pouring_mass_kg=15,
        flask_size_mm="900x600x200/200",
    )]
    win._recalculate_dependents()
    mold = win.tabs["molding_tab"]
    mold._park_mode.setCurrentIndex(1)
    assert "IL-225" in mold._fleet_spins
    calls = {}
    for key in ("core_tab", "sand_tab", "workforce_tab", "areas_tab",
                "transport_tab", "summary_tab"):
        tab = win.tabs[key]
        original = tab.refresh
        calls[key] = 0
        def wrapper(*args, _original=original, _key=key, **kwargs):
            calls[_key] += 1
            return _original(*args, **kwargs)
        monkeypatch.setattr(tab, "refresh", wrapper)

    spin = mold._fleet_spins["IL-225"]
    spin.setValue(spin.value() + 1)
    assert all(count == 1 for count in calls.values()), calls
    assert win.tabs["summary_tab"]._result is not None
    win.close()
