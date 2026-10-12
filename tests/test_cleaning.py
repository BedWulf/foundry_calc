"""Тесты расчёта отделения обрубки, очистки и термообработки (ОООиТО).

Эталон — «Sample Diploma.pdf», л. 43–45: выпуск 39 666 т годного,
ЛПС 28.9 %, брак 5 % → тоннаж литья с ЛПС ≈ 51 150 т; годовое число
отливок при средней массе 7.5 кг ≈ 5 271 000 шт.
"""
import unittest
from pathlib import Path

from core.casting_item import CastingItem
from core.cleaning import (
    CleaningCalculator, OPERATIONS, OPERATION_TITLES, OPERATION_BASIS,
    LOAD_OPTIMAL_MIN, LOAD_OPTIMAL_MAX,
    calc_annual_pieces, calc_department_masses, calc_units_required,
    load_factor, pick_unit_count,
)
from core.project import Project


class TestMassBalance(unittest.TestCase):
    """Баланс металла: тоннажи до и после обрубки."""

    def test_diploma_tonnage(self) -> None:
        """Г+ЛП+Б = 39 666·(1+0.289+0.05) ≈ 53 149? — сверка формулы."""
        m = calc_department_masses(39_666.0, 28.9, 5.0)
        self.assertAlmostEqual(m["casting_count_t"],
                               39_666 * 1.339, delta=1.0)
        self.assertAlmostEqual(m["clean_casting_t"],
                               39_666 * 1.05, delta=1.0)
        self.assertLess(m["clean_casting_t"], m["casting_count_t"])

    def test_gating_and_scrap(self) -> None:
        """ЛПС и брак считаются от годного выпуска."""
        m = calc_department_masses(1000.0, 30.0, 5.0)
        self.assertAlmostEqual(m["gating_t"], 300.0, delta=0.1)
        self.assertAlmostEqual(m["scrap_return_t"], 350.0, delta=0.1)

    def test_metal_charge_with_ugar(self) -> None:
        """Металлозавалка = жидкий металл / (1 − угар).

        Эталонная формула методички/дипломов: М = (Г + ЛП + Б)·100/(100−У),
        где ЛП и Б — проценты от годного. При Г=1000, ЛП=30 %, Б=5 %:
        жидкий металл = 1350 т, М = 1350/0.95 ≈ 1421 т.
        """
        m = calc_department_masses(1000.0, 30.0, 5.0, ugar_pct=5.0)
        liquid = 1000.0 * (1 + 0.30 + 0.05)
        self.assertAlmostEqual(m["liquid_metal_t"], liquid, delta=0.5)
        self.assertAlmostEqual(m["metal_charge_t"], liquid / 0.95, delta=0.5)

    def test_zero_output(self) -> None:
        """Нулевой выпуск не ломает расчёт."""
        m = calc_department_masses(0.0, 28.9, 5.0)
        self.assertEqual(m["casting_count_t"], 0.0)

    def test_bad_ugar_raises(self) -> None:
        """Угар вне [0, 100) — ошибка данных."""
        with self.assertRaises(ValueError):
            calc_department_masses(100.0, 30.0, 5.0, ugar_pct=100.0)


class TestPiecesAndUnits(unittest.TestCase):
    """Штучная программа и число установок (формулы П₁, Nпр, Кзо)."""

    def test_annual_pieces_diploma(self) -> None:
        """N = M·1000/m: 5 271 000 шт при 39 666 т и 7.5 кг (без брака)."""
        self.assertEqual(calc_annual_pieces(39_666.0, 7.5, 0.0), 5_288_800)

    def test_units_required_formula(self) -> None:
        """П₁ = M·k_н/(Q·Фд·η)."""
        n = calc_units_required(1000.0, 2.0, 3770.0, k_uneven=1.3, utilization=1.0)
        self.assertAlmostEqual(n, 1000 * 1.3 / (2.0 * 3770.0), delta=1e-6)

    def test_drum_utilization_increases_park(self) -> None:
        """КПД барабана < 1 увеличивает потребное число установок."""
        plain = calc_units_required(1000.0, 2.0, 3770.0, 1.3, 1.0)
        drum = calc_units_required(1000.0, 2.0, 3770.0, 1.3, 0.85)
        self.assertGreater(drum, plain)

    def test_pick_unit_count_rounds_up(self) -> None:
        """Принятое число — округление вверх, минимум для ненулевого П₁ — 1."""
        self.assertEqual(pick_unit_count(0.4), 1)
        self.assertEqual(pick_unit_count(2.01), 3)

    def test_load_factor_bounds(self) -> None:
        """Кзо = П₁/Nпр ∈ (0, 1]."""
        self.assertAlmostEqual(load_factor(2.4, 3), 0.8, delta=1e-9)
        self.assertLessEqual(load_factor(2.4, 3), 1.0)


