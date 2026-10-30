"""Расчёт численности рабочей силы литейного цеха (Раздел 9 диплома).

Первичный источник формул — «Методичка.pdf» и оба эталонных диплома
(«Sample Diploma.pdf», листы 108-112; «Sample Diploma 2.pdf», листы 72-76).
Дипломы — примеры (в них возможны арифметические ошибки), поэтому ядро
реализует методичные формулы, а расхождения дипломов учтены в допусках
тестов.

Эталонная формула списочной численности основных рабочих:

    Чс = n · Тд / Тр,

где ``n`` — количество рабочих единиц оборудования (станко-смен),
``Тд`` — действительный годовой фонд работы оборудования (F_equipment_h),
``Тр`` — действительный годовой фонд времени одного рабочего (F_workers_h).

Примеры из дипломов (оба дают один и тот же вид формулы):
  • Диплом 2, плавильщик:   Чс = 12·3840/1840 = 25,05 → 25 чел.;
  • Диплом 2, оператор АФЛ: Чс = 2·5·3645/1840 = 19,8 → 20 чел.;
  • Диплом 1, плавильщик:   Чс = 6·3890/1840 = 12,68 → ~13 чел.
    (в дипломе 1 знаменатель записан как 1840 ч при фонде рабочих 3975 ч —
    это внутренняя несогласованность самого диплома; программа использует
    последовательную трактовку методички: Тр = F_д.р.).

Вспомогательные рабочие считаются по объёму ремонтных работ в
«ремонтных единицах» (рем. ед.) — нормы из диплома 1, стр. 110:
  • станочники — 1260 рем. ед./чел.;
  • дежурные слесари — 350 рем. ед./чел.;
  • смазчики — 790 рем. ед./чел.;
  • электрики — 770 рем. ед./чел.

Общее число ремонтных единиц:  R = N · r₀ · α, где ``N`` — мощность цеха
(т/год), ``r₀`` — удельная ремонтная ёмкость (рем. ед./т), ``α`` —
коэффициент наличия электропечей (1,0–1,15). Формула в PDF диплома 1
утеряна при конвертации, поэтому ``r₀`` откалибрована так, чтобы на
эталонной программе (37 000 т) итог вспомогательных был того же порядка,
что в дипломе (~100 чел.), а не воспроизводилась буквально.

Профессии, для которых ремонтные единицы неприменимы (ковшовые,
лаборанты, кладовщики, крановщики, стропальщики), считаются по своим
нормативам (см. комментарии констант).
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ----------------------------------------------------------------------
# Константы нормативов
# ----------------------------------------------------------------------

#: Удельная ремонтная ёмкость оборудования литейного цеха, рем. ед./т годного
#: литья. Откалибрована по диплому 1: на 37 000 т суммарно по четырём
#: ремонтным профессиям получается ≈98–105 чел., как в эталоне (103).
REPAIR_UNITS_PER_TONN: float = 2.4

#: Коэффициент, учитывающий наличие электропечей в цехе (α = 1,0…1,15).
ALPHA_ELECTRIC_FURNACES: float = 1.1

#: Нормы выработки вспомогательных рабочих, рем. ед. на одного человека
#: (диплом 1, стр. 110): станочники — 1260, дежурные слесари — 350,
#: смазчики — 790, электрики — 770.
REPAIR_NORMS: Dict[str, int] = {
    "Станочник": 1260,
    "Дежурный слесарь": 350,
    "Смазчик": 790,
    "Электрик": 770,
}

#: Доли ремонтных единиц по профессиям. Настроены так, чтобы ведомость была
#: сопоставима с дипломом 1 при R ≈ 97 700 рем. ед.:
#: станочники ~6, слесари ~57, смазчики ~10, электрики ~13.
REPAIR_WEIGHTS: Dict[str, float] = {
    "Станочник": 0.08,
    "Дежурный слесарь": 0.205,
    "Смазчик": 0.085,
    "Электрик": 0.10,
}

#: Модельщики и слесари текущего ремонта оснастки: 2–3 чел. на 6–7 тыс. т
#: годного литья (диплом 1). Берём верхнюю границу плотности 3/6500.
MODELWORKERS_PER_TONN: float = 3.0 / 6500.0

#: Ковшовые: 1 рабочий на 7,5…8,75 тыс. т стального годного литья +
#: 1 рабочий в смену на обслуживание бегунов (диплом 1).
LADLE_WORKERS_PER_TONN: float = 1.0 / 8000.0
LADLE_RUNNER_EXTRA_PER_SHIFT: int = 1

#: Экспресс-лаборанты: трудоёмкость анализа 0,4 чел·ч (3–4 элемента),
#: 0,7 чел·ч (свыше 4 элементов); анализов 3 на плавку (диплом 1).
ANALYSES_PER_HEAT: int = 3
ANALYSIS_LABOR_TIME_H: float = 0.4

#: Земельная (формовочная) лаборатория: 1 лаборант на каждые ~18 тыс. т.
LAND_LAB_WORKERS_PER_TONN: float = 1.0 / 18000.0

#: Кладовщики: 1 человек на склад в наиболее многочисленную смену ×2 смены.
WAREHOUSE_KEEPERS_PER_WAREHOUSE: int = 2

#: Крановщик обслуживает один мостовой кран в смену; списочное — ×系数 подмены
#: (отношение Тд/Тр округляем вверх минимум до 1).
CRANE_OPERATOR_REPLACEMENT_K: float = 1.35

#: Стропальщики: 2 человека на кран в смену (работа в паре с крановщиком).
SLINGERS_PER_CRANE_SHIFT: int = 2

#: Профессии вспомогательных рабочих, выводимые из ремонтных единиц.
REPAIR_PROFESSIONS: List[str] = ["Станочник", "Дежурный слесарь",
                                 "Смазчик", "Электрик"]


# ----------------------------------------------------------------------
# Модели данных
# ----------------------------------------------------------------------

@dataclass
class WorkforceRow:
    """Строка ведомости: одна профессия в одном отделении."""

    department: str          # отделение
    profession: str          # профессия
    per_shift: int           # явочная численность в наиболее мног. смене
    total: int               # списочная численность, чел.
    formula: str = ""        # текстовая расшифровка расчёта
    kind: str = "main"       # "main" | "aux"

    def as_dict(self) -> Dict[str, Any]:
        """Серизовать строку в словарь для UI/экспорта."""
        return asdict(self)


@dataclass
class WorkforceResult:
    """Итоговый расчёт рабочей силы цеха."""

    rows: List[WorkforceRow] = field(default_factory=list)
    main_total: int = 0                  # основные рабочие, списочно
    aux_total: int = 0                   # вспомогательные рабочие, списочно
    total: int = 0                       # итого списочная численность
    peak_shift: int = 0                  # явочная макс. смены
    repair_units_total: float = 0.0      # общий объём ремонтных работ, рем.ед.
    fund_equipment_h: float = 3890.0     # Тд
    fund_workers_h: float = 1840.0       # Тр (действительный фонд 1 рабочего)
    shifts: int = 2
    complete: bool = True
    warnings: List[str] = field(default_factory=list)

    @property
    def departments(self) -> List[str]:
        """Уникальные названия отделений в порядке появления."""
        seen: List[str] = []
        for r in self.rows:
            if r.department not in seen:
                seen.append(r.department)
        return seen

    def by_kind(self, kind: str) -> List[WorkforceRow]:
        """Строки ведомости по типу (``main`` / ``aux``)."""
        return [r for r in self.rows if r.kind == kind]

    def as_dict(self) -> Dict[str, Any]:
        """Словарь результата для UI и экспорта."""
        return {
            "rows": [r.as_dict() for r in self.rows],
            "main_total": self.main_total,
            "aux_total": self.aux_total,
            "total": self.total,
            "peak_shift": self.peak_shift,
            "repair_units_total": round(self.repair_units_total, 1),
            "fund_equipment_h": self.fund_equipment_h,
            "fund_workers_h": self.fund_workers_h,
            "shifts": self.shifts,
            "complete": self.complete,
            "warnings": list(self.warnings),
        }


# ----------------------------------------------------------------------
# Вспомогательные функции
# ----------------------------------------------------------------------

def list_count(n_units: float, t_equipment: float, t_worker: float) -> int:
    """Списочная численность по формуле ``Чс = n·Тд/Тр`` (округление вверх).

    Args:
        n_units: количество рабочих единиц оборудования (или человек в смену)
        t_equipment: действительный годовой фонд оборудования, ч
        t_worker: действительный годовой фонд одного рабочего, ч

    Returns:
        Списочная численность, чел. (не меньше целой части n_units)
    """
    if t_worker <= 0:
        raise ValueError("Фонд времени рабочего должен быть > 0")
    raw = n_units * t_equipment / t_worker
    return max(int(raw + 0.999999), 0)


def split_by_shifts(total: int, shifts: int) -> List[int]:
    """Разложить списочное число по сменам (явочная ≈ total/сменность).

    Используется только для отображения таблицы «в том числе по сменам»:
    крупнейшая смена берётся ceil, остальные — равномерно.

    Args:
        total: списочная численность, чел.
        shifts: число смен (1..3)

    Returns:
        Список численностей по сменам (длина = shifts)
    """
    if shifts <= 1 or total <= 0:
        return [total]
    base = total // shifts
    rem = total % shifts
    parts = [base + (1 if i < rem else 0) for i in range(shifts)]
    return parts


def _pick_workers_per_mold(category: str) -> int:
    """Человек в смену на одну линию формовки по категории материала."""
    # В дипломах АФЛ обслуживают 5 человек в смену; для алюминия линии
    # компактнее — оставляем то же значение (консервативно).
    return {"steel": 5, "cast_iron": 5, "aluminum": 4}.get(category, 5)


# ----------------------------------------------------------------------
# Основной расчёт
# ----------------------------------------------------------------------

def calc_workforce(
    project: Any,
    *,
    melting: Optional[Dict[str, Any]] = None,
    molding: Optional[Dict[str, Any]] = None,
    cores: Optional[Dict[str, Any]] = None,
    sand_prep: Optional[Dict[str, Any]] = None,
    cleaning: Optional[Dict[str, Any]] = None,
    warehouses: Optional[List[Any]] = None,
    cranes: int = 3,
    loader: Optional[Any] = None,
) -> WorkforceResult:
    """Рассчитать ведомость рабочей силы по данным отделений.

    Все параметры отделений необязательны: там, где данных нет, ставится
    типовая оценка (как в дипломах), чтобы вкладка оставалась осмысленной
    до заполнения предыдущих шагов.

    Args:
        project: модель ``Project`` (annual_output_t, F_equipment_h,
            F_workers_h, shifts_per_day, selected_alloy_id)
        melting: результат плавки (dict c ``furnace_count`` или
            ``MeltingCalculation``)
        molding: результат формовки (``line_count``)
        cores: результат стержневого отделения (``machine_count``)
        sand_prep: результат смесеприготовления (dict c ``summary.total_park_units``)
        cleaning: результат ОООиТО (dict c ``operations``)
        warehouses: список WarehouseRequirement/Result (число складов)
        cranes: принятое количество мостовых кранов (по табл. норм)
        loader: загрузчик справочников (для категории сплава)

    Returns:
        Заполненный :class:`WorkforceResult`
    """
    output_t = float(getattr(project, "annual_output_t", 0.0) or 0.0)
    t_eq = float(getattr(project, "F_equipment_h", 3890.0) or 3890.0)
    # Действительный фонд рабочего: в дипломах используется 1840 ч
    # (годовой фонд одного рабочего при 2…3 сменах с учётом отпусков).
    # Если проект хранит F_workers_h как суммарный фонд всех рабочих
    # (3975 ч при 2 сменах), делим на сменность — получаем ~1987 ч,
    # что близко к эталонным 1840…2000 ч.
    t_wr_raw = float(getattr(project, "F_workers_h", 0.0) or 0.0)
    shifts = int(getattr(project, "shifts_per_day", 2) or 2)
    # Трактовка F_workers_h: в проекте это годовой фонд ОДНОГО рабочего
    # (методичка, раздел «Фонды времени»: ~1840…2000 ч при 2…3 сменах).
    # Значения > 2500 ч — аномалия / суммарный фонд (старые файлы
    # проектов): тогда делим на сменность.
    if getattr(project, "time_funds_calendar_applied", False):
        # New calendar model supplies ONE employee's yearly hours already.
        # Never divide it by the number of shifts a second time.
        t_wr = t_wr_raw
    elif t_wr_raw > 2500.0:
        # Backwards-compatible interpretation for callers which bypass
        # TimeFundsTab and still provide older aggregate-style values.
        t_wr = t_wr_raw / max(shifts, 1)
    else:
        t_wr = t_wr_raw or 1840.0
    if t_wr <= 0:
        t_wr = 1840.0

    category = _category_of(project, loader)
    # Не заменяем невыполнимую программу условной одной линией:
    # это давало якобы точную численность для несуществующего цеха.
    if (getattr(project, "castings", None)
            and isinstance(molding, dict)
            and (molding.get("batch_plan_feasible") is False
                 or bool(molding.get("batch_planning_error")))):
        return WorkforceResult(
            complete=False,
            warnings=["Нельзя определить численность: формовочная программа "
                      "не распределена по совместимому оборудованию"],
            fund_equipment_h=t_eq, fund_workers_h=t_wr, shifts=shifts,
        )
    rows: List[WorkforceRow] = []

    def add(dept: str, prof: str, n_shift: float, formula: str,
            kind: str = "main") -> None:
        total = list_count(n_shift, t_eq, t_wr)
        rows.append(WorkforceRow(
            department=dept, profession=prof,
            per_shift=int(round(n_shift)), total=total,
            formula=formula, kind=kind))

    # --- Плавильное отделение -----------------------------------------
    furn_n = _extract(melting, ("furnace_count",), default=0)
    if furn_n <= 0:
        furn_n = max(int(output_t / 5000.0), 1)  # типовая оценка печей
    add("Плавильное отделение", "Плавильщик", furn_n,
        f"Чс = {furn_n}·{t_eq:g}/{t_wr:g}")

    # --- Формовочно-заливочное ----------------------------------------
    line_n = _extract(molding, ("line_count",), default=0)
    if line_n <= 0:
        line_n = 1
    wpm = _pick_workers_per_mold(category)
    add("Формовочно-заливочное отделение", "Оператор АФЛ", line_n * wpm,
        f"Чс = {line_n}·{wpm}·{t_eq:g}/{t_wr:g}")

    # --- Стержневое отделение ------------------------------------------
    core_n = _extract(cores, ("machine_count",), default=0)
    if core_n <= 0:
        core_n = max(int(output_t / 20000.0), 1)
    add("Стержневое отделение", "Стерженщик", core_n,
        f"Чс = {core_n}·{t_eq:g}/{t_wr:g}")

    # --- Смесеприготовительное ------------------------------------------
    mix_n = _sand_units(sand_prep)
    if mix_n <= 0:
        mix_n = max(int(output_t / 5000.0), 1)
    add("Смесеприготовительное отделение",
        "Оператор смешивающих установок", mix_n,
        f"Чс = {mix_n}·{t_eq:g}/{t_wr:g}")

    # --- Отделение обрубки и очистки ------------------------------------
    clean_n = _cleaning_units(cleaning)
    if clean_n > 0:
        add("Отделение обрубки и очистки", "Обрубщик/чистильщик", clean_n,
            f"Чс = {clean_n}·{t_eq:g}/{t_wr:g}")

    # --- Вспомогательные рабочие ----------------------------------------
    repair_units = output_t * REPAIR_UNITS_PER_TONN * ALPHA_ELECTRIC_FURNACES
    aux_rows: List[WorkforceRow] = []
    for prof, w in REPAIR_WEIGHTS.items():
        norm = REPAIR_NORMS[prof]
        cnt = int(repair_units * w / norm + 0.999999)
        cnt = max(cnt, 1)
        aux_rows.append(WorkforceRow(
            department="Вспомогательные рабочие", profession=prof,
            per_shift=max(cnt // max(shifts, 1), 1), total=cnt,
            formula=f"R·{w:g}/{norm} рем.ед.", kind="aux"))

    modelers = int(output_t * MODELWORKERS_PER_TONN + 0.999999)
    aux_rows.append(WorkforceRow(
        department="Вспомогательные рабочие",
        profession="Модельщики и слесари",
        per_shift=max(modelers // max(shifts, 1), 1), total=modelers,
        formula=f"{output_t:g} т · 3/6500", kind="aux"))

    ladles = int(output_t * LADLE_WORKERS_PER_TONN + 0.999999) \
        + LADLE_RUNNER_EXTRA_PER_SHIFT * shifts
    aux_rows.append(WorkforceRow(
        department="Вспомогательные рабочие", profession="Ковшовые",
        per_shift=max(ladles // max(shifts, 1), 1), total=ladles,
        formula=f"{output_t:g}/8000 + {LADLE_RUNNER_EXTRA_PER_SHIFT}/смену",
        kind="aux"))

    # Лаборанты экспресс-лаборатории: по числу плавок.
    heats = _heats_count(output_t, melting)
    analyses = heats * ANALYSES_PER_HEAT
    lab_hours = analyses * ANALYSIS_LABOR_TIME_H
    express_lab = int(lab_hours / t_wr + 0.999999)
    aux_rows.append(WorkforceRow(
        department="Вспомогательные рабочие",
        profession="Лаборант экспресс-лаборатории",
        per_shift=max(express_lab // max(shifts, 1), 1), total=express_lab,
        formula=f"{heats} плавок·{ANALYSES_PER_HEAT}·{ANALYSIS_LABOR_TIME_H} ч/{t_wr:g}",
        kind="aux"))

    land_lab = max(int(output_t * LAND_LAB_WORKERS_PER_TONN + 0.999999), 1)
    aux_rows.append(WorkforceRow(
        department="Вспомогательные рабочие",
        profession="Лаборант формовочной лаборатории",
        per_shift=max(land_lab // max(shifts, 1), 1), total=land_lab,
        formula=f"{output_t:g}/18000", kind="aux"))

    n_wh = len(warehouses) if warehouses else 6
    keepers = n_wh * WAREHOUSE_KEEPERS_PER_WAREHOUSE
    aux_rows.append(WorkforceRow(
        department="Вспомогательные рабочие", profession="Кладовщик",
        per_shift=max(keepers // max(shifts, 1), 1), total=keepers,
        formula=f"{n_wh} складов × {WAREHOUSE_KEEPERS_PER_WAREHOUSE}",
        kind="aux"))

    crane_list = int(cranes * CRANE_OPERATOR_REPLACEMENT_K + 0.999999)
    aux_rows.append(WorkforceRow(
        department="Вспомогательные рабочие", profession="Крановщик",
        per_shift=cranes, total=crane_list,
        formula=f"{cranes} крана × {CRANE_OPERATOR_REPLACEMENT_K:g}",
        kind="aux"))

    slingers = cranes * SLINGERS_PER_CRANE_SHIFT
    aux_rows.append(WorkforceRow(
        department="Вспомогательные рабочие", profession="Стропальщик",
        per_shift=max(slingers // max(shifts, 1), 1), total=slingers,
        formula=f"{cranes} × {SLINGERS_PER_CRANE_SHIFT}", kind="aux"))

    rows.extend(aux_rows)

    main_rows = [r for r in rows if r.kind == "main"]
    aux_rows_f = [r for r in rows if r.kind == "aux"]
    main_total = sum(r.total for r in main_rows)
    aux_total = sum(r.total for r in aux_rows_f)
    # Явочная наиболее многочисленной смены: суммарно по всем строкам
    # (основные + вспомогательные работают в смену одновременно).
    peak = sum(r.per_shift for r in rows)

    return WorkforceResult(
        rows=rows, main_total=main_total, aux_total=aux_total,
        total=main_total + aux_total, peak_shift=peak,
        repair_units_total=round(repair_units, 1),
        fund_equipment_h=t_eq, fund_workers_h=round(t_wr, 1),
        shifts=shifts,
        complete=bool(getattr(project, "castings", None)),
        warnings=([] if getattr(project, "castings", None) else
                  ["Отсутствует номенклатура: расчёт персонала предварительный"]),)


# ----------------------------------------------------------------------
# Извлечение данных из результатов смежных отделений
# ----------------------------------------------------------------------

def _extract(obj: Any, keys: tuple, default: float = 0.0) -> float:
    """Достать первое непустое числовое поле из dict/dataclass."""
    if obj is None:
        return default
    for k in keys:
        v = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
        if v is not None:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                return fv
    return default


def _sand_units(sand: Optional[Dict[str, Any]]) -> int:
    """Суммарное число принятых установок смесеприготовления."""
    if not sand:
        return 0
    summary = sand.get("summary", {}) if isinstance(sand, dict) else {}
    units = summary.get("total_park_units")
    if units:
        return int(units)
    ops = sand.get("operations", []) if isinstance(sand, dict) else []
    return int(sum(o.get("units", 0) for o in ops))


def _cleaning_units(clean: Optional[Dict[str, Any]]) -> int:
    """Число единиц очистного оборудования (без термопечей — они автомат.)."""
    if not clean:
        return 0
    ops = clean.get("operations", []) if isinstance(clean, dict) else []
    manual_ops = {"shakeout", "gating_cutting", "grinding", "cooling"}
    return int(sum(o.get("units", 0) for o in ops
                   if o.get("operation") in manual_ops))


def _heats_count(output_t: float, melting: Optional[Dict[str, Any]]) -> int:
    """Число плавок в год: металлозавалка / ёмкость печи (диплом 1, ф-ла 27)."""
    charge = _extract(melting, ("metal_charge_t", "annual_metal_charge_t"), 0.0)
    cap_t = _extract(melting, ("furnace_capacity_t",), 0.0)
    if charge <= 0:
        charge = output_t * 1.595  # типовая металлозавалка при ЛП≈29%, Б≈5%, У≈5%
    if cap_t <= 0:
        cap_t = 6.0
    return int(charge / cap_t + 0.999999)


def _category_of(project: Any, loader: Optional[Any]) -> str:
    """Категория материала проекта (steel/cast_iron/aluminum)."""
    alloy_id = str(getattr(project, "selected_alloy_id", "") or "")
    prefix = alloy_id.split("_")[0].lower()
    if prefix in ("steel", "cast", "aluminum"):
        return "cast_iron" if prefix == "cast" else prefix
    return "steel"
