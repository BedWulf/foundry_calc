"""Audit norm-backed alloy grade index and separate unverified process values."""
from __future__ import annotations

from collections.abc import Mapping


PROCESS_FIELDS = ("density_kg_m3", "melting_temp_C", "pouring_temp_C",
                  "shrinkage_pct", "burnout_pct")


def validate_grade_index(reference: dict) -> list[str]:
    """Reject missing provenance and duplicate labels, including legacy aliases."""
    errors: list[str] = []
    if not isinstance(reference, dict):
        return ["Каталог не является словарём"]
    sources = {}
    for source in reference.get("sources", []):
        if not isinstance(source, Mapping):
            errors.append("Неверная карточка ГОСТ")
            continue
        sid = source.get("id")
        if not sid or sid in sources:
            errors.append(f"Повторяющийся/пустой ID ГОСТ: {sid!r}")
        sources[sid] = source
        for key in ("designation", "title", "url", "text_url", "text_kind",
                    "evidence_scope"):
            if not source.get(key):
                errors.append(f"{sid}: не указан источник {key}")
        if not str(source.get("url", "")).startswith("https://protect.gost.ru/"):
            errors.append(f"{sid}: нет официального URL Росстандарта")
        if not str(source.get("text_url", "")).startswith("https://"):
            errors.append(f"{sid}: нет отдельного URL текста стандарта")
        if source.get("text_kind") != "third_party_reproduction":
            errors.append(f"{sid}: необходимо обозначить происхождение перепечатки")
    labels = set()
    for grade in reference.get("grades", []):
        if not isinstance(grade, Mapping):
            errors.append("Неверная запись марки")
            continue
        name = grade.get("name")
        category = grade.get("category")
        if grade.get("standard_id") not in sources:
            errors.append(f"{name}: неизвестный ГОСТ")
        if grade.get("verification_status") != "verified_designation_only":
            errors.append(f"{name}: статус не допускается")
        if not grade.get("evidence") or not grade.get("group"):
            errors.append(f"{name}: нет пункта или группы в стандарте")
        aliases = grade.get("aliases", [])
        if not isinstance(aliases, list) or any(
            not isinstance(a, str) or not a.strip() for a in aliases
        ):
            errors.append(f"{name}: некорректные альтернативные обозначения")
            continue
        for label in [name] + aliases:
            if not isinstance(label, str) or not label.strip():
                errors.append(f"Пустое обозначение {category}")
                continue
            key = (category, label)
            if key in labels:
                errors.append(f"Повтор обозначения {category}: {label}")
            labels.add(key)
    return errors


def audit_alloy_references(alloys: dict, reference: dict) -> list[dict[str, str]]:
    """Check old operating alloy identifiers; NEVER inherit physical parameters."""
    findings = []
    sources = {s["id"]: s for s in reference.get("sources", [])}
    grades = {}
    for grade in reference.get("grades", []):
        for label in [grade["name"]] + grade.get("aliases", []):
            grades[(grade["category"], label)] = grade
    for alloy in alloys.get("alloys", []):
        aid = alloy.get("id", "")
        grade = grades.get((alloy.get("category"), alloy.get("name")))
        if grade is None:
            findings.append({"alloy_id": aid, "field": "gost",
                             "code": "GRADE_NOT_VERIFIED",
                             "message": "Марка ещё не сопоставлена с текстом стандарта"})
        else:
            source = sources.get(grade["standard_id"], {})
            if alloy.get("gost") != source.get("designation"):
                findings.append({"alloy_id": aid, "field": "gost",
                                 "code": "STANDARD_MISMATCH",
                                 "message": "ГОСТ старой карточки не совпадает с нормативной записью; нужна миграция без подмены"})
        for field in PROCESS_FIELDS:
            if field in alloy:
                findings.append({"alloy_id": aid, "field": field,
                                 "code": "PROCESS_PROPERTY_UNVERIFIED",
                                 "message": "Значение требует отдельного источника и условий применения"})
    return findings
