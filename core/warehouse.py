"""Расчёт складского хозяйства литейного цеха (раздел «Склады»).

Логика опирается на оба дипломных примера и методичку:

* Годовые потребности в материалах считаются от металлозавалки
  ``calc_metal_charge`` (шихта) и от годового объёма песчано-глинистых
  смесей ``core.sand_prep`` (формовочные и стержневые материалы).
* Требуемая разовая вместимость склада — по формуле запаса:
  ``Q_скл = G_год / 365 * T_xран / K_neer``, где ``G_год`` — годовой расход,
  ``T_xран`` — норма хранения в сутках, ``K_neer`` — коэффициент
  неравномерности потребления (методичка, дипломы, табл. 14/15).
* Площадь склада — подбором единиц хранения из справочника
  ``data/equipment/warehouse_equip.json`` (вместимость ед. × площадь ед.).
* Склады опок, модельной оснастки и инструмента — по удельным нормативам
  (площадь на тонну комплекта / на рабочего), как в разделах 9–10 дипломов.

Все справочники читаются только из JSON через ``DataLoader`` (``config.DATA_DIR``).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from core.warehouse_meta import WAREHOUSES, WAREHOUSE_TITLES
from data.loader import DataLoader

#: Каталог пользовательских данных рядом с каталогом приложения
# Пользовательские справочники не должны храниться внутри PyInstaller bundle.
from config import USER_DATA_DIR

# ---------------------------------------------------------------------------
# Константы нормативов (методичка + оба диплома)
# ---------------------------------------------------------------------------

#: Норма хранения шихтовых материалов, суток.
STORAGE_DAYS_CHARGE: float = 30.0
#: Норма хранения свежих формовочных материалов, суток.
STORAGE_DAYS_MOLDING_SAND: float = 60.0
#: Норма хранения стержневых материалов, суток.
STORAGE_DAYS_CORE_MATERIALS: float = 15.0

#: Коэффициент неравномерности поступления/потребления материалов.
DEFAULT_K_IRREGULARITY: float = 1.2

#: Удельная площадь склада опок, м² на 1 т массы комплекта опок.
FLASK_AREA_M2_PER_TONN: float = 1.2
#: Средняя масса комплекта опок на 1 форму, кг (укрупнённо).
FLASK_KG_PER_MOLD: float = 28.0
#: Оборачиваемость опок: среднее число форм, делаемых в одном комплекте за год.
FLASK_TURNOVER_PER_YEAR: int = 60

#: Удельная площадь склада модельной оснастки, м² на 1 т оснастки.
PATTERN_AREA_M2_PER_TONN: float = 2.0
#: Доля массы модельной оснастки от годовой программы отливок.
PATTERN_MASS_SHARE: float = 0.004

#: Удельная площадь склада инструмента и приспособлений, м² на рабочего.
TOOLS_AREA_M2_PER_WORKER: float = 0.6
#: Укрупненный выход рабочих мест на 1000 т годовой программы (чел./1000 т).
WORKERS_PER_1000T: float = 22.0

#: Насыпная плотность шихты/песка в штабеле или бункере, т/м³.
BULK_DENSITY_T_M3: float = 1.5
#: Средняя высота хранения сыпучих по нормативам (штабель на площадке), м.
STORAGE_HEIGHT_M: float = 1.5
#: Коэффициент использования площади склада (проходы, развороты, транспорт).
AREA_USAGE_K: float = 0.6
#: Высота складирования в закрытых бункерах и силосах, м.
BIN_STORAGE_HEIGHT_M: float = 3.0
#: Минимальная площадь одного склада, м².
MIN_WAREHOUSE_AREA_M2: float = 40.0

#: Максимальное число подбираемых единиц хранения одного типа.
MAX_STORAGE_UNITS: int = 40
#: Предельно допустимый запас площади сверх норматива (иначе вариант отбрасывается).
MAX_AREA_OVERNORM_RATIO: float = 2.5


@dataclass
class WarehouseRequirement:
    """Норматив одного склада: запас, вместимость и эталонная площадь."""

    key: str
    title: str
    basis: str                      # человекочитаемое описание расхода
    annual_need_t: Optional[float]  # годовой расход/поступление, т (None — штучный)
    storage_days: Optional[float]   # норма хранения, сутки
    k_irregularity: float
    required_capacity_t: Optional[float]  # требуемая разовая вместимость, т
    area_norm_hint_m2: Optional[float]    # эталонная (нормативная) площадь, м²
    unit: str = "т"                 # единица запаса ("т" или иное)


@dataclass
class WarehouseResult:
    """Итоговый расчёт склада: подобранное оборудование и площадь."""

    requirement: WarehouseRequirement
    units: List[Dict[str, Any]] = field(default_factory=list)  # карточки picker'а
    total_area_m2: float = 0.0
    total_capacity_t: float = 0.0
    notes: str = ""

    @property
    def key(self) -> str:
        """Ключ склада (совпадает с ``WarehouseRequirement.key``)."""
        return self.requirement.key

    @property
    def title(self) -> str:
        """Человекочитаемое название склада."""
        return self.requirement.title


# ---------------------------------------------------------------------------
# Потребности складов
# ---------------------------------------------------------------------------

def _annual_molds(project: Any) -> int:
    """Годовое число форм по номенклатуре (поле ``molds_per_year``)."""
    total = 0
    for item in getattr(project, "castings", []) or []:
        try:
            total += int(getattr(item, "molds_per_year", 0) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _charge_from_melting(melt: Any) -> float:
    """Достать годовую металлозавалку из результата ``calc_metal_charge``.

    ``calc_metal_charge`` возвращает просто число (т); поддержка словаря и
    объекта с полем ``metal_charge_t`` оставлена на случай расширения API.
    """
    if isinstance(melt, (int, float)):
        return float(melt)
    if isinstance(melt, dict):
        for k in ("metal_charge_t", "charge_t", "annual_charge_t"):
            if k in melt:
                return float(melt[k])
        raise KeyError(f"В результате нет поля металлозавалки: {list(melt)}")
    return float(getattr(melt, "metal_charge_t"))


def _mix_tonnages(project: Any) -> tuple:
    """Годовые массы свежих формовочной и стержневой смесей, т.

    Считает геометрический баланс смеси через ``calc_sand_volumes``
    (тот же путь, что и вкладка «Смесеприготовительное»), с запасом на
    выбывание/дополнение по дипломам. Если номенклатуры нет — типовые
    нормы из методички: ~1.5 т формовочной и ~0.25 т стержневой смеси
    на тонну годного литья.

    Args:
        project: модель проекта.

    Returns:
        Кортеж ``(molding_mix_t_per_year, core_mix_t_per_year)``.
    """
    from core.sand_prep import calc_sand_volumes  # локальный импорт против циклов

    castings = list(getattr(project, "castings", []) or [])
    if not castings:
        output_t = float(getattr(project, "annual_output_t", 0.0) or 0.0)
        return round(output_t * 1.5, 1), round(output_t * 0.25, 1)

    weights = sum(int(getattr(c, "molds_per_year", 0) or 0) for c in castings) or 1
    metal_per_mold = sum(
        float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0)
        * int(getattr(c, "molds_per_year", 0) or 0) for c in castings) / weights
    core_mass_per_mold = sum(
        float(getattr(c, "core_mass_kg", 0.0) or 0.0)
        * int(getattr(c, "cores_count", 0) or 0)
        * int(getattr(c, "molds_per_year", 0) or 0) for c in castings) / weights
    mold_volume = sum(
        _flask_vol_m3(c) * int(getattr(c, "molds_per_year", 0) or 0)
        for c in castings) / weights
    vols = calc_sand_volumes(_annual_molds(project), mold_volume,
                             metal_per_mold, core_mass_per_mold)
    molding_t = float(vols.get("sand_mass_loose_t", 0.0))
    core_t = sum(float(getattr(c, "core_mass_kg", 0.0) or 0.0)
                 * int(getattr(c, "cores_count", 0) or 0)
                 * int(getattr(c, "molds_per_year", 0) or 0)
                 for c in castings) / 1000.0
    return round(molding_t, 1), round(core_t, 1)


def _flask_vol_m3(item: Any) -> float:
    """Объём опки позиции в м³ по габаритам (0, если данных нет)."""
    try:
        l = float(getattr(item, "length_mm", 0.0) or 0.0)
        w = float(getattr(item, "width_mm", 0.0) or 0.0)
        h = float(getattr(item, "height_mm", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if l > 0 and w > 0 and h > 0:
        return l * w * h / 1e9
    return 0.0


def _bulk_area_m2(capacity_t: float) -> float:
    """Площадь под сыпучий запас: ``F = Q / (ρ * h * k_исп)`` (методичка)."""
    if capacity_t <= 0:
        return MIN_WAREHOUSE_AREA_M2
    area = capacity_t / (BULK_DENSITY_T_M3 * STORAGE_HEIGHT_M * AREA_USAGE_K)
    return max(math.ceil(area), MIN_WAREHOUSE_AREA_M2)


def _department_workers(project: Any) -> float:
    """Оценка общего списочного числа рабочих цеха (основных + вспомогательных).

    Используется только как резерв для склада инструмента, когда модуль
    :mod:`core.workforce` недоступен (циклический импорт, пустой проект).

    Args:
        project: модель проекта.

    Returns:
        Приблизительное число рабочих, чел.
    """
    output_t = float(getattr(project, "annual_output_t", 0.0) or 0.0)
    return output_t / 1000.0 * WORKERS_PER_1000T


def calc_warehouse_requirements(
    project: Any,
    *,
    loader: Optional[DataLoader] = None,
    k_irregularity: float = DEFAULT_K_IRREGULARITY,
    workers_total: Optional[float] = None,
) -> List[WarehouseRequirement]:
    """Рассчитать нормативы по всем шести складам для проекта.

    Args:
        project: объект :class:`core.project.Project` (или совместимый).
        loader: необязательный загрузчик справочников (для тестов).
        k_irregularity: коэффициент неравномерности потребления.
        workers_total: списочная численность рабочих цеха (из
            :mod:`core.workforce`); если не передана — считается сам.

    Returns:
        Список :class:`WarehouseRequirement` в порядке ведомости площадей.
    """
    from core.melting import calc_metal_charge  # локальный импорт против циклов

    reqs: List[WarehouseRequirement] = []

    # --- 1. Шихтовые материалы --------------------------------------------
    charge_t = _charge_from_melting(calc_metal_charge(
        annual_output_t=float(getattr(project, "annual_output_t", 0.0) or 0.0),
        brak_pct=float(getattr(project, "brak_pct", 5.0) or 0.0),
        litniki_pribyli_pct=float(getattr(project, "litniki_pribyli_pct", 28.9) or 0.0),
        ugar_pct=float(getattr(project, "ugar_pct", 5.0) or 0.0),
    ))
    days = STORAGE_DAYS_CHARGE
    cap = charge_t / 365.0 * days / k_irregularity
    reqs.append(WarehouseRequirement(
        key="charge", title=WAREHOUSE_TITLES["charge"],
        basis=f"Металлозавалка {charge_t:,.0f} т/год, хранение {days:.0f} сут",
        annual_need_t=charge_t, storage_days=days, k_irregularity=k_irregularity,
        required_capacity_t=cap, area_norm_hint_m2=_bulk_area_m2(cap),
    ))

    # --- 2/3. Формовочные и стержневые материалы --------------------------
    molding_t, core_t = _mix_tonnages(project)
    for key, tonnage, dstore in (
        ("molding_sand", molding_t, STORAGE_DAYS_MOLDING_SAND),
        ("core_materials", core_t, STORAGE_DAYS_CORE_MATERIALS),
    ):
        cap = tonnage / 365.0 * dstore / k_irregularity
        reqs.append(WarehouseRequirement(
            key=key, title=WAREHOUSE_TITLES[key],
            basis=f"Смесей {tonnage:,.0f} т/год, хранение {dstore:.0f} сут",
            annual_need_t=tonnage, storage_days=dstore, k_irregularity=k_irregularity,
            required_capacity_t=cap, area_norm_hint_m2=_bulk_area_m2(cap),
        ))

    # --- 4. Опки -----------------------------------------------------------
    molds = _annual_molds(project)
    flask_sets = math.ceil(molds / FLASK_TURNOVER_PER_YEAR) if molds else 0
    flasks_t = flask_sets * FLASK_KG_PER_MOLD / 1000.0
    flask_area = max(flasks_t * FLASK_AREA_M2_PER_TONN, MIN_WAREHOUSE_AREA_M2)
    reqs.append(WarehouseRequirement(
        key="flasks", title=WAREHOUSE_TITLES["flasks"],
        basis=(f"{molds:,} форм/год → комплект опок ≈{flask_sets:,} шт "
               f"(≈{flasks_t:,.0f} т)"),
        annual_need_t=None, storage_days=None, k_irregularity=1.0,
        required_capacity_t=flasks_t, area_norm_hint_m2=math.ceil(flask_area),
        unit="т опок",
    ))

    # --- 5. Модельная оснастка ---------------------------------------------
    output_t = float(getattr(project, "annual_output_t", 0.0))
    pattern_t = max(output_t * PATTERN_MASS_SHARE, 5.0)
    pattern_area = max(pattern_t * PATTERN_AREA_M2_PER_TONN, 50.0)
    reqs.append(WarehouseRequirement(
        key="patterns", title=WAREHOUSE_TITLES["patterns"],
        basis=f"Оснастка ≈{pattern_t:,.0f} т ({PATTERN_MASS_SHARE:.1%} программы "
              f"{output_t:,.0f} т)",
        annual_need_t=None, storage_days=None, k_irregularity=1.0,
        required_capacity_t=pattern_t, area_norm_hint_m2=math.ceil(pattern_area),
        unit="т оснастки",
    ))

    # --- 6. Инструмент и приспособления ------------------------------------
    # Приоритет — реальная списочная численность из core.workforce
    # (связка «рабочая сила → склады»); резерв — укрупненная норма.
    try:
        from core.workforce import calc_workforce as _calc_wf  # без цикла
        workers = float(_calc_wf(project).total_total)
    except Exception:
        workers = _department_workers(project)
    tools_area = max(workers * TOOLS_AREA_M2_PER_WORKER, 40.0)
    reqs.append(WarehouseRequirement(
        key="tools", title=WAREHOUSE_TITLES["tools"],
        basis=f"≈{workers:,.0f} рабочих мест × {TOOLS_AREA_M2_PER_WORKER} м²",
        annual_need_t=None, storage_days=None, k_irregularity=1.0,
        required_capacity_t=None, area_norm_hint_m2=math.ceil(tools_area),
        unit="раб. место",
    ))

    return reqs


# ---------------------------------------------------------------------------
# Подбор единиц хранения
# ---------------------------------------------------------------------------

def load_storage_units(loader: Optional[DataLoader] = None) -> List[Dict[str, Any]]:
    """Загрузить справочник единиц хранения ``equipment/warehouse_equip.json``.

    Пользовательские склады из ``user_data/custom_warehouses.json``
    добавляются в конец списка (см. :func:`add_custom_unit`).
    """
    loader = loader or DataLoader(DATA_DIR)
    units = list(loader.load_dict("equipment/warehouse_equip.json").get("units", []))
    custom = load_custom_units()
    known_ids = {u.get("id") for u in units}
    units.extend(u for u in custom if u.get("id") not in known_ids)
    return units


#: Файл пользовательских складов (в ``user_data/`` рядом с приложением)
CUSTOM_WAREHOUSE_FILE = USER_DATA_DIR / "custom_warehouses.json"


def load_custom_units() -> List[Dict[str, Any]]:
    """Загрузить пользовательские единицы хранения (пустой список, если нет)."""
    path = CUSTOM_WAREHOUSE_FILE
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return list(data.get("units", []))


def add_custom_unit(unit: Dict[str, Any]) -> Dict[str, Any]:
    """Сохранить пользовательскую единицу хранения в JSON-справочник.

    Args:
        unit: карточка склада (ключи id/name/type/specs/applicable_for)

    Returns:
        Дополненная карточка (проставлены ``id`` и ``custom=True``)
    """
    record = dict(unit)
    if not record.get("id"):
        slug = re.sub(r"[^a-zа-я0-9]+", "-",
                      str(record.get("name", "склад")).lower()).strip("-")[:24]
        record["id"] = f"CUSTOM-{slug or 'warehouse'}"
    record["custom"] = True
    units = load_custom_units()
    units = [u for u in units if u.get("id") != record["id"]]
    units.append(record)
    path = CUSTOM_WAREHOUSE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": "1.0", "units": units}, f,
                  ensure_ascii=False, indent=2)
    return record


def to_picker_options(options: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Преобразовать варианты компоновки склада в формат ``EquipmentPicker``.

    Добавляет служебные поля ``_num_required`` (кол-во единиц) и
    ``_load_factor`` (отношение потребной площади к принятой — аналог
    коэффициента использования), а также сводный блок ``specs`` для
    отображения в карточке.

    Args:
        options: варианты из :func:`pick_storage_options`

    Returns:
        Список карточек для виджета выбора
    """
    cards: List[Dict[str, Any]] = []
    for opt in options:
        card = dict(opt)
        card["_num_required"] = int(opt.get("unit_count", 0))
        req_area = float(opt.get("required_area_m2") or 0.0)
        tot_area = float(opt.get("total_area_m2") or 0.0)
        # «загрузка»Inverse: насколько плотно принятая площадь закрывает норму
        card["_load_factor"] = round(req_area / tot_area, 3) \
            if tot_area > 0 and req_area > 0 else 0.0
        card["specs"] = {
            "capacity_t": opt.get("capacity_per_unit_t", 0.0),
            "productivity_t_h": 0.0,
            "footprint_m2": opt.get("footprint_per_unit_m2", 0.0),
            "total_area_m2": opt.get("total_area_m2", 0.0),
            "total_capacity_t": opt.get("total_capacity_t", 0.0),
        }
        if opt.get("custom"):
            card["custom"] = True
        cards.append(card)
    return cards


