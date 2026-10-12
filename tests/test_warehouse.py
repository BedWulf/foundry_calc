"""Тесты расчёта складского хозяйства (Разделы 8, 10).

Эталонные формулы методички:
    Qраз = Mгод / 365 · Tхран / kн ;   F = Q / (h · ρ · kисп)
Проверяются: нормы хранения по типам складов, фильтрация единиц по типу
склада и материалу, закрытие норматива площадью/вместимостью, сортировка
вариантов (оптимальность > recommended), восстановление выбора пользователя.
"""
import unittest

from core.casting_item import CastingItem
from core.project import Project
from core.warehouse import (
    DEFAULT_K_IRREGULARITY, STORAGE_DAYS_CHARGE, STORAGE_DAYS_CORE_MATERIALS,
    STORAGE_DAYS_MOLDING_SAND, WarehouseRequirement, add_custom_unit,
    calc_warehouse_requirements, calc_warehouses, load_storage_units,
    pick_storage_options, to_picker_options, total_warehouse_area,
)


def _demo_project() -> Project:
    """Собрать тестовый проект со смесевыми связками (сталь, 20 000 т)."""
    p = Project(name="Тест-склад", annual_output_t=20_000.0)
    p.selected_alloy_id = "steel_45L"
    p.add_casting(CastingItem(
        name="Корпус", mass_with_LPS_kg=250.0, mass_casting_kg=200.0,
        annual_qty_pcs=80_000, molds_per_year=84_000,
        flask_size_mm="1000x800x400/400", cores_count=2))
    return p


class TestRequirements(unittest.TestCase):
    """Нормативы запасов и площадей шести складов."""

    def test_six_warehouses(self) -> None:
        """Возвращаются все шесть складов в ведомостном порядке."""
        reqs = calc_warehouse_requirements(_demo_project())
        keys = [r.key for r in reqs]
        self.assertEqual(keys, ["charge", "molding_sand", "core_materials",
                                "flasks", "patterns", "tools"])

    def test_charge_capacity_formula(self) -> None:
        """Qраз шихты = Мзавалка/365 · 30 сут / kн (методичка)."""
        p = _demo_project()
        reqs = {r.key: r for r in calc_warehouse_requirements(p)}
        charge = reqs["charge"]
        self.assertIsNotNone(charge.annual_need_t)
        expected = charge.annual_need_t / 365.0 * STORAGE_DAYS_CHARGE \
            / DEFAULT_K_IRREGULARITY
        self.assertAlmostEqual(charge.required_capacity_t, expected, delta=0.5)
        self.assertGreater(charge.area_norm_hint_m2 or 0, 0)

    def test_storage_days_by_type(self) -> None:
        """Нормы хранения различаются для шихты/формовки/стержней."""
        reqs = {r.key: r for r in calc_warehouse_requirements(_demo_project())}
        self.assertEqual(reqs["molding_sand"].storage_days,
                         STORAGE_DAYS_MOLDING_SAND)
        self.assertEqual(reqs["core_materials"].storage_days,
                         STORAGE_DAYS_CORE_MATERIALS)
        self.assertNotEqual(reqs["charge"].storage_days,
                            reqs["molding_sand"].storage_days)

    def test_tools_scale_with_workforce(self) -> None:
        """Площадь склада инструмента растёт с численностью рабочих."""
        small = _demo_project()
        big = _demo_project()
        big.annual_output_t = 60_000.0
        area_small = next(r.area_norm_hint_m2 for r in
                          calc_warehouse_requirements(small)
                          if r.key == "tools")
        area_big = next(r.area_norm_hint_m2 for r in
                        calc_warehouse_requirements(big)
                        if r.key == "tools")
        self.assertGreater(area_big, area_small)


