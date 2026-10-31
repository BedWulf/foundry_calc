"""Verified ferrous norm records with field-level sources, never process defaults."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from config import DATA_DIR

FERROUS_CATEGORIES = frozenset(("steel", "cast_iron", "ductile_iron", "malleable_iron"))
PROPERTY_LABELS = {
    "carbon_mass_pct": "C",
    "manganese_mass_pct": "Mn",
    "silicon_mass_pct": "Si",
    "phosphorus_mass_pct": "P",
    "sulfur_mass_pct": "S",
    "tensile_strength_min_mpa": "Предел прочности σв",
    "proof_strength_min_mpa": "Условный предел текучести",
    "elongation_min_pct": "Относительное удлинение δ",
    "brinell_hardness_hb": "Твёрдость по Бринеллю",
}
PROPERTY_UNITS = {
    "carbon_mass_pct": "mass_%",
    "manganese_mass_pct": "mass_%",
    "silicon_mass_pct": "mass_%",
    "phosphorus_mass_pct": "mass_%",
    "sulfur_mass_pct": "mass_%",
    "tensile_strength_min_mpa": "MPa",
    "proof_strength_min_mpa": "MPa",
    "elongation_min_pct": "%",
    "brinell_hardness_hb": "HB",
}
PROCESS_PARAMETERS = frozenset((
    "density_kg_m3", "pouring_temp_C", "melting_temp_C",
    "shrinkage_pct", "burnout_pct",
))


def validate_ferrous_catalog(data: dict, grade_index: dict) -> list[str]:
    """Validate all records; source membership is not proof of a specific melt."""
    problems: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("sources"), dict) or not isinstance(data.get("records"), list):
        return ["Некорректная структура нормативной базы"]
    if data.get("usage_policy") != "reference_only_no_automatic_selection":
        problems.append("Нормативные данные нельзя автоматически использовать как технологические")
    known = {(g["category"], g["name"]): g["standard_id"] for g in grade_index.get("grades", [])}
    registry = {s["id"]: s for s in grade_index.get("sources", [])}

    seen = set()
    for record in data["records"]:
        if not isinstance(record, dict):
            problems.append("Некорректная запись материала")
            continue
        name = record.get("name")
        category = record.get("category")
        key = (category, name)
        if key in seen:
            problems.append(f"Повтор марки {name}")
        seen.add(key)
        standard = record.get("standard_id")
        if category not in FERROUS_CATEGORIES:
            problems.append(f"{name}: цветной сплав не должен входить в эту базу")
        if known.get(key) != standard:
            problems.append(f"{name}: не совпадает нормативный указатель")
        details = data["sources"].get(standard)
        if not isinstance(details, dict):
            problems.append(f"{name}: стандарт без подтверждённого источника")
            continue
        if not str(details.get("source_url", "")).startswith("https://protect.gost.ru/"):
            problems.append(f"{name}: отсутствует официальный реестр")
        if details.get("source_url") != registry.get(standard, {}).get("url"):
            problems.append(f"{name}: официальный документ не совпадает с каталогом ГОСТ")
        if details.get("designation") != registry.get(standard, {}).get("designation"):
            problems.append(f"{name}: обозначение ГОСТ не совпадает с реестром")
        if not str(details.get("text_url", "")).startswith("https://"):
            problems.append(f"{name}: нет ссылки на текст таблицы")
        if record.get("eligible_for_process_calculations") is not False:
            problems.append(f"{name}: запрещено автоматически считать технологические параметры")
        if not record.get("scope"):
            problems.append(f"{name}: нет условий нормирования")
        props = record.get("properties")
        if not isinstance(props, dict) or not props:
            problems.append(f"{name}: нет нормативных параметров")
            continue
        for field, val in props.items():
            if field not in PROPERTY_LABELS or field in PROCESS_PARAMETERS:
                problems.append(f"{name}: неизвестное нормативное поле {field}")
                continue
            if not isinstance(val, dict) or val.get("unit") != PROPERTY_UNITS[field]:
                problems.append(f"{name}.{field}: неверная единица")
                continue
            source = val.get("source")
            if (not isinstance(source, dict) or
                    source.get("standard_id") != standard or not source.get("location")):
                problems.append(f"{name}.{field}: не указан источник параметра")
            elif "строка " in source["location"] and name not in source["location"]:
                problems.append(f"{name}.{field}: источник относится к другой марке")
            kind = val.get("kind")
            if kind == "normative_range":
                if field in ("phosphorus_mass_pct", "sulfur_mass_pct"):
                    problems.append(f"{name}.{field}: нормируемый максимум нельзя трактовать как диапазон")
                low, high = val.get("min"), val.get("max")
                if not (type(low) in (int, float) and type(high) in (int, float)
                        and math.isfinite(low) and math.isfinite(high)
                        and 0 <= low <= high):
                    problems.append(f"{name}.{field}: неверный диапазон")
            elif kind == "normative_maximum":
                if field not in ("phosphorus_mass_pct", "sulfur_mass_pct"):
                    problems.append(f"{name}.{field}: максимум допустим только для нормируемых примесей")
                number = val.get("value")
                if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
                    problems.append(f"{name}.{field}: неверная предельная величина")
            elif kind == "normative_minimum":
                number = val.get("value")
                if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
                    problems.append(f"{name}.{field}: неверная минимальная величина")
            else:
                problems.append(f"{name}.{field}: неизвестный тип нормативного значения")
    return problems


def load_ferrous_catalog(data_dir: Path | None = None) -> dict[str, Any]:
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    folder = root / "verified_references"
    data = json.loads((folder / "ferrous_normative_properties.json").read_text(encoding="utf-8"))
    index = json.loads((folder / "alloy_standards.json").read_text(encoding="utf-8"))
    problems = validate_ferrous_catalog(data, index)
    if problems:
        raise ValueError("Ошибка нормативной базы: " + "; ".join(problems[:5]))
    return data


def property_description(field: str, value: dict) -> str:
    label = PROPERTY_LABELS[field]
    unit = "%" if value["unit"] == "mass_%" else value["unit"]
    if value["kind"] == "normative_range":
        return f"{label}: {value['min']:g}–{value['max']:g} {unit}"
    if value["kind"] == "normative_maximum":
        return f"{label}: не более {value['value']:g} {unit}"
    return f"{label}: не менее {value['value']:g} {unit}"


def get_ferrous_grade_properties(category: str, name: str,
                                 data_dir: Path | None = None) -> dict | None:
    if category not in FERROUS_CATEGORIES:
        return None
    data = load_ferrous_catalog(data_dir)
    return next((r for r in data["records"]
                 if r["category"] == category and r["name"] == name), None)


def list_ferrous_reference_rows(data_dir: Path | None = None) -> list[dict[str, str]]:
    data = load_ferrous_catalog(data_dir)
    rows = []
    for record in data["records"]:
        source = data["sources"][record["standard_id"]]
        descriptions = [property_description(field, val)
                        for field, val in record["properties"].items()]
        rows.append({
            "name": record["name"],
            "specs": "; ".join(descriptions),
            "conditions": record["scope"],
            "source": source["designation"] + ", " + "; ".join(dict.fromkeys(
                value["source"]["location"] for value in record["properties"].values()
            )),
            "url": source["source_url"],
            "text_url": source["text_url"],
            "status": "Нормируемое свойство образца / химический состав, НЕ значение для расчёта плавки",
        })
    return rows