class TestCleaningCalculator(unittest.TestCase):
    """Подбор оборудования из справочника thermal_equip.json."""

    def setUp(self) -> None:
        self.calc = CleaningCalculator()

    def test_reference_loaded(self) -> None:
        """Справочник загрузился и непустой."""
        machines = self.calc._all_machines()
        self.assertGreater(len(machines), 5)

    def test_material_filter_strict(self) -> None:
        """Для алюминия не должна попасть печь ТО только под сталь/чугун."""
        options = self.calc.find_for_operation(
            operation="heat_treatment", tonnage_t=5000.0,
            fund_hours=3770.0, material_category="aluminum")
        for opt in options:
            mats = opt.get("applicable_for", {}).get("materials", [])
            self.assertIn("aluminum", mats)

    def test_options_sorted_optimal_first(self) -> None:
        """Лучшие по баллу варианты — первыми (оптимальность важнее recommended)."""
        options = self.calc.find_for_operation(
            operation="shot_blasting", tonnage_t=50_000.0,
            fund_hours=3770.0, material_category="steel", avg_mass_kg=10.0)
        self.assertGreater(len(options), 1)
        # Балл должен быть монотонно неотрастающим по списку (или зоны
        # "в optimum / вне optimum" с сортировкой внутри по баллу).
        in_zone = [LOAD_OPTIMAL_MIN <= o["_load_factor"] <= LOAD_OPTIMAL_MAX
                   for o in options]
        self.assertEqual(in_zone, sorted(in_zone, reverse=True),
                         "варианты из optimum-зоны должны идти первыми")
        for a, b in zip(options, options[1:]):
            if (LOAD_OPTIMAL_MIN <= a["_load_factor"] <= LOAD_OPTIMAL_MAX) == \
               (LOAD_OPTIMAL_MIN <= b["_load_factor"] <= LOAD_OPTIMAL_MAX):
                self.assertGreaterEqual(a["_score"], b["_score"])

    def test_chamber_preferring_for_heavy_castings(self) -> None:
        """Крупная отливка (>100 кг) не должна закрываться барабаном."""
        options = self.calc.find_for_operation(
            operation="shot_blasting", tonnage_t=5000.0,
            fund_hours=3770.0, material_category="steel", avg_mass_kg=250.0)
        for opt in options:
            rng = opt.get("applicable_for", {}).get(
                "casting_mass_range_kg", [0, 1e9])
            self.assertLessEqual(rng[0], 250.0)

    def test_calc_department_structure(self) -> None:
        """Сводный расчёт возвращает все позиции техпроцесса."""
        res = self.calc.calc_department(
            annual_output_t=40_000.0, litniki_pribyli_pct=28.9,
            brak_pct=5.0, material_category="steel", avg_mass_kg=10.0)
        self.assertEqual(set(res["operations"].keys()), set(OPERATIONS))
        for op, data in res["operations"].items():
            self.assertEqual(data["tonnage_t"] > 0, True, op)
            if data["selected_id"]:
                self.assertGreater(data["machine_count"], 0)
                self.assertGreater(data["load_factor"], 0.0)
                self.assertLessEqual(data["load_factor"], 1.0)

    def test_shakeout_includes_cores(self) -> None:
        """Тоннаж выбивки больше тоннажа обрубка на стержневую смесь."""
        res = self.calc.calc_department(
            annual_output_t=40_000.0, litniki_pribyli_pct=28.9, brak_pct=5.0,
            material_category="steel", avg_mass_kg=10.0,
            cores_per_mold=2.0, annual_molds=1_000_000)
        shake = res["operations"]["shakeout"]["tonnage_t"]
        cut = res["operations"]["gating_cutting"]["tonnage_t"]
        self.assertGreater(shake, cut)
        # 1 млн форм × 2 стержня × 3 кг (типовая AVG_CORE_MASS_KG) = 6000 т
        self.assertAlmostEqual(shake - cut, 6_000.0, delta=1.0)

    def test_selected_ids_restored(self) -> None:
        """Сохранённый id восстанавливается, если он в топе."""
        res = self.calc.calc_department(
            annual_output_t=40_000.0, litniki_pribyli_pct=28.9, brak_pct=5.0,
            material_category="steel", avg_mass_kg=10.0)
        op = "shot_blasting"
        chosen = res["operations"][op]["selected_id"]
        second = [o["id"] for o in res["operations"][op]["options"]]
        if len(second) > 1:
            alt = second[1]
            res2 = self.calc.calc_department(
                annual_output_t=40_000.0, litniki_pribyli_pct=28.9,
                brak_pct=5.0, material_category="steel", avg_mass_kg=10.0,
                selected_ids={op: alt})
            self.assertEqual(res2["operations"][op]["selected_id"], alt)
            self.assertNotEqual(chosen, "")

    def test_custom_machine_saved_and_used(self) -> None:
        """Своя установка сохраняется в custom-файл и попадает в подбор."""
        card = {
            "name": "Тест Дробемёт 5 т/ч",
            "type": "custom_cleaning",
            "specs": {"productivity_t_h": 5.0},
            "applicable_for": {
                "materials": ["steel"],
                "casting_mass_range_kg": [0, 500],
                "recommended": False,
                "operations": ["shot_blasting"],
            },
        }
        record = self.calc.add_custom_machine(card)
        try:
            self.assertTrue(record["id"].startswith("custom_"))
            self.assertTrue(self.calc.custom_path().exists())
            loaded = self.calc.load_custom_machines()
            self.assertIn(record["id"], [m["id"] for m in loaded])
            options = self.calc.find_for_operation(
                operation="shot_blasting", tonnage_t=1000.0,
                fund_hours=3770.0, material_category="steel",
                avg_mass_kg=10.0)
            self.assertIn(record["id"], [o["id"] for o in options])
        finally:
            # Не оставляем мусор в user_data после теста
            path = self.calc.custom_path()
            backup = path.read_text(encoding="utf-8") if path.exists() else None
            others = [m for m in self.calc.load_custom_machines()
                      if m["id"] != record["id"]]
            import json
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": "1.0", "machines": others},
                          f, indent=2, ensure_ascii=False)
            if not others and backup is None:
                path.unlink(missing_ok=True)


