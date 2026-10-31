"""Independent, non-mutating audits of furnace, core-machine and mixer catalogs."""
from __future__ import annotations

import json
import math
from pathlib import Path


def _num(value, *, allow_zero=False):
    return type(value) in (int, float) and math.isfinite(value) and (
        value >= 0 if allow_zero else value > 0
    )


def audit_equipment_catalog(data: object, kind: str) -> list[dict[str, str]]:
    """Return issues for the selected catalog without modifying source data.

    This checks consistency, not manufacturer-passport authenticity.
    """
    collections = {
        "furnaces": "furnaces", "core_machines": "machines", "mixers": "mixers"
    }
    if kind not in collections:
        raise ValueError(f"Неизвестный тип каталога: {kind}")
    key = collections[kind]
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        return [{"code": "INVALID_CATALOG", "equipment_id": "", "field": key,
                 "message": "Нет списка оборудования"}]
    result = []
    seen = set()

    def add(code, eid, field, message):
        result.append({"code": code, "equipment_id": eid,
                       "field": field, "message": message})

    for index, machine in enumerate(data[key]):
        if not isinstance(machine, dict):
            add("INVALID_ITEM", str(index), "", "Карточка не является объектом")
            continue
        eid = machine.get("id")
        if not isinstance(eid, str) or not eid.strip():
            eid = f"index:{index}"
            add("MISSING_ID", eid, "id", "Отсутствует ID")
        if eid in seen:
            add("DUPLICATE_ID", eid, "id", "Повтор ID")
        seen.add(eid)
        specs = machine.get("specs")
        if not isinstance(specs, dict):
            add("MISSING_SPECS", eid, "specs", "Нет характеристик")
            continue

        if kind == "furnaces":
            for field in ("capacity_t", "productivity_t_h", "melt_time_h"):
                if not _num(specs.get(field)):
                    add("INVALID_SPEC", eid, field, "Требуется положительное конечное число")
            if not _num(specs.get("power_kw"), allow_zero=True):
                add("INVALID_SPEC", eid, "power_kw", "Мощность должна быть неотрицательной")
            capacity = specs.get("capacity_t")
            rate = specs.get("productivity_t_h")
            cycle = specs.get("melt_time_h")
            if all(_num(v) for v in (capacity, rate, cycle)):
                theoretical_rate = capacity / cycle
                if rate > theoretical_rate * 1.01:
                    add("RATE_EXCEEDS_SIMPLE_CYCLE", eid, "productivity_t_h",
                        "Заданная производительность выше ёмкость/время плавки; "
                        "проверьте смысл циклов, подпитку и параллельность")
            add("SOURCE_UNVERIFIED", eid, "specs",
                "Паспорта и условия измерения характеристик не приложены к карточке")

        elif kind == "core_machines":
            for field in ("cycle_time_s", "cavities_per_box", "hourly_output_cores_h"):
                if not _num(specs.get(field)):
                    add("INVALID_SPEC", eid, field, "Требуется положительное конечное число")
            cycle, cavities, rate = (specs.get(k) for k in
                ("cycle_time_s", "cavities_per_box", "hourly_output_cores_h"))
            if all(_num(v) for v in (cycle, cavities, rate)):
                derived = 3600 * cavities / cycle
                if not math.isclose(derived, rate, rel_tol=1e-6, abs_tol=1e-6):
                    add("CORE_RATE_MISMATCH", eid, "hourly_output_cores_h",
                        f"По циклу и гнёздам {derived:g} стержней/ч, в каталоге {rate:g}; "
                        "возможно, учтён отдельный коэффициент")
            add("SOURCE_UNVERIFIED", eid, "specs",
                "Паспортные параметры цикла не подтверждены индивидуальным источником")

        else:
            unit = machine.get("unit")
            if unit not in ("m3_h", "t_h"):
                add("INVALID_UNIT", eid, "unit", "Неизвестная единица производительности")
                continue
            suffix = "m3_h" if unit == "m3_h" else "t_h"
            maximum = f"productivity_{suffix}"
            minimum = f"productivity_min_{suffix}"
            if not _num(specs.get(maximum)):
                add("INVALID_SPEC", eid, maximum, "Нет положительной производительности")
            if minimum in specs and (
                not _num(specs[minimum]) or
                (_num(specs.get(maximum)) and specs[minimum] > specs[maximum])
            ):
                add("INVALID_RANGE", eid, minimum, "Минимум выше максимума или <= 0")
            if not _num(specs.get("installed_power_kw"), allow_zero=True):
                add("INVALID_SPEC", eid, "installed_power_kw",
                    "Мощность должна быть конечной и неотрицательной")
            if "inlet_temp_c" in specs and "outlet_temp_c" in specs and (
                not _num(specs["inlet_temp_c"], allow_zero=True) or
                not _num(specs["outlet_temp_c"], allow_zero=True) or
                specs["outlet_temp_c"] >= specs["inlet_temp_c"]
            ):
                add("TEMPERATURE_INCONSISTENT", eid, "outlet_temp_c",
                    "Проверьте температуры охлаждения")
            add("SOURCE_UNVERIFIED", eid, "specs",
                "Нет поэлементной подтверждённой ссылки на паспорт")
    return result


def audit_equipment_file(path: str | Path, kind: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as stream:
        return audit_equipment_catalog(json.load(stream), kind)
