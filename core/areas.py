"""Расчёт площадей производственных участков литейного цеха (раздел 10).

Методика — по методичке и обоим дипломным примерам: полезная площадь
участка рассчитывается по формуле

    F_полезн = L · l₁ + B · l₂ + C · l₃ + … + G,

где ``L, B, C, …`` — количество единиц оборудования данного типоразмера,
а ``l₁, l₂, l₃, …`` — его габаритная площадь в плане (м²); ``G`` — площадь
прочего немонтируемого оборудования. Принятая (расчётная) площадь участка
получается делением полезной площади на коэффициент использования площади:

    F_принят = F_полезн / K_исп.

Источники данных — только JSON-справочники через ``DataLoader``
(``config.DATA_DIR``): отделения берутся из выбранных пользователем
карточек оборудования (``user_data/choices.json``), при отсутствии выбора
используется лучший вариант по скорингу каждого отделения.

Площади складов считаются в :mod:`core.warehouse` и сюда только
подключаются как отдельная строка ведомости.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: Доля подсобно-ремонтных помещений от производственной площади цеха
#: (металлорежущие и кузнечно-сварочные участки, дипломы, раздел 10).
AUX_PRODUCTION_SHARE: float = 0.15
#: Доля бытовых помещений от производственной площади цеха
#: (санпропускники, душевые, гардеробные; методичка ~12–18 %).
SANITARY_SHARE: float = 0.15

_DEFAULT_FOOTPRINT_PATTERN = re.compile(
    r"(?P<l>\d+(?:[.,]\d+)?)\s*[xх*]\s*(?P<w>\d+(?:[.,]\d+)?)"
    r"(?:\s*x\s*\d+(?:[.,]\d+)?)?\s*мм", re.IGNORECASE)

#: Типовые габариты в плане для оборудования без явных размеров, м².
#: Значения — по укрупнённым нормам площадок (методичка, раздел 10):
#: площадь места с учётом подходов и обслуживания.
DEFAULT_UNIT_AREAS_M2: Dict[str, float] = {
    # Индукционные сталеплавильные печи (ИСТ): печь + завалочная площадка
    "furnace_ist": 35.0,
    # Дуговые сталеплавильные печи (ДСП): печь + электроузел + завалка
    "furnace_dsp": 45.0,
    # Вагранки (ВПЖ): вагранка + завалочный транспорт
    "furnace_vpzh": 30.0,
    # Тигельные (ТГА) и сопротивления (ТС) малоёмкостные печи
    "furnace_small": 12.0,
    # Автоматические формовочные линии (АФЛ): у ИЛ-225 явные габариты
    # в справочнике; для прочих линий — типовое место АФЛ средней длины
    "line_afl": 800.0,
    # Ручная/стендовая формовка на площадках (опочная)
    "molding_manual": 25.0,
    # Линии литья в кокиль/оболочки (ТЛ и аналоги)
    "line_other": 300.0,
    # Стержневые автоматы/полуавтоматы среднего размера
    "core_machine": 16.0,
    # Смесители, бегуны, сита, охладители, дробилки (позиции АСМ)
    "sand_machine": 10.0,
    # Дробемётные барабаны непрерывного действия (ДБНД)
    "cleaning_drum": 30.0,
    # Камерные очистные установки (дробемёт/пескоструй)
    "cleaning_chamber": 15.0,
    # Печи термообработки (нормализация, отжиг) — посадка с загрузкой
    "thermal_furnace": 60.0,
    # Конвейеры (охлаждение/подачи) — единица длины трассы
    "conveyor": 8.0,
    # Станки индивидуального типа (обрубка, зачистка) — место станка
    "machine_tool": 6.0,
}

#: Префиксы id печей из ``furnaces.json`` → ключ типовых габаритов.
_FURNACE_AREA_KEYS: Dict[str, str] = {
    "IST": "furnace_ist", "DSP": "furnace_dsp", "VPZH": "furnace_vpzh",
    "TGA": "furnace_small", "TS": "furnace_small",
}

#: Префиксы id прочего оборудования (кириллица транслитом из JSON) →
#: ключ типовых габаритов. Порядок проверки — от более длинных к коротким.
_OTHER_AREA_KEYS: List[Tuple[str, str]] = [
    # Формовочные линии: АФЛ и аналоги
    ("IL-", "line_afl"), ("KV", "line_afl"),
    ("TL-", "line_other"),
    # Стержневое оборудование
    ("SCL", "core_machine"), ("C-23229", "core_machine"),
    ("C-1701", "core_machine"), ("Z8612", "core_machine"),
    ("ZB08", "core_machine"),
    # Смесеприготовление (поз. АСМ): бегуны, смесители, сита, дробилки
    ("15126", "sand_machine"), ("1A11", "sand_machine"),
    ("C-110", "sand_machine"),
    ("D3G", "sand_machine"), ("D4G", "sand_machine"),
    ("SITO", "sand_machine"), ("OHL", "sand_machine"),
    ("SEPARATOR", "sand_machine"),
    # Очистка и термообработка
    ("CONV", "conveyor"),
    ("SHAKEOUT", "cleaning_drum"), ("DRUM", "cleaning_drum"),
    ("SHOT-BAY", "cleaning_chamber"), ("BLAST", "cleaning_chamber"),
    ("PMR", "machine_tool"), ("DISC", "machine_tool"),
    ("ZM", "machine_tool"),
    ("NORMALIZE", "thermal_furnace"), ("FURNACE", "thermal_furnace"),
]


def default_unit_area_m2(equipment_id: str) -> float:
    """Типовая площадь места для оборудования без явных габаритов, м².

    Args:
        equipment_id: id карточки оборудования (``IST-6M1``, ``SCL-540``,
            ``DRUM-42322``…)

    Returns:
        Укрупнённая площадь одного места; 0.0 для неизвестных типов
    """
    uid = str(equipment_id or "").upper()
    if not uid:
        return 0.0
    prefix = re.split(r"[-_\s]", uid)[0]
    if prefix in _FURNACE_AREA_KEYS:
        return DEFAULT_UNIT_AREAS_M2[_FURNACE_AREA_KEYS[prefix]]
    for token, key in _OTHER_AREA_KEYS:
        if uid.startswith(token):
            return DEFAULT_UNIT_AREAS_M2[key]
    return 0.0


@dataclass
class AreaRow:
    """Строка ведомости площадей: один участок или помещение."""

    key: str                    # ключ секции приложения ("melting_tab" и т.п.)
    name: str                   # название участка
    units: int                  # принятое количество единиц оборудования
    footprint_m2: float         # суммарная габаритная (полезная) площадь, м²
    area_m2: float              # принятая (расчётная) площадь участка, м²
    basis: str                  # человекочитаемое обоснование расчёта

    def as_dict(self) -> Dict[str, Any]:
        """Сериализовать строку ведомости в словарь."""
        return {
            "key": self.key, "name": self.name, "units": self.units,
            "footprint_m2": round(self.footprint_m2, 1),
            "area_m2": round(self.area_m2, 1), "basis": self.basis,
        }


@dataclass
class AreasResult:
    """Итоговый расчёт площадей цеха: ведомость участков и свод здания."""

    rows: List[AreaRow] = field(default_factory=list)
    warehouse_area_m2: float = 0.0
    production_total_m2: float = 0.0   # производственные участки + склады
    aux_repair_m2: float = 0.0         # подсобно-ремонтные помещения
    sanitary_m2: float = 0.0           # бытовые помещения
    building_total_m2: float = 0.0      # общая площадь здания цеха
    complete: bool = True              # все обязательные участки рассчитаны
    warnings: List[str] = field(default_factory=list)

    @property
    def sections(self) -> List[Tuple[str, float]]:
        """Пары «название участка → принятая площадь» для диаграмм/отчётов."""
        out = [(r.name, r.area_m2) for r in self.rows]
        if self.warehouse_area_m2 > 0:
            out.append(("Складское хозяйство", round(self.warehouse_area_m2, 1)))
        return out

    def as_dict(self) -> Dict[str, Any]:
        """Представить весь результат словарём (для UI и экспорта)."""
        return {
            "rows": [r.as_dict() for r in self.rows],
            "warehouse_area_m2": round(self.warehouse_area_m2, 1),
            "production_total_m2": round(self.production_total_m2, 1),
            "aux_repair_m2": round(self.aux_repair_m2, 1),
            "sanitary_m2": round(self.sanitary_m2, 1),
            "building_total_m2": round(self.building_total_m2, 1),
            "complete": self.complete,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Извлечение габаритной площади единицы оборудования
# ---------------------------------------------------------------------------

def unit_footprint_m2(equipment: Dict[str, Any]) -> float:
    """Габаритная площадь одной единицы оборудования в плане, м².

    Ищет площадь в явных полях ``footprint_m2`` / ``area_m2`` (словарь
    карточки или ``specs``), затем пытается распарсить строку габаритов
    ``footprint_mm`` вида ``65200x9300x6855 мм`` (длина × ширина, высота
    игнорируется). Если явных данных нет — возвращает типовую укрупнённую
    норму площади места (:func:`default_unit_area_m2`).

    Args:
        equipment: карточка оборудования из любого отделения

    Returns:
        Площадь в м²; 0.0, если данных нет и тип не распознан
    """
    for source in (equipment, equipment.get("specs") or {}):
        for key in ("footprint_m2", "total_footprint_m2", "area_m2"):
            try:
                val = float(source.get(key) or 0.0)
            except (TypeError, ValueError):
                val = 0.0
            if val > 0:
                return val
    text = str((equipment.get("specs") or {}).get("footprint_mm")
               or equipment.get("footprint_mm") or "")
    m = _DEFAULT_FOOTPRINT_PATTERN.search(text)
    if not m:
        parts = re.split(r"[xх*,]", re.sub(r"\s*мм.*$", "", text, flags=re.I))
        nums = []
        for p in parts:
            try:
                nums.append(float(p.replace(",", ".").strip()))
            except ValueError:
                nums = []
                break
        if len(nums) >= 2 and all(n > 0 for n in nums[:2]):
            return nums[0] * nums[1] / 1e6
        # Явных габаритов нет — укрупнённая типовая норма по id модели
        return default_unit_area_m2(str(equipment.get("id")
                                        or equipment.get("model") or ""))
    length = float(m.group("l").replace(",", "."))
    width = float(m.group("w").replace(",", "."))
    return length * width / 1e6


def _unit_count(equipment: Dict[str, Any]) -> int:
    """Принятое количество единиц в выбранной карточке оборудования."""
    for key in ("_num_required", "unit_count", "count"):
        try:
            n = int(float(equipment.get(key) or 0))
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            return n
    return 1 if equipment else 0


# ---------------------------------------------------------------------------
# Сбор отделений проекта
# ---------------------------------------------------------------------------

def collect_departments(
    project: Any,
    *,
    loader: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Собрать принятые отделения с их оборудованием и площадью.

    Для каждого отделения берётся сохранённый выбор пользователя
    (``user_data/choices.json`` через :class:`core.user_choices.UserChoices`);
    если выбора нет — первый (лучший по скорингу) вариант расчёта
    отделения.

    Args:
        project: модель :class:`core.project.Project`
        loader: загрузчик справочников (для тестов)

    Returns:
        Список словарей ``{key, title, equipment, count, footprint_m2}``
    """
    from core.user_choices import UserChoices
    from config import DATA_DIR
    from data.loader import DataLoader

    if loader is None:
        loader = DataLoader(DATA_DIR)
    uc = UserChoices()
    pid = str(getattr(project, "project_id", ""))
    departments: List[Dict[str, Any]] = []

    def add(key: str, title: str, equipment: Optional[Dict[str, Any]],
            count: Optional[int] = None) -> None:
        """Добавить участок в ведомость (если есть оборудование и габариты)."""
        if not equipment:
            return
        departments.append({
            "key": key, "title": title, "equipment": equipment,
            "count": count if count is not None else _unit_count(equipment),
            "footprint_m2": unit_footprint_m2(equipment),
        })

    def saved_id(category: str) -> Optional[str]:
        """Сохранённый id оборудования категории для текущего проекта."""
        entry = uc.get_choice(pid, category) or {}
        return entry.get("equipment_id") or None

    def saved_map(category: str) -> Dict[str, str]:
        """Сохранённая карта ``{позиция: id}`` для многотипных отделений."""
        return uc.get_operation_choices(pid, category)

    # ── Плавильное ────────────────────────────────────────────────
    from core.melting import calc_metal_charge
    from core.equipment_selector import EquipmentSelector

    charge_t = float(getattr(project, "metal_charge_t", 0.0) or 0.0)
    if charge_t <= 0:
        charge_t = float(calc_metal_charge(
            annual_output_t=float(getattr(project, "annual_output_t", 0.0) or 0.0),
            brak_pct=float(getattr(project, "brak_pct", 5.0) or 0.0),
            litniki_pribyli_pct=float(
                getattr(project, "litniki_pribyli_pct", 28.9) or 0.0),
            ugar_pct=float(getattr(project, "ugar_pct", 5.0) or 0.0)))
    fund = float(getattr(project, "F_equipment_h", 3890.0) or 3890.0)
    category = loader.get_alloy_category(
        getattr(project, "selected_alloy_id", "") or "")
    selector = EquipmentSelector(loader)
    furnace_opts = selector.find_furnaces(category, charge_t, fund, top_n=5)
    fid = saved_id(UserChoices.EQUIPMENT_CATEGORY)
    furnace = next((o for o in furnace_opts if o.get("id") == fid),
                   furnace_opts[0] if furnace_opts else None)
    add("melting_tab", "Плавильное отделение", furnace)

    # ── Формовочное ───────────────────────────────────────────────
    from core.molding import calc_molding

    molding = calc_molding(project,
                           selected_line_id=saved_id(
                               UserChoices.MOLDING_LINE_CATEGORY))
    # Для номенклатуры используем ПАРК общих линий, а не одну выбранную
    # модель. Невыполнимый план нельзя заменить старым оптимистичным подбором.
    if getattr(project, "castings", None):
        plan = molding.batch_plan
        if plan is not None and plan.feasible:
            from collections import Counter
            from core.molding.afl_calc import MoldingCalculator
            catalog = MoldingCalculator()
            counts = Counter(line.equipment_id for line in plan.lines)
            for equipment_id, count in sorted(counts.items()):
                card = catalog.get_line_by_id(equipment_id)
                if not card:
                    raise ValueError(f"Нет габаритов принятой линии {equipment_id}")
                add("molding_tab", "Формовочное: " + str(card.get("name", equipment_id)),
                    card, count=count)
    else:
        add("molding_tab", "Формовочное отделение", molding.selected_line,
            count=molding.line_count)

    # ── Стержневое ────────────────────────────────────────────────
    from core.core_making import CoreCalculator
    from core.molding import calc_avg_cores_per_mold

    core_calc = CoreCalculator(loader)
    cores = core_calc.calc_cores(
        material_category=category,
        annual_molds=molding.annual_molds_total,
        cores_per_mold=calc_avg_cores_per_mold(
            list(getattr(project, "castings", []) or [])),
        working_hours=fund,
        selected_machine_id=saved_id(UserChoices.CORE_MACHINE_CATEGORY),
    )
    chosen_core = next((o for o in cores["options"]
                        if o.get("id") == cores["selected_machine_id"]), {})
    add("core_tab", "Стержневое отделение", chosen_core,
        count=cores["machine_count"])

    # ── Смесеприготовительное ─────────────────────────────────────
    from core.sand_prep import calc_sand_prep

    sand = calc_sand_prep(project, selected_ids=saved_map(
        UserChoices.SAND_PREP_CATEGORY))
    for section in sand.get("operations", []):
        opts = section.get("options") or []
        chosen = next((o for o in opts
                       if o.get("id") == section.get("selected_id")), None)
        if chosen and int(section.get("units") or 0) > 0:
            add("sand_tab",
                f"Смесеприготовление: {section.get('title', '')}",
                chosen, count=int(section["units"]))

    # ── Обрубка и очистка ─────────────────────────────────────────
    from core.cleaning import calc_cleaning

    cleaning = calc_cleaning(project, selected_ids=saved_map(
        UserChoices.CLEANING_CATEGORY))
    for op_key, section in (cleaning.get("operations") or {}).items():
        opts = section.get("options") or []
        chosen = next((o for o in opts
                       if o.get("id") == section.get("selected_id")), None)
        if chosen and int(section.get("machine_count") or 0) > 0:
            add("cleaning_tab",
                f"Очистка: {section.get('title', op_key)}",
                chosen, count=int(section["machine_count"]))

    return departments