def _units_for(req: WarehouseRequirement, material_category: Optional[str],
               all_units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Отфильтровать единицы хранения под склад и категорию материала."""
    out: List[Dict[str, Any]] = []
    for u in all_units:
        app = u.get("applicable_for", {})
        if req.key not in app.get("storage_types", []):
            continue
        mats = app.get("materials") or []
        if material_category and mats and material_category not in mats:
            continue
        out.append(u)
    return out


def _score_option(option: Dict[str, Any]) -> float:
    """Эффективность варианта компоновки: минимум избыточной площади."""
    norm = option.get("required_area_m2") or 0.0
    area = option.get("total_area_m2") or 0.0
    if area <= 0:
        return -1e9
    if norm > 0:
        ratio = area / norm
        base = 1.0 - abs(ratio - 1.12)  # оптимум: ~12 % запас сверх нормы
    else:
        base = 1.0 / (1.0 + area / 1000.0)
    n_units = option.get("unit_count") or 1
    return base - 0.015 * (n_units - 1)


def _build_area_option(unit: Dict[str, Any], target_area_m2: float,
                       capacity_t: Optional[float]) -> Optional[Dict[str, Any]]:
    """Подобрать N единиц хранения так, чтобы закрыть площадь и вместимость.

    Вместимость одной единицы берётся из ``specs.capacity_per_unit_t``, а
    если она не задана — вычисляется по геометрической формуле склада
    ``Q = F * h * ρ * k`` (площадь × высота × насыпная плотность × коэф.
    использования). Для закрытых бункеров/силосов высота выше нормативной.

    Если даже ``MAX_STORAGE_UNITS`` единиц не закрывают требуемый объём
    запаса, считается «виртуальная» крупнотоннажная площадка: её площадь
    определяется той же геометрической формулой ``F = Q / (h·ρ·k)`` —
    так норматив всегда выполняется, а карточка честно показывает дефицит
    стандартных единиц.
    """
    specs = unit.get("specs", {})
    footprint = float(specs.get("footprint_m2") or 0.0)
    if footprint <= 0:
        return None
    cap_unit = float(specs.get("capacity_per_unit_t") or 0.0)
    if cap_unit <= 0:
        height = (BIN_STORAGE_HEIGHT_M
                  if unit.get("type") in ("bin", "silo") else STORAGE_HEIGHT_M)
        cap_unit = round(footprint * height * BULK_DENSITY_T_M3 * AREA_USAGE_K, 1)
    count = max(1, math.ceil(target_area_m2 / footprint))
    if capacity_t is not None and cap_unit > 0:
        count = max(count, math.ceil(capacity_t / cap_unit))
    if count > MAX_STORAGE_UNITS:
        # стандартным парком норматив не закрывается — укрупнённая площадка:
        # площадь из геометрии F = Q / (h·ρ·k), вместимость — из запаса
        height = (BIN_STORAGE_HEIGHT_M
                  if unit.get("type") in ("bin", "silo") else STORAGE_HEIGHT_M)
        area_needed = target_area_m2
        if capacity_t:
            area_needed = max(area_needed,
                              capacity_t / (height * BULK_DENSITY_T_M3
                                            * AREA_USAGE_K))
        big_footprint = round(area_needed, 1)
        # вместимость площадки: геометрия F·h·ρ·k, но не больше реального запаса
        geo_cap = big_footprint * height * BULK_DENSITY_T_M3 * AREA_USAGE_K
        if capacity_t:
            big_cap = round(min(geo_cap, capacity_t), 1) \
                if geo_cap >= capacity_t - 0.5 else round(geo_cap, 1)
        else:
            big_cap = round(geo_cap, 1)
        return {
            "id": unit["id"],
            "name": f"{unit['name']} (укрупнённая площадка)",
            "type": unit.get("type", ""),
            "unit_count": 1,
            "capacity_per_unit_t": big_cap,
            "total_capacity_t": big_cap,
            "footprint_per_unit_m2": big_footprint,
            "total_area_m2": big_footprint,
            "required_area_m2": round(target_area_m2, 1),
            "required_capacity_t": round(capacity_t or 0.0, 1),
            "recommended": bool(unit.get("applicable_for", {}).get("recommended")),
            "notes": (f"Стандартных единиц ({MAX_STORAGE_UNITS} шт) не хватает "
                      f"для запаса {capacity_t or 0:,.0f} т / площади "
                      f"{target_area_m2:,.0f} м² — принята укрупнённая площадка"),
        }
    count = min(count, MAX_STORAGE_UNITS)
    return {
        "id": unit["id"],
        "name": unit["name"],
        "type": unit.get("type", ""),
        "unit_count": count,
        "capacity_per_unit_t": cap_unit,
        "total_capacity_t": round(count * cap_unit, 1),
        "footprint_per_unit_m2": footprint,
        "total_area_m2": round(count * footprint, 1),
        "required_area_m2": round(target_area_m2, 1),
        "required_capacity_t": round(capacity_t or 0.0, 1),
        "recommended": bool(unit.get("applicable_for", {}).get("recommended")),
        "notes": unit.get("notes", ""),
    }


def pick_storage_options(
    req: WarehouseRequirement,
    *,
    material_category: Optional[str] = None,
    units: Optional[List[Dict[str, Any]]] = None,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """Топ-N вариантов компоновки склада (сортировка: эффективность ↓)."""
    all_units = units if units is not None else load_storage_units()
    candidates = _units_for(req, material_category, all_units)
    options: List[Dict[str, Any]] = []
    for u in candidates:
        opt = _build_area_option(u, req.area_norm_hint_m2 or 0.0,
                                 req.required_capacity_t)
        if opt is None:
            continue
        opt["scoring"] = round(_score_option(opt), 4)
        options.append(opt)
    options.sort(key=lambda o: o["scoring"], reverse=True)
    return options[:top_n]


def calc_warehouses(
    project: Any,
    *,
    loader: Optional[DataLoader] = None,
    material_category: Optional[str] = None,
    k_irregularity: float = DEFAULT_K_IRREGULARITY,
    top_n: int = 5,
    selected_ids: Optional[Dict[str, str]] = None,
    workers_total: Optional[float] = None,
) -> List[WarehouseResult]:
    """Полный расчёт складского хозяйства: нормативы + подбор оборудования.

    Args:
        project: модель проекта.
        loader: загрузчик справочников (для тестов).
        material_category: категория сплава ("steel"/"cast_iron"/"aluminum");
            если не задана — берётся из ``project.selected_alloy_id``.
        k_irregularity: коэффициент неравномерности.
        top_n: число вариантов компоновки на склад.
        selected_ids: сохранённый выбор пользователя ``{ключ_склада: id}``;
            если оборудование больше не подходит — берётся лучший вариант.
        workers_total: списочная численность рабочих (из
            :mod:`core.workforce`) для склада инструмента; если не передана —
            считается сам.

    Returns:
        Список :class:`WarehouseResult` по всем шести складам.
    """
    loader = loader or DataLoader(DATA_DIR)
    if material_category is None:
        material_category = loader.get_alloy_category(
            getattr(project, "selected_alloy_id", "") or "")
    all_units = load_storage_units(loader)
    selected_ids = selected_ids or {}
    results: List[WarehouseResult] = []
    for req in calc_warehouse_requirements(project, loader=loader,
                                           k_irregularity=k_irregularity,
                                           workers_total=workers_total):
        options = pick_storage_options(req, material_category=material_category,
                                       units=all_units, top_n=top_n)
        chosen = next(
            (o for o in options if o["id"] == selected_ids.get(req.key)),
            options[0] if options else None)
        results.append(WarehouseResult(
            requirement=req,
            units=options,
            total_area_m2=float(chosen["total_area_m2"]) if chosen else 0.0,
            total_capacity_t=float(chosen["total_capacity_t"]) if chosen else 0.0,
            notes=(f"Выбрано: {chosen['name']} × {chosen['unit_count']}"
                   if chosen else "Нет подходящих единиц хранения"),
        ))
    return results


def total_warehouse_area(results: List[WarehouseResult]) -> float:
    """Суммарная площадь всех складов, м²."""
    return round(sum(r.total_area_m2 for r in results), 1)


__all__ = [
    "WAREHOUSES",
    "WAREHOUSE_TITLES",
    "WarehouseRequirement",
    "WarehouseResult",
    "calc_warehouse_requirements",
    "load_storage_units",
    "pick_storage_options",
    "calc_warehouses",
    "total_warehouse_area",
    "STORAGE_DAYS_CHARGE",
    "STORAGE_DAYS_MOLDING_SAND",
    "STORAGE_DAYS_CORE_MATERIALS",
    "DEFAULT_K_IRREGULARITY",
]
