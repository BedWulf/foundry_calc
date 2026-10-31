"""Audit provenance of standard designations separately from process assumptions."""
from __future__ import annotations


PROCESS_FIELDS = ("density_kg_m3", "melting_temp_C", "pouring_temp_C",
                  "shrinkage_pct", "burnout_pct")


def audit_alloy_references(alloys: dict, reference: dict) -> list[dict[str, str]]:
    findings = []
    sources = {s["id"]: s for s in reference.get("sources", [])}
    grades = {(g["category"], g["name"]): g for g in reference.get("grades", [])}
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
                                 "message": "Указанный ГОСТ не совпадает с проверенной маркой"})
        for field in PROCESS_FIELDS:
            if field in alloy:
                findings.append({"alloy_id": aid, "field": field,
                                 "code": "PROCESS_PROPERTY_UNVERIFIED",
                                 "message": "Значение требует отдельного источника и условий применения"})
    return findings