# ---------------------------------------------------------------------------
# Основной расчёт
# ---------------------------------------------------------------------------

def calc_areas(
    project: Any,
    *,
    loader: Optional[Any] = None,
    warehouse_area_m2: Optional[float] = None,
) -> AreasResult:
    """Рассчитать ведомость площадей цеха по принятому оборудованию.

    Args:
        project: модель проекта
        loader: загрузчик справочников (для тестов)
        warehouse_area_m2: готовая площадь складов; если ``None`` —
            считается через :func:`core.warehouse.calc_warehouses`

    Returns:
        Заполненный :class:`AreasResult`
    """
    from core.user_choices import UserChoices

    departments = collect_departments(project, loader=loader)

    complete = True
    warnings: List[str] = []
    if getattr(project, "castings", None):
        from core.molding import calc_molding
        molding = calc_molding(project)
        if molding.batch_plan is None or not molding.batch_plan.feasible:
            complete = False
            warnings.append(
                "Не подобран полный парк формовочных линий: площадь здания "
                "является частичной оценкой, а не итоговым проектом. "
                + (molding.planning_error or
                   ("Не распределены: " + ", ".join(molding.batch_plan.unassigned)
                    if molding.batch_plan else "Расчёт плана не выполнен")))

    rows: List[AreaRow] = []
    prod_sum = 0.0
    for dep in departments:
        count = max(int(dep.get("count") or 1), 1)
        footprint = float(dep["footprint_m2"]) * count
        # Принятая площадь = полезная/K_исп; K_исп = 0.7 — типовое значение
        # методички для механизированных участков.
        k_use = 0.7
        area = footprint / k_use if footprint > 0 else 0.0
        if area <= 0:
            continue
        rows.append(AreaRow(
            key=dep["key"], name=dep["title"], units=count,
            footprint_m2=footprint, area_m2=math.ceil(area),
            basis=f"{count} ед. × {float(dep['footprint_m2']):,.0f} м² "
                  f"/ Kисп={k_use:g}"))
        prod_sum += rows[-1].area_m2

    if warehouse_area_m2 is None:
        from core.warehouse import calc_warehouses, total_warehouse_area
        uc = UserChoices()
        wh_results = calc_warehouses(
            project,
            selected_ids=uc.get_operation_choices(
                str(getattr(project, "project_id", "")),
                UserChoices.WAREHOUSE_CATEGORY))
        warehouse_area_m2 = total_warehouse_area(wh_results)

    production_total = prod_sum + warehouse_area_m2
    aux_repair = production_total * AUX_PRODUCTION_SHARE
    sanitary = production_total * SANITARY_SHARE
    building_total = production_total + aux_repair + sanitary

    return AreasResult(
        rows=rows,
        warehouse_area_m2=round(warehouse_area_m2, 1),
        production_total_m2=round(production_total, 1),
        aux_repair_m2=round(aux_repair, 1),
        sanitary_m2=round(sanitary, 1),
        building_total_m2=round(building_total, 1),
        complete=complete,
        warnings=warnings,
    )


__all__ = [
    "AUX_PRODUCTION_SHARE", "SANITARY_SHARE",
    "AreaRow", "AreasResult",
    "unit_footprint_m2", "collect_departments", "calc_areas",
]
