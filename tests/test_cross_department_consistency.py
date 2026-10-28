"""Cross-department engineering status: no fake complete plant from partial molding."""
from core.areas import calc_areas
from core.workforce import calc_workforce
from core.summary import build_summary
from core.project import Project
from core.casting_item import CastingItem


def _project():
    p = Project(name="Недоступная оснастка", annual_output_t=1000.0)
    p.castings = [CastingItem(
        name="Корпус", mass_with_LPS_kg=20, annual_qty_pcs=100,
        molds_per_year=100, flask_size_mm="9999x8888x300/400",
    )]
    return p


def test_areas_flag_incomplete_molding_park():
    p = _project()
    res = calc_areas(p, warehouse_area_m2=0.0)
    assert not res.complete
    assert res.warnings
    assert not [d for d in res.rows if d.key == "molding_tab"]
    assert res.as_dict()["complete"] is False


def test_workforce_never_invents_operator_for_infeasible_plan():
    p = _project()
    result = calc_workforce(p, molding={
        "annual_molds_total": 100,
        "line_count": 0,
        "batch_plan_feasible": False,
    })
    assert not result.complete
    assert result.total == 0
    assert result.warnings


def test_summary_blocks_incomplete_building_and_workforce():
    p = _project()
    res = build_summary({
        "molding": {"annual_molds_total": 100, "line_count": 0,
                    "batch_plan_feasible": False, "batch_planning_error": "Опока"},
        "areas": {"building_total_m2": 12345, "complete": False,
                  "warnings": ["Нет формовочной линии"]},
        "workforce": {"total": 999, "complete": False,
                      "warnings": ["Нет парка"]},
    }, p)
    assert not res.ready
    assert res.building_area_m2 == 0
    assert res.workforce_total == 0
    assert not any(row.department == "Формовочное" for row in res.rows)
    assert any("Опока" in message for message in res.warnings)


def test_summary_preserves_two_different_line_models():
    p = Project(name="Два типоразмера")
    res = build_summary({"molding": {
        "annual_molds_total": 1000, "batch_plan_feasible": True,
        "park": [
            {"name": "АФЛ А", "units": 2, "load_factor": .7},
            {"name": "АФЛ Б", "units": 3, "load_factor": .8},
        ],
    }}, p)
    rows = [r for r in res.rows if r.department == "Формовочное"]
    assert len(rows) == 2
    assert sum(row.units for row in rows) == 5
    assert {row.equipment for row in rows} == {"АФЛ А", "АФЛ Б"}
