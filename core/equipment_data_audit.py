"""Non-destructive audit of the molding-line equipment catalogue.

Validation is deliberately separate from selection: an undocumented specification
is reported, not silently changed or declared to be a manufacturer's passport.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path


CRITICAL_SPECS = (
    "flask_size_mm",
    "flask_heights_mm",
    "nominal_productivity_molds_h",
    "max_mold_metal_kg",
    "installed_power_kw",
)
SOURCE_TYPES = frozenset({
    "manufacturer_passport", "standard", "textbook",
    "diploma_example", "assumption", "unknown",
})
VERIFICATION_STATES = frozenset({"verified", "unverified", "disputed"})


def _positive_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def audit_molding_catalog(data: dict) -> list[dict[str, str]]:
    """Return actionable findings; never mutate the input catalogue."""
    findings: list[dict[str, str]] = []

    def report(code: str, equipment_id: str, field: str, detail: str) -> None:
        findings.append({
            "code": code, "equipment_id": equipment_id,
            "field": field, "message": detail,
        })

    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        return [{"code": "INVALID_CATALOG", "equipment_id": "",
                 "field": "lines", "message": "Ожидается список lines"}]

    seen: set[str] = set()
    for index, line in enumerate(data["lines"]):
        if not isinstance(line, dict):
            report("INVALID_LINE", str(index), "", "Карточка должна быть объектом")
            continue
        eid = line.get("id")
        if not isinstance(eid, str) or not eid.strip():
            eid = f"index:{index}"
            report("MISSING_ID", eid, "id", "Нет идентификатора модели")
        elif eid in seen:
            report("DUPLICATE_ID", eid, "id", "Повтор идентификатора модели")
        seen.add(eid)
        specs = line.get("specs")
        if not isinstance(specs, dict):
            report("MISSING_SPECS", eid, "specs", "Нет блока характеристик")
            continue
        for field in CRITICAL_SPECS:
            if field not in specs or specs[field] is None:
                report("MISSING_SPEC", eid, field, "Не заполнена критичная характеристика")
        size = specs.get("flask_size_mm")
        if size is not None:
            if not isinstance(size, str) or not re.fullmatch(
                r"\s*\d+\s*[xх×]\s*\d+\s*", size, re.IGNORECASE
            ) or any(int(v) <= 0 for v in re.findall(r"\d+", size)):
                report("INVALID_DIMENSIONS", eid, "flask_size_mm", "Нужны два размера опоки в мм")
        heights = specs.get("flask_heights_mm")
        if heights is not None and (
            not isinstance(heights, list) or not heights or
            any(not _positive_number(v) for v in heights)
        ):
            report("INVALID_HEIGHTS", eid, "flask_heights_mm", "Высоты должны быть положительными")
        for field in ("nominal_productivity_molds_h", "max_mold_metal_kg"):
            if field in specs and not _positive_number(specs[field]):
                report("INVALID_POSITIVE", eid, field, "Ожидается конечное число > 0")
        if "installed_power_kw" in specs and not _positive_number(specs["installed_power_kw"]):
            report("INVALID_POSITIVE", eid, "installed_power_kw", "Мощность должна быть > 0")
        mass = line.get("applicable_for", {}).get("casting_mass_range_kg") if isinstance(line.get("applicable_for"), dict) else None
        if mass is not None and (
            not isinstance(mass, list) or len(mass) != 2 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in mass) or
            mass[0] < 0 or mass[1] <= mass[0]
        ):
            report("INVALID_MASS_RANGE", eid, "casting_mass_range_kg", "Диапазон массы некорректен")

        provenance = line.get("provenance")
        if not isinstance(provenance, dict):
            report("MISSING_PROVENANCE", eid, "provenance", "Нет поэлементного происхождения данных")
            continue
        for field in CRITICAL_SPECS:
            record = provenance.get(field)
            if not isinstance(record, dict):
                report("MISSING_SOURCE", eid, field, "Не указан статус и источник характеристики")
                continue
            kind = record.get("source_type")
            status = record.get("verification_status")
            if kind not in SOURCE_TYPES or status not in VERIFICATION_STATES:
                report("INVALID_SOURCE_STATUS", eid, field, "Недопустимый тип/статус источника")
            if status == "verified" and (
                kind in (None, "unknown", "assumption", "diploma_example") or
                not record.get("source_document") or not record.get("source_page")
            ):
                report("UNSUPPORTED_VERIFIED", eid, field, "Нельзя считать проверенным без независимого документа и страницы")
            if status != "verified":
                report("UNVERIFIED_SOURCE", eid, field, "Характеристика не подтверждена первоисточником")
    return findings


def audit_catalog_file(path: str | Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as stream:
        return audit_molding_catalog(json.load(stream))
