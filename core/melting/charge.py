"""Годовой баланс металла (формула 1 из эталонных дипломов).

Все проверенные формулы и константы находятся внутри обычного пакета
``core.melting.metal_balance``. Не загружать Python-файлы вручную через
``spec_from_file_location``: PyInstaller замораживает .py как модули,
и физических файлов по старым путям в EXE может не быть.
"""
from __future__ import annotations

from .metal_balance import (
    DIPLOMA_REFERENCE_SCENARIOS,
    REFERENCE_YIELD,
    MeltingCalculation,
    calc_metal_charge,
)

__all__ = [
    "calc_metal_charge",
    "MeltingCalculation",
    "REFERENCE_YIELD",
    "DIPLOMA_REFERENCE_SCENARIOS",
]
