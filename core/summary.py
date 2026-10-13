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
    res.workforce_total = _i(wf, "total")
    res.building_area_m2 = _f(areas, "building_total_m2")
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
        one("Формовочное", mold.get("line_name", ""),
            _i(mold, "line_count"), _f(mold, "load_factor"),
            f"{_i(mold, 'annual_molds_total'):,} форм/год")
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

    # --- Какие секции не готовы ---------------------------------------
    for key, title in SECTION_ORDER:
        if not (summaries.get(key) or {}):
            res.missing_sections.append(title)
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

    widths = [26, 34, 12, 16, 34]
    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w

    wb.save(p)
    return p
