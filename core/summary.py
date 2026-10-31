"""Сводная ведомость проекта «ЛитейныйЦех PRO».

Собирает итоговые данные всех отделений (``get_summary()`` вкладок,
см. :meth:`gui.main_window.MainWindow.department_summaries`) в единую
структуру и умеет экспортировать её в Excel (openpyxl).

Модуль не зависит от PySide6: на вход подаются только словари-сводки,
поэтому его можно тестировать без GUI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.plant_capacity import calculate_plant_capacity
from core.casting_audit import audit_castings, audit_casting_technology
from core.casting_item import CastingItem
from core.shift_capacity import calculate_shift_stress
from core.engineering_readiness import audit_calculation_sources

# ----------------------------------------------------------------------
# Константы оформления экспорта (палитра приложения; для Excel — hex)
# ----------------------------------------------------------------------
XLSX_COLORS: Dict[str, str] = {
    "bg_main": "2D0A0A",       # глубокий бордо
    "bg_panel": "4A1515",      # тёмно-винный
    "text_primary": "F4D03F",  # тёплое золото
    "text_secondary": "C9A84C",
    "accent": "FF6B35",        # огненный оранжевый
    "separator": "B87333",     # медный
}

#: Порядок секций в сводке: (ключ в summaries, заголовок)
SECTION_ORDER: List[Tuple[str, str]] = [
    ("melting", "Плавильное отделение"),
    ("molding", "Формовочное отделение"),
    ("cores", "Стержневое отделение"),
    ("sand_prep", "Смесеприготовительное отделение"),
    ("cleaning", "Отделение обрубки и очистки"),
    ("warehouses", "Складское хозяйство"),
    ("workforce", "Рабочая сила"),
    ("areas", "Площади"),
    ("transport", "Транспорт"),
]


@dataclass
class SummaryRow:
    """Одна строка сводной ведомости оборудования."""

    department: str          # отделение
    equipment: str           # наименование / модель
    units: int               # принятое количество
    load_factor: float       # коэффициент загрузки (0, если неприменим)
    note: str = ""           # комментарий (производительность, площадь и т.п.)

    def as_dict(self) -> Dict[str, Any]:
        """Серизовать строку в словарь для UI/экспорта."""
        return {
            "department": self.department,
            "equipment": self.equipment,
            "units": self.units,
            "load_factor": round(self.load_factor, 3),
            "note": self.note,
        }


@dataclass
class SummaryResult:
    """Итоговая сводка проекта: ключевые показатели + ведомость парка."""

    project_name: str = ""
    material_category: str = ""
    annual_output_t: float = 0.0
    metal_charge_t: float = 0.0
    annual_molds: int = 0
    annual_cores: int = 0
    workforce_total: int = 0
    building_area_m2: float = 0.0
    cranes_total: int = 0
    rows: List[SummaryRow] = field(default_factory=list)
    missing_sections: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evidence_blockers: List[str] = field(default_factory=list)
    ready: bool = True
    capacity_rows: List[Dict[str, Any]] = field(default_factory=list)
    capacity_has_deficit: bool = False
    capacity_unverified: bool = False
    shift_rows: List[Dict[str, Any]] = field(default_factory=list)
    shift_has_deficit: bool = False
    shift_lines_running: int = 0
    shift_hours: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        """Представить сводку словарём (для UI и экспорта)."""
        return {
            "project_name": self.project_name,
            "material_category": self.material_category,
            "annual_output_t": round(self.annual_output_t, 1),
            "metal_charge_t": round(self.metal_charge_t, 1),
            "annual_molds": self.annual_molds,
            "annual_cores": self.annual_cores,
            "workforce_total": self.workforce_total,
            "building_area_m2": round(self.building_area_m2, 1),
            "cranes_total": self.cranes_total,
            "rows": [r.as_dict() for r in self.rows],
            "missing_sections": list(self.missing_sections),
            "warnings": list(self.warnings),
            "evidence_blockers": list(self.evidence_blockers),
            "ready": self.ready,
            "capacity_rows": list(self.capacity_rows),
            "capacity_has_deficit": self.capacity_has_deficit,
            "capacity_unverified": self.capacity_unverified,
            "shift_rows": list(self.shift_rows),
            "shift_has_deficit": self.shift_has_deficit,
            "shift_lines_running": self.shift_lines_running,
            "shift_hours": self.shift_hours,
        }


def _f(data: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Безопасно извлечь float из словаря сводки."""
    try:
        return float(data.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _i(data: Dict[str, Any], key: str, default: int = 0) -> int:
    """Безопасно извлечь int из словаря сводки."""
    try:
        return int(float(data.get(key, default) or default))
    except (TypeError, ValueError):
        return default


def _park_rows(park: Any, department: str) -> List[SummaryRow]:
    """Разобрать секцию ``park`` (dict или list) в строки ведомости.

    Поддерживает форматы парков разных вкладок:
    * dict {ключ: {"title"/"model"/"unit", "units"/"machine_count", "load_factor"}}
    * list [{"name"/"title", ...}]

    Args:
        park: значение ключа ``park`` из сводки вкладки
        department: название отделения для строк результата

    Returns:
        Список непустых строк ведомости (единицы > 0 либо имя задано)
    """
    rows: List[SummaryRow] = []
    if isinstance(park, dict):
        items = list(park.values())
    elif isinstance(park, list):
        items = park
    else:
        return rows
    for it in items:
        if not isinstance(it, dict):
            continue
        name = (it.get("model") or it.get("unit") or it.get("name")
                or it.get("title") or "").strip()
        units = _i(it, "units") or _i(it, "machine_count") or _i(it, "count")
        lf = _f(it, "load_factor")
        note = str(it.get("note", "") or "")
        if not name and units == 0:
            continue
        rows.append(SummaryRow(department=department,
                               equipment=name or "—",
                               units=units, load_factor=lf, note=note))
    return rows


def build_summary(summaries: Dict[str, Dict[str, Any]],
                  project: Optional[Any] = None) -> SummaryResult:
    """Собрать сводную ведомость из сводок отделений.

    Args:
        summaries: результат ``MainWindow.department_summaries()`` —
            словарь ``{section_key: get_summary()}``; пустые словари
            трактуются как «данные ещё не рассчитаны»
        project: необязательный объект :class:`core.project.Project`
            для подстановки имени и объёма выпуска

    Returns:
        :class:`SummaryResult` с ключевыми показателями и ведомостью парка
    """
    res = SummaryResult()
    if project is not None:
        res.project_name = getattr(project, "name", "") or ""
        res.annual_output_t = float(getattr(project, "annual_output_t", 0.0) or 0.0)
        # Some lightweight integration clients use placeholder objects only
        # to indicate that a casting program exists. Audit real CastingItem
        # records; do not crash unrelated shift/capacity summaries on stubs.
        casting_rows = [c for c in (getattr(project, "castings", []) or [])
                        if isinstance(c, CastingItem)]
        issues = audit_castings(casting_rows) + audit_casting_technology(casting_rows)
        if issues:
            res.ready = False
            res.warnings.append(
                f"НЕ ПОДТВЕРЖДЕНА НОМЕНКЛАТУРА: {len(issues)} замечаний "
                "по количеству форм, массе металла и источникам технологических данных.")
            res.warnings.extend(i.describe() for i in issues[:16])
            if len(issues) > 16:
                res.warnings.append(
                    f"Ещё {len(issues)-16} замечаний в исходных данных. "
                    "Полный перечень откройте на вкладке «Исходные данные».")
        # The schedule may be an optimistic maximum until actual planned
        # downtime and per-worker absence assumptions are checked.
        if (getattr(project, "time_funds_calendar_applied", False)
                and not getattr(project, "time_funds_verified", False)
                and getattr(project, "castings", None)):
            res.ready = False
            res.warnings.append(
                "НЕ ПОДТВЕРЖДЕНО: фонд оборудования и одного работника "
                "основан на календаре без проверенных простоев и отсутствий. "
                "Уточните и подтвердите раздел «Фонды времени».")

    # Keep preliminary values visible; prevent the final report from being
    # marked ready while selected ferrous material and melting equipment
    # still rely on unverified example/catalog parameters.
    if project is not None and hasattr(project, "selected_alloy_id"):
        res.evidence_blockers = audit_calculation_sources(
            project, summaries.get("melting", {}) or {}
        )
        if res.evidence_blockers:
            res.ready = False
            res.warnings.append(
                "ИНЖЕНЕРНЫЕ ДАННЫЕ НЕ ПОДТВЕРЖДЕНЫ: "
                f"{len(res.evidence_blockers)} критичных замечаний к источникам. "
                "Числа ниже являются предварительными, а не готовым проектом."
            )

    melt = summaries.get("melting", {}) or {}
    mold = summaries.get("molding", {}) or {}
    cores = summaries.get("cores", {}) or {}
    sand = summaries.get("sand_prep", {}) or {}
    clean = summaries.get("cleaning", {}) or {}
    wh = summaries.get("warehouses", {}) or {}
    wf = summaries.get("workforce", {}) or {}
    areas = summaries.get("areas", {}) or {}
    tr = summaries.get("transport", {}) or {}

    # --- Ключевые показатели -----------------------------------------
    res.material_category = melt.get("material_category") or mold.get(
        "material_category", "")
    res.metal_charge_t = _f(melt, "metal_charge_t")
    res.annual_molds = _i(mold, "annual_molds_total")
    res.annual_cores = _i(cores, "annual_cores")
    res.workforce_total = _i(wf, "total") if wf.get("complete", True) else 0
    res.building_area_m2 = (_f(areas, "building_total_m2")
                            if areas.get("complete", True) else 0.0)
    res.cranes_total = _i(tr, "cranes_total")

    # --- Ведомость оборудования по отделениям -------------------------
    def one(dept: str, name: str, units: int, lf: float, note: str = "") -> None:
        if name or units:
            res.rows.append(SummaryRow(dept, name or "—", units, lf, note))

    if melt:
        one("Плавильное", melt.get("furnace_name", ""),
            _i(melt, "furnace_count"), _f(melt, "load_factor"),
            f"Металлозавалка {res.metal_charge_t:,.0f} т/год")
    if mold:
        if mold.get("batch_plan_feasible") is False and getattr(project, "castings", None):
            res.ready = False
            shortage = _i(mold, "annual_molds_total") - _i(mold, "assigned_molds")
            res.warnings.append(
                "НЕ ГОТОВО: формовочная программа не распределена полностью. "
                + str(mold.get("batch_planning_error") or
                      f"Не обеспечено {shortage:,} форм/год"))
        if mold.get("park"):
            res.rows.extend(_park_rows(mold["park"], "Формовочное"))
        elif not getattr(project, "castings", None):
            one("Формовочное", mold.get("line_name", ""),
                _i(mold, "line_count"), _f(mold, "load_factor"),
                f"{_i(mold, 'annual_molds_total'):,} форм/год")
    if cores and cores.get("core_data_complete") is False and getattr(project, "castings", None):
        res.ready = False
        res.warnings.append(
            "НЕ ПОДТВЕРЖДЕНО: число стержней в позициях с нулём может "
            "означать отсутствующие исходные данные. Проверьте номенклатуру "
            "и подтвердите нули на вкладке «Стержневое отделение».")
    if cores:
        one("Стержневое", cores.get("machine_name", ""),
            _i(cores, "machine_count"), _f(cores, "load_factor"),
            f"{_i(cores, 'annual_cores'):,} стержней/год")
    for dept_key, dept_title in (("sand_prep", "Смесеприготовительное"),
                                 ("cleaning", "Обрубка/очистка")):
        src = summaries.get(dept_key, {}) or {}
        rows = _park_rows(src.get("park"), dept_title)
        if rows:
            res.rows.extend(rows)
        elif src:
            one(dept_title, "", 0, 0.0)
    wrows = _park_rows(wh.get("park"), "Склады")
    if wrows:
        res.rows.extend(wrows)
    trows = _park_rows(tr.get("rows"), "Транспорт")
    if trows:
        res.rows.extend(trows)

    if wf.get("complete") is False:
        res.ready = False
        res.warnings.extend("Не рассчитана численность: " + str(v)
                            for v in wf.get("warnings", []))
    if areas.get("complete") is False:
        res.ready = False
        res.warnings.extend("Не рассчитана полная площадь: " + str(v)
                            for v in areas.get("warnings", []))

    # --- Какие секции не готовы ---------------------------------------
    for key, title in SECTION_ORDER:
        if not (summaries.get(key) or {}):
            res.missing_sections.append(title)
    if res.missing_sections:
        res.ready = False

    balance = calculate_plant_capacity(summaries, project)
    res.capacity_rows = [row.as_dict() for row in balance.rows]
    res.capacity_has_deficit = balance.has_deficit
    res.capacity_unverified = balance.unverified
    if balance.has_deficit:
        res.ready = False
        for row in balance.rows:
            if row.status == "deficit":
                shortage = (row.demand or 0) - (row.capacity or 0)
                res.warnings.append(
                    f"НЕДОСТАТОК МОЩНОСТИ: {row.department} — {row.stream}; "
                    f"дефицит {shortage:,.1f} {row.unit}")
    if balance.unverified:
        res.warnings.append(
            "Часть производственных потоков не проверена: "
            "отсутствуют паспортные данные или внутрисменный график")

    if project is not None:
        try:
            scenario = calculate_shift_stress(
                summaries,
                shift_hours=float(getattr(project, "shift_duration_h", 0)),
                concurrent_lines=int(mold.get("concurrent_line_limit", 0) or 0),
                ugar_pct=getattr(project, "ugar_pct", None),
            )
        except (ValueError, TypeError):
            res.warnings.append("Сменный сценарий не рассчитан: неверные параметры смены")
        else:
            res.shift_rows = [row.as_dict() for row in scenario.rows]
            res.shift_lines_running = scenario.lines_running
            res.shift_hours = scenario.shift_hours
            res.shift_has_deficit = scenario.has_deficit
            if scenario.has_deficit:
                res.ready = False
                for row in scenario.rows:
                    if row.status == "deficit":
                        res.warnings.append(
                            "СМЕННЫЙ ПИК: " + row.stream
                            + " — потребность выше теоретической подачи")
    return res


# ----------------------------------------------------------------------
# Экспорт в Excel
# ----------------------------------------------------------------------

def export_to_excel(result: SummaryResult, path: Path | str) -> Path:
    """Сохранить сводную ведомость в файл .xlsx (openpyxl).

    Лист «Сводка»: шапка проекта, ключевые показатели, ведомость парка,
    предупреждения о нерассчитанных разделах. Оформление — в палитре
    приложения (тёмный фон, золотой текст; белого цвета нет).

    Args:
        result: собранный :class:`SummaryResult`
        path: целевой файл (расширение .xlsx добавляется автоматически)

    Returns:
        Фактический путь к сохранённому файлу
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    p = Path(path)
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        p = p.with_suffix(".xlsx")
    p.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Сводка"

    fill_bg = PatternFill("solid", fgColor=XLSX_COLORS["bg_main"])
    fill_panel = PatternFill("solid", fgColor=XLSX_COLORS["bg_panel"])
    thin = Side(style="thin", color=XLSX_COLORS["separator"])
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    f_title = Font(name="Calibri", size=16, bold=True,
                   color=XLSX_COLORS["accent"])
    f_head = Font(name="Calibri", size=11, bold=True,
                  color=XLSX_COLORS["text_primary"])
    f_norm = Font(name="Calibri", size=11, color=XLSX_COLORS["text_primary"])
    f_note = Font(name="Calibri", size=10, italic=True,
                  color=XLSX_COLORS["text_secondary"])
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    row_idx = 1

    def paint(row: int, ncols: int, fill: PatternFill) -> None:
        for c in range(1, ncols + 1):
            cell = ws.cell(row=row, column=c)
            cell.fill = fill
            cell.border = border

    ncols = 5

    # Шапка
    ws.cell(row=row_idx, column=1, value="ЛитейныйЦех PRO — Сводная ведомость")
    ws.cell(row=row_idx, column=1).font = f_title
    ws.merge_cells(start_row=row_idx, start_column=1,
                   end_row=row_idx, end_column=ncols)
    paint(row_idx, ncols, fill_panel)
    row_idx += 1
    ws.cell(row=row_idx, column=1,
            value=f"Проект: {result.project_name or 'без названия'}")
    ws.cell(row=row_idx, column=1).font = f_head
    paint(row_idx, ncols, fill_panel)
    row_idx += 1
    ws.cell(row=row_idx, column=1,
            value=("СТАТУС: НЕПОЛНЫЙ ПРОЕКТ" if not result.ready
                   else "СТАТУС: предварительная инженерная оценка"))
    ws.cell(row=row_idx, column=1).font = f_head
    paint(row_idx, ncols, fill_panel)
    row_idx += 2

    # Ключевые показатели
    kpis: List[Tuple[str, str]] = [
        ("Материал (категория)", result.material_category or "—"),
        ("Годовой выпуск годных отливок, т", f"{result.annual_output_t:,.1f}"),
        ("Металлозавалка, т/год", f"{result.metal_charge_t:,.1f}"),
        ("Форм в год", f"{result.annual_molds:,}"),
        ("Стержней в год", f"{result.annual_cores:,}"),
        ("Численность рабочих, чел.", f"{result.workforce_total:,}"),
        ("Общая площадь здания цеха, м²", f"{result.building_area_m2:,.1f}"),
        ("Мостовых кранов, шт", f"{result.cranes_total:,}"),
    ]
    ws.cell(row=row_idx, column=1, value="Ключевые показатели")
    ws.cell(row=row_idx, column=1).font = f_head
    paint(row_idx, ncols, fill_panel)
    row_idx += 1
    for label, value in kpis:
        ws.cell(row=row_idx, column=1, value=label).font = f_norm
        ws.cell(row=row_idx, column=3, value=value).font = f_head
        ws.cell(row=row_idx, column=3).alignment = center
        paint(row_idx, ncols, fill_bg)
        row_idx += 1
    row_idx += 1

    # Ведомость оборудования
    ws.cell(row=row_idx, column=1, value="Ведомость принятого оборудования")
    ws.cell(row=row_idx, column=1).font = f_head
    paint(row_idx, ncols, fill_panel)
    row_idx += 1
    headers = ["Отделение", "Оборудование", "Кол-во, шт",
               "Коэф. загрузки", "Примечание"]
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=row_idx, column=c, value=h)
        cell.font = f_head
        cell.alignment = center
    paint(row_idx, ncols, fill_panel)
    row_idx += 1
    if result.rows:
        for r in result.rows:
            vals = [r.department, r.equipment, r.units,
                    round(r.load_factor, 3) if r.load_factor else "",
                    r.note]
            for c, v in enumerate(vals, start=1):
                cell = ws.cell(row=row_idx, column=c, value=v)
                cell.font = f_norm
                cell.alignment = center if c >= 3 else left
            paint(row_idx, ncols, fill_bg)
            row_idx += 1
    else:
        ws.cell(row=row_idx, column=1,
                value="Данные ещё не рассчитаны").font = f_note
        paint(row_idx, ncols, fill_bg)
        row_idx += 1
    row_idx += 1

    # Предупреждения
    if result.missing_sections:
        ws.cell(row=row_idx, column=1,
                value="⚠ Разделы без данных: "
                      + ", ".join(result.missing_sections)).font = f_note
        row_idx += 1

    if result.warnings:
        for warning in result.warnings:
            ws.cell(row=row_idx, column=1, value="⚠ " + warning).font = f_note
            row_idx += 1

    # Each unresolved engineering source is exported independently, so a
    # preliminary Excel cannot be mistaken for a certified project.
    evidence_ws = wb.create_sheet("Проверка источников")
    evidence_ws.append(["Статус", "Основание"])
    evidence_ws.append([
        "НЕ ПОДТВЕРЖДЕНО" if result.evidence_blockers else "Структурных замечаний нет",
        "Проверка источников не является подтверждением точности расчёта"
    ])
    for issue in result.evidence_blockers:
        evidence_ws.append(["БЛОКИРУЕТ ГОТОВНОСТЬ", issue])
    for row in evidence_ws.iter_rows():
        for cell in row:
            cell.fill = fill_panel if cell.row == 1 else fill_bg
            cell.font = f_head if cell.row == 1 else f_norm
            cell.border = border
    evidence_ws.column_dimensions["A"].width = 28
    evidence_ws.column_dimensions["B"].width = 115
    evidence_ws.freeze_panes = "B2"

    # На отдельном листе единицы потока не смешиваются, а статус unknown
    # отличается от реального дефицита мощности.
    balance_ws = wb.create_sheet("Баланс мощностей")
    headers_balance = ["Отделение", "Поток", "Потребность", "Мощность",
                       "Ед./статус", "Примечание"]
    for col, title in enumerate(headers_balance, 1):
        cell = balance_ws.cell(row=1, column=col, value=title)
        cell.font = f_head
        cell.fill = fill_panel
    for idx, row in enumerate(result.capacity_rows, 2):
        values = [
            row["department"], row["stream"],
            row["demand"], row["capacity"],
            str(row["unit"]) + " / " + str(row["status"]),
            row["note"],
        ]
        for col, val in enumerate(values, 1):
            cell = balance_ws.cell(row=idx, column=col, value=val)
            cell.font = f_norm
            cell.fill = fill_bg
            cell.border = border
    for col, width in enumerate((25, 40, 20, 20, 28, 72), 1):
        balance_ws.column_dimensions[get_column_letter(col)].width = width
    balance_ws.freeze_panes = "C2"
    balance_ws.auto_filter.ref = f"A1:F{max(1, len(result.capacity_rows) + 1)}"

    if result.shift_rows:
        shift_ws = wb.create_sheet("Сменный сценарий")
        shift_ws.append([
            "Проверка пика, не календарь", "Потребность", "Подача",
            "Единицы", "Статус", "Ограничение",
        ])
        for col in range(1, 7):
            shift_ws.cell(row=1, column=col).font = f_head
            shift_ws.cell(row=1, column=col).fill = fill_panel
        for entry in result.shift_rows:
            shift_ws.append([
                entry["stream"], entry["demand"], entry["available"],
                entry["unit"], entry["status"], entry["note"],
            ])
            for col in range(1, 7):
                cell = shift_ws.cell(row=shift_ws.max_row, column=col)
                cell.font = f_norm
                cell.fill = fill_bg
                cell.border = border
        for col, width in enumerate((40, 20, 20, 20, 18, 80), 1):
            shift_ws.column_dimensions[get_column_letter(col)].width = width
        shift_ws.freeze_panes = "B2"

    widths = [26, 34, 12, 16, 34]
    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w

    wb.save(p)
    return p
