"""Core geometry regression: coreless molds are not blank core counts.

Older files may have unspecified fields saved as zero. An explicit
confirmation is therefore required before core capacity is considered
verified for productive zero-core casting rows.
"""
from datetime import date

from core.casting_item import CastingItem
from core.core_making import core_counts_complete
from core.molding import calc_avg_cores_per_mold
from core.plant_capacity import calculate_plant_capacity
from core.project import Project
from core.project_io import read_project, write_project
from core.summary import build_summary


def castings():
    return [
        CastingItem(name="Стержневая", molds_per_year=100, cores_count=2),
        CastingItem(name="Без стержней", molds_per_year=300, cores_count=0),
    ]


def test_weighted_average_includes_real_zero_core_rows():
    items = castings()
    # 100 molds * 2 cores + 300 molds * 0 = 200 / 400 = 0.5.
    assert calc_avg_cores_per_mold(items) == 0.5
    assert calc_avg_cores_per_mold(
        [CastingItem(name="Без стержней", molds_per_year=100,
                     cores_count=0)]) == 0.0


def test_core_data_quality_requires_confirmation_of_zero_values():
    items = castings()
    assert not core_counts_complete(items)
    assert core_counts_complete(items, zeros_confirmed=True)
    assert core_counts_complete([items[0]])
    assert not core_counts_complete([])


def test_unknown_core_counts_do_not_produce_verified_annual_capacity():
    summary = {
        "cores": {
            "annual_cores": None, "annual_cores_lower_bound": 200,
            "core_data_complete": False, "capacity_cores_year": 250,
            "machine_name": "Модель", "machine_count": 1,
        }
    }
    p = Project(castings=castings())
    row = next(r for r in calculate_plant_capacity(summary, p).rows
               if r.department == "Стержневое")
    assert row.demand is None and row.status == "unknown"
    total = build_summary(summary, p)
    assert total.ready is False
    assert any("НЕ ПОДТВЕРЖДЕНО" in w for w in total.warnings)

    summary["cores"]["annual_cores"] = 200
    summary["cores"]["core_data_complete"] = True
    confirmed = next(r for r in calculate_plant_capacity(summary, p).rows
                     if r.department == "Стержневое")
    assert confirmed.status == "ok"
    assert confirmed.demand == 200


def test_confirmation_survives_fpro_project_roundtrip(tmp_path):
    project = Project(
        name="Проверенные стержни", created_at=date(2026, 10, 30),
        castings=castings(), cores_zero_confirmed=True)
    path = tmp_path / "cores.fpro.json"
    write_project(path, project)
    loaded = read_project(path).project
    assert loaded.cores_zero_confirmed is True
    assert core_counts_complete(
        loaded.castings, zeros_confirmed=loaded.cores_zero_confirmed)


def test_old_project_without_confirmation_is_not_silently_trusted(tmp_path):
    import json
    project = Project(castings=castings())
    path = tmp_path / "legacy.fpro.json"
    write_project(path, project)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["project"].pop("cores_zero_confirmed")
    path.write_text(json.dumps(data), encoding="utf-8")
    old = read_project(path).project
    assert old.cores_zero_confirmed is False
    assert not core_counts_complete(
        old.castings, zeros_confirmed=old.cores_zero_confirmed)
