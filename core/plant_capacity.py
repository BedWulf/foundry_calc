"""Сквозная проверка годовой производственной мощности литейного цеха.

Только одноимённые физические потоки сравниваются между собой. Оценка
годовых возможностей НЕ доказывает синхронизацию по сменам и не позволяет
автоматически уменьшать заданную годовую программу выпуска.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Mapping
import math


@dataclass(frozen=True)
class CapacityRow:
    department: str
    stream: str
    demand: float | None
    capacity: float | None
    unit: str
    status: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapacityReport:
    rows: list[CapacityRow] = field(default_factory=list)

    @property
    def has_deficit(self) -> bool:
        return any(r.status == "deficit" for r in self.rows)

    @property
    def unverified(self) -> bool:
        return any(r.status == "unknown" for r in self.rows)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": [r.as_dict() for r in self.rows],
            "has_deficit": self.has_deficit,
            "unverified": self.unverified,
        }


def _num(value: Any) -> float | None:
    """Отсутствующий/некорректный показатель нельзя превращать в ноль."""
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return x if math.isfinite(x) and x >= 0 else None


def _row(dept: str, stream: str, demand: Any, capacity: Any,
         unit: str, note: str = "") -> CapacityRow:
    d, c = _num(demand), _num(capacity)
    if d is None or c is None:
        status = "unknown"
    elif d <= c + max(1e-7, d * 1e-9):
        status = "ok"
    else:
        status = "deficit"
    return CapacityRow(dept, stream, d, c, unit, status, note)


def calculate_plant_capacity(
    summaries: Mapping[str, Mapping[str, Any]],
    project: Any | None = None,
) -> CapacityReport:
    """Сверить годовую программу с реальной установленной мощностью отделений.

    missing -> unknown, не 0. Базой являются сводки *принятого* оборудования.
    Для завалки и стержней производительность берётся из паспортных карточек,
    а для смесеприготовления отдельно по каждой операции и её единицам.
    """
    out = CapacityReport()
    mold = summaries.get("molding") or {}
    if getattr(project, "castings", None) and mold:
        target = _num(mold.get("annual_molds_total"))
        actual = _num(mold.get("assigned_molds"))
        if mold.get("batch_planning_error") or not mold.get("batch_plan_feasible"):
            if actual is not None and target is not None and actual < target:
                out.rows.append(_row(
                    "Формовочное", "Годовое распределение форм", target, actual,
                    "форм/год", "Дефицит по совместимости/фонду; не выпуск годной продукции"))
            else:
                out.rows.append(_row(
                    "Формовочное", "Годовое распределение форм", target, None,
                    "форм/год", str(mold.get("batch_planning_error") or
                                    "План формовки не подтверждён")))
        else:
            out.rows.append(_row("Формовочное", "Годовое распределение форм",
                                 target, actual, "форм/год",
                                 "Учитывает совместимость и переналадки"))
    else:
        out.rows.append(_row("Формовочное", "Годовое распределение форм",
                             mold.get("annual_molds_total"), None, "форм/год",
                             "Нет полной программы/плана партий"))

    melt = summaries.get("melting") or {}
    out.rows.append(_row(
        "Плавильное", "Металлозавалка", melt.get("metal_charge_t"),
        melt.get("capacity_charge_t_year"), "т/год",
        "Сравнение по завалке, не по массе годного литья"))

    cores = summaries.get("cores") or {}
    out.rows.append(_row(
        "Стержневое", "Изготовление стержней", cores.get("annual_cores"),
        cores.get("capacity_cores_year"), "стержней/год",
        "Мощность по паспортным стержням/час, без календарного расписания"))

    sand = summaries.get("sand_prep") or {}
    operations = sand.get("capacity_operations")
    if isinstance(operations, list) and operations:
        for op in operations:
            if not isinstance(op, Mapping):
                continue
            label = str(op.get("title") or op.get("operation") or "Операция")
            unit = str(op.get("unit") or "ед./год")
            demand_unit = op.get("quantity_unit")
            capacity_unit = op.get("capacity_unit")
            if (demand_unit is not None and capacity_unit is not None
                    and str(demand_unit).strip() != str(capacity_unit).strip()):
                out.rows.append(_row(
                    "Смесеприготовительное", label, op.get("quantity"),
                    None, unit,
                    f"Несовместимые единицы: потребность {demand_unit}, "
                    f"мощность {capacity_unit}; пересчёт не задан"))
                continue
            out.rows.append(_row(
                "Смесеприготовительное", label,
                op.get("quantity"), op.get("capacity_year"),
                unit, str(op.get("note") or "")))
    else:
        out.rows.append(_row(
            "Смесеприготовительное", "Операции подготовки смеси", None, None,
            "по операциям", "Нет подтверждённых сопоставимых паспортных данных"))

    transport = summaries.get("transport") or {}
    ladle = transport.get("ladles") or {}
    if isinstance(ladle, Mapping):
        demand = _num(ladle.get("liquid_metal_t"))
        n = _num(ladle.get("working"))
        cap = _num(ladle.get("capacity_t"))
        hours = _num(ladle.get("fund_h"))
        cycle = _num(ladle.get("cycle_time_h"))
        annual = (n * cap * hours / cycle
                  if None not in (n, cap, hours, cycle) and cycle > 0
                  else None)
        out.rows.append(_row(
            "Транспорт", "Развозка жидкого металла ковшами", demand, annual,
            "т/год", "Теоретическая ёмкость по рабочим ковшам, циклу и фонду"))
    else:
        out.rows.append(_row(
            "Транспорт", "Развозка жидкого металла ковшами", None, None,
            "т/год", "Расчёт ковшового хозяйства отсутствует"))

    out.rows.append(_row(
        "Транспорт", "Краны и внутрисменная синхронизация", None, None,
        "не задано",
        "Годовая норма количества кранов не подтверждает такт подачи"))
    return out
