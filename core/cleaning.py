"""Расчёт отделения обрубки, очистки и термообработки (ОООиТО).

Формулы взяты из обоих эталонных дипломов (раздел 7 «Отделение обрубки,
очистки и термообработки», формулы (13)–(15)):

    n  = Q · k_н / (q · Тд)      — потребное число установок;
    Рд = n / Кзо                 — принятое число (Кзо = 0.70…0.85);
    кз = n / Рд                  — фактический коэффициент загрузки,

где Q — количество литья на программу в тоннах, k_н — коэффициент
неравномерности (1.2…1.4), q — паспортная производительность установки,
Тд — действительный годовой фонд времени оборудования.

Два ключевых момента из эталонов, которые часто упускают:

1. Разные операции обрабатывают РАЗНЫЙ тоннаж:
     • охлаждение/выбивка/дробемётная очистка/термообработка работают с
       металлом после выбивки, т.е. с ЛПС:  Г+ЛП+Б  (диплом 2: 90 720 т);
     • зачистка (обдирочно-шлифовальные станки) снимает уже обрубанное
       литьё без ЛПС:                       Г+Б      (диплом 2: 68 320 т).
   В дипломе 2 для станков ЗМ636 подставлено 849 295 — это опечатка
   (правильно 683 200 т), поэтому программа считает по формуле, а не по цифре.

2. Единицы производительности бывают «т/ч» и «шт/ч». Станок ЗМ636 в
   паспортах указан как 60–100 шт/ч; чтобы формула осталась единой,
   штуки пересчитываются в тонны через среднюю массу очищаемой отливки:
   q_т/ч = q_шт/ч · m_ср / 1000.

Справочник оборудования: ``data/equipment/thermal_equip.json``
(только JSON, без SQLite). Пользовательское оборудование добавляется
через UI и хранится в ``user_data/custom_cleaning_machines.json``.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import DATA_DIR
from data.loader import DataLoader

#: Справочник очистного/термического оборудования — всегда через DATA_DIR.
CLEANING_EQUIP_FILE: str = "equipment/thermal_equip.json"

#: Идеальная зона загрузки парка (методичка, 0.70–0.85).
LOAD_OPTIMAL_MIN: float = 0.70
LOAD_OPTIMAL_MAX: float = 0.85

#: Среднее число стержней на форму, если номенклатура не задана.
DEFAULT_CORES_PER_MOLD: float = 1.5

#: Средняя масса одной отливки с ЛПС при пустой номенклатуре, кг.
DEFAULT_UNIT_MASS_KG: float = 10.0

#: Средняя масса одного стержня, кг (ориентир методички для среднего ЛПС).
AVG_CORE_MASS_KG: float = 3.0

#: Годовой фонд работы очистного оборудования по умолчанию, ч
#: (действительный фонд оборудования из дипломов — 3770 ч при 2 сменах).
DEFAULT_FUND_HOURS: float = 3770.0

#: Коэффициент использования парка дробемётных камер (непрерывная загрузка
#: барабана/камеры невозможна: загрузка-разгрузка, замена абразива).
#: В дипломе 2 принято 0.85: n_расч = Q·kН/(q·Тд) → N = ceil(n/0.85),
#: что эквивалентно увеличению расчёта в 1/0.85 ≈ 1.176 раза.
DRUM_UTILIZATION: float = 0.85

#: Максимально допустимое число единиц в парке очистного оборудования.
#: Позиции, где расчёт даёт больший парк (обрубка и зачистка штучными
#: станками при крупном литье), считаются «поточным участком с бригадой»
#: и не предлагаются как отдельное оборудование — см. ``find_for_operation``.
#: 60, а не 40: в дипломе 1 под программу ~59 тыс. т получается около 48
#: обдирочных станков ЗМ636 — такой парк для штучной позиции реалистичен,
#: поэтому верхнюю границу подняли, чтобы вкладка не оставалась пустой на
#: средних тоннажах.
MAX_PARK_UNITS: int = 60

#: Минимальная масса отливки программы (кг), при которой имеет смысл
#: предлагать дробемётные камеры непрерывного/периодического типа
#: (``type == shot_blasting_chamber``). Камера SHOT-BAY-15 ориентирована на
#: относительно крупное штучное литьё; показывать её под 7-килограммовую
#: отливку, где корректно работает барабан 42322, — значит уводить выбор.
CHAMBER_MIN_MASS_KG: float = 100.0

#: Позиции технологического процесса отделения (порядок — как в дипломе).
OPERATIONS: Tuple[str, ...] = (
    "cooling",          # охлаждение на пластинчатом конвейере
    "shakeout",         # выбивка (обычно в составе АФЛ)
    "shot_blasting",    # очистка и удаление стержней дробемётом
    "gating_cutting",   # обрубка литниковых систем
    "grinding",         # зачистка обдирочно-шлифовальными станками
    "heat_treatment",   # термообработка (нормализация/отжиг)
)

#: Человекочитаемые названия позиций.
OPERATION_TITLES: Dict[str, str] = {
    "cooling": "Охлаждение",
    "shakeout": "Выбивка",
    "shot_blasting": "Очистка и удаление стержней",
    "gating_cutting": "Обрубка ЛПС",
    "grinding": "Зачистка",
    "heat_treatment": "Термообработка",
}

#: По какому тоннажу считается каждая позиция: ``casting_count`` — литьё
#: до обрубки (с ЛПС, Г+ЛП+Б), ``clean_casting`` — после обрубки (без ЛПС, Г+Б).
OPERATION_BASIS: Dict[str, str] = {
    "cooling": "casting_count",
    "shakeout": "casting_count",
    "shot_blasting": "casting_count",
    "gating_cutting": "casting_count",
    "grinding": "clean_casting",
    "heat_treatment": "casting_count",
}


# ----------------------------------------------------------------------
# Баланс металла: сколько тонн проходит по каждой позиции отделения
# ----------------------------------------------------------------------
def calc_department_masses(
    annual_output_t: float,
    litniki_pribyli_pct: float,
    brak_pct: float,
    ugar_pct: float = 5.0,
) -> Dict[str, float]:
    """Рассчитать тоннаж, проходящий через отделение обрубки и очистки.

    Args:
        annual_output_t: годовой выпуск годных отливок (без брака), т
        litniki_pribyli_pct: доля литниковых систем и прибылей, % от годного
        brak_pct: процент брака, % от годного
        ugar_pct: процент угара, % (нужен для оценки металлозавалки)

    Returns:
        Словарь:
            ``liquid_metal_t``   — жидкий металл на заливку, Г+ЛП+Б;
            ``casting_count_t``  — литьё после выбивки (с ЛПС), = liquid;
            ``clean_casting_t``  — литьё после обрубки (без ЛПС), Г+Б;
            ``gating_t``         — металл ЛПС на возврат, ЛП;
            ``scrap_return_t``   — весь технологический возврат (ЛП+Б);
            ``metal_charge_t``   — годовая металлозавалка М.

    Raises:
        ValueError: если угар вне диапазона [0, 100)
    """
    if annual_output_t <= 0:
        return {
            "liquid_metal_t": 0.0, "casting_count_t": 0.0,
            "clean_casting_t": 0.0, "gating_t": 0.0,
            "scrap_return_t": 0.0, "metal_charge_t": 0.0,
        }
    ug = ugar_pct / 100.0
    if not (0.0 <= ug < 1.0):
        raise ValueError(f"Некорректный процент угара: {ugar_pct}%")

    gating = annual_output_t * litniki_pribyli_pct / 100.0
    scrap = annual_output_t * brak_pct / 100.0
    liquid = annual_output_t + gating + scrap
    metal_charge = liquid / (1.0 - ug)
    return {
        "liquid_metal_t": round(liquid, 1),
        "casting_count_t": round(liquid, 1),
        "clean_casting_t": round(annual_output_t + scrap, 1),
        "gating_t": round(gating, 1),
        "scrap_return_t": round(gating + scrap, 1),
        "metal_charge_t": round(metal_charge, 1),
    }


def calc_annual_pieces(
    annual_output_t: float,
    unit_mass_with_lps_kg: float,
    brak_pct: float,
) -> int:
    """Годовое число отливок (в штуках) с учётом брака.

    Используется для позиций со штуко-часовой производительностью
    (обдирочные станки). Эталон: диплом 1, лист 44 — N = 39 666 т · 1000 /
    7.5 кг ≈ 5 271 000 шт.

    Args:
        annual_output_t: годовой выпуск литья вместе с ЛПС, т
        unit_mass_with_lps_kg: средняя масса отливки с ЛПС, кг
        brak_pct: процент брака (дополнительный выпуск), %

    Returns:
        Годовое число отливок, шт (0 при некорректных данных)
    """
    if annual_output_t <= 0 or unit_mass_with_lps_kg <= 0:
        return 0
    need_t = annual_output_t * (1.0 + brak_pct / 100.0)
    return int(math.ceil(need_t * 1000.0 / unit_mass_with_lps_kg))


# ----------------------------------------------------------------------
# Расчёт числа установок по формулам (13)–(15)
# ----------------------------------------------------------------------
def calc_units_required(
    tonnage_t: float,
    productivity_t_h: float,
    fund_hours: float,
    k_uneven: float = 1.3,
    utilization: float = 1.0,
) -> float:
    """Потребное (расчётное) число установок, шт.

    Формула (13)/(14)/(15) дипломов: ``n = Q · k_н / (q · Тд)``.

    Args:
        tonnage_t: обрабатываемый тоннаж за год, т
        productivity_t_h: часовая производительность одной установки, т/ч
        fund_hours: действительный годовой фонд времени, ч
        k_uneven: коэффициент неравномерности (1.2–1.4)
        utilization: доля фонда, в которой установка реально загружена
            (для дробемётных камер 0.85 — как в дипломе 2: там сначала
            считают n, затем принимают N = ceil(n / 0.85))

    Returns:
        Расчётное число установок (не округлённое); 0 при некорректных данных
    """
    if productivity_t_h <= 0 or fund_hours <= 0 or utilization <= 0:
        return 0.0
    return tonnage_t * k_uneven / (productivity_t_h * fund_hours * utilization)


def pick_unit_count(n_required: float,
                    max_load_factor: float = LOAD_OPTIMAL_MAX) -> int:
    """Принять число установок по методике дипломов.

    Диплом: ``Рд = n / (0.7 ÷ 0.85)``, т.е. парк берут не ``ceil(n)``,
    а ближайшее целое, при котором загрузка не превышает верх оптимального
    диапазона. Примеры диплома 2: 3.9 → 5 (кз 0.78); 2.6 → 3 (кз 0.85).

    Args:
        n_required: расчётное число установок
        max_load_factor: верх допустимой загрузки (по умолчанию 0.85)

    Returns:
        Принятое число установок (не меньше 1 при положительном запросе)
    """
    if n_required <= 0:
        return 0
    return max(math.ceil(n_required), math.ceil(n_required / max_load_factor))


def load_factor(n_required: float, units: int) -> float:
    """Коэффициент загрузки парка: ``кз = n / Nпр``."""
    if units <= 0:
        return 0.0
    return round(n_required / units, 3)


class CleaningCalculator:
    """Подбор оборудования отделения обрубки, очистки и термообработки."""

    def __init__(self, loader: Optional[DataLoader] = None):
        """Инициализировать калькулятор.

        Args:
            loader: загрузчик справочников; по умолчанию работает с config.DATA_DIR
        """
        if loader is None:
            loader = DataLoader(DATA_DIR)
        self.loader = loader

    # ---------- справочник + пользовательское оборудование ----------
    @staticmethod
    def custom_path() -> Path:
        """Путь к файлу пользовательского очистного оборудования."""
        return DATA_DIR.parent / "user_data" / "custom_cleaning_machines.json"

    def load_custom_machines(self) -> List[Dict[str, Any]]:
        """Загрузить пользовательское оборудование (файл может отсутствовать).

        Returns:
            Список карточек оборудования
        """
        path = self.custom_path()
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
        items = data.get("machines", []) if isinstance(data, dict) else data
        return [i for i in items if isinstance(i, dict)]

    def add_custom_machine(self, machine: Dict[str, Any]) -> Dict[str, Any]:
        """Добавить своё оборудование и сохранить в JSON (требование №5).

        Args:
            machine: карточка (минимум name/operation/specs.productivity_t_h
                или specs.productivity_pieces_h); id проставляется автоматически

        Returns:
            Сохранённая карточка с полями ``id`` и ``custom=True``
        """
        record: Dict[str, Any] = {**machine, "custom": True}
        if not record.get("id"):
            raw = f"{record.get('name', 'cleaning')}|{datetime.now().isoformat()}"
            record["id"] = "custom_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
        records = [r for r in self.load_custom_machines()
                   if r.get("id") != record["id"]]
        records.append(record)
        path = self.custom_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "machines": records},
                      f, indent=2, ensure_ascii=False)
        return record

    def _all_machines(self) -> List[Dict[str, Any]]:
        """Объединённый список: справочник + пользовательское оборудование."""
        catalog = list(self.loader.load_list(CLEANING_EQUIP_FILE, key="machines"))
        catalog.extend(self.load_custom_machines())
        return catalog

    # ---------- вспомогательные вычисления ----------
    @staticmethod
    def hourly_tonnage(machine: Dict[str, Any], avg_mass_kg: float) -> float:
        """Перевести паспортную производительность установки в т/ч.

        Поддерживаются способы задания: прямая производительность
        ``specs.productivity_t_h``, штуки ``specs.productivity_pieces_h``
        (пересчёт через среднюю массу отливки) и формы ``specs.molds_h``.

        Args:
            machine: карточка оборудования
            avg_mass_kg: средняя масса одной очищаемой отливки с ЛПС, кг

        Returns:
            Производительность, т/ч (0, если данных недостаточно)
        """
        specs = machine.get("specs", {})
        direct = float(specs.get("productivity_t_h", 0) or 0)
        if direct > 0:
            return direct
        pieces = float(specs.get("productivity_pieces_h", 0) or 0)
        if pieces > 0 and avg_mass_kg > 0:
            return pieces * avg_mass_kg / 1000.0
        molds = float(specs.get("molds_h", 0) or 0)
        if molds > 0 and avg_mass_kg > 0:
            return molds * avg_mass_kg / 1000.0
        return 0.0

    @staticmethod
    def _score(load_factor_value: float, units: int) -> float:
        """Балл релевантности парка (0..1), как в плавильном отделении.

        Максимум — внутри диапазона 0.70–0.85 с поощрением загрузки ближе
        к верхней границе; штраф — за перегрузку и за раздробленность парка.

        Args:
            load_factor_value: коэффициент загрузки
            units: принятое число установок

        Returns:
            Балл релевантности
        """
        lo, hi = LOAD_OPTIMAL_MIN, LOAD_OPTIMAL_MAX
        if lo <= load_factor_value <= hi:
            base = 1.0
            bonus = 0.15 * (load_factor_value - lo) / (hi - lo)
        elif load_factor_value > hi:
            dist = load_factor_value - hi
            base = 1.0 / (1.0 + 5 * dist ** 2)
            bonus = -0.3 * min((load_factor_value - hi) / hi, 0.5)
        else:
            dist = lo - load_factor_value
            base = 1.0 / (1.0 + 5 * dist ** 2)
            bonus = 0.0
        penalty = 1.0 / (1.0 + 0.02 * max(units - 1, 0))
        return round((base + bonus) * penalty, 3)

    def _is_suitable(self, machine: Dict[str, Any], operation: str,
                     material_category: str, casting_mass_kg: float) -> bool:
        """Проверить применимость установки к позиции, материалу и массе.

        Args:
            machine: карточка оборудования
            operation: позиция техпроцесса (ключ из ``OPERATIONS``)
            material_category: категория сплава проекта
            casting_mass_kg: наибольшая масса отливки с ЛПС в программе, кг

        Returns:
            True, если установку можно показать пользователю
        """
        app = machine.get("applicable_for", {})
        operations = app.get("operations", [])
        if operations and operation not in operations:
            return False
        materials = app.get("materials", [])
        if materials and material_category and material_category not in materials:
            return False
        mass_range = app.get("casting_mass_range_kg") or []
        if mass_range and casting_mass_kg > 0:
            low = float(mass_range[0]) if len(mass_range) > 0 else 0.0
            high = float(mass_range[1]) if len(mass_range) > 1 else float("inf")
            if not (low <= casting_mass_kg <= high):
                return False
        # Подвесные/периодические дробемётные камеры имеют смысл только для
        # программ с относительно крупным литьём: при мелком литье барабан
        # непрерывного действия эффективнее, и показывать камеру — значит
        # уводить выбор (см. CHAMBER_MIN_MASS_KG). Для пользовательского
        # оборудования правило не применяется: человек сам решает, что у
        # него установлено.
        mtype = str(machine.get("type", ""))
        if (mtype == "shot_blasting_chamber" and not machine.get("custom")
                and 0 < casting_mass_kg < CHAMBER_MIN_MASS_KG):
            return False
        return True

    # ---------- подбор по одной позиции ----------
    def find_for_operation(
        self,
        operation: str,
        tonnage_t: float,
        fund_hours: float,
        material_category: str = "",
        avg_mass_kg: float = DEFAULT_UNIT_MASS_KG,
        k_uneven: float = 1.3,
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Подобрать оборудование для одной позиции техпроцесса.

        Args:
            operation: ключ позиции из ``OPERATIONS``
            tonnage_t: обрабатываемый тоннаж позиции, т
            fund_hours: действительный годовой фонд времени оборудования, ч
            material_category: категория сплава (steel/cast_iron/aluminum)
            avg_mass_kg: средняя масса отливки с ЛПС, кг (для перевода шт→т);
                если номенклатура не задана (0), для штуных позиций масса
                оценивается по тоннажу — см. тело метода
            k_uneven: коэффициент неравномерности (1.2–1.4)
            top_n: сколько лучших вариантов вернуть

        Returns:
            Карточки оборудования, отсортированные от наиболее оптимальных,
            с расчётными полями ``_p1_required``, ``_num_required``,
            ``_load_factor``, ``_score``, ``_productivity_t_h``
        """
        # Штуковая производительность имеет смысл только при известной массе
        # отливки. Если пользователь не импортировал номенклатуру
        # (avg_mass_kg <= 0), массу оценивают по тоннажу: 300 т/год ≈ мелкое
        # литьё (5 кг), 90 000 т/год ≈ среднее (75 кг). Иначе станок на
        # 100 шт/ч превращался бы в 0.5 т/ч и давал парк в тысячи единиц.
        mass_for_filter = avg_mass_kg if avg_mass_kg > 0 else min(
            75.0, max(5.0, tonnage_t / 1200.0))

        options: List[Dict[str, Any]] = []
        for machine in self._all_machines():
            if not self._is_suitable(machine, operation, material_category,
                                     mass_for_filter):
                continue
            prod = self.hourly_tonnage(machine, mass_for_filter)
            if prod <= 0:
                continue
            util = (DRUM_UTILIZATION
                    if str(machine.get("type", "")).startswith("shot_blasting")
                    else 1.0)
            n_req = calc_units_required(tonnage_t, prod, fund_hours, k_uneven, util)
            if n_req <= 0:
                continue
            units = pick_unit_count(n_req)
            if units > MAX_PARK_UNITS:
                # Слишком раздробленный парк — позицию логичнее закрывать
                # поточным участком/бригадой, а не отдельными установками.
                continue
            factor = load_factor(n_req, units)
            # Дробемётные барабаны/камеры работают циклично: их реальная
            # выработка ниже паспортной — учитываем это в отображаемой
            # производительности карточки.
            shown_prod = prod * util if util < 1.0 else prod
            options.append({
                **machine,
                "_productivity_t_h": round(shown_prod, 3),
                "_p1_required": round(n_req, 2),
                "_num_required": units,
                "_load_factor": factor,
                "_score": self._score(factor, units),
            })

        # Наиболее эффективные варианты — первыми (дипломы — примеры,
        # а не эталон оптимальности): балл загрузки, затем бóльшая
        # производительность (меньше единиц в парке).
        options.sort(
            key=lambda x: (
                x["_score"],
                x["_productivity_t_h"],
                -x["_num_required"],
                bool(x.get("applicable_for", {}).get("recommended", False)),
            ),
            reverse=True,
        )
        return options[:top_n]

    # ---------- сводный расчёт отделения ----------
    def calc_department(
        self,
        annual_output_t: float,
        litniki_pribyli_pct: float,
        brak_pct: float,
        fund_hours: float = DEFAULT_FUND_HOURS,
        material_category: str = "",
        avg_mass_kg: float = DEFAULT_UNIT_MASS_KG,
        cores_per_mold: float = DEFAULT_CORES_PER_MOLD,
        annual_molds: int = 0,
        ugar_pct: float = 5.0,
        k_uneven: float = 1.3,
        top_n: int = 5,
        selected_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Рассчитать всё отделение обрубки, очистки и термообработки.

        Args:
            annual_output_t: годовой выпуск годных отливок, т
            litniki_pribyli_pct: доля ЛПС, % от годного
            brak_pct: процент брака, % от годного
            fund_hours: действительный фонд времени оборудования, ч
            material_category: категория сплава проекта
            avg_mass_kg: средняя масса отливки с ЛПС, кг
            cores_per_mold: среднее число стержней на форму (тоннаж стержней)
            annual_molds: годовое число форм (для выбивки); если 0 — оценка
                по тоннажу и средней массе
            ugar_pct: процент угара, %
            k_uneven: коэффициент неравномерности (1.2–1.4)
            top_n: сколько вариантов показывать по каждой позиции
            selected_ids: сохранённый выбор пользователя
                ``{operation: machine_id}``

        Returns:
            Словарь с тоннажами (``masses``), позициями (``operations``) и
            сводкой (``summary``). Каждая позиция содержит ``options``,
            ``selected_id``, ``machine_count``, ``load_factor``,
            ``tonnage_t``, ``cores_ton_t``.
        """
        selected_ids = dict(selected_ids or {})
        masses = calc_department_masses(
            annual_output_t, litniki_pribyli_pct, brak_pct, ugar_pct)

        casting_count_t = masses["casting_count_t"]
        clean_casting_t = masses["clean_casting_t"]
        # Стержневая смесь, выброшенная вместе с литьём (т/год):
        # формы × стержней в форме × средняя масса стержня.
        molds = annual_molds if annual_molds > 0 else calc_annual_pieces(
            casting_count_t, avg_mass_kg, 0.0)
        cores_ton = molds * max(cores_per_mold, 0.0) * AVG_CORE_MASS_KG / 1000.0

        basis_tonnage: Dict[str, float] = {
            "casting_count": casting_count_t,
            "clean_casting": clean_casting_t,
        }

        operations: Dict[str, Dict[str, Any]] = {}
        for op in OPERATIONS:
            tonnage = basis_tonnage[OPERATION_BASIS[op]]
            if op == "shakeout":
                # Выборка перерабатывает форму целиком: металл + ЛПС +
                # стержневая смесь (дипломы: «выбивка вместе со стержнями»).
                tonnage += cores_ton
            options = self.find_for_operation(
                operation=op,
                tonnage_t=tonnage,
                fund_hours=fund_hours,
                material_category=material_category,
                avg_mass_kg=avg_mass_kg,
                k_uneven=k_uneven,
                top_n=top_n,
            )
            chosen_id = ""
            saved = selected_ids.get(op, "")
            if saved and any(o.get("id") == saved for o in options):
                chosen_id = saved
            elif options:
                chosen_id = options[0].get("id", "")
            chosen = next((o for o in options if o.get("id") == chosen_id), {})
            operations[op] = {
                "key": op,
                "title": OPERATION_TITLES[op],
                "tonnage_t": round(tonnage, 1),
                "cores_ton_t": round(cores_ton, 1),
                "options": options,
                "selected_id": chosen_id,
                "machine_count": int(chosen.get("_num_required", 0)),
                "load_factor": float(chosen.get("_load_factor", 0.0)),
                "p1_required": float(chosen.get("_p1_required", 0.0)),
            }

        total_units = sum(o["machine_count"] for o in operations.values())
        factors = [o["load_factor"] for o in operations.values()
                   if o["machine_count"] > 0]
        summary = {
            "total_units": total_units,
            "avg_load_factor": round(sum(factors) / len(factors), 3) if factors else 0.0,
            "fund_hours": fund_hours,
            "k_uneven": k_uneven,
            "annual_molds": molds,
        }
        return {
            "masses": masses,
            "operations": operations,
            "summary": summary,
            "material_category": material_category,
            "avg_mass_kg": avg_mass_kg,
        }


def calc_cleaning(
    project: Any,
    calculator: Optional[CleaningCalculator] = None,
    selected_ids: Optional[Dict[str, str]] = None,
    top_n: int = 5,
) -> Dict[str, Any]:
    """Единая точка расчёта очистного отделения для GUI.

    Берёт данные из модели ``Project`` (баланс металла, номенклатура,
    фонд времени оборудования, категория сплава) и возвращает результат
    :meth:`CleaningCalculator.calc_department`.

    Args:
        project: модель ``Project``
        calculator: калькулятор (по умолчанию создаётся новый)
        selected_ids: сохранённый выбор пользователя по позициям
        top_n: сколько вариантов показывать по каждой позиции

    Returns:
        Результат ``calc_department`` (см. документацию метода)
    """
    from core.core_making import DEFAULT_CORES_PER_MOLD as _CPM  # локально, без цикла
    from core.molding import calc_avg_cores_per_mold

    calc = calculator or CleaningCalculator()
    castings: List[Any] = list(getattr(project, "castings", []) or [])
    masses_from_items = sum(float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0)
                            for c in castings)
    # Средняя масса считается по числу ФОРМ каждой позиции (взвешивание),
    # иначе редкая крупная отливка завышает средний вес и занижает число
    # штук в штуко-часовых позициях (обрубка/зачистка).
    mold_weights = sum(int(getattr(c, "molds_per_year", 0) or 0)
                       for c in castings)
    if castings and mold_weights > 0:
        avg_mass = sum(
            float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0)
            * int(getattr(c, "molds_per_year", 0) or 0)
            for c in castings) / mold_weights
    elif castings:
        avg_mass = masses_from_items / len(castings)
    else:
        avg_mass = DEFAULT_UNIT_MASS_KG
    max_mass = max((float(getattr(c, "mass_with_LPS_kg", 0.0) or 0.0)
                    for c in castings), default=0.0)
    # Для фильтра «по массе отливки» используем максимум программы.
    avg_mass_for_filter = max_mass if max_mass > 0 else avg_mass

    annual_molds = 0
    for c in castings:
        annual_molds += int(getattr(c, "molds_per_year", 0) or 0)

    category = _alloy_category(str(getattr(project, "selected_alloy_id", "")))
    cores_per_mold = calc_avg_cores_per_mold(castings) if castings else _CPM

    result = calc.calc_department(
        annual_output_t=float(getattr(project, "annual_output_t", 0.0) or 0.0),
        litniki_pribyli_pct=float(getattr(project, "litniki_pribyli_pct", 28.9) or 0.0),
        brak_pct=float(getattr(project, "brak_pct", 5.0) or 0.0),
        fund_hours=float(getattr(project, "F_equipment_cleaning_h", 0.0) or
                              getattr(project, "F_equipment_h", DEFAULT_FUND_HOURS) or
                              DEFAULT_FUND_HOURS),
        material_category=category,
        # avg_mass == 0 означает «номенклатуры нет» — пусть find_for_operation
        # сам оценит массу по тоннажу, а не подставляет жёстко 10 кг.
        avg_mass_kg=avg_mass,
        cores_per_mold=cores_per_mold,
        annual_molds=annual_molds,
        ugar_pct=float(getattr(project, "ugar_pct", 5.0) or 5.0),
        top_n=top_n,
        selected_ids=selected_ids,
    )
    result["max_casting_mass_kg"] = avg_mass_for_filter
    return result


def _alloy_category(alloy_id: str) -> str:
    """Определить категорию материала по ``selected_alloy_id``.

    Args:
        alloy_id: идентификатор сплава из ``data/materials/alloys.json``

    Returns:
        Категория (``steel``/``cast_iron``/``aluminum``) или пустая строка,
        если сплав не найден
    """
    if not alloy_id:
        return ""
    loader = DataLoader(DATA_DIR)
    for alloy in loader.load_list("materials/alloys.json", key="alloys"):
        if alloy.get("id") == alloy_id:
            return str(alloy.get("category", ""))
    return ""


# ----------------------------------------------------------------------
# Мосты для GUI (единый формат карточек с остальными отделениями)
# ----------------------------------------------------------------------
def to_picker_options(options: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Подготовить карточки позиции к показу в ``EquipmentPicker``.

    Виджет читает расчётные поля ``_num_required``/``_load_factor`` и строку
    характеристик из ``specs``; для очистного оборудования задаём свой набор
    полей через ``card_fields``, чтобы корректно отображались т/ч и шт/ч.

    Args:
        options: карточки из :meth:`CleaningCalculator.find_for_operation`

    Returns:
        Тот же список с добавленными полями ``description`` и ``card_fields``
    """
    prepared: List[Dict[str, Any]] = []
    for opt in options:
        specs = dict(opt.get("specs", {}) or {})
        fields: List[Tuple[str, str]] = []
        if specs.get("productivity_t_h"):
            fields.append(("productivity_t_h", "Производительность, т/ч"))
        if specs.get("productivity_pieces_h"):
            fields.append(("productivity_pieces_h", "Производительность, шт/ч"))
        if specs.get("working_temp_c"):
            fields.append(("working_temp_c", "T нагрева, °C"))
        if specs.get("power_kw"):
            fields.append(("power_kw", "Мощность, кВт"))
        if specs.get("length_m"):
            fields.append(("length_m", "Длина, м"))
        card = {
            **opt,
            "specs": specs,
            "card_fields": fields,
            "description": opt.get("notes", "") or opt.get("description", ""),
        }
        prepared.append(card)
    return prepared


def get_chosen_operations(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Вернуть только те позиции, для которых подобрано оборудование.

    Args:
        result: вывод :func:`calc_cleaning` / :meth:`CleaningCalculator.calc_department`

    Returns:
        Список выбранных позиций в порядке техпроцесса
    """
    ops = result.get("operations", {})
    return [ops[op] for op in OPERATIONS
            if op in ops and ops[op].get("selected_id")]
