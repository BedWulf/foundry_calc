"""Fail-closed evidence audit for foundry material and furnace calculations.

An exact grade designation in GOST does NOT certify physical process
properties in legacy alloys.json. Manufacturer reference melting rates are
reference-only until the operating conditions and exact equipment variant
are validated. This module does not invent missing values.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from config import DATA_DIR
from data.loader import DataLoader
from core.verified_equipment_gate import verify_equipment_for_selection

REQUIRED_MATERIAL_FIELDS = {
    "density_kg_m3": "кг/м³",
    "melting_temp_C": "°C",
    "pouring_temp_C": "°C",
    "shrinkage_pct": "%",
    "burnout_pct": "%",
}
REQUIRED_FURNACE_FIELDS = {
    "capacity_t": "т",
    "productivity_t_h": "т/ч",
}
FERROUS = frozenset({"steel", "cast_iron", "ductile_iron", "malleable_iron"})


def _source_complete(source: object, *, grade: str, field: str) -> bool:
    """Only accept explicit source evidence for this exact property and grade.

    A link/description alone is insufficient: actual conditions must be
    documented. Structural validation does not authenticate the document.
    """
    if not isinstance(source, Mapping):
        return False
    return (
        source.get("verification_status") == "verified"
        and source.get("grade") == grade
        and source.get("field") == field
        and source.get("source_type") in ("published_standard", "technical_reference")
        and isinstance(source.get("document_url"), str)
        and source["document_url"].startswith("https://")
        and all(isinstance(source.get(k), str) and source[k].strip()
                for k in ("document_title", "document_revision", "location",
                          "measurement_conditions"))
    )


def audit_calculation_sources(project: Any, melting_summary: Mapping | None = None,
                              data_dir: Path | None = None) -> list[str]:
    """Return blockers for a final engineering claim, not numerical guesses."""
    errors: list[str] = []
    data = DataLoader(Path(data_dir) if data_dir is not None else DATA_DIR)
    selected = getattr(project, "selected_alloy_id", "")
    if not isinstance(selected, str) or not selected:
        return ["Не указана марка материала, проверка свойств невозможна"]
    try:
        alloy = data.get_alloy(selected)
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        return [f"Невозможно проверить справочник сплавов: {exc}"]
    if not alloy:
        return [f"Марка {selected} отсутствует в расчётном справочнике"]
    grade, category = alloy.get("name"), alloy.get("category")
    if category not in FERROUS:
        return ["Выбранная марка вне текущей проверенной базы сталей и чугунов; "
                "технологические характеристики не сертифицированы"]
    evidence = alloy.get("field_provenance") or {}
    for field in REQUIRED_MATERIAL_FIELDS:
        if field not in alloy:
            errors.append(f"{grade}: отсутствует технологическое поле {field}")
        elif not _source_complete(evidence.get(field), grade=grade, field=field):
            errors.append(f"{grade}: нет подтверждённого источника и условий для {field}")
    melting = melting_summary or {}
    if melting:
        name = melting.get("furnace_name") or melting.get("model_designation")
        if not isinstance(name, str) or not name.strip():
            errors.append("Плавильное отделение: не выбрана модель печи")
        else:
            verified = {
                "model_designation": melting.get("model_designation"),
                "verified_parameters": melting.get("verified_parameters"),
            }
            for issue in verify_equipment_for_selection(verified, REQUIRED_FURNACE_FIELDS):
                errors.append(f"Печь {name}: {issue}")
    return errors
