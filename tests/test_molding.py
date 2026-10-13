"""Тесты расчёта формовочного отделения и подбора АФЛ по эталонным дипломам.

Эталон — «Sample Diploma.pdf», л. 24–25 (и продублировано в
«Sample Diploma 2.pdf», л. 23): группа 4 000 т/год, отливка 4 кг с ЛПС →
    Nф.год = 4 000 000 / 4 = 1 000 000 форм;
    Рр     = 1 000 000 / 3 890 ≈ 257 ф/ч;
    ИЛ-225 (q_ном = 240 ф/ч) → П₁ = 257/240 = 1.07 → принято 2 линии,
    Кзо = 0.536 (недогрузка компенсируется догрузкой других групп).
"""
import math
import unittest

from core.casting_item import CastingItem
from core.molding import (
    MoldingCalculator, build_mass_groups, calc_annual_molds, calc_molding,
    calc_lines_count, calc_required_productivity, mass_group_index,
)
from core.project import Project


class TestAflFormulas(unittest.TestCase):
    """Базовые формулы диплома: Nф, Рр, П₁, Кзо."""

    def test_annual_molds_diploma(self) -> None:
        """Nф.год = Г·1000/m_отл: 4 000 т / 4 кг = 1 000 000 форм."""
        self.assertEqual(calc_annual_molds(4000.0, 4.0), 1_000_000)

    def test_annual_molds_with_brak(self) -> None:
        """Допвыпуск на брак 5 % увеличивает число форм пропорционально."""
        self.assertEqual(calc_annual_molds(4000.0, 4.0, brak_pct=5.0), 1_050_000)

    def test_required_productivity_diploma(self) -> None:
        """Рр = Nф/Фд = 1 000 000/3 890 ≈ 257 ф/ч."""
        p = calc_required_productivity(1_000_000, 3890.0)
        self.assertAlmostEqual(p, 257.07, delta=0.1)

    def test_lines_count_il225_diploma(self) -> None:
        """ИЛ-225: П₁ = 1.07 → ceil → 2 линии, Кзо = 0.536."""
        res = calc_lines_count(257.07, 240.0)
        self.assertAlmostEqual(res["p1_required"], 1.071, delta=0.01)
        self.assertEqual(res["count"], 2)
        self.assertAlmostEqual(res["load_factor"], 0.536, delta=0.005)

    def test_lines_count_never_overloaded(self) -> None:
        """Кзо не может превышать 1.0 при любом числе форм."""
        res = calc_lines_count(1000.0, 240.0)   # Рр = 1000 ф/ч
        self.assertLessEqual(res["load_factor"], 1.0)
        self.assertEqual(res["count"], int(math.ceil(1000.0 / 240.0)))

    def test_zero_inputs(self) -> None:
        """Нулевые/отрицательные данные не должны ломать расчёт."""
        self.assertEqual(calc_annual_molds(0, 4), 0)
        self.assertEqual(calc_annual_molds(100, 0), 0)
        self.assertEqual(calc_required_productivity(100, 0), 0.0)
        self.assertEqual(calc_lines_count(100, 0)["count"], 0)


class TestMassGroups(unittest.TestCase):
    """Группы номенклатуры по массе (табл. 7 диплома)."""

    def test_group_bounds(self) -> None:
        """Границы групп: ≤4 / 4–10 / 10–30 / >30 кг."""
        self.assertEqual(mass_group_index(4.0), 0)
        self.assertEqual(mass_group_index(4.1), 1)
        self.assertEqual(mass_group_index(10.0), 1)
        self.assertEqual(mass_group_index(10.1), 2)
        self.assertEqual(mass_group_index(30.0), 2)
        self.assertEqual(mass_group_index(30.1), 3)

    def test_build_mass_groups(self) -> None:
        """Отливки корректно раскладываются по группам с суммами."""
        castings = [
            CastingItem(name="А", mass_with_LPS_kg=2.0, annual_metal_t=100.0),
            CastingItem(name="Б", mass_with_LPS_kg=4.0, annual_metal_t=200.0),
            CastingItem(name="В", mass_with_LPS_kg=8.0, annual_metal_t=300.0),
            CastingItem(name="Г", mass_with_LPS_kg=50.0, annual_metal_t=400.0),
        ]
        groups = build_mass_groups(castings)
        indexes = {g.index for g in groups}
        self.assertEqual(indexes, {0, 1, 3})
        g0 = next(g for g in groups if g.index == 0)
        self.assertEqual(g0.items_count, 2)
        self.assertAlmostEqual(g0.annual_mass_t, 300.0)


