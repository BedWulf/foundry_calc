"""Плавильное отделение: согласованный импортируемый Python-пакет.

Публичный API `from core.melting import calc_metal_charge` сохранён.
Проверенные формулы находятся в `metal_balance.py`, количество печей
рассчитывает `furnace_calc.py`. Стандартные импорты совместимы с PyInstaller.
"""
from __future__ import annotations

from .charge import (
    DIPLOMA_REFERENCE_SCENARIOS,
    REFERENCE_YIELD,
    MeltingCalculation,
    calc_metal_charge,
)
from .furnace_calc import (
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
