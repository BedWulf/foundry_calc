"""Тесты смесеприготовительного отделения (core/sand_prep.py).

Проверяют эталонные формулы раздела 6 методички, фильтрацию по
материалу/операции, скоринг (оптимальность важнее recommended),
восстановление выбора пользователя и разбор объёма опок.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from core.casting_item import CastingItem
from core.project import Project
from core.sand_prep import (
    SandPrepCalculator,
    calc_sand_prep,
    calc_sand_volumes,
    load_factor,
    machine_productivity,
    pick_unit_count,
    to_picker_options,
    _flask_volume_m3,
    LOAD_OPTIMAL_MIN,
    LOAD_OPTIMAL_MAX,
)


# ---------------------------------------------------------------- helpers
def make_project(with_castings: bool = True) -> Project:
    """Собрать проект с типовой номенклатурой (сталь, АФЛ-параметры).

    Args:
        with_castings: добавить ли позиции номенклатуры

    Returns:
        Модель Project
    """
    project = Project()
    project.selected_alloy_id = "steel_45L"
    if with_castings:
        item = CastingItem(
            index=1, name="Блок", mass_with_LPS_kg=480.0,
            annual_qty_pcs=9000, brak_pct=5.0,
            flask_size_mm="1200x1000x400/400", molds_per_year=12000,
            cores_count=2, core_mass_kg=25.0,
        )
        project.add_casting(item)
    return project


CALC = SandPrepCalculator()


# ---------------------------------------------------------------- unit count
def test_pick_unit_count_diploma_example():
    """Диплом 2: n = 5.31 → Рд = 7, кз ≈ 0.76 (в optimum-зоне)."""
    units = pick_unit_count(5.31)
    assert units == 7
    assert abs(load_factor(5.31, units) - 0.759) < 0.01


def test_pick_unit_count_small_and_zero():
    """Малые n дают 1 единицу; нулевой запрос — 0 единиц."""
    assert pick_unit_count(0.4) == 1
    assert pick_unit_count(0.0) == 0
    assert load_factor(0.4, 1) == pytest.approx(0.4)


def test_load_factor_never_exceeds_cap():
    """Кзо при любом n не превышает верх зоны 0.85."""
    for n in [0.3, 1.1, 2.7, 5.31, 9.9, 13.4]:
        units = pick_unit_count(n)
        assert load_factor(n, units) <= LOAD_OPTIMAL_MAX + 1e-9


# ---------------------------------------------------------------- volumes
def test_calc_sand_volumes_geometry():
    """Объём смеси = объём опки минус металл и стержни, пересчёт в неуплотнёнку."""
    res = calc_sand_volumes(
        annual_molds=1000, mold_volume_m3=1.0,
        metal_per_mold_kg=780.0, cores_mass_per_mold_kg=155.0)
    # занятый объём: 780 кг стали = 0.1 м3, 155 кг ГТС = 0.1 м3
    assert res["sand_volume_tamped_m3"] == pytest.approx(800.0, rel=1e-6)
    assert res["sand_volume_loose_m3"] == pytest.approx(
        800.0 * 1.8 / 1.25, rel=1e-6)
    assert res["mold_volume_total_m3"] == pytest.approx(1000.0)


def test_calc_sand_volumes_empty_program():
    """Пустая программа → нули, без деления на ноль."""
    res = calc_sand_volumes(0, 0.5, 10.0, 1.0)
    assert all(v == 0.0 for v in res.values())


# ---------------------------------------------------------------- filtering
def test_find_for_operation_filters_by_operation_and_material():
    """Подбор возвращает только установки своей операции и материала."""
    options = CALC.find_for_operation(
        operation="molding_mix", quantity=20000.0,
        material_category="steel", working_hours=3890.0)
    assert options, "для стали должна найтись хотя бы одна бегун-смесь"
    assert all(o["operation"] == "molding_mix" for o in options)
    for o in options:
        mats = o.get("applicable_for", {}).get("materials", [])
        assert not mats or "steel" in mats


def test_sorted_optimal_first_not_recommended_first():
    """Первая карточка — с Кзо ближе всего к optimum-зоне (дипломы — примеры)."""
    options = CALC.find_for_operation(
        operation="sieving", quantity=25000.0,
        material_category="steel", working_hours=3890.0)
    assert len(options) >= 2

    def distance_to_zone(lf: float) -> float:
        if lf < LOAD_OPTIMAL_MIN:
            return LOAD_OPTIMAL_MIN - lf
        if lf > LOAD_OPTIMAL_MAX:
            return lf - LOAD_OPTIMAL_MAX
        return 0.0

    best = min(options, key=lambda o: distance_to_zone(o["_load_factor"]))
    assert options[0]["_score"] >= best["_score"] - 1e-9


def test_scores_are_descending():
    """Список отсортирован по убыванию балла скоринга."""
    options = CALC.find_for_operation(
        operation="core_mix", quantity=500.0,
        material_category="cast_iron", working_hours=3890.0)
    scores = [o["_score"] for o in options]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------- department
def test_calc_department_structure():
    """Сводный расчёт возвращает все 6 позиций, тоннажи и парк."""
    result = CALC.calc_department(
        annual_output_t=46000.0, annual_molds=120000,
        mold_volume_m3=0.216, metal_per_mold_kg=500.0,
        material_category="steel")
    ops = {o["operation"]: o for o in result["operations"]}
    assert set(ops) == {"molding_mix", "core_mix", "lumps", "sieving",
                        "cooling", "magnetic_separation"}
    assert ops["molding_mix"]["quantity"] > 0
    assert result["summary"]["total_park_units"] >= 1
    # комья = 10% массы уплотнённой формовочной смеси
    expected_lumps = round(result["volumes"]["sand_mass_tamped_t"] * 0.10, 1)
    assert ops["lumps"]["quantity"] == pytest.approx(expected_lumps, abs=0.2)


def test_calc_department_respects_selected_ids():
    """Сохранённый id пользователя восстанавливается вместо top-1."""
    full = CALC.calc_department(
        annual_output_t=46000.0, annual_molds=120000,
        mold_volume_m3=0.216, metal_per_mold_kg=500.0,
        material_category="steel")
    sieve_ops = next(o for o in full["operations"]
                     if o["operation"] == "sieving")
    if len(sieve_ops["options"]) < 2:
        pytest.skip("в справочнике одно просевающее сито")
    second_id = sieve_ops["options"][1]["id"]
    again = CALC.calc_department(
        annual_output_t=46000.0, annual_molds=120000,
        mold_volume_m3=0.216, metal_per_mold_kg=500.0,
        material_category="steel",
        selected_ids={"sieving": second_id})
    restored = next(o for o in again["operations"]
                    if o["operation"] == "sieving")
    assert restored["selected_id"] == second_id


def test_stale_selection_falls_back_to_best():
    """Если сохранённого id нет среди кандидатов — берётся лучший."""
    result = CALC.calc_department(
        annual_output_t=46000.0, annual_molds=120000,
        mold_volume_m3=0.216, metal_per_mold_kg=500.0,
        material_category="steel",
        selected_ids={"molding_mix": "no_such_machine"})
    mix_op = next(o for o in result["operations"]
                  if o["operation"] == "molding_mix")
    assert mix_op["selected_id"] == mix_op["options"][0]["id"]


# ---------------------------------------------------------------- project glue
def test_flask_volume_parsing():
    """Размер опки «1200x1000x400/400» → 0.96 м³ (полная высота 800 мм)."""
    item = CastingItem(flask_size_mm="1200x1000x400/400")
    assert _flask_volume_m3(item) == pytest.approx(0.96, rel=1e-9)
    bad = CastingItem(flask_size_mm="нестандарт")
    assert _flask_volume_m3(bad) == 0.0


def test_calc_sand_prep_from_project():
    """Единая точка входа для GUI считает объёмы из номенклатуры проекта."""
    project = make_project()
    result = calc_sand_prep(project)
    vols = result["volumes"]
    # 12000 форм × 0.96 м³ = 11520 м³ геометрии
    assert vols["mold_volume_total_m3"] == pytest.approx(11520.0, rel=1e-6)
    assert vols["sand_volume_loose_m3"] > 0
    summary = result["summary"]
    assert summary["annual_molds"] == 12000
    # 2 стержня × 25 кг на форму → 60 т стержней в год
    assert summary["cores_mass_t"] == pytest.approx(600.0, rel=1e-3)


def test_calc_sand_prep_empty_project_no_crash():
    """Проект без номенклатуры не роняет расчёт."""
    project = make_project(with_castings=False)
    result = calc_sand_prep(project)
    assert result["summary"]["annual_molds"] == 0
    assert all(o["quantity"] == 0 for o in result["operations"])


# ---------------------------------------------------------------- picker glue
def test_to_picker_options_fields():
    """Карточки содержат поля, нужные EquipmentPicker."""
    options = CALC.find_for_operation(
        operation="molding_mix", quantity=20000.0,
        material_category="steel", working_hours=3890.0)
    cards = to_picker_options(options)
    assert cards
    for card in cards:
        assert card["id"] and card["name"]
        assert "count" in card and "load_factor" in card
        assert card["productivity"].endswith(("м³/ч", "т/ч")) or \
            "–" in card["productivity"]


def test_machine_productivity_generic_fallback():
    """Пользовательская карточка с generic-полем productivity учитывается."""
    machine: Dict[str, Any] = {
        "unit": "m3_h",
        "specs": {"productivity": 12.0},
    }
    assert machine_productivity(machine) == 12.0
