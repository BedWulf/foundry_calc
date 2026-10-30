"""Раздел 2: Фонды времени и режимы работы отделений цеха.

Расчёт по формулам из методички (Коршунов В.В., 2014, стр. 11):
  - Календарный фонд:  F_кал = 365 × 24 = 8760 ч
  - Номинальный фонд:  F_ном = (365 − выходные − праздники) × 24
  - Действительный фонд оборудования: F_д.об (табл. 3 методички)
  - Действительный фонд рабочих:      F_д.р  (табл. 4 методички)

Табличные значения для стандартных режимов (2-сменный — как в дипломе):
  1 смена: F_д.об = 1830 ч, F_д.р = 1880 ч
  2 смены: F_д.об = 3890 ч, F_д.р = 3975 ч
  3 смены: F_д.об = 7008 ч, F_д.р = 7008 ч
"""
from dataclasses import dataclass
from typing import Dict

# ─── Табличные значения из методички (табл. 3 и 4) ───────────────────
# Формат: {количество_смен: (F_д.об, F_д.р)}
TABLE_VALUES: Dict[int, tuple] = {
    1: (1830, 1880),
    2: (3890, 3975),
    3: (7008, 7008),
}

# Стандартные параметры календаря
DEFAULT_WEEKENDS = 104   # выходных дней в году
DEFAULT_HOLIDAYS = 12    # праздничных дней в году
HOURS_PER_DAY = 24
DAYS_PER_YEAR = 365


@dataclass(frozen=True)
class TimeFunds:
    """Результат расчёта фондов времени."""
    F_calendar: float      # F_кал — календарный фонд, ч
    F_nominal: float       # F_ном — номинальный фонд, ч
    F_equipment: float     # F_д.об — действительный фонд оборудования, ч
    F_workers: float       # F_д.р — действительный фонд рабочих, ч
    weekends: int          # количество выходных дней
    holidays: int          # количество праздничных дней
    shifts: int            # количество смен

    def as_dict(self) -> Dict[str, float]:
        return {
            "F_кал": self.F_calendar,
            "F_ном": self.F_nominal,
            "F_д.об": self.F_equipment,
            "F_д.р": self.F_workers,
        }


def calculate_time_funds(
    shifts: int = 2,
    weekends: int = DEFAULT_WEEKENDS,
    holidays: int = DEFAULT_HOLIDAYS,
) -> TimeFunds:
    """Рассчитать все четыре фонда времени.

    Args:
        shifts: количество смен в сутки (1, 2 или 3)
        weekends: количество выходных дней в году
        holidays: количество праздничных дней в году

    Returns:
        TimeFunds — датакласс с результатами расчёта
    """
    # 1. Календарный фонд — константа
    F_cal = DAYS_PER_YEAR * HOURS_PER_DAY  # 8760

    # 2. Номинальный фонд
    working_days = DAYS_PER_YEAR - weekends - holidays
    F_nom = working_days * HOURS_PER_DAY   # 5976 для 104+12

    # 3. Действительные фонды — из таблицы или интерполяция
    if shifts in TABLE_VALUES:
        F_eq, F_wr = TABLE_VALUES[shifts]
    else:
        # Для нестандартного числа смен — линейная интерполяция
        # между ближайшими табличными значениями
        F_eq, F_wr = _interpolate_funds(shifts)

    return TimeFunds(
        F_calendar=F_cal,
        F_nominal=F_nom,
        F_equipment=F_eq,
        F_workers=F_wr,
        weekends=weekends,
        holidays=holidays,
        shifts=shifts,
    )


def _interpolate_funds(shifts: float) -> tuple:
    """Линейная интерполяция для нестандартного числа смен."""
    keys = sorted(TABLE_VALUES.keys())
    if shifts <= keys[0]:
        return TABLE_VALUES[keys[0]]
    if shifts >= keys[-1]:
        return TABLE_VALUES[keys[-1]]

    # Найти интервал
    for i in range(len(keys) - 1):
        if keys[i] <= shifts <= keys[i + 1]:
            t = (shifts - keys[i]) / (keys[i + 1] - keys[i])
            eq = TABLE_VALUES[keys[i]][0] + t * (TABLE_VALUES[keys[i + 1]][0] - TABLE_VALUES[keys[i]][0])
            wr = TABLE_VALUES[keys[i]][1] + t * (TABLE_VALUES[keys[i + 1]][1] - TABLE_VALUES[keys[i]][1])
            return round(eq), round(wr)

    return TABLE_VALUES[keys[-1]]


def get_reference_table() -> Dict[int, Dict[str, int]]:
    """Вернуть справочную таблицу фондов для всех режимов."""
    result = {}
    for shifts, (eq, wr) in TABLE_VALUES.items():
        tf = calculate_time_funds(shifts)
        result[shifts] = {
            "F_кал": int(tf.F_calendar),
            "F_ном": int(tf.F_nominal),
            "F_д.об": eq,
            "F_д.р": wr,
        }
    return result

def calculate_operating_time_funds(
    *,
    working_days_per_year: int,
    shifts_per_day: int,
    shift_duration_h: float,
    equipment_downtime_h: float = 0.0,
    worker_absence_h: float = 0.0,
) -> TimeFunds:
    """Calendar-based annual funds with explicit, physically distinct units.

    F_nominal is a MACHINE'S scheduled operating hours in the year:
        days/year * shifts/day * hours/shift.
    F_equipment removes the specified annual planned/unplanned downtime
    from this one-machine schedule.
    F_workers is ONE PERSON'S annual hours: days/year * hours/shift
    minus that person's annual absence. Do not multiply by the number of
    shifts to inflate an individual's annual fund.

    The default zero reductions yield UPPER BOUNDS, not verified effective
    hours. The caller must display that assumption, never claim that zero
    downtime / absence is an observed industrial fact.

    The standardised 365-day planning year is intentional. A leap-year
    or continuous-shift schedule requires its own calendar implementation.
    """
    import math

    if type(working_days_per_year) is not int or not 1 <= working_days_per_year <= DAYS_PER_YEAR:
        raise ValueError("Число рабочих дней должно быть целым от 1 до 365")
    if type(shifts_per_day) is not int or not 1 <= shifts_per_day <= 4:
        raise ValueError("Число смен должно быть целым от 1 до 4")
    for name, value in (
        ("Продолжительность смены", shift_duration_h),
        ("Простои оборудования", equipment_downtime_h),
        ("Отсутствия одного работника", worker_absence_h),
    ):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{name}: требуется конечное число")
    if shift_duration_h <= 0 or shifts_per_day * shift_duration_h > HOURS_PER_DAY:
        raise ValueError("Суммарная длительность смен в сутки должна быть от 0 до 24 часов")
    if equipment_downtime_h < 0 or worker_absence_h < 0:
        raise ValueError("Простои/отсутствия не могут быть отрицательными")

    scheduled_equipment = working_days_per_year * shifts_per_day * shift_duration_h
    scheduled_one_worker = working_days_per_year * shift_duration_h
    if equipment_downtime_h > scheduled_equipment:
        raise ValueError("Простои оборудования превышают календарный фонд машины")
    if worker_absence_h > scheduled_one_worker:
        raise ValueError("Отсутствия работника превышают индивидуальный фонд")

    return TimeFunds(
        F_calendar=DAYS_PER_YEAR * HOURS_PER_DAY,
        F_nominal=scheduled_equipment,
        F_equipment=scheduled_equipment - equipment_downtime_h,
        F_workers=scheduled_one_worker - worker_absence_h,
        weekends=DAYS_PER_YEAR - working_days_per_year,
        holidays=0,
        shifts=shifts_per_day,
    )
