"""Тесты расчёта площадей цеха (Раздел 10).

Эталонная формула методички:
    F_полезн = Σ (кол-во × габаритная площадь места);  F_принят = F/Kисп.
Проверяются: парсинг явных габаритов, типовые нормы для позиций без
размеров, сборка ведомости по принятому оборудованию всех отделений,
добавление складов/подсобок/бытов к зданию цеха.
"""
import unittest

from core.areas import (
    AUX_PRODUCTION_SHARE, SANITARY_SHARE, AreasResult, calc_areas,
    collect_departments, default_unit_area_m2, unit_footprint_m2,
)
from core.casting_item import CastingItem
from core.project import Project


def _demo_project() -> Project:
    """Стальной проект среднего тоннажа (позиции с опками и стержнями)."""
    p = Project(name="Тест-площади", annual_output_t=50_000.0)
    p.selected_alloy_id = "steel_45L"
    p.add_casting(CastingItem(
        name="Корпус", mass_with_LPS_kg=36.9, mass_casting_kg=28.0,
        annual_qty_pcs=45_000, molds_per_year=45_000,
        flask_size_mm="1200x1000x350/400", cores_count=1))
    p.add_casting(CastingItem(
        name="Станина", mass_with_LPS_kg=250.0, mass_casting_kg=200.0,
        annual_qty_pcs=8_000, molds_per_year=8_000,
        flask_size_mm="1600x1200x500/600", cores_count=3))
    return p


class TestFootprint(unittest.TestCase):
    """Извлечение габаритной площади единицы оборудования."""

    def test_explicit_m2_field(self) -> None:
        """Явное поле footprint_m2 имеет приоритет."""
        self.assertAlmostEqual(
            unit_footprint_m2({"id": "X", "footprint_m2": 123.4}), 123.4)

    def test_parse_mm_string(self) -> None:
        """Габариты 'ДхШхВ мм' переводятся в м² (высота игнорируется)."""
        card = {"id": "IL-225", "specs": {"footprint_mm": "65200x9300x6855"}}
        self.assertAlmostEqual(unit_footprint_m2(card), 65.2 * 9.3, delta=0.1)

    def test_default_norm_fallback(self) -> None:
        """Без габаритов берётся укрупнённая норма по id."""
        self.assertAlmostEqual(
            unit_footprint_m2({"id": "IST-6M1"}),
            default_unit_area_m2("IST-6M1"))
        self.assertGreater(default_unit_area_m2("DRUM-42322"), 0.0)
        self.assertGreater(default_unit_area_m2("Sito-175M"), 0.0)
        self.assertEqual(default_unit_area_m2("UNKNOWN-XYZ"), 0.0)


class TestAreasLedger(unittest.TestCase):
    """Ведомость площадей по отделениям проекта."""

    def setUp(self) -> None:
        """Собрать ведомость на демо-проекте один раз."""
        self.deps = collect_departments(_demo_project())
        self.result = calc_areas(_demo_project(),
                                 warehouse_area_m2=4000.0)

    def test_departments_collected(self) -> None:
        """Собираются все ключевые отделения с ненулевой площадью."""
        keys = {d["key"] for d in self.deps}
        # В тестовой номенклатуре две нестандартные опоки без полностью
        # совместимого парка; нельзя добавлять вымышленную линию.
        self.assertNotIn("molding_tab", keys)
        for expected in ("melting_tab", "core_tab",
                         "sand_tab", "cleaning_tab"):
            self.assertIn(expected, keys)
        self.assertFalse(self.result.complete)
        self.assertTrue(self.result.warnings)
        for d in self.deps:
            self.assertGreater(d["count"], 0)
            self.assertGreaterEqual(d["footprint_m2"], 0.0)

    def test_rows_positive_and_rounded_up(self) -> None:
        """Все строки ведомости имеют принятую площадь ≥ полезной."""
        self.assertGreater(len(self.result.rows), 0)
        for r in self.result.rows:
            self.assertGreaterEqual(r.area_m2, r.footprint_m2)
            self.assertEqual(r.area_m2, float(int(r.area_m2)))

    def test_building_totals(self) -> None:
        """Итоги здания: производства + склады + 15 % + 15 %."""
        res: AreasResult = self.result
        prod = sum(r.area_m2 for r in res.rows) + 4000.0
        self.assertAlmostEqual(res.production_total_m2, round(prod, 1),
                               delta=1.0)
        self.assertAlmostEqual(res.aux_repair_m2,
                               prod * AUX_PRODUCTION_SHARE, delta=1.0)
        self.assertAlmostEqual(res.sanitary_m2, prod * SANITARY_SHARE,
                               delta=1.0)
        self.assertAlmostEqual(res.building_total_m2,
                               prod * (1 + AUX_PRODUCTION_SHARE
                                       + SANITARY_SHARE), delta=2.0)

    def test_as_dict_serializable(self) -> None:
        """as_dict возвращает JSON-созвучную структуру для UI/экспорта."""
        d = self.result.as_dict()
        for key in ("rows", "warehouse_area_m2", "production_total_m2",
                    "aux_repair_m2", "sanitary_m2", "building_total_m2"):
            self.assertIn(key, d)
        self.assertIsInstance(d["rows"], list)
        if d["rows"]:
            self.assertIn("area_m2", d["rows"][0])

    def test_empty_project_no_crash(self) -> None:
        """Пустой проект не роняет расчёт (нет данных — пустая ведомость)."""
        res = calc_areas(Project(name="пусто"), warehouse_area_m2=0.0)
        self.assertIsInstance(res, AreasResult)


if __name__ == "__main__":
    unittest.main()
