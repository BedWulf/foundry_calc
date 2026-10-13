"""Пакет расчётов формовочного отделения «ЛитейныйЦех PRO».

Модули:
    ``mass_groups`` — распределение отливок по группам массы и годового
        объёма выпуска (эталон: «Sample Diploma.pdf», табл. 7, лист 24).
    ``afl_calc``    — расчёт количества автоматических формовочных линий
        (АФЛ) по формуле (5) дипломов и подбор линий из справочника
        ``data/equipment/molding_lines.json``.

Пакет также выполняет роль фасада: отсюда доступен ``calc_molding(project)`` —
единая точка расчёта отделения для GUI (см. документацию ниже).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.casting_item import CastingItem
from core.molding.afl_calc import (
    MoldingCalculator, calc_annual_molds, calc_lines_count,
    calc_required_productivity,
)
from core.molding.mass_groups import (
    MASS_GROUP_METHODS, MASS_GROUP_TITLES, MassGroup, build_mass_groups,
    mass_group_index,
)

__all__ = [
    "MASS_GROUP_TITLES", "MASS_GROUP_METHODS", "MassGroup",
    "build_mass_groups", "mass_group_index", "calc_annual_molds",
    "calc_required_productivity", "calc_lines_count", "MoldingCalculator",
    "MoldingCalculation", "calc_molding", "DEFAULT_UNIT_MASS_KG",
    "DEFAULT_CORES_PER_MOLD", "calc_avg_cores_per_mold",
]

#: Средняя масса одной отливки с ЛПС по цеху, кг (методичка, типовой
#: сталелитейный цех тракторостроения) — резерв, когда номенклатура не введена.
DEFAULT_UNIT_MASS_KG: float = 10.0

#: Среднее число стержней на одну форму, если номенклатура не задана
#: (методичка, ориентир для среднего ЛПС-содержащего цеха).
DEFAULT_CORES_PER_MOLD: float = 1.5


def calc_avg_cores_per_mold(castings: List[CastingItem]) -> float:
    """Средневзвешенное число стержней на форму по номенклатуре.

    Взвешивание — по годовому числу форм каждой позиции
    (``cores_count * molds_per_year / Σ molds_per_year``), как в дипломе.

    Args:
        castings: позиции номенклатуры

    Returns:
        Среднее число стержней на форму; ``DEFAULT_CORES_PER_MOLD``,
        если данные неполные
    """
    total_molds = 0
    total_cores = 0
    for c in castings:
        molds = int(getattr(c, "molds_per_year", 0) or 0)
        cores = int(getattr(c, "cores_count", 0) or 0)
        if molds <= 0 or cores <= 0:
            continue
        total_molds += molds
        total_cores += molds * cores
    if total_molds <= 0:
        return DEFAULT_CORES_PER_MOLD
    return round(total_cores / total_molds, 2)


@dataclass
class MoldingCalculation:
    """Итоговый расчёт формовочного отделения для проекта.

    Attributes:
        groups: непустые группы номенклатуры по массе
        annual_molds_total: суммарное годовое число форм, шт
        required_productivity_molds_h: потребная произв. формовки, ф/ч
        fund_hours: действительный фонд времени оборудования, ч
        material_category: категория выбранного сплава
        line_options: топ подходящих линий (карточки с расчётными полями)
        selected_line_id: id принятой линии (выбор пользователя или лучший)
        line_count: принятое количество линий
        load_factor: коэффициент загрузки принятых линий
    """

    groups: List[MassGroup] = field(default_factory=list)
    annual_molds_total: int = 0
    required_productivity_molds_h: float = 0.0
    fund_hours: float = 0.0
    material_category: str = ""
    line_options: List[Dict[str, Any]] = field(default_factory=list)
    selected_line_id: str = ""
    line_count: int = 0
    load_factor: float = 0.0

    @property
    def selected_line(self) -> Dict[str, Any]:
        """Карточка принятой линии (пустой словарь, если не выбрана)."""
        for opt in self.line_options:
            if opt.get("id") == self.selected_line_id:
                return opt
        return {}


def _annual_molds_from_castings(castings: List[CastingItem]) -> int:
    """Годовое число форм по номенклатуре (сумма по позициям).

    Args:
        castings: позиции номенклатуры

    Returns:
        Общее годовое количество форм, шт
    """
    total = 0
    for c in castings:
        molds = int(getattr(c, "molds_per_year", 0) or 0)
        if molds <= 0:
            molds = calc_annual_molds(
                float(getattr(c, "annual_metal_t", 0.0) or 0.0),
                float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0),
            )
        total += molds
    return total


def _material_category(calc: MoldingCalculator, alloy_id: str) -> str:
    """Категория материала сплава ('steel'/'cast_iron'/'aluminum').

    Args:
        calc: калькулятор (даёт доступ к загрузчику справочников)
        alloy_id: идентификатор сплава из проекта

    Returns:
        Категория; 'steel' как базовый вариант при неизвестном сплаве
    """
    try:
        alloys = calc.loader.load_list("materials/alloys.json", key="alloys")
    except Exception:
        alloys = []
    target = (alloy_id or "").strip().lower()
    for a in alloys:
        # Сравнение регистронезависимо: id в справочнике — 'cast_iron_SCh20',
        # а сохранённые пользователем значения могли быть приведены к нижнему
        if (a.get("id", "").strip().lower() == target
                or a.get("name", "").strip().lower() == target):
            return a.get("category", "steel")
    return "steel"


def _average_unit_mass_kg(project: Any) -> float:
    """Средняя заливочная масса отливки: из номенклатуры или константа."""
    castings = list(getattr(project, "castings", []) or [])
    masses = [float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0) for c in castings]
    masses = [m for m in masses if m > 0]
    if not masses:
        return DEFAULT_UNIT_MASS_KG
    return sum(masses) / len(masses)


def calc_molding(
    project: Any,
    calculator: Optional[MoldingCalculator] = None,
    top_n: int = 5,
    selected_line_id: Optional[str] = None,
) -> MoldingCalculation:
    """Рассчитать формовочное отделение проекта и подобрать линии.

    Эталонные формулы («Sample Diploma.pdf», лист 25):
        Nф.год = Г·1000/m_отл ;  Pр = Nф.год/Фд ;  П₁ = Pр/q_ном ;
        Кзо = П₁/Ппр.

    Args:
        project: модель ``Project`` (используются ``castings``,
            ``annual_output_t``, ``selected_alloy_id``, ``F_equipment_h``)
        calculator: калькулятор линий (по умолчанию создаётся новый)
        top_n: сколько вариантов линий вернуть
        selected_line_id: ранее сохранённый выбор пользователя; если линия
            больше не подходит — берётся лучший вариант по скорингу

    Returns:
        Заполненный ``MoldingCalculation``
    """
    calc = calculator or MoldingCalculator()
    fund = float(getattr(project, "F_equipment_h", 3890) or 3890)
    category = _material_category(calc, getattr(project, "selected_alloy_id", ""))

    castings: List[CastingItem] = list(getattr(project, "castings", []) or [])
    groups = build_mass_groups(castings)

    annual_molds = _annual_molds_from_castings(castings)
    if annual_molds <= 0:
        # Номенклатура не загружена — оценка по средней массе отливки цеха
        annual_molds = calc_annual_molds(
            float(getattr(project, "annual_output_t", 0.0) or 0.0),
            _average_unit_mass_kg(project))

    req_prod = calc_required_productivity(annual_molds, fund)
    max_mass = max((float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0)
                    for c in castings), default=0.0)

    options = calc.find_lines(
        material_category=category,
        annual_molds=annual_molds,
        working_hours=fund,
        max_casting_mass_kg=max_mass,
        top_n=top_n,
    )

    chosen_id = ""
    if selected_line_id and any(o.get("id") == selected_line_id for o in options):
        chosen_id = selected_line_id
    elif options:
        chosen_id = options[0].get("id", "")

    chosen = next((o for o in options if o.get("id") == chosen_id), {})
    return MoldingCalculation(
        groups=groups,
        annual_molds_total=annual_molds,
        required_productivity_molds_h=round(req_prod, 2),
        fund_hours=fund,
        material_category=category,
        line_options=options,
        selected_line_id=chosen_id,
        line_count=int(chosen.get("_num_required", 0)),
        load_factor=float(chosen.get("_load_factor", 0.0)),
    )
