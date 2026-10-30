"""Independent dimensional time-funds and project-safety regression checks."""
import json
import pytest

from core.time_funds import calculate_operating_time_funds
from core.project import Project
from core.project_io import ProjectFileError, read_project, write_project
from core.workforce import calc_workforce


def test_two_shift_schedule_and_individual_worker_hours():
    r = calculate_operating_time_funds(
        working_days_per_year=249, shifts_per_day=2, shift_duration_h=8,
        equipment_downtime_h=94, worker_absence_h=152)
    assert r.F_calendar == 8760
    assert r.F_nominal == 3984
    assert r.F_equipment == 3890
    assert r.F_workers == 1840
    assert r.F_workers < r.F_equipment


def test_shifts_increase_equipment_hours_not_one_person_hours():
    one = calculate_operating_time_funds(
        working_days_per_year=249, shifts_per_day=1, shift_duration_h=8)
    two = calculate_operating_time_funds(
        working_days_per_year=249, shifts_per_day=2, shift_duration_h=8)
    three = calculate_operating_time_funds(
        working_days_per_year=249, shifts_per_day=3, shift_duration_h=8)
    assert (one.F_nominal, two.F_nominal, three.F_nominal) == (1992, 3984, 5976)
    assert (one.F_workers, two.F_workers, three.F_workers) == (1992, 1992, 1992)
    assert all(0 <= x.F_equipment <= x.F_nominal <= x.F_calendar
               for x in (one, two, three))


def test_real_days_and_hours_change_funds():
    r = calculate_operating_time_funds(
        working_days_per_year=200, shifts_per_day=3, shift_duration_h=7.5,
        equipment_downtime_h=200, worker_absence_h=80)
    assert r.F_nominal == 4500
    assert r.F_equipment == 4300
    assert r.F_workers == 1420


def test_four_six_hour_shifts_are_possible_not_four_eight_hour_shifts():
    r = calculate_operating_time_funds(
        working_days_per_year=365, shifts_per_day=4, shift_duration_h=6)
    assert r.F_equipment == 8760
    assert r.F_workers == 2190
    with pytest.raises(ValueError):
        calculate_operating_time_funds(
            working_days_per_year=365, shifts_per_day=4, shift_duration_h=8)


@pytest.mark.parametrize("kw", [
    {"working_days_per_year": 366},
    {"working_days_per_year": 0},
    {"working_days_per_year": 100.5},
    {"shifts_per_day": 0},
    {"shifts_per_day": True},
    {"shift_duration_h": float("nan")},
    {"shift_duration_h": float("inf")},
    {"shift_duration_h": 0},
    {"equipment_downtime_h": -1},
    {"equipment_downtime_h": 5000},
    {"worker_absence_h": -1},
    {"worker_absence_h": 3000},
])
def test_invalid_calendar_is_rejected(kw):
    args = dict(working_days_per_year=249, shifts_per_day=2,
                shift_duration_h=8)
    args.update(kw)
    with pytest.raises(ValueError):
        calculate_operating_time_funds(**args)


def test_project_file_preserves_calendar_inputs_not_calculated_funds(tmp_path):
    p = Project(
        working_days_per_year=200, shifts_per_day=3, shift_duration_h=7.5,
        equipment_downtime_h_per_year=135,
        worker_absence_h_per_year=64,
        time_funds_verified=True,
        time_funds_calendar_applied=True)
    f = tmp_path / "calendar.fpro.json"
    write_project(f, p)
    raw = json.loads(f.read_text(encoding="utf-8"))
    assert "time_funds_calendar_applied" not in raw["project"]
    loaded = read_project(f).project
    assert loaded.equipment_downtime_h_per_year == 135
    assert loaded.worker_absence_h_per_year == 64
    assert loaded.time_funds_verified
    assert not loaded.time_funds_calendar_applied


@pytest.mark.parametrize("kw", [
    {"shifts_per_day": 4, "shift_duration_h": 8},
    {"working_days_per_year": 366},
    {"equipment_downtime_h_per_year": 10000},
    {"worker_absence_h_per_year": -1},
])
def test_invalid_calendar_does_not_overwrite_project(tmp_path, kw):
    f = tmp_path / "safe.fpro.json"
    write_project(f, Project())
    previous = f.read_bytes()
    p = Project()
    for k, v in kw.items():
        setattr(p, k, v)
    with pytest.raises(ProjectFileError):
        write_project(f, p)
    assert f.read_bytes() == previous


def test_workforce_uses_one_person_fund_without_shift_division():
    p = Project(working_days_per_year=350, shifts_per_day=3,
                shift_duration_h=8)
    f = calculate_operating_time_funds(
        working_days_per_year=350, shifts_per_day=3, shift_duration_h=8)
    p.F_equipment_h = f.F_equipment
    p.F_workers_h = f.F_workers
    p.time_funds_calendar_applied = True
    actual = calc_workforce(p, melting={"furnace_count": 3})
    assert actual.fund_workers_h == 2800
    assert actual.fund_equipment_h == 8400
    assert not (actual.fund_workers_h == 2800 / 3)
