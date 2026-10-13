"""Тесты расчёта металлозавалки и подбора печей по эталонным дипломам.

Эталон 1 — «Sample Diploma.pdf» (цех стального литья, выпуск 37 000 т/год):
    табл. 6, лист 18: годное 37 000 т + ЛП 16 320 т + брак 2 666 т,
    угар 5 % → завалка М = 58 932 т; лист 21: ИСТ-6М1, P'1 = 5.05,
    принято 6 печей, К_загр ≈ 0.84.
Эталон 2 — «Sample Diploma 2.pdf» (выпуск 64 000 т/год):
    лист 14: М = (64000 + 22400 + 4320)/(100−5)·100 = 95 494 т;
    лист 20: ИСТ-6,0, P'1 = 95494·1.0/(3890·3) = 8.18 → 10 печей, Кзо = 0.81.
"""
import unittest

from core.melting import DIPLOMA_REFERENCE_SCENARIOS, calc_metal_charge
from core.equipment_selector import EquipmentSelector


class TestMetalCharge(unittest.TestCase):
    """Расчёт металлозавалки: формула (1) дипломов."""

    def test_diploma1_exact(self) -> None:
        """Диплом 1: 37 000 т, ЛП 44.1 %, брак 7.2 %, угар 5 % → 58 932 т."""
        m = calc_metal_charge(37000, brak_pct=7.2, litniki_pribyli_pct=44.1)
        self.assertAlmostEqual(m, 58932, delta=10)

    def test_diploma2_exact(self) -> None:
        """Диплом 2: 64 000 т, ЛП 35 %, брак 6.75 %, угар 5 % → 95 494 т."""
        m = calc_metal_charge(64000, brak_pct=6.75, litniki_pribyli_pct=35.0)
        self.assertAlmostEqual(m, 95494, delta=10)

    def test_reference_scenarios_self_consistent(self) -> None:
        """Пресеты DIPLOMA_REFERENCE_SCENARIOS воспроизводят ожидаемую завалку."""
        for key, sc in DIPLOMA_REFERENCE_SCENARIOS.items():
            with self.subTest(scenario=key):
                m = calc_metal_charge(
                    sc["annual_output_t"],
                    brak_pct=sc["brak_pct"],
                    litniki_pribyli_pct=sc["litniki_pribyli_pct"],
                    ugar_pct=sc["ugar_pct"],
                )
                self.assertAlmostEqual(
                    m, sc["expected_charge_t"], delta=sc["expected_charge_t"] * 0.005)

    def test_zero_output(self) -> None:
        self.assertEqual(calc_metal_charge(0), 0.0)

    def test_invalid_ugar(self) -> None:
        with self.assertRaises(ValueError):
            calc_metal_charge(1000, ugar_pct=100)


class TestFurnaceSelection(unittest.TestCase):
    """Умный подбор печей: фильтр по материалу + скоринг загрузки."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.selector = EquipmentSelector()

    def _check_scenario(self, key: str) -> None:
        sc = DIPLOMA_REFERENCE_SCENARIOS[key]
        top = self.selector.find_furnaces(
            "steel", sc["expected_charge_t"], working_hours=3890)
        self.assertTrue(top)
        best = top[0]
        self.assertEqual(best["id"], sc["expected_furnace_id"])
        self.assertEqual(best["_num_required"], sc["expected_count"])
        self.assertAlmostEqual(
            best["_load_factor"], sc["expected_load_factor"], delta=0.01)

    def test_diploma1_reference_scenario(self) -> None:
        """Эталон диплома 1: 58 932 т → топ-1 ИСТ-6М1, 6 шт., Кз ≈ 0.84."""
        self._check_scenario("diploma_1_37k")

    def test_diploma2_reference_scenario(self) -> None:
        """Эталон диплома 2: 95 494 т → топ-1 ИСТ-6М1, 10 шт., Кз ≈ 0.81."""
        self._check_scenario("diploma_2_64k")

    def test_material_filter_steel(self) -> None:
        """Для стали не должны показываться печи только для алюминия/чугуна."""
        top = self.selector.find_furnaces("steel", 58932, 3890, top_n=20)
        for f in top:
            self.assertIn("steel", f["applicable_for"]["materials"])

    def test_material_filter_aluminum(self) -> None:
        """Алюминий → только печи с materials ∋ aluminum (без сталелитейных ИСТ-6)."""
        top = self.selector.find_furnaces("aluminum", 5000, 3890, top_n=20)
        self.assertTrue(top)
        for f in top:
            self.assertIn("aluminum", f["applicable_for"]["materials"])

    def test_material_filter_cast_iron(self) -> None:
        """Чугун → только печи, применимые к cast_iron."""
        top = self.selector.find_furnaces("cast_iron", 20000, 3890, top_n=20)
        self.assertTrue(top)
        for f in top:
            self.assertIn("cast_iron", f["applicable_for"]["materials"])

    def test_top_n_limit(self) -> None:
        """Пользователю показывается 3–5 вариантов."""
        top = self.selector.find_furnaces("cast_iron", 20000, 3890)
        self.assertTrue(3 <= len(top) <= 5)

    def test_best_option_in_optimal_band(self) -> None:
        """Лучший вариант имеет Кз в оптимальной зоне 0.70–0.85."""
        top = self.selector.find_furnaces("steel", 58932, 3890)
        self.assertTrue(0.70 <= top[0]["_load_factor"] <= 0.85)

    def test_k_uneven_scales_requirement(self) -> None:
        """k_uneven=1.2 увеличивает потребное число печей (диапазон 1.0–1.2)."""
        base = self.selector.find_furnaces("steel", 58932, 3890)[0]
        uneven = self.selector.find_furnaces("steel", 58932, 3890, k_uneven=1.2)[0]
        self.assertGreater(uneven["_num_required"], base["_num_required"])


if __name__ == "__main__":
    unittest.main()
