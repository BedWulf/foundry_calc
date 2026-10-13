"""Расчёт внутрицехового транспорта литейного цеха (раздел 12 дипломов).

Источники истины — методичка; дипломы-примеры («Sample Diploma.pdf»,
«Sample Diploma 2.pdf») дают подтверждение формул и эталонные числа.

Разделы расчёта:

1. **Мостовые краны** — по нормам длины участка, обслуживаемого одним
   краном (диплом 1, табл. 16; диплом 2, табл. 18):

   ============ ==========================
   Отделение    Длина на 1 кран, м
   ============ ==========================
   Плавильное   20…30
   Склад        40…60
   ============ ==========================

   Число кранов отделения = ceil(L_отделения / L_нормы), минимум 1.
   Итог обоих дипломов: 2 + 1 = 3 крана.

2. **Транспортные ковши** — формула (5)/(6) дипломов:

       К = П · Тц / (Т · n),
       Тц = t_зал + l/0.75 + l/1.00 + t_ожид + t_ост + t_рем + t_сушки [мин],

   где П — годовое количество жидкого металла, т; n — ёмкость ковша, т;
   Т — годовой фонд работы ковша, ч. Парк дополняется запасом: в
   постоянном ремонте ~20 % ковшей, резерв ~10 % от работающих
   (оба диплома).

   Эталонные проверки:
     • Диплом 1: П=55 699.4 т, Тц=137 мин (2.28 ч), Т=3645 ч, n=2.5 →
       К = 14.00 рабочих; итого с запасом/ремонтом 19 шт ✓ (лист 30).
     • Диплом 2: П=90 720 т, Тц=120 мин (2.0 ч), Т=3645 ч, n=2.5 →
       К = 19.9 ≈ 20 рабочих; итого 26 шт ✓ (лист 30).

3. **Конвейеры и пневмотранспорт** — трассы по отделениям (дипломы,
   табл. 15/17): роликовый (формовочно-заливочное), пластинчатый
   (термообрубное), вертикальный (формовка–термообрубка), ленточный
   (смесеприготовление/подача шихты), пневмотранспорт сыпучих
   (склад ↔ АСМ, дистанция до 100 м, 1…1.5 кВт·ч на 1 т).

Данные справочника — только JSON: ``data/equipment/transport.json``
через ``DataLoader(config.DATA_DIR)``. Выбор пользователя сохраняется
в ``user_data/choices.json`` (:class:`core.user_choices.UserChoices`,
категория ``TRANSPORT_CATEGORY``).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from config import DATA_DIR
from data.loader import DataLoader

#: Относительный путь справочника транспорта от ``config.DATA_DIR``.
TRANSPORT_FILE = "equipment/transport.json"
#: Ключ списка оборудования внутри JSON (для ``DataLoader.load_list``).
TRANSPORT_KEY = "equipment"

#: Годовой фонд работы транспортного ковша, ч (оба диплома: 3645 ч).
LADLE_FUND_H: float = 3645.0
#: Коэффициент использования годового фонда парком ковшей (КВИ):
#: Тковшей = Тг × КВИ = 4380 × 0.832 ≈ 3645 ч — одинаково в обоих
#: дипломах; если ``project`` не задаёт фонд явно, считаем от него.
LADLE_FUND_KVI: float = 0.832
#: Доля ковшей, постоянно находящихся в ремонте (дипломы: 20 %).
LADLE_REPAIR_PCT: float = 0.20
#: Доля резервных ковшей от числа работающих (дипломы: 10 %).
LADLE_SPARE_PCT: float = 0.10

#: Нормы длины участка, обслуживаемого одним мостовым краном, м
#: (диплом 1 табл. 16, диплом 2 табл. 18 — значения идентичны).
#: Диапазон «20…30» трактуется консервативно: верхняя граница диапазона
#: даёт минимальный парк, нижняя — максимальный; для подбора принимаем
#: середину диапазона как типовую норму проектирования.
CRANE_NORMS_M: Dict[str, tuple] = {
    "melting": (20.0, 30.0),      # плавильное отделение
    "warehouse": (40.0, 60.0),    # склад шихтовых и формовочных материалов
    "molding": (30.0, 40.0),      # формовочно-заливочное (укрупнённая норма)
    "cleaning": (30.0, 40.0),     # термообрубное (укрупнённая норма)
}

#: Типовая скорость движения гружёного/порожнего ковша, м/мин
#: (формула (6) дипломов: l/0.75 + l/1.00).
LADLE_SPEED_LOADED_M_MIN: float = 0.75
LADLE_SPEED_EMPTY_M_MIN: float = 1.00

#: Параметры цикла ковша по умолчанию, мин (диплом 2, лист 29:
#: t_зал=2, l=20 м, t_ожид=15, t_ост=45, t_рем=8, t_сушки=3 → Тц=120).
DEFAULT_LADLE_CYCLE: Dict[str, float] = {
    "t_pour_min": 2.0,
    "distance_m": 20.0,
    "t_wait_min": 15.0,
    "t_cool_min": 45.0,
    "t_repair_min": 8.0,
    "t_dry_min": 3.0,
}


# ---------------------------------------------------------------------------
# Структуры результатов
# ---------------------------------------------------------------------------

@dataclass
class LadleResult:
    """Результат расчёта парка транспортных ковшей."""

    ladle_id: str = ""             # id карточки ковша из справочника
    ladle_name: str = ""           # название модели
    capacity_t: float = 0.0        # ёмкость ковша n, т
    liquid_metal_t: float = 0.0    # годовое количество жидкого металла П, т
    cycle_time_h: float = 0.0      # цикл работы ковша Тц, ч
    fund_h: float = LADLE_FUND_H   # годовой фонд работы ковша Т, ч
    working: int = 0               # необходимое число рабочих ковшей К
    in_repair: int = 0             # ковши в текущем ремонте (≈20 %)
    reserve: int = 0               # резервные ковши (≈10 % от работающих)
    total: int = 0                 # итого парк ковшей
    formula: str = ""              # текстовая расшифровка расчёта

    def as_dict(self) -> Dict[str, Any]:
        """Сериализовать результат в словарь для UI/экспорта."""
        return asdict(self)


@dataclass
class TransportRow:
    """Строка ведомости транспорта: единица/трасса оборудования."""

    kind: str                  # crane | conveyor | pneumatic | ladle | auxiliary
    name: str                  # наименование позиции
    model: str                 # модель/тип
    units: int                 # принятое количество (шт или условных блоков)
    area_m2: float             # занимаемая площадь (для ведомости площадей)
    basis: str                 # обоснование (норма/формула)
    department: str = ""       # отделение обслуживания

    def as_dict(self) -> Dict[str, Any]:
        """Сериализовать строку в словарь."""
        return asdict(self)


@dataclass
class TransportResult:
    """Итоговый расчёт внутрицехового транспорта цеха."""

    rows: List[TransportRow] = field(default_factory=list)
    cranes_total: int = 0                    # всего мостовых кранов
    ladles: Optional[LadleResult] = None     # расчёт ковшей
    crane_areas_m2: float = 0.0              # суммарная площадь групп кранов
    other_areas_m2: float = 0.0              # площадь конвейеров/пневмо/погрузчиков
    total_area_m2: float = 0.0               # итоговая транспортная площадь
    notes: List[str] = field(default_factory=list)

    @property
    def departments(self) -> List[str]:
        """Уникальные отделения в порядке появления."""
        seen: List[str] = []
        for r in self.rows:
            if r.department and r.department not in seen:
                seen.append(r.department)
        return seen

    def by_kind(self, kind: str) -> List[TransportRow]:
        """Строки ведомости по виду транспорта."""
        return [r for r in self.rows if r.kind == kind]

    def as_dict(self) -> Dict[str, Any]:
        """Словарь результата для UI и экспорта."""
        return {
            "rows": [r.as_dict() for r in self.rows],
            "cranes_total": self.cranes_total,
            "ladles": self.ladles.as_dict() if self.ladles else None,
            "crane_areas_m2": round(self.crane_areas_m2, 1),
            "other_areas_m2": round(self.other_areas_m2, 1),
            "total_area_m2": round(self.total_area_m2, 1),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Справочник
# ---------------------------------------------------------------------------

def load_transport_catalog(loader: Optional[DataLoader] = None
                           ) -> List[Dict[str, Any]]:
    """Загрузить справочник транспорта из JSON (через ``config.DATA_DIR``).

    Args:
        loader: загрузчик (для тестов); по умолчанию новый DataLoader

    Returns:
        Список карточек оборудования транспорта
    """
    if loader is None:
        loader = DataLoader(DATA_DIR)
    return loader.load_list(TRANSPORT_FILE, key=TRANSPORT_KEY)


def get_transport_item(item_id: str,
                       loader: Optional[DataLoader] = None
                       ) -> Optional[Dict[str, Any]]:
    """Найти карточку транспорта по id.

    Args:
        item_id: идентификатор из ``transport.json``
        loader: загрузчик справочников

    Returns:
        Карточка либо ``None``
    """
    for item in load_transport_catalog(loader):
        if str(item.get("id")) == str(item_id):
            return item
    return None


# ---------------------------------------------------------------------------
# Мостовые краны
# ---------------------------------------------------------------------------

def calc_cranes(
    bay_lengths_m: Dict[str, float],
    *,
    norms: Optional[Dict[str, tuple]] = None,
) -> List[TransportRow]:
    """Рассчитать число мостовых кранов по нормам длины участка.

    Норма — диапазон метров пролёта на один кран (табл. 16/18 дипломов).
    Берётся верхняя граница диапазона (наиболее длинное обслуживание),
    но не менее одного крана на отделение — как принято в эталонах
    (плавильное 20…30 м при длине пролёта ~48 м → 2 крана).

    Args:
        bay_lengths_m: длины участков по отделениям,
            ``{"melting": 48.0, "warehouse": 48.0, ...}``
        norms: переопределение норм (для тестов)

    Returns:
        Строки ведомости с ``kind == \"crane\"``
    """
    norms = norms or CRANE_NORMS_M
    rows: List[TransportRow] = []
    for dept, length in bay_lengths_m.items():
        lo_hi = norms.get(dept)
        if not lo_hi or length <= 0:
            continue
        lo, hi = lo_hi
        per_crane = hi                      # консервативная верхняя граница
        n = max(1, math.ceil(length / per_crane))
        rows.append(TransportRow(
            kind="crane",
            name=f"Кран мостовой ({_dept_title(dept)})",
            model="двухбалочный, 10 т",
            units=n,
            area_m2=0.0,   # площадь группы крана учитывается отдельно
            basis=(f"L={length:.0f} м / норма {lo:g}…{hi:g} м на кран "
                   f"→ {n} шт"),
            department=_dept_title(dept),
        ))
    return rows


_DEPT_TITLES = {
    "melting": "Плавильное отделение",
    "warehouse": "Склад шихтовых и формовочных материалов",
    "molding": "Формовочно-заливочное отделение",
    "cleaning": "Отделение обрубки и очистки",
}


def _dept_title(key: str) -> str:
    """Человекочитаемое название отделения по ключу."""
    return _DEPT_TITLES.get(key, key.capitalize())


# ---------------------------------------------------------------------------
# Транспортные ковши
# ---------------------------------------------------------------------------

def ladle_cycle_time_h(cycle_params: Optional[Dict[str, float]] = None
                       ) -> float:
    """Цикл работы ковша Тц, ч — формула (6) дипломов.

    Тц = t_зал + l/0.75 + l/1.00 + t_ожид + t_ост + t_рем + t_сушки (мин).

    Args:
        cycle_params: параметры цикла (ключи DEFAULT_LADLE_CYCLE)

    Returns:
        Тц в часах
    """
    p = dict(DEFAULT_LADLE_CYCLE)
    if cycle_params:
        p.update({k: float(v) for k, v in cycle_params.items()
                  if k in p and v is not None})
    minutes = (p["t_pour_min"]
               + p["distance_m"] / LADLE_SPEED_LOADED_M_MIN
               + p["distance_m"] / LADLE_SPEED_EMPTY_M_MIN
               + p["t_wait_min"] + p["t_cool_min"]
               + p["t_repair_min"] + p["t_dry_min"])
    return minutes / 60.0


def calc_ladles(
    liquid_metal_t: float,
    *,
    capacity_t: float = 2.5,
    fund_h: float = LADLE_FUND_H,
    cycle_time_h: Optional[float] = None,
    ladle_id: Optional[str] = None,
    loader: Optional[DataLoader] = None,
) -> LadleResult:
    """Рассчитать парк транспортных ковшей — формула (5) дипломов.

        К = П · Тц / (Т · n),

    затем округление вверх, ремонтный фонд ≈20 % и резерв ≈10 % от
    работающих ковшей (округление до целых по правилам дипломов).

    Эталонные проверки:
        • Диплом 1: 55 699.4·2.28/(3645·2.5) = 13.99 → 14; +3+2 = 19 ✓
        • Диплом 2: 90 720·2.00/(3645·2.5)  = 19.89 → 20; +4+2 = 26 ✓

    Args:
        liquid_metal_t: годовое количество жидкого металла П, т
        capacity_t: ёмкость ковша n, т (используется, если ``ladle_id``
            не задан)
        fund_h: годовой фонд работы ковша Т, ч
        cycle_time_h: готовый Тц, ч; если ``None`` — считается по
            параметрам цикла ковша из справочника или умолчаниям
        ladle_id: id карточки ковша из ``transport.json`` (перебивает
            ``capacity_t`` и параметры цикла из specs карточки)
        loader: загрузчик справочников

    Returns:
        Заполненный :class:`LadleResult`
    """
    name = f"Ковш транспортный, {capacity_t:g} т"
    params: Dict[str, float] = {}
    if ladle_id:
        card = get_transport_item(ladle_id, loader)
        if card:
            capacity_t = float(card.get("capacity_t") or capacity_t)
            name = str(card.get("name") or name)
            specs = card.get("specs") or {}
            if specs.get("cycle_time_min"):
                cycle_time_h = float(specs["cycle_time_min"]) / 60.0

    if cycle_time_h is None:
        cycle_time_h = ladle_cycle_time_h(params or None)

    working_exact = (liquid_metal_t * cycle_time_h / (fund_h * capacity_t)
                     if fund_h > 0 and capacity_t > 0 else 0.0)
    working = max(0, math.ceil(working_exact - 1e-9)) if working_exact > 0 else 0
    # Ремфонд и резерв округляются ВВЕРХ (правило приёмки парка):
    # диплом 1: 14·0.2=2.8→3 ремонта, 14·0.1=1.4→2 резерва, итого 19 ✓;
    # диплом 2: 20·0.2=4, 20·0.1=2, итого 26 ✓.
    in_repair = math.ceil(working * LADLE_REPAIR_PCT - 1e-9)
    reserve = math.ceil(working * LADLE_SPARE_PCT - 1e-9)
    total = working + in_repair + reserve

    formula = (f"К = {liquid_metal_t:,.1f} × {cycle_time_h:.2f} / "
               f"({fund_h:.0f} × {capacity_t:g}) = {working_exact:.2f} → "
               f"{working} рабочих; ремонт {in_repair}, резерв {reserve}, "
               f"итого {total}").replace(",", " ")

    return LadleResult(
        ladle_id=ladle_id or "", ladle_name=name, capacity_t=capacity_t,
        liquid_metal_t=round(liquid_metal_t, 1),
        cycle_time_h=round(cycle_time_h, 3), fund_h=fund_h,
        working=working, in_repair=in_repair, reserve=reserve, total=total,
        formula=formula,
    )


# ---------------------------------------------------------------------------
# Конвейеры и пневмотранспорт
# ---------------------------------------------------------------------------

def estimate_bay_length_m(project: Any) -> Dict[str, float]:
    """Оценить длины участков отделений для норм кранов.

    Приоритет источников:
      1. Явное переопределение ``project.bay_lengths_m``;
      2. Фактические длины участков из ведомости площадей
         (:func:`core.areas.collect_departments`, типовая ширина
         пролёта 12 м → L = F_принят / 12);
      3. Укрупнённая норма 48 м на отделение (как в обоих дипломах).

    Args:
        project: модель проекта

    Returns:
        ``{ключ_отделения: длина_м}``
    """
    override = getattr(project, "bay_lengths_m", None)
    if isinstance(override, dict) and override:
        return {str(k): float(v) for k, v in override.items()}

    #: Типовая ширина пролёта литейного цеха, м (нормы проектирования)
    bay_width_m = 12.0
    lengths: Dict[str, float] = {}
    try:
        from core.areas import calc_areas
        areas = calc_areas(project)
        # Суммируем площади участков одного отделения по ключу секции
        dept_area: Dict[str, float] = {}
        for row in areas.rows:
            key = str(row.key)
            if key == "melting_tab":
                dept = "melting"
            elif key == "molding_tab":
                dept = "molding"
            elif key == "cleaning_tab":
                dept = "cleaning"
            else:
                continue
            dept_area[dept] = dept_area.get(dept, 0.0) + row.area_m2
        if areas.warehouse_area_m2 > 0:
            # склады обычно в один складской блок — делим на 2 пролёта
            dept_area["warehouse"] = areas.warehouse_area_m2 / 2.0
        for dept, area in dept_area.items():
            lengths[dept] = max(24.0, min(96.0, area / bay_width_m))
    except Exception:
        lengths = {}

    default = 48.0   # типовая длина участка в обоих дипломных проектах
    for dept in CRANE_NORMS_M:
        lengths.setdefault(dept, default)
    return lengths


def _conveyor_rows(molds_per_year: float, sand_tonnage_t: float,
                   bulk_t: float) -> List[TransportRow]:
    """Оценить трассы конвейеров и пневмотранспорта по потокам.

    Args:
        molds_per_year: годовое число форм (длина рольганга)
        sand_tonnage_t: годовой расход формовочной смеси, т (ленточный)
        bulk_t: тоннаж сыпучих для пневмотранспорта, т

    Returns:
        Строки ведомости ``kind == conveyor/pneumatic``
    """
    rows: List[TransportRow] = []
    # Роликовый конвейер: длина трассы ~ шаг опки 1.5 м на 120 часов
    # непрерывной работы линии (2 смены × 249 дней ≈ 3980 ч → ~2650 форм/ч)
    if molds_per_year > 0:
        hours = max(LADLE_FUND_H, 1.0)
        molds_h = molds_per_year / hours
        length = max(30.0, min(300.0, molds_h * 0.6))
        rows.append(TransportRow(
            kind="conveyor", name="Конвейер роликовый (опоки)",
            model="ИЛ-225/рольганг", units=int(round(length / 10.0)) or 1,
            area_m2=12.0 * max(1, int(round(length / 10.0))),
            basis=f"~{molds_h:.0f} форм/ч → трасса ≈{length:.0f} м",
            department="Формовочно-заливочное отделение"))
    # Пластинчатый конвейер выбитого литья: 1 трасса на отделение очистки
    rows.append(TransportRow(
        kind="conveyor", name="Конвейер пластинчатый (охлаждение литья)",
        model="1126Б", units=1, area_m2=14.0 * 6,
        basis="Норма: 1 трасса охлаждения ≈60 м (методичка, раздел 7)",
        department="Отделение обрубки и очистки"))
    # Вертикальный конвейер: 1 на каждую линию формовки выше 1 позиции —
    # в типовом проекте одна подопочная эскалаторная установка
    rows.append(TransportRow(
        kind="conveyor", name="Конвейер вертикальный (подопочный)",
        model="ИЛ-225/элеватор", units=1, area_m2=12.0,
        basis="1 установка на формовочный комплекс",
        department="Формовочно-заливочное отделение"))
    # Ленточный конвейер подачи песков/шихты АСМ
    if sand_tonnage_t > 0:
        length = max(20.0, min(120.0, sand_tonnage_t / 3000.0 * 25.0))
        blocks = max(1, int(round(length / 10.0)))
        rows.append(TransportRow(
            kind="conveyor", name="Конвейер ленточный (пески, шихта)",
            model="КЛЛ-2У", units=blocks, area_m2=10.0 * blocks,
            basis=f"Смесь {sand_tonnage_t:,.0f} т/год → трасса ≈{length:.0f} м"
                  .replace(",", " "),
            department="Смесеприготовительное отделение"))
    # Пневмотранспорт: пропускная способность 8 т/ч, фонд 3975 ч
    if bulk_t > 0:
        need_units = max(1, math.ceil(bulk_t / (8.0 * 3975.0)))
        rows.append(TransportRow(
            kind="pneumatic", name="Пневмотранспортная установка",
            model="ПСУ-8", units=need_units, area_m2=25.0 * need_units,
            basis=(f"Сыпучие {bulk_t:,.0f} т/год / (8 т/ч × 3975 ч)"
                   .replace(",", " ") + f" → {need_units} шт"),
            department="Склад ↔ АСМ"))
    return rows


# ---------------------------------------------------------------------------
# Сборка полного расчёта
# ---------------------------------------------------------------------------

def calc_transport(
    project: Any,
    *,
    loader: Optional[DataLoader] = None,
    selected_ids: Optional[Dict[str, str]] = None,
) -> TransportResult:
    """Полный расчёт внутрицехового транспорта проекта.

    Собирает: мостовые краны (нормы табл. 16/18), транспортные ковши
    (формулы (5)/(6)), конвейерные трассы и пневмотранспорт. Модель
    ковша можно переопределить выбором пользователя (id из
    ``transport.json``).

    Args:
        project: модель проекта
        loader: загрузчик справочников
        selected_ids: сохранённый выбор ``{позиция: id}`` из
            ``UserChoices.TRANSPORT_CATEGORY``; поддерживаются ключи
            ``ladle`` (ковш) и ``crane`` (мостовой кран)

    Returns:
        Заполненный :class:`TransportResult`
    """
    if loader is None:
        loader = DataLoader(DATA_DIR)
    selected_ids = selected_ids or {}

    result = TransportResult()

    # ── Жидкий металл для ковшей ──────────────────────────────────
    liquid_t = float(getattr(project, "liquid_metal_t", 0.0) or 0.0)
    charge_t = float(getattr(project, "metal_charge_t", 0.0) or 0.0)
    if liquid_t <= 0:
        from core.melting import calc_metal_charge
        if charge_t <= 0:
            charge_t = calc_metal_charge(
                annual_output_t=float(
                    getattr(project, "annual_output_t", 0.0) or 0.0),
                brak_pct=float(getattr(project, "brak_pct", 5.0) or 0.0),
                litniki_pribyli_pct=float(
                    getattr(project, "litniki_pribyli_pct", 28.9) or 0.0),
                ugar_pct=float(getattr(project, "ugar_pct", 5.0) or 0.0))
        # Жидкий металл: из годовой металлозавалки вычитается угар.
        # По балансу дипломов П ≈ М × (1 − У/100):
        # диплом 1: 58 932 × 0.945 ≈ 55 699 т ✓; диплом 2: 95 494 × 0.95
        # = 90 719 ≈ 90 720 т ✓.
        ugar = float(getattr(project, "ugar_pct", 5.0) or 0.0)
        liquid_t = charge_t * (1.0 - ugar / 100.0)

    # ── Ковши ─────────────────────────────────────────────────────
    ladle_id = selected_ids.get("ladle") or "LADLE-2.5T"
    # Диплом 1 использует цикл 137 мин (К=14), диплом 2 — 120 мин (К=20).
    # Формула цикла по умолчанию даёт 120 мин; если проект наследует
    # параметры диплома 1 (t_ожид и пр.), пользователь может выбрать
    # карточку LADLE-2.5T с cycle_time_min=137 явным выбором.
    ladle = calc_ladles(liquid_t, ladle_id=ladle_id, loader=loader)
    result.ladles = ladle
    result.rows.append(TransportRow(
        kind="ladle", name=ladle.ladle_name,
        model=str(ladle.ladle_id or "—"), units=ladle.total,
        area_m2=0.0, basis=ladle.formula,
        department="Плавильно-заливочное хозяйство"))

    # ── Мостовые краны ────────────────────────────────────────────
    bays = estimate_bay_length_m(project)
    crane_rows = calc_cranes(bays)
    crane_model = selected_ids.get("crane")
    crane_card = get_transport_item(crane_model, loader) if crane_model \
        else next((i for i in load_transport_catalog(loader)
                   if i.get("recommended") and i.get("category") == "crane"),
                  {})
    group_area = float((crane_card or {}).get("specs", {})
                       .get("group_area_m2") or 100.0)
    for row in crane_rows:
        row.model = str((crane_card or {}).get("name") or row.model)
        row.area_m2 = row.units * group_area
    result.rows.extend(crane_rows)
    result.cranes_total = sum(r.units for r in crane_rows)
    result.crane_areas_m2 = sum(r.area_m2 for r in crane_rows)

    # ── Конвейеры / пневмотранспорт ───────────────────────────────
    molds_per_year = 0.0
    try:
        from core.molding import calc_molding
        molding = calc_molding(project)
        molds_per_year = float(molding.annual_molds_total or 0.0)
    except Exception:      # неполные данные — просто без рольганга
        molding = None
    sand_tonnage = 0.0
    bulk_t = 0.0
    try:
        from core.sand_prep import calc_sand_prep
        sand = calc_sand_prep(project)
        summary = sand.get("summary") or {}
        sand_tonnage = float(summary.get("total_mix_t") or
                             summary.get("sand_t") or 0.0)
        bulk_t = sand_tonnage
    except Exception:
        sand = None
    conv_rows = _conveyor_rows(molds_per_year, sand_tonnage, bulk_t)
    result.rows.extend(conv_rows)
    result.other_areas_m2 = sum(r.area_m2 for r in conv_rows)

    # ── Вспомогательный транспорт ─────────────────────────────────
    catalog = load_transport_catalog(loader)
    forklift = next((c for c in catalog
                     if c.get("id") == "FORKLIFT-3T"), {})
    if forklift:
        n_fork = 1 if liquid_t < 70000 else 2
        result.rows.append(TransportRow(
            kind="auxiliary", name=str(forklift.get("name", "Погрузчик")),
            model=str(forklift.get("model", "—")), units=n_fork,
            area_m2=n_fork * float(forklift.get("specs", {})
                                   .get("group_area_m2") or 16.0),
            basis="1 погрузчик на склад до 70 тыс. т/год, далее +1",
            department="Склады"))
        result.other_areas_m2 += result.rows[-1].area_m2

    result.total_area_m2 = result.crane_areas_m2 + result.other_areas_m2

    result.notes.append(
        "Нормы кранов: плавильное 20…30 м/кран, склад 40…60 м/кран "
        "(табл. 16 диплома 1, табл. 18 диплома 2).")
    result.notes.append(
        "Эталон: диплом 1 — 14 рабочих ковшей (итого 19), "
        "диплом 2 — 20 рабочих (итого 26).")
    return result


__all__ = [
    "TRANSPORT_FILE", "TRANSPORT_KEY",
    "LADLE_FUND_H", "LADLE_REPAIR_PCT", "LADLE_SPARE_PCT",
    "CRANE_NORMS_M", "DEFAULT_LADLE_CYCLE",
    "LadleResult", "TransportRow", "TransportResult",
    "load_transport_catalog", "get_transport_item",
    "calc_cranes", "ladle_cycle_time_h", "calc_ladles",
    "estimate_bay_length_m", "calc_transport",
]
