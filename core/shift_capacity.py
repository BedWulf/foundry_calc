"""Сценарная проверка одновременной работы формовочных линий за одну смену.

Пиковая проверка НЕ является графиком выпуска. Для каждого ресурса выбираем
консервативную верхнюю границу потребления до N одновременно работающих
линий: максимальный расход из реально запланированных на линии изделий.
Разные максимумы разных материалов не обязательно возникают одновременно.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Mapping, Sequence
import math


@dataclass(frozen=True)
class ShiftRow:
    stream: str
    demand: float | None
    available: float | None
    unit: str
    status: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShiftReport:
    lines_running: int = 0
    shift_hours: float = 0.0
    rows: list[ShiftRow] = field(default_factory=list)

    @property
    def has_deficit(self) -> bool:
        return any(row.status == "deficit" for row in self.rows)

    def as_dict(self) -> dict[str, Any]:
        return {
            "lines_running": self.lines_running,
            "shift_hours": self.shift_hours,
            "rows": [row.as_dict() for row in self.rows],
            "has_deficit": self.has_deficit,
        }


def _positive(value: Any, *, allow_zero: bool = False) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(result) or result < 0 or (result == 0 and not allow_zero):
        return None
    return result


def _make_row(stream: str, demand: float | None, available: float | None,
              unit: str, note: str) -> ShiftRow:
    if demand is None or available is None:
        status = "unknown"
    elif demand <= available + max(1e-8, demand * 1e-9):
        status = "ok"
    else:
        status = "deficit"
    return ShiftRow(stream, demand, available, unit, status, note)


def _peak_rate(lines: Sequence[Mapping[str, Any]], count: int, field: str) -> float | None:
    if not lines or count <= 0:
        return None
    # If ANY active line has missing mass/cores input, a total peak based on
    # the remaining lines would undercount demand. Return unknown.
    if any(_positive(line.get(field), allow_zero=(field == "cores_h")) is None
           for line in lines):
        return None
    rates = sorted((float(line[field]) for line in lines), reverse=True)
    return sum(rates[:count])


def calculate_shift_stress(
    summaries: Mapping[str, Mapping[str, Any]],
    *,
    shift_hours: float,
    concurrent_lines: int = 0,
    ugar_pct: float | None = None,
) -> ShiftReport:
    """Validate peak-demand assumptions against theoretical hourly resources.

    concurrent_lines=0 means all productive lines; otherwise at most the
    requested number. No buffers, standby spare lines or calendar included.
    """
    hours = _positive(shift_hours)
    if hours is None:
        raise ValueError("Продолжительность смены должна быть > 0 ч")
    if isinstance(concurrent_lines, bool) or not isinstance(concurrent_lines, int) or concurrent_lines < 0:
        raise ValueError("Одновременно работающих линий должно быть целое число >= 0")

    mold = summaries.get("molding") or {}
    lines = mold.get("shift_peak_lines")
    valid_lines = (list(lines) if isinstance(lines, list) else [])
    valid_lines = [line for line in valid_lines if isinstance(line, Mapping)]
    active = len(valid_lines)
    count = min(concurrent_lines or active, active)
    report = ShiftReport(lines_running=count, shift_hours=hours)

    # Finished molding plan may have 0 jobs or be infeasible: this check can
    # still illuminate the current load, but never marks the full plan ready.
    metal_rate = _peak_rate(valid_lines, count, "metal_t_h")
    cores_rate = _peak_rate(valid_lines, count, "cores_h")
    metal_needed = metal_rate * hours if metal_rate is not None else None

    melt = summaries.get("melting") or {}
    loss = _positive(ugar_pct, allow_zero=True)
    if loss is not None and loss >= 100:
        loss = None
    charge_rate = _positive(melt.get("capacity_charge_t_h"))
    melt_rate = charge_rate * (1 - loss / 100) if charge_rate is not None and loss is not None else None
    report.rows.append(_make_row(
        "Жидкий металл для работающих линий",
        metal_needed, melt_rate * hours if melt_rate is not None else None,
        "т/смену",
        "Пиковый расход по отливкам; печи переведены из завалки в жидкий "
        "металл только через введённый угар. Буфер и график плавок не учтены."))

    transport = summaries.get("transport") or {}
    ladle = transport.get("ladles") or {}
    ladle_count = _positive(ladle.get("working"), allow_zero=True) if isinstance(ladle, Mapping) else None
    ladle_cap = _positive(ladle.get("capacity_t")) if isinstance(ladle, Mapping) else None
    ladle_cycle = _positive(ladle.get("cycle_time_h")) if isinstance(ladle, Mapping) else None
    ladle_rate = (ladle_count * ladle_cap / ladle_cycle
                  if None not in (ladle_count, ladle_cap, ladle_cycle) else None)
    report.rows.append(_make_row(
        "Перевозка жидкого металла ковшами",
        metal_needed, ladle_rate * hours if ladle_rate is not None else None,
        "т/смену",
        "По рабочим ковшам, паспортной ёмкости и циклу; реальные маршруты и "
        "время ожидания не проверены."))

    core = summaries.get("cores") or {}
    core_output = _positive(core.get("capacity_cores_h"))
    # All-zero core counts in the current data model can mean either no cores
    # or no populated data. Do not falsely claim that demand is zero.
    cores_needed = (cores_rate * hours
                    if cores_rate is not None and cores_rate > 0 else None)
    report.rows.append(_make_row(
        "Подача стержней на формовку",
        cores_needed, core_output * hours if core_output is not None else None,
        "стержней/смену",
        "Нужны достоверные стержни/форму по каждой позиции; запас стержней "
        "и последовательность изготовления не моделируются."))

    report.rows.append(_make_row(
        "Формовочная смесь — подача по такту",
        None, None, "м³/смену",
        "Пока нет проверенного расхода смеси на одну форму и буферного "
        "схемного расчёта; годовые объёмы не заменяют тактовую проверку."))
    return report