class TestLineSelection(unittest.TestCase):
    """Фильтрация линий по материалу и скоринг."""

    def setUp(self) -> None:
        self.calc = MoldingCalculator()

    def test_material_filter_strict(self) -> None:
        """Для алюминия нет стальных/чугунных линий, для стали — алюминиевых."""
        st = self.calc.find_lines("steel", 1_000_000, 3890.0)
        al = self.calc.find_lines("aluminum", 1_000_000, 3890.0)
        self.assertTrue(st and al)
        for o in st:
            self.assertIn("steel", o["applicable_for"]["materials"])
        for o in al:
            self.assertIn("aluminum", o["applicable_for"]["materials"])
        ids_al = {o["id"] for o in al}
        # ИЛ-225 предназначена для стали/чугуна — в алюминии её быть не должно
        self.assertNotIn("IL-225", ids_al)

    def test_top_n_limit(self) -> None:
        """Возвращается не более top_n вариантов."""
        opts = self.calc.find_lines("steel", 1_000_000, 3890.0, top_n=3)
        self.assertLessEqual(len(opts), 3)
        self.assertGreaterEqual(len(opts), 1)

    def test_best_option_first(self) -> None:
        """Список отсортирован по убыванию скоринга (лучший — первый)."""
        opts = self.calc.find_lines("steel", 1_000_000, 3890.0)
        scores = [o["_score"] for o in opts]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_casting_mass_filter(self) -> None:
        """Линия с диапазоном масс меньше массы формы отсеивается."""
        opts = self.calc.find_lines(
            "steel", 100_000, 3890.0, max_casting_mass_kg=500.0)
        for o in opts:
            hi = o["applicable_for"]["casting_mass_range_kg"][1]
            self.assertGreaterEqual(hi, 500.0)


class TestCalcMoldingFacade(unittest.TestCase):
    """Фасад calc_molding: интеграция проекта, справочника и выбора."""

    @staticmethod
    def _project() -> Project:
        p = Project(name="Тест", annual_output_t=37000.0)
        p.selected_alloy_id = "steel_45L"
        p.F_equipment_h = 3890.0
        p.castings = [
            CastingItem(name="Блок", mass_with_LPS_kg=4.0, annual_metal_t=4000.0),
        ]
        return p

    def test_diploma_scenario_end_to_end(self) -> None:
        """Эталон группы 4000 т / 4 кг: 1 млн форм, 257 ф/ч, подбор не пуст."""
        r = calc_molding(self._project())
        self.assertEqual(r.annual_molds_total, 1_000_000)
        self.assertAlmostEqual(r.required_productivity_molds_h, 257.07, delta=0.5)
        self.assertEqual(r.material_category, "steel")
        self.assertTrue(r.line_options)
        self.assertTrue(r.selected_line_id)
        self.assertGreaterEqual(r.line_count, 1)

    def test_selected_line_restores_user_choice(self) -> None:
        """Сохранённый id пользователя возвращается, если линия подходит."""
        project = self._project()
        r = calc_molding(project)
        second = (r.line_options[1]["id"] if len(r.line_options) > 1
                  else r.line_options[0]["id"])
        r2 = calc_molding(project, selected_line_id=second)
        self.assertEqual(r2.selected_line_id, second)
        self.assertEqual(r2.line_count, second and r2.selected_line.get("_num_required"))

    def test_invalid_saved_id_falls_back_to_best(self) -> None:
        """Несуществующий сохранённый id → автовыбор лучшего варианта."""
        r = calc_molding(self._project(), selected_line_id="NO_SUCH_LINE")
        self.assertEqual(r.selected_line_id, r.line_options[0]["id"])

    def test_no_castings_estimate(self) -> None:
        """Без номенклатуры — оценка по средней массе (не падает)."""
        p = Project(name="Пустой", annual_output_t=37000.0)
        p.selected_alloy_id = "cast_iron_sch20"
        r = calc_molding(p)
        self.assertGreater(r.annual_molds_total, 0)
        self.assertEqual(r.material_category, "cast_iron")


if __name__ == "__main__":
    unittest.main()