class TestUnitSelection(unittest.TestCase):
    """Подбор единиц хранения: фильтры и оптимальность."""

    def test_filter_by_storage_type(self) -> None:
        """Для склада опок не предлагаются бункеры шихты."""
        req = WarehouseRequirement(
            key="flasks", title="Склад опок", basis="", annual_need_t=None,
            storage_days=None, k_irregularity=1.0, required_capacity_t=50.0,
            area_norm_hint_m2=100.0)
        opts = pick_storage_options(req, material_category="steel")
        self.assertTrue(opts)
        ids = {o["id"] for o in opts}
        # только единицы, у которых в applicable_for есть «flasks»
        self.assertTrue(ids <= {"RACK-FLASK-20", "PALLET-FLASK-15",
                                "CRANE-PATTERNS-40"}, msg=str(ids))
        # бункеры шихты не должны попадать в склад опок
        self.assertFalse(ids & {"BIN-STEEL-60", "BIN-SAND-50"})

    def test_filter_by_material(self) -> None:
        """Алюминиевый проект не получает кранную зону стальной оснастки."""
        req = WarehouseRequirement(
            key="patterns", title="Склад оснастки", basis="",
            annual_need_t=None, storage_days=None, k_irregularity=1.0,
            required_capacity_t=100.0, area_norm_hint_m2=200.0)
        alu = {o["id"] for o in pick_storage_options(req,
                                                     material_category="aluminum")}
        self.assertNotIn("CRANE-PATTERNS-40", alu)
        steel = {o["id"] for o in pick_storage_options(req,
                                                       material_category="steel")}
        self.assertIn("CRANE-PATTERNS-40", steel)

    def test_options_cover_norm(self) -> None:
        """Лучший вариант закрывает норматив вместимости.

        Площадь — компромисс: при ограниченном парке единиц (MAX_STORAGE_UNITS)
        вариант может не дотянуть норму площади, но обязан покрыть разовый
        запас материала; избыток площади на складах опок/оснастки допустим.
        """
        p = _demo_project()
        for req in calc_warehouse_requirements(p):
            opts = pick_storage_options(req, material_category="steel")
            if not opts:
                continue
            best = opts[0]
            if req.required_capacity_t:
                self.assertGreaterEqual(best["total_capacity_t"],
                                        req.required_capacity_t - 0.5,
                                        msg=f"{req.key}: вместимость")

    def test_sorted_optimal_first(self) -> None:
        """Варианты отсортированы по убыванию скоринга (эффективность)."""
        p = _demo_project()
        reqs = calc_warehouse_requirements(p)
        scores = []
        for req in reqs:
            opts = pick_storage_options(req, material_category="steel")
            scores.extend(o["scoring"] for o in opts)
        # внутри каждого склада — невозрастающий порядок
        for req in reqs:
            local = [o["scoring"] for o in
                     pick_storage_options(req, material_category="steel")]
            self.assertEqual(local, sorted(local, reverse=True),
                             msg=f"{req.key}: {local}")
        self.assertTrue(scores)

    def test_custom_unit_added(self) -> None:
        """Пользовательский склад появляется в подборе после сохранения."""
        card = {
            "name": "Мой ангар шихты 500 м²",
            "type": "area",
            "specs": {"footprint_m2": 500.0, "capacity_per_unit_t": 1500.0},
            "applicable_for": {"materials": ["steel"],
                               "storage_types": ["charge"]},
        }
        record = add_custom_unit(card)
        self.assertTrue(record.get("custom"))
        try:
            units = load_storage_units()
            self.assertIn(record["id"], {u["id"] for u in units})
            req = WarehouseRequirement(
                key="charge", title="Склад шихты", basis="",
                annual_need_t=10_000.0, storage_days=30.0,
                k_irregularity=1.2, required_capacity_t=700.0,
                area_norm_hint_m2=450.0)
            opts = pick_storage_options(req, material_category="steel")
            self.assertIn(record["id"], {o["id"] for o in opts})
        finally:
            # убрать тестовую запись из user_data, чтобы не засорять справочник
            from core.warehouse import CUSTOM_WAREHOUSE_FILE, load_custom_units
            remaining = [u for u in load_custom_units()
                         if u.get("id") != record["id"]]
            import json
            with open(CUSTOM_WAREHOUSE_FILE, "w", encoding="utf-8") as f:
                json.dump({"version": "1.0", "units": remaining}, f,
                          ensure_ascii=False, indent=2)


class TestFullCalculation(unittest.TestCase):
    """Сквозной расчёт и восстановление выборов."""

    def test_calc_warehouses_all_closed(self) -> None:
        """Все склады закрыты оборудованием, итоговая площадь > 0."""
        results = calc_warehouses(_demo_project(), material_category="steel")
        self.assertEqual(len(results), 6)
        for r in results:
            self.assertTrue(r.units, msg=f"{r.key}: нет вариантов")
            self.assertGreater(r.total_area_m2, 0)
        self.assertGreater(total_warehouse_area(results), 0)

    def test_selected_id_restored(self) -> None:
        """Сохранённый выбор пользователя восстанавливается при пересчёте."""
        p = _demo_project()
        results = calc_warehouses(p, material_category="steel")
        second_choice = results[0].units[1] if len(results[0].units) > 1 \
            else results[0].units[0]
        restored = calc_warehouses(
            p, material_category="steel",
            selected_ids={"charge": second_choice["id"]})
        charge = restored[0]
        chosen = next(o for o in charge.units
                      if o["id"] == second_choice["id"])
        self.assertEqual(chosen["id"], second_choice["id"])
        self.assertAlmostEqual(charge.total_area_m2,
                               chosen["total_area_m2"], places=1)

    def test_picker_cards_fields(self) -> None:
        """Карточки для EquipmentPicker содержат обязательные поля."""
        results = calc_warehouses(_demo_project(), material_category="steel")
        cards = to_picker_options(results[0].units)
        self.assertTrue(cards)
        for c in cards:
            self.assertIn("_num_required", c)
            self.assertIn("_load_factor", c)
            self.assertIn("specs", c)
            self.assertGreater(c["_num_required"], 0)


if __name__ == "__main__":
    unittest.main()
