"""Qt acceptance checks for project-driven time funds."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from core.casting_item import CastingItem
from core.project import Project
from core.summary import build_summary
from gui.tabs.time_funds_tab import TimeFundsTab
from gui.tabs.project_tab import ProjectTab


def qtapp():
    return QApplication.instance() or QApplication([])


def test_time_tab_uses_actual_workdays_and_individual_worker_fund():
    qtapp()
    p = Project(working_days_per_year=200, shifts_per_day=3, shift_duration_h=7.5)
    tab = TimeFundsTab(p)
    assert p.F_nominal_h == 4500
    assert p.F_equipment_h == 4500
    assert p.F_workers_h == 1500
    assert p.time_funds_calendar_applied
    assert not p.time_funds_verified
    assert "ПРЕДВАРИТЕЛЬНО" in tab.lbl_time_status.text()

    tab.spin_equipment_downtime.setValue(200)
    tab.spin_worker_absence.setValue(80)
    assert p.F_equipment_h == 4300
    assert p.F_workers_h == 1420
    assert p.equipment_downtime_h_per_year == 200
    assert p.worker_absence_h_per_year == 80

    tab.check_verified.setChecked(True)
    assert p.time_funds_verified
    tab.spin_worker_absence.setValue(100)
    assert p.F_workers_h == 1400
    assert not p.time_funds_verified
    assert not tab.check_verified.isChecked()
    tab.close()


def test_project_tab_limits_combined_shift_hours_and_invalidates_confirmation():
    qtapp()
    p = Project(time_funds_verified=True)
    tab = ProjectTab(p)
    tab.spin_shifts.setValue(4)
    assert p.shifts_per_day == 4
    assert p.shift_duration_h <= 6
    assert p.shifts_per_day * p.shift_duration_h <= 24
    assert not p.time_funds_verified
    tab.close()


def test_unconfirmed_calendar_blocks_summary_ready():
    p = Project(castings=[CastingItem(name="Check", molds_per_year=10)],
                time_funds_calendar_applied=True,
                time_funds_verified=False)
    res = build_summary({}, p)
    assert not res.ready
    assert any("фонд оборудования" in msg for msg in res.warnings)
