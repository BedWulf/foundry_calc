from dataclasses import dataclass, field
from typing import List
import math


#: Расчётное отношение годного литья к завалке по ЧИСЛАМ
#: контрольного сценария («Sample Diploma.pdf», табл. 6, лист 18):
#: 37 000 т годного / 58 932 т завалки ≈ 0.62784 (62.8 %).
#: Прежнее 0.611 не соответствовало указанным в комментарии числам.
#: Это арифметическая проверка отношения, не новая паспортная норма.
REFERENCE_YIELD: float = 37000.0 / 58932.0


def calc_metal_charge(
    annual_output_t: float,
    brak_pct: float = 5.0,
    litniki_pribyli_pct: float = 28.9,
    ugar_pct: float = 5.0,
) -> float:
    """Рассчитать годовую металлозавалку по балансу металла.

    Используется формула (1) из обоих эталонных дипломов
    («Sample Diploma.pdf», п. 3.1; «Sample Diploma 2.pdf», лист 14):

        М = (Г + ЛП + Б) / (100 − У) × 100 %,

    где Г — годное литье на программу, т; ЛП — металл литниковых систем;
    Б — брак; У — угар, %. Проценты ЛП и Б задаются ОТНОСИТЕЛЬНО годного
    литья (так их понимает пользователь вкладок «Исходные данные»),
    поэтому формула эквивалентна:

        М = Г · (1 + ЛП/100 + Б/100) / (1 − У/100)

    Эталонные проверки:
      • Диплом 1 (37 000 т годного, ЛП=44.1 %, Б=7.2 %, У=5 %):
        М = (37000 + 16320 + 2666)/0.95 = 58 932 т ✓ (табл. 6, лист 18).
      • Диплом 2 (64 000 т годного, ЛП=35 %, Б=6.75 %, У=5 %):
        М = (64000 + 22400 + 4320)/0.95 = 95 494 т ✓ (лист 14).
      • При настройках проекта по умолчанию (ЛП=28.9 %, Б=5 %,
        У=5 %) на 37 000 т формула даёт ≈52 151 т. Это НЕ эталон
        диплома 1: там ЛП=16 320 т и Б=2 666 т, соответствующие
        другим процентам. Нельзя приписывать настройкам по умолчанию
        эталонные 58 932 т или число печей без нового расчёта.

    Args:
        annual_output_t: годовой выпуск годных отливок, т
        brak_pct: процент брака от годного литья, %
        litniki_pribyli_pct: процент литников и прибылей от годного литья, %
        ugar_pct: процент угара, %

    Returns:
        Годовая металлозавалка, т

    Raises:
        ValueError: если масса или проценты некорректны, отрицательны,
            не являются конечными числами или угар достигает 100 %.
    """
    # Reject invalid source values rather than producing a plausible
    # physical quantity from a negative percentage or NaN. These guards
    # also run for zero output, so bad input never masquerades as zero.
    for name, value in (
        ("Годовой выпуск", annual_output_t),
        ("Процент брака", brak_pct),
        ("Литники и прибыли", litniki_pribyli_pct),
        ("Процент угара", ugar_pct),
    ):
        if (type(value) not in (int, float)
                or not math.isfinite(value) or value < 0):
            raise ValueError(f"Некорректный параметр «{name}»: {value}")
    if ugar_pct >= 100:
        raise ValueError(f"Некорректный процент угара: {ugar_pct}%")
    if annual_output_t == 0:
        return 0.0
    ug = ugar_pct / 100.0

    lp = annual_output_t * litniki_pribyli_pct / 100.0   # металл ЛПС, т
    br = annual_output_t * brak_pct / 100.0              # брак, т
    return (annual_output_t + lp + br) / (1.0 - ug)


#: Эталонные сценарии из образцов дипломов (для проверки и пресетов UI).
#: Проценты ЛП и брака — ОТНОСИТЕЛЬНО годного литья (выведены из тоннажа
#: таблиц баланса металла каждого диплома).
DIPLOMA_REFERENCE_SCENARIOS: dict[str, dict[str, float]] = {
    "diploma_1_37k": {
        "title": "Sample Diploma.pdf: цех стального литья 37 000 т/год",
        "annual_output_t": 37000.0,
        "brak_pct": 2666.0 / 37000.0 * 100.0,          # ≈ 7.2 %
        "litniki_pribyli_pct": 16320.0 / 37000.0 * 100.0,  # ≈ 44.1 %
        "ugar_pct": 5.0,
        "expected_charge_t": 58932.0,
        "expected_furnace_id": "IST-6M1",
        "expected_count": 6,
        "expected_load_factor": 0.84,
    },
    "diploma_2_64k": {
        "title": "Sample Diploma 2.pdf: цех стального литья 64 000 т/год",
        "annual_output_t": 64000.0,
        "brak_pct": 4320.0 / 64000.0 * 100.0,          # ≈ 6.75 %
        "litniki_pribyli_pct": 22400.0 / 64000.0 * 100.0,  # = 35.0 %
        "ugar_pct": 5.0,
        "expected_charge_t": 95494.0,
        "expected_furnace_id": "IST-6M1",
        "expected_count": 10,
        "expected_load_factor": 0.81,
    },
}


@dataclass
class MeltingCalculation:
    """Расчет плавильного отделения"""
    annual_metal_charge_t: float  # Годовая металлозавалка, т
    furnace_type: str  # Тип печи (ИСТ-6М1, ДСП, и т.д.)
    furnace_capacity_t: float  # Емкость тигля, т
    furnace_productivity_t_h: float  # Производительность, т/ч
    fund_hours: float  # Действительный фонд времени, ч
    k_uneven: float  # Коэффициент неравномерности (1.0-1.2)
    
    # Результаты расчета
    furnace_count: int  # Количество печей
    load_factor: float  # Коэффициент загрузки