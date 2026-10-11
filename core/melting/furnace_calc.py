"""Расчёт количества печей и коэффициента загрузки (формулы (3)/(4)).

Формулы обоих эталонных дипломов:

    P'1 = М · kн / (Фд · q)   — потребное число агрегатов, шт.
    Кзо = P'1 / Pр            — коэффициент загрузки парка, доля

где М — годовая металлозавалка, т; kн — коэффициент неравномерности;
Фд — действительный годовой фонд времени, ч; q — производительность
печи, т/ч; Pр — принятое (целое) число печей.

Инженерное правило выбора Pр (воспроизводит решения дипломов): берётся
наименьшее целое, при котором Кзо ≤ 0.85 (верх оптимального диапазона
0.70–0.85 из методички). Диплом 1: P'1 = 5.05 → 6 печей (Кзо 0.84);
диплом 2: P'1 = 8.18 → 10 печей (Кзо 0.82).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Верх оптимального диапазона коэффициента загрузки парка печей.
MAX_LOAD_FACTOR: float = 0.85


@dataclass(frozen=True)
class FurnaceCountResult:
    """Результат расчёта парка печей для одной модели оборудования."""

    productivity_t_h: float   #: Производительность одной печи, т/ч
    annual_charge_t: float    #: Годовая металлозавалка, т
    fund_hours: float         #: Действительный годовой фонд времени, ч
    k_uneven: float           #: Коэффициент неравномерности потребления металла
    p1_required: float        #: Потребное число печей (расчётное, дробное), шт.
    num_furnaces: int         #: Принятое (целое) число печей Pр, шт.
    load_factor: float        #: Коэффициент загрузки парка Кзо, доля

    @property
    def installed_productivity_t_h(self) -> float:
        """Суммарная установленная производительность парка, т/ч."""
        return self.num_furnaces * self.productivity_t_h


def calc_furnace_count(
    annual_charge_t: float,
    productivity_t_h: float,
    fund_hours: float = 3890.0,
    k_uneven: float = 1.0,
    max_load_factor: float = MAX_LOAD_FACTOR,
) -> FurnaceCountResult:
    """Рассчитать потребное и принятое число печей, коэффициент загрузки.

    Args:
        annual_charge_t: годовая металлозавалка, т
        productivity_t_h: часовая производительность одной печи, т/ч
        fund_hours: действительный годовой фонд времени работы, ч
        k_uneven: коэффициент неравномерности (1.0–1.2)
        max_load_factor: целевой верх диапазона загрузки парка

    Returns:
        Заполненный :class:`FurnaceCountResult`.

    Raises:
        ValueError: если ``productivity_t_h <= 0`` или ``fund_hours <= 0``.
    """
    if productivity_t_h <= 0:
        raise ValueError(f"Некорректная производительность печи: {productivity_t_h}")
    if fund_hours <= 0:
        raise ValueError(f"Некорректный фонд времени: {fund_hours}")

    required_productivity = annual_charge_t * k_uneven / fund_hours
    p1_required = required_productivity / productivity_t_h
    num_furnaces = max(
        math.ceil(p1_required),
        math.ceil(p1_required / max_load_factor),
    )
    lf = p1_required / num_furnaces if num_furnaces else 0.0
    return FurnaceCountResult(
        productivity_t_h=productivity_t_h,
        annual_charge_t=annual_charge_t,
        fund_hours=fund_hours,
        k_uneven=k_uneven,
        p1_required=round(p1_required, 3),
        num_furnaces=num_furnaces,
        load_factor=round(lf, 3),
    )


def load_factor(p1_required: float, num_furnaces: int) -> float:
    """Коэффициент загрузки парка: Кзо = P'1 / Pр (формула (4)).

    Args:
        p1_required: расчётное (дробное) потребное число печей
        num_furnaces: принятое целое число печей

    Returns:
        Коэффициент загрузки, доля (0 при нулевом числе печей).
    """
    if num_furnaces <= 0:
        return 0.0
    return p1_required / num_furnaces


__all__ = ["FurnaceCountResult", "calc_furnace_count", "load_factor", "MAX_LOAD_FACTOR"]
