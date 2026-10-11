"""Пакет расчётов плавильного отделения.

ВНИМАНИЕ: исторически расчёты плавки жили в модуле верхнего уровня
``core/melting.py``. Когда в каталоге появился пакет ``core/melting/``,
он имел приоритет над одноимённым модулем, из-за чего импорт
``from core.melting import calc_metal_charge`` падал с ImportError.

Решение: пакет является «фасадом» — он реэкспортирует всё содержимое
модуля ``core/melting.py`` через ``core.melting.charge`` (который сам
подгружает проверенный эталонами код верхнеуровневого модуля) и
дополнительные точки расширения.

Модули пакета:
    ``charge``        — баланс металла и годовая металлозавалка (формула (1)).
    ``furnace_calc``  — расчёт количества печей и коэффициента загрузки
                        (формулы (3)/(4), P₁ = М·kн/(Фд·q), Кзо = P₁/Nпр).
"""

from __future__ import annotations

from core.melting.charge import (
    DIPLOMA_REFERENCE_SCENARIOS,
    REFERENCE_YIELD,
    MeltingCalculation,
    calc_metal_charge,
)
from core.melting.furnace_calc import (
    FurnaceCountResult,
    calc_furnace_count,
    load_factor,
)

__all__ = [
    "calc_metal_charge",
    "REFERENCE_YIELD",
    "DIPLOMA_REFERENCE_SCENARIOS",
    "MeltingCalculation",
    "FurnaceCountResult",
    "calc_furnace_count",
    "load_factor",
]
