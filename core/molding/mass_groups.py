"""Распределение отливок по группам массы и годового объёма выпуска.

Эталон — «Sample Diploma.pdf», раздел «Формовочное отделение» (табл. 7,
лист 24): номенклатура цеха разбивается на группы по массе одной отливки
(до 4 кг / св. 4–10 кг / св. 10–30 кг / свыше 30 кг), для каждой группы
определяется способ формовки: АФЛ в опоках либо машинная/ручная формовка
без опок на площадках (мелкосерийные крупные отливки).

Границы групп вынесены в константы — единственный источник данных для
вкладки, расчёта АФЛ и тестов (SQLite не используется, правило №5).
"""
from dataclasses import dataclass
from typing import List

# Границы групп по массе одной отливки с ЛПС, кг (табл. 7 диплома).
MASS_GROUP_BOUNDS_KG: List[float] = [4.0, 10.0, 30.0]

#: Человекочитаемые названия групп по массе (индекс = номер группы).
MASS_GROUP_TITLES: List[str] = [
    "мелкая (до 4 кг)",
    "средняя (св. 4 — 10 кг)",
    "крупная (св. 10 — 30 кг)",
    "крупная (свыше 30 кг)",
]

#: Рекомендуемый способ формовки для каждой группы (методичка/диплом).
MASS_GROUP_METHODS: List[str] = [
    "АФЛ в опоках",
    "АФЛ в опоках",
    "АФЛ в опоках",
    "Машинная формовка без опок на площадках",
]

#: Годовой объём группы (т), ниже которого группа считается мелкосерийной
#: и АФЛ для неё не назначается (недогрузка линии).
SMALL_SERIES_ANNUAL_T: float = 50.0


@dataclass
class MassGroup:
    """Одна группа отливок по массе.

    Attributes:
        index: порядковый номер группы (0 — самая мелкая)
        title: название диапазона масс
        method: рекомендуемый способ формовки
        min_mass_kg: нижняя граница массы отливки с ЛПС, кг (не включительно)
        max_mass_kg: верхняя граница массы отливки с ЛПС, кг (включительно)
        items_count: число позиций номенклатуры в группе
        annual_qty_pcs: годовой выпуск отливок с учётом брака, шт
        annual_mass_t: годовая масса отливок с ЛПС, т
        molds_per_year: расчётное годовое количество форм, шт
    """

    index: int = 0
    title: str = ""
    method: str = ""
    min_mass_kg: float = 0.0
    max_mass_kg: float = 0.0
    items_count: int = 0
    annual_qty_pcs: int = 0
    annual_mass_t: float = 0.0
    molds_per_year: int = 0

    @property
    def is_small_series(self) -> bool:
        """True, если объём группы недостаточен для полной загрузки АФЛ."""
        return self.annual_mass_t < SMALL_SERIES_ANNUAL_T

    @property
    def use_afl(self) -> bool:
        """True, если группу следует относить на автоматические линии."""
        return self.index < len(MASS_GROUP_BOUNDS_KG) and not self.is_small_series


def mass_group_index(mass_kg: float) -> int:
    """Вернуть индекс группы по массе одной отливки (с ЛПС), кг.

    Args:
        mass_kg: заливочная масса отливки (с литниковой системой), кг

    Returns:
        Индекс группы от 0 до ``len(MASS_GROUP_TITLES) - 1``
    """
    for i, bound in enumerate(MASS_GROUP_BOUNDS_KG):
        if mass_kg <= bound:
            return i
    return len(MASS_GROUP_BOUNDS_KG)


def build_mass_groups(castings: List) -> List[MassGroup]:
    """Сгруппировать позиции номенклатуры по массе отливки.

    Args:
        castings: список ``CastingItem``; используются поля
            ``mass_with_LPS_kg``, ``annual_qty_with_brak``/``annual_qty_pcs``,
            ``molds_per_year``, ``annual_metal_t``

    Returns:
        Список непустых групп по возрастанию массы (пустые диапазоны
        не возвращаются, чтобы UI не показывал нулевые строки)
    """
    n = len(MASS_GROUP_TITLES)
    groups: List[MassGroup] = [
        MassGroup(
            index=i,
            title=MASS_GROUP_TITLES[i],
            method=MASS_GROUP_METHODS[i],
            min_mass_kg=0.0 if i == 0 else MASS_GROUP_BOUNDS_KG[i - 1],
            max_mass_kg=(MASS_GROUP_BOUNDS_KG[i]
                         if i < len(MASS_GROUP_BOUNDS_KG) else float("inf")),
        )
        for i in range(n)
    ]

    for c in castings:
        mass_kg = float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0)
        g = groups[mass_group_index(mass_kg)]
        g.items_count += 1
        g.annual_qty_pcs += int(getattr(c, "annual_qty_with_brak", 0)
                               or getattr(c, "annual_qty_pcs", 0) or 0)
        g.annual_mass_t += float(getattr(c, "annual_metal_t", 0.0) or 0.0)
        g.molds_per_year += int(getattr(c, "molds_per_year", 0) or 0)

    return [g for g in groups if g.items_count > 0]
