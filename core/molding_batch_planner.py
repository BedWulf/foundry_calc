"""Техническое распределение разных отливок по общим формовочным линиям.

Проверяет годовую вместимость парка и совместимость оснастки. НЕ строит
посменный календарь и НЕ доказывает экономический оптимум.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import math
import re


def _number(v: object, title: str, zero: bool = False) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{title}: требуется число") from e
    if not math.isfinite(n) or n < 0 or (n == 0 and not zero):
        raise ValueError(f"{title}: недопустимое значение {v!r}")
    return n


def _flask(value: object) -> tuple[int, int, int] | None:
    numbers = re.findall(r"\d+(?:[.,]\d+)?", str(value or ""))
    if len(numbers) < 2:
        return None
    values = [float(s.replace(",", ".")) for s in numbers[:3]]
    if any(not x.is_integer() or x <= 0 for x in values):
        return None
    if len(values) == 2:
        values.append(0)
    return (*sorted((int(values[0]), int(values[1]))), int(values[2]))


@dataclass(frozen=True)
class MoldingJob:
    key: str
    name: str
    annual_molds: int
    flask_size_mm: str
    material: str
    casting_mass_kg: float = 0.0
    pouring_mass_kg: float = 0.0
    batches_per_year: int = 1
    setup_hours_per_batch: float = 0.0

    def __post_init__(self) -> None:
        if not self.key or not self.name or _flask(self.flask_size_mm) is None:
            raise ValueError("Нужны название, ID и корректный размер опоки")
        if isinstance(self.annual_molds, bool) or not isinstance(self.annual_molds, int) or self.annual_molds <= 0:
            raise ValueError(f"{self.name}: число форм должно быть целым положительным")
        if isinstance(self.batches_per_year, bool) or not isinstance(self.batches_per_year, int) or not 1 <= self.batches_per_year <= self.annual_molds:
            raise ValueError(f"{self.name}: некорректное число партий")
        for v, name in ((self.casting_mass_kg, "Масса отливки"), (self.pouring_mass_kg, "Масса в форме"), (self.setup_hours_per_batch, "Переналадка")):
            _number(v, name, zero=True)


@dataclass(frozen=True)
class ScheduledCampaign:
    job_key: str
    job_name: str
    molds: int
    process_hours: float
    setup_hours: float

    @property
    def total_hours(self) -> float:
        return self.process_hours + self.setup_hours


@dataclass
class LineInstance:
    equipment_id: str
    equipment_name: str
    instance_no: int
    nominal_molds_h: float
    annual_fund_hours: float
    allowed_hours: float
    installed_power_kw: float | None
    campaigns: list[ScheduledCampaign] = field(default_factory=list)

    @property
    def used_hours(self) -> float:
        return sum(c.total_hours for c in self.campaigns)

    @property
    def utilization(self) -> float:
        return self.used_hours / self.annual_fund_hours if self.annual_fund_hours else 0.0


@dataclass
class BatchPlan:
    lines: list[LineInstance] = field(default_factory=list)
    unassigned: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_molds: int = 0
    assigned_molds: int = 0
    max_load_factor: float = 0.85

    @property
    def feasible(self) -> bool:
        return not self.unassigned and self.assigned_molds == self.total_molds


def build_jobs_from_castings(
    castings: Sequence[Any], material: str, *, batches_per_year: int = 1,
    setup_hours_per_batch: float = 0.0,
) -> list[MoldingJob]:
    jobs = []
    for pos, c in enumerate(castings, 1):
        name = str(getattr(c, "name", "") or f"Позиция {pos}")
        molds = getattr(c, "molds_per_year", 0) or 0
        if molds:
            if isinstance(molds, bool) or float(molds) != int(float(molds)):
                raise ValueError(f"{name}: число форм не целое")
            molds = int(molds)
        else:
            qty = getattr(c, "annual_qty_with_brak", 0) or 0
            if not qty:
                good = _number(getattr(c, "annual_qty_pcs", 0) or 0, "Годной продукции", zero=True)
                pct = _number(getattr(c, "brak_pct", 0) or 0, "Брак", zero=True)
                if pct >= 100:
                    raise ValueError(f"{name}: брак должен быть менее 100%")
                qty = math.ceil(good / (1 - pct / 100))
            per = getattr(c, "castings_per_mold", 1)
            if isinstance(per, bool) or not float(per).is_integer() or float(per) <= 0:
                raise ValueError(f"{name}: отливок в форме должно быть целое положительное число")
            molds = math.ceil(float(qty) / int(per))
        jobs.append(MoldingJob(
            key=f"casting-{pos}", name=name, annual_molds=molds,
            flask_size_mm=str(getattr(c, "flask_size_mm", "")),
            material=material,
            casting_mass_kg=float(getattr(c, "mass_with_LPS_kg", 0) or 0),
            pouring_mass_kg=float(getattr(c, "pouring_mass_kg", 0) or 0),
            batches_per_year=int(getattr(c, "batches_per_year", batches_per_year) or batches_per_year),
            setup_hours_per_batch=float(getattr(c, "setup_hours_per_batch", setup_hours_per_batch)
                                        if getattr(c, "setup_hours_per_batch", None) is not None
                                        else setup_hours_per_batch),
        ))
    return jobs


def _compatible(line: Mapping[str, Any], job: MoldingJob) -> bool:
    spec, app = line.get("specs") or {}, line.get("applicable_for") or {}
    dims, needed = _flask(spec.get("flask_size_mm")), _flask(job.flask_size_mm)
    if dims is None or needed is None or dims[:2] != needed[:2]:
        return False
    heights = spec.get("flask_heights_mm") or []
    if needed[2] and heights and needed[2] not in heights:
        return False
    if job.material not in (app.get("materials") or []):
        return False
    mass_range = app.get("casting_mass_range_kg") or []
    if job.casting_mass_kg and len(mass_range) == 2 and not float(mass_range[0]) <= job.casting_mass_kg <= float(mass_range[1]):
        return False
    max_metal = spec.get("max_mold_metal_kg")
    if job.pouring_mass_kg and (max_metal is None or float(max_metal) < job.pouring_mass_kg):
        return False
    try:
        return _number(spec.get("nominal_productivity_molds_h"), "Производительность") > 0
    except ValueError:
        return False


def _allocate(group: Sequence[MoldingJob], machine: Mapping[str, Any], count: int,
              hours: float, allowance: float) -> list[LineInstance] | None:
    spec = machine["specs"]
    speed = float(spec["nominal_productivity_molds_h"])
    power = spec.get("installed_power_kw")
    power = float(power) if power is not None and float(power) >= 0 else None
    lines = [LineInstance(str(machine["id"]), str(machine.get("name") or machine["id"]),
                          i + 1, speed, hours, allowance, power) for i in range(count)]
    for job in sorted(group, key=lambda j: (-j.annual_molds / speed - j.batches_per_year * j.setup_hours_per_batch, j.key)):
        base, extra = divmod(job.annual_molds, job.batches_per_year)
        for idx in range(job.batches_per_year):
            remaining = base + (1 if idx < extra else 0)
            while remaining:
                capable = []
                for ln in lines:
                    available = allowance - ln.used_hours - job.setup_hours_per_batch
                    n = math.floor(available * speed + 1e-7)
                    if n > 0:
                        capable.append((n, ln))
                if not capable:
                    return None
                fitting = [(n, ln) for n, ln in capable if n >= remaining]
                if fitting:
                    n, ln = min(fitting, key=lambda a: (a[0] - remaining, a[1].instance_no))
                else:
                    n, ln = max(capable, key=lambda a: (a[0], -a[1].instance_no))
                qty = min(n, remaining)
                ln.campaigns.append(ScheduledCampaign(job.key, job.name, qty, qty / speed, job.setup_hours_per_batch))
                remaining -= qty
    return lines


def plan_molding_batches(
    jobs: Sequence[MoldingJob], equipment: Sequence[Mapping[str, Any]],
    fund_hours: float, *, max_load_factor: float = 0.85, max_lines_per_group: int = 100,
) -> BatchPlan:
    hours = _number(fund_hours, "Фонд оборудования")
    factor = _number(max_load_factor, "Максимальная загрузка")
    if factor > 1 or not isinstance(max_lines_per_group, int) or max_lines_per_group < 1:
        raise ValueError("Некорректная загрузка или ограничение числа линий")
    if len({j.key for j in jobs}) != len(jobs):
        raise ValueError("Повторяющиеся идентификаторы отливок")
    plan = BatchPlan(total_molds=sum(j.annual_molds for j in jobs), max_load_factor=factor)
    if not jobs:
        plan.warnings.append("Нет номенклатуры для распределения")
        return plan
    if any(j.setup_hours_per_batch == 0 for j in jobs):
        plan.warnings.append("Переналадки для части позиций не заданы (0 ч); количество линий может быть занижено")
    families: dict[tuple[int, int, str], list[MoldingJob]] = {}
    for j in jobs:
        dim = _flask(j.flask_size_mm)
        assert dim is not None
        families.setdefault((*dim[:2], j.material), []).append(j)
    for family_key, family in sorted(families.items()):
        remaining = list(family)
        while remaining:
            # One candidate need not fit all: handle compatible sub-families.
            coverage = [(m, [j for j in remaining if _compatible(m, j)]) for m in equipment]
            coverage = [(m, js) for m, js in coverage if js]
            if not coverage:
                plan.unassigned.extend(j.key for j in remaining)
                plan.warnings.append("Нет совместимого оборудования: " + ", ".join(j.name for j in remaining))
                break
            if any(len(js) == len(remaining) for _, js in coverage):
                group = remaining
                candidates = [m for m, js in coverage if len(js) == len(remaining)]
            else:
                # Technical heuristic, not global min-cost set cover.
                _, group = max(coverage, key=lambda x: (sum(j.annual_molds for j in x[1]), len(x[1])))
                candidates = [m for m, js in coverage if all(j in js for j in group)]
                plan.warnings.append(f"Группа {family_key}: несколько типов оборудования")
            opts = []
            cap = hours * factor
            for m in candidates:
                speed = float(m["specs"]["nominal_productivity_molds_h"])
                base_h = sum(j.annual_molds / speed + j.batches_per_year * j.setup_hours_per_batch for j in group)
                minimum = max(1, math.ceil((base_h - 1e-9) / cap))
                for count in range(minimum, max_lines_per_group + 1):
                    assigned = _allocate(group, m, count, hours, cap)
                    if assigned is not None:
                        power = m["specs"].get("installed_power_kw")
                        known = power is not None and float(power) >= 0
                        opts.append((count, not known, count * float(power) if known else float("inf"),
                                     sum(ln.used_hours for ln in assigned), str(m["id"]), assigned))
                        break
            if not opts:
                plan.unassigned.extend(j.key for j in group)
                plan.warnings.append(f"Для группы {family_key} не хватает фонда в пределах {max_lines_per_group} линий")
            else:
                plan.lines.extend(min(opts, key=lambda x: x[:5])[5])
            keys = {j.key for j in group}
            remaining = [j for j in remaining if j.key not in keys]
    plan.assigned_molds = sum(c.molds for ln in plan.lines for c in ln.campaigns)
    plan.warnings.append("Проверен годовой фонд, но не посменная календарная выполнимость")
    return plan
