"""Тесты расчёта внутрицехового транспорта (Раздел 12).

Эталонные формулы дипломов:
    К = П · Тц / (Т · n)   — парк транспортных ковшей (формула 5);
    Тц = t_зал + l/0.75 + l/1.00 + t_ожид + t_ост + t_рем + t_сушки (ф-ла 6);
    число мостовых кранов — по нормам длины участка (табл. 16/18).

Проверяются: цикл ковша, баланс жидкого металла, эталоны диплома 1
(55 699 т → 14 рабочих / 19 всего) и диплома 2 (90 720 т → 20 / 26),
нормы кранов, сборка полной ведомости и сохранение выбора пользователя.
"""
import unittest

from core.casting_item import CastingItem
from core.project import Project
from core.transport import (
    CRANE_NORMS_M, DEFAULT_LADLE_CYCLE,
    calc_cranes, calc_ladles, calc_transport, estimate_bay_length_m,
    get_transport_item, ladle_cycle_time_h, load_transport_catalog,
)


def _demo_project() -> Project:
    """Стальной проект тоннажа диплома 1 (~58 932 т завалки)."""
    p = Project(name="Тест-транспорт", annual_output_t=50_000.0)
    p.selected_alloy_id = "steel_45L"
    p.add_casting(CastingItem(
        name="Корпус", mass_with_LPS_kg=36.9, mass_casting_kg=28.0,
        annual_qty_pcs=45_000, molds_per_year=45_000,
        flask_size_mm="1200x1000x350/400", cores_count=1))
    return p


class TestCatalog(unittest.TestCase):
    """Справочник transport.json."""

    def test_catalog_loads(self) -> None:
        """Справочник загружается через config.DATA_DIR и непустой."""
        catalog = load_transport_catalog()
        self.assertGreater(len(catalog), 0)

    def test_required_categories_present(self) -> None:
        """Есть карточки ковшей, кранов и погрузчика."""
        cats = {str(i.get("category")) for i in load_transport_catalog()}
        self.assertIn("ladle", cats)
        self.assertIn("crane", cats)
        self.assertIsNotNone(get_transport_item("FORKLIFT-3T"))

    def test_get_by_id(self) -> None:
        """Поиск карточки по id работает, неизвестный id → None."""
        card = get_transport_item("LADLE-2.5T")
        self.assertIsNotNone(card)
        self.assertEqual(str(card["category"]), "ladle")
        self.assertIsNone(get_transport_item("NO-SUCH-ID"))


class TestLadleCycle(unittest.TestCase):
    """Формула (6): цикл работы ковша.

    Тц = t_зал + l/0.75 + l/1.00 + t_ожид + t_ост + t_рем + t_сушки (мин).
    При l = 20 м путь даёт 20/0.75 + 20/1.00 = 46.67 мин, поэтому
    типовые параметры дипломов дают ~119.7 мин ≈ 2 ч (в дипломе 2
    значение округлено до ровно 120 мин).
    """

    def test_default_cycle_about_2h(self) -> None:
        """Параметры диплома 2 (l=20) дают цикл ≈ 2 ч."""
        self.assertAlmostEqual(ladle_cycle_time_h(), 2.0, delta=0.02)

    def test_diploma1_cycle_137_min(self) -> None:
        """Диплом 1: t_ожид=30 мин → формула даёт 134.7 мин (автор округлил до 137)."""
        params = dict(DEFAULT_LADLE_CYCLE, t_wait_min=30.0)
        cycle_h = ladle_cycle_time_h(params)
        self.assertAlmostEqual(cycle_h, 134.67 / 60.0, places=2)
        # расчёт парка в дипломе 1 ведётся по Тц = 2.28 ч — в пределах
        # разницы между точным значением формулы и округлением автора
        self.assertLess(abs(cycle_h - 2.28), 0.08)


class TestLadleFleet(unittest.TestCase):
    """Формула (5): парк ковшей с ремонтом и резервом."""

    def test_diploma1_reference(self) -> None:
        """Диплом 1: П=55 699.4 т, Тц=2.28 ч, n=2.5 → 14; итого 19."""
        res = calc_ladles(55_699.4, capacity_t=2.5, cycle_time_h=137 / 60.0)
        self.assertEqual(res.working, 14)
        self.assertEqual(res.in_repair, 3)
        self.assertEqual(res.reserve, 2)
        self.assertEqual(res.total, 19)

    def test_diploma2_reference(self) -> None:
        """Диплом 2: П=90 720 т, Тц=2.00 ч, n=2.5 → 20; итого 26."""
        res = calc_ladles(90_720.0, capacity_t=2.5, cycle_time_h=2.0)
        self.assertEqual(res.working, 20)
        self.assertEqual(res.in_repair, 4)
        self.assertEqual(res.reserve, 2)
        self.assertEqual(res.total, 26)

    def test_larger_ladle_fewer_units(self) -> None:
        """Ковш 5 т требует вдвое меньше единиц, чем 2.5 т."""
        small = calc_ladles(55_699.4, capacity_t=2.5, cycle_time_h=2.0)
        big = calc_ladles(55_699.4, capacity_t=5.0, cycle_time_h=2.0)
        self.assertLess(big.working, small.working)

    def test_zero_metal_empty_fleet(self) -> None:
        """Нулевой выпуск → пустой парк без деления на ноль."""
        res = calc_ladles(0.0, capacity_t=2.5, cycle_time_h=2.0)
        self.assertEqual(res.total, 0)