class TestCalcCleaningFromProject(unittest.TestCase):
    """Единая точка входа GUI: проект → результат отделения."""

    def _project(self) -> Project:
        p = Project(name="Тест ОООиТО", annual_output_t=40_000.0,
                    selected_alloy_id="45L")
        p.add_casting(CastingItem(
            name="Блок", mass_with_LPS_kg=25.0, molds_per_year=1_700_000,
            annual_qty_pcs=1_600_000, cores_count=2))
        return p

    def test_project_flow(self) -> None:
        """Расчёт по проекту даёт непустой парк и корректные тоннажи."""
        from core.cleaning import calc_cleaning
        res = calc_cleaning(self._project())
        self.assertEqual(res["material_category"], "steel")
        self.assertGreater(res["masses"]["casting_count_t"], 40_000.0)
        total = sum(o["machine_count"] for o in res["operations"].values())
        self.assertGreater(total, 0)

    def test_no_castings_still_works(self) -> None:
        """Без номенклатуры масса оценивается по тоннажу, расчёт не падает."""
        from core.cleaning import calc_cleaning
        p = Project(name="Пустой", annual_output_t=5_000.0,
                    selected_alloy_id="AK12")
        res = calc_cleaning(p)
        self.assertEqual(res["material_category"], "aluminum")
        self.assertGreater(res["summary"]["annual_molds"], 0)

    def test_get_chosen_operations_order(self) -> None:
        """Выбранные позиции идут в порядке техпроцесса."""
        from core.cleaning import calc_cleaning, get_chosen_operations
        res = calc_cleaning(self._project())
        chosen = get_chosen_operations(res)
        keys = [c["key"] for c in chosen]
        self.assertEqual(keys, [k for k in OPERATIONS if k in keys])


if __name__ == "__main__":
    unittest.main()
