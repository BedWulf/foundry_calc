"""Баланс металла и годовая металлозавалка (формула (1)).

Исторически вся проверенная эталонами логика расчёта плавки находится в
модуле верхнего уровня ``core/melting.py``. Когда рядом появился пакет
``core/melting/``, он затеняет одноимённый модуль (пакеты имеют приоритет
над модулями в sys.path), поэтому прямой импорт ``core.melting`` изнутри
пакета невозможен.

Настоящий модуль решает это, загружая исходный файл ``core/melting.py``
через ``importlib.util.spec_from_file_location`` под уникальным именем
``_core_melting_legacy`` и реэкспортируя его публичные объекты.
Таким образом единственный источник истины для формул сохраняется, а
код получает их через стабильный путь ``core.melting.charge``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

#: Путь к легаси-модулю верхнего уровня ``core/melting.py``.
LEGACY_MODULE_PATH: Path = Path(__file__).resolve().parent.parent / "melting.py"

_LEGACY_NAME: str = "_core_melting_legacy"


def _load_legacy_module() -> ModuleType:
    """Загрузить ``core/melting.py`` как модуль по файловому пути."""
    if _LEGACY_NAME in sys.modules:
        return sys.modules[_LEGACY_NAME]
    if not LEGACY_MODULE_PATH.is_file():
        raise FileNotFoundError(f"Легаси-модуль не найден: {LEGACY_MODULE_PATH}")
    spec = importlib.util.spec_from_file_location(_LEGACY_NAME, LEGACY_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Не удалось загрузить модуль: {LEGACY_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_LEGACY_NAME] = module
    spec.loader.exec_module(module)
    return module


_legacy = _load_legacy_module()

# Реэкспорт публичного API легаси-модуля (единственный источник истины).
calc_metal_charge = _legacy.calc_metal_charge
MeltingCalculation = _legacy.MeltingCalculation
REFERENCE_YIELD = _legacy.REFERENCE_YIELD
DIPLOMA_REFERENCE_SCENARIOS = _legacy.DIPLOMA_REFERENCE_SCENARIOS

__all__ = [
    "calc_metal_charge",
    "MeltingCalculation",
    "REFERENCE_YIELD",
    "DIPLOMA_REFERENCE_SCENARIOS",
]