class TestCranes(unittest.TestCase):
    """Мостовые краны по нормам длины участка."""

    def test_norms_table_shape(self) -> None:
        """Нормы заданы диапазоном (lo, hi) для ключевых отделений."""
        for dept in ("melting", "warehouse", "molding", "cleaning"):
            lo, hi = CRANE_NORMS_M[dept]
            self.assertLess(lo, hi)

    def test_melting_48m_two_cranes(self) -> None:
        """Плавильное 48 м при норме 20…30 → 2 крана (верхняя граница)."""
        rows = calc_cranes({"melting": 48.0})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].units, 2)

    def test_warehouse_60m_one_crane(self) -> None:
        """Склад 60 м при норме до 60 м/кран → 1 кран."""
        rows = calc_cranes({"warehouse": 60.0})
        self.assertEqual(rows[0].units, 1)

    def test_unknown_or_zero_dept_skipped(self) -> None:
        """Неизвестное отделение и нулевая длина не дают строк."""
        rows = calc_cranes({"bogus": 50.0, "melting": 0.0})
        self.assertEqual(rows, [])

    def test_estimate_bay_override(self) -> None:
        """Явное project.bay_lengths_m перебивает оценку из площадей."""
        p = _demo_project()
        p.bay_lengths_m = {"melting": 30.0}
        est = estimate_bay_length_m(p)
        self.assertAlmostEqual(est["melting"], 30.0)


class TestFullTransport(unittest.TestCase):
    """Сборка полного расчёта и интеграция."""

    @classmethod
    def setUpClass(cls) -> None:
        """Один полный расчёт на демо-проект."""
        cls.result = calc_transport(_demo_project())

    def test_result_has_all_kinds(self) -> None:
        """Ведомость содержит ковши, краны и конвейеры."""
        kinds = {r.kind for r in self.result.rows}
        self.assertIn("ladle", kinds)
        self.assertIn("crane", kinds)
        self.assertIn("conveyor", kinds)

    def test_ladle_balance_from_charge(self) -> None:
        """Жидкий металл = завалка × (1 − угар/100) > 0, парк посчитан."""
        self.assertIsNotNone(self.result.ladles)
        assert self.result.ladles is not None
        self.assertGreater(self.result.ladles.liquid_metal_t, 0.0)
        self.assertGreater(self.result.ladles.total, 0)

    def test_areas_summed(self) -> None:
        """Итоговая транспортная площадь = краны + прочее > 0."""
        self.assertAlmostEqual(
            self.result.total_area_m2,
            self.result.crane_areas_m2 + self.result.other_areas_m2,
            places=1)
        self.assertGreater(self.result.total_area_m2, 0.0)

    def test_selected_ladle_respected(self) -> None:
        """Выбор пользователя (ковш 1 т) меняет модель и цикл в расчёте."""
        chosen = calc_transport(_demo_project(),
                                selected_ids={"ladle": "LADLE-1.0T"})
        default = calc_transport(_demo_project())
        assert chosen.ladles and default.ladles
        self.assertEqual(str(chosen.ladles.ladle_id), "LADLE-1.0T")
        self.assertAlmostEqual(chosen.ladles.capacity_t, 1.0)
        # цикл карточки LADLE-1.0T = 120 мин против 137 мин у ковша по умолчанию
        self.assertAlmostEqual(chosen.ladles.cycle_time_h, 2.0, places=3)
        self.assertAlmostEqual(default.ladles.cycle_time_h, 137 / 60.0,
                               places=3)

    def test_as_dict_serializable(self) -> None:
        """Результат сериализуется в словарь для UI/экспорта."""
        d = self.result.as_dict()
        self.assertIn("rows", d)
        self.assertIn("ladles", d)
        self.assertIsInstance(d["cranes_total"], int)


if __name__ == "__main__":
    unittest.main()
