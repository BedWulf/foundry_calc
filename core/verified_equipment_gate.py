"""Fail-closed eligibility for manufacturer-backed operational equipment records.

A document reference is necessary but not sufficient for actual plant suitability.
This module does NOT turn existing example/legacy catalog entries into verified data.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

# Explicit values, no guessed fallbacks or implied standard operating rates.
REQUIRED_SOURCE_FIELDS = ("document_url", "document_title", "document_revision",
                          "location", "model_designation")
REQUIRED_PARAMETER_FIELDS = ("value", "unit", "source", "conditions")
ACCEPTED_SOURCE_TYPES = frozenset({"manufacturer_passport", "manufacturer_datasheet",
                                    "published_standard"})


def validate_verified_parameter(record: object, *, expected_model: str,
                                expected_unit: str | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, Mapping):
        return ["Нет паспортной записи параметра"]
    for field in REQUIRED_PARAMETER_FIELDS:
        if field not in record or record[field] in (None, ""):
            errors.append(f"Нет поля {field}")
    value = record.get("value")
    if type(value) not in (int, float) or not math.isfinite(value):
        errors.append("Параметр должен быть конечным числом")
    if expected_unit is not None and record.get("unit") != expected_unit:
        errors.append(f"Ожидается единица {expected_unit}")
    source = record.get("source")
    if not isinstance(source, Mapping):
        return errors + ["Нет независимого первоисточника"]
    for field in REQUIRED_SOURCE_FIELDS:
        if not source.get(field):
            errors.append(f"Источник: нет поля {field}")
    if source.get("source_type") not in ACCEPTED_SOURCE_TYPES:
        errors.append("Тип источника не допускается для производственной базы")
    if source.get("model_designation") != expected_model:
        errors.append("Документ относится к другой модификации оборудования")
    url = source.get("document_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        errors.append("Отсутствует допустимая ссылка на источник")
    conditions = record.get("conditions")
    if not isinstance(conditions, Mapping) or not conditions:
        errors.append("Не указаны условия измерения")
    if record.get("verification_status") != "verified":
        errors.append("Параметр не подтверждён")
    return errors


def verify_equipment_for_selection(equipment: object,
                                   required_specs: Mapping[str, str]) -> list[str]:
    """No source or incomplete provenance => never use in verified auto-selection."""
    if not isinstance(equipment, Mapping):
        return ["Недопустимая карточка оборудования"]
    model = equipment.get("model_designation")
    if not isinstance(model, str) or not model.strip():
        return ["Отсутствует обозначение модели"]
    params = equipment.get("verified_parameters")
    if not isinstance(params, Mapping):
        return ["Нет подтверждённых параметров модели"]
    issues = []
    for name, unit in required_specs.items():
        problems = validate_verified_parameter(params.get(name), expected_model=model,
                                               expected_unit=unit)
        issues.extend(f"{name}: {problem}" for problem in problems)
    return issues
