"""Qt integration: editing physical molding line counts recalculates model + downstream."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from core.project import Project
from core.casting_item import CastingItem
from core.areas import calc_areas
from core.workforce import calc_workforce
from gui.tabs.molding_tab import MoldingTab


def test_manual_line_spinbox_updates_plan_area_and_staff():
    app = QApplication.instance() or QApplication([])
    project = Project(name="Qt-manual-line-count-regression")
    project.castings = [CastingItem(
        name="Корпус", annual_qty_pcs=1000, molds_per_year=1000,
        mass_with_LPS_kg=5, pouring_mass_kg=10,
        flask_size_mm="900x600x200/200",
    )]
    tab = MoldingTab(project)
    changes = []
    tab.line_choice_changed.connect(lambda _d: changes.append("changed"))
    tab._park_mode.setCurrentIndex(1)
    assert project.molding_park_mode == "manual"
    assert "IL-225" in tab._fleet_spins

    # Explicitly remove any automatically suggested line and all compatible
    # models. The planner must NOT add an extra line in response.
    for model_id, spin in tab._fleet_spins.items():
        spin.setValue(0)
    assert not tab._last_result.batch_plan.feasible
    assert tab.get_summary()["line_count"] == 0

    tab._fleet_spins["IL-225"].setValue(1)
    a = tab.get_summary()
    assert a["batch_plan_feasible"]
    assert a["line_count"] == 1
    assert project.molding_line_counts["IL-225"] == 1
    area_a = calc_areas(project, warehouse_area_m2=0)
    staff_a = calc_workforce(project, molding=a)
    assert sum(row.units for row in area_a.rows if row.key == "molding_tab") == 1

    tab._fleet_spins["IL-225"].setValue(2)
    b = tab.get_summary()
    area_b = calc_areas(project, warehouse_area_m2=0)
    staff_b = calc_workforce(project, molding=b)
    assert b["batch_plan_feasible"]
    assert b["line_count"] == 2
    assert b["load_factor"] < a["load_factor"]
    assert sum(row.units for row in area_b.rows if row.key == "molding_tab") == 2
    assert area_b.production_total_m2 > area_a.production_total_m2
    assert staff_b.total >= staff_a.total
    assert len(changes) >= 3

    tab._park_mode.setCurrentIndex(0)
    assert project.molding_park_mode == "auto"
    assert tab._last_result.batch_plan.feasible
    tab.close()
