"""Manual counts are physical installed equipment, not automatic suggestions."""
import pytest

from core.molding_batch_planner import MoldingJob, plan_molding_batches
from core.project import Project
from core.casting_item import CastingItem
from core.molding import calc_molding
from core.areas import calc_areas
from core.summary import build_summary


def machine(ident, flask="900x600", productivity=100):
    return {
        "id": ident, "name": ident,
        "specs": {
            "flask_size_mm": flask,
            "flask_heights_mm": [200],
            "nominal_productivity_molds_h": productivity,
            "max_mold_metal_kg": 50,
            "installed_power_kw": 100,
        },
        "applicable_for": {"materials": ["steel"],
                           "casting_mass_range_kg": [0, 50]},
    }


def j(name, number, flask="900x600x200"):
    return MoldingJob(name, name, number, flask, "steel", 5, 10)


def test_one_line_schedules_two_castings():
    p = plan_molding_batches([j("A", 60_000), j("B", 70_000)],
                              [machine("L")], 2000, line_counts={"L": 1})
    assert p.feasible
    assert len(p.lines) == 1
    assert p.assigned_molds == 130_000
    assert set(c.job_key for c in p.lines[0].campaigns) == {"A", "B"}


def test_line_count_changes_capacity_and_load():
    jobs = [j("A", 200_000)]
    one = plan_molding_batches(jobs, [machine("L")], 1500,
                               line_counts={"L": 1}, max_load_factor=.8)
    two = plan_molding_batches(jobs, [machine("L")], 1500,
                               line_counts={"L": 2}, max_load_factor=.8)
    assert not one.feasible and one.assigned_molds < 200_000
    assert two.feasible and two.assigned_molds == 200_000
    assert sum(ln.used_hours for ln in two.lines) <= sum(ln.allowed_hours for ln in two.lines)


def test_zero_lines_is_infeasible_not_auto_added():
    p = plan_molding_batches([j("A", 1000)], [machine("L")], 2000,
                             line_counts={"L": 0})
    assert p.lines == []
    assert not p.feasible and p.assigned_molds == 0 and p.unassigned == ["A"]


def test_idle_installed_line_is_counted():
    p = plan_molding_batches([j("A", 10_000)], [machine("L")], 2000,
                             line_counts={"L": 3})
    assert p.feasible and len(p.lines) == 3
    assert sum(bool(x.campaigns) for x in p.lines) == 1
    assert any("простаивающ" in w for w in p.warnings)


def test_two_models_have_independent_counts_and_compatibility():
    jobs = [j("A", 40_000), j("B", 20_000, "1100x750x200")]
    cards = [machine("L1"), machine("L2", "1100x750")]
    p = plan_molding_batches(jobs, cards, 2000,
                             line_counts={"L1": 1, "L2": 2})
    assert p.feasible and len(p.lines) == 3
    assert {ln.equipment_id for ln in p.lines} == {"L1", "L2"}


def test_wrong_flask_height_rejected():
    p = plan_molding_batches([j("A", 100, "900x600x200/250")],
                             [machine("L")], 2000, line_counts={"L": 1})
    assert not p.feasible
    assert p.assigned_molds == 0


@pytest.mark.parametrize("wrong", [{"unknown": 1}, {"L": -1}, {"L": 1.5}, {"L": True}])
def test_invalid_user_quantities_rejected(wrong):
    with pytest.raises(ValueError):
        plan_molding_batches([j("A", 100)], [machine("L")], 2000,
                             line_counts=wrong)


def test_project_manual_mode_does_not_silently_revert_to_auto():
    p = Project()
    p.castings = [
        CastingItem(name="Блок", annual_qty_pcs=1000, molds_per_year=1000,
                    mass_with_LPS_kg=5, flask_size_mm="900x600x200/200"),
    ]
    p.molding_park_mode = "manual"
    p.molding_line_counts = {}
    result = calc_molding(p)
    assert result.batch_plan is not None
    assert not result.batch_plan.feasible
    assert result.batch_plan.assigned_molds == 0


def test_summary_reports_manual_installed_fleet_as_incomplete():
    p = Project()
    p.castings = [CastingItem(name="Test", annual_qty_pcs=10,
                              molds_per_year=10, mass_with_LPS_kg=1)]
    report = build_summary({
        "molding": {
            "batch_plan_feasible": False, "assigned_molds": 8,
            "annual_molds_total": 10, "line_count": 2,
            "park": [{"name": "ИЛ-225", "units": 2, "load_factor": .8}],
        },
    }, p)
    assert not report.ready
    assert sum(row.units for row in report.rows if row.department == "Формовочное") == 2
    assert any("2" in w for w in report.warnings)
